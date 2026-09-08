"""Native consumer acceptance of immutable observed intents; never a trading bot."""
from pathlib import Path
from datetime import timedelta
import hashlib
import json
import math

REPO=Path(__file__).resolve().parents[1]
PROTOCOL=REPO/'docs/protocols/perp-forward-native-acceptance-v1.json'
PAIRS=('BTC/USDT:USDT','ETH/USDT:USDT')


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read(path):return json.loads(Path(path).read_text())
def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,default=str).encode()).hexdigest()


def capture_files(seed_root,incremental_root,start,end):
    from lab.perp_forward_signal import dt
    files={};roots=[]
    for root in [Path(seed_root)]+sorted(p.parent for p in Path(incremental_root).glob('*/receipt.json')):
        receipt_path=root/'receipt.json';receipt=read(receipt_path)
        if dt(receipt['window_start'])>=end or dt(receipt['window_end_exclusive'])<start-timedelta(days=8):continue
        if receipt.get('exchange')!='binance':raise ValueError('wrong capture exchange')
        roots.append(str(root.resolve()));files[str(receipt_path.resolve())]=sha(receipt_path)
        for pair in PAIRS:
            for kind in ('ohlcv','mark','funding','premium'):
                name=pair.split('/')[0]+'USDT-'+kind;item=receipt.get('datasets',{}).get(name)
                if item is None:continue
                path=(root/item['path']).resolve()
                if not path.is_relative_to(root.resolve()) or sha(path)!=item['sha256']:raise ValueError('capture digest/path differs')
                files[str(path)]=sha(path)
        rules=root/'instrument-rules.json'
        if rules.exists():files[str(rules.resolve())]=sha(rules)
    return roots,files


def source_pools(files,source_at,observed_at):
    """Read only the exact immutable files referenced by a persisted intent."""
    from lab.perp_forward_signal import dt,encoded
    pools={(p,k):{} for p in PAIRS for k in ('ohlcv','funding','premium')}
    for name,expected in files.items():
        path=Path(name)
        if sha(path)!=expected:raise ValueError('observed source drift: '+name)
        if path.suffix!='.jsonl':continue
        for pair,kind in pools:
            if path.name!=pair.split('/')[0]+'USDT-'+kind+'.jsonl':continue
            for row in (json.loads(line) for line in path.read_text().splitlines() if line.strip()):
                event=dt(row['event_time']);fetched=dt(row['fetched_at'])
                if not source_at-timedelta(hours=169)<=event<=source_at+timedelta(hours=1):continue
                declared=dt(row.get('historical_available_at_assumption',row['available_at']))
                floor=event+timedelta(hours=1,seconds=0 if kind=='funding' else 60)
                if declared<floor:raise ValueError('publication violates frozen lag')
                effective=max(dt(row['available_at']),fetched,declared)
                if effective>observed_at:continue
                value=dict(row,event=event,fetched=fetched,declared=declared,effective=effective,
                    row_sha256=hashlib.sha256(encoded(row)).hexdigest())
                prior=pools[pair,kind].get(event)
                if prior and prior['fetched']==fetched and prior['row_sha256']!=value['row_sha256']:raise ValueError('same-time revision collision')
                if prior is None or fetched>prior['fetched']:pools[pair,kind][event]=value
    return pools


def snapshot(seed_root,incremental_root,signal_root,registration,protocol,binding,now):
    """Pure snapshot content; callers explicitly freeze it only after readiness."""
    from lab.perp_forward_signal import dt,control
    p=read(PROTOCOL);start=dt(p['window_start']);end=dt(p['window_end_exclusive'])
    if now<dt(p['earliest_ready_at']):raise ValueError('WAITING_DATA: fixed interval/publication gate not reached')
    _,_,_,identity=control(registration,protocol,binding)
    roots,files=capture_files(seed_root,incremental_root,start,end)
    records=[];at=start
    while at<end:
        key=at.strftime('%Y%m%dT%H00Z');raw=Path(signal_root)/'hours'/(key+'.intent.json');rec=Path(signal_root)/'hours'/(key+'.receipt.json')
        if not raw.exists() or not rec.exists():
            records.append(dict(planned_entry=at.isoformat(),missing=True));at+=timedelta(hours=1);continue
        intent=read(raw);receipt=read(rec)
        if receipt.get('intent_sha256')!=sha(raw) or intent['identity']!=identity or receipt['identity']!=identity:raise ValueError('intent identity/durable SHA mismatch')
        if dt(intent['planned_entry'])!=at or receipt.get('phase')!='PRE_CONFIRMATION':raise ValueError('wrong intention phase/window')
        for name,d in intent['source_bindings'].items():
            if name in files and files[name]!=d:raise ValueError('source snapshot collision')
            files[name]=d
        files[str(raw.resolve())]=sha(raw);files[str(rec.resolve())]=sha(rec)
        records.append(dict(planned_entry=at.isoformat(),intent=intent,receipt=receipt))
        at+=timedelta(hours=1)
    return dict(schema='perp-native-intent-snapshot-v1',identity=identity,signal_root=str(Path(signal_root).resolve()),
        start=start.isoformat(),end=end.isoformat(),frozen_observed_at=now.isoformat(),capture_roots=roots,
        source_files=files,records=records)


