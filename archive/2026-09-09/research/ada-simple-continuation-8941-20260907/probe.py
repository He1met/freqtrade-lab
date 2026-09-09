import json, hashlib, time, urllib.request, urllib.error
from decimal import Decimal, InvalidOperation
from datetime import datetime, timedelta, timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parent/'metadata-probe'
ROOT.mkdir(exist_ok=False)
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs): return None
opener=urllib.request.build_opener(NoRedirect())
days=['2021-01-04','2022-01-03','2023-01-02','2023-04-03','2023-06-30']
started=time.monotonic(); total=0; results=[]
for day in days:
    if time.monotonic()-started>=75: break
    start=datetime.fromisoformat(day).replace(tzinfo=timezone.utc)
    lo=int(start.timestamp()*1000); hi=int((start+timedelta(days=1)).timestamp()*1000)
    url=f'https://fapi.binance.com/fapi/v1/fundingRate?symbol=ADAUSDT&startTime={lo}&endTime={hi-1}&limit=10'
    row={'day':day,'url':url,'status':'FAILED','expected_events':3}
    body=b''
    try:
        req=urllib.request.Request(url,headers={'Accept-Encoding':'identity','User-Agent':'freqtrade-lab-metadata-probe'})
        with opener.open(req,timeout=15) as response:
            row['http_status']=response.status
            body=response.read(256*1024-total+1)
        total+=len(body)
        if total>256*1024: raise ValueError('DECODED_BUDGET_EXCEEDED')
        data=json.loads(body)
        if not isinstance(data,list): raise ValueError('NOT_EVENT_LIST')
        row['actual_events']=len(data)
        if len(data)!=3: raise ValueError('EVENT_COUNT_MISMATCH')
        times=[]
        for event in data:
            if event.get('symbol')!='ADAUSDT': raise ValueError('SYMBOL_MISMATCH')
            ts=event.get('fundingTime')
            if type(ts) is not int or not lo<=ts<hi: raise ValueError('TIMESTAMP_INVALID')
            times.append(ts)
            mark=event.get('markPrice')
            if not isinstance(mark,(str,int,float)) or isinstance(mark,bool): raise ValueError('ASSOCIATED_MARK_MISSING_OR_INVALID')
            try: numeric=Decimal(str(mark))
            except InvalidOperation: raise ValueError('ASSOCIATED_MARK_MISSING_OR_INVALID')
            if not numeric.is_finite() or numeric<=0: raise ValueError('ASSOCIATED_MARK_MISSING_OR_INVALID')
        if times!=[lo,lo+28800000,lo+57600000]: raise ValueError('FUNDING_CALENDAR_MISMATCH')
        row.update(status='PASS',associated_mark_all_finite_positive=True,timestamp_calendar_pass=True)
    except Exception as exc:
        if isinstance(exc,urllib.error.HTTPError):
            row['http_status']=exc.code
            body=exc.read(max(0,256*1024-total)); total+=len(body)
        row['error']=str(exc) if isinstance(exc,ValueError) else type(exc).__name__
    if body:
        file=ROOT/(day+'.response.json');file.write_bytes(body)
        row.update(response_file=file.name,response_sha256=hashlib.sha256(body).hexdigest(),response_bytes=len(body))
    results.append(row)
    if row['status']!='PASS': break
receipt={'status':'REPRESENTATIVE_DAYS_PASS_NOT_FULL_COVERAGE' if len(results)==5 and all(r['status']=='PASS' for r in results) else 'NO_GO_CURRENT_WINDOW_CONTRACT', 'exposure':'DATA_METADATA_ONLY','pair':'ADA/USDT:USDT','actual_http_get':len(results),'decoded_bytes':total,'wall_seconds':round(time.monotonic()-started,3),'results':results,'funding_economics_computed':False,'ohlcv_acquired':False,'business_db_written':False,'holdout_strategy_opened':False,'remaining_requests_executed':False if len(results)<5 else None,'recorded_at_utc':datetime.now(timezone.utc).isoformat()}
(ROOT/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
print(json.dumps(receipt,indent=2))
