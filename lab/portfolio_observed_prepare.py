"""Deterministic source conversion and job manifests; never activates a call."""
from datetime import datetime, timedelta
from dataclasses import is_dataclass,asdict
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
import hashlib
import importlib.metadata
import json
import subprocess
import sys

from lab.portfolio_budget import canonical, RUNTIME_ROOT
from lab.portfolio_causal import PAIRS
from lab.portfolio_observed_source import ROOT, RECEIPT_SHA, START, END, load_view, funding_records
from lab.portfolio_short import configuration
from lab.portfolio_source import SourceError

SEMANTICS = ROOT/'docs/protocols/issue125-observed-semantics-v3.json'
SEMANTICS_SHA = '3f28c163e41b6b94d70bf2de342a38929860052f86a23d689195a3b7dc670da9'
SHORT = ROOT/'docs/protocols/issue121-short-feasibility-v2.json'
NATIVE_SOURCE = Path('/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue-43-profile-driven-v1/freqtrade')
NATIVE_SHA = '52bc96f4480b1a0da6a9b455bd00b17fbb6786a5'
BUDGET_PREFIX_SHA = 'a828469373802b7296a19d15bb79735d3adf30ca31c7201e4ff881b59e969e18'
PREPARED = RUNTIME_ROOT/'issue125-observed-prepared'
ACTIVATION = RUNTIME_ROOT/'observed-v3-activation.json'
DEPENDENCIES = {'freqtrade':'2026.7','ccxt':'4.5.68','pandas':'3.0.3','pyarrow':'25.0.0'}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def serial(value):
    if is_dataclass(value):return serial(asdict(value))
    if isinstance(value, (datetime, Decimal)):return str(value)
    if isinstance(value, Fraction):return {'numerator':value.numerator,'denominator':value.denominator}
    if isinstance(value, dict):return {str(k):serial(v) for k,v in value.items()}
    if isinstance(value, (tuple,list)):return [serial(v) for v in value]
    return value


def encoded(value):return canonical(serial(value))


def verify_semantics():
    if sha(SEMANTICS)!=SEMANTICS_SHA:raise SourceError('observed semantics SHA drift')
    return json.loads(SEMANTICS.read_bytes())


def jobs():
    return json.loads(SHORT.read_bytes())['budget']['jobs']


def environment():
    if sys.version.split()[0]!='3.13.13' or any(importlib.metadata.version(k)!=v for k,v in DEPENDENCIES.items()):
        raise SourceError('locked native environment differs')
    def git(*args):return subprocess.check_output(['git','-C',str(NATIVE_SOURCE),*args],text=True).strip()
    if git('rev-parse','HEAD')!=NATIVE_SHA or git('status','--porcelain','--untracked-files=all'):
        raise SourceError('native source must be fixed clean commit')
    return dict(source_commit=NATIVE_SHA,source_tree=git('rev-parse','HEAD^{tree}'),python='3.13.13',
                interpreter=sys.executable,interpreter_sha256=sha(sys.executable),packages=DEPENDENCIES)


def code_files():
    # All importable project code is bound, not just the directly named adapter.
    paths = sorted(set(ROOT.glob('lab/*.py'))|set(ROOT.glob('scripts/*.py'))|
                   set(ROOT.glob('docs/protocols/*.json')))
    return {str(p.relative_to(ROOT)):sha(p) for p in paths}


def native_config(mode,cost):
    c=configuration(mode,cost)
    return dict(max_open_trades=2,stake_currency='USDT',stake_amount='unlimited',
        tradable_balance_ratio=1.,fiat_display_currency='USD',dry_run=True,dry_run_wallet=1000.,
        cancel_open_orders_on_exit=False,trading_mode='futures',margin_mode='isolated',
        timeframe='1h',fee=float(c['fee']),unfilledtimeout={'entry':10,'exit':30,'exit_timeout_count':0,'unit':'minutes'},
        entry_pricing={'price_side':'other','use_order_book':True,'order_book_top':1},
        exit_pricing={'price_side':'other','use_order_book':True,'order_book_top':1},
        exchange={'name':'binance','enable_ws':False,'pair_whitelist':list(PAIRS),'pair_blacklist':[]},
        pairlists=[{'method':'StaticPairList'}],strategy='PortfolioObserved',dataformat_ohlcv='feather',
        disableparamexport=True,backtest_cache='none',
        order_types={'entry':'market','exit':'market','stoploss':'market','stoploss_on_exchange':False},
        observed_mode=mode,observed_cost=cost,observed_source_sha256=RECEIPT_SHA,
        observed_semantics_sha256=SEMANTICS_SHA)


