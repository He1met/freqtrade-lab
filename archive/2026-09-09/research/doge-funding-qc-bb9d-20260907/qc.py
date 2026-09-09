import hashlib, json, math, time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
import ccxt
from requests.adapters import HTTPAdapter

ROOT=Path(__file__).parent
LO=int(datetime(2023,11,6,tzinfo=timezone.utc).timestamp()*1000)
HI=int(datetime(2024,11,4,tzinfo=timezone.utc).timestamp()*1000)
LIMIT=2*1024*1024
def now(): return datetime.now(timezone.utc).isoformat()
def write(name,obj):
    with (ROOT/name).open('x') as f: json.dump(obj,f,ensure_ascii=False,sort_keys=True,indent=2)
started=now(); tick=time.monotonic(); receipts=[]; total=0; expected_start=LO
write('authorization.json',{'supervisor':'01a05dcc-17fd-7972-9177-9fed95e4b07a','issue':98,
 'authorized_phase':'DOGE S funding-only QC','start_ms':LO,'end_exclusive_ms':HI,
 'max_actual_http_get':3,'max_decoded_bytes':LIMIT,'wall_seconds':600,'retries':0,'redirects':0,
 'D_H_OHLCV_Candidate_Search':'NOT_AUTHORIZED','external_unregistered_exposure':'UNKNOWN',
 'proposal_sha256':'6d7a927f68a6d62b8508414eed713fecac1ba67c5f5d419ac598bbf42de48f75',
 'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'started_at':started})
exchange=ccxt.binance({'enableRateLimit':False,'timeout':30000,'maxRetriesOnFailure':0})
exchange.session.trust_env=False
exchange.session.mount('https://',HTTPAdapter(max_retries=0))
original=exchange.session.request
def guarded(method,url,**kwargs):
    global total
    p=urlsplit(url); q=parse_qs(p.query)
    assert method=='GET' and p.scheme=='https' and p.netloc=='fapi.binance.com' and not p.fragment
    assert len(receipts)<3 and time.monotonic()-tick<600
    assert not kwargs.get('data') and not kwargs.get('files')
    assert not any(k.lower() in ('authorization','x-mbx-apikey','cookie') for k in (kwargs.get('headers') or {}))
    if not receipts: assert p.path=='/fapi/v1/exchangeInfo' and not q
    else:
        assert p.path=='/fapi/v1/fundingRate'
        assert q=={'symbol':['DOGEUSDT'],'startTime':[str(expected_start)],'endTime':[str(HI-1)],'limit':['1000']}
        assert LO<=expected_start<HI
    item={'sequence':len(receipts)+1,'method':method,'url':url,'started_at':now()}
    receipts.append(item)
    with (ROOT/'requests.jsonl').open('a') as f: f.write(json.dumps(item)+'\n')
    kwargs.update(allow_redirects=False,stream=True,timeout=(10,30))
    response=None; chunks=[]
    try:
        response=original(method,url,**kwargs)
        item['http_status']=response.status_code
        item['retry_after']=response.headers.get('Retry-After')
        for chunk in response.iter_content(chunk_size=4096):
            if time.monotonic()-tick>=600: raise RuntimeError('WALL_BUDGET')
            if len(chunk)>LIMIT-total:
                chunks.append(chunk[:LIMIT-total]); total=LIMIT
                raise RuntimeError('DECODED_BYTE_BUDGET')
            total+=len(chunk);chunks.append(chunk)
            if total>=LIMIT: raise RuntimeError('DECODED_BYTE_BUDGET')
        raw=b''.join(chunks);response._content=raw;response._content_consumed=True
        if not 200<=response.status_code<300: raise RuntimeError('HTTP_STATUS_REJECTED')
        return response
    finally:
        raw=b''.join(chunks); name=f'response-{item["sequence"]}.json'
        (ROOT/name).write_bytes(raw)
        item.update(body_file=name,decoded_bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest(),finished_at=now())
        if response is not None: response.close()
        write(f'receipt-{item["sequence"]}.json',item)

exchange.session.request=guarded
report={'started_at':started,'status':'BLOCKED_DATA','market_requests_before_this_gate':0,
 'external_unregistered_exposure':'UNKNOWN','new_market_PnL_observed':False,'D_H_OHLCV_Candidate_Search':0}
try:
    assert ccxt.__version__=='4.5.68'
    info=exchange.fapiPublicGetExchangeInfo()
    matches=[x for x in info['symbols'] if x.get('symbol')=='DOGEUSDT']
    assert len(matches)==1
    m=matches[0]
    report['market']={k:m.get(k) for k in ['symbol','status','contractType','baseAsset','quoteAsset','marginAsset']}
    assert report['market']=={'symbol':'DOGEUSDT','status':'TRADING','contractType':'PERPETUAL','baseAsset':'DOGE','quoteAsset':'USDT','marginAsset':'USDT'}
    rows=[]
    for page in range(2):
        batch=exchange.fapiPublicGetFundingRate({'symbol':'DOGEUSDT','startTime':expected_start,'endTime':HI-1,'limit':1000})
        assert isinstance(batch,list) and 0<len(batch)<=1000
        times=[x.get('fundingTime') for x in batch]
        assert all(isinstance(t,int) and expected_start<=t<HI for t in times)
        assert times==sorted(set(times))
        rows+=batch
        expected_start=times[-1]+1
        if len(batch)<1000:break
    clocks=[x['fundingTime'] for x in rows]
    buckets=[t//60000*60000 for t in clocks]
    expected=set(range(LO,HI,28800000))
    def finite_positive(x):
        try:return math.isfinite(float(x)) and float(x)>0
        except (ValueError,TypeError):return False
    def finite(x):
        try:return math.isfinite(float(x))
        except (ValueError,TypeError):return False
    report['qc']={'expected_events':len(expected),'actual_events':len(rows),
      'strictly_ascending':clocks==sorted(set(clocks)),'duplicate_timestamps':len(clocks)-len(set(clocks)),
      'duplicate_native_minute_buckets':len(buckets)-len(set(buckets)),
      'missing_8h_buckets':len(expected-set(buckets)),'extra_buckets':len(set(buckets)-expected),
      'wrong_symbol_count':sum(x.get('symbol')!='DOGEUSDT' for x in rows),
      'nonregular_count':sum(x.get('rateType','Regular')!='Regular' for x in rows),
      'invalid_associated_mark_count':sum(not finite_positive(x.get('markPrice')) for x in rows),
      'nonfinite_funding_count':sum(not finite(x.get('fundingRate')) for x in rows),
      'first_utc':datetime.fromtimestamp(clocks[0]/1000,timezone.utc).isoformat(),
      'last_utc':datetime.fromtimestamp(clocks[-1]/1000,timezone.utc).isoformat(),
      'native_minute_mapping':'existing BINANCE_ASSOCIATED_MARK_BOUNDARY_V1; raw unchanged'}
    write('utc-sequence.json',{'raw_timestamps_ms':clocks,'missing_native_buckets_ms':sorted(expected-set(buckets)),
      'extra_native_buckets_ms':sorted(set(buckets)-expected)})
    q=report['qc']
    if len(rows)==1092 and q['strictly_ascending'] and all(q[k]==0 for k in ['duplicate_timestamps','duplicate_native_minute_buckets','missing_8h_buckets','extra_buckets','wrong_symbol_count','nonregular_count','invalid_associated_mark_count','nonfinite_funding_count']):
        report['status']='FUNDING_CALENDAR_ASSOCIATED_MARK_QC_PASS_NOT_SOURCE_READY'
    else: report['failure']='FUNDING_METADATA_CONTRACT_FAILED'
except Exception as exc:
    report['failure_type']=type(exc).__name__
    report['failure']='REQUEST_OR_METADATA_VALIDATION_FAILED' # Do not expose CCXT raw-response exception text.
finally:
    report.update(finished_at=now(),elapsed_seconds=round(time.monotonic()-tick,3),actual_http_get=len(receipts),
       decoded_bytes=total,retries=0,redirects_followed=0,ccxt_version=ccxt.__version__,receipts=receipts)
    write('qc-report.json',report)
    print(json.dumps(report,ensure_ascii=False,indent=2))
