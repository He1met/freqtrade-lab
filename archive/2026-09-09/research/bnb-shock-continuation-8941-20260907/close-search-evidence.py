from pathlib import Path
from datetime import datetime, timezone
import json, hashlib, fcntl, os
r=Path(__file__).parent
sha=lambda b:hashlib.sha256(b).hexdigest()
def load(name):return json.loads((r/name).read_text())
def save(name,value):
    with (r/name).open('x') as f:json.dump(value,f,sort_keys=True,indent=2,allow_nan=False);f.write('\n')
assert not (r/'final-delivery-receipt.json').exists()
attachment=load('rejection-attachment-receipt.json')
live=load('rejection-live-verification.json')
review=load('search-protocol-review.json')
assert attachment['status']=='ATTACHED_ONCE' and live['status']=='VERIFIED_READ_ONLY'
for p,s in attachment['frozen_hashes_unchanged'].items():assert sha((r/p).read_bytes())==s
ledger=Path('/Users/shenjianpeng/Documents/freqtrade-lab-local/search-research-supervision-20260902/global-research-ledger.jsonl')
record=dict(record_type='SEARCH_PROTOCOL_REJECTED_TERMINAL',cohort_id='issue104-bnb-daily-shock-continuation-single-v1',
    recorded_at_utc=datetime.now(timezone.utc).isoformat(),issue=104,root=str(r),
    campaign_id=attachment['attachment']['campaign_id'],candidate_id=attachment['attachment']['protocol_review_identity']['candidate_id'],
    core_status='SEARCH_FINALIST_FROZEN',full_protocol_status='REJECTED',qualified_finalist=False,
    actual_native_Search_runs=1,S_consumed=True,remaining_authorized_Search_runs=0,
    failed_gates=attachment['attachment']['failed_gates'],cost_decomposition=review['cost_decomposition'],
    D='PHYSICALLY_ISOLATED_QC_ONLY_NO_STRATEGY_RUN',H_Stress='OHLCV_SEALED_LIMITED_FUNDING_METADATA_QC_NO_STRATEGY_RUN',
    ResearchRun_count=0,development_block='PERSISTED_REJECTION_VERIFIED_BY_REAL_READ_ONLY_API',
    attachment_receipt_sha256=sha((r/'rejection-attachment-receipt.json').read_bytes()),
    api_verification_sha256=sha((r/'rejection-live-verification.json').read_bytes()),
    protocol_review_identity=attachment['attachment']['protocol_review_identity'])
with ledger.with_suffix(ledger.suffix+'.lock').open('a+b') as lock:
    fcntl.flock(lock.fileno(),fcntl.LOCK_EX)
    before=ledger.read_bytes()
    assert sha(before)==load('ledger-search-pre-run-receipt.json')['after_sha256']
    with (r/'ledger-before-terminal.jsonl').open('xb') as f:f.write(before)
    record['previous_prefix_sha256']=sha(before)
    addition=(json.dumps(record,sort_keys=True,allow_nan=False)+'\n').encode()
    with ledger.open('ab') as f:f.write(addition);f.flush();os.fsync(f.fileno())
    after=ledger.read_bytes()
    assert after==before+addition
    save('ledger-terminal-record.json',record)
    save('ledger-terminal-receipt.json',dict(before_sha256=sha(before),after_sha256=sha(after),
        prefix_preserved=True,appended_records=1,appended_bytes=len(addition)))
files=['rejection-attachment-before.json','rejection-attachment-after.json','rejection-attachment-receipt.json',
       'rejection-live-verification.json','rejection-live-search-api.json','rejection-live-research-api.json',
       'rejection-live-generation-api.json','rejection-rendered-page-evidence.json','ledger-terminal-receipt.json',
       'ledger-terminal-record.json','search-protocol-review.json','native-hourly-mtm.json']
final=dict(status='BOUNDED_SEARCH_DELIVERED_PROTOCOL_REJECTED',issue=104,
    PRs=[105,106],merge_sha='97b5e5dd45605655e25574e0d6948acee20aacd5',
    core_status='SEARCH_FINALIST_FROZEN',full_protocol_status='REJECTED',qualified_strategy_found=False,
    actual_native_Search_runs=1,actual_native_D_H_Stress_runs=0,Search_window_consumed=True,
    natural_samples=44,total_trades=47,conservative_net_usdt=review['cost_decomposition']['conservative_net_usdt'],
    failed_gates=record['failed_gates'],counts=attachment['counts'],
    db_mutation='Candidate metadata_json and updated_at only; all other rows unchanged',
    original_artifacts_unchanged=attachment['frozen_hashes_unchanged'],D=record['D'],H_Stress=record['H_Stress'],
    UI='REJECTED, both failed gates, original core result and positive net visible; D/H disabled',
    handoff_check=live['bound_finalist_rejection'],ledger_after_sha256=sha(after),
    artifact_sha256={name:sha((r/name).read_bytes()) for name in files},
    closure='AUTHORIZED_AFTER_THIS_RECEIPT; remote closure evidence will be separate',
    next_research='NOT_STARTED; supervisor owns next task')
save('final-delivery-receipt.json',final)
print(json.dumps(dict(final_receipt_sha256=sha((r/'final-delivery-receipt.json').read_bytes()),ledger_after_sha256=sha(after))))
