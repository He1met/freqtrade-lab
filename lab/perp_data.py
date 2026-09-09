"""Bounded public-only BTC/ETH USD-M collection; immutable captures and honest timing."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone, timedelta
from decimal import Decimal
import hashlib
import json
import re
import fcntl
import os
from pathlib import Path
import time
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse

HOUR = 3_600_000
SYMBOLS = ('BTCUSDT', 'ETHUSDT')
BINANCE = 'https://fapi.binance.com'
CM = 'https://community-api.coinmetrics.io/v4'
MAX_BYTES = 100 * 1024 * 1024

def utcnow(): return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
def iso(ms): return (datetime(1970,1,1,tzinfo=timezone.utc)+timedelta(milliseconds=ms)).isoformat().replace('+00:00','Z')
def millis(value):
    value = re.sub(r'(\.\d{6})\d+(?=Z|[+-])', r'\1', value)
    delta=datetime.fromisoformat(value.replace('Z','+00:00'))-datetime(1970,1,1,tzinfo=timezone.utc)
    return (delta.days*86400+delta.seconds)*1000+delta.microseconds//1000
def save(path, value):
    path=Path(path);temp=path.with_name(path.name+'.pending')
    with temp.open('w') as stream:
        stream.write(json.dumps(value,indent=2,ensure_ascii=False)+'\n')
        stream.flush();os.fsync(stream.fileno())
    temp.replace(path)

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

def public_open(request,timeout):
    return build_opener(NoRedirect).open(request,timeout=timeout)

def quality_times(times, start, end, step=HOUR):
    values = sorted(times)
    unique = set(values)
    missing = sorted(set(range(start, end, step)) - unique)
    return {'rows': len(values), 'duplicates': len(values)-len(unique),
            'first': iso(values[0]) if values else None, 'last': iso(values[-1]) if values else None,
            'expected_rows': len(range(start, end, step)), 'missing_rows': len(missing),
            'missing_fraction': len(missing)/len(range(start,end,step)) if end>start else None,
            'gap_examples': [iso(t) for t in missing[:20]],
            'out_of_window': sum(t < start or t >= end for t in values)}

class Capture:
    def __init__(self, root, start, end, max_requests=120, max_bytes=MAX_BYTES, max_seconds=1200):
        self.root = Path(root).resolve()
        if any((p/'.git').exists() for p in (self.root,*self.root.parents)):
            raise ValueError('RUNTIME_MUST_BE_OUTSIDE_GIT')
        self.root.mkdir(parents=True, exist_ok=False)
        (self.root/'raw').mkdir()
        self.started = time.monotonic(); self.calls=0; self.bytes=0
        self.max_requests=max_requests
        self.max_bytes=max_bytes;self.max_seconds=max_seconds
        self.start,self.end=start,end
        save(self.root/'budget.json', {'policy_version':'BTC_ETH_PERP_AUTONOMOUS_V1', 'registered_at':utcnow(),
             'collector_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
             'window_start':iso(start),'window_end_exclusive':iso(end),'max_requests':max_requests,
             'max_total_response_bytes':max_bytes,'max_seconds':max_seconds,'max_attempts_per_request':2,
             'symbols':list(SYMBOLS),'market_compute_workers':0,'historical_use':'EXPOSED_DEVELOPMENT',
             'notes':'Public GET only. HTTP 429/5xx/transport retry once within budget; other errors stop endpoint.'})

    def get(self, name, url, params=None):
        if urlparse(url).netloc not in {'fapi.binance.com','community-api.coinmetrics.io'}:
            raise ValueError('unapproved public host')
        full=url+('?' + urlencode(params) if params else '')
        for attempt in range(2):
            if self.calls >= self.max_requests or self.bytes >= self.max_bytes or time.monotonic()-self.started>self.max_seconds:
                raise RuntimeError('ACQUISITION_BUDGET_STOP')
            self.calls+=1
            save(self.root/'request-reservation.json',{'requests_reserved':self.calls,'bytes_retained_before_request':self.bytes,
                 'at':utcnow(),'state':'REQUEST_OUTCOME_UNKNOWN_UNTIL_REQUESTS_LEDGER'})
            fetched=utcnow(); status=None; body=b''; error=None; retry_after=None
            try:
                req=Request(full,headers={'User-Agent':'freqtrade-lab-public-research/1.0'})
                with public_open(req, timeout=min(25,max(1,self.max_seconds-(time.monotonic()-self.started)))) as response:
                    status=response.status
                    body=response.read(min(5*1024*1024,self.max_bytes-self.bytes)+1)
                    if len(body)>5*1024*1024 or self.bytes+len(body)>self.max_bytes:
                        raise RuntimeError('RESPONSE_SIZE_BUDGET_STOP')
            except HTTPError as exc:
                status=exc.code; body=exc.read(65536); error=f'HTTP_{status}'
                retry_after=exc.headers.get('Retry-After')
            except (URLError, TimeoutError, OSError) as exc:
                error=type(exc).__name__+':'+str(exc)[:160]
            except RuntimeError as exc:
                error=str(exc)
            self.bytes+=len(body)
            raw=f'raw/{self.calls:03d}-{name}.json'
            (self.root/raw).write_bytes(body)
            entry={'request_number':self.calls,'name':name,'url':full,'attempt':attempt+1,
                   'fetched_at':fetched,'completed_at':utcnow(),'status':status,'error':error,
                   'bytes':len(body),'sha256':hashlib.sha256(body).hexdigest(),'path':raw}
            with (self.root/'requests.jsonl').open('a') as stream:
                stream.write(json.dumps(entry)+'\n');stream.flush();os.fsync(stream.fileno())
            if error is None:
                return json.loads(body),fetched
            retryable=status==429 or (status is not None and 500<=status<600) or status is None
            if attempt==0 and retryable:
                delay=2
                if retry_after:
                    try: delay=max(2,float(retry_after))
                    except ValueError: delay=60
                if delay>30: break
                time.sleep(delay)
            else: break
        raise RuntimeError(error)


def normalize_klines(raw, kind, fetched, start, end):
    result=[]
    for row in raw:
        t=int(row[0])
        if not start <= t < end: continue
        if t+HOUR > millis(fetched): continue
        values=[Decimal(str(v)) for v in row[1:6]]
        if not all(v.is_finite() for v in values): raise ValueError('NONFINITE_PRICE')
        if kind!='premium' and min(values[:4])<=0: raise ValueError('NONPOSITIVE_PRICE')
        if values[1]<max(values[0],values[3]) or values[2]>min(values[0],values[3]) or values[1]<values[2]:
            raise ValueError('INVALID_OHLC_RANGE')
        if kind=='ohlcv' and values[4]<0:raise ValueError('NEGATIVE_VOLUME')
        result.append({'event_time':iso(t),'available_at':iso(t+HOUR+60_000),
                       'fetched_at':fetched,'source_version':'BINANCE_USDM_REST_V1_2026-09-08',
                       'quality':'HISTORICAL_CLOSED_BAR_CONSERVATIVE_60S_LAG',
                       'vintage':fetched,'open':str(values[0]),'high':str(values[1]),
                       'low':str(values[2]),'close':str(values[3]),
                       'volume':str(values[4]) if kind=='ohlcv' else None,
                       'taker_buy_base_volume':str(row[9]) if kind=='ohlcv' else None})
    return result

def dump_jsonl(path,rows):
    with path.open('w') as stream:
        for row in rows:stream.write(json.dumps(row)+'\n')
        stream.flush();os.fsync(stream.fileno())

def observed_availability(rows):
    """Forward captures cannot claim that a late observation was available before fetch."""
    for row in rows:
        row['historical_available_at_assumption']=row['available_at']
        row['available_at']=iso(max(millis(row['available_at']),millis(row['fetched_at'])))
        row['quality']+=';FIRST_OBSERVATION_FLOOR'
    return rows

def collect(root, start, end, max_requests=120, core_only=False, *, incremental=False,
            slow_due=True, circuits=()):
    cap=Capture(root,start,end,max_requests,20*1024*1024 if incremental else MAX_BYTES,
                300 if incremental else 1200)
    summary={'schema':'perp-public-data-v1','root':str(cap.root),'started_at':utcnow(),
             'exchange':'binance','execution_venue':'UNCONFIRMED','research_source':'PROVISIONAL',
             'window_start':iso(start),'window_end_exclusive':iso(end), 'datasets':{},'errors':{},
             'historical_use':'EXPOSED_DEVELOPMENT_NO_INDEPENDENT_CONFIRMATION'}
    def publish():
        summary.update(requests=cap.calls,response_bytes=cap.bytes,updated_at=utcnow())
        save(cap.root/'receipt.json',summary)
    if 'instrument_rules' in circuits:
        summary['errors']['instrument_rules']='CIRCUIT_OPEN';summary['status']='BLOCKED_DATA';publish();return summary
    try:
        info,at=cap.get('exchange-info',BINANCE+'/fapi/v1/exchangeInfo')
        rules=[r for r in info['symbols'] if r['symbol'] in SYMBOLS]
        if len(rules)!=2 or any(r['contractType']!='PERPETUAL' or r['quoteAsset']!='USDT' or r['marginAsset']!='USDT' for r in rules):
            raise ValueError('INSTRUMENT_IDENTITY_INVALID')
        save(cap.root/'instrument-rules.json',{'fetched_at':at,'historical_rules_verified':False,'symbols':rules})
        summary['instrument_rules']='CURRENT_RULES_VERIFIED_HISTORICAL_RULES_UNPROVEN'
    except Exception as exc:
        summary['errors']['instrument_rules']=str(exc);summary['status']='BLOCKED_DATA';publish();return summary
    for kind,endpoint,key in [('ohlcv','klines','symbol'),('mark','markPriceKlines','symbol'),
                              ('funding','fundingRate','symbol'),('index','indexPriceKlines','pair'),
                              ('premium','premiumIndexKlines','symbol')]:
        if core_only and kind in {'index','premium'}:continue
        for symbol in SYMBOLS:
            name=f'{symbol}-{kind}';all_rows=[]
            funding_start=start-24*HOUR if incremental and kind=='funding' else start
            cursor=funding_start
            if name in circuits:
                summary['errors'][name]='CIRCUIT_OPEN';continue
            try:
                while cursor<end:
                    params={key:symbol,'startTime':cursor,'endTime':end-1,'limit':1000 if kind=='funding' else 1500}
                    if kind!='funding':params['interval']='1h'
                    raw,fetched=cap.get(name,BINANCE+'/fapi/v1/'+endpoint,params)
                    if not isinstance(raw,list):raise ValueError('INVALID_RESPONSE_SHAPE')
                    if not raw:break
                    if kind=='funding':
                        rows=[]
                        for item in raw:
                            t=int(item['fundingTime'])
                            if not funding_start<=t<end:continue
                            if item['symbol']!=symbol:raise ValueError('WRONG_SYMBOL')
                            if not Decimal(item['fundingRate']).is_finite():raise ValueError('INVALID_FUNDING')
                            rows.append({'event_time':iso(t),'available_at':iso(t+HOUR),'fetched_at':fetched,
                              'source_version':'BINANCE_SETTLED_FUNDING_V1_2026-09-08','vintage':fetched,
                              'quality':'SETTLED_RECORD_SIGNAL_LAG_1H_ASSUMPTION','rate':item['fundingRate'],
                              'mark_price':item.get('markPrice'),'cost_time':iso(t)})
                        next_cursor=max(int(r['fundingTime']) for r in raw)+1
                    else:
                        rows=normalize_klines(raw,kind,fetched,start,end)
                        next_cursor=max(int(r[0]) for r in raw)+HOUR
                    if next_cursor<=cursor:raise ValueError('PAGINATION_NO_PROGRESS')
                    cursor=next_cursor;all_rows.extend(rows)
                times=[millis(r['event_time']) for r in all_rows]
                if len(set(times))!=len(times):raise ValueError('DUPLICATE_TIMESTAMPS')
                all_rows.sort(key=lambda r:r['event_time'])
                if incremental:observed_availability(all_rows)
                dump_jsonl(cap.root/f'{name}.jsonl',all_rows)
                if kind=='funding':
                    deltas=sorted(set((b-a)//1000 for a,b in zip(sorted(times),sorted(times)[1:])))
                    milliseconds=[b-a for a,b in zip(sorted(times),sorted(times)[1:])]
                    quality={'rows':len(times),'first':iso(min(times)) if times else None,'last':iso(max(times)) if times else None,
                             'observed_interval_seconds':deltas,'missing_rows':None,
                             'observed_interval_ms_counts':{str(d):milliseconds.count(d) for d in sorted(set(milliseconds))},
                             'coverage_status':'OBSERVED_SETTLEMENTS_NO_ASSUMED_FIXED_INTERVAL',
                             'overlap_start':iso(funding_start),'overlap_is_revision_observation_not_new_events':incremental,
                             'first_boundary_seconds':(min(times)-start)//1000 if times else None,
                             'last_boundary_seconds':(end-max(times))//1000 if times else None}
                else: quality=quality_times(times,start,end)
                summary['datasets'][name]={'path':f'{name}.jsonl','sha256':hashlib.sha256((cap.root/f'{name}.jsonl').read_bytes()).hexdigest(),**quality}
            except Exception as exc:summary['errors'][name]=str(exc)
            publish()
    if not core_only:
        for symbol in SYMBOLS:
            name=f'{symbol}-oi'
            if name in circuits:
                summary['errors'][name]='CIRCUIT_OPEN';continue
            try:
                raw,fetched=cap.get(name,BINANCE+'/futures/data/openInterestHist',{'symbol':symbol,'period':'1h','limit':2 if incremental else 500})
                rows=[{'event_time':iso(int(r['timestamp'])),'available_at':iso(int(r['timestamp'])+HOUR),'fetched_at':fetched,
                       'source_version':'BINANCE_OI_HIST_V1_2026-09-08','vintage':fetched,
                       'quality':'RECENT_HISTORY_1H_PUBLICATION_LAG_ASSUMPTION','open_interest':r['sumOpenInterest'],
                       'open_interest_value':r['sumOpenInterestValue']} for r in raw]
                if incremental:observed_availability(rows)
                dump_jsonl(cap.root/f'{name}.jsonl',rows)
                summary['datasets'][name]={'path':f'{name}.jsonl','rows':len(rows),
                    'first':min(r['event_time'] for r in rows) if rows else None,'last':max(r['event_time'] for r in rows) if rows else None,
                    'status':'RECENT_ONLY_BEGIN_FORWARD_CAPTURE','unit_contract_verified':False}
            except Exception as exc:summary['errors'][name]=str(exc)
            publish()
        try:
            if not slow_due or 'coinmetrics-network' in circuits:
                raise ValueError('NOT_DUE' if not slow_due else 'CIRCUIT_OPEN')
            catalog,fetched=cap.get('cm-catalog',CM+'/catalog-v2/asset-metrics',{'assets':'btc,eth','metrics':'TxCnt,AdrActCnt'})
            save(cap.root/'coinmetrics-catalog.json',{'fetched_at':fetched,'response':catalog})
            assets={r['asset'] for r in catalog.get('data',[])}
            if not {'btc','eth'}<=assets:raise ValueError('CATALOG_COVERAGE_UNCONFIRMED')
            raw,at=cap.get('cm-network',CM+'/timeseries/asset-metrics',{'assets':'btc,eth','metrics':'TxCnt,AdrActCnt',
                            'frequency':'1d','start_time':iso(end-5*24*HOUR if incremental else start),'end_time':iso(end-1),'page_size':10000})
            if raw.get('next_page_url'):raise ValueError('CM_UNCONSUMED_NEXT_PAGE')
            rows=[]
            for r in raw.get('data',[]):
                if r['asset'] not in ('btc','eth'):raise ValueError('CM_WRONG_ASSET')
                if any(r.get(m) is not None and (not Decimal(r[m]).is_finite() or Decimal(r[m])<0) for m in ('TxCnt','AdrActCnt')):
                    raise ValueError('CM_INVALID_COUNT')
                t=millis(r['time'])
                rows.append({'asset':r['asset'],'event_time':iso(t),'available_at':iso(t+2*24*HOUR),
                             'fetched_at':at,'source_version':'COINMETRICS_COMMUNITY_V4_2026-09-08','vintage':at,
                             'quality':'DEVELOPMENT_ONLY_NO_HISTORICAL_VINTAGE_48H_LAG_ASSUMPTION',
                             'TxCnt':r.get('TxCnt'),'AdrActCnt':r.get('AdrActCnt')})
            if incremental:observed_availability(rows)
            dump_jsonl(cap.root/'coinmetrics-network.jsonl',rows)
            summary['datasets']['coinmetrics-network']={'path':'coinmetrics-network.jsonl','rows':len(rows),
                'status':'DEVELOPMENT_ONLY_NO_PIT','assets':sorted({r['asset'] for r in rows}),
                'first':min(r['event_time'] for r in rows) if rows else None,'last':max(r['event_time'] for r in rows) if rows else None,
                'missing_metric_values':sum(r[m] is None for r in rows for m in ('TxCnt','AdrActCnt'))}
        except Exception as exc:
            if str(exc)!='NOT_DUE':summary['errors']['coinmetrics-network']=str(exc)
    summary['status']='CAPTURED_WITH_LIMITATIONS' if summary['datasets'] else 'BLOCKED_DATA'
    summary['completed_at']=utcnow();publish();return summary


def update(root, now=None, *, collector=collect):
    """One hourly capture; missed decisions are never replayed. Parent ticker may call often."""
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    now=now or utcnow();at=millis(now)
    # At xx:00..09 keep waiting for the just-closed bar publication buffer.
    if at % HOUR < 10*60_000:return {'status':'WAIT_CLOSED_HOUR_PUBLICATION','at':now,'requests':0}
    lock=(root/'writer.lock').open('a')
    try:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return {'status':'LOCK_CONFLICT','requests':0}
        state_path=root/'state.json'
        state=json.loads(state_path.read_text()) if state_path.exists() else {'circuits':{},'daily_requests':{},'weekly_requests':{}}
        end=(at//HOUR)*HOUR;key=iso(end).replace(':','').replace('-','')
        capture_root=root/key
        if capture_root.exists():
            committed_path=capture_root/'update-receipt.json'
            prior={}
            if committed_path.is_file():
                try:prior=json.loads(committed_path.read_text())
                except (OSError,ValueError):pass
            identity_ok=(isinstance(prior,dict) and prior.get('key')==key and
                         prior.get('root')==str(capture_root))
            result={'status':'INTERRUPTED_CAPTURE_RETAINED','key':key,'requests':0,
                    'root':str(capture_root),'core_complete':False,
                    'receipt':str(committed_path) if committed_path.is_file() else None}
            if identity_ok and prior.get('status')=='DATA_CAPTURED' and prior.get('core_complete') is True:
                result.update(status='NO_OP_ALREADY_CAPTURED',core_complete=True,errors=prior.get('errors',{}))
            elif identity_ok and prior.get('status')=='BLOCKED_DATA' and prior.get('core_complete') is False:
                result.update(status='NO_OP_BLOCKED_DATA',errors=prior.get('errors',{}))
            return result
        day=iso(end)[:10];week=datetime.fromtimestamp(end/1000,timezone.utc).strftime('%G-W%V')
        if state['daily_requests'].get(day,0)+24>576 or state['weekly_requests'].get(week,0)+24>4032:
            return {'status':'WAIT_RESOURCE_BUDGET','requests':0}
        # Startup begins with the latest completed hour; historical bootstrap is a separate immutable batch.
        last=millis(state['last_complete_end']) if state.get('last_complete_end') else end-HOUR
        start=max(last,end-24*HOUR)
        slow_due=state.get('last_slow_day')!=day
        # Reserve the full call budget before network activity so a killed process cannot erase usage.
        state['daily_requests'][day]=state['daily_requests'].get(day,0)+24
        state['weekly_requests'][week]=state['weekly_requests'].get(week,0)+24
        state['last_reserved_key']=key
        save(state_path.with_suffix('.tmp'),state);state_path.with_suffix('.tmp').replace(state_path)
        try:
            receipt=collector(capture_root,start,end,24,incremental=True,slow_due=slow_due,circuits=state['circuits'])
        except Exception as exc:
            receipt={'status':'TECHNICAL_BLOCK','errors':{'collector':type(exc).__name__+':'+str(exc)},'requests':24}
            capture_root.mkdir(exist_ok=True);save(capture_root/'failure.json',receipt)
        used=receipt.get('requests',24)
        state['daily_requests'][day]-=max(0,24-used);state['weekly_requests'][week]-=max(0,24-used)
        for name,error in receipt.get('errors',{}).items():
            if re.fullmatch(r'HTTP_(301|302|307|308|400|401|403|404|451)',error) or error.startswith(('INVALID_','INSTRUMENT_','CM_INVALID_','CM_WRONG_','CATALOG_COVERAGE_')):
                state['circuits'][name]={'reason':error,'since':now,'reset':'versioned source/permission fix required'}
        core=[f'{s}-{k}' for s in SYMBOLS for k in ('ohlcv','mark','funding')]
        datasets=receipt.get('datasets',{})
        core_ok=all(k in datasets and datasets[k].get('missing_rows') in (0,None) and
                    k not in receipt.get('errors',{}) for k in core)
        if core_ok:state['last_complete_end']=iso(end)
        if 'coinmetrics-network' in datasets:state['last_slow_day']=day
        state.update(updated_at=now,last_capture=str(capture_root),last_status=receipt.get('status'))
        save(state_path.with_suffix('.tmp'),state);state_path.with_suffix('.tmp').replace(state_path)
        result={'status':'DATA_CAPTURED' if core_ok else 'BLOCKED_DATA','key':key,'root':str(capture_root),
                'requests':used,'core_complete':core_ok,'decision_replay':False,
                'receipt':str(capture_root/'update-receipt.json'),
                'capture_use':'LATE_BACKFILL_AND_FIRST_OBSERVATION_ONLY','gap_before_start':last<start,
                'errors':receipt.get('errors',{})}
        save(capture_root/'update-receipt.json',result)
        return result
    finally:
        lock.close()

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,required=True);p.add_argument('--start');p.add_argument('--end')
    p.add_argument('--incremental',action='store_true')
    p.add_argument('--max-requests',type=int,default=120);p.add_argument('--core-only',action='store_true')
    a=p.parse_args()
    if a.incremental:
        if a.start or a.end:p.error('incremental clock owns the closed-hour window')
        print(json.dumps(update(a.root),indent=2));return
    if not a.start or not a.end:p.error('historical capture requires start and end')
    start,end=millis(a.start),millis(a.end)
    if start>=end or start%HOUR or end%HOUR or not 1<=a.max_requests<=120:p.error('invalid bounded window/budget')
    result=collect(a.root,start,end,a.max_requests,a.core_only)
    print(json.dumps({'root':str(a.root),'status':result.get('status'),'requests':result['requests'],'errors':result['errors']},indent=2))
if __name__=='__main__':main()
