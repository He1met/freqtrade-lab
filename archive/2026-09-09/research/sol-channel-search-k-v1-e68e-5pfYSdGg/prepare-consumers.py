"""Run existing public CLI consumers once after successful official acquisition."""
from pathlib import Path
import subprocess,os,json,hashlib,datetime
R=Path(__file__).resolve().parent;REPO=Path('/Users/shenjianpeng/.codex/worktrees/e68e/freqtrade-lab')
PY='/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue-43-profile-driven-v1/venv/bin/python'
assert json.loads((R/'producer-completion.json').read_text())['exit_code']==0
source=R/'source-acquisition';sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
args=['--source-root',str(source),'--source-provenance-sha256',sha(source/'retained-data-provenance.json'),'--source-receipt-sha256',sha(source/'retrieval_receipt.json'),'--database',str(R/'research.sqlite'),'--profile-id','sol-channel-k-v1-e68e-5pfysdgg','--search-timerange','20240301-20250301','--development-timerange','20250301-20260301','--pre-roll-candles','29','--economic-gate',str(R/'economic-gate.json')]
env=os.environ.copy();env['PYTHONDONTWRITEBYTECODE']='1';env['PYTHONPATH']=str(REPO)
for phase,directory in [('search','search'),('development','development')]:
    argv=[PY,str(REPO/'scripts/run_bounded_research_pilot.py'),'prepare-'+phase+'-data',*args,'--output-root',str(R/directory)]
    began=datetime.datetime.now(datetime.UTC).isoformat()
    with (R/('prepare-'+phase+'.log')).open('xb') as log:
        result=subprocess.run(argv,cwd=REPO,env=env,stdout=log,stderr=subprocess.STDOUT)
    (R/('prepare-'+phase+'-process.json')).write_text(json.dumps({'argv':argv,'started_at_utc':began,'finished_at_utc':datetime.datetime.now(datetime.UTC).isoformat(),'exit_code':result.returncode,'log_sha256':sha(R/('prepare-'+phase+'.log'))},indent=2)+'\n')
    print(json.dumps({'phase':phase,'exit_code':result.returncode}),flush=True)
    if result.returncode: raise SystemExit(result.returncode)
