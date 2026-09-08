"""Fixed 90-day consumer; import only after the real-clock endpoint gate."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import hashlib
import json
import math
import random

from lab.perp_forward_signal import control, dt, iso, encoded
from lab.perp_forward_native import PAIRS, capture_files, source_pools, mask_signals, sha, read

REPO=Path(__file__).resolve().parents[1]
PROTOCOL=REPO/'docs/protocols/perp-independent-confirmation-v2.json'


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,default=str).encode()).hexdigest()


def activation(signal_root,identity,protocol,acceptance_path):
    state=read(Path(signal_root)/'state.json');acceptance=read(acceptance_path)
    if (state.get('identity')!=identity or state.get('active') is not True or
            dt(state.get('activated_at',''))>=dt(protocol['window']['start_inclusive']) or
            sha(acceptance_path)!=state.get('native_acceptance_receipt_sha256')):
        raise ValueError('confirmation requires unchanged pre-start activation and acceptance')
    if (acceptance.get('status') not in ('PASS','LIMITED_PASS') or acceptance.get('native_calls')!=1 or
            acceptance.get('economic_validation') is not False or
            any(acceptance.get(k)!=v for k,v in identity.items()) or
            acceptance.get('signal_root')!=str(Path(signal_root).resolve())):
        raise ValueError('activation acceptance identity differs')
    for name,expected in acceptance.get('code_bindings',{}).items():
        if sha(REPO/name)!=expected:raise ValueError('acceptance code drift')
    if not acceptance.get('code_bindings'):raise ValueError('acceptance code provenance absent')
    return state


def snapshot(seed_root,incremental_root,signal_root,registration,protocol,binding,acceptance_path,now):
    _,spec,_,identity=control(registration,protocol,binding)
    start=dt(spec['window']['start_inclusive']);end=dt(spec['window']['end_exclusive'])
    if now<end+timedelta(minutes=10):raise ValueError('WAIT_FORWARD: fixed interval/publication gate not reached')
    state=activation(signal_root,identity,spec,acceptance_path)
    roots,files=capture_files(seed_root,incremental_root,start,end)
    for path in (Path(signal_root)/'state.json',Path(acceptance_path)):
        files[str(path.resolve())]=sha(path)
    records=[];at=start
    while at<end:
        key=at.strftime('%Y%m%dT%H00Z');raw=Path(signal_root)/'hours'/(key+'.intent.json');rec=Path(signal_root)/'hours'/(key+'.receipt.json')
        committed=state.get('records',{}).get(key)
        if committed is None and not raw.exists() and not rec.exists():
            records.append(dict(planned_entry=iso(at),missing=True));at+=timedelta(hours=1);continue
        if committed is None or not raw.is_file() or not rec.is_file():raise ValueError('partial or uncommitted confirmation evidence')
        intent=read(raw);receipt=read(rec)
        if (committed['intent_sha256']!=sha(raw) or committed['receipt_sha256']!=sha(rec) or
                receipt.get('intent_sha256')!=sha(raw) or intent.get('identity')!=identity or receipt.get('identity')!=identity or
                dt(intent['planned_entry'])!=at or receipt.get('phase')!='CONFIRMATION'):
            raise ValueError('confirmation intent identity/durable SHA/phase mismatch')
        for name,expected in intent['source_bindings'].items():
            if name in files and files[name]!=expected:raise ValueError('source snapshot collision')
            files[name]=expected
        files[str(raw.resolve())]=sha(raw);files[str(rec.resolve())]=sha(rec)
        records.append(dict(planned_entry=iso(at),intent=intent,receipt=receipt));at+=timedelta(hours=1)
    return dict(schema='perp-confirmation-intent-snapshot-v1',identity=identity,signal_root=str(Path(signal_root).resolve()),
        start=iso(start),end=iso(end),frozen_observed_at=iso(now),capture_roots=roots,source_files=files,records=records,
        activation_at=state['activated_at'],native_acceptance_sha256=sha(acceptance_path))


def primary_verdict(metrics,coverage,protocol):
    gate=protocol['sample_and_decision'];risk=metrics['observed_hourly_mtm_drawdown']
    if coverage['timely_fraction']<protocol['time_and_data']['minimum_timely_decision_coverage'] or metrics['common_72h_entry_clusters']<gate['minimum_nonempty_synchronized_72h_blocks']:
        verdict='UNDERPOWERED'
    elif metrics['gross_price_effect_usdt']<=0:verdict='GROSS_NOT_SUPPORTED'
    elif metrics['net_usdt']<=0:verdict='COST_NOT_SUPPORTED'
    else:verdict='CONFIRMATION_POSITIVE_LIMITED'
    return dict(verdict=verdict,risk_classification='RISK_RECALIBRATION_REQUIRED' if risk>=.3 else 'ABOVE_TARGET_REVIEW' if risk>.2 else 'WITHIN_TARGET',
        cost_sensitivity='COST_SENSITIVE' if metrics['conditional_same_fill_stress_net_usdt']<0 else 'CONDITIONAL_STRESS_NONNEGATIVE',
        economic_qualification=False,live_trading_authorized=False)


def validate_snapshot_records(snap,start,end):
    if [r['planned_entry'] for r in snap['records']]!=[iso(start+timedelta(hours=i)) for i in range(2160)]:
        raise ValueError('exact 2160 scheduled hours required; no date removal')
    root=Path(snap['signal_root']);state_path=root/'state.json';state=read(state_path)
    if (snap['source_files'].get(str(state_path.resolve()))!=sha(state_path) or state.get('identity')!=snap['identity'] or
            state.get('active') is not True or dt(state['activated_at'])>=start or snap.get('activation_at')!=state['activated_at']):
        raise ValueError('snapshot activation proof differs')
    for record in snap['records']:
        key=dt(record['planned_entry']).strftime('%Y%m%dT%H00Z');raw=root/'hours'/(key+'.intent.json');receipt=root/'hours'/(key+'.receipt.json')
        committed=state.get('records',{}).get(key)
        if record.get('missing'):
            if committed is not None or raw.exists() or receipt.exists():raise ValueError('snapshot selectively omitted existing evidence')
            continue
        if (not committed or snap['source_files'].get(str(raw.resolve()))!=committed['intent_sha256'] or
                snap['source_files'].get(str(receipt.resolve()))!=committed['receipt_sha256'] or
                sha(raw)!=committed['intent_sha256'] or sha(receipt)!=committed['receipt_sha256'] or
                record['intent']!=read(raw) or record['receipt']!=read(receipt) or
                record['intent'].get('identity')!=snap['identity'] or record['receipt'].get('identity')!=snap['identity'] or
                record['receipt'].get('phase')!='CONFIRMATION' or record['receipt'].get('intent_sha256')!=sha(raw)):
            raise ValueError('snapshot differs from durable original confirmation evidence')


def block_interval(points,start,end,protocol):
    """Frozen conditional-path bootstrap; no resimulated wallet or trade samples."""
    spec=protocol['sample_and_decision']['bootstrap_spec']
    result=dict(status='UNKNOWN',lower_return_fraction=None,upper_return_fraction=None,
        seed=spec['seed'],resamples=spec['resamples'],block_hours=spec['block_hours'],
        estimator='Conditional 90-day realized-path compounded return; Python MT19937; 30 synchronized blocks including zero exposure.',
        initial_equity=1000.,first_hour_endpoint=iso(start+timedelta(hours=1)))
    expected=[iso(start+timedelta(hours=i)) for i in range(2161)]
    if (end-start!=timedelta(days=90) or [p['at'] for p in points]!=expected or
            any(not math.isfinite(float(p['equity'])) or p['equity']<=0 for p in points)):
        return dict(result,reason='Missing/nonfinite/nonpositive primary equity; no blocks discarded')
    if (spec['seed'],spec['resamples'],spec['block_hours'],spec['synchronize_pairs'])!=(162,2000,72,True):
        raise ValueError('frozen bootstrap specification changed')
    # The first hourly return includes entry costs at start against the frozen
    # initially flat 1000-USDT wallet, rather than dropping the t=start fees.
    previous=1000.;returns=[]
    for point in points[1:]:
        returns.append(math.log(point['equity'])-math.log(previous));previous=point['equity']
    blocks=[sum(returns[i:i+72]) for i in range(0,2160,72)]
    rng=random.Random(162);draws=[]
    try:
        for _ in range(2000):draws.append(math.expm1(sum(blocks[rng.randrange(30)] for _ in range(30))))
    except OverflowError:return dict(result,reason='Bootstrap numeric range exceeded; no estimate invented')
    if any(not math.isfinite(value) for value in draws):return dict(result,reason='Nonfinite bootstrap estimate')
    draws.sort()
    def quantile(fraction):
        index=(len(draws)-1)*fraction;lo=int(index);hi=min(lo+1,len(draws)-1)
        return draws[lo]+(index-lo)*(draws[hi]-draws[lo])
    return dict(result,status='COMPUTED_CONDITIONAL_PATH_ONLY',lower_return_fraction=quantile(.025),upper_return_fraction=quantile(.975),
        complete_blocks=30,resampled_account_executions=0,future_profit_probability=None)


def score(result,marks,events,start,end,coverage,protocol):
    from lab.perp_baseline_runner import audit_native
    metrics,points=audit_native(result,marks,events,start,end)
    if any(not math.isfinite(float(row[k])) for row in points for k in ('equity','drawdown','gross_exposure','funding','cost','turnover')):
        raise ValueError('nonfinite primary accounting; economic result remains unknown')
    expected={iso(start+timedelta(hours=i)) for i in range(2161)}
    if {row['at'] for row in points}!=expected or len(points)!=2161:
        raise ValueError('incomplete primary hourly marked equity; no missing-zero reconstruction')
    trades=result['trades'];anchor=lambda ms:int((datetime.fromtimestamp(ms/1000,timezone.utc)-start).total_seconds()//(72*3600))
    metrics['common_72h_entry_clusters']=len({anchor(t['open_timestamp']) for t in trades})
    interval=block_interval(points,start,end,protocol)
    metrics.update(independent_confirmation=True,annualization_is_descriptive_development=False,
        evidence_grade='PRECOMMITTED_FUTURE_INTENTS_WITH_NATIVE_OFFLINE_FILL_ASSUMPTIONS',
        confidence_interval=interval,confidence_interval_status=interval['status'],
        uncertainty='Conditional realized-path synchronized-block interval; not independent trades, a resimulated wallet or probability of future profit. Order-book impact and intrahour risk remain unknown.')
    equity={dt(r['at']):r['equity'] for r in points};daily=[];stages=[]
    for size,target in ((24,daily),(30*24,stages)):
        initial=1000.;at=start
        while at<end:
            finish=min(at+timedelta(hours=size),end);final=equity[finish]
            target.append(dict(start=iso(at),end_exclusive=iso(finish),initial_equity=initial,final_equity=final,return_fraction=final/initial-1 if initial>0 else None))
            initial=final;at=finish
    force=[dict(pair=t['pair'],at=datetime.fromtimestamp(t['close_timestamp']/1000,timezone.utc).isoformat()) for t in trades if t['exit_reason']=='force_exit']
    return dict(metrics=metrics,decision=primary_verdict(metrics,coverage,protocol),daily=daily,stages=stages,
        coverage=coverage,native_force_exits=force,
        boundary='Native final available candle is end-1h; any force exit keeps its actual timestamp. No invented midnight fill or non-native equity splice.',
        same_availability_comparator=dict(status='UNKNOWN_NOT_RUN_SINGLE_FIXED_NATIVE_CALL',net_usdt=None),
        unique_next_direction='本冻结窗口终结；不自动延长或换候选。若需下一确认，先依据本报告冻结新的独立窗口。'),points


def chinese_report(summary):
    lines=['# BTC/ETH 永续：90 日独立确认终点报告','',summary['conclusion'],'',
        '本报告不代表实盘许可；未取得的指标保留 UNKNOWN。']
    if 'result' in summary:
        result=summary['result'];m=result['metrics'];d=result['decision']
        interval=m['confidence_interval'];ci=(f"[{interval['lower_return_fraction']:.2%}, {interval['upper_return_fraction']:.2%}]" if interval['status']=='COMPUTED_CONDITIONAL_PATH_ONLY' else 'UNKNOWN')
        lines += ['',f"结论：{d['verdict']}；风险：{d['risk_classification']}。",'',
            f"成本后净收益 {m['net_usdt']:.8f} USDT；价格毛贡献 {m['gross_price_effect_usdt']:.8f} USDT；小时盯市最大回撤 {m['observed_hourly_mtm_drawdown']:.2%}。",
            f"手续费 {m['taker_fee_usdt']:.8f}，滑点预算 {m['slippage_allowance_usdt']:.8f}，真实资金费 {m['funding_usdt']:.8f} USDT。",
            f"及时覆盖 {result['coverage']['timely_fraction']:.2%}；共同 72h 非空簇 {m['common_72h_entry_clusters']}；自然原生持仓周期 {m['native_position_cycles']}。",
            '', '固定同步 72h 块、seed=162、2000 次重采样的条件路径 95% 区间：'+ci+'；不是未来盈利概率，也没有重跑账户。',
            '实际价差冲击及真实小时内最大回撤为 UNKNOWN；本单窗口不授予通用经济资格。',
            '原生末根 K 线为窗口终点前一小时，强平按原生真实时间记录，不拼接午夜收益。','',result['unique_next_direction'],
            '', '逐日/阶段收益、暴露、集中度、尾部、持续时间及缺失槽保留在绑定 JSON 与 equity.json。']
    return '\n'.join(lines)+'\n'


def decode(snap):
    """Validate retained intent conditions; prepare native data without running it."""
    import pandas as pd
    from lab.perp_forward_signal import dt,intent as compute_intent
    for name,d in snap['source_files'].items():
        if sha(name)!=d:raise ValueError('frozen source/intent changed: '+name)
    start=dt(snap['start']);end=dt(snap['end']);now=dt(snap['frozen_observed_at'])
    spec=read(PROTOCOL)
    if start!=dt(spec['window']['start_inclusive']) or end!=dt(spec['window']['end_exclusive']) or now<end+timedelta(minutes=10):raise ValueError('WAIT_FORWARD: fixed interval/publication gate differs')
    validate_snapshot_records(snap,start,end)
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
            if planned>=dt(spec['window']['last_new_entry_exclusive']) and expected['status']=='VALID_INTENT':expected.update(intent='NO_TRADE',entry_window_closed=True)
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
    return frames,marks,events,rules,factors,intents,dict(complete_two_pair_hours=complete_hours,scheduled_hours=len(snap['records']),timely_entry_signals=signals,omitted=omitted,scheduled_pair_hours=4320,timely_pair_hours=sum(len(v) for v in intents.values()),timely_fraction=sum(len(v) for v in intents.values())/4320)


from lab.perp_forward_native import PerpForwardNativeAcceptance
from lab.perp_funding_premium import PerpFundingPremiumV1


class PerpForwardConfirmation(PerpForwardNativeAcceptance):
    def populate_entry_trend(self,dataframe,metadata):
        # Apply the already-frozen final-72h no-entry rule before comparison.
        value=PerpFundingPremiumV1.populate_entry_trend(self,dataframe,metadata)
        cutoff=dt(read(PROTOCOL)['window']['last_new_entry_exclusive'])
        closed=value.date+timedelta(hours=1)>=cutoff
        value.loc[closed,['enter_long','enter_short']]=0
        return mask_signals(value,self.acceptance_intents,metadata['pair'],('enter_long','enter_short'))


def run_native_confirmation(root, frames, events, metadata, factors, intents, start, end):
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
    value.update(strategy='PerpForwardConfirmation', perp_factor_variant=variant, perp_factor_files=factor_files)
    path = root/'config.json'; write(path, value)
    config = setup_optimize_configuration(dict(command='backtesting', config=[str(path)],
        datadir=str(root/'data'), user_data_dir=str(root/'user'), strategy_path=str(REPO/'lab'),
        strategy='PerpForwardConfirmation', timerange=f'{int(start.timestamp())}-{int(end.timestamp())}', fee=.0008,
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
        result = read_strategy_export(archives[0], 'PerpForwardConfirmation')
        write(root/'native-result.json', result); write(root/'entry-audit.json', engine.strategylist[0].entry_audit)
        return result, {p.name: sha(p) for p in archives}
    finally:
        if engine is not None: engine.cleanup()
        exchange.close()
