from datetime import datetime,timezone,timedelta
from decimal import Decimal as D
import pytest
from lab.portfolio_causal import PAIRS,BASE_SHA,SEMANTICS_SHA,State,daily_decision,advance
from lab.portfolio_causal_fixture import expand,known_hour,input_sha
from lab.portfolio_causal_account import account_snapshot
from lab.portfolio_budget import NativeBudget,BudgetError
from lab.portfolio_causal_audit import audit_causal

T=datetime(2020,1,1,tzinfo=timezone.utc)
P=PAIRS[0]


def order(index,side,amount,price,hour):
    return dict(id=str(index),pair=P,side=side,amount=amount,price=price,filled_at=T+timedelta(hours=hour))


def test_latest_cycle_flat_receipt_and_costs():
    orders=[order(1,"buy",2,100,0),order(2,"sell",2,110,1),order(3,"sell",1,105,2)]
    snapshot=account_snapshot(orders,at=T+timedelta(hours=2),marks={P:100},funding=0)
    assert P not in snapshot["flat_confirmed_at"]
    assert snapshot["actual_quantities"][P]==-1
    assert snapshot["equity"]==D("1024.3700")
    orders.append(order(4,"buy",1,100,3))
    snapshot=account_snapshot(orders,at=T+timedelta(hours=3),marks={P:100},funding=0)
    assert snapshot["flat_confirmed_at"][P]==T+timedelta(hours=3)
    assert snapshot["slippage_paid"]==D("0.3750")
    assert snapshot["equity"]==D("1024.2500")
    with pytest.raises(ValueError): account_snapshot(orders+[orders[0]],at=T+timedelta(hours=4),marks={P:100},funding=0)


def test_future_fills_not_visible_and_missing_mark_not_zero():
    orders=[order(1,"buy",1,100,1)]
    snapshot=account_snapshot(orders,at=T,marks={},funding=0)
    assert snapshot["actual_order_count"]==0
    with pytest.raises(ValueError): account_snapshot(orders,at=T+timedelta(hours=1),marks={},funding=0)


def test_fixed_input_real_indicators_and_hourly_stops_without_fill_simulation():
    spec,start,hourly,daily=expand()
    state=State("B")
    events={}
    for h in range(6):
        at=start+timedelta(hours=h)
        completed,opens=known_hour(hourly,at)
        decision=daily_decision(daily,at,1000,mode="B",selection=spec["selection"],base_protocol_sha256=BASE_SHA,semantics_sha256=SEMANTICS_SHA) if h==0 else None
        if decision:
            assert len(decision.entries)==4
            assert {e.direction for e in decision.entries}=={-1,1}
        state,out=advance(state,at=at,opens=opens,completed=completed,actual_quantities={p:0 for p in PAIRS},
            equity=1000,free_cash=1000,rules={p:dict(step=".001",min_qty=".001",min_notional="20",max_qty="2000") for p in PAIRS},
            flat_confirmed_at={p:start-timedelta(hours=1) for p in PAIRS},decision=decision,
            base_protocol_sha256=BASE_SHA,semantics_sha256=SEMANTICS_SHA)
        events[h]=out["family_exits"]
        assert out["actual_quantities"]=={p:0 for p in PAIRS}
    assert all(e[1:]==("reversal","stop") for e in events[2]) and len(events[2])==2
    assert all(e[1:]==("trend","stop") for e in events[5]) and len(events[5])==2
    assert len(input_sha())==64


