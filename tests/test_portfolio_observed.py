from datetime import datetime,timedelta,timezone
from decimal import Decimal
from fractions import Fraction
from types import SimpleNamespace
from dataclasses import replace
import pytest
from lab.portfolio_causal import PAIRS,State,Episode,Entry
from lab.portfolio_causal_fixture import expand
from lab.portfolio_risk_v2 import RiskState
from lab.portfolio_short import configuration
from lab.portfolio_observed_source import ObservedView,load_view
from lab.portfolio_observed_money import EventAccount,event_cash
from lab.portfolio_observed_control import ObservedState,advance_observed
from lab.portfolio_source import SourceError


def view_fixture():
    _,start,hourly,daily=expand()
    by={p:{b.closed_at-timedelta(hours=1):b for b in hourly[p]} for p in PAIRS}
    return ObservedView(by,by,daily,[],'synthetic-test-only',start,start+timedelta(days=2))


def order(pair,t,side='buy',amount='1',price='100',id='o'):
    return dict(id=id,pair=pair,filled_at=t,side=side,amount=amount,price=price)


def event(pair,t,rate='.01'):
    return dict(pair=pair,time=t,nominal=t.replace(minute=0,second=0,microsecond=0),rate=rate,mark='100')


@pytest.mark.parametrize('delta',[0,1,15])
def test_hour_fill_then_fee_conservative_no_credit_no_future(delta):
    h=datetime(2024,8,1,tzinfo=timezone.utc);t=h+timedelta(milliseconds=delta)
    old=order(PAIRS[0],h-timedelta(hours=1),amount='2')
    close=order(PAIRS[0],h,side='sell',amount='2',id='c')
    e=event(PAIRS[0],t)
    flow,before,after=event_cash(e,[old,close]);assert (flow,before,after)==(Fraction(-2),2,0)
    e['rate']='-.01';assert event_cash(e,[old,close])[0]==0


def test_event_fee_risk_before_next_action_no_future_order_read():
    v=view_fixture();h=v.start;p=PAIRS[0]
    v.funding=[event(p,h+timedelta(milliseconds=1),rate='3')]
    book=EventAccount(v,'0','0');past=order(p,h-timedelta(hours=1),price='100')
    marks={p:'100' for p in PAIRS}
    first=book.observe([past],h,marks);assert first['funding']==0 and not book.halted
    future=order(p,h+timedelta(hours=2),price='not-readable',id='future')
    now=book.observe([past,future],h+timedelta(hours=1),marks)
    assert now['funding']==-300 and book.halted
    assert book.points[-2]['time']==h+timedelta(milliseconds=1)
    assert first['funding']==0  # prior open was not rewritten
    with pytest.raises(SourceError):book.observe([order(p,h+timedelta(seconds=3))],h+timedelta(hours=2),marks)


def args(v,t,eq='1000'):
    actual={p:Decimal(0) for p in PAIRS}
    rules={p:dict(step='.001',min_qty='.001',min_notional='1',max_qty='100000') for p in PAIRS}
    flat={p:t-timedelta(hours=5) for p in PAIRS}
    return dict(view=v,at=t,equity=Decimal(eq),free_cash=Decimal(eq),actual=actual,rules=rules,flat=flat,
                config=configuration('A-trend','base'),ledger=SimpleNamespace(peak=Fraction(1000),warning=False,halted=False))


def test_midnight_freeze_then_01_activation_never_increases_quantity():
    v=view_fixture();s=ObservedState(RiskState(State('A-trend',complete_checks=3)))
    s,out=advance_observed(s,**args(v,v.start))
    assert all(q==0 for q in out['target_quantities'].values())
    frozen={(e.pair,e.family):e.units for e in s.pending};assert frozen
    s,out=advance_observed(s,**args(v,v.start+timedelta(hours=1),'990'))
    assert out['activated']
    for a in out['activated']:
        assert a['activated_units']<=frozen[(a['pair'],a['family'])]
        assert a['started']==v.start+timedelta(hours=1)
    for ep in s.risk.episodes:assert ep.started.hour==1


def test_midnight_existing_expiry_and_C_update_not_delayed():
    v=view_fixture();t=v.start;e=Entry(PAIRS[0],'trend',1,Decimal(1),Decimal(1),None)
    ep=Episode(e,t-timedelta(days=42),Decimal(100),Decimal(1),t)
    st=ObservedState(RiskState(State('C',episodes=(ep,),complete_checks=3)))
    kw=args(v,t);kw['config']=configuration('C','base')
    st,out=advance_observed(st,**kw)
    assert any(x[:2]==(PAIRS[0],'trend') for x in out['family_exits'])
    assert dict(st.risk.multipliers)


def test_reserved_view_rejected_before_read():
    with pytest.raises(SourceError,match='sealed'):load_view(role='reserved-process-check',raw_root='/not/read')


def test_last_hour_exit_does_not_invent_flat_when_unexecutable():
    v=view_fixture();t=v.end-timedelta(hours=1)
    st=ObservedState(RiskState(State('A-trend',complete_checks=3)))
    kw=args(v,t);kw['actual'][PAIRS[0]]=Decimal('.0001')
    st,out=advance_observed(st,**kw)
    assert out['target_quantities'][PAIRS[0]]==Decimal('.0001')
    assert PAIRS[0] in out['blocked_final_exit']


