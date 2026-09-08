import importlib.util
import json
from decimal import Decimal as D
from fractions import Fraction
from pathlib import Path
import time
import pytest
spec=importlib.util.spec_from_file_location('p143',Path(__file__).parents[1]/'scripts/issue143_prescreen.py')
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


def test_sigma_covariance_and_no_future():
    daily=p.daily_closes(synthetic()); boundary=(p.SCORE-1)//24
    sig=p.sigma_at(daily,boundary)
    rs=[[daily[d][i]/daily[d-1][i]-1 for i in range(2)] for d in range(boundary-20,boundary)]
    means=[sum((r[i] for r in rs),D(0))/20 for i in range(2)]
    cov=[[sum(((r[i]-means[i])*(r[j]-means[j]) for r in rs),D(0))/19 for j in range(2)] for i in range(2)]
    assert abs(sig**2-sum((cov[i][j]/4 for i in range(2) for j in range(2)),D(0)))<D('1e-48')
    daily[boundary]=[D('1e30'),D('1e-30')]
    assert p.sigma_at(daily,boundary)==sig
    del daily[boundary-5]
    assert p.sigma_at(daily,boundary) is None


def test_frozen_quantity_delay_base_fee_cash_and_independent_wallets():
    w=p.Wallet('V/base'); px={s:D(100) for s in p.SYMS}
    w.decision(0,D('.1'),px,D('.04'))
    assert w.weekly[1]=={s:D(2) for s in p.SYMS}
    w.execute(0,px); assert not w.trades
    changed={s:D(110) for s in p.SYMS}; w.execute(1,changed)
    assert all(w.q[s]==D(2)*(1-w.fee) for s in p.SYMS)
    assert w.cash==1000-4*110*(1+w.slip)
    assert w.nav(changed)+w.cost_loss==1000
    other=p.Wallet('F/base'); assert other.cash==1000 and all(q==0 for q in other.q.values())
    # Exact arithmetic independent Fraction reference for a buy and sell round trip.
    for s in p.SYMS: w.trade(2,'SELL',s,w.q[s],D(110),'fixture')
    f=Fraction('.001');s=Fraction('.0006')
    exact=Fraction(1000)-4*110*(1+s)+4*(1-f)*110*(1-s)*(1-f)
    assert abs(w.cash-D(exact.numerator)/D(exact.denominator))<D('1e-45')


def test_sell_first_cash_scale_and_halt():
    w=p.Wallet('F/stress');w.cash=D(0);w.q={p.SYMS[0]:D(10),p.SYMS[1]:D(0)}
    rec={};w.weekly=(1,{s:D(5) for s in p.SYMS},rec)
    w.execute(1,{s:D(100) for s in p.SYMS})
    assert [x['side'] for x in w.trades]==['SELL','BUY'] and w.cash==0
    assert rec['cash_scale']<1
    w.halt=True; w.weekly=(2,{s:D(10) for s in p.SYMS},{})
    before=dict(w.q);w.execute(2,{s:D(100) for s in p.SYMS});assert w.q==before


def test_risk_delay_latches_drift_and_gap_recovery():
    w=p.Wallet('V/base');w.cash=D(100);w.q={s:D(5) for s in p.SYMS};px={s:D(100) for s in p.SYMS}
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
    assert len(out['cells'])==4
    for name,c in out['cells'].items():
        assert c['first_decision']['target_total']==D('.4')
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
    assert out['cohort_trigger_hour']==p.SCORE and out['last_processed_hour']==p.SCORE+1
    assert not out['completed_requested_window']
    assert all(e['trades'][-1]['reason']=='COHORT_ADMIN_EXIT' for e in ev.values())
    short,ev=p.analyze(b,end=p.SCORE+1)
    assert short['settlement_end_utc'] is None
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


def test_invalid_twenty_days_does_not_compress_or_replay_week():
    b=synthetic();daily=p.daily_closes(b);boundary=(p.SCORE-1)//24
    b[p.SYMS[0]][(boundary-3)*24]['full']=False
    assert p.sigma_at(p.daily_closes(b),boundary) is None
    w=p.Wallet('F/base');w.decision(0,None,{s:D(100) for s in p.SYMS},D('.04'))
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
