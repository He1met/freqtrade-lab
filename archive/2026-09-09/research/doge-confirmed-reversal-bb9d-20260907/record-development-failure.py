from pathlib import Path
from datetime import datetime,timezone
import json,hashlib,fcntl,os
r=Path(__file__).parent
sha=lambda b:hashlib.sha256(b).hexdigest()
f=json.loads((r/'development-failure-inspection.json').read_bytes())
record=dict(record_type='DEVELOPMENT_TECHNICAL_FAILURE',cohort_id='issue98-doge-confirmed-reversal-single-v1',issue=98,recorded_at_utc=datetime.now(timezone.utc).isoformat(),root=str(r),research_run_id=f['research_run']['id'],execution_id=f['executions'][0]['id'],status='FAILED',classification=f['classification'],error_message=f['research_run']['error_message'],economic_verdict=None,metrics=None,Development_consumed=True,actual_Development_native_invocations=1,additional_native_invocations=0,surviving_sanitized_archive=f['archive']['path'],surviving_sanitized_archive_sha256=f['archive']['sha256'],runner_summary='MISSING_RUNTIME_REMOVED',native_raw_archive='MISSING_RUNTIME_REMOVED',provenance='NOT_WRITTEN',inspection_sha256=sha((r/'development-failure-inspection.json').read_bytes()),recovery_assessment_sha256=sha((r/'development-recovery-assessment.md').read_bytes()),D_retry_authorized=False,H_Stress='SEALED_UNREAD_UNACQUIRED',six_table_counts=f['six_table_counts'],next_gate='SUPERVISOR_TECHNICAL_RECOVERY_DECISION')
ledger=Path('/Users/shenjianpeng/Documents/freqtrade-lab-local/search-research-supervision-20260902/global-research-ledger.jsonl')
assert not (r/'development-failure-ledger-receipt.json').exists()
with ledger.with_suffix(ledger.suffix+'.lock').open('a+b') as lock:
 fcntl.flock(lock.fileno(),fcntl.LOCK_EX)
 before=ledger.read_bytes();assert sha(before)==json.loads((r/'development-ledger-prerun-receipt.json').read_bytes())['after_sha256']
 record['previous_prefix_sha256']=sha(before)
 addition=(json.dumps(record,sort_keys=True)+'\n').encode()
 with ledger.open('ab') as h:h.write(addition);h.flush();os.fsync(h.fileno())
 after=ledger.read_bytes();assert after==before+addition
 receipt=dict(before_sha256=sha(before),after_sha256=sha(after),before_bytes=len(before),after_bytes=len(after),prefix_preserved=True)
 (r/'development-failure-ledger-record.json').write_text(json.dumps(record,indent=2)+'\n')
 (r/'development-failure-ledger-receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
 print(json.dumps(receipt))