def test_native_order_provenance_not_timestamp_only():
    from lab.portfolio_observed_adapter import audit_order_source
    v=view_fixture();p=PAIRS[0];t=v.start
    v.metadata={p:{'filters':[{'filterType':'PRICE_FILTER','tickSize':'.01'}]} for p in PAIRS}
    good=dict(order(p,t,price=str(v.hourly[p][t].open)),tag='observed_open',exit_reason=None)
    audit_order_source(v,[good])
    for changed in (dict(good,exit_reason='force_exit'),dict(good,exit_reason='stop_loss'),
                    dict(good,tag='manual'),dict(good,price=str(Decimal(good['price'])+1))):
        with pytest.raises(SourceError,match='MODEL_INVALID'):audit_order_source(v,[changed])


def test_callback_failure_stays_fatal_even_if_native_wrapper_swallows_exception():
    from lab.portfolio_observed_adapter import ObservedCallbacks
    callback=ObservedCallbacks();callback.config={'dry_run':False}
    with pytest.raises(SourceError):callback.bot_start()
    with pytest.raises(SourceError,match='sticky'):callback.raise_if_invalid()
    with pytest.raises(SourceError,match='sticky'):callback.custom_exit(None,None,None,None,None)


def test_event_groups_and_explicit_native_replacement_are_exact():
    v=view_fixture();h=v.start
    v.funding=[event(p,h) for p in PAIRS]
    orders=[order(p,h-timedelta(hours=1),id=p) for p in PAIRS]
    book=EventAccount(v,'0','0')
    book.observe(orders,h,{p:'100' for p in PAIRS})
    out=book.observe(orders,h+timedelta(hours=1),{p:'100' for p in PAIRS},native_funding='-2.1')
    assert out['funding']==-2 and out['native_funding_delta']==Fraction(1,10)
    assert len([p for p in book.points if p['kind']=='FUNDING_EVENT'])==1
    out=book.observe(orders,h+timedelta(hours=2),{p:'100' for p in PAIRS},native_funding='-2')
    assert out['funding']==-2 and out['native_funding_delta']==0


def test_direct_event_table_retains_original_milliseconds():
    from lab.portfolio_observed_source import funding_records
    v=view_fixture();h=v.start
    v.funding=[event(PAIRS[0],h+timedelta(milliseconds=d)) for d in (1,15)]
    rows=funding_records(v,PAIRS[0])
    assert [r['date'].microsecond for r in rows]==[1000,15000]
    assert all(r['date'] not in v.marks[PAIRS[0]] for r in rows)  # hourly inner join would lose both
    assert [r['open_mark'] for r in rows]==['100','100']


def test_control_precision_is_independent_of_callers_decimal_context():
    from decimal import localcontext
    v=view_fixture();st=ObservedState(RiskState(State('A-trend',complete_checks=3)))
    with localcontext() as c:
        c.prec=12
        low=advance_observed(st,**args(v,v.start))
    with localcontext() as c:
        c.prec=60
        high=advance_observed(st,**args(v,v.start))
    assert low==high


def test_real_source_structure_and_causal_prefix_only():
    """Approved real-source structural read; never emits a signal or economic score."""
    from lab.portfolio_observed_source import RAW_ROOT,START,END,RECEIPT_SHA
    from lab.portfolio_causal import daily_decision,BASE_SHA,SEMANTICS_SHA
    if not RAW_ROOT.exists():pytest.skip('frozen Git-external source unavailable')
    v=load_view()
    assert v.source_sha==RECEIPT_SHA
    assert all(len(v.hourly[p])==8784 and len(v.daily[p])==366 for p in PAIRS)
    assert len(v.funding)==552 and all(e['time']<END for e in v.funding)
    assert all(max(v.hourly[p])==END-timedelta(hours=1) for p in PAIRS)
    # Changing future values cannot alter the first decision; no matching performed.
    changed={p:[replace(b,close=float('nan'),high=float('nan')) if b.closed_at>START else b for b in v.daily[p]] for p in PAIRS}
    kw=dict(mode='B',selection={'trend':63,'reversal':'2'},base_protocol_sha256=BASE_SHA,semantics_sha256=SEMANTICS_SHA)
    assert daily_decision(v.daily,START,1000,**kw)==daily_decision(changed,START,1000,**kw)


def test_episode_evidence_has_stable_identity_and_never_claims_a_fill():
    from lab.portfolio_observed_adapter import episode_id,family_intents
    from lab.portfolio_observed_prepare import encoded
    v=view_fixture();t=v.start+timedelta(hours=1)
    e=Entry(PAIRS[0],'trend',1,Decimal('0.4'),Decimal('1'),None)
    ep=Episode(e,t,Decimal('100'),Decimal('99'),t+timedelta(days=42))
    r=RiskState(State('half-risk-B',episodes=(ep,)))
    intents=family_intents(r)
    assert intents[0]['id']==episode_id(ep) and intents[0]['risk_scale']==Decimal('.5')
    assert intents[0]['status']=='LOGICAL_INTENT_NOT_ACTUAL_FILL_OR_SAMPLE'
    assert b'0.4' in encoded({'episode':ep,'intents':intents})
