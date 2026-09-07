#!/usr/bin/env python3
"""Explicit structure-only preparation. Run one manifest only after external batch approval."""
import argparse
from decimal import localcontext
import json
from pathlib import Path
import signal
import subprocess
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from lab.portfolio_observed_prepare import (ROOT,PREPARED,ACTIVATION,NATIVE_SOURCE,RUNTIME_ROOT,
    prepare,verify_prepared,encoded,sha)
from lab.portfolio_observed_budget import locked_observed
from lab.portfolio_budget import verify_anchor,checkpoint_budget
from lab.portfolio_source import SourceError


def run_native(root,manifest):
    """Only called after durable shared-budget reservation and checkpoint."""
    sys.path.insert(0,str(NATIVE_SOURCE))
    def no_network(event,args):
        if event in ('socket.connect','socket.getaddrinfo','socket.bind'):
            raise SourceError('observed native network prohibited')
    sys.addaudithook(no_network)
    import freqtrade
    if Path(freqtrade.__file__).resolve()!=(NATIVE_SOURCE/'freqtrade/__init__.py').resolve():
        raise SourceError('native import path mismatch')
    from freqtrade.commands.optimize_commands import setup_optimize_configuration
    from freqtrade.enums import RunMode
    from freqtrade.exchange.binance import Binance
    from lab.portfolio_observed_native import ObservedBacktesting
    for name in ('user','exports'):(root/name).mkdir()
    config_path=root/'config.json';config_path.write_bytes(encoded(manifest['config']))
    config=setup_optimize_configuration(dict(command='backtesting',config=[str(config_path)],
        datadir=str(PREPARED/'data'),user_data_dir=str(root/'user'),strategy_path=str(ROOT/'lab'),
        strategy='PortfolioObserved',timerange=manifest['native_timerange'],fee=manifest['config']['fee'],
        export='trades',exportdirectory=str(root/'exports'),dataformat_ohlcv='feather',
        disableparamexport=True,backtest_cache='none'),RunMode.BACKTEST)
    assembly=json.loads((PREPARED/'assembly.json').read_bytes())
    exchange=Binance(config,validate=False,load_leverage_tiers=False)
    def deny(*a,**k):raise SourceError('native exchange request prohibited')
    exchange._api.fetch=deny;exchange._api_async.fetch=deny
    exchange._api.set_markets(assembly['markets'],{});exchange._api_async.set_markets(assembly['markets'],{})
    exchange._markets=exchange._api.markets;exchange._leverage_tiers=assembly['tiers']
    bt=None;strategy=None
    try:
        bt=ObservedBacktesting(config,exchange=exchange)
        if len(bt.strategylist)!=1 or set(bt.pairlists.whitelist)!=set(manifest['config']['exchange']['pair_whitelist']):
            raise SourceError('one strategy/account and exact two pairs required')
        strategy=bt.strategylist[0]
        with localcontext() as context:
            context.prec=60
            bt.start()
            result=strategy.finalize_model()
        result.update(native_calls=1,artifact_sha256={p.name:sha(p) for p in (root/'exports').glob('*.zip')},
                      natural_cluster_gate='NOT_EVALUATED_NO_QUALIFICATION',independent_confirmation='SEALED_NOT_AUTHORIZED')
        if len(result['artifact_sha256'])!=1:raise SourceError('requires retained native archive')
        return result
    finally:
        # Raw traces may be retained on failure, but never passed off as scored results.
        if strategy is not None and hasattr(strategy,'trace'):
            (root/'trace.json').write_bytes(encoded(strategy.trace))
            (root/'risk-events.json').write_bytes(encoded(strategy.book.points))
            (root/'episode-events.json').write_bytes(encoded(strategy.episode_events))
            (root/'actual-orders.json').write_bytes(encoded(strategy.last_orders))
            (root/'position-cycles.json').write_bytes(encoded(strategy.position_cycles))
        if bt is not None:bt.cleanup()
        exchange.close()


def run(key):
    # No implicit activation creation or flag that bypasses the approval record.
    activation=json.loads(ACTIVATION.read_bytes())
    plan_raw=(PREPARED/'plan.json').read_bytes();plan=json.loads(plan_raw)
    if key not in plan['first_batch']:raise SourceError('unknown or sealed key')
    mpath=Path(plan['first_batch'][key]['path']);raw=mpath.read_bytes();manifest=json.loads(raw)
    if sha(mpath)!=plan['first_batch'][key]['sha256']:raise SourceError('prepared job SHA drift')
    def git(*args):return subprocess.check_output(['git','-C',str(ROOT),*args],text=True).strip()
    if git('status','--porcelain','--untracked-files=all') or git('rev-parse','HEAD')!=activation.get('code_commit'):
        raise SourceError('run requires exact reviewed clean execution commit')
    verify_prepared(PREPARED,manifest);verify_anchor()
    root=RUNTIME_ROOT/'observed-jobs'/mpath.stem
    with locked_observed(RUNTIME_ROOT,activation,plan,plan_raw) as budget:
        if root.exists():raise SourceError('output already exists; no overwrite or replay')
        root.mkdir(parents=True)
        (root/'manifest.json').write_bytes(raw)
        budget.reserve_observed(key,raw)
        status='FAILED';result={'status':'MODEL_INVALID','economic_qualification':'NO_REAL_ECONOMIC_QUALIFICATION'}
        def interrupted(*args):raise KeyboardInterrupt('native job interrupted')
        oldterm=signal.signal(signal.SIGTERM,interrupted)
        try:
            checkpoint_budget()
            result=run_native(root,manifest);status='SUCCEEDED'
        except BaseException as exc:
            result.update(error=f'{type(exc).__name__}: {exc}')
            if isinstance(exc,KeyboardInterrupt):status='INTERRUPTED'
        finally:
            signal.signal(signal.SIGTERM,oldterm)
            (root/'result.json').write_bytes(encoded(result))
            evidence={str(p.relative_to(root)):sha(p) for p in sorted(root.rglob('*')) if p.is_file()}
            (root/'evidence-index.json').write_bytes(encoded(dict(key=key,manifest_sha256=sha(root/'manifest.json'),
                status=status,files=evidence,economic_qualification='NO_REAL_ECONOMIC_QUALIFICATION')))
            budget.finish(key,status,sha(root/'evidence-index.json'));checkpoint_budget()
        return dict(status=status,root=str(root),result_sha256=sha(root/'result.json'))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare',action='store_true')
    parser.add_argument('--run-key')
    args=parser.parse_args()
    if args.prepare==bool(args.run_key):parser.error('choose --prepare or --run-key; run needs external activation')
    print(encoded(prepare() if args.prepare else run(args.run_key)).decode())


if __name__=='__main__':main()
