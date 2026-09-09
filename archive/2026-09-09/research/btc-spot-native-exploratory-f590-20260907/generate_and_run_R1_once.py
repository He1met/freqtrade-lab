import http.client
import json
import os
import threading
import time
import traceback
from pathlib import Path
from initialize_and_synthetic_once import ROOT, append, put, sha
from lab.research_console import create_research_console_server

os.umask(0o077)
NATIVE=Path('/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue-43-profile-driven-v1')
assert json.loads((ROOT/'capture-execution-receipt.json').read_text())['status']=='CAPTURE_PASS_PENDING_SOURCE_QC'
assert sha((ROOT/'source-2024-01/retained-data-provenance.json').read_bytes())=='8355d77fe8dc7b35d525faa596cce5354466d6b487e4273b779d4d6b1c943af0'
assert sha((ROOT/'search-data-01/acquisition/retained-data-provenance.json').read_bytes())=='e0195da22b732215e651ee7eeb7a5ea7340eee9fba9ad168c792f30ce7a36391'
for name in ['console-runtime','unused-pilot']:
    (ROOT/name).mkdir(mode=0o700,exist_ok=False)
server=create_research_console_server(ROOT/'lab.sqlite',ROOT/'console-runtime',ROOT/'unused-pilot',0,
    search_root=ROOT/'search-data-01',exploration_contract=json.loads((ROOT/'exploration-contract.json').read_text()),
    codex_binary='/Applications/ChatGPT.app/Contents/Resources/codex',
    freqtrade_python=NATIVE/'venv/bin/python',freqtrade_source=NATIVE/'freqtrade',task_timeout_seconds=900)
port=server.server_port
thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
base=f'http://127.0.0.1:{port}'
put('console-entrypoint.json',{'base_url':base,'page':base+'/','generation_calls':0,'market_calls':0})
print(json.dumps({'page':base,'status':'CONSOLE_STARTED'}),flush=True)

def call(method,path,body=None):
    con=http.client.HTTPConnection('127.0.0.1',port,timeout=30)
    headers={}
    data=None
    if body is not None:
        data=json.dumps(body).encode();headers={'Content-Type':'application/json','Origin':base,'X-CSRF-Token':server.research_console_csrf_token}
    con.request(method,path,body=data,headers=headers)
    res=con.getresponse();raw=res.read();code=res.status;con.close()
    value=json.loads(raw)
    if code>=400:
        raise RuntimeError(f'{method} {path}: HTTP {code}: '+json.dumps(value,ensure_ascii=False)[:800])
    return value

def main():
    ids={}
    try:
        context=call('GET','/api/search/context')
        put('search-context-before-generation.json',context)
        entry=append({'record_type':'OBSERVED_TRAINING_SOURCE_QC_AND_GENERATION_START','pair':'BTC/USDT',
            'source_provenance_sha256':'8355d77fe8dc7b35d525faa596cce5354466d6b487e4273b779d4d6b1c943af0',
            'search_provenance_sha256':'e0195da22b732215e651ee7eeb7a5ea7340eee9fba9ad168c792f30ce7a36391',
            'rows':365,'score_window':'20240130-20241231','mode':'EXPLORATORY','generation_invocations':1,
            'market_native_calls':0},'b512b298997691e6c67122258671a20a2d009dfd513ed85037c8ca3fe485a498')
        put('source-qc-generation-start-receipt.json',entry)
        started=call('POST','/api/generations',json.loads((ROOT/'generation-request.json').read_text()))
        put('generation-start-api.json',started)
        gid=started['id'];ids['generation_id']=gid
        put('generation-identity.json',ids)
        print(json.dumps({'generation_id':gid,'status':'GENERATION_RUNNING'}),flush=True)
        deadline=time.monotonic()+1000
        while True:
            current=call('GET','/api/generations/'+gid)
            runtime=current.get('runtime_status')
            if current.get('status')!='RUNNING' and runtime not in {'STARTING','RUNNING'}:
                break
            if time.monotonic()>deadline:
                raise RuntimeError('Generation completion exceeded control timeout; no replay')
            time.sleep(2)
        put('generation-final-api.json',current)
        assert current['status']=='COMPLETED' and current['runtime_status']=='SUCCEEDED', 'Generation did not succeed'
        candidate=current['candidate']
        assert candidate['code_sha256']=='e1ab5c109eded7a6bd0e4e5d7b07f6c8e3082640530129ea9a390a2f89944611'
        assert candidate['code_text']==(ROOT/'BtcWeeklyMomentumFixedStake.py').read_text()
        cid=candidate['id'];ids['candidate_id']=cid
        reviewed=call('POST','/api/generations/'+gid+'/actions',{'action':'APPROVE'})
        assert reviewed['candidate']['review_status']=='APPROVED'
        put('generation-approval-api.json',reviewed)
        entry=append({'record_type':'AUTHORIZED_OBSERVED_EXPLORATORY_R1_START',**ids,'market_R1_invocation_budget_consumed':1,
            'strategy_sha256':candidate['code_sha256'],'maximum_R1_native_calls':1,'remaining_R2_calls_authorized':0,
            'D_H_Stress_benchmark_calls_authorized':0,'page':base})
        put('R1-start-ledger-receipt.json',entry)
        launched=call('POST','/api/search-campaigns',{'profile_id':'btc-spot-native-exploratory-f590-v1','candidate_ids':[cid]})
        put('R1-start-api.json',launched)
        sid=launched.get('campaign_id') or launched.get('id')
        assert isinstance(sid,str), 'Search API did not return an identity'
        ids['search_campaign_id']=sid
        put('R1-identities.json',ids)
        print(json.dumps({**ids,'status':'R1_STARTED'}),flush=True)
        deadline=time.monotonic()+1000
        while True:
            state=call('GET','/api/search-campaigns/'+sid)
            if state.get('status') not in {'STARTING','RUNNING'}:
                break
            if time.monotonic()>deadline:
                raise RuntimeError('R1 exceeded controller timeout; no replay')
            time.sleep(2)
        put('R1-final-api.json',state)
        done={'status':'R1_FINISHED_REVIEW_PENDING','project_status':state.get('status'),**ids,'page':base,
              'R2_D_H_Stress_benchmark_smoke_calls':0,'framework_two_round_completion_not_assumed':True}
        done['ledger']=append({'record_type':'OBSERVED_EXPLORATORY_R1_PROJECT_RETURNED',**done})
        put('R1-controller-delivery.json',done)
        print(json.dumps(done),flush=True)
    except BaseException as exc:
        traceback.print_exc()
        failure={'status':'NORMAL_ENTRYPOINT_FAILED_STOP','error_type':type(exc).__name__,'message':str(exc)[:1000],**ids,'page':base,'no_automatic_retry':True}
        failure['ledger']=append({'record_type':'OBSERVED_TRAINING_NORMAL_ENTRYPOINT_FAILURE',**failure})
        put('normal-entrypoint-failure.json',failure)
        print(json.dumps(failure),flush=True)

main()
print('WORKFLOW_STOPPED_CONSOLE_REMAINS_FOR_READONLY_REVIEW',flush=True)
thread.join()
