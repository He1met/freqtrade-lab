"""Synthetic integration and temporary 18+10 budget history; no native imports."""
from datetime import datetime,timedelta,timezone
from decimal import Decimal,getcontext
from fractions import Fraction
import hashlib
import json
from types import SimpleNamespace
import pytest
from lab.portfolio_causal import PAIRS,State,Entry,Episode,PriceBar
from lab.portfolio_risk_v2 import RiskState
from lab.portfolio_short import reserve_additions,configuration
from lab.portfolio_observed_adapter import ObservedCallbacks
from lab import portfolio_observed_control as control
from lab import portfolio_corrected as corrected
from lab import portfolio_observed_budget as old_budget
from lab.portfolio_budget import LockedBudget,BudgetError,verify_checkpoint
from lab.portfolio_source import SourceError


def test_actual_observed_path_calls_exact_reserve_and_keeps_native_padding(monkeypatch):
    t=datetime(2024,8,1,2,tzinfo=timezone.utc)
    prices={PAIRS[0]:60000,PAIRS[1]:3000}
    bars={p:PriceBar(t,px,px,px,px) for p,px in prices.items()}
    view=SimpleNamespace(start=t-timedelta(hours=2),end=t+timedelta(days=2),
                         known=lambda at:(bars,prices,prices),daily={})
    ep=Episode(Entry(PAIRS[0],'trend',1,Decimal('.001'),Decimal(1000),None),
               t-timedelta(hours=1),Decimal(60000),Decimal(59000),t+timedelta(days=5))
    state=control.ObservedState(RiskState(State('A-trend',episodes=(ep,))))
    calls=[]
    assert control.reserve_additions is reserve_additions
    def spy(E,a,d,px,step,config):
        assert getcontext().prec==60
        q=reserve_additions(E,a,d,px,step,config)
        assert all(abs(q[p])<=abs(d[p]) for p in PAIRS)
        calls.append((dict(d),q));return q
    monkeypatch.setattr(control,'reserve_additions',spy)
    rules={p:dict(step='.001',min_qty='.001',max_qty='1000',min_notional='50' if p==PAIRS[0] else '20') for p in PAIRS}
    _,out=control.advance_observed(state,view,t,Decimal(1000),Decimal(1000),
        {p:Decimal(0) for p in PAIRS},rules,{p:t-timedelta(days=1) for p in PAIRS},
        configuration('A-trend','base'),SimpleNamespace(peak=Fraction(1000),warning=False,halted=False))
    assert len(calls)==1 and out['target_quantities'][PAIRS[0]]==Decimal('.001')
    callback=ObservedCallbacks();callback.targets=out['target_quantities'];callback.target_time=t
    # Original native minQty padding is 0.001*60000*1.05=63, above target60.
    assert callback.custom_stake_amount(PAIRS[0],t,60000,60,63,1000,1,'observed_open','long')==0
    assert callback.custom_stake_amount(PAIRS[0],t,60000,60,60,1000,1,'observed_open','long')==60
    trade=SimpleNamespace(pair=PAIRS[0],is_short=False,amount=.0005,stake_amount=30)
    assert callback.adjust_trade_position(trade,t,60000,0,31.5,1000) is None


