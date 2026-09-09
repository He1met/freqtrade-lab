from pathlib import Path
from datetime import datetime,timezone
import json,hashlib,fcntl,os,urllib.request
r=Path(__file__).parent;sha=lambda b:hashlib.sha256(b).hexdigest()
d=json.loads((r/'development-posthoc-diagnostic.json').read_bytes())
assert d['classification']=='POSTHOC_DIAGNOSTIC_ONLY' and not d['formal_acceptance']
current=json.load(urllib.request.urlopen('http://127.0.0.1:8798/api/research-runs/68fcd677-fd22-40e9-a6f1-78ee910b3a68'))
assert current['status']=='FAILED' and current['development']['profit_pct'] is None and current['verdict'] is None
record=dict(record_type='DEVELOPMENT_POSTHOC_DIAGNOSTIC',cohort_id='issue98-doge-confirmed-reversal-single-v1',issue=98,recorded_at_utc=datetime.now(timezone.utc).isoformat(),research_run_id=d['research_run_id'],classification=d['classification'],formal_acceptance=False,project_status='FAILED',database_metrics='NULL',verdict=None,archive_sha256=d['archive_sha256'],diagnostic_sha256=sha((r/'development-posthoc-diagnostic.json').read_bytes()),cost_decomposition=d['cost_decomposition'],gates=d['gates'],root=str(r),D_native_invocations=1,D_replays=0,H_Stress='SEALED_UNREAD_UNACQUIRED',disposition_recommendation='STOP_CANDIDATE_NO_NEW_RECOVERY_PLATFORM',missing_native_runner_summary='UNKNOWN',missing_native_stdout_stderr='UNKNOWN')
ledger=Path('/Users/shenjianpeng/Documents/freqtrade-lab-local/search-research-supervision-20260902/global-research-ledger.jsonl')
assert not (r/'development-diagnostic-ledger-receipt.json').exists()
with ledger.with_suffix(ledger.suffix+'.lock').open('a+b') as lock:
 fcntl.flock(lock.fileno(),fcntl.LOCK_EX)
 before=ledger.read_bytes();assert sha(before)==json.loads((r/'development-failure-ledger-receipt.json').read_bytes())['after_sha256']
 record['previous_prefix_sha256']=sha(before);addition=(json.dumps(record,sort_keys=True)+'\n').encode()
 with ledger.open('ab') as f:f.write(addition);f.flush();os.fsync(f.fileno())
 after=ledger.read_bytes();assert after==before+addition
 receipt=dict(before_sha256=sha(before),after_sha256=sha(after),before_bytes=len(before),after_bytes=len(after),prefix_preserved=True)
 (r/'development-diagnostic-ledger-record.json').write_text(json.dumps(record,indent=2)+'\n')
 (r/'development-diagnostic-ledger-receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
 print(json.dumps(receipt))
