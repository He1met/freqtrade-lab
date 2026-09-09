import json, hashlib, os
from pathlib import Path
ROOT=Path(__file__).resolve().parent
BASE=ROOT.parent.parent
INDEX=BASE/'bch-exact-grid-dual-sma-10-30-v1/cohort-v1._ryz88c7/consumption-metadata.json'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
j=json.loads(INDEX.read_text()); prior=Path(j['index']['path']); old=json.loads(prior.read_text())
records=old['canonical_metadata']+j['new_canonical_records']; known={r['path'] for r in records}
names={Path(r['path']).name for r in records}|{'research-contract.json','profile-acquisition-contract.json','window-spec.json','retained-data-provenance.json','search-terminal.json'}
allowed={'schema','status','pair','pairs','instrument_id','timeframe','data_start_utc','search_start_utc','development_start_utc','holdout_start_utc','end_exclusive_utc','start_utc','end_utc','timerange','search_timerange','development_timerange','holdout','holdout_status','stress_status'}
def extract(v,path=''):
 out={}
 if isinstance(v,dict):
  for k,x in v.items():
   key=f'{path}.{k}' if path else k
   if k in allowed and not isinstance(x,dict):out[key]=x
   elif isinstance(x,(dict,list)):out.update(extract(x,key))
 elif isinstance(v,list):
  for i,x in enumerate(v):
   if isinstance(x,(dict,list)):out.update(extract(x,f'{path}.{i}'))
 return out
new=[]
for d,dirs,files in os.walk(BASE):
 dirs[:]=[x for x in dirs if x not in {'.git','venv','.venv','node_modules','freqtrade','raw','data','backtest_results','codex-standard'}]
 if str(d).startswith(str(ROOT)):dirs[:]=[];continue
 for n in files:
  p=Path(d)/n
  if n in names and str(p) not in known:
   raw=p.read_bytes();v=json.loads(raw);new.append({'path':str(p),'sha256':hashlib.sha256(raw).hexdigest(),'metadata':extract(v)})
matches=[r for r in records+new if 'DOGE' in json.dumps(r).upper()]
result={'index':{'path':str(INDEX),'sha256':sha(INDEX)},'prior_index':{'path':str(prior),'sha256':sha(prior)},'scope':str(BASE),'scope_note':'Metadata allowlist only; all timeframes and original range metadata. Historical index reused without rehashing historical source files. No market files or sensitive databases read. Uncovered external runs UNKNOWN.','indexed_records':len(records),'metadata_names':sorted(names),'new_canonical_records':new,'doge_any_timeframe_records':matches,'external_runs':'UNKNOWN','conclusion':'BLOCKED_CONSUMPTION_CONFLICT' if matches else 'NO_IDENTIFIED_CANONICAL_DOGE_CONFLICT'}
(ROOT/'consumption-metadata.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({k:v for k,v in result.items() if k!='new_canonical_records'},indent=2))
