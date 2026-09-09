import hashlib,json
from pathlib import Path
from datetime import datetime,timezone
r=Path(__file__).parent
w=Path('/Users/shenjianpeng/.codex/worktrees/bb9d/freqtrade-lab')
paths=['lab/bounded_research.py','lab/binance_source.py','lab/futures_costs.py',
 'tests/test_binance_market.py','tests/test_binance_source.py','tests/test_binance_pair_binding.py',
 'tests/profile_holdout_fixture.py','tests/test_profile_holdout.py','docs/issue98-next-contract-proposal.md']
def record(p):return {'path':str(p),'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
receipt={'recorded_at_utc':datetime.now(timezone.utc).isoformat(),'issue':98,'issue_state':'OPEN',
 'pr':'https://github.com/He1met/freqtrade-lab/pull/99','pr_draft':True,
 'local_and_remote_head':'8abddba4319382f9c3e173feb9d15cd7ccb8afca','base_main':'fcb52ff59013b3a49271a259293069b62907578e',
 'worktree':str(w),'worktree_clean':True,'files':[record(w/p) for p in paths],
 'tests':{'passed':92,'failed':0,'skipped':0,'warnings':76,'seconds':6.70,
  'command':record(r/'engineering-tests-command.sh'),'cwd':str(w),
  'output':record(r/'engineering-tests-output.txt'),'prior_91_output':record(r/'engineering-tests-91-output.txt'),
  'output_capture':'stdout chunks returned by exec/write_stdin concatenated without rewriting test results',
  'first_run':'71 passed/15 failed: new 2-day fixture failed existing capacity gate; synthetic 4-day/2-trade fixture corrected, business gate unchanged',
  'last_change':'After 91 pass, added H authorization Profile identity rejection and one test; same targeted set 92 pass',
  'no_full_suite':True,'native_backtests':0},
 'runtime':{'python':'3.13.13','ccxt':'4.5.68','pandas':'3.0.3','pyarrow':'25.0.0','freqtrade':'2026.7',
  'native_commit':'52bc96f4480b1a0da6a9b455bd00b17fbb6786a5',
  'python_executable':'/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue-43-profile-driven-v1/venv/bin/python'},
 'actual_market_requests_total':3,'additional_market_requests_after_funding_qc':0,
 'real_Candidate_Search_D_H_Stress':0,'business_tables_changed':False,'native_modified':False,
 'funding_qc':record(r/'qc-report.json'),'ledger_receipt':record(r/'ledger-receipt.json'),
 'next_gate':'Supervisor verifies fixed commit; decide enforceable smaller capture budgets and full economic protocol before any more acquisition',
 'budget_gap':'capture_native still 2000 fetch/2GiB/7200s; proposed 128/32MiB/1800s NOT enforced. No acquisition permitted yet.'}
with (r/'engineering-receipt.json').open('x') as f:json.dump(receipt,f,ensure_ascii=False,sort_keys=True,indent=2)
print(record(r/'engineering-receipt.json'))