def market_assembly(view):
    markets=[];tiers={}
    tier=verify_semantics()['engine_only_tier_assumption']
    for pair in PAIRS:
        base=pair.split('/')[0];info=view.metadata[pair]
        fs={f['filterType']:f for f in info['filters']};lot=fs['MARKET_LOT_SIZE'];price=fs['PRICE_FILTER']
        markets.append(dict(id=base+'USDT',symbol=pair,base=base,quote='USDT',settle='USDT',
            baseId=base,quoteId='USDT',settleId='USDT',active=True,contract=True,swap=True,
            spot=False,future=False,option=False,linear=True,inverse=False,type='swap',contractSize=1.,expiry=None,
            precision={'amount':float(lot['stepSize']),'price':float(price['tickSize'])},
            limits={'amount':{'min':float(lot['minQty']),'max':float(lot['maxQty'])},
                    'price':{'min':float(price['minPrice']),'max':float(price['maxPrice'])},
                    'cost':{'min':float(fs['MIN_NOTIONAL']['notional']),'max':None},
                    'leverage':{'min':1.,'max':1.}},maker=.0006,taker=.0006,info={}))
        tiers[pair]=[{k:float(tier[k]) for k in ('minNotional','maxNotional','maintenanceMarginRate','maxLeverage','maintAmt')}]
    return dict(markets=markets,tiers=tiers,historical_rules_verified=False)


def convert(view,directory):
    """Structure only: original OHLCV into native files, no score or matching."""
    sys.path.insert(0,str(NATIVE_SOURCE))
    import pandas as pd
    import freqtrade
    if Path(freqtrade.__file__).resolve()!=(NATIVE_SOURCE/'freqtrade/__init__.py').resolve():
        raise SourceError('conversion native import path mismatch')
    from freqtrade.enums import CandleType
    from freqtrade.data.history.datahandlers import get_datahandler
    if view.source_sha!=RECEIPT_SHA or view.kind!='OBSERVED_API_COMPLETE_FOR_EXPLORATORY_MODEL':
        raise SourceError('synthetic or unapproved source prohibited')
    directory.mkdir()
    handler=get_datahandler(directory,'feather')
    for pair in PAIRS:
        frame=pd.DataFrame([dict(date=t,open=b.open,high=b.high,low=b.low,close=b.close,volume=view.volumes[pair][t])
                            for t,b in view.hourly[pair].items()])
        if len(frame)!=8784 or frame.date.max()>=END:raise SourceError('explore conversion coverage')
        handler.ohlcv_store(pair,'1h',frame,CandleType.FUTURES)
    return {str(p.relative_to(directory)):sha(p) for p in sorted(directory.rglob('*.feather'))}


