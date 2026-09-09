from pathlib import Path
from datetime import datetime, timezone
import json, urllib.request, hashlib, subprocess
from lab.database import get_connection
from lab import search_campaign as sc
r=Path(__file__).parent
sha=lambda b:hashlib.sha256(b).hexdigest()
def save(name,v):
    with (r/name).open('x') as f:json.dump(v,f,sort_keys=True,indent=2,allow_nan=False);f.write('\n')
def get(path,name):
    with urllib.request.urlopen('http://127.0.0.1:8801'+path,timeout=30) as response:
        assert response.status==200
        value=json.load(response)
    save(name,value)
    return value
search=json.loads((r/'rejection-live-search-api.json').read_text())
research=json.loads((r/'rejection-live-research-api.json').read_text())
generation=json.loads((r/'rejection-live-generation-api.json').read_text())
attachment=json.loads((r/'rejection-attachment-receipt.json').read_text())['attachment']
assert search['state']['status']=='SEARCH_FINALIST_FROZEN'
assert search['state']['search_protocol_rejection']==attachment
assert generation['candidate']['search_protocol_rejection']==attachment
assert generation['candidate']['review_status']=='APPROVED'
assert len(attachment['failed_gates'])==2 and attachment['summary']['conservative_net_usdt']>0
assert research['candidates'][0]['status']=='BLOCKED_SECURITY'
assert research['candidates'][0]['reason']=='Full frozen protocol REJECTED; Development cannot start'
assert research['latest_research_run_id'] is None
assert search['state']['budget']['consumed_total']==1 and search['state']['budget']['remaining']==0
# The real Console GET executes verified_finalist_binding using its owned
# frozen capability. A separate freeze was correctly denied by that root lock.
# Do not bypass ownership or restart just to duplicate the same read-only call.
rejection=dict(code='search_protocol_rejected',message=research['candidates'][0]['reason'],
    verification_path='GET /api/research/context -> ResearchConsoleController.research_context -> verified_finalist_binding',
    standalone_freeze='BLOCKED_DATA: Search capability could not be frozen (Console owns root)',
    standalone_verified_finalist_binding_called=False)
with get_connection(r/'lab.sqlite',read_only=True) as c:
    c.execute('BEGIN')
    current={t:[dict(row) for row in c.execute('SELECT * FROM '+t+' ORDER BY id')] for t in sc.BUSINESS_TABLES}
assert current==json.loads((r/'rejection-attachment-after.json').read_text())
save('rejection-live-verification.json',dict(status='VERIFIED_READ_ONLY',at=datetime.now(timezone.utc).isoformat(),
    bound_finalist_rejection=rejection,post_attachment_db_unchanged=True,counts={t:len(v) for t,v in current.items()},
    actual_Search_runs=1,actual_Development_Holdout_Stress_runs=0,ResearchRun_POST_calls=0,
    merge_sha=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
    artifact_sha256={name:sha((r/name).read_bytes()) for name in ['rejection-live-search-api.json','rejection-live-research-api.json','rejection-live-generation-api.json','rejection-rendered-page-evidence.json']}))
print(json.dumps(dict(status='VERIFIED_READ_ONLY',rejection=rejection,db_unchanged=True)))
