from datetime import datetime,timezone,timedelta
from decimal import Decimal
import json
from pathlib import Path
import pytest
from lab.portfolio_causal import PAIRS
from lab.portfolio_causal_fixture import expand
from lab.portfolio_short import configuration,decision,account,funding_cash,reserve_additions,continuation_allowance,ContinuationBudget
from lab.portfolio_source import SourceError,digest


def test_real_daily_core_receives_all_modes_and_central_only():
    _,start,_,daily=expand()
    for mode in ('A-trend','A-reversal','B','C','half-risk-B'):
        d=decision(daily,start,'1000',configuration(mode,'base'))
        assert d.mode==mode
    with pytest.raises(SourceError):configuration('market-exposure','base')
    c=configuration('B','base');c['selection']['trend']=42
    with pytest.raises(SourceError):decision(daily,start,'1000',c)


def test_stress_reaches_account_equity_and_native_fee_configuration():
    at=datetime(2024,8,1,tzinfo=timezone.utc)
    orders=[dict(id='1',pair=PAIRS[0],side='buy',amount='1',price='100',filled_at=at)]
    marks={p:'100' for p in PAIRS}
    base=account(orders,at,marks,[],configuration('B','base'))
    stress=account(orders,at,marks,[],configuration('B','stress'))
    assert base['equity']-stress['equity']==Decimal('.12')
    assert configuration('B','stress')['native_fee']=='0.0012'


def event(at):
    return dict(pair=PAIRS[0],event_at=at,available_at=at,eligibility_resolved_at=at,
                eligibility_verified=True,associated_mark_verified=True,
                signed_quantity='2',rate='.001',associated_mark='100')


def test_funding_future_values_never_enter_prior_decision_and_due_pending_blocks():
    t=datetime(2024,8,1,tzinfo=timezone.utc);e=event(t)
    e['associated_mark']='garbage'
    assert funding_cash([e],t-timedelta(seconds=1))==0
    e['available_at']=t+timedelta(seconds=15)
    with pytest.raises(SourceError,match='unresolved'):funding_cash([e],t)
    e['associated_mark']='100';assert funding_cash([e],t+timedelta(seconds=15))==Decimal('-.2')
    e['signed_quantity']='-2';assert funding_cash([e],t+timedelta(seconds=15))==Decimal('.2')
    with pytest.raises(SourceError,match='duplicate'):funding_cash([e,e],t+timedelta(seconds=15))
    e['eligibility_verified']=False
    with pytest.raises(SourceError,match='eligibility'):funding_cash([e],t+timedelta(seconds=15))


def test_cost_reservation_keeps_post_cost_caps_and_blocks_old_breach():
    actual={p:'0' for p in PAIRS};target={p:'4' for p in PAIRS};prices={p:'100' for p in PAIRS};steps={p:'.001' for p in PAIRS}
    q=reserve_additions('1000',actual,target,prices,steps,configuration('B','stress'))
    assert all(v<4 for v in q.values())
    n=sum(v*100 for v in q.values());net=1000-n*Decimal('.0024')
    assert n<=Decimal('.8')*net and all(v*100<=Decimal('.4')*net for v in q.values())
    actual={p:'5' for p in PAIRS}
    with pytest.raises(SourceError,match='breach'):reserve_additions('1000',actual,actual,prices,steps,configuration('B','base'))


def test_continuation_preserves_parent_prefix_cumulative_budget_and_time(tmp_path):
    parent=dict(status='BLOCKED_DATA',attempts=[{'number':i+1} for i in range(37)],charged_bytes=7697705,root=str(tmp_path/'old'))
    raw=json.dumps(parent).encode();p=tmp_path/'acquisition-budget.json';p.write_bytes(raw)
    spec=dict(parent_budget_sha256=digest(raw),parent_seconds_charged=130,preparation_authorization='prepare')
    assert continuation_allowance(raw,spec)==dict(gets=85,total_bytes=59411159,seconds=1670)
    with pytest.raises(SourceError,match='activation'):ContinuationBudget(p,spec,'prepare')
    b=ContinuationBudget(p,spec,'specific-test-activation',now=lambda:200)
    assert b.state['attempts']==parent['attempts'] and b.remaining_time()==1670
    r=b.reserve('fundingRate',{})
    assert r['number']==38 and b.state['charged_bytes']==7697705+5242880
    assert p.read_bytes()==raw
    with pytest.raises(SourceError,match='already started'):ContinuationBudget(p,spec,'other-activation')
    spec['parent_seconds_charged']=36
    with pytest.raises(SourceError,match='refunded'):continuation_allowance(raw,spec)


def test_continuation_segment_stops_at_54_new_gets(tmp_path):
    parent=dict(status='BLOCKED_DATA',attempts=[{'number':i+1} for i in range(37)],charged_bytes=7697705,root=str(tmp_path/'old'))
    raw=json.dumps(parent).encode();p=tmp_path/'acquisition-budget.json';p.write_bytes(raw)
    spec=dict(parent_budget_sha256=digest(raw),parent_seconds_charged=130,preparation_authorization='prepare')
    b=ContinuationBudget(p,spec,'specific-test-activation',now=lambda:200)
    for _ in range(54):
        row=b.reserve('fundingRate',{});b.finish(row,size=1,status=200)
    assert len(b.state['attempts'])==91
    with pytest.raises(SourceError,match='GET budget'):b.reserve('fundingRate',{})
