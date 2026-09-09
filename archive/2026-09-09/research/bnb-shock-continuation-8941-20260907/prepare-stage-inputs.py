from pathlib import Path
import subprocess,sys,json
r=Path(__file__).parent
repo=Path('/Users/shenjianpeng/.codex/worktrees/8941/freqtrade-lab')
h=json.loads((r/'source-publication-v2.json').read_bytes())
base=['--source-root',str(r/'complete-source-v2'),'--source-provenance-sha256',h['provenance_sha256'],'--source-receipt-sha256',h['retrieval_receipt_sha256'],'--database',str(r/'lab.sqlite'),'--profile-id','issue104-bnb-daily-shock-continuation-48h-v1','--search-timerange','20231106-20241104','--development-timerange','20241104-20251103','--pre-roll-candles','35','--economic-gate',str(r/'economic-gate.json'),'--single-baseline',str(r/'single-baseline.json')]
# Development is physically isolated first; these are producer/QC commands only.
for action,name in [('prepare-development-data','development-pilot'),('prepare-search-data','search-campaign')]:
 argv=[sys.executable,str(repo/'scripts/run_bounded_research_pilot.py'),action,*base,'--output-root',str(r/name)]
 with (r/(name+'-argv.json')).open('x') as f:f.write(json.dumps(argv)+'\n')
 with (r/(name+'-prepare.log')).open('xb') as log:
  subprocess.run(argv,cwd=repo,stdout=log,stderr=subprocess.STDOUT,check=True)
 print(action+' completed')
