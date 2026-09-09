"""Authorized five-day structure-only funding check. No retries, no OHLCV."""
from pathlib import Path
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import fcntl, hashlib, json, os, signal, subprocess, time
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError
ROOT=Path(__file__).resolve().parent
OUT=ROOT/'metadata-probe-v2'
LEDGER=Path('/Users/shenjianpeng/Documents/freqtrade-lab-local/search-research-supervision-20260902/global-research-ledger.jsonl')
DAYS=['2023-11-06','2024-11-04','2025-11-03','2026-02-09','2026-05-24']
MAX=5*1024*1024
def sha(b): return hashlib.sha256(b).hexdigest()
def now(): return datetime.now(timezone.utc).isoformat()
def encoded(x): return (json.dumps(x,sort_keys=True,separators=(',',':'))+'\n').encode()
def timeout(*a): raise TimeoutError('SINGLE_REQUEST_30_SECOND_BOUND')
signal.signal(signal.SIGALRM,timeout)
class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs): raise RuntimeError('REDIRECT_FORBIDDEN')

os.mkdir(OUT,0o700)
state={'status':'PRECHECK','created_at_utc':now(),'pair':'XRP/USDT:USDT','days':DAYS,
       'maximum_get':5,'actual_http_get':0,'decoded_bytes':0,'maximum_decoded_bytes':MAX,
       'requests':[],'automatic_retries':0,'OHLCV_acquired':False,'economic_results_computed':False,
       'S_signal_exposed':False,'D_H_exposure':'LIMITED_FUNDING_METADATA_QC_ONLY',
       'full_source_ready':False,'business_db_written':False,'adoption_sha256':sha((ROOT/'pre-value-adoption.md').read_bytes())}
