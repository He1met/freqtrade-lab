import pathlib,json,hashlib,fcntl,subprocess,datetime,time,signal,http.client,urllib.parse,zipfile,io,csv,stat,re,decimal,math
R=pathlib.Path(__file__).parent
L=pathlib.Path('/Users/shenjianpeng/Documents/freqtrade-lab-local/search-research-supervision-20260902/global-research-ledger.jsonl')
ID='BCH-S-FUNDING-QC-202308-V1'
URL='https://static.okx.com/cdn/okex/traderecords/swaprates/monthly/202308/BCH-USDT-SWAP-fundingrates-2023-08.zip?v=999'
sha=lambda b:hashlib.sha256(b).hexdigest()
now=lambda:datetime.datetime.now(datetime.timezone.utc).isoformat()
def save(n,v): (R/n).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
def append(event,label,expected):
 with open(str(L)+'.lock','r+b') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  before=L.read_bytes()
  if sha(before)!=expected: raise RuntimeError('LEDGER_CHANGED_REQUIRES_NEW_IDENTITY_PROJECTION')
  records=[json.loads(x) for x in before.splitlines() if x.strip()]
  if any(x.get('qc_id')==ID and x.get('event')==event['event'] for x in records):raise RuntimeError('DUPLICATE_QC_EVENT')
  if label=='registration' and any(ID in str(v) or 'BCH-USDT-SWAP' in str(v) for x in records for k,v in x.items() if k in ('qc_id','cohort_id','instrument_id','instrument','source_url','official_object')):raise RuntimeError('IDENTITY_CONFLICT_REVIEW_REQUIRED')
  assert before.endswith(b'\n')
  line=json.dumps(event,ensure_ascii=False,separators=(',',':')).encode()+b'\n'
  # apply_patch context generated from opaque final line, never displayed to model.
  anchor=before.splitlines()[-1].decode()
  patch='*** Begin Patch\n*** Update File: '+str(L)+'\n@@\n '+anchor+'\n+'+line.decode().rstrip('\n')+'\n*** End Patch\n'
  (R/(label+'-before.bin')).write_bytes(before)
  p=subprocess.run(['apply_patch'],input=patch,text=True,capture_output=True)
  if p.returncode:raise RuntimeError('APPLY_PATCH_FAILED')
  after=L.read_bytes()
  if after!=before+line:raise RuntimeError('PREFIX_OR_APPEND_MISMATCH')
  receipt={'before_bytes':len(before),'before_sha256':sha(before),'after_bytes':len(after),'after_sha256':sha(after),'preserved_prefix_sha256':sha(after[:len(before)]),'old_bytes_including_blank_lines_preserved':True,'appended_bytes':len(line),'append_method':'apply_patch under existing flock sidecar','time_utc':now()}
  save(label+'-ledger-receipt.json',receipt)
  return sha(after)
