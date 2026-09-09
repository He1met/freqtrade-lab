from pathlib import Path
from datetime import datetime, timezone
import fcntl, hashlib, json, os, subprocess
r=Path(__file__).parent
repo=Path('/Users/shenjianpeng/.codex/worktrees/bb9d/freqtrade-lab')
native=Path('/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue-43-profile-driven-v1/freqtrade')
ledger=Path('/Users/shenjianpeng/Documents/freqtrade-lab-local/search-research-supervision-20260902/global-research-ledger.jsonl')
sha=lambda b:hashlib.sha256(b).hexdigest()
assert not (r/'ledger-preregistration-receipt.json').exists()
g=json.loads((r/'generation-approved.json').read_bytes())
assert g['candidate']['review_status']=='APPROVED'
record=dict(record_type='COHORT_PREREGISTERED',cohort_id='issue98-doge-confirmed-reversal-single-v1',issue=98,
 recorded_at_utc=datetime.now(timezone.utc).isoformat(),root=str(r),pair='DOGE/USDT:USDT',instrument_id='DOGEUSDT',pair_family='DOGE-USDT',exchange='binance',
 search_window=['2023-11-06T00:00:00Z','2024-11-04T00:00:00Z'],development_window=['2024-11-04T00:00:00Z','2025-11-03T00:00:00Z'],holdout_stress_window=['2025-11-03T00:00:00Z','2026-05-25T00:00:00Z'],
 pre_roll_candles=37,mode='SINGLE_BASELINE_V1',maximum_rounds=1,maximum_attempts=1,maximum_generations=1,maximum_captures=1,
 candidate_id=g['candidate']['id'],generation_id=g['id'],profile_id=g['profile_id'],database=str(r/'lab.sqlite'),
 status='FROZEN_BEFORE_OHLCV_VALUES',actual_Search_attempts=0,actual_generations=1,D_strategy_runs=0,H_Stress='SEALED_UNREAD_UNACQUIRED',D_source='AUTHORIZED_MECHANICAL_QC_ONLY',
 future_study_reserved=True,search_consumed=False,source_provenance_sha256=None,source_receipt_sha256=None,
 prior_exposure='FUNDING_QC_ONLY: doge-funding-qc-bb9d-20260907; no OHLCV or Search',external_unregistered_exposure='UNKNOWN',
 strategy_label='Known reversal family improvement; not a wholly new mechanism',
 capture_budget=json.loads((r/'supervisor-authorization.json').read_bytes())['capture_budget'])
files=['final-protocol.md','supervisor-authorization.json','profile-snapshot.json','profile-contract.json','DogeConfirmedShockReversal3D-v2.py','single-baseline.json','economic-gate.json','window.json','synthetic-equivalence.json','generation-approved.json']
record['file_sha256']={name:sha((r/name).read_bytes()) for name in files}
record['runtime_binding']={'lab_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip(),'native_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=native,text=True).strip(),'files':{str(p):sha(p.read_bytes()) for p in [repo/'lab/binance_source.py',repo/'lab/bounded_research.py',repo/'lab/futures_costs.py',native/'freqtrade/optimize/backtesting.py']}}
with ledger.with_suffix(ledger.suffix+'.lock').open('a+b') as lock:
 fcntl.flock(lock.fileno(),fcntl.LOCK_EX)
 before=ledger.read_bytes()
 assert len(before)==113454 and sha(before)=='af0a1c3287e1162995e40636471d395016d2e1301df64f310bdabf987b1c2af0'
 assert record['cohort_id'].encode() not in before
 record['previous_prefix_sha256']=sha(before)
 addition=(json.dumps(record,sort_keys=True)+'\n').encode()
 with ledger.open('ab') as f:
  f.write(addition);f.flush();os.fsync(f.fileno())
 after=ledger.read_bytes();assert after==before+addition
 receipt=dict(before_sha256=sha(before),after_sha256=sha(after),before_bytes=len(before),after_bytes=len(after),prefix_preserved=True,record_sha256=sha(addition))
 (r/'ledger-preregistration.json').write_text(json.dumps(record,indent=2)+'\n')
 (r/'ledger-preregistration-receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
 print(json.dumps(receipt))
