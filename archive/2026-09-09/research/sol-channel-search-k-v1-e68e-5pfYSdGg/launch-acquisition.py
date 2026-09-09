"""Record the unchanged official producer CLI process, without intercepting its transport."""
from pathlib import Path
import subprocess,os,json,datetime,hashlib
R=Path(__file__).resolve().parent
REPO=Path('/Users/shenjianpeng/.codex/worktrees/e68e/freqtrade-lab')
NATIVE=Path('/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue-43-profile-driven-v1/freqtrade')
PYTHON=NATIVE.parent/'venv/bin/python'
argv=[str(PYTHON),str(REPO/'scripts/fetch_okx_profile_data.py'),'--output-root',str(R/'source-acquisition'),'--window-spec',str(R/'source-window.json'),'--profile-database',str(R/'research.sqlite'),'--profile-id','sol-channel-k-v1-e68e-5pfysdgg','--pre-roll-candles','29','--economic-gate',str(R/'economic-gate.json')]
def now(): return datetime.datetime.now(datetime.UTC).isoformat()
env=os.environ.copy();env['PYTHONDONTWRITEBYTECODE']='1';env['PYTHONPATH']=str(NATIVE)+os.pathsep+str(REPO)
assert not (R/'producer-launch.json').exists()
record={'argv':argv,'cwd':str(REPO),'environment_overrides':{k:env[k] for k in ['PYTHONDONTWRITEBYTECODE','PYTHONPATH']},'started_at_utc':now(),'preregistration_sha256':hashlib.sha256((R/'freeze-manifest.json').read_bytes()).hexdigest(),'controller_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'raw_retained':False,'failure_preceding_unpersisted_request_evidence':'UNKNOWN','supervisor_disposition':'Use official main unchanged; atomic unpublished output cleanup accepted; sibling logs retained; no whole-acquisition retry'}
with (R/'producer-stdout.log').open('xb') as out,(R/'producer-stderr.log').open('xb') as err:
    p=subprocess.Popen(argv,cwd=REPO,env=env,stdout=out,stderr=err)
    record['pid']=p.pid;(R/'producer-launch.json').write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps({'pid':p.pid,'launch_receipt':str(R/'producer-launch.json')}),flush=True)
    code=p.wait()
record['exit_code']=code;record['finished_at_utc']=now()
record['stdout_sha256']=hashlib.sha256((R/'producer-stdout.log').read_bytes()).hexdigest()
record['stderr_sha256']=hashlib.sha256((R/'producer-stderr.log').read_bytes()).hexdigest()
(R/'producer-completion.json').write_text(json.dumps(record,indent=2)+'\n')
print(json.dumps({'exit_code':code,'receipt':str(R/'producer-completion.json')}),flush=True)
raise SystemExit(code)
