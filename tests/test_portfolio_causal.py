from dataclasses import replace
from datetime import datetime,timedelta,timezone
import math
from statistics import mean,stdev,median
import pytest

from lab.portfolio_causal import PriceBar,indicators,consumer_costs,CausalError

START=datetime(2019,1,1,tzinfo=timezone.utc)


def bars(count=290):
    return [PriceBar(START+timedelta(days=i),100+i*.1,101+i*.1,99+i*.1,100+i*.1) for i in range(count)]


def test_hand_calculated_atr_channel_and_strict_breakout():
    b=bars(70);s=indicators(b,b[-1].closed_at)
    assert s.atr20==2
    assert s.trend_direction==1
    assert s.exit_lower==b[-22].close and s.exit_upper==b[-2].close
    b[-1]=replace(b[-1],close=b[-2].close)
    assert indicators(b,b[-1].closed_at).trend_direction==0


def test_reversal_uses_prior_sixty_returns_not_current_shock():
    b=bars(70)
    b[-1]=replace(b[-1],high=150,close=150)
    r=[math.log(b[i].close/b[i-1].close) for i in range(1,len(b))]
    expected=math.log(b[-1].close/b[-4].close)/(stdev(r[-61:-1])*math.sqrt(3))
    s=indicators(b,b[-1].closed_at)
    assert s.reversal_z==expected and s.reversal_direction==-1
    assert s.reversal_target==mean(x.close for x in b[-5:])


def test_C_prior_window_excludes_current_volatility():
    b=bars();b[-1]=replace(b[-1],high=200,close=200)
    r=[None]+[math.log(b[i].close/b[i-1].close) for i in range(1,len(b))]
    i=len(b)-1
    expected=median(stdev(r[j-19:j+1]) for j in range(i-252,i))/stdev(r[-20:])
    assert indicators(b,b[-1].closed_at).raw_multiplier==expected


def test_future_prices_cannot_change_prefix_even_when_future_values_invalid():
    b=bars();at=b[275].closed_at
    expected=indicators(b[:276],at)
    altered=b[:276]+[replace(x,open=-1,high=float('nan'),low=0,close=1e10) for x in b[276:]]
    assert indicators(altered,at)==expected


def test_zero_vol_and_insufficient_warmup_remain_unknown():
    b=[replace(x,open=100,high=100,low=100,close=100) for x in bars()]
    s=indicators(b,b[-1].closed_at)
    assert s.reversal_z is s.raw_multiplier is None
    assert s.reversal_direction==0
    assert indicators(b[:20],b[19].closed_at).atr20 is None


@pytest.mark.parametrize('mutation',['gap','duplicate','nan','wrong_ohlc','not_utc','boundary'])
def test_bad_closed_data_rejected(mutation):
    b=bars(70)
    if mutation=='gap': del b[40]
    elif mutation=='duplicate': b[40]=b[39]
    elif mutation=='nan': b[40]=replace(b[40],close=float('nan'))
    elif mutation=='wrong_ohlc': b[40]=replace(b[40],low=999)
    elif mutation=='not_utc': b[40]=replace(b[40],closed_at=b[40].closed_at.replace(tzinfo=None))
    elif mutation=='boundary': b[40]=replace(b[40],closed_at=b[40].closed_at+timedelta(hours=1))
    with pytest.raises(CausalError): indicators(b,b[-1].closed_at)


def test_costs_flow_without_double_funding_or_higher_fee_downgrade():
    base=consumer_costs();stress=consumer_costs(stress=True)
    assert base['native_fee_each_side']==base['audit_slippage_each_side']=='0.0006'
    assert stress['native_fee_each_side']==stress['audit_slippage_each_side']=='0.0012'
    assert stress['funding']==base['funding']
    assert base['native_inclusive_endpoints_are_settlement_authority'] is False
    assert base['economic_result'] is None
    with pytest.raises(CausalError):consumer_costs(known_taker='0.0007')

from lab.portfolio_causal import (BASE_SHA, SEMANTICS_SHA, PAIRS, State, Entry, Episode,
                                 Decision, advance, daily_decision, verify_binding)
from decimal import Decimal as D
from dataclasses import replace

BIND = dict(base_protocol_sha256=BASE_SHA, semantics_sha256=SEMANTICS_SHA)
P,Q = PAIRS
T = datetime(2020,1,1,tzinfo=timezone.utc)