base={'qc_id':ID,'thread_id':'01a07563-65c4-7193-a35c-2ae23f44a0e8','instrument_id':'BCH-USDT-SWAP','official_object':URL,'archive_month':'2023-08','phase':'S','proposed_S_window':['2023-07-17T00:00:00Z','2024-07-15T00:00:00Z'],'exposure':'DATA_QC_ONLY','search_consumed':False,'strategy_runs':0,'root':str(R)}
reg={**base,'event':'DATA_QC_REGISTERED_PRE_GET','time_utc':now(),'raw_sha256':'UNKNOWN','budget':{'http_get':1,'zip':1,'qc_seconds':600,'compressed_bytes':10000000,'uncompressed_bytes':20000000,'members':1,'retries':0,'redirects':0},'prior_unregistered_exposure':'UNKNOWN','rate_outputs_to_model':False}
ledger_sha=append(reg,'registration','2f2e1ee577ca324f82e25f1222058b159cff0949a6b502a43eee9ba58c584205')
save('registration.json',reg)
q={**base,'started_utc':now(),'http_attempts':0,'retries':0,'redirects_followed':0,'transport':'stdlib http.client.HTTPSConnection single request; no retry/redirect mechanism; direct connection; no producer or floor','raw_sha256':'UNKNOWN','status':'BLOCKED','rate_values_displayed':False}
start=time.monotonic()
def timeout(*args):raise RuntimeError('QC_600_SECONDS_LIMIT')
signal.signal(signal.SIGALRM,timeout);signal.alarm(600)
try:
 u=urllib.parse.urlsplit(URL);c=http.client.HTTPSConnection(u.hostname,timeout=45)
 q['http_attempts']=1;q['request_started_utc']=now();save('qc-receipt.json',q)
 c.request('GET',u.path+'?'+u.query,headers={'Accept-Encoding':'identity','User-Agent':'freqtrade-lab-bounded-data-qc/1'})
 resp=c.getresponse();q['http_status']=resp.status;q['response_headers']={k:resp.getheader(k) for k in ('Date','Content-Type','Content-Length','Content-Encoding','Location','Retry-After','ETag','Last-Modified') if resp.getheader(k) is not None}
 limit=10000000;length=resp.getheader('Content-Length')
 if length is not None and (not length.isdigit() or int(length)>limit):raise RuntimeError('COMPRESSED_SIZE_HEADER_LIMIT')
 raw=R/'response-body.bin';count=0
 with raw.open('xb') as f:
  while count<limit:
   chunk=resp.read(min(65536,limit-count))
   if not chunk:break
   f.write(chunk);count+=len(chunk)
  if count==limit and (length is None or int(length)!=limit):raise RuntimeError('COMPRESSED_HARD_LIMIT_REACHED')
 c.close();q['response_bytes']=count;q['raw_sha256']=sha(raw.read_bytes());q['response_complete']=length is None or count==int(length)
 if not q['response_complete']:raise RuntimeError('TRUNCATED_RESPONSE')
 if resp.status!=200:raise RuntimeError('HTTP_STATUS_'+str(resp.status))
 if resp.getheader('Content-Encoding','identity')!='identity':raise RuntimeError('UNEXPECTED_CONTENT_ENCODING')
 raw.rename(R/'BCH-USDT-SWAP-fundingrates-2023-08.zip');q['raw_file']='BCH-USDT-SWAP-fundingrates-2023-08.zip'
 with zipfile.ZipFile(R/q['raw_file']) as z:
  members=z.infolist();q['members']=[{'name':m.filename,'compressed_bytes':m.compress_size,'uncompressed_bytes':m.file_size} for m in members]
  if len(members)!=1:raise RuntimeError('MEMBER_COUNT_LIMIT_OR_MISMATCH')
  m=members[0];p=pathlib.PurePosixPath(m.filename)
  if p.is_absolute() or '..' in p.parts or '\\' in m.filename or m.is_dir() or stat.S_ISLNK(m.external_attr>>16) or m.flag_bits&1:raise RuntimeError('UNSAFE_ZIP_MEMBER')
  if m.filename!='BCH-USDT-SWAP-fundingrates-2023-08.csv':raise RuntimeError('CSV_MEMBER_IDENTITY_MISMATCH')
  if not 0<m.file_size<=20000000:raise RuntimeError('UNCOMPRESSED_SIZE_LIMIT')
  with z.open(m) as f: content=f.read(20000000)
  if len(content)!=m.file_size:raise RuntimeError('UNCOMPRESSED_SIZE_MISMATCH')
 q['zip_crc_checked']=True;q['csv_sha256']=sha(content)
 rows=list(csv.reader(io.StringIO(content.decode('utf-8')),strict=True));header=rows.pop(0);q['csv_fields']=header
 if header!=['instrument_name','funding_rate','funding_time']:raise RuntimeError('CSV_HEADER_MISMATCH')
 stamps=[];identities=set()
 for row in rows:
  if len(row)!=3:raise RuntimeError('CSV_ROW_SHAPE')
  identities.add(row[0])
  if row[0]!='BCH-USDT-SWAP':raise RuntimeError('INSTRUMENT_MISMATCH')
  if not re.fullmatch(r'[0-9]{13}',row[2]):raise RuntimeError('RAW_TIME_FORMAT')
  stamps.append(int(row[2]))
 if not stamps:raise RuntimeError('EMPTY_CSV')
 utc=lambda x:datetime.datetime.fromtimestamp(x/1000,datetime.timezone.utc).isoformat()
 S=lambda s:int(datetime.datetime.fromisoformat(s.replace('Z','+00:00')).timestamp()*1000)
 outside=sum(not S(base['proposed_S_window'][0])<=t<S(base['proposed_S_window'][1]) for t in stamps)
 intervals=[b-a for a,b in zip(stamps,stamps[1:])];ordered=sorted(set(stamps));diffs=sorted(set(b-a for a,b in zip(ordered,ordered[1:])))
 q['structure']={'rows':len(rows),'identities':sorted(identities),'raw_time_format':'13 ASCII digits interpreted as Unix milliseconds, no modification','raw_min_ms':min(stamps),'raw_max_ms':max(stamps),'utc_min':utc(min(stamps)),'utc_max':utc(max(stamps)),'utc_plus_8_min':datetime.datetime.fromtimestamp(min(stamps)/1000,datetime.timezone(datetime.timedelta(hours=8))).isoformat(),'utc_plus_8_max':datetime.datetime.fromtimestamp(max(stamps)/1000,datetime.timezone(datetime.timedelta(hours=8))).isoformat(),'duplicate_timestamps':len(stamps)-len(set(stamps)),'duplicate_full_rows':len(rows)-len(set(map(tuple,rows))),'file_strictly_ascending':all(x>0 for x in intervals),'file_strictly_descending':all(x<0 for x in intervals),'file_interval_ms_unique':sorted(set(intervals)),'chronological_interval_ms_unique':diffs,'offset_from_utc_8h_grid_ms_unique':sorted(set(t%28800000 for t in stamps)),'outside_S_rows':outside,'all_in_utc_plus_8_archive_month':all(datetime.datetime.fromtimestamp(t/1000,datetime.timezone(datetime.timedelta(hours=8))).strftime('%Y-%m')=='2023-08' for t in stamps)}
 if outside:raise RuntimeError('OUTSIDE_S_STOP_BEFORE_ALL_RATE_PARSING')
 q['rate_validation']='STARTED_ONLY_AFTER_ALL_IDENTITIES_AND_TIMES_VALIDATED_IN_S'
 for row in rows:
  if not re.fullmatch(r'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?',row[1]):raise RuntimeError('RATE_DECIMAL_SYNTAX')
  d=decimal.Decimal(row[1])
  if not d.is_finite() or decimal.Decimal(str(d))!=d:raise RuntimeError('RATE_FINITE_EXACT_DECIMAL_CHECK')
  if not math.isfinite(float(row[1])):raise RuntimeError('CONSUMER_FLOAT_NOT_FINITE')
 q['rate_validation']='PASS_FINITE_EXACT_DECIMAL_AND_FINITE_CONSUMER_FLOAT; NO_VALUES_OR_DISTRIBUTION_OUTPUT; NOT_ASSERTING_FLOAT_EXACTNESS'
 q['status']='DATA_QC_COMPLETED_STRUCTURE_OBSERVED_SEMANTICS_UNKNOWN'
