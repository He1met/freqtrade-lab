from pathlib import Path
import importlib.util,json,sys,hashlib,io,csv,zipfile
from datetime import datetime,UTC
ROOT=Path(__file__).parent
REPO=Path('/Users/shenjianpeng/.codex/worktrees/6dc2/freqtrade-lab')
s=importlib.util.spec_from_file_location('producer',REPO/'scripts/fetch_okx_profile_data.py'); p=importlib.util.module_from_spec(s);s.loader.exec_module(p)
base=sys.argv[1]; out=ROOT/('precheck-'+base.lower());out.mkdir(mode=0o700)
def save(name,value): (out/name).write_text(json.dumps(value,indent=2,sort_keys=True))
p.DATA_START=datetime(2024,2,1,tzinfo=UTC);p.SEARCH_START=datetime(2024,4,1,tzinfo=UTC);p.DEVELOPMENT_START=datetime(2025,4,1,tzinfo=UTC);p.DATA_END=datetime(2026,4,1,tzinfo=UTC)
p.DATA_START_MS=int(p.DATA_START.timestamp()*1000);p.DATA_END_MS=int(p.DATA_END.timestamp()*1000);p.MARK_START_MS=p.DATA_START_MS
p.SYMBOL=f'{base}/USDT:USDT';p.INSTRUMENT_ID=f'{base}-USDT-SWAP';p.PAIR_FAMILY=f'{base}-USDT';p.FUTURES_TIMEFRAME='1d';p.PROFILE_ACQUISITION={'mode':'ISOLATED_DATA_ONLY_SYNTHETIC_CONFIGURATION'}
requests=[];captures=[];original=p.archive_http_request
# Record raw official response bytes without interpreting funding values.
def capture(method,url,**kw):
 raw,headers=original(method,url,**kw); num=len(captures)+1
 name=f'http-{num:03d}'+('.zip' if method=='GET' else '.json');(out/name).write_bytes(raw)
 rec={'method':method,'url':url,'file':name,'sha256':p.sha256(raw),'bytes':len(raw),'headers':headers}
 if kw.get('body') is not None: (out/f'http-{num:03d}-request.json').write_bytes(kw['body'])
 captures.append(rec);save('http-receipts.json',captures)
 return raw,headers
p.archive_http_request=capture
result={'pair':p.SYMBOL,'instrument_id':p.INSTRUMENT_ID,'timeframe':'1d','mode':'DATA_ONLY','status':'RUNNING','months':[],'protected_rates':'UNINTERPRETED','runtime':p.validate_runtime()}
save('result.json',result)
try:
 ex=p.transport.ccxt.okx({'enableRateLimit':True,'timeout':30000,'options':{'defaultType':'swap'}});p.install_request_guard(ex)
 try:
  resp=p.assert_okx_response(ex.public_get_public_instruments({'instType':'SWAP','instId':p.INSTRUMENT_ID}),'instrument');requests.append(p.request_receipt(ex,'instrument')); save('instrument-response.json',resp)
  assert len(resp['data'])==1
  inst=resp['data'][0];market=ex.parse_market(inst)
  assert inst['instId']==p.INSTRUMENT_ID and inst['state']=='live' and inst['settleCcy']=='USDT'
  assert market['symbol']==p.SYMBOL and market['swap'] is True and market['linear'] is True
  assert int(inst['listTime'])<=p.DATA_START_MS
  result['instrument']={k:inst.get(k) for k in ['instId','instType','state','settleCcy','listTime']}
 finally: ex.close()
 allrows=[];first=int(p.SEARCH_START.timestamp()*1000)
 for year,month in p._archive_months():
  entry=p._archive_catalog_group([(year,month)],requests)[0];_,_,url,an,cn=entry
  raw,headers=p.archive_http_request('GET',url)
  assert headers.get('content-type','').lower().startswith('application/zip')
  try:
   rows,receipt=p._parse_funding_archive(raw,archive_name=an,csv_name=cn,year=year,month=month,start_ms=first,end_exclusive_ms=p.DATA_END_MS)
  except RuntimeError:
   # Diagnostic selected timestamps only; rates are never parsed here.
   with zipfile.ZipFile(io.BytesIO(raw)) as z:
    reader=csv.reader(io.StringIO(z.read(cn).decode()));next(reader)
    for n,fields in enumerate(reader,2):
     ts=int(fields[2]); drift=ts%p.FUNDING_INTERVAL_MS
     if first<=ts<p.DATA_END_MS and first<=ts-drift<p.DATA_END_MS and drift>2000:
      result['first_unsupported_timestamp']={'month':f'{year:04d}-{month:02d}','csv_line':n,'timestamp_ms':ts,'drift_ms':drift,'maximum_allowed_drift_ms':2000};break
   raise
  # Fail at first incomplete month, without auditing subsequent failed months.
  times=[x['timestamp'] for x in rows]; localstart=p.datetime(year,month,1,tzinfo=p.ARCHIVE_TIMEZONE)
  ny,nm=p._month_after((year,month)); localend=p.datetime(ny,nm,1,tzinfo=p.ARCHIVE_TIMEZONE)
  expected=list(range(max(first,int(localstart.timestamp()*1000)),min(p.DATA_END_MS,int(localend.timestamp()*1000)),p.FUNDING_INTERVAL_MS))
  if sorted(times)!=expected or len(set(times))!=len(times):raise RuntimeError(f'funding archive {year:04d}-{month:02d} missing/duplicate timestamps; expected={len(expected)} actual={len(times)}')
  allrows.extend(rows);result['months'].append(receipt);save('result.json',result);save('request-receipts.json',requests)
  print(base,f'{year:04d}-{month:02d}','INTEGRITY_PASS',len(rows),flush=True)
 p.validate_funding_history(sorted(allrows,key=lambda x:x['timestamp']))
 result['status']='FUNDING_INTEGRITY_PASS';result['rows']=len(allrows)
except Exception as e:
 result['status']='BLOCKED_DATA';result['error']=type(e).__name__+': '+str(e)
finally:
 save('result.json',result);save('request-receipts.json',requests)
 print(json.dumps({k:v for k,v in result.items() if k not in ['months','runtime']}),flush=True)
