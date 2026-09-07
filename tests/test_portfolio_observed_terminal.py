import hashlib
import json
import time
import pytest
from lab.portfolio_observed_prepare import encoded,jobs
import lab.portfolio_observed_integrity as integrity
import lab.portfolio_observed_budget as observed
from scripts import run_portfolio_observed as runner
from test_portfolio_observed_budget import setup


def controls(tmp_path,monkeypatch):
    monkeypatch.setattr(integrity,'git_state',lambda path:dict(commit='e'*40,tree='f'*40,dirty=''))
    monkeypatch.setattr(integrity,'DEPENDENCIES',{})
    files=[]
    for name in ('code.py','input.feather','source.json','interpreter','manifest.json','activation.json','plan.json'):
        p=tmp_path/name;p.write_bytes(b'frozen');files.append(str(p))
    return files


def call_fixture(tmp_path,monkeypatch):
    budget_root=tmp_path/'budget';budget_root.mkdir()
    old,plan,raw,activation,manifests=setup(budget_root,monkeypatch)
    root=tmp_path/'output';root.mkdir();key=jobs()[0]['key']
    (root/'manifest.json').write_bytes(manifests[key])
    files=controls(tmp_path,monkeypatch)
    monkeypatch.setattr(runner,'checkpoint_budget',lambda:None)
    monkeypatch.setattr(runner,'verify_anchor',lambda:None)
    return budget_root,root,key,old,plan,raw,activation,manifests,files


def test_real_internal_deadline_consumes_and_closes_slot_with_traceback(tmp_path,monkeypatch):
    br,root,key,old,plan,raw,activation,manifests,files=call_fixture(tmp_path,monkeypatch)
    def blocked(*args):
        (root/'trace.json').write_bytes(b'[]')
        try:time.sleep(.1)
        except Exception:raise AssertionError('deadline must escape native safe wrapper')
    monkeypatch.setattr(runner,'run_native',blocked)
    with observed.locked_observed(br,activation,plan,raw) as budget:
        budget.reserve_observed(key,manifests[key])
        before=integrity.freeze(files+[str(budget.path)])
        result=runner.execute_reserved(root,key,{'native_timeout_seconds':.01},budget,before)
        assert result['status']=='INTERRUPTED' and not budget.pending()
        assert sum(r['event']=='RESERVED' for r in budget.events)==2  # one old + this one
        exception=json.loads((root/'exception.json').read_bytes())
        assert exception['type']=='NativeDeadline' and 'time.sleep' in exception['traceback']
        assert (root/'trace.json').exists() and budget.path.read_bytes().startswith(old)
        with pytest.raises(observed.BudgetError,match='BATCH_STOPPED'):
            budget.reserve_observed(jobs()[1]['key'],manifests[jobs()[1]['key']])


@pytest.mark.parametrize('failure',[False,True])
@pytest.mark.parametrize('changed',range(7),ids=['code','input','source','interpreter','manifest','activation','plan'])
def test_every_control_drift_blocks_economic_output_on_success_or_failure(tmp_path,monkeypatch,failure,changed):
    br,root,key,_,plan,raw,activation,manifests,files=call_fixture(tmp_path,monkeypatch)
    def native(*args):
        from pathlib import Path
        Path(files[changed]).write_bytes(b'changed')
        if failure:raise ValueError('fabricated unit exception')
        return {'modeled_net':123,'modeled_risk_gate':True}
    monkeypatch.setattr(runner,'run_native',native)
    with observed.locked_observed(br,activation,plan,raw) as budget:
        budget.reserve_observed(key,manifests[key]);before=integrity.freeze(files+[str(budget.path)])
        out=runner.execute_reserved(root,key,{'native_timeout_seconds':1},budget,before)
        assert out['status']=='FAILED' and not budget.pending()
    result=json.loads((root/'result.json').read_bytes())
    assert result['status']=='CONTROL_INTEGRITY' and result['economic_output'] is None
    assert 'modeled_net' not in result and 'modeled_risk_gate' not in result
    if failure:assert 'ValueError' in result['exception']['traceback']
    assert json.loads((root/'terminal-integrity.json').read_bytes())['status']=='CONTROL_INTEGRITY'