def setup(tmp_path,monkeypatch):
    root=tmp_path/'budget';root.mkdir()
    ledger=LockedBudget(root)
    for i in range(1,9):
        key=f'synthetic/{i}'
        ledger._append(dict(event='RESERVED',key=key,input_sha256='a'*64,source_sha256='b'*64,code_sha256='c'*64))
        ledger.finish(key,'SUCCEEDED','d'*64)
    raw8=ledger.path.read_bytes()
    monkeypatch.setattr(old_budget,'BUDGET_PREFIX_SHA',hashlib.sha256(raw8).hexdigest())
    oldplanroot=tmp_path/'old';oldplanroot.mkdir()
    monkeypatch.setattr(corrected.old,'PREPARED',oldplanroot)
    monkeypatch.setattr(corrected.old,'ACTIVATION',tmp_path/'old-activation.json')
    oldjobs=corrected.old.jobs()
    oldman={j['key']:corrected.encoded(dict(key=j['key'],source_receipt_sha256=corrected.old.RECEIPT_SHA,
        semantics_sha256=corrected.old.SEMANTICS_SHA,code_bundle_sha256='c'*64)) for j in oldjobs[:10]}
    oldplan=dict(first_batch={k:dict(path='unused-fixture-path',sha256=hashlib.sha256(v).hexdigest()) for k,v in oldman.items()},
        replacement_map={j['key']:j['replaces_unused_key_on_approval'] for j in oldjobs},
        source_receipt_sha256=corrected.old.RECEIPT_SHA,semantics_sha256=corrected.old.SEMANTICS_SHA,
        native_budget_prefix_bytes=len(raw8),native_budget_prefix_sha256=hashlib.sha256(raw8).hexdigest())
    pr=corrected.encoded(oldplan);(oldplanroot/'plan.json').write_bytes(pr)
    activation=dict(schema='issue125-observed-activation-v1',status='APPROVED_FIRST_EXPLORATION_BATCH',
        approval_reference='synthetic-test-only',code_commit='e'*40,
        plan_sha256=hashlib.sha256(pr).hexdigest(),allowed_manifests={k:v['sha256'] for k,v in oldplan['first_batch'].items()})
    corrected.old.ACTIVATION.write_bytes(corrected.encoded(activation))
    budget=old_budget.ObservedLockedBudget(root,activation,oldplan,pr)
    for key,m in oldman.items():budget.reserve_observed(key,m);budget.finish(key,'SUCCEEDED','f'*64)
    prefix=budget.path.read_bytes()
    spec=corrected.protocol().copy()
    spec.update(original_plan_sha256=hashlib.sha256(pr).hexdigest(),
        original_activation_sha256=corrected.sha(corrected.old.ACTIVATION),
        budget_prefix_bytes=len(prefix),budget_prefix_sha256=hashlib.sha256(prefix).hexdigest())
    monkeypatch.setattr(corrected,'protocol',lambda:spec)
    monkeypatch.setattr(corrected,'RUNTIME',root)
    monkeypatch.setattr(corrected,'PREPARED',tmp_path/'new-prepared')
    monkeypatch.setattr(corrected,'ACTIVATION',tmp_path/'new-activation.json')
    monkeypatch.setattr(corrected,'OUTPUT',tmp_path/'new-outputs')
    manifests={j['key']:corrected.encoded(dict(key=j['key'],correction_protocol_sha256=corrected.PROTOCOL_SHA,
        source_receipt_sha256=corrected.old.RECEIPT_SHA,semantics_sha256=corrected.old.SEMANTICS_SHA,
        code_bundle_sha256='c'*64,replaces_unused_key_on_approval=j['replaces_unused_key_on_approval'])) for j in corrected.mapping()}
    plan=corrected.expected_plan({k:dict(path=str(corrected.PREPARED/'jobs'/f'{i+1:02d}.json'),
        sha256=hashlib.sha256(v).hexdigest()) for i,(k,v) in enumerate(manifests.items())})
    raw=corrected.encoded(plan)
    act=dict(schema='issue131-corrected-activation-v1',status='APPROVED_CORRECTED_EXPLORATORY_BATCH',
        approval_reference='synthetic-test-only',code_commit='e'*40,correction_protocol_sha256=corrected.PROTOCOL_SHA,
        plan_sha256=hashlib.sha256(raw).hexdigest(),allowed_manifests={k:v['sha256'] for k,v in plan['first_batch'].items()})
    return root,prefix,plan,raw,act,manifests


def test_budget_reads_18_and_finishes_28_without_reset_or_old_key_unlock(tmp_path,monkeypatch):
    root,prefix,plan,raw,act,manifests=setup(tmp_path,monkeypatch)
    for key,m in manifests.items():
        b=corrected.CorrectedBudget(root,act,plan,raw)
        for forbidden in [corrected.old.jobs()[0]['key'],corrected.old.jobs()[10]['key'],
                          corrected.mapping()[0]['replaces_unused_key_on_approval'],'synthetic/8','retry/2']:
            with pytest.raises(BudgetError):b.reserve_corrected(forbidden,m)
        b.reserve_corrected(key,m);b.finish(key,'SUCCEEDED','f'*64)
        with pytest.raises(BudgetError,match='consumed'):b.reserve_corrected(key,m)
    b=corrected.CorrectedBudget(root,act,plan,raw)
    assert sum(r['event']=='RESERVED' for r in b.events)==28
    assert (root/'calls.jsonl').read_bytes().startswith(prefix)
    verify_checkpoint((root/'calls.jsonl').read_bytes(),{'bytes':len(prefix),'sha256':hashlib.sha256(prefix).hexdigest()})


def test_first_failure_pending_and_mapping_drift_fail_closed(tmp_path,monkeypatch):
    root,prefix,plan,raw,act,ms=setup(tmp_path,monkeypatch);keys=list(ms)
    b=corrected.CorrectedBudget(root,act,plan,raw)
    b.reserve_corrected(keys[0],ms[keys[0]])
    with pytest.raises(BudgetError,match='pending'):b.reserve_corrected(keys[1],ms[keys[1]])
    b.finish(keys[0],'FAILED','f'*64)
    b=corrected.CorrectedBudget(root,act,plan,raw)
    with pytest.raises(BudgetError,match='BATCH_STOPPED'):b.reserve_corrected(keys[1],ms[keys[1]])
    changed=dict(plan,replacement_map={})
    with pytest.raises(BudgetError,match='plan drift'):corrected.validate_activation(act,changed,corrected.encoded(changed))
    assert (root/'calls.jsonl').read_bytes().startswith(prefix)