def transition(state, at=T, **overrides):
    args=dict(at=at, opens={p:100 for p in PAIRS},
              completed={p:PriceBar(at,100,101,99,100) for p in PAIRS},
              actual_quantities={p:0 for p in PAIRS}, equity=1000, free_cash=1000,
              rules={p:dict(step="0.001",min_qty="0.001",min_notional="0",max_qty="100") for p in PAIRS},
              flat_confirmed_at={p:at-timedelta(hours=1) for p in PAIRS}, **BIND)
    args.update(overrides)
    return advance(state,**args)


def episode(family, direction, *, units="2", stop=None):
    e=Entry(P,family,direction,D(units),D("10"),D("90") if direction<0 else D("110"))
    return Episode(e,T-timedelta(hours=2),D("100"),D(stop or ("90" if direction>0 else "110")),T+timedelta(days=5))


def test_dual_binding_and_daily_frozen_quantity():
    with pytest.raises(CausalError): verify_binding(BASE_SHA,None)
    history={p:bars(290) for p in PAIRS}
    at=history[P][-1].closed_at
    d=daily_decision(history,at,1000,mode="B",selection={"trend":63,"reversal":None},**BIND)
    assert len(d.entries)==2 and all(e.units==D(5)/D(6) for e in d.entries)
    assert all(e.family=="trend" for e in d.entries)
    a=daily_decision(history,at,1000,mode="A-trend",selection={"trend":63,"reversal":None},**BIND)
    assert a.entries[0].units==d.entries[0].units*2
    cash=daily_decision(history,at,1000,mode="B",selection={"trend":None,"reversal":None},**BIND)
    assert not cash.entries
    with pytest.raises(CausalError): daily_decision(history,at+timedelta(days=1),1000,mode="B",selection={"trend":63,"reversal":None},**BIND)


def test_net_zero_retains_episodes_then_short_stop_increases_long():
    state=State("B",episodes=(episode("trend",1),episode("reversal",-1)))
    state,out=transition(state)
    assert out["target_quantities"][P]==0 and len(state.episodes)==2
    at=T+timedelta(hours=1)
    state,out=transition(state,at,completed={P:PriceBar(at,100,111,99,100),Q:PriceBar(at,100,101,99,100)})
    assert out["target_quantities"][P]==2 and len(state.episodes)==1
    assert out["actual_quantities"][P]==0 and out["economic_result"] is None
    assert dict(state.cooldowns)[(P,"reversal")]==T+timedelta(days=2)


def test_global_halt_wins_over_short_exit_and_never_restarts():
    state=State("B",episodes=(episode("trend",1),episode("reversal",-1)))
    state,out=transition(state,opens={P:112,Q:100},equity=840)
    assert state.halted and out["target_quantities"][P]==0
    state,out=transition(state,T+timedelta(hours=1),equity=1100)
    assert state.halted and state.peak==1100 and out["target_quantities"][P]==0


def test_gap_and_simultaneous_stops_no_fills():
    state=State("B",episodes=(episode("trend",1),episode("reversal",-1)))
    nxt,out=transition(state,opens={P:85,Q:100})
    assert len(nxt.episodes)==1 and out["target_quantities"][P]==-2
    nxt,out=transition(state,completed={P:PriceBar(T,100,115,85,100),Q:PriceBar(T,100,101,99,100)})
    assert not nxt.episodes and len(out["family_exits"])==2


def test_cash_caps_half_control_warning_and_data_recovery():
    state=State("B",episodes=(episode("trend",1,units="20"),))
    _,out=transition(state,free_cash=100)
    assert out["target_quantities"][P]==D("0.998")
    _,out=transition(state)
    assert out["target_quantities"][P]==4
    small=State("half-risk-B",episodes=(episode("trend",1),))
    _,out=transition(small)
    assert out["target_quantities"][P]==1
    nxt,out=transition(small,equity=900)
    assert nxt.warning and out["target_quantities"][P]==D("0.5")
    nxt,out=transition(state,data_complete=False)
    assert out["target_quantities"][P]==0
    for hour in (1,2,3):
        nxt,out=transition(nxt,T+timedelta(hours=hour))
        assert bool(out["target_quantities"][P])==(hour==3)


