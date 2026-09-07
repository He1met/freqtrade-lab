#!/usr/bin/env python3
"""Explicit structure-only preparation. Run one manifest only after external batch approval."""
import argparse
from decimal import localcontext
import json
from pathlib import Path
import signal
import subprocess
import sys
import traceback
from contextlib import contextmanager

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from lab.portfolio_observed_prepare import (ROOT,PREPARED,ACTIVATION,NATIVE_SOURCE,RUNTIME_ROOT,
    prepare,verify_prepared,encoded,sha)
from lab.portfolio_observed_budget import locked_observed
from lab.portfolio_budget import verify_anchor,checkpoint_budget
from lab.portfolio_source import SourceError
from lab.portfolio_observed_integrity import controlled_hashes,freeze,terminal_audit
from lab.portfolio_observed_budget import validate_activation


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


class NativeDeadline(BaseException):
    """Cannot be swallowed by native strategy-safe wrappers catching Exception."""


@contextmanager
def deadline(seconds):
    def expired(*args):raise NativeDeadline(f'fixed {seconds} second native job deadline expired')
    def interrupted(*args):raise KeyboardInterrupt('native job interrupted')
    if signal.getitimer(signal.ITIMER_REAL)!=(0.0,0.0):
        raise SourceError('unbound outer timer prohibited')
    oldalarm=signal.signal(signal.SIGALRM,expired)
    oldterm=signal.signal(signal.SIGTERM,interrupted)
    signal.setitimer(signal.ITIMER_REAL,seconds)
    try:yield
    finally:
        signal.setitimer(signal.ITIMER_REAL,0)
        signal.signal(signal.SIGALRM,oldalarm);signal.signal(signal.SIGTERM,oldterm)


def execute_reserved(root,key,manifest,budget,before):
    """All outcomes audit the original frozen identities before a terminal row."""
    status='FAILED';candidate=None;failure=None
    try:
        with deadline(manifest['native_timeout_seconds']):
            before['files'][str(budget.path)]=sha(budget.path)
            (root/'pre-call-integrity.json').write_bytes(encoded(before))
            checkpoint_budget()
            candidate=run_native(root,manifest)
        status='SUCCEEDED'
    except BaseException as exc:
        failure=dict(type=type(exc).__name__,message=str(exc),traceback=traceback.format_exc())
        if isinstance(exc,(KeyboardInterrupt,NativeDeadline)):status='INTERRUPTED'
    # Integrity review must run after BOTH a returned candidate and an exception.
    try:
        audit=terminal_audit(before)
        verify_anchor()
    except BaseException as exc:
        audit=dict(status='CONTROL_INTEGRITY',error=f'{type(exc).__name__}: {exc}',
                   traceback=traceback.format_exc(),before=before)
    (root/'terminal-integrity.json').write_bytes(encoded(audit))
    if audit['status']!='PASS':
        status='FAILED'
        result=dict(status='CONTROL_INTEGRITY',economic_output=None,
                    economic_qualification='NO_REAL_ECONOMIC_QUALIFICATION',exception=failure)
    elif status!='SUCCEEDED':
        result=dict(status='INTERRUPTED' if status=='INTERRUPTED' else 'MODEL_INVALID',
                    economic_output=None,economic_qualification='NO_REAL_ECONOMIC_QUALIFICATION',exception=failure)
    else:result=candidate
    # A drifted candidate is never published as an economic result. Raw native
    # artifacts and traces stay explicitly untrusted for forensic review.
    (root/'result.json').write_bytes(encoded(result))
    if failure:(root/'exception.json').write_bytes(encoded(failure))
    evidence={str(p.relative_to(root)):sha(p) for p in sorted(root.rglob('*')) if p.is_file()}
    (root/'evidence-index.json').write_bytes(encoded(dict(key=key,manifest_sha256=sha(root/'manifest.json'),
        status=status,files=evidence,economic_qualification='NO_REAL_ECONOMIC_QUALIFICATION')))
    budget.finish(key,status,sha(root/'evidence-index.json'));checkpoint_budget()
    return dict(status=status,root=str(root),result_sha256=sha(root/'result.json'))


def run(key):
    # Read-only early checks; repeat identities and anchor within the same lock
    # as reservation. No approval creation or per-job override is exposed.
    activation_raw=ACTIVATION.read_bytes();activation=json.loads(activation_raw)
    plan_raw=(PREPARED/'plan.json').read_bytes();plan=json.loads(plan_raw)
    if key not in plan['first_batch']:raise SourceError('unknown or sealed key')
    mpath=Path(plan['first_batch'][key]['path']);raw=mpath.read_bytes();manifest=json.loads(raw)
    if sha(mpath)!=plan['first_batch'][key]['sha256']:raise SourceError('prepared job SHA drift')
    validate_activation(activation,plan,plan_raw)
    verify_prepared(PREPARED,manifest);verify_anchor()
    root=RUNTIME_ROOT/'observed-jobs'/mpath.stem
    with locked_observed(RUNTIME_ROOT,activation,plan,plan_raw) as budget:
        verify_anchor()
        if (ACTIVATION.read_bytes()!=activation_raw or (PREPARED/'plan.json').read_bytes()!=plan_raw or
            mpath.read_bytes()!=raw):raise SourceError('CONTROL_INTEGRITY lock-time activation/plan/manifest drift')
        validate_activation(json.loads(ACTIVATION.read_bytes()),plan,plan_raw)
        verify_prepared(PREPARED,manifest)
        expected=controlled_hashes(mpath,manifest,raw,activation_raw,plan_raw)
        before=freeze(expected,expected)
        if before['project']['commit']!=activation['code_commit']:
            raise SourceError('run requires exact reviewed execution commit')
        if root.exists():raise SourceError('output already exists; no overwrite or replay')
        root.mkdir(parents=True)
        (root/'manifest.json').write_bytes(raw)
        before['files'][str(root/'manifest.json')]=sha(root/'manifest.json')
        budget.reserve_observed(key,raw)
        return execute_reserved(root,key,manifest,budget,before)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare',action='store_true')
    parser.add_argument('--run-key')
    args=parser.parse_args()
    if args.prepare==bool(args.run_key):parser.error('choose --prepare or --run-key; run needs external activation')
    result=prepare() if args.prepare else run(args.run_key)
    print(encoded(result).decode())
    if args.run_key and result['status']!='SUCCEEDED':raise SystemExit(2)


if __name__=='__main__':main()
