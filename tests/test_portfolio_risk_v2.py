from dataclasses import replace
from datetime import datetime,timedelta,timezone
from decimal import Decimal as D
import pytest
from lab.portfolio_causal import State,Entry,Episode,PriceBar,BASE_SHA,PAIRS,Decision
from lab.portfolio_risk_v2 import RiskState,RiskDecision,V2_SHA,advance_v2
from lab.portfolio_budget import NativeBudget,BudgetError
T=datetime(2020,1,1,1,tzinfo=timezone.utc);P,Q=PAIRS


def episode(pair=P):
    return Episode(Entry(pair,'trend',1,D(8),D(10),None),T-timedelta(hours=1),D(100),D(90),T+timedelta(days=42))


def step(state,at=T,**overrides):
    args=dict(at=at,opens={p:100 for p in PAIRS},completed={p:PriceBar(at,100,101,99,100) for p in PAIRS},
              actual_quantities={P:D('4.005'),Q:0},equity=1000,free_cash=500,
              flat_confirmed_at={Q:T-timedelta(hours=2)},
              rules={p:dict(step='.001',min_qty='.001',min_notional='50',max_qty='120') for p in PAIRS})
    args.update(overrides)
    return advance_v2(state,base_protocol_sha256=BASE_SHA,semantics_sha256=V2_SHA,**args)


def test_hard_small_reduction_full_exit_and_no_fictitious_flat():
    nxt,out=step(RiskState(State('B',episodes=(episode(),))))
    assert out['target_quantities'][P]==0 and out['pending_actual_flat']==(P,)
    assert len(nxt.episodes)==1 and not nxt.paused_until
    assert out['v1_unexecutable_reductions']==(P,)
    assert not out['unexecutable_reductions']  # pending full exit still requires fill audit
    nxt,out=step(nxt,T+timedelta(hours=1),actual_quantities={P:0,Q:0},flat_confirmed_at={P:T,Q:T})
    assert dict(nxt.paused_until)[P]==T.replace(hour=0)+timedelta(days=1)
    assert out['target_quantities'][P]==0 and len(nxt.episodes)==1


def test_floor_legal_but_still_above_cap_uses_same_branch():
    nxt,out=step(RiskState(State('B',episodes=(episode(),))),equity='999.9',
                 rules={p:dict(step='.001',min_qty='.001',min_notional='0',max_qty='120') for p in PAIRS})
    assert out['target_quantities'][P]==0 and out['pending_actual_flat']==(P,)


def test_illegal_full_exit_keeps_actual_and_blocks_other_asset_addition():
    nxt,out=step(RiskState(State('B',episodes=(episode(),episode(Q)))),
                 rules={p:dict(step='.001',min_qty='.001',min_notional='500',max_qty='120') for p in PAIRS})
    assert out['target_quantities'][P]==D('4.005') and out['target_quantities'][Q]==0
    assert out['blocked_assets']==(P,) and out['actual_quantities'][P]==D('4.005')


def test_normal_adjustment_below_caps_does_not_full_close():
    nxt,out=step(RiskState(State('B',episodes=(replace(episode(),entry=replace(episode().entry,units=D(3))),))),
                 actual_quantities={P:D('3.001'),Q:0})
    assert out['target_quantities'][P]==D('3.001') and not nxt.pending_flat


def test_recent_cycle_flat_and_strict_next_midnight():
    state=RiskState(State('B',episodes=(episode(),)),pending_flat=((P,T),))
    nxt,out=step(state,T+timedelta(hours=1),actual_quantities={P:0,Q:0},flat_confirmed_at={P:T-timedelta(hours=1)})
    assert nxt.pending_flat and not nxt.paused_until
    midnight=T.replace(hour=0)+timedelta(days=1)
    nxt,out=step(state,midnight,actual_quantities={P:0,Q:0},flat_confirmed_at={P:midnight})
    assert dict(nxt.paused_until)[P]==midnight+timedelta(days=1)