def test_valid_negative_path_does_not_stop_batch(tmp_path,monkeypatch):
    br,root,key,_,plan,raw,activation,manifests,files=call_fixture(tmp_path,monkeypatch)
    monkeypatch.setattr(runner,'run_native',lambda *args:{'modeled_net':-10,'modeled_risk_gate':False})
    with observed.locked_observed(br,activation,plan,raw) as budget:
        budget.reserve_observed(key,manifests[key]);before=integrity.freeze(files+[str(budget.path)])
        out=runner.execute_reserved(root,key,{'native_timeout_seconds':1},budget,before)
        assert out['status']=='SUCCEEDED'
        next_key=jobs()[1]['key'];budget.reserve_observed(next_key,manifests[next_key]);budget.finish(next_key,'SUCCEEDED','f'*64)


def test_anchor_change_at_lock_boundary_refuses_native_and_reservation(tmp_path,monkeypatch):
    br,root,key,old,plan,_,activation,manifests,_=call_fixture(tmp_path,monkeypatch)
    prepared=tmp_path/'prepared';prepared.mkdir();mpath=prepared/'01.json';mpath.write_bytes(manifests[key])
    plan['first_batch'][key]['path']=str(mpath)
    raw=encoded(plan);(prepared/'plan.json').write_bytes(raw)
    activation['plan_sha256']=hashlib.sha256(raw).hexdigest()
    apath=tmp_path/'approved.json';apath.write_bytes(encoded(activation))
    monkeypatch.setattr(runner,'PREPARED',prepared);monkeypatch.setattr(runner,'ACTIVATION',apath)
    monkeypatch.setattr(runner,'RUNTIME_ROOT',br);monkeypatch.setattr(runner,'verify_prepared',lambda *args:None)
    calls=[]
    def anchor():
        calls.append('anchor')
        if len(calls)==2:raise ValueError('anchor changed while waiting for shared writer lock')
    monkeypatch.setattr(runner,'verify_anchor',anchor)
    monkeypatch.setattr(runner,'run_native',lambda *args:pytest.fail('native must not be reached'))
    with pytest.raises(ValueError,match='anchor changed'):runner.run(key)
    assert len(calls)==2 and (br/'calls.jsonl').read_bytes()==old


@pytest.mark.parametrize('message',['generic assembly failure','MODEL_INVALID forbidden native force exit'])
def test_first_engineering_failure_closes_slot_and_stops_entire_batch(tmp_path,monkeypatch,message):
    br,root,key,_,plan,raw,activation,manifests,files=call_fixture(tmp_path,monkeypatch)
    def failed(*args):raise ValueError(message)
    monkeypatch.setattr(runner,'run_native',failed)
    with observed.locked_observed(br,activation,plan,raw) as budget:
        budget.reserve_observed(key,manifests[key]);before=integrity.freeze(files+[str(budget.path)])
        out=runner.execute_reserved(root,key,{'native_timeout_seconds':1},budget,before)
        assert out['status']=='FAILED' and not budget.pending()
        result=json.loads((root/'result.json').read_bytes())
        assert result['status']=='MODEL_INVALID' and message in result['exception']['traceback']
        for next_key in list(manifests)[1:]:
            with pytest.raises(observed.BudgetError,match='BATCH_STOPPED'):
                budget.reserve_observed(next_key,manifests[next_key])


def test_freeze_rejects_hash_change_between_validation_and_reservation(tmp_path,monkeypatch):
    files=controls(tmp_path,monkeypatch)
    expected={name:hashlib.sha256(b'approved').hexdigest() for name in files}
    with pytest.raises(Exception,match='reservation boundary'):integrity.freeze(files,expected)
