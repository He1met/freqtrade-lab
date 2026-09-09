"""Candidate-priority collection over the frozen V1 public transport and normalizer."""
from pathlib import Path
from datetime import datetime, timezone
from decimal import Decimal
import fcntl
import hashlib
import json
import re
import time

from lab import perp_data as legacy

HOUR, SYMBOLS = legacy.HOUR, legacy.SYMBOLS
REQUIRED = ('ohlcv', 'mark', 'funding', 'premium')
OPTIONAL = tuple(f'{symbol}-{kind}' for kind in ('index', 'oi') for symbol in SYMBOLS)+('coinmetrics-network',)
ENDPOINTS = dict(ohlcv=('klines','symbol'), mark=('markPriceKlines','symbol'),
    funding=('fundingRate','symbol'), premium=('premiumIndexKlines','symbol'), index=('indexPriceKlines','pair'))


def candidate_complete(receipt, root=None):
    """Premium completeness is required even though the selected gate ignores its sign."""
    if receipt.get('instrument_rules') != 'CURRENT_RULES_VERIFIED_HISTORICAL_RULES_UNPROVEN': return False
    errors = receipt.get('errors', {})
    if 'instrument_rules' in errors: return False
    data_root = root or receipt.get('root')
    if data_root is None: return False
    data_root = Path(data_root).resolve()
    try: cutoff = legacy.millis(receipt['window_end_exclusive'])+60_000
    except (KeyError,ValueError,TypeError): return False
    for symbol in SYMBOLS:
        for kind in REQUIRED:
            name = f'{symbol}-{kind}'; item = receipt.get('datasets', {}).get(name)
            if (not item or name in errors or item.get('duplicates',0) or item.get('out_of_window',0) or
                    item.get('missing_rows') not in ((0,None) if kind=='funding' else (0,))): return False
            path = (data_root/item.get('path','')).resolve()
            if not path.is_relative_to(data_root) or not path.is_file(): return False
            raw=path.read_bytes()
            if hashlib.sha256(raw).hexdigest()!=item.get('sha256'): return False
            if kind=='funding':
                # A 200/empty overlap is not proof of the candidate's latest rate.
                # Nominal publication selects the same event as the frozen model;
                # the observer separately enforces actual fetched/effective time.
                try:
                    rows=[json.loads(line) for line in raw.splitlines() if line.strip()]
                    if not rows or len(rows)!=item.get('rows'): return False
                    eligible=[]
                    for row in rows:
                        event=legacy.millis(row['event_time'])
                        declared=legacy.millis(row.get('historical_available_at_assumption',row['available_at']))
                        rate,mark=Decimal(str(row['rate'])),Decimal(str(row['mark_price']))
                        if not rate.is_finite() or not mark.is_finite() or mark<=0 or declared<event+HOUR: return False
                        if declared<=cutoff:eligible.append(event)
                    if not eligible or not 0<=cutoff-max(eligible)<=12*HOUR:return False
                except (KeyError,ValueError,TypeError,ArithmeticError):return False
    return True