def decode(snap):
    """Validate retained intent conditions; prepare native data without running it."""
    import pandas as pd
    from lab.perp_forward_signal import dt,intent as compute_intent
    for name,d in snap['source_files'].items():
        if sha(name)!=d:raise ValueError('frozen source/intent changed: '+name)
    start=dt(snap['start']);end=dt(snap['end']);now=dt(snap['frozen_observed_at'])
    spec=read(PROTOCOL)
    if start!=dt(spec['window_start']) or end!=dt(spec['window_end_exclusive']) or now<dt(spec['earliest_ready_at']):raise ValueError('fixed interval/publication gate differs')
    # The capture receipt proves the bounded endpoint query completed. No
    # settlement cadence is invented from a last observed rate or empty hour.
    funding_coverage={p:[] for p in PAIRS}
    for rootname in snap['capture_roots']:
        path=(Path(rootname)/'receipt.json').resolve()
        if str(path) not in snap['source_files']:raise ValueError('capture receipt unbound')
        receipt=read(path)
        for pair in PAIRS:
            name=pair.split('/')[0]+'USDT-funding';item=receipt.get('datasets',{}).get(name)
            if item is None or name in receipt.get('errors',{}):continue
            source=(path.parent/item['path']).resolve()
            if snap['source_files'].get(str(source))!=item.get('sha256'):raise ValueError('funding query/source binding differs')
            if len([x for x in source.read_text().splitlines() if x.strip()])!=item['rows']:raise ValueError('funding query row count differs')
            funding_coverage[pair].append((dt(receipt['window_start']),dt(receipt['window_end_exclusive'])))
    for pair in PAIRS:
        cursor=start
        for lo,hi in sorted(funding_coverage[pair]):
            if lo<=cursor:cursor=max(cursor,hi)
        if cursor<end:raise ValueError('funding query coverage incomplete; absence is not zero')
    allrows={(p,k):{} for p in PAIRS for k in ('ohlcv','mark','funding')};rules=None
    for rootname in snap['capture_roots']:
        root=Path(rootname)
        if rules is None and str((root/'instrument-rules.json').resolve()) in snap['source_files']:rules=read(root/'instrument-rules.json')['symbols']
        for pair,kind in allrows:
            path=root/(pair.split('/')[0]+'USDT-'+kind+'.jsonl')
            if str(path.resolve()) not in snap['source_files']:continue
            for row in (json.loads(x) for x in path.read_text().splitlines() if x.strip()):
                at=dt(row['event_time']);fetched=dt(row['fetched_at'])
                if max(fetched,dt(row['available_at']))>now or at>=end or at<start-timedelta(days=8):continue
                prior=allrows[pair,kind].get(at)
                if prior is None or fetched>dt(prior['fetched_at']):allrows[pair,kind][at]=row
    frames={};marks={};events={};factors={};intents={};omitted=[];complete_hours=0;signals=0
    if rules is None:raise ValueError('instrument specifications missing')
    if any(not allrows[p,k] for p in PAIRS for k in ('ohlcv','mark')):raise ValueError('execution or mark series absent')
    common_start=max(min(allrows[p,kind]) for p in PAIRS for kind in ('ohlcv','mark'))
    for pair in PAIRS:
        expected=pd.date_range(common_start,end,freq='1h',inclusive='left')
        if common_start>start-timedelta(hours=170):raise ValueError('insufficient causal warmup')
        for kind,target in (('ohlcv',frames),('mark',marks)):
            values=allrows[pair,kind]
            if set(values)!=set(expected):raise ValueError('missing execution/mark hour; no native filling allowed')
            target[pair]=pd.DataFrame([dict(date=at,**{c:float(values[at][c]) for c in ('open','high','low','close')},volume=float(values[at]['volume']) if kind=='ohlcv' else 0.) for at in expected])
            for r in target[pair].itertuples():
                if (any(not math.isfinite(v) or v<=0 for v in (r.open,r.high,r.low,r.close)) or
                        r.high<max(r.open,r.close,r.low) or r.low>min(r.open,r.close,r.high) or
                        not math.isfinite(r.volume) or r.volume<0):raise ValueError('invalid execution price/volume')
        rows=allrows[pair,'funding']
        if not rows:raise ValueError('funding history missing')
        events[pair]=pd.DataFrame([dict(date=at,open_fund=float(row['rate']),open_mark=float(row['mark_price'])) for at,row in sorted(rows.items())])
        if any(not math.isfinite(r.open_fund) or not math.isfinite(r.open_mark) or r.open_mark<=0 for r in events[pair].itertuples()):raise ValueError('invalid settlement amount/mark')
        table=pd.DataFrame(dict(date=expected,funding_rate=float('nan'),premium_close=float('nan'),factor_valid=False))
        for column in ('funding_event_at','funding_available_at','premium_available_at','decision_at'):table[column]=pd.Series(pd.NaT,index=table.index,dtype='datetime64[ns, UTC]')
        factors[pair]=table
    for record in snap['records']:
        planned=dt(record['planned_entry']);key=planned.isoformat();intents[key]={}
        if record.get('missing'):
            omitted.append(dict(at=key,pairs=list(PAIRS),reason='MISSING_RECEIPT'));continue
        raw=record['intent'];rec=record['receipt'];source=dt(raw['source_candle']);observed=dt(raw['observed_at'])
        from lab.perp_forward_signal import encoded
        if hashlib.sha256(encoded(raw['source_bindings'])).hexdigest()!=raw['source_bundle_sha256']:raise ValueError('observed source bundle differs')
        if source+timedelta(hours=2)!=planned or dt(raw['nominal_cutoff'])!=source+timedelta(hours=1,seconds=60):raise ValueError('wrong source/entry shift')
        pools=source_pools(raw['source_bindings'],source,observed)
        hour_complete=True
        for pair in PAIRS:
            actual=raw['pairs'][pair];published=rec['pairs'][pair]
            timely=(published['status'] in ('TIMELY_SIGNAL','TIMELY_NO_TRADE') and dt(rec['published_observed_at'])<planned)
            if not timely:
                hour_complete=False;omitted.append(dict(at=key,pairs=[pair],reason=published['status']));continue
            if {k:v for k,v in published.items() if k!='status'}!={k:v for k,v in actual.items() if k!='status'}:raise ValueError('published intent content differs')
            if published['status']!=('TIMELY_NO_TRADE' if actual['intent']=='NO_TRADE' else 'TIMELY_SIGNAL'):raise ValueError('receipt intention class differs')
            expected=compute_intent(pair,pools,source)
            if expected!=actual:raise ValueError('persisted intent differs from frozen conditions/input provenance')
            if observed>=planned or dt(actual['latest_required_fetched_at'])>observed or dt(actual['effective_available_at'])>observed:raise ValueError('late input falsely classified timely')
            # Native vector calculation uses one immutable candle view. Refuse
            # conflicting revisions rather than combine incompatible vintages.
            current=frames[pair].set_index('date')
            for at,r in pools[pair,'ohlcv'].items():
                if source-timedelta(hours=168)<=at<=source:
                    if any(float(r[c])!=float(current.loc[at,c]) for c in ('open','high','low','close','volume')):raise ValueError('observed/native price vintage mismatch')
            cutoff=source+timedelta(hours=1,seconds=60)
            funding=max((r for r in pools[pair,'funding'].values() if r['declared']<=cutoff),key=lambda r:r['event'])
            premium=pools[pair,'premium'][source];table=factors[pair];idx=table.index[table.date==source][0]
            table.loc[idx,['funding_rate','premium_close','factor_valid']]=[float(funding['rate']),float(premium['close']),True]
            table.loc[idx,'funding_event_at']=funding['event'];table.loc[idx,'funding_available_at']=funding['declared'];table.loc[idx,'premium_available_at']=premium['declared'];table.loc[idx,'decision_at']=cutoff
            intents[key][pair]=dict(intent=actual['intent'],exit_long=actual['exit_long'],exit_short=actual['exit_short'])
            signals+=int(actual['intent']!='NO_TRADE')
        complete_hours+=int(hour_complete)
    if not complete_hours:raise ValueError('UNDERPOWERED: no complete timely two-pair engineering hour')
    return frames,marks,events,rules,factors,intents,dict(complete_two_pair_hours=complete_hours,scheduled_hours=len(snap['records']),timely_entry_signals=signals,omitted=omitted)


