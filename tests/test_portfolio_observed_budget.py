import hashlib
import json
import pytest
from lab.portfolio_budget import NativeBudget, BudgetError
from lab.portfolio_observed_prepare import jobs,encoded,SEMANTICS_SHA,RECEIPT_SHA
import lab.portfolio_observed_budget as observed


def setup(tmp_path,monkeypatch):
    with NativeBudget(tmp_path).locked() as old:
        old.reserve('synthetic/1',input_sha256='a'*64,code_sha256='b'*64,source_sha256='c'*64)
        old.finish('synthetic/1','SUCCEEDED','d'*64)
    before=(tmp_path/'calls.jsonl').read_bytes();digest=hashlib.sha256(before).hexdigest()
    monkeypatch.setattr(observed,'BUDGET_PREFIX_SHA',digest)
    manifests={j['key']:encoded(dict(key=j['key'],source_receipt_sha256=RECEIPT_SHA,
        semantics_sha256=SEMANTICS_SHA,code_bundle_sha256='b'*64)) for j in jobs()[:10]}
    plan=dict(first_batch={k:{'sha256':hashlib.sha256(v).hexdigest()} for k,v in manifests.items()},
        replacement_map={j['key']:j['replaces_unused_key_on_approval'] for j in jobs()},
        source_receipt_sha256=RECEIPT_SHA,semantics_sha256=SEMANTICS_SHA,
        native_budget_prefix_bytes=len(before),native_budget_prefix_sha256=digest)
    raw=encoded(plan)
    activation=dict(schema='issue125-observed-activation-v1',status='APPROVED_FIRST_EXPLORATION_BATCH',
        approval_reference='fabricated-unit-fixture-only',code_commit='e'*40,
        plan_sha256=hashlib.sha256(raw).hexdigest(),allowed_manifests={k:v['sha256'] for k,v in plan['first_batch'].items()})
    return before,plan,raw,activation,manifests


def test_budget_new_calls_keep_old_prefix_and_refuse_duplicates_sealed_retired(tmp_path,monkeypatch):
    before,plan,raw,activation,manifests=setup(tmp_path,monkeypatch)
    key=jobs()[0]['key']
    with observed.locked_observed(tmp_path,activation,plan,raw) as b:
        for forbidden in (jobs()[10]['key'],jobs()[0]['replaces_unused_key_on_approval'],'synthetic/8'):
            with pytest.raises(BudgetError):b.reserve_observed(forbidden,manifests[key])
        with pytest.raises(BudgetError):b.reserve_observed(key,manifests[key]+b' ')
        assert b.path.read_bytes()==before
        b.reserve_observed(key,manifests[key])
        with pytest.raises(BudgetError):b.reserve_observed(jobs()[1]['key'],manifests[jobs()[1]['key']])
        b.finish(key,'FAILED','f'*64)
    with observed.locked_observed(tmp_path,activation,plan,raw) as b:
        with pytest.raises(BudgetError):b.reserve_observed(key,manifests[key])
        assert b.path.read_bytes().startswith(before)
        second=jobs()[1]['key'];b.reserve_observed(second,manifests[second]);b.finish(second,'SUCCEEDED','f'*64)


def test_missing_or_changed_activation_fails_before_reservation(tmp_path,monkeypatch):
    before,plan,raw,activation,manifests=setup(tmp_path,monkeypatch)
    for changed in ({},dict(activation,status='PREPARED_NOT_AUTHORIZED'),dict(activation,plan_sha256='0'*64),
                    dict(activation,allowed_manifests={})):
        with pytest.raises(BudgetError):
            with observed.locked_observed(tmp_path,changed,plan,raw):pass
        assert (tmp_path/'calls.jsonl').read_bytes()==before


def test_shared_lock_excludes_legacy_worker(tmp_path,monkeypatch):
    _,plan,raw,activation,_=setup(tmp_path,monkeypatch)
    with NativeBudget(tmp_path).locked():
        with pytest.raises(BudgetError):
            with observed.locked_observed(tmp_path,activation,plan,raw):pass


def test_prepare_publishes_ten_jobs_and_ten_sealed_descriptors_without_activation(tmp_path,monkeypatch):
    import lab.portfolio_observed_prepare as prep
    from types import SimpleNamespace
    anchor=tmp_path/'budget';anchor.mkdir();(anchor/'calls.jsonl').write_bytes(b'unchanged-budget')
    monkeypatch.setattr(prep,'RUNTIME_ROOT',anchor)
    monkeypatch.setattr(prep,'ACTIVATION',anchor/'activation.json')
    monkeypatch.setattr(prep,'BUDGET_PREFIX_SHA',hashlib.sha256(b'unchanged-budget').hexdigest())
    monkeypatch.setattr(prep,'environment',lambda:{'unit_fixture':True})
    monkeypatch.setattr(prep,'load_view',lambda:SimpleNamespace(kind='OBSERVED_API_COMPLETE_FOR_EXPLORATORY_MODEL',funding=[]))
    monkeypatch.setattr(prep,'convert',lambda view,path: {})
    monkeypatch.setattr(prep,'market_assembly',lambda view:{})
    monkeypatch.setattr(prep,'code_files',lambda:{'unit_fixture.py':'a'*64})
    out=prep.prepare(tmp_path/'prepared');assert out['native_calls']==0
    plan=json.loads((tmp_path/'prepared/plan.json').read_bytes())
    assert len(plan['first_batch'])==len(plan['reserved'])==10
    assert all(j['input_sha256'] is None and j['status']=='SEALED_NOT_PREPARED' for j in plan['reserved'])
    assert not (anchor/'activation.json').exists() and (anchor/'calls.jsonl').read_bytes()==b'unchanged-budget'
    with pytest.raises(Exception,match='never overwrite'):prep.prepare(tmp_path/'prepared')