def prepare(root=PREPARED):
    """New output only. The caller must use the pinned interpreter; no native call."""
    root=Path(root)
    if root.exists():raise SourceError('prepared output already exists; never overwrite')
    env=environment();sem=verify_semantics();view=load_view()
    raw=(RUNTIME_ROOT/'calls.jsonl').read_bytes()
    if hashlib.sha256(raw).hexdigest()!=BUDGET_PREFIX_SHA:raise SourceError('native budget changed before preparation')
    if ACTIVATION.exists():raise SourceError('activation already exists; preparation cannot change it')
    root.mkdir(parents=True)
    files=convert(view,root/'data');assembly=market_assembly(view)
    (root/'assembly.json').write_bytes(encoded(assembly))
    event_table={p:funding_records(view,p) for p in PAIRS}
    (root/'events.json').write_bytes(encoded(event_table))
    bundle=code_files()
    common=dict(schema='issue125-observed-job-v1',status='PREPARED_NOT_AUTHORIZED',
        source_receipt_sha256=RECEIPT_SHA,semantics_sha256=SEMANTICS_SHA,
        source_grade=view.kind,source_view_start='2023-11-01T00:00:00Z',
        source_view_end_exclusive=END.isoformat(),data_files=files,
        funding_event_table_sha256=sha(root/'events.json'),funding_counts={p:len(event_table[p]) for p in PAIRS},
        assembly_sha256=sha(root/'assembly.json'),environment=env,code_files=bundle,
        code_bundle_sha256=hashlib.sha256(encoded(bundle)).hexdigest(),
        native_budget_prefix_sha256=BUDGET_PREFIX_SHA,native_budget_prefix_bytes=len(raw),
        native_calls=1,continuous_risk_coverage='UNKNOWN',economic_qualification=sem['economic_qualification'])
    manifests={};sealed=[]
    (root/'jobs').mkdir()
    for i,job in enumerate(jobs()):
        if i>=10:
            sealed.append({**job,'input_sha256':None,'status':'SEALED_NOT_PREPARED'})
            continue
        config=native_config(job['mode'],job['cost'])
        manifest=dict(common,key=job['key'],replaces_unused_key_on_approval=job['replaces_unused_key_on_approval'],
            command=[sys.executable,str(ROOT/'scripts/run_portfolio_observed.py'),'--run-key',job['key']],
            wrappers=[],output_root=str(RUNTIME_ROOT/'observed-jobs'/f'{i+1:02d}'),prepared_root=str(root),
            mode=job['mode'],cost=job['cost'],config=config,config_sha256=hashlib.sha256(encoded(config)).hexdigest(),
            native_timerange=f'{int((START-timedelta(hours=3)).timestamp())}-{int(END.timestamp())}',
            score_start=START.isoformat(),score_end_exclusive=END.isoformat(),final_flat_at=(END-timedelta(hours=1)).isoformat(),
            selection=configuration(job['mode'],job['cost'])['selection'])
        path=root/'jobs'/f'{i+1:02d}.json';path.write_bytes(encoded(manifest));manifests[job['key']]=dict(path=str(path),sha256=sha(path))
    plan=dict(schema='issue125-observed-plan-v1',status='PREPARED_NOT_AUTHORIZED',
        native_total=96,consumed=8,proposed_jobs=20,unallocated_after_activation=68,
        native_budget_prefix_bytes=len(raw),native_budget_prefix_sha256=BUDGET_PREFIX_SHA,
        semantics_sha256=SEMANTICS_SHA,source_receipt_sha256=RECEIPT_SHA,
        first_batch=manifests,reserved=sealed,
        replacement_map={j['key']:j['replaces_unused_key_on_approval'] for j in jobs()},
        activation_authority=None,native_calls_executed=0)
    (root/'plan.json').write_bytes(encoded(plan))
    return dict(prepared_root=str(root),plan_sha256=sha(root/'plan.json'),first_batch_jobs=10,sealed_jobs=10,
                native_calls=0,new_gets=0,data_files=files)


def verify_prepared(root,manifest):
    root=Path(root);verify_semantics()
    if manifest['source_receipt_sha256']!=RECEIPT_SHA or manifest['semantics_sha256']!=SEMANTICS_SHA:
        raise SourceError('manifest source/semantics mismatch')
    if manifest['code_files']!=code_files():raise SourceError('code bundle drift')
    if manifest['environment']!=environment():raise SourceError('environment drift')
    view=load_view()  # All original raw SHA/coverage before reservation.
    if sha(root/'events.json')!=manifest['funding_event_table_sha256'] or (root/'events.json').read_bytes()!=encoded({p:funding_records(view,p) for p in PAIRS}):
        raise SourceError('direct funding event view drift')
    if sha(root/'assembly.json')!=manifest['assembly_sha256'] or (root/'assembly.json').read_bytes()!=encoded(market_assembly(view)):
        raise SourceError('frozen market/tier assembly drift')
    actual={str(p.relative_to(root/'data')):sha(p) for p in (root/'data').rglob('*.feather')}
    if actual!=manifest['data_files']:raise SourceError('native data view drift')
    expected=next((j for j in jobs()[:10] if j['key']==manifest['key']),None)
    if (expected is None or manifest['config']!=native_config(expected['mode'],expected['cost']) or
        manifest['mode']!=expected['mode'] or manifest['cost']!=expected['cost'] or
        manifest['native_timerange']!=f'{int((START-timedelta(hours=3)).timestamp())}-{int(END.timestamp())}' or
        manifest['score_start']!=START.isoformat() or manifest['score_end_exclusive']!=END.isoformat() or
        manifest['final_flat_at']!=(END-timedelta(hours=1)).isoformat() or
        manifest['source_grade']!='OBSERVED_API_COMPLETE_FOR_EXPLORATORY_MODEL'):
        raise SourceError('sealed or config drift')
    return view