def mask_signals(dataframe,intents,pair,columns):
    """Check native natural conditions before masking missing/late intentions."""
    from lab.perp_forward_signal import iso
    for index,row in dataframe.iterrows():
        planned=iso(row.date.to_pydatetime()+timedelta(hours=1));target=intents.get(planned,{}).get(pair)
        for column in columns:
            if target is None:dataframe.at[index,column]=0;continue
            wanted=(target['intent']==('long' if column=='enter_long' else 'short')) if column.startswith('enter_') else target[column]
            if bool(row[column])!=bool(wanted):raise ValueError('natural native signal differs from observed intention')
    return dataframe


# Loaded only after CLI/native test calls native_environment().
from lab.perp_funding_premium import PerpFundingPremiumV1


class PerpForwardNativeAcceptance(PerpFundingPremiumV1):
    def bot_start(self,**kwargs):
        super().bot_start(**kwargs)
        item=self.config['observed_intents']
        if sha(item['path'])!=item['sha256']:raise ValueError('intent table changed')
        self.acceptance_intents=read(item['path'])

    def populate_entry_trend(self,dataframe,metadata):
        value=super().populate_entry_trend(dataframe,metadata)
        return mask_signals(value,self.acceptance_intents,metadata['pair'],('enter_long','enter_short'))

    def populate_exit_trend(self,dataframe,metadata):
        value=super().populate_exit_trend(dataframe,metadata)
        return mask_signals(value,self.acceptance_intents,metadata['pair'],('exit_long','exit_short'))