def test_flip_requires_real_flat_receipt_and_min_order_does_not_inflate():
    state=State("B",episodes=(episode("trend",1),))
    _,out=transition(state,actual_quantities={P:-1,Q:0})
    assert out["target_quantities"][P]==0 and out["actual_quantities"][P]==-1
    _,out=transition(state,flat_confirmed_at={P:T,Q:T})
    assert out["target_quantities"][P]==0
    state=State("B",episodes=(episode("trend",1,units="0.0001"),))
    _,out=transition(state)
    assert out["target_quantities"][P]==0


def test_C_recovery_and_invalid_history_no_imputation():
    snap=indicators(bars(),bars()[-1].closed_at)
    state=State("C",episodes=(episode("trend",1),),multipliers=((P,D("0.2")),(Q,D("0.2"))))
    d=Decision(T,"C",tuple((p,replace(snap,closed_at=T,raw_multiplier=.8)) for p in PAIRS),(),BASE_SHA,SEMANTICS_SHA)
    state,out=transition(state,decision=d)
    assert dict(state.multipliers)[P]==D("0.3") and out["target_quantities"][P]==D("0.6")
    at=T+timedelta(days=1)
    d=replace(d,at=at,snapshots=tuple((p,replace(snap,closed_at=at,raw_multiplier=None)) for p in PAIRS))
    state,out=transition(state,at,decision=d)
    assert dict(state.multipliers)[P]==0 and out["target_quantities"][P]==0


def test_entry_open_only_reference_not_quantity_and_expiry():
    e=Entry(P,"trend",1,D("2"),D("10"),None)
    snap=replace(indicators(bars(),bars()[-1].closed_at),closed_at=T)
    d=Decision(T,"B",tuple((p,snap) for p in PAIRS),(e,),BASE_SHA,SEMANTICS_SHA)
    low,out=transition(State("B"),decision=d)
    high,_=transition(State("B"),decision=d,opens={P:120,Q:100})
    assert low.episodes[0].entry.units==high.episodes[0].entry.units==2
    assert high.episodes[0].stop-low.episodes[0].stop==20
    state,out=transition(low,T+timedelta(days=42))
    assert not state.episodes and out["family_exits"][0][2]=="expiry"
    with pytest.raises(CausalError): transition(low,T,decision=d)


def test_daily_exit_precedes_entry_and_stop_cooldown():
    snap=replace(indicators(bars(),bars()[-1].closed_at),closed_at=T,close=120)
    e=episode("reversal",1).entry
    d=Decision(T,"B",tuple((p,snap) for p in PAIRS),(e,),BASE_SHA,SEMANTICS_SHA)
    state,out=transition(State("B",episodes=(episode("reversal",1),)),decision=d)
    assert not state.episodes and out["family_exits"][0][2]=="signal"
    # Stops at midnight consume the whole following day, even if a fresh
    # daily signal would otherwise request an entry on this boundary.
    active=episode("trend",1,stop="100")
    d=replace(d,entries=(replace(active.entry,target=None),))
    state,out=transition(State("B",episodes=(active,)),decision=d)
    assert not state.episodes and dict(state.cooldowns)[(P,"trend")]==T+timedelta(days=1)


def test_halt_dust_is_explicit_unexecuted_and_stress_cash_reserve():
    state=State("B",halted=True)
    _,out=transition(state,actual_quantities={P:D("0.0001"),Q:0})
    assert out["risk_target_quantities"][P]==0
    assert out["target_quantities"][P]==D("0.0001")
    assert out["unexecutable_reductions"]==(P,)
    state=State("B",episodes=(episode("trend",1),))
    _,out=transition(state,free_cash=100,stress=True)
    assert out["target_quantities"][P]==D("0.997")
    assert out["costs"]["audit_slippage_each_side"]=="0.0012"


def test_lifecycle_future_tail_invariance_and_failed_transition_immutable():
    history={p:bars(290) for p in PAIRS}
    at=history[P][-2].closed_at
    d=daily_decision(history,at,1000,mode="B",selection={"trend":63,"reversal":"2"},**BIND)
    changed={p:history[p][:-1]+[replace(history[p][-1],close=float("nan"))] for p in PAIRS}
    other=daily_decision(changed,at,1000,mode="B",selection={"trend":63,"reversal":"2"},**BIND)
    assert d==other
    state=State("B")
    assert transition(state,at,decision=d)==transition(state,at,decision=other)
    with pytest.raises(CausalError): transition(state,at,decision=replace(d,semantics_sha256="bad"))
    assert state==State("B")