def test_unapproved_control_checkpoint_and_shared_lock(tmp_path,monkeypatch):
    root,prefix,plan,raw,act,ms=setup(tmp_path,monkeypatch)
    for changed in ({},dict(act,status='NOT_APPROVED'),dict(act,code_commit=None),dict(act,allowed_manifests={})):
        with pytest.raises(BudgetError):corrected.CorrectedBudget(root,changed,plan,raw)
    with pytest.raises(BudgetError,match='absent'):corrected.run(next(iter(ms)))
    assert (root/'calls.jsonl').read_bytes()==prefix and not corrected.OUTPUT.exists()
    with corrected.locked(act,plan,raw):
        with pytest.raises(BudgetError,match='writer'):
            with corrected.locked(act,plan,raw):pass
    (root/'calls.jsonl').write_bytes(prefix[:-1])
    with pytest.raises(BudgetError,match='checkpointed'):corrected.CorrectedBudget(root,act,plan,raw)


def test_prepare_copies_view_only_and_template_cannot_activate(tmp_path,monkeypatch):
    root,prefix,_,_,_,_=setup(tmp_path,monkeypatch)
    monkeypatch.setattr(corrected,'verify_anchor',lambda:None)
    monkeypatch.setattr(corrected.old,'environment',lambda:{'synthetic-fixture':True})
    monkeypatch.setattr(corrected.old,'code_files',lambda:{'fixture.py':'a'*64})
    monkeypatch.setattr(corrected,'original_evidence',lambda:{})
    (corrected.old.PREPARED/'data').mkdir()
    for name in ('data/example.feather','assembly.json','events.json'):
        (corrected.old.PREPARED/name).write_bytes(b'synthetic-bytes-no-market-data')
    base=dict(status='PREPARED_NOT_AUTHORIZED',data_files={'example.feather':corrected.sha(corrected.old.PREPARED/'data/example.feather')},
        assembly_sha256=corrected.sha(corrected.old.PREPARED/'assembly.json'),funding_event_table_sha256=corrected.sha(corrected.old.PREPARED/'events.json'))
    monkeypatch.setattr(corrected,'original_manifest',lambda job:(base,'f'*64))
    result=corrected.prepare();assert result['native_calls']==result['new_gets']==0
    assert len(list((corrected.PREPARED/'jobs').glob('*.json')))==10
    assert (corrected.PREPARED/'data/example.feather').read_bytes()==b'synthetic-bytes-no-market-data'
    pr=(corrected.PREPARED/'plan.json').read_bytes();plan=json.loads(pr)
    template=json.loads((corrected.PREPARED/'activation-template.json').read_bytes())
    with pytest.raises(BudgetError,match='approval'):corrected.validate_activation(template,plan,pr)
    assert (root/'calls.jsonl').read_bytes()==prefix and not corrected.ACTIVATION.exists()
    with pytest.raises(SourceError,match='never overwrite'):corrected.prepare()


def test_corrected_lock_boundary_drift_prevents_reservation(tmp_path,monkeypatch):
    root,prefix,plan,raw,act,ms=setup(tmp_path,monkeypatch)
    corrected.PREPARED.mkdir();(corrected.PREPARED/'jobs').mkdir()
    (corrected.PREPARED/'plan.json').write_bytes(raw)
    corrected.ACTIVATION.write_bytes(corrected.encoded(act))
    for key,item in plan['first_batch'].items():
        from pathlib import Path
        Path(item['path']).write_bytes(ms[key])
    monkeypatch.setattr(corrected,'verify_manifest',lambda *args,**kwargs:None)
    calls=[]
    def anchor():
        calls.append(1)
        if len(calls)==2:raise BudgetError('anchor lock-time drift')
    monkeypatch.setattr(corrected,'verify_anchor',anchor)
    from scripts import run_portfolio_observed as runner
    monkeypatch.setattr(runner,'execute_reserved',lambda *args:pytest.fail('no native boundary allowed'))
    with pytest.raises(BudgetError,match='lock-time'):corrected.run(next(iter(ms)))
    assert len(calls)==2 and (root/'calls.jsonl').read_bytes()==prefix
    assert not corrected.OUTPUT.exists()


def test_integrity_uses_new_prepared_and_activation_paths(tmp_path,monkeypatch):
    from lab import portfolio_observed_integrity as integrity
    receipt=tmp_path/'receipt.json';receipt.write_bytes(b'{"source_files":[]}')
    monkeypatch.setattr(integrity,'RECEIPT',receipt)
    monkeypatch.setattr(integrity,'RECEIPT_SHA',corrected.sha(receipt))
    prepared=tmp_path/'corrected';activation=tmp_path/'new-approval.json'
    m=dict(code_files={},data_files={'input.feather':'a'*64},environment={'interpreter_sha256':'b'*64},
           assembly_sha256='c'*64,funding_event_table_sha256='d'*64)
    hashes=integrity.controlled_hashes(prepared/'manifest.json',m,b'm',b'a',b'p',prepared=prepared,activation_path=activation)
    assert str(prepared/'data/input.feather') in hashes
    assert str(prepared/'plan.json') in hashes and str(activation) in hashes
    assert str(integrity.PREPARED/'plan.json') not in hashes and str(integrity.ACTIVATION) not in hashes
