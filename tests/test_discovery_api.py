import copy
import json
from pathlib import Path
import pytest
from lab import discovery_api as api
from lab.discovery_job import MANIFEST, canonical, run_job, check_api_budget, locked
from lab.mechanism_precheck import PrecheckError


@pytest.fixture
def manifest(): return json.loads(MANIFEST.read_bytes())


def response():
    return {'model':api.MODEL,'status':'completed','error':None,'incomplete_details':None,
            'output':[{'type':'message','role':'assistant','status':'completed',
                       'content':[{'type':'output_text','text':'{"proposals":[]}'}]}],
            'usage':{'input_tokens':123,'output_tokens':456}}


def test_request_policy_and_reserved_price(manifest):
    r=json.loads(api.build_request(b'only supplied text',manifest))
    assert r['tools']==[] and r['tool_choice']=='none' and r['reasoning']=={'effort':'medium'}
    assert r['text']['format']['strict'] is True and r['text']['format']['type']=='json_schema'
    assert r['max_output_tokens']==8192 and r['model']==api.MODEL
    assert r['truncation']=='disabled' and r['service_tier']=='default' and r['store'] is False
    assert api.COST['reserve_micro_usd']==400000*.75+8192*4.5


def test_missing_key_zero_actions(manifest,tmp_path,monkeypatch):
    monkeypatch.delenv(api.KEY_ENV,raising=False)
    monkeypatch.setattr(api,'post_once',lambda *a:pytest.fail('API'))
    state=run_job(manifest,registry=tmp_path,http=lambda *a:pytest.fail('HTTP'))
    assert state['status']=='BLOCKED_MISSING_API_KEY' and state['attempts']==[]
    assert not (tmp_path/'api-budget-v1.json').exists()


def test_budget_precharged_and_no_refund(manifest,tmp_path):
    class Fake:
        def preflight(self,w): return {'synthetic':True}
        def __call__(self,*a):
            budget=json.loads((tmp_path/'api-budget-v1.json').read_bytes())
            state=json.loads((tmp_path/manifest['job_id']/'state.json').read_bytes())
            assert budget['charges'][0]['micro_usd']==336864
            assert state['attempts'][-1]['status']=='RESERVED'
            raise TimeoutError()
    s=run_job(manifest,registry=tmp_path,http=lambda *a:b'<p>test</p>',provider=Fake())
    assert s['status'].startswith('BLOCKED')
    assert json.loads((tmp_path/'api-budget-v1.json').read_bytes())['charges'][0]['micro_usd']==336864
    assert run_job(manifest,registry=tmp_path,http=lambda *a:pytest.fail('replay'),provider=Fake())==s


def test_overbudget_and_orphan_reservation(manifest,tmp_path):
    (tmp_path/'api-budget-v1.json').write_text(json.dumps({'limit_micro_usd':5000000,'charges':[{'job_id':'prior','micro_usd':4900000}]}))
    with locked(tmp_path):
        with pytest.raises(PrecheckError,match='API_BUDGET_EXCEEDED'):
            check_api_budget(tmp_path,manifest,'a',reserve=True)
    (tmp_path/'api-budget-v1.json').write_text(json.dumps({'limit_micro_usd':5000000,'charges':[{'job_id':manifest['job_id'],'micro_usd':336864}]}))
    class Fake:
        def preflight(self,w): return {}
    s=run_job(manifest,registry=tmp_path,http=lambda *a:pytest.fail('HTTP'),provider=Fake())
    assert s['status']=='BLOCKED_API_RESERVATION_ALREADY_EXISTS'


@pytest.mark.parametrize('status',[401,429])
def test_http_failure_no_retry(manifest,monkeypatch,status):
    monkeypatch.setenv(api.KEY_ENV,'synthetic-test-key-not-a-credential')
    calls=[]
    class Conn:
        def __init__(self,*a,**k):pass
        def request(self,*a,**k):calls.append(1)
        def getresponse(self):return type('R',(),{'status':status})()
        def close(self):pass
    monkeypatch.setattr(api.http.client,'HTTPSConnection',Conn)
    with pytest.raises(PrecheckError,match='API_HTTP_'+str(status)): api.post_once(b'{}',1,100)
    assert len(calls)==1


def test_timeout_no_retry(manifest,monkeypatch):
    monkeypatch.setenv(api.KEY_ENV,'synthetic-test-key-not-a-credential');calls=[]
    class Conn:
        def __init__(self,*a,**k):pass
        def request(self,*a,**k):calls.append(1);raise TimeoutError()
        def close(self):pass
    monkeypatch.setattr(api.http.client,'HTTPSConnection',Conn)
    with pytest.raises(PrecheckError,match='API_TRANSPORT_UNKNOWN'):api.post_once(b'{}',1,100)
    assert len(calls)==1


def test_reasoning_metadata_ignored(manifest):
    r=response();r['output'].insert(0,{'type':'reasoning','id':'rs_test','summary':[{'type':'summary_text','text':'Not strategy evidence'}]})
    p,receipt=api.parse_response(canonical(r),manifest)
    assert p=={'proposals':[]} and 'Not strategy evidence' not in str(receipt)
    r['output'].append({'type':'function_call','name':'touch','arguments':'EVIL'})
    with pytest.raises(PrecheckError):api.parse_response(canonical(r),manifest)


@pytest.mark.parametrize('mode',['refusal','incomplete','tool','unknown','two_messages','bad_json','schema','missing_usage'])
def test_response_fail_closed(manifest,mode):
    r=response()
    if mode=='refusal':r['output'][0]['content']=[{'type':'refusal','refusal':'no'}]
    elif mode=='incomplete':r['status']='incomplete'
    elif mode in ('tool','unknown'):r['output'].append({'type':'function_call' if mode=='tool' else 'new_thing'})
    elif mode=='two_messages':r['output']*=2
    elif mode=='bad_json':r['output'][0]['content'][0]['text']='not JSON'
    elif mode=='schema':r['output'][0]['content'][0]['text']='{"proposals":[{}]}'
    else:r.pop('usage')
    with pytest.raises(PrecheckError):api.parse_response(canonical(r),manifest)
