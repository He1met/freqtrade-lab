from pathlib import Path
import subprocess,sys,json
r=Path(__file__).parent;repo=Path('/Users/shenjianpeng/.codex/worktrees/60d5/freqtrade-lab');h=json.loads((r/'source-publication.json').read_bytes())
base=['--source-root',str(r/'complete-source'),'--source-provenance-sha256',h['provenance_sha256'],'--source-receipt-sha256',h['retrieval_receipt_sha256'],'--database',str(r/'lab.sqlite'),'--profile-id','issue96-bch-trend28-v1','--search-timerange','20231113-20240715','--development-timerange','20240715-20250714','--pre-roll-candles','29','--economic-gate',str(r/'economic-gate.json'),'--single-baseline',str(r/'single-baseline.json')]
# D is physically isolated first; no backtesting command is called.
for action,name in [('prepare-development-data','development-pilot'),('prepare-search-data','search-campaign')]:
 argv=[sys.executable,str(repo/'scripts/run_bounded_research_pilot.py'),action,*base,'--output-root',str(r/name)]
 (r/(name+'-argv.json')).write_text(json.dumps(argv)+'\n')
 with (r/(name+'-prepare.log')).open('xb') as log:
  subprocess.run(argv,cwd=repo,stdout=log,stderr=subprocess.STDOUT,check=True)
 print(action+' completed')
