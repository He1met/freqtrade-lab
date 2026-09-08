import importlib.util
import json
from decimal import Decimal as D
from fractions import Fraction
from pathlib import Path
import time
import pytest
spec=importlib.util.spec_from_file_location('p145',Path(__file__).parents[1]/'scripts/issue145_prescreen.py')
p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)


def synthetic(end=None):
    end=end or p.SCORE+48
    b={s:{} for s in p.SYMS}
    for h in range(p.START,end):
        day=(h-p.START)//24
        for i,s in enumerate(p.SYMS):
            value=D(100)+D(day%3)*D(i+1)
            b[s][h]=dict(open=value,close=value,full=True)
    return b


def test_relative_direction_tie_and_no_future():
    daily=p.daily_closes(synthetic()); boundary=(p.SCORE-1)//24
    ratio=p.relative_at(daily,boundary)
    first,last=daily[boundary-29],daily[boundary-1]
    exact=Fraction(last[1])*Fraction(first[0])/(Fraction(first[1])*Fraction(last[0]))
    assert abs(ratio-D(exact.numerator)/D(exact.denominator))<D('1e-48')
    daily[boundary]=[D('1e30'),D('1e-30')]
    assert p.relative_at(daily,boundary)==ratio
    assert p.allocation('R',D(2))==[D('.1'),D('.3')]
    assert p.allocation('R',D('.5'))==[D('.3'),D('.1')]
    assert p.allocation('R',D(1))==[D('.2'),D('.2')]
    assert p.allocation('B',D(2))==[D('.3'),D('.1')]
    assert p.allocation('H',D('.5'))==[D('.1'),D('.3')]
    del daily[boundary-5]
    assert p.relative_at(daily,boundary) is None


def test_frozen_quantity_delay_base_fee_cash_and_independent_wallets():
    w=p.Wallet('R/base'); px={s:D(100) for s in p.SYMS}
    w.decision(0,D(1),px)
    assert w.weekly[1]=={s:D(2) for s in p.SYMS}
    w.execute(0,px); assert not w.trades
    changed={s:D(110) for s in p.SYMS}; w.execute(1,changed)
    assert all(w.q[s]==D(2)*(1-w.fee) for s in p.SYMS)
    assert w.cash==1000-4*110*(1+w.slip)
    assert w.nav(changed)+w.cost_loss==1000
    other=p.Wallet('E/base'); assert other.cash==1000 and all(q==0 for q in other.q.values())
    # Exact arithmetic independent Fraction reference for a buy and sell round trip.
    for s in p.SYMS: w.trade(2,'SELL',s,w.q[s],D(110),'fixture')
    f=Fraction('.001');s=Fraction('.0006')
    exact=Fraction(1000)-4*110*(1+s)+4*(1-f)*110*(1-s)*(1-f)
    assert abs(w.cash-D(exact.numerator)/D(exact.denominator))<D('1e-45')


def test_sell_first_cash_scale_and_halt():
    w=p.Wallet('E/stress');w.cash=D(0);w.q={p.SYMS[0]:D(10),p.SYMS[1]:D(0)}
    rec={};w.weekly=(1,{s:D(5) for s in p.SYMS},rec)
    w.execute(1,{s:D(100) for s in p.SYMS})
    assert [x['side'] for x in w.trades]==['SELL','BUY'] and w.cash==0
    assert rec['cash_scale']<1
    w.halt=True; w.weekly=(2,{s:D(10) for s in p.SYMS},{})
    before=dict(w.q);w.execute(2,{s:D(100) for s in p.SYMS});assert w.q==before


def test_risk_delay_latches_drift_and_gap_recovery():
    w=p.Wallet('R/base');w.cash=D(100);w.q={s:D(5) for s in p.SYMS};px={s:D(100) for s in p.SYMS}
    w.observe(0,px); assert w.pending and w.q[p.SYMS[0]]==5
    w.execute(1,px);assert w.q[p.SYMS[0]]==D('4.4')
    assert any('NOTIONAL_DRIFT' in r['events'] for r in w.risks)
    w.peak=D(2000);w.observe(1,px);assert w.half and w.halt and w.breach
    assert any('DD10_LATCH' in r['events'] for r in w.risks)
    w.observe(2,None); assert w.recover==0 and w.unknown[-1]['held']
    for t in [3,4,5]: w.observe(t,px)
    assert w.recover==3 and w.half and w.halt


def test_missing_week_no_makeup_and_terminal_not_trade():
    b=synthetic(); out,ev=p.analyze(b,end=p.SCORE+48)
    assert len(out['cells'])==8
    for name,c in out['cells'].items():
        assert sum(c['first_decision']['target_weights'])==D('.4')
        assert c['first_decision']['last_signal_close_known_utc']==p.stamp(p.SCORE-1)
        assert c['first_decision']['execution_due_utc']==p.stamp(p.SCORE)
        assert c['terminal_exit_is_trade'] is False and c['estimated_exit_cost']>0
        assert all(e['hour']==p.SCORE for e in ev[name]['trades'])
        assert c['mark_less_estimated_exit_cost']<c['mark_nav_net']
    # A missing execution open cancels the weekly order for all paths, no next-hour catch-up.
    del b[p.SYMS[0]][p.SCORE]
    out,ev=p.analyze(b,end=p.SCORE+48)
    assert all(not e['trades'] for e in ev.values())
    assert all(c['first_decision']['execution']=='CANCELLED_NO_MAKEUP' for c in out['cells'].values())