except Exception as e:
 q['failure']=type(e).__name__+(':'+str(e) if isinstance(e,RuntimeError) else ':DETAIL_SUPPRESSED_TO_AVOID_RAW_VALUES')
finally:
 signal.alarm(0);q['completed_utc']=now();q['elapsed_seconds']=round(time.monotonic()-start,3)
 for filename in ('response-body.bin','BCH-USDT-SWAP-fundingrates-2023-08.zip'):
  p=R/filename
  if p.exists():q['raw_file']=filename;q['retained_bytes']=p.stat().st_size;q['raw_sha256']=sha(p.read_bytes())
 save('qc-receipt.json',q)
terminal={**base,'event':'DATA_QC_TERMINAL','time_utc':now(),'status':q['status'],'raw_sha256':q['raw_sha256'],'receipt_sha256':sha((R/'qc-receipt.json').read_bytes()),'http_attempts':q['http_attempts'],'rate_validation':q.get('rate_validation','NOT_STARTED'),'structure':q.get('structure'),'failure':q.get('failure'),'future_exposure_label':'DATA_QC_ONLY_NEVER_UNREAD'}
newsha=append(terminal,'terminal',ledger_sha)
print(json.dumps({'root':str(R),'qc':q,'ledger_final_sha256':newsha},ensure_ascii=False,indent=2))
