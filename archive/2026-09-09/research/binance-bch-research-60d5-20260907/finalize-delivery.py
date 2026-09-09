from pathlib import Path
from datetime import datetime, timezone
import json, hashlib, subprocess, urllib.request, sys
sys.path.insert(0,'/Users/shenjianpeng/.codex/worktrees/60d5/freqtrade-lab')
from lab.database import get_connection
from lab.bounded_research import canonical
r=Path(__file__).parent
repo=Path('/Users/shenjianpeng/.codex/worktrees/60d5/freqtrade-lab')
sha=lambda b:hashlib.sha256(b).hexdigest()
def command(*args):return subprocess.check_output(args,cwd=repo,text=True).strip()
pr=json.loads(command('gh','pr','view','97','--json','number,state,mergedAt,mergeCommit,headRefOid,url'))
issue=json.loads(command('gh','issue','view','96','--json','number,state,stateReason,closedAt,url'))
assert pr['state']=='MERGED' and pr['headRefOid']=='2656bd19b0bc1c01675ce8a1453210536b207a5e'
assert issue['state']=='CLOSED' and issue['stateReason']=='COMPLETED'
assert command('git','status','--porcelain')==''
assert command('git','rev-parse','HEAD')==pr['headRefOid']
changed=command('git','diff-tree','--no-commit-id','--name-only','-r','HEAD').splitlines()
assert changed==['docs/issue96-bch-trend28-negative.md']
subprocess.run(['git','diff','HEAD^','HEAD','--check'],cwd=repo,check=True)
context=json.load(urllib.request.urlopen('http://127.0.0.1:8796/api/search/context'))
research=json.load(urllib.request.urlopen('http://127.0.0.1:8796/api/research/context'))
assert context['state']['status']=='SEARCH_TERMINATED_NO_FINALIST' and context['state']['search_finalist'] is None
assert research['latest_research_run_id'] is None
c=get_connection(r/'lab.sqlite',read_only=True)
counts={t:c.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in ['research_profiles','generation_runs','candidates','research_runs','backtest_executions','releases']}
assert counts=={'research_profiles':1,'generation_runs':2,'candidates':1,'research_runs':0,'backtest_executions':0,'releases':0}
c.close()
files=['frozen-protocol.md','supervisor-authorization.json','profile-snapshot.json','single-baseline.json','BchPriorCloseTrend28.py','strategy-t0-review.json','source-publication.json','source-aggregation-qc.json','aggregated-retained-v2/aggregation-manifest.json','packaging-failure-note.json','search-protocol-review.json','search-campaign/search-terminal.json','search-campaign/trials.jsonl','ui-verification.json','verify-readonly.sql','terminal-ledger-record.json','terminal-ledger-receipt.json']
review=json.loads((r/'search-protocol-review.json').read_bytes());archive=Path(review['archive']);assert sha(archive.read_bytes())==review['archive_sha256']
ledger=Path('/Users/shenjianpeng/Documents/freqtrade-lab-local/search-research-supervision-20260902/global-research-ledger.jsonl').read_bytes()
terminal_receipt=json.loads((r/'terminal-ledger-receipt.json').read_bytes())
assert sha(ledger[:terminal_receipt['after_bytes']])==terminal_receipt['after_sha256']
assert sha(ledger[:105613])=='4a3a95c716b90b3bf065fc52ad6d7a11a8fca2027087c2ff6bf35b589ece0459'
capture=[json.loads(l) for l in (r/'d-capture/http-receipts.jsonl').read_bytes().splitlines()]
stored=sum(p.stat().st_size for p in (r/'d-capture').rglob('*') if p.is_file())
assert len(capture)==33 and sum(x['bytes'] for x in capture)==3095502 and stored<=5*1024**3
receipt={'schema':'issue96-final-delivery-v1','verified_at_utc':datetime.now(timezone.utc).isoformat(),
 'PR':pr,'Issue':issue,'local_head':pr['headRefOid'],'remote_main':command('git','ls-remote','origin','refs/heads/main').split()[0],
 'scoped_diff':changed,'worktree_clean':True,'sensitive_content_review':'Only sanitized research report, IDs, public-source costs, exact local evidence paths and digests tracked; no credentials, raw responses, DB, logs or native ZIP tracked',
 'project_terminal':'SEARCH_TERMINATED_NO_FINALIST','economic_classification':'BOUNDED_NEGATIVE','effective_samples':7,
 'six_table_counts':counts,'ResearchRun_id':None,'D_H_Stress':'N/A_NOT_EXECUTED_NOT_PASSED','H_data':'SEALED_UNREAD_UNACQUIRED',
 'archive':str(archive),'archive_sha256':sha(archive.read_bytes()),'evidence':{name:{'path':str(r/name),'sha256':sha((r/name).read_bytes())} for name in files},
 'terminal_ledger_prefix':terminal_receipt,'initial_105613_bytes_preserved':True,
 'capture_actual':{'native_download_invocations':1,'CCXT_fetch':len(capture),'decoded_bytes':sum(x['bytes'] for x in capture),'stored_bytes':stored,'automatic_retries':0,'wire_redirect_attempts':'UNKNOWN'},
 'Search_actual_native_invocations':1,'additional_backtests':0,
 'page':'http://127.0.0.1:8796/console','page_GET_search_state_verified':True,'page_GET_latest_ResearchRun':None,'browser_evidence':'ui-verification.json','FreqUI':'UNAVAILABLE',
 'effort':'Approximately 0.5 active hours, rough estimate excluding prerequisite engineering; no budget-filling work',
 'next_gate':'At most one approximately45-minute read-only mechanism deduplication / untouched-window / cost-and-natural-capacity feasibility screen, separately scoped. Reversal is only a hypothesis; no implementation or market run authorized.'}
(r/'final-delivery-receipt.json').write_bytes(canonical(receipt))
print(json.dumps({'PR':pr,'Issue':issue,'receipt':str(r/'final-delivery-receipt.json'),'receipt_sha256':sha((r/'final-delivery-receipt.json').read_bytes()),'ledger_sha256':terminal_receipt['after_sha256'],'six_table_counts':counts,'stored_capture_bytes':stored},ensure_ascii=False))
