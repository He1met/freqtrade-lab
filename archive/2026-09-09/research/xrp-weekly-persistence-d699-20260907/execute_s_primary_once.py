from pathlib import Path
from datetime import datetime,timezone
import json,hashlib,os,sys,fcntl,http.client,threading,time,subprocess
r=Path(__file__).parent;repo=Path.cwd();sys.path.insert(0,str(repo))
from lab.research_console import create_research_console_server
os.umask(0o077)
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def put(n,v):
 with (r/n).open('x') as f:json.dump(v,f,sort_keys=True,indent=2)
 return sha(r/n)
ledger=Path('/Users/shenjianpeng/Documents/freqtrade-lab-local/search-research-supervision-20260902/global-research-ledger.jsonl')
def append(v,expected=None):
 with Path(str(ledger)+'.lock').open('r+') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);before=ledger.read_bytes();b=hashlib.sha256(before).hexdigest()
  if expected:assert b==expected,'Global ledger changed'
  v={**v,'previous_prefix_sha256':b,'recorded_at_utc':datetime.now(timezone.utc).isoformat()}
  with ledger.open('ab') as f:
   if before and not before.endswith(b'\n'):f.write(b'\n')
   f.write(json.dumps(v,sort_keys=True,separators=(',',':')).encode()+b'\n');f.flush();os.fsync(f.fileno())
  after=ledger.read_bytes();assert after.startswith(before)
  return dict(before_sha256=b,after_sha256=hashlib.sha256(after).hexdigest(),old_prefix_preserved=True)
frozen=json.loads((r/'freeze-package-receipt.json').read_bytes())
for n,v in frozen['files'].items():assert sha(r/n)==v['sha256']
assert sha(r/'search-campaign/acquisition/retained-data-provenance.json')=='f029356471dcd818aa88a5e22c4b96f44f080a79d21aa39323e54d29e396f6a8'
assert subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()=='07ea2cf4742de3d2473302dc57bf0b2283a5fbf2'
assert not subprocess.check_output(['git','status','--porcelain'])
assert subprocess.check_output(['gh','issue','view','107','--json','state','--jq','.state'],text=True).strip()=='OPEN'
start=dict(record_type='AUTHORIZED_S_PRIMARY_START',cohort_id=r.name,candidate_id='3b447051-a17e-4482-a6f7-bb4d01f660cd',protocol_sha256=sha(r/'final-protocol.json'),source_provenance_sha256=sha(r/'search-campaign/acquisition/retained-data-provenance.json'),maximum_primary_native_calls=1,maximum_conditional_benchmark_calls=1,D_H_STRESS_authorized=False,D_values_exposed=True,authorization='Supervisor 01a05dcc explicitly authorized one S primary via project entrypoint; conditional one benchmark after all decidable main gates; no replay')
startsha=put('s-primary-once-guard.json',start);put('s-primary-start-ledger-receipt.json',append({**start,'receipt_sha256':startsha},'a06708f098d8b15fdb942a481e8369893d15d838d77fcf8ec77ad3c27d65c4a8'))
runtime=r/'s-console-runtime';runtime.mkdir();pilot=r/'s-empty-development-context';pilot.mkdir();art=r/'artifacts';art.mkdir()
server=None
try:
 server=create_research_console_server(r/'lab.sqlite',runtime,pilot,port=0,artifact_root=art,search_root=r/'search-campaign',check_data_python=Path(sys.executable),freqtrade_python=Path(sys.executable),freqtrade_source=Path('/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue-43-profile-driven-v1/freqtrade'),task_timeout_seconds=7200)
 threading.Thread(target=server.serve_forever,daemon=True).start()
 def request(path,body=None):
  c=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=30)
  try:
   headers={} if body is None else {'Origin':f'http://127.0.0.1:{server.server_port}','X-CSRF-Token':server.research_console_csrf_token,'Content-Type':'application/json'}
   c.request('GET' if body is None else 'POST',path,body=None if body is None else json.dumps(body).encode(),headers=headers);resp=c.getresponse();return resp.status,json.loads(resp.read())
  finally:c.close()
 status,context=request('/api/search/context');put('s-preflight-context.json',dict(http_status=status,response=context))
 status,created=request('/api/search-campaigns',dict(profile_id='issue107-xrp-weekly-persistent-v1',candidate_ids=[start['candidate_id']]))
 put('s-create-response.json',dict(http_status=status,response=created))
 if status!=202:raise RuntimeError('Project Search HTTP rejected: '+str(created.get('error',status)))
 cid=created['campaign_id'];print(json.dumps(dict(campaign_id=cid,status='PROJECT_SEARCH_STARTED')),flush=True)
 deadline=time.monotonic()+7230
 while time.monotonic()<deadline:
  status,state=request('/api/search-campaigns/'+cid)
  if status!=200:raise RuntimeError('Search status unavailable')
  if server.research_console_controller._active is None:break
  time.sleep(2)
 else:raise RuntimeError('Search deadline exceeded')
 put('s-terminal-api.json',state)
 terminal=dict(record_type='S_PRIMARY_PROJECT_TERMINAL',cohort_id=r.name,campaign_id=cid,public_status=state.get('status'),benchmark_calls=0,D_H_STRESS_calls=0,terminal_api_sha256=sha(r/'s-terminal-api.json'))
 put('s-primary-terminal-ledger-receipt.json',append(terminal));print(json.dumps(terminal),flush=True)
except Exception as e:
 put('s-project-entry-failure.json',dict(error_type=type(e).__name__,message=str(e),retry=False));print(json.dumps(dict(status='STOPPED',error_type=type(e).__name__,message=str(e))),flush=True);raise
finally:
 if server is not None:server.research_console_controller.shutdown();server.shutdown();server.server_close()
