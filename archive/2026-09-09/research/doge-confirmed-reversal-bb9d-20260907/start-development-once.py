from pathlib import Path
from datetime import datetime,timezone
import json,hashlib,fcntl,os,urllib.request,re
r=Path(__file__).parent; base='http://127.0.0.1:8798'
sha=lambda b:hashlib.sha256(b).hexdigest()
assert not (r/'development-http-request.json').exists()
review=json.loads((r/'search-protocol-review.json').read_bytes())
assert review['all_protocol_gates']=='PASSED'
research=json.load(urllib.request.urlopen(base+'/api/research/context'))
assert research['latest_research_run_id'] is None and research['capability']['status']=='READY'
round_one=json.loads((r/'search-campaign/campaign-round-1.json').read_bytes())
protocol_review=dict(schema='freqtrade-lab-single-baseline-review-v1',protocol_sha256=review['protocol_sha256'],data_provenance_sha256=round_one['data_provenance_sha256'],candidate_id=review['candidate_id'],source_sha256=review['strategy_sha256'],attempt_number=1,raw_artifact_sha256=review['archive_sha256'],all_protocol_gates='PASSED')
payload=dict(candidate_id=review['candidate_id'],protocol_review=protocol_review)
record=dict(record_type='DEVELOPMENT_REGISTERED_PRE_RUN',cohort_id='issue98-doge-confirmed-reversal-single-v1',issue=98,recorded_at_utc=datetime.now(timezone.utc).isoformat(),root=str(r),search_campaign_id=review['campaign_id'],candidate_id=review['candidate_id'],protocol_review=protocol_review,authorization_sha256=sha((r/'development-supervisor-authorization.json').read_bytes()),D_provenance_sha256=sha((r/'development-pilot/development-isolation/retained-data-provenance.json').read_bytes()),maximum_Development_attempts=1,additional_Search_Generation_capture=0,H_Stress='SEALED_UNREAD_UNACQUIRED')
ledger=Path('/Users/shenjianpeng/Documents/freqtrade-lab-local/search-research-supervision-20260902/global-research-ledger.jsonl')
with ledger.with_suffix(ledger.suffix+'.lock').open('a+b') as lock:
 fcntl.flock(lock.fileno(),fcntl.LOCK_EX)
 before=ledger.read_bytes();assert sha(before)==json.loads((r/'terminal-ledger-receipt.json').read_bytes())['after_sha256']
 record['previous_prefix_sha256']=sha(before)
 addition=(json.dumps(record,sort_keys=True)+'\n').encode()
 with ledger.open('ab') as f:f.write(addition);f.flush();os.fsync(f.fileno())
 after=ledger.read_bytes();assert after==before+addition
 (r/'development-ledger-prerun.json').write_text(json.dumps(record,indent=2)+'\n')
 (r/'development-ledger-prerun-receipt.json').write_text(json.dumps(dict(before_sha256=sha(before),after_sha256=sha(after),before_bytes=len(before),after_bytes=len(after),prefix_preserved=True))+'\n')
page=urllib.request.urlopen(base+'/console').read().decode();token=re.search(r'name="csrf-token" content="([^"]+)"',page)[1]
with (r/'development-http-request.json').open('x') as f:json.dump(payload,f)
request=urllib.request.Request(base+'/api/research-runs',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json','Origin':base,'X-CSRF-Token':token})
with urllib.request.urlopen(request,timeout=60) as response:value=json.load(response)
(r/'development-http-response.json').write_text(json.dumps(value,indent=2)+'\n')
print(json.dumps(value,ensure_ascii=False))