def test_v2_slot_explicit_and_old_binding_history_remains_readable(tmp_path):
    from lab.portfolio_causal import SEMANTICS_SHA
    args=dict(input_sha256='a'*64,code_sha256='b'*64,source_sha256='c'*64)
    with NativeBudget(tmp_path).locked() as b:
        b.reserve('synthetic/6',**args,semantics_sha256=SEMANTICS_SHA);b.finish('synthetic/6','FAILED','d'*64)
        with pytest.raises(BudgetError):b.reserve('synthetic/7',**args,semantics_sha256=SEMANTICS_SHA)
        b.reserve('synthetic/7',**args,semantics_sha256=V2_SHA)
    with NativeBudget(tmp_path).locked() as b:assert len(b.events)==3


def test_paused_asset_only_resumes_at_fresh_daily_decision():
    from lab.portfolio_causal_fixture_v2 import expand
    from lab.portfolio_risk_v2 import decision_v2
    spec,start,hourly,daily=expand();boundary=start+timedelta(days=1)
    ep=replace(episode(),started=start,expires=start+timedelta(days=42))
    state=RiskState(State('B',episodes=(ep,)),paused_until=((P,boundary),))
    nxt,out=step(state,boundary,actual_quantities={p:0 for p in PAIRS},flat_confirmed_at={p:start for p in PAIRS})
    assert out['target_quantities'][P]==0 and nxt.paused_until
    decision=decision_v2(daily,boundary,1000,mode='B',selection=spec['selection'],base_protocol_sha256=BASE_SHA,semantics_sha256=V2_SHA)
    nxt,out=step(state,boundary,actual_quantities={p:0 for p in PAIRS},flat_confirmed_at={p:start for p in PAIRS},decision=decision)
    assert not nxt.paused_until and out['target_quantities'][P]>0


def test_v2_frozen_input_has_real_opposing_family_signals_and_unchanged_mark_shock():
    from lab.portfolio_causal_fixture_v2 import expand
    from lab.portfolio_risk_v2 import decision_v2
    spec,start,hourly,daily=expand()
    d=decision_v2(daily,start,1000,mode='B',selection=spec['selection'],base_protocol_sha256=BASE_SHA,semantics_sha256=V2_SHA)
    assert len(d.inner.entries)==4 and {e.direction for e in d.inner.entries}=={-1,1}
    assert spec['mark_factors_after_hours']==[[97,0.5]]


def test_new_audit_rejects_target_zero_without_actual_full_fill():
    from lab.portfolio_causal_audit_v2 import audit_v2
    start=T.replace(hour=0)
    trace=[dict(time=start.isoformat(),hard_cap_fallback=[]),
           dict(time=T.isoformat(),inventory={p:'4' for p in PAIRS},hard_cap_fallback=[dict(event='FULL_REDUCE_ONLY_INTENT',pair=P)]),
           dict(time=(T+timedelta(hours=1)).isoformat(),hard_cap_fallback=[dict(event='ACTUAL_FLAT_CONFIRMED',pair=P,receipt=T.isoformat(),pause_until=(start+timedelta(days=1)).isoformat())]),
           dict(time=(start+timedelta(days=1)).isoformat(),hard_cap_fallback=[dict(event='RESUME_AT_FRESH_DAILY_BOUNDARY',pair=P)])]
    trades=[dict(pair=p,leverage=1,fee_open=.0006,fee_close=.0006,orders=[dict(ft_order_side='buy',amount=4,safe_price=100,order_filled_timestamp=int(start.timestamp()*1000),ft_is_entry=True)]) for p in PAIRS]
    with pytest.raises(ValueError,match='not filled'):
        audit_v2({'trades':trades},trace,start)


def test_new_manifest_covers_parser_risk_and_native_adapter():
    from scripts.prepare_portfolio_causal_probe_v2 import CODE_FILES
    assert {'lab/portfolio_native_export.py','lab/portfolio_risk_v2.py','lab/portfolio_causal_strategy_v2.py',
            'lab/portfolio_causal_audit_v2.py','scripts/dispatch_portfolio_causal_probe.py'}.issubset(CODE_FILES)
