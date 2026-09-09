from pathlib import Path
import pandas as pd,json,hashlib,subprocess,os,sys
from urllib.parse import urlsplit,parse_qs
from lab.futures_costs import validate_events
r=Path(__file__).parent;s=r/'source-sd-01';repo=Path.cwd()
h=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def put(n,v):
 with (r/n).open('x') as f:json.dump(v,f,sort_keys=True,indent=2)
p=json.loads((s/'retained-data-provenance.json').read_bytes());assert h(s/'retained-data-provenance.json')=='bce5f57e3ea98905d793ae48aaccf450b05b639602eb356f7a723efef796424e'
requests=[];rawtimes=set()
for line in (r/'capture-sd-01/http-receipts.jsonl').read_bytes().splitlines():
 rec=json.loads(line);u=urlsplit(rec['url'])
 if u.path!='/fapi/v1/fundingRate':continue
 q=parse_qs(u.query);raw=r/'capture-sd-01/raw'/rec['body_file'];assert h(raw)==rec['sha256'];values=json.loads(raw.read_bytes())
 times=[x['fundingTime'] for x in values];rawtimes.update(times)
 requests.append(dict(start_ms=int(q['startTime'][0]),end_ms=int(q['endTime'][0]),rows=len(times)))
rows=[];frames={}
for name,v in {**p['files'],**p['local_only_files']}.items():
 f=s/name;assert not f.is_symlink();assert h(f)==v['sha256'];assert f.stat().st_size==v['bytes']
 if f.suffix=='.feather':
  df=pd.read_feather(f);frames[f.name]=df;t=pd.to_datetime(df.date,utc=True);expected=742 if '1d-futures' in name else 2184 if 'funding_rate' in name else 17808
  assert len(df)==expected and t.is_monotonic_increasing and not t.duplicated().any() and not df.isna().any().any()
  rows.append(dict(path=name,rows=len(df),first_utc=t.iloc[0].isoformat(),last_utc=t.iloc[-1].isoformat(),sha256=h(f)))
marks=frames['XRP_USDT_USDT-1h-mark.feather'];mv=[[int(t.timestamp()*1000),o,hi,lo,c] for t,o,hi,lo,c in marks[['date','open','high','low','close']].itertuples(index=False,name=None)]
counts={}
for phase,a,b in [('S','2023-11-06','2024-11-04'),('D','2024-11-04','2025-11-03')]:
 events,_=validate_events(p['source']['funding_events'],mv,symbol='XRPUSDT',start_ms=int(pd.Timestamp(a,tz='UTC').timestamp()*1000),end_ms=int(pd.Timestamp(b,tz='UTC').timestamp()*1000));assert len(events)==1092;counts[phase]=len(events)
put('funding-row-count-erratum.json',dict(status='SUPERVISOR_APPROVED_SERIALIZATION_COUNT_ERRATUM',raw_funding_requests=requests,raw_unique_events=len(rawtimes),raw_first_ms=min(rawtimes),raw_last_ms=max(rawtimes),compiled_expected=2184,compiled_actual=2184,phase_source_events=counts,original_plan_unchanged=True,source_unchanged=True,thresholds_unchanged=True,D_exposure_restriction_retained=True,code_evidence=['lab/binance_source.py:273-274','lab/bounded_research.py:1236','lab/futures_costs.py:69-106'],authorization='Supervisor 01a05dcc explicit additive erratum approval'))
put('source-aggregation-qc.json',dict(status='SOURCE_QC_PASS_WITH_APPROVED_ERRATUM',files=rows,phase_event_calendar_and_associated_mark_validated=counts,D_values_accidentally_exposed=True,D_signals_computed=False,market_native_calls=0))
print(json.dumps(dict(qc='PASS_WITH_ERRATUM',raw_funding_events=len(rawtimes),compiled_funding_events=2184,phase_event_counts=counts)),flush=True)
common=['--source-root',str(s),'--source-provenance-sha256',h(s/'retained-data-provenance.json'),'--source-receipt-sha256',h(s/'retrieval_receipt.json'),'--database',str(r/'lab.sqlite'),'--profile-id','issue107-xrp-weekly-persistent-v1','--search-timerange','20231106-20241104','--development-timerange','20241104-20251103','--pre-roll-candles','14','--economic-gate',str(r/'economic-gate.json'),'--single-baseline',str(r/'single-baseline.json')]
env={**os.environ,'PYTHONPATH':str(repo)+':/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue-43-profile-driven-v1/freqtrade','PYTHONDONTWRITEBYTECODE':'1'}
for action,out in [('prepare-search-data','search-campaign'),('prepare-development-data','development-pilot')]:
 assert not (r/out).exists();cmd=[sys.executable,str(repo/'scripts/run_bounded_research_pilot.py'),action,*common,'--output-root',str(r/out)]
 put(action+'-invocation.json',cmd)
 with (r/(action+'.stdout')).open('x') as stdout,(r/(action+'.stderr')).open('x') as stderr:result=subprocess.run(cmd,env=env,stdout=stdout,stderr=stderr)
 print(json.dumps({'action':action,'returncode':result.returncode}),flush=True)
 if result.returncode:sys.exit(result.returncode)
with (r/'check-development-data.stdout').open('x') as stdout,(r/'check-development-data.stderr').open('x') as stderr:result=subprocess.run([sys.executable,str(repo/'scripts/run_bounded_research_pilot.py'),'check-development-data','--pilot-root',str(r/'development-pilot')],env=env,stdout=stdout,stderr=stderr)
print(json.dumps({'check_development_returncode':result.returncode}))