def test_semantics_budget_append_preserves_legacy_and_retry(tmp_path):
    args=dict(input_sha256="a"*64,code_sha256="b"*64,source_sha256="c"*64)
    with NativeBudget(tmp_path).locked() as b:
        b.reserve("synthetic/1",**args);b.finish("synthetic/1","SUCCEEDED","d"*64)
        prefix=b.path.read_bytes()
        with pytest.raises(BudgetError): b.reserve("synthetic/6",**args)
        assert b.path.read_bytes()==prefix
        b.reserve("synthetic/6",**args,semantics_sha256=SEMANTICS_SHA)
        b.finish("synthetic/6","FAILED","e"*64)
        with pytest.raises(BudgetError): b.reserve("retry/2",**args,retry_of="synthetic/6")
        b.reserve("retry/2",**args,retry_of="synthetic/6",semantics_sha256=SEMANTICS_SHA)
        assert b.path.read_bytes().startswith(prefix)
    with NativeBudget(tmp_path).locked() as b: assert len([e for e in b.events if e["event"]=="RESERVED"])==3


def test_audit_refuses_absent_or_failed_evidence():
    for trace in ([],[{"fatal_error":"ValueError"}]):
        with pytest.raises(ValueError): audit_causal({},trace,T)


def test_execution_function_cannot_run_without_durable_reservation(tmp_path,monkeypatch):
    import hashlib
    from scripts import prepare_portfolio_causal_probe as script
    from lab.portfolio_budget import canonical
    monkeypatch.setattr(script,"RUNTIME_ROOT",tmp_path)
    monkeypatch.setattr(script,"verify_anchor",lambda:None)
    monkeypatch.setattr(script,"verify_manifest",lambda binding,source:None)
    binding=dict(base_protocol_sha256=BASE_SHA,semantics_sha256=SEMANTICS_SHA,
                 code={},code_sha256=hashlib.sha256(canonical({})).hexdigest())
    with pytest.raises(BudgetError,match="no sole durable"):
        script.run_reserved(tmp_path/"runs/synthetic-6",tmp_path,binding)
    assert not list(tmp_path.iterdir())


def test_halt_requires_real_liquidation_at_first_open_not_final_forceexit():
    from lab.portfolio_causal_audit import audit_halt_liquidation,HaltLiquidationError
    stamp=int(T.timestamp()*1000)
    trace=[dict(time=T.isoformat(),halted=True,inventory={P:"2",PAIRS[1]:"0"}),
           dict(time=(T+timedelta(hours=1)).isoformat(),halted=True,inventory={p:"0" for p in PAIRS})]
    fills=[dict(pair=P,side="buy",amount=2,time=stamp-3600000,is_entry=True),
           dict(pair=P,side="sell",amount=2,time=stamp,is_entry=False)]
    receipt=audit_halt_liquidation(fills,trace)
    assert receipt["residual_at_earliest_time"][P]=="0"
    # Final inventory is still zero, but an end-of-run force exit is too late.
    delayed=[fills[0],{**fills[1],"time":stamp+24*3600000}]
    assert sum(f["amount"]*(1 if f["side"]=="buy" else -1) for f in delayed)==0
    with pytest.raises(HaltLiquidationError,match="delayed") as exc:
        audit_halt_liquidation(delayed,trace)
    assert exc.value.receipt["residual_at_earliest_time"][P]=="2"
    with pytest.raises(HaltLiquidationError,match="incomplete"):
        audit_halt_liquidation([fills[0],{**fills[1],"amount":1}],trace)
    trace[1]["inventory"][P]="1"
    with pytest.raises(HaltLiquidationError,match="remains"):
        audit_halt_liquidation(fills,trace)


def test_manifest_rejects_omitted_or_extra_paths_before_native(tmp_path):
    import hashlib
    from scripts.prepare_portfolio_causal_probe import verify_manifest,CODE_FILES
    from lab.portfolio_budget import canonical
    for code in ({},{**{p:"a"*64 for p in CODE_FILES},"unreviewed.py":"a"*64}):
        binding=dict(base_protocol_sha256=BASE_SHA,semantics_sha256=SEMANTICS_SHA,code=code,
                     code_sha256=hashlib.sha256(canonical(code)).hexdigest())
        with pytest.raises(BudgetError,match="exactly"):
            verify_manifest(binding,tmp_path)