start=time.monotonic()
with (Path(str(LEDGER)+'.lock')).open('a+b') as lock:
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    before=LEDGER.read_bytes()
    state['ledger_before_sha256']=sha(before)
    known=[]
    for line in before.splitlines():
        if not line.strip(): continue
        obj=json.loads(line)
        if obj.get('ban_until_utc'):
            until=datetime.fromisoformat(obj['ban_until_utc'].replace('Z','+00:00'))
            known.append(until.isoformat())
            if until>datetime.now(timezone.utc): raise RuntimeError('KNOWN_BAN_NOT_EXPIRED')
    state['known_ban_until_utc']=known
    processes=[]
    for line in subprocess.check_output(['ps','-axo','pid=,comm=,args=']).decode('utf-8',errors='replace').splitlines():
        fields=line.strip().split(None,2)
        if len(fields)<3:continue
        pid,command,args=fields
        if int(pid)==os.getpid():continue
        if ('python' in command.lower() or Path(command).name=='freqtrade') and any(t in args for t in
             ['download-data','fetch_binance_profile_data.py','capture-binance','probe_metadata_once.py','metadata-probe/']):
            processes.append({'pid':int(pid),'executable':Path(command).name})
    state['concurrent_capture_candidates']=processes
    if processes: raise RuntimeError('CONCURRENT_CAPTURE_FOUND')
    (OUT/'precheck.json').write_bytes(encoded(state))
    opener=build_opener(NoRedirect())
    try:
        for day in DAYS:
            if time.monotonic()-start>=600: raise TimeoutError('TOTAL_10_MIN_BOUND')
            first=datetime.fromisoformat(day).replace(tzinfo=timezone.utc)
            lo=int(first.timestamp()*1000);hi=int((first+timedelta(days=1)).timestamp()*1000)
            url=f'https://fapi.binance.com/fapi/v1/fundingRate?symbol=XRPUSDT&startTime={lo}&endTime={hi-1}&limit=1000'
            row={'day':day,'method':'GET','url':url,'requested_at_utc':now(),'status':'REQUESTED'}
            state['requests'].append(row);state['actual_http_get']+=1
            (OUT/'progress.json').write_bytes(encoded(state))
            signal.alarm(30)
            t=time.monotonic()
            try:
                request=Request(url,headers={'Accept':'application/json','Accept-Encoding':'identity','User-Agent':'freqtrade-lab-metadata-qc/1'})
                try: response=opener.open(request,timeout=30)
                except HTTPError as e: response=e
                with response:
                    row['http_status']=response.code
                    row['retry_after']=response.headers.get('Retry-After')
                    if response.headers.get('Content-Encoding','identity') not in ['identity','']:
                        raise RuntimeError('UNSUPPORTED_CONTENT_ENCODING_NO_RETRY')
                    remaining=MAX-state['decoded_bytes']
                    raw=response.read(remaining)
                    (OUT/(day+'.response.json')).write_bytes(raw)
                    state['decoded_bytes']+=len(raw)
                    row.update(decoded_bytes=len(raw),response_sha256=sha(raw))
                    if len(raw)>=remaining:raise RuntimeError('DECODED_BUDGET_REACHED')
                    if response.code!=200:
                        if response.code in [418,429]:
                            try:
                                error=json.loads(raw)
                                row['exchange_error_code']=error.get('code')
                                # Preserve body privately. Never echo response messages/values.
                            except Exception:pass
                        raise RuntimeError('HTTP_'+str(response.code))
                values=json.loads(raw)
                if not isinstance(values,list) or len(values)!=3:raise RuntimeError('EXPECTED_THREE_FUNDING_EVENTS')
                times=[v.get('fundingTime') for v in values]
                valid_times=all(type(t) is int and lo<=t<hi for t in times)
                buckets=[t//60000*60000 for t in times] if valid_times else []
                calendar=valid_times and times==sorted(times) and buckets==[lo,lo+28800000,lo+57600000]
                identities=all(v.get('symbol')=='XRPUSDT' and v.get('rateType','Regular')=='Regular' for v in values)
                try:
                    rates=all(Decimal(str(v['fundingRate'])).is_finite() for v in values)
                    marks=all(Decimal(str(v['markPrice'])).is_finite() and Decimal(str(v['markPrice']))>0 for v in values)
                except Exception:rates=False;marks=False
                row.update(rows=len(values),calendar_8h_3_events=calendar,identity_valid=identities,
                           finite_funding_field=rates,positive_associated_mark=marks,
                           raw_timestamp_preserved=True,minute_bucket_contract_unchanged=True)
                if not marks:raise RuntimeError('ASSOCIATED_MARK_MISSING_OR_INVALID')
                if not all([calendar,identities,rates]):raise RuntimeError('STRUCTURE_OR_SEQUENCE_INVALID')
                row['status']='METADATA_QC_PASS'
            finally:
                signal.alarm(0);row['wall_seconds']=round(time.monotonic()-t,6)
                (OUT/'progress.json').write_bytes(encoded(state))
        state['status']='LIMITED_METADATA_QC_PASS_NOT_FULL_COVERAGE'
    except Exception as exc:
        state['status']='BLOCKED_DATA'
        state['failure_reason']=str(exc) if isinstance(exc,RuntimeError) else type(exc).__name__
        if state['requests']:state['requests'][-1]['status']='FAILED_STOP_REMAINING'
    state['wall_seconds']=round(time.monotonic()-start,6)
    state['remaining_requests_executed']=False
    raw_receipt=encoded(state)
    (OUT/'receipt.json').write_bytes(raw_receipt)
    record={'record_type':'DATA_METADATA_ONLY','recorded_at_utc':now(),
        'cohort_id':'xrp-weekly-persistence-design-d699-20260907','pair':state['pair'],
        'status':state['status'],'exposure':'LIMITED_FUNDING_METADATA_QC_ONLY',
        'requested_utc_days':[r['day'] for r in state['requests']],
        'actual_http_get':state['actual_http_get'],'decoded_bytes':state['decoded_bytes'],
        'failure_reason':state.get('failure_reason'),'automatic_retries':0,
        'D_H_exposure':state['D_H_exposure'],'OHLCV_acquired':False,'S_signal_exposed':False,
        'search_window_consumed':False,'economic_results_computed':False,'business_db_written':False,
        'receipt_path':str(OUT/'receipt.json'),'receipt_sha256':sha(raw_receipt),
        'authorization':'Supervisor 01a05dcc explicit five GET metadata and original-lock append; no market Search',
        'previous_prefix_sha256':sha(before)}
    line=encoded(record)
    if LEDGER.read_bytes()!=before:raise RuntimeError('LEDGER_CHANGED_WHILE_LOCKED')
    with LEDGER.open('ab') as f:f.write(line);f.flush();os.fsync(f.fileno())
    after=LEDGER.read_bytes()
    assert after==before+line
    (OUT/'ledger-append-receipt.json').write_bytes(encoded({'before_sha256':sha(before),
        'after_sha256':sha(after),'previous_bytes_preserved':True,'appended_records':1,
        'appended_record_sha256':sha(line),'receipt_sha256':sha(raw_receipt)}))
    fcntl.flock(lock,fcntl.LOCK_UN)
print(json.dumps({'status':state['status'],'GET':state['actual_http_get'],
                  'decoded_bytes':state['decoded_bytes'],'failure_reason':state.get('failure_reason'),
                  'receipt':str(OUT/'receipt.json'),'ledger_sha256':sha(after)}))