def collect(root, start, end, max_requests=120, core_only=False, *, incremental=False,
            slow_due=True, circuits=(), candidate_required=False):
    if not candidate_required:
        return legacy.collect(root,start,end,max_requests,core_only,incremental=incremental,slow_due=slow_due,circuits=circuits)
    cap = legacy.Capture(root,start,end,max_requests,20*1024*1024 if incremental else legacy.MAX_BYTES,300 if incremental else 1200)
    priority_sha = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    budget = json.loads((cap.root/'budget.json').read_text())
    budget.update(priority_mode='CANDIDATE_REQUIRED_V1',priority_collector_sha256=priority_sha,
        required_order=list(REQUIRED),optional_order=['index','oi','coinmetrics-network'],limits_unchanged=True)
    legacy.save(cap.root/'budget.json',budget)
    summary = dict(schema='perp-public-data-v1',root=str(cap.root),started_at=legacy.utcnow(),exchange='binance',
        execution_venue='UNCONFIRMED',research_source='PROVISIONAL',window_start=legacy.iso(start),
        window_end_exclusive=legacy.iso(end),datasets={},errors={},deferred={},candidate_required=True,
        priority_collector_sha256=priority_sha,historical_use='EXPOSED_DEVELOPMENT_NO_INDEPENDENT_CONFIRMATION')
    def publish():
        summary.update(requests=cap.calls,response_bytes=cap.bytes,updated_at=legacy.utcnow(),
            candidate_core_complete=candidate_complete(summary))
        legacy.save(cap.root/'receipt.json',summary)
    def remaining():
        return cap.calls<cap.max_requests and cap.bytes<cap.max_bytes and time.monotonic()-cap.started<cap.max_seconds
    def defer(names, reason):
        summary['deferred'].update({name:reason for name in names});publish()
    if 'instrument_rules' in circuits:
        summary['errors']['instrument_rules']='CIRCUIT_OPEN';summary['status']='BLOCKED_DATA'
        defer(OPTIONAL,'REQUIRED_DATA_INCOMPLETE');return summary
    try:
        info,at=cap.get('exchange-info',legacy.BINANCE+'/fapi/v1/exchangeInfo')
        rules=[r for r in info['symbols'] if r['symbol'] in SYMBOLS]
        if len(rules)!=2 or any(r['contractType']!='PERPETUAL' or r['quoteAsset']!='USDT' or r['marginAsset']!='USDT' for r in rules):
            raise ValueError('INSTRUMENT_IDENTITY_INVALID')
        legacy.save(cap.root/'instrument-rules.json',dict(fetched_at=at,historical_rules_verified=False,symbols=rules))
        summary['instrument_rules']='CURRENT_RULES_VERIFIED_HISTORICAL_RULES_UNPROVEN'
    except Exception as exc:
        summary['errors']['instrument_rules']=str(exc);summary['status']='BLOCKED_DATA'
        defer(OPTIONAL,'REQUIRED_DATA_INCOMPLETE');return summary

    def hourly(kind,symbol):
        endpoint,key=ENDPOINTS[kind];name=f'{symbol}-{kind}'
        begin=start-24*HOUR if incremental and kind=='funding' else start
        cursor=begin;all_rows=[]
        if name in circuits:
            summary['errors'][name]='CIRCUIT_OPEN';publish();return
        try:
            while cursor<end:
                params={key:symbol,'startTime':cursor,'endTime':end-1,'limit':1000 if kind=='funding' else 1500}
                if kind!='funding':params['interval']='1h'
                raw,fetched=cap.get(name,legacy.BINANCE+'/fapi/v1/'+endpoint,params)
                if not isinstance(raw,list):raise ValueError('INVALID_RESPONSE_SHAPE')
                if not raw:break
                if kind=='funding':
                    rows=[]
                    for item in raw:
                        at=int(item['fundingTime'])
                        if not begin<=at<end:continue
                        if item['symbol']!=symbol:raise ValueError('WRONG_SYMBOL')
                        if not Decimal(item['fundingRate']).is_finite():raise ValueError('INVALID_FUNDING')
                        mark=Decimal(str(item.get('markPrice')))
                        if not mark.is_finite() or mark<=0:raise ValueError('INVALID_FUNDING_MARK')
                        rows.append(dict(event_time=legacy.iso(at),available_at=legacy.iso(at+HOUR),fetched_at=fetched,
                            source_version='BINANCE_SETTLED_FUNDING_V1_2026-09-08',vintage=fetched,
                            quality='SETTLED_RECORD_SIGNAL_LAG_1H_ASSUMPTION',rate=item['fundingRate'],mark_price=item['markPrice'],cost_time=legacy.iso(at)))
                    nxt=max(int(r['fundingTime']) for r in raw)+1
                else:
                    rows=legacy.normalize_klines(raw,kind,fetched,start,end);nxt=max(int(r[0]) for r in raw)+HOUR
                if nxt<=cursor:raise ValueError('PAGINATION_NO_PROGRESS')
                cursor=nxt;all_rows.extend(rows)
            times=[legacy.millis(r['event_time']) for r in all_rows]
            if len(set(times))!=len(times):raise ValueError('DUPLICATE_TIMESTAMPS')
            all_rows.sort(key=lambda r:r['event_time'])
            if incremental:legacy.observed_availability(all_rows)
            path=cap.root/f'{name}.jsonl';legacy.dump_jsonl(path,all_rows)
            if kind=='funding':
                milliseconds=[b-a for a,b in zip(sorted(times),sorted(times)[1:])]
                quality=dict(rows=len(times),first=legacy.iso(min(times)) if times else None,last=legacy.iso(max(times)) if times else None,
                    observed_interval_seconds=sorted(set(d//1000 for d in milliseconds)),missing_rows=None,
                    observed_interval_ms_counts={str(d):milliseconds.count(d) for d in sorted(set(milliseconds))},
                    coverage_status='OBSERVED_SETTLEMENTS_NO_ASSUMED_FIXED_INTERVAL',overlap_start=legacy.iso(begin),
                    overlap_is_revision_observation_not_new_events=incremental,
                    first_boundary_seconds=(min(times)-start)//1000 if times else None,last_boundary_seconds=(end-max(times))//1000 if times else None)
            else:quality=legacy.quality_times(times,start,end)
            summary['datasets'][name]=dict(path=path.name,sha256=hashlib.sha256(path.read_bytes()).hexdigest(),**quality)
        except Exception as exc:summary['errors'][name]=str(exc)
        publish()

    for kind in REQUIRED:
        for symbol in SYMBOLS:hourly(kind,symbol)
    if not candidate_complete(summary):
        summary['errors']['candidate_required']='REQUIRED_DATA_INCOMPLETE_OR_NO_ELIGIBLE_RECENT_SETTLEMENT'
        summary['status']='BLOCKED_DATA';defer(OPTIONAL,'REQUIRED_DATA_INCOMPLETE');return summary
    if core_only:
        defer(OPTIONAL,'CORE_ONLY_REQUESTED')
    else:
        for symbol in SYMBOLS:
            name=symbol+'-index'
            if remaining():hourly('index',symbol)
            else:defer((name,),'ACQUISITION_BUDGET_STOP')
        for symbol in SYMBOLS:
            name=symbol+'-oi'
            if not remaining():defer((name,),'ACQUISITION_BUDGET_STOP');continue
            if name in circuits:summary['errors'][name]='CIRCUIT_OPEN';continue
            try:
                raw,fetched=cap.get(name,legacy.BINANCE+'/futures/data/openInterestHist',dict(symbol=symbol,period='1h',limit=2 if incremental else 500))
                rows=[dict(event_time=legacy.iso(int(r['timestamp'])),available_at=legacy.iso(int(r['timestamp'])+HOUR),fetched_at=fetched,
                    source_version='BINANCE_OI_HIST_V1_2026-09-08',vintage=fetched,quality='RECENT_HISTORY_1H_PUBLICATION_LAG_ASSUMPTION',
                    open_interest=r['sumOpenInterest'],open_interest_value=r['sumOpenInterestValue']) for r in raw]
                if incremental:legacy.observed_availability(rows)
                path=cap.root/f'{name}.jsonl';legacy.dump_jsonl(path,rows)
                summary['datasets'][name]=dict(path=path.name,sha256=hashlib.sha256(path.read_bytes()).hexdigest(),rows=len(rows),
                    first=min((r['event_time'] for r in rows),default=None),last=max((r['event_time'] for r in rows),default=None),
                    status='RECENT_ONLY_BEGIN_FORWARD_CAPTURE',unit_contract_verified=False)
            except Exception as exc:summary['errors'][name]=str(exc)
            publish()
        name='coinmetrics-network'
        if not slow_due:defer((name,),'NOT_DUE')
        elif name in circuits:summary['errors'][name]='CIRCUIT_OPEN'
        elif not remaining() or cap.max_requests-cap.calls<2:defer((name,),'ACQUISITION_BUDGET_STOP')
        else:
            try:
                catalog,fetched=cap.get('cm-catalog',legacy.CM+'/catalog-v2/asset-metrics',dict(assets='btc,eth',metrics='TxCnt,AdrActCnt'))
                legacy.save(cap.root/'coinmetrics-catalog.json',dict(fetched_at=fetched,response=catalog))
                if not {'btc','eth'}<={r['asset'] for r in catalog.get('data',[])}:raise ValueError('CATALOG_COVERAGE_UNCONFIRMED')
                raw,at=cap.get('cm-network',legacy.CM+'/timeseries/asset-metrics',dict(assets='btc,eth',metrics='TxCnt,AdrActCnt',
                    frequency='1d',start_time=legacy.iso(end-5*24*HOUR if incremental else start),end_time=legacy.iso(end-1),page_size=10000))
                if raw.get('next_page_url'):raise ValueError('CM_UNCONSUMED_NEXT_PAGE')
                rows=[]
                for row in raw.get('data',[]):
                    if row['asset'] not in ('btc','eth'):raise ValueError('CM_WRONG_ASSET')
                    if any(row.get(m) is not None and (not Decimal(row[m]).is_finite() or Decimal(row[m])<0) for m in ('TxCnt','AdrActCnt')):raise ValueError('CM_INVALID_COUNT')
                    event=legacy.millis(row['time'])
                    rows.append(dict(asset=row['asset'],event_time=legacy.iso(event),available_at=legacy.iso(event+48*HOUR),fetched_at=at,
                        source_version='COINMETRICS_COMMUNITY_V4_2026-09-08',vintage=at,
                        quality='DEVELOPMENT_ONLY_NO_HISTORICAL_VINTAGE_48H_LAG_ASSUMPTION',TxCnt=row.get('TxCnt'),AdrActCnt=row.get('AdrActCnt')))
                if incremental:legacy.observed_availability(rows)
                path=cap.root/'coinmetrics-network.jsonl';legacy.dump_jsonl(path,rows)
                summary['datasets'][name]=dict(path=path.name,sha256=hashlib.sha256(path.read_bytes()).hexdigest(),rows=len(rows),
                    status='DEVELOPMENT_ONLY_NO_PIT',assets=sorted({r['asset'] for r in rows}),
                    first=min((r['event_time'] for r in rows),default=None),last=max((r['event_time'] for r in rows),default=None),
                    missing_metric_values=sum(r[m] is None for r in rows for m in ('TxCnt','AdrActCnt')))
            except Exception as exc:summary['errors'][name]=str(exc)
    summary.update(status='CAPTURED_WITH_LIMITATIONS',completed_at=legacy.utcnow());publish();return summary


def update(root, now=None, *, collector=None, candidate_required=False):
    if not candidate_required:return legacy.update(root,now,collector=collector or legacy.collect)
    collector=collector or collect;root=Path(root);root.mkdir(parents=True,exist_ok=True)
    now=now or legacy.utcnow();at=legacy.millis(now)
    if at%HOUR<10*60_000:return dict(status='WAIT_CLOSED_HOUR_PUBLICATION',at=now,requests=0,candidate_required=True)
    with (root/'writer.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return dict(status='LOCK_CONFLICT',requests=0,candidate_required=True)
        state_path=root/'state.json';state=json.loads(state_path.read_text()) if state_path.exists() else dict(circuits={},daily_requests={},weekly_requests={})
        end=at//HOUR*HOUR;key=legacy.iso(end).replace(':','').replace('-','');capture_root=root/key
        if capture_root.exists():
            committed_path=capture_root/'update-receipt.json';prior={}
            if committed_path.is_file():
                try:prior=json.loads(committed_path.read_text())
                except (OSError,ValueError):pass
            identity=isinstance(prior,dict) and prior.get('key')==key and prior.get('root')==str(capture_root)
            result=dict(status='INTERRUPTED_CAPTURE_RETAINED',key=key,requests=0,root=str(capture_root),core_complete=False,
                candidate_required=True,receipt=str(committed_path) if committed_path.is_file() else None)
            if identity and prior.get('status') in ('DATA_CAPTURED','BLOCKED_DATA'):
                try:receipt=json.loads((capture_root/'receipt.json').read_text())
                except (OSError,ValueError):receipt={}
                okay=prior.get('status')=='DATA_CAPTURED' and prior.get('core_complete') is True and candidate_complete(receipt,capture_root)
                result.update(status='NO_OP_ALREADY_CAPTURED' if okay else 'NO_OP_BLOCKED_DATA',core_complete=okay,
                    errors=prior.get('errors',{}),deferred=receipt.get('deferred',{}))
                if not okay:result['candidate_required_reason']='REQUIRED_DATA_INCOMPLETE_OR_UNVERIFIED'
            return result
        day=legacy.iso(end)[:10];week=datetime.fromtimestamp(end/1000,timezone.utc).strftime('%G-W%V')
        if state['daily_requests'].get(day,0)+24>576 or state['weekly_requests'].get(week,0)+24>4032:
            return dict(status='WAIT_RESOURCE_BUDGET',requests=0,candidate_required=True)
        last=legacy.millis(state['last_complete_end']) if state.get('last_complete_end') else end-HOUR
        start=max(last,end-24*HOUR);slow_due=state.get('last_slow_day')!=day
        state['daily_requests'][day]=state['daily_requests'].get(day,0)+24
        state['weekly_requests'][week]=state['weekly_requests'].get(week,0)+24
        state['last_reserved_key']=key;legacy.save(state_path,state)
        try:receipt=collector(capture_root,start,end,24,incremental=True,slow_due=slow_due,circuits=state['circuits'],candidate_required=True)
        except Exception as exc:
            receipt=dict(status='TECHNICAL_BLOCK',errors={'collector':type(exc).__name__+':'+str(exc)},requests=24)
            capture_root.mkdir(exist_ok=True);legacy.save(capture_root/'failure.json',receipt)
        used=receipt.get('requests',24)
        state['daily_requests'][day]-=max(0,24-used);state['weekly_requests'][week]-=max(0,24-used)
        for name,error in receipt.get('errors',{}).items():
            if re.fullmatch(r'HTTP_(301|302|307|308|400|401|403|404|451)',error) or error.startswith(('INVALID_','INSTRUMENT_','CM_INVALID_','CM_WRONG_','CATALOG_COVERAGE_')):
                state['circuits'][name]=dict(reason=error,since=now,reset='versioned source/permission fix required')
        okay=candidate_complete(receipt,capture_root)
        if okay:state['last_complete_end']=legacy.iso(end)
        if 'coinmetrics-network' in receipt.get('datasets',{}):state['last_slow_day']=day
        state.update(updated_at=now,last_capture=str(capture_root),last_status=receipt.get('status'),candidate_required=True)
        legacy.save(state_path,state)
        result=dict(status='DATA_CAPTURED' if okay else 'BLOCKED_DATA',key=key,root=str(capture_root),requests=used,
            core_complete=okay,candidate_required=True,decision_replay=False,receipt=str(capture_root/'update-receipt.json'),
            capture_use='LATE_BACKFILL_AND_FIRST_OBSERVATION_ONLY',gap_before_start=last<start,
            errors=receipt.get('errors',{}),deferred=receipt.get('deferred',{}))
        legacy.save(capture_root/'update-receipt.json',result);return result
