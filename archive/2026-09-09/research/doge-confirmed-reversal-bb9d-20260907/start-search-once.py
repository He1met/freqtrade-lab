from pathlib import Path
from datetime import datetime, timezone
import json, hashlib, fcntl, os, urllib.request, re
r=Path(__file__).parent
base='http://127.0.0.1:8798'
sha=lambda b:hashlib.sha256(b).hexdigest()
assert not (r/'search-http-request.json').exists() and not (r/'ledger-search-pre-run.json').exists()
context=json.load(urllib.request.urlopen(base+'/api/search/context'))
assert context['state']['campaign_id'] is None and context['state']['status']=='SEARCH_READY'
assert context['state']['budget']['consumed_total']==0 and context['state']['budget']['remaining']==1
assert context['capability']['single_baseline']['maximum_attempts']==1
assert context['capability']['profile_snapshot_sha256']==sha((r/'profile-snapshot.json').read_bytes())
assert len(context['candidates'])==1
assert context['candidates'][0]['strategy_sha256']==sha((r/'DogeConfirmedShockReversal3D-v2.py').read_bytes())
assert json.loads((r/'source-aggregation-qc.json').read_bytes())['status']=='SOURCE_QC_PASS'
record=dict(record_type='SEARCH_REGISTERED_PRE_RUN',cohort_id='issue98-doge-confirmed-reversal-single-v1',recorded_at_utc=datetime.now(timezone.utc).isoformat(),issue=98,maximum_actual_native_Search_runs=1,source=json.loads((r/'source-publication.json').read_bytes()),root=str(r),candidate_id=context['candidates'][0]['candidate_id'],strategy_sha256=context['candidates'][0]['strategy_sha256'],protocol_sha256=sha((r/'final-protocol.md').read_bytes()),D_status='PHYSICALLY_ISOLATED_QC_ONLY_NO_STRATEGY_RUN',H_Stress='SEALED_UNREAD_UNACQUIRED')
record['S_prepared_provenance_sha256']=sha((r/'search-campaign/acquisition/retained-data-provenance.json').read_bytes())
record['D_prepared_provenance_sha256']=sha((r/'development-pilot/development-isolation/retained-data-provenance.json').read_bytes())
record['aggregation_qc_sha256']=sha((r/'source-aggregation-qc.json').read_bytes())
ledger=Path('/Users/shenjianpeng/Documents/freqtrade-lab-local/search-research-supervision-20260902/global-research-ledger.jsonl')
with ledger.with_suffix(ledger.suffix+'.lock').open('a+b') as lock:
 fcntl.flock(lock.fileno(),fcntl.LOCK_EX)
 before=ledger.read_bytes()
 assert sha(before)==json.loads((r/'ledger-preregistration-receipt.json').read_bytes())['after_sha256']
 record['previous_prefix_sha256']=sha(before)
 addition=(json.dumps(record,sort_keys=True)+'\n').encode()
 with ledger.open('ab') as f:f.write(addition);f.flush();os.fsync(f.fileno())
 after=ledger.read_bytes();assert after==before+addition
 (r/'ledger-search-pre-run.json').write_text(json.dumps(record,indent=2)+'\n')
 (r/'ledger-search-pre-run-receipt.json').write_text(json.dumps(dict(before_sha256=sha(before),after_sha256=sha(after),prefix_preserved=True))+'\n')
page=urllib.request.urlopen(base+'/console').read().decode()
token=re.search(r'name="csrf-token" content="([^"]+)"',page)[1]
payload={'profile_id':'issue98-doge-confirmed-reversal-v1','candidate_ids':[context['candidates'][0]['candidate_id']]}
with (r/'search-http-request.json').open('x') as f:json.dump(payload,f)
request=urllib.request.Request(base+'/api/search-campaigns',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json','Origin':base,'X-CSRF-Token':token})
with urllib.request.urlopen(request,timeout=60) as response:value=json.load(response)
(r/'search-http-response.json').write_text(json.dumps(value,indent=2)+'\n')
print(json.dumps(value,ensure_ascii=False))
