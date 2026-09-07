import hashlib
import json
import pytest
from lab.portfolio_budget import NativeBudget, BudgetError, verify_checkpoint


def reserve(b, key="synthetic/1", **kwargs):
    return b.reserve(key, input_sha256=kwargs.pop("input_sha256", "a"*64),
                     code_sha256="b"*64, source_sha256="c"*64, **kwargs)


def test_budget_survives_new_object_and_output_directory_change(tmp_path):
    with NativeBudget(tmp_path).locked() as b:
        reserve(b); b.finish("synthetic/1", "SUCCEEDED", "d"*64)
    before = (tmp_path/"calls.jsonl").read_bytes()
    with NativeBudget(tmp_path).locked() as b:
        with pytest.raises(BudgetError): reserve(b)
    assert (tmp_path/"calls.jsonl").read_bytes() == before


def test_lock_prevents_simultaneous_worker(tmp_path):
    with NativeBudget(tmp_path).locked():
        with pytest.raises(BudgetError):
            with NativeBudget(tmp_path).locked(): pass


def test_crash_consumes_slot_and_requires_recorded_interruption(tmp_path):
    with NativeBudget(tmp_path).locked() as b: reserve(b)
    with NativeBudget(tmp_path).locked() as b:
        with pytest.raises(BudgetError): reserve(b, "synthetic/2")
        b.finish("synthetic/1", "INTERRUPTED", "e"*64)
        reserve(b, "retry/1", retry_of="synthetic/1")
        b.finish("retry/1", "SUCCEEDED", "f"*64)
    with NativeBudget(tmp_path).locked() as b:
        assert len([r for r in b.events if r["event"] == "RESERVED"]) == 2


def test_bad_retry_or_market_key_has_no_mutation(tmp_path):
    with NativeBudget(tmp_path).locked() as b:
        for key in ("fold-1/train/trend-42", "synthetic/9", "retry/5"):
            with pytest.raises(BudgetError): reserve(b, key)
        reserve(b); b.finish("synthetic/1", "FAILED", "d"*64)
        before = b.path.read_bytes()
        with pytest.raises(BudgetError): reserve(b, "retry/1", retry_of="synthetic/1", input_sha256="e"*64)
        assert b.path.read_bytes() == before
        reserve(b, "retry/1", retry_of="synthetic/1"); b.finish("retry/1", "FAILED", "d"*64)
        with pytest.raises(BudgetError): reserve(b, "retry/2", retry_of="synthetic/1")
        reserve(b, "retry/2", retry_of="retry/1")


@pytest.mark.parametrize("corruption", [b"{", b"{}\n", b"\n"])
def test_corrupt_ledger_never_resets(tmp_path, corruption):
    (tmp_path/"calls.jsonl").write_bytes(corruption)
    with pytest.raises(BudgetError):
        with NativeBudget(tmp_path).locked(): pass
    assert (tmp_path/"calls.jsonl").read_bytes() == corruption


def test_terminal_cannot_be_replaced(tmp_path):
    with NativeBudget(tmp_path).locked() as b:
        reserve(b); b.finish("synthetic/1", "FAILED", "d"*64)
        with pytest.raises(BudgetError): b.finish("synthetic/1", "SUCCEEDED", "e"*64)


def test_postprocessing_recovery_preserves_failed_terminal_and_consumption(tmp_path):
    with NativeBudget(tmp_path).locked() as b:
        reserve(b); b.finish("synthetic/1", "FAILED", "d"*64)
        b.recover_audit("synthetic/1", "e"*64)
        with pytest.raises(BudgetError): b.recover_audit("synthetic/1", "e"*64)
    with NativeBudget(tmp_path).locked() as b:
        assert [r["event"] for r in b.events] == ["RESERVED","FAILED","AUDIT_RECOVERED"]
        with pytest.raises(BudgetError): reserve(b)
        with pytest.raises(BudgetError): reserve(b,"retry/1",retry_of="synthetic/1")


def test_global_checkpoint_rejects_reset_truncation_and_rewrite():
    raw=b'old-reservation\n'
    cp={"bytes":len(raw),"sha256":hashlib.sha256(raw).hexdigest()}
    verify_checkpoint(raw+b'new-append\n',cp)
    for changed in (b'',raw[:-1],b'new-reservation\n'):
        with pytest.raises(BudgetError): verify_checkpoint(changed,cp)