def test_cohort_stop_settlement_and_no_outside_open():
    b=synthetic()
    for s in p.SYMS:
        b[s][p.SCORE]['close']=D(1)
    out,ev=p.analyze(b,end=p.SCORE+2)
    assert out['cohort_trigger_close_known_utc']==p.stamp(p.SCORE+1) and out['admin_exit_last_open_utc']==p.stamp(p.SCORE+1)
    assert not out['completed_requested_window']
    assert all(e['trades'][-1]['reason']=='COHORT_ADMIN_EXIT' for e in ev.values())
    short,ev=p.analyze(b,end=p.SCORE+1)
    assert short['settlement_completed'] is False
    assert all(any(c['quantities'].values()) for c in short['cells'].values())
    assert all(c['terminal_exit_is_trade'] is False for c in short['cells'].values())


@pytest.mark.parametrize('timeout',[False,True])
def test_attempt_consumed(tmp_path,timeout):
    root=tmp_path/'once'
    def action(_):
        if timeout:time.sleep(.03)
        raise ValueError('synthetic')
    with pytest.raises((ValueError,TimeoutError)): p.once(root,action,.01 if timeout else 1)
    assert json.loads((root/'terminal.json').read_text())['status']=='FAILED'
    with pytest.raises(FileExistsError):p.once(root,lambda _:None)


def test_invalid_twenty_eight_days_does_not_compress_or_replay_week():
    b=synthetic();daily=p.daily_closes(b);boundary=(p.SCORE-1)//24
    b[p.SYMS[0]][(boundary-3)*24]['full']=False
    assert p.relative_at(p.daily_closes(b),boundary) is None
    w=p.Wallet('E/base');w.decision(0,None,{s:D(100) for s in p.SYMS})
    w.execute(1,{s:D(100) for s in p.SYMS});w.execute(2,{s:D(100) for s in p.SYMS})
    assert not w.trades and w.weeks[0]['execution']=='CANCELLED_INVALID_INPUT'


def test_source_scope_inventory_and_warmup_hash_only(tmp_path):
    warm=tmp_path/'warm';warm.write_text('not JSON')
    sources=[dict(path=str(warm),sha256=p.sha(warm),request={'interval':'1d'})];anomalies={}
    for s in p.SYMS:
        path=tmp_path/s
        # Outside permitted window has intentionally invalid OHLC and is not decoded into Decimal.
        rows=[[0,'invalid','invalid','invalid','invalid','0',3599999,'0',0,'0','0','0'],
              [3600000,'1','1','1','1','0',7199999,'0',0,'0','0','0'],
              [10800000,'1','1','1','1','0',10800100,'0',0,'0','0','0']]
        path.write_text(json.dumps(rows));sources.append(dict(path=str(path),sha256=p.sha(path),request=dict(symbol=s,interval='1h',startTime=0,endTime=14399999)))
        anomalies[s]=[dict(kind='MISSING',open_ms=7200000),dict(kind='SHORT',open_ms=10800000)]
    m=dict(sources=sources,start=1,end=4,anomalies=anomalies)
    assert list(p.load_sources(m)[p.SYMS[0]])==[1,3]
    m['anomalies'][p.SYMS[0]]=[]
    with pytest.raises(ValueError,match='inventory'):p.load_sources(m)


def test_joint_calendar_cancellation_and_distinct_eight_wallets():
    end=p.SCORE+24*9;b=synthetic(end)
    # First week has all dependencies, but following week's signal window includes a short candle.
    b[p.SYMS[1]][p.SCORE+24]['full']=False
    out,ev=p.analyze(b,end=end)
    assert len(out['cells'])==8
    for n,e in ev.items():
        assert e['weeks'][0]['execution']=='EXECUTED'
        assert e['weeks'][1]['execution']=='CANCELLED_INVALID_INPUT'
        assert e['unknown'][0]['held']
        assert len([t for t in e['trades'] if t['reason']=='WEEKLY'])==2
    assert out['cells']['B/base']['first_decision']['target_weights']==[D('.3'),D('.1')]
    assert out['cells']['H/base']['first_decision']['target_weights']==[D('.1'),D('.3')]
    assert out['cells']['E/base']['quantities']!=out['cells']['E/stress']['quantities']


def test_asymmetric_half_risk_reduces_without_buying():
    w=p.Wallet('R/base');w.weights=[D('.3'),D('.1')]
    w.cash=D(600);w.q={p.SYMS[0]:D(3),p.SYMS[1]:D(1)}
    w.peak=D(1200);px={s:D(100) for s in p.SYMS};w.observe(0,px)
    assert w.pending=={p.SYMS[0]:D('1.5'),p.SYMS[1]:D('.5')}
    assert w.q[p.SYMS[0]]==3
    w.execute(1,{p.SYMS[0]:D(90)})
    assert w.q[p.SYMS[0]]==D('1.5') and w.q[p.SYMS[1]]==1
    w.execute(2,{p.SYMS[1]:D(80)})
    assert w.q[p.SYMS[1]]==D('.5') and all(t['side']=='SELL' for t in w.trades)
    assert w.risks[0]['close_known_utc']==p.stamp(1)


def test_bad_source_terminal_is_blocked_and_consumed(tmp_path):
    def action(_): raise p.DataError('unregistered anomaly')
    with pytest.raises(p.DataError):p.once(tmp_path/'one',action)
    assert json.loads((tmp_path/'one'/'terminal.json').read_text())['verdict']=='BLOCKED_DATA'
    with pytest.raises(FileExistsError):p.once(tmp_path/'one',lambda _:None)
