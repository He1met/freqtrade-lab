from pathlib import Path
import sys,json,hashlib
from http_request import request
R=Path(__file__).resolve().parent
def read(label): return json.loads((R/'http-evidence'/(label+'.json')).read_text())['response']
action=sys.argv[1];n=int(sys.argv[2]) if len(sys.argv)>2 else 0
if action=='generate':
    source=(R.parent/f'ConsolidationChannelR{n}.py').read_text()
    payload={'profile_id':'sol-channel-k-v1-e68e-5pfysdgg','idea':'Frozen complete source; reproduce character-for-character including final newline. No optimization, edits, or repairs.\n'+source,'strategy_family':'sol_prior_close_channel_consolidation_v1','expected_failure_mode':'Insufficient closed trades or net return after costs; noisy breakouts. No parameter/window rescue.'}
    if n==2: payload['parent_candidate_id']=read('generation-1-approved')['candidate']['id']
    status,value=request('/api/generations',payload,f'generation-{n}-submitted')
elif action=='poll-generation':
    gid=read(f'generation-{n}-submitted')['id']
    status,value=request('/api/generations/'+gid,None,f'generation-{n}-'+sys.argv[3])
elif action=='approve':
    value=read(f'generation-{n}-final');candidate=value['candidate']
    source=(R.parent/f'ConsolidationChannelR{n}.py').read_bytes()
    assert candidate['code_text'].encode()==source
    assert candidate['code_sha256']==hashlib.sha256(source).hexdigest()
    assert value['status']=='COMPLETED'
    status,value=request('/api/generations/'+value['id']+'/actions',{'action':'APPROVE'},f'generation-{n}-approved')
elif action=='start':
    candidate=read(f'generation-{n}-approved')['candidate']['id']
    if n==1:
        status,value=request('/api/search-campaigns',{'profile_id':'sol-channel-k-v1-e68e-5pfysdgg','candidate_ids':[candidate]},'search-1-submitted')
    else:
        cid=read('search-1-submitted')['campaign_id']
        status,value=request('/api/search-campaigns/'+cid+'/actions',{'action':'START_ROUND_2','candidates':[{'candidate_id':candidate,'changed_factor':'entry_prior_close_channel_28_10pct_v1'}]},'search-2-submitted')
else: raise RuntimeError('unsupported explicit action')
print(json.dumps({'http_status':status,'response':value},ensure_ascii=False))
assert status in (200,202)
