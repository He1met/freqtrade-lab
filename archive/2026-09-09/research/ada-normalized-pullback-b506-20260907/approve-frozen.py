import json, re, urllib.request, hashlib
from pathlib import Path
r=Path(__file__).parent
d=json.loads((r/'generation-status.json').read_bytes())
code=(r/'AdaNormalizedTrendPullback3D.py').read_bytes()
assert d['status']=='COMPLETED' and d['tool_event_count']==0 and d['returned_strategy_count']==1
assert d['candidate']['code_text'].encode()==code
assert d['candidate']['code_sha256']==hashlib.sha256(code).hexdigest()=='eb1f551464519f52b6f29469843dfe0acc880b53a6e86b778b94f09a88eda4b8'
assert not (r/'generation-approved.json').exists()
base='http://127.0.0.1:8799'
html=urllib.request.urlopen(base+'/console').read().decode()
token=re.search(r'name="csrf-token" content="([^"]+)"',html).group(1)
req=urllib.request.Request(base+'/api/generations/'+d['id']+'/actions',data=b'{"action":"APPROVE"}',headers={'Content-Type':'application/json','Origin':base,'X-CSRF-Token':token},method='POST')
body=urllib.request.urlopen(req,timeout=60).read()
(r/'generation-approved.json').write_bytes(body)
approved=json.loads(body)
print(json.dumps({'status':approved['status'],'candidate_id':approved['candidate']['id'],'review_status':approved['candidate']['review_status'],'code_sha256':approved['candidate']['code_sha256']}))
