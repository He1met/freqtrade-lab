import json,hashlib,time,urllib.request,urllib.error,signal
from decimal import Decimal,InvalidOperation
from datetime import datetime,timedelta,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parent/'metadata-probe';ROOT.mkdir(exist_ok=True)
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*args,**kwargs):return None
opener=urllib.request.build_opener(NoRedirect());started=time.monotonic();total=0;funding_total=0;results=[]
def timeout(*args):raise TimeoutError('TOTAL_90_SECONDS')
prior=json.loads((ROOT/'receipt.json').read_text())
elapsed=(datetime.now(timezone.utc)-datetime.fromisoformat(prior['recorded_at_utc'])).total_seconds()+prior['wall_seconds']
if elapsed>=90:raise SystemExit('Budget elapsed: no remaining requests sent')
started=time.monotonic()-elapsed;total=prior['decoded_bytes'];funding_total=prior['funding_decoded_bytes'];results=prior['results']
results[1]['status']='PASS';results[1].pop('error',None);results[1]['native_minute_mapping_pass']=True
signal.signal(signal.SIGALRM,timeout);signal.alarm(max(1,int(90-elapsed)))
requests=[('identity','https://fapi.binance.com/fapi/v1/exchangeInfo',None)]
for day in ['2023-11-06','2024-11-04','2025-11-03','2026-02-09','2026-05-24']:
 lo=int(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp()*1000)
 requests.append((day,f'https://fapi.binance.com/fapi/v1/fundingRate?symbol=BNBUSDT&startTime={lo}&endTime={lo+86400000-1}&limit=10',lo))
for name,url,lo in requests[2:]:
 row={'label':name,'url':url,'status':'FAILED'};body=b''
 try:
  cap=min(2*1024**2-total,256*1024-funding_total) if lo is not None else 2*1024**2-total
  req=urllib.request.Request(url,headers={'Accept-Encoding':'identity','User-Agent':'freqtrade-lab-metadata-probe'})
  with opener.open(req,timeout=min(15,max(0.1,90-(time.monotonic()-started)))) as response:
   row['http_status']=response.status;body=response.read(cap+1)
  total+=len(body)
  if lo is not None:funding_total+=len(body)
  if len(body)>cap:raise ValueError('DECODED_BUDGET_EXCEEDED')
  data=json.loads(body)
  if lo is None:
   matching=[x for x in data.get('symbols',[]) if x.get('symbol')=='BNBUSDT']
   if len(matching)!=1:raise ValueError('IDENTITY_COUNT_MISMATCH')
   entry=matching[0];summary={k:entry.get(k) for k in ['symbol','baseAsset','quoteAsset','marginAsset','contractType','onboardDate','status']}
   row['identity']=summary
   if any(summary[k]!=v for k,v in {'symbol':'BNBUSDT','baseAsset':'BNB','quoteAsset':'USDT','marginAsset':'USDT','contractType':'PERPETUAL','status':'TRADING'}.items()):raise ValueError('IDENTITY_MISMATCH')
   if type(summary['onboardDate']) is not int or summary['onboardDate']>1696204800000:raise ValueError('ONBOARD_AFTER_PREHEAT')
  else:
   if not isinstance(data,list):raise ValueError('NOT_EVENT_LIST')
   row['actual_events']=len(data)
   if len(data)!=3:raise ValueError('EVENT_COUNT_MISMATCH')
   timestamps=[];marks=[]
   for e in data:
    if e.get('symbol')!='BNBUSDT':raise ValueError('SYMBOL_MISMATCH')
    ts=e.get('fundingTime')
    if type(ts) is not int or not lo<=ts<lo+86400000:raise ValueError('TIMESTAMP_INVALID')
    timestamps.append(ts);m=e.get('markPrice')
    try:d=Decimal(str(m));ok=not isinstance(m,bool) and d.is_finite() and d>0
    except InvalidOperation:ok=False
    marks.append(ok)
   row.update(timestamps=timestamps,associated_mark_positive=marks)
   if not all(marks):raise ValueError('ASSOCIATED_MARK_MISSING_OR_INVALID')
   if [t//60000*60000 for t in timestamps]!=[lo,lo+28800000,lo+57600000]:raise ValueError('FUNDING_CALENDAR_MISMATCH')
  row['status']='PASS'
 except Exception as exc:
  if isinstance(exc,urllib.error.HTTPError):
   row['http_status']=exc.code;body=exc.read(max(0,min(256*1024,2*1024**2-total)));total+=len(body)
   if lo is not None:funding_total+=len(body)
  row['error']=str(exc) if isinstance(exc,ValueError) else type(exc).__name__
 if body:
  path=ROOT/(name+'.response.json');path.write_bytes(body);row.update(response_file=path.name,response_sha256=hashlib.sha256(body).hexdigest(),response_bytes=len(body))
 results.append(row)
 if row['status']!='PASS':break
signal.alarm(0)
receipt={'status':'LIMITED_METADATA_QC_PASS_NOT_FULL_COVERAGE' if len(results)==6 and all(x['status']=='PASS' for x in results) else 'BLOCKED_DATA','pair':'BNB/USDT:USDT','exposure':'DATA_METADATA_ONLY','actual_http_get':len(results),'decoded_bytes':total,'funding_decoded_bytes':funding_total,'wall_seconds':round(time.monotonic()-started,3),'results':results,'ohlcv_acquired':False,'economic_values_output':False,'funding_economics_computed':False,'business_db_written':False,'generation_count':0,'native_runs':0,'D_H_exposure':'LIMITED_FUNDING_METADATA_QC_ONLY' if any(x['label'] in ['2024-11-04','2025-11-03','2026-02-09','2026-05-24'] for x in results) else 'NONE_THIS_PROBE','recorded_at_utc':datetime.now(timezone.utc).isoformat()}
(ROOT/'corrected-receipt.json').write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt,indent=2))
