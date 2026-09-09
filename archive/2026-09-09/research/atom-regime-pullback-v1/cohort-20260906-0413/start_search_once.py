"""Issue92 one authorized Console Search POST, no retry or alternate runner."""
import hashlib
import json
import os
import re
from datetime import datetime,timezone
from pathlib import Path
from urllib.request import Request,urlopen

ROOT=Path(__file__).resolve().parent
BASE='http://127.0.0.1:50783'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(name,value):
    with (ROOT/name).open('xb') as f:
        f.write((json.dumps(value,indent=2)+'\n').encode());f.flush();os.fsync(f.fileno())

with urlopen(BASE+'/api/search/context',timeout=10) as r:context=json.load(r)
assert context['state']['status']=='SEARCH_READY' and context['state']['budget']['consumed_total']==0 and context['state']['budget']['remaining']==1
f=json.loads((ROOT/'freeze-receipt.json').read_text())
assert context['candidates'][0]['candidate_id']==f['candidate_id']
save('search-authorization.json',{'created_at':datetime.now(timezone.utc).isoformat(),'issue':92,'authorization_source':'supervisor task 01a05dcc-17fd-7972-9177-9fed95e4b07a explicit one-Search authorization','mode':'CURRENT_CONSOLE_POST_ONLY','allowed_native_runs':1,'maximum_rounds':1,'maximum_attempts':1,'search_timerange':'20210901-20230901','source_ready_sha256':sha(ROOT/'source-ready.json'),'protocol_sha256':sha(ROOT/'protocol.md'),'freeze_sha256':sha(ROOT/'freeze-receipt.json'),'db_binding_addendum_sha256':sha(ROOT/'freeze-db-binding-addendum.json'),'script_sha256':sha(Path(__file__)),'profile_id':f['profile_id'],'candidate_id':f['candidate_id'],'other_phase_authorized':False,'finalist_import_authorized':False})
with urlopen(BASE+'/console',timeout=10) as r:page=r.read().decode()
token=re.search(r'<meta name="csrf-token" content="([^"]+)"',page).group(1)
payload={'profile_id':f['profile_id'],'candidate_ids':[f['candidate_id']]}
save('search-post-intent.json',{'endpoint':BASE+'/api/search-campaigns','payload':payload,'automatic_retry':False,'created_at':datetime.now(timezone.utc).isoformat()})
request=Request(BASE+'/api/search-campaigns',data=json.dumps(payload).encode(),headers={'Origin':BASE,'Content-Type':'application/json','X-CSRF-Token':token},method='POST')
with urlopen(request,timeout=60) as r:response=json.load(r);status=r.status
save('search-post-response.json',{'status_code':status,'response':response})
print(json.dumps({'http_status':status,'response':response}))
