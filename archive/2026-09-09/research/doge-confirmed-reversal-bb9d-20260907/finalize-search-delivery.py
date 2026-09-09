from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,subprocess
r=Path(__file__).parent
repo=Path('/Users/shenjianpeng/.codex/worktrees/bb9d/freqtrade-lab')
sha=lambda b:hashlib.sha256(b).hexdigest()
review=json.loads((r/'search-protocol-review.json').read_bytes())
assert review['all_protocol_gates']=='PASSED'
assert sha(Path(review['archive']).read_bytes())==review['archive_sha256']
assert subprocess.check_output(['git','status','--porcelain'],cwd=repo)==b''
files=['final-protocol.md','DogeConfirmedShockReversal3D-v2.py','synthetic-equivalence.json','supervisor-authorization.json','generation-approved.json','profile-snapshot.json','profile-contract.json','window.json','economic-gate.json','single-baseline.json','source-publication.json','source-aggregation-qc.json','qc-script-correction.json','search-protocol-review.json','search-context-terminal.json','search-campaign/search-terminal.json','search-campaign/trials.jsonl','terminal-ledger-record.json','terminal-ledger-receipt.json','ui-verification.json','search-handoff.md']
ledger=(Path('/Users/shenjianpeng/Documents/freqtrade-lab-local/search-research-supervision-20260902/global-research-ledger.jsonl')).read_bytes()
lr=json.loads((r/'terminal-ledger-receipt.json').read_bytes())
assert sha(ledger[:lr['after_bytes']])==lr['after_sha256']
assert sha(ledger[:113454])=='af0a1c3287e1162995e40636471d395016d2e1301df64f310bdabf987b1c2af0'
out=dict(schema='issue98-search-delivery-v1',verified_at_utc=datetime.now(timezone.utc).isoformat(),project_status=review['project_status'],protocol_gates=review['all_protocol_gates'],archive=review['archive'],archive_sha256=review['archive_sha256'],six_table_counts=review['six_table_counts'],Search_actual=1,Generation_actual=1,capture_actual=1,D_H_Stress_Release_execution=0,next_gate='SUPERVISOR_REVIEW_AND_SEPARATE_DEVELOPMENT_AUTHORIZATION',Issue98='OPEN',PR99='MERGED',worktree_clean=True,lab_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip(),page='http://127.0.0.1:8798/console',FreqUI='UNAVAILABLE',evidence={name:dict(path=str(r/name),sha256=sha((r/name).read_bytes())) for name in files},ledger_prefix=lr)
(r/'search-delivery-receipt.json').write_text(json.dumps(out,indent=2)+'\n')
print(json.dumps(dict(receipt=str(r/'search-delivery-receipt.json'),sha256=sha((r/'search-delivery-receipt.json').read_bytes()),review_sha256=sha((r/'search-protocol-review.json').read_bytes()),ledger=lr)))
