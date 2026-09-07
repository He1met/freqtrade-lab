"""Dispatcher control tests: fake function only, temporary budget, NO native."""
import json
import pytest
from lab.portfolio_budget import NativeBudget,BudgetError
from lab.portfolio_causal import SEMANTICS_SHA
from scripts import dispatch_portfolio_causal_probe as worker


@pytest.fixture
def harness(tmp_path,monkeypatch):
    events=[]
    binding=dict(input_sha256="a"*64,code_sha256="b"*64,source_sha256="c"*64,semantics_sha256=SEMANTICS_SHA)
    monkeypatch.setattr(worker,"RUNTIME_ROOT",tmp_path)
    monkeypatch.setattr(worker,"prepare",lambda source:binding)
    def assert_locked(label):
        with pytest.raises(BudgetError):
            with NativeBudget(tmp_path).locked(): pass
        events.append(label)
    monkeypatch.setattr(worker,"verify_anchor",lambda:assert_locked("anchor"))
    monkeypatch.setattr(worker,"verify_manifest",lambda b,s:assert_locked("verify"))
    monkeypatch.setattr(worker,"checkpoint_budget",lambda:assert_locked("checkpoint"))
    monkeypatch.setattr(worker.signal,"alarm",lambda seconds:events.append(("alarm",seconds)))
    def fake(root,source,b):
        assert_locked("fake_function")
        ledger=[json.loads(line) for line in (tmp_path/"calls.jsonl").read_text().splitlines()]
        assert ledger[-1]["event"]=="RESERVED"
        assert "checkpoint" in events
        assert (root/"bindings.json").exists()
        return {"status":"FAKE_TEST_ONLY"}
    monkeypatch.setattr(worker,"run_reserved",fake)
    return tmp_path,binding,events


def test_dispatch_lock_reservation_checkpoint_timeout_and_terminal(harness):
    root,binding,events=harness
    assert worker.dispatch(root,binding)["status"]=="SUCCEEDED"
    rows=[json.loads(s) for s in (root/"calls.jsonl").read_text().splitlines()]
    assert [r["event"] for r in rows]==["RESERVED","SUCCEEDED"]
    assert events.count("checkpoint")==2 and ("alarm",180) in events and ("alarm",0) in events
    assert events.index("checkpoint")<events.index("fake_function")
    assert events[-1]=="checkpoint"
    assert (root/"runs/synthetic-6/evidence.json").exists()
    before=(root/"calls.jsonl").read_bytes()
    with pytest.raises(BudgetError): worker.dispatch(root,binding)
    assert (root/"calls.jsonl").read_bytes()==before


@pytest.mark.parametrize("error",[TimeoutError("180s"),ValueError("failed assertion")])
def test_dispatch_failure_consumes_slot_and_records_terminal(harness,monkeypatch,error):
    root,binding,events=harness
    def fail(*args): raise error
    monkeypatch.setattr(worker,"run_reserved",fail)
    assert worker.dispatch(root,binding)["status"]=="FAILED"
    rows=[json.loads(s) for s in (root/"calls.jsonl").read_text().splitlines()]
    assert [r["event"] for r in rows]==["RESERVED","FAILED"]
    assert events.count("verify")==2 and events.count("checkpoint")==2


def test_postexecution_binding_change_fails_instead_of_success(harness,monkeypatch):
    root,binding,events=harness
    calls=[]
    def verify(*args):
        calls.append(1)
        if len(calls)==2: raise ValueError("code/input/source changed")
    monkeypatch.setattr(worker,"verify_manifest",verify)
    assert worker.dispatch(root,binding)["status"]=="FAILED"
    evidence=json.loads((root/"runs/synthetic-6/evidence.json").read_text())
    assert "post-execution" in evidence["reason"]


def test_existing_output_and_mismatched_manifest_do_not_reserve(harness):
    root,binding,events=harness
    with pytest.raises(BudgetError): worker.dispatch(root,{**binding,"input_sha256":"d"*64})
    (root/"runs/synthetic-6").mkdir(parents=True)
    with pytest.raises(BudgetError): worker.dispatch(root,binding)
    assert not (root/"calls.jsonl").exists()


def test_pre_native_checkpoint_failure_never_enters_function(harness,monkeypatch):
    root,binding,events=harness
    calls=[]
    def checkpoint():
        calls.append(1)
        if len(calls)==1: raise OSError("checkpoint unavailable")
    monkeypatch.setattr(worker,"checkpoint_budget",checkpoint)
    # Output setup has not happened; terminal still records the consumed slot,
    # then persistence failure is surfaced rather than creating replacement data.
    with pytest.raises(OSError): worker.dispatch(root,binding)
    assert "fake_function" not in events
    rows=[json.loads(s) for s in (root/"calls.jsonl").read_text().splitlines()]
    assert [r["event"] for r in rows]==["RESERVED","FAILED"]
    assert len(calls)==2


def test_v2_dispatch_selects_explicit_slot_and_semantics_without_native(harness,monkeypatch):
    from scripts import prepare_portfolio_causal_probe_v2 as v2
    from lab.portfolio_risk_v2 import V2_SHA
    root,binding,events=harness
    binding={**binding,'key':'synthetic/7','semantics_sha256':V2_SHA}
    monkeypatch.setattr(v2,'prepare',lambda source:binding)
    monkeypatch.setattr(v2,'verify_manifest',lambda *args:None)
    monkeypatch.setattr(v2,'run_reserved',lambda *args:{'status':'FAKE_V2_TEST_ONLY'})
    assert worker.dispatch(root,binding)['status']=='SUCCEEDED'
    rows=[json.loads(s) for s in (root/'calls.jsonl').read_text().splitlines()]
    assert rows[0]['key']=='synthetic/7' and rows[0]['semantics_sha256']==V2_SHA