def run_native_acceptance(root, frames, events, metadata, factors, intents, start, end):
    """Use unchanged Freqtrade assembly, matching, cash flow and fill auditing."""
    import pandas as pd
    from freqtrade.commands.optimize_commands import setup_optimize_configuration
    from freqtrade.enums import RunMode, CandleType
    from freqtrade.exchange.binance import Binance
    from freqtrade.optimize.backtesting import Backtesting
    from freqtrade.data.history.datahandlers import get_datahandler
    from lab.perp_baseline_runner import REPO, native_config, assembly
    from lab.portfolio_native_export import read_strategy_export
    variant = 'carry_nonpaying'
    root = Path(root)
    for name in ('user', 'exports', 'data', 'factors'):
        (root/name).mkdir(parents=True)
    handler = get_datahandler(root/'data', 'feather'); factor_files = {}
    for pair, frame in frames.items():
        handler.ohlcv_store(pair, '1h', frame, CandleType.FUTURES)
        path = root/'factors'/(pair.split('/')[0]+'.json')
        factors[pair].to_json(path, orient='table', date_format='iso', date_unit='ms')
        factor_files[pair] = dict(path=str(path), sha256=sha(path))
    from lab.perp_baseline_runner import write
    intent_path = root/'observed-intents.json'; write(intent_path,intents)
    value = native_config('persistence', 1.)
    value['observed_intents'] = dict(path=str(intent_path),sha256=sha(intent_path))
    value.update(strategy='PerpForwardNativeAcceptance', perp_factor_variant=variant, perp_factor_files=factor_files)
    path = root/'config.json'; write(path, value)
    config = setup_optimize_configuration(dict(command='backtesting', config=[str(path)],
        datadir=str(root/'data'), user_data_dir=str(root/'user'), strategy_path=str(REPO/'lab'),
        strategy='PerpForwardNativeAcceptance', timerange=f'{int(start.timestamp())}-{int(end.timestamp())}', fee=.0008,
        export='trades', exportdirectory=str(root/'exports'), dataformat_ohlcv='feather',
        disableparamexport=True, backtest_cache='none'), RunMode.BACKTEST)

    class EventBacktesting(Backtesting):
        def _load_bt_data_detail(self):
            if self.timeframe_detail:
                raise ValueError('factor intrahour extension forbidden')
            self.detail_data = {}; self.futures_data = events; self.funding_fee_timeframe_secs = 3600

    class EventBinance(Binance):
        def calculate_funding_fees(self, df, amount, is_short, open_date, close_date):
            return super().calculate_funding_fees(df.loc[df.date > pd.Timestamp(open_date)],
                amount=amount, is_short=is_short, open_date=open_date, close_date=close_date)

    exchange = EventBinance(config, validate=False, load_leverage_tiers=False)
    def deny(*a, **k): raise RuntimeError('factor native worker cannot request exchange')
    exchange._api.fetch = deny; exchange._api_async.fetch = deny
    markets, tiers = assembly(metadata)
    exchange._api.set_markets(markets, {}); exchange._api_async.set_markets(markets, {})
    exchange._markets = exchange._api.markets; exchange._leverage_tiers = tiers
    engine = None
    try:
        engine = EventBacktesting(config, exchange=exchange)
        if len(engine.strategylist) != 1 or set(engine.pairlists.whitelist) != set(PAIRS):
            raise ValueError('factor native wallet/pair mismatch')
        engine.start(); archives = list((root/'exports').glob('*.zip'))
        if len(archives) != 1:
            raise ValueError('expected one factor native archive')
        result = read_strategy_export(archives[0], 'PerpForwardNativeAcceptance')
        write(root/'native-result.json', result); write(root/'entry-audit.json', engine.strategylist[0].entry_audit)
        return result, {p.name: sha(p) for p in archives}
    finally:
        if engine is not None: engine.cleanup()
        exchange.close()
