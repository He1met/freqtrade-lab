import importlib.util,json,time
from pathlib import Path
from decimal import Decimal as D
from fractions import Fraction as F
import pytest
spec=importlib.util.spec_from_file_location('p147',Path(__file__).parents[1]/'scripts/issue147_diagnostic.py');p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)


def fixtures():
    bars={s:{h:dict(open=D(100),close=D(100),full=True) for h in range(p.START,p.END)} for s in p.SYMS}
    prior={'R/'+c:dict(weeks=[],trades=[],marks=[]) for c in p.COSTS}
    return bars,prior,{}


def test_quote_formula_hand_examples():
    for c,(fee,slip) in p.COSTS.items():
        for ratio in ['1.02','1.01','.99','.98']:
            z=p.event_return(D(100),D(100)*D(ratio),c)
            exact=F(ratio)*(1-F(slip))/(1+F(slip))*(1-F(fee))**2-1
            assert abs(z['net']-D(exact.numerator)/D(exact.denominator))<D('1e-48')
        strong=p.event_return(D(100),D(99),c)['net'];weak=p.event_return(D(100),D(98),c)['net']
        assert strong>weak and strong<0


def test_anchors_full_dependency_and_exit_boundary():
    a=p.anchors();assert len(a)==17 and a[0]==p.SCORE-1
    assert all(y-x==42*24 and x+1+168<p.END for x,y in zip(a,a[1:]))
    assert p.stamp(a[-1])=='2022-12-12T00:00:00+00:00'
    bars,prior,summary=fixtures();t=a[0]
    bars['ETHUSDT'][t-1]['close']=D(110)
    bars['ETHUSDT'][t+1]['open']=D(100);bars['ETHUSDT'][t+169]['open']=D(102)
    out,rows=p.analyze(bars,prior,summary)
    assert rows[0]['stronger']=='ETHUSDT' and rows[0]['cost_cases']['base']['stronger']['gross']==D('.02')
    assert rows[1]['status']=='TIE' and rows[1]['stronger'] is None and rows[1]['cost_cases']['base']['paired_net'] is None
    bars['ETHUSDT'][t]['close']=D('999999')
    assert p.input_ratio(bars,t)[0]==D('1.1')
    # Full held interval is necessary; exit open is executable even if its later candle is short.
    bars['ETHUSDT'][t+169]['full']=False
    assert p.analyze(bars,prior,summary)[1][0]['status']=='SCORED'
    bars['ETHUSDT'][t+100]['full']=False
    row=p.analyze(bars,prior,summary)[1][0]
    assert row['status']=='UNKNOWN' and row['cost_cases'] is None and t+100 in row['event_bad_hours']


def test_signal_gap_and_exit_missing_no_anchor_replacement():
    bars,prior,summary=fixtures();t=p.anchors()[0]
    del bars['BTCUSDT'][t-48];del bars['ETHUSDT'][t+169]
    out,rows=p.analyze(bars,prior,summary)
    assert len(rows)==17 and rows[0]['status']=='UNKNOWN'
    assert rows[0]['reasons']==['SIGNAL_29_DAY_INCOMPLETE','EXIT_OPEN_MISSING']
    assert rows[0]['action_coverage']['base']['status']=='NOT_OBSERVED'


def test_prior_state_only_actual_two_leg_rotation():
    t=p.anchors()[1];previous=t-168
    week=lambda h,q:dict(decision_hour=h,relative_ratio=q,execution='EXECUTED')
    tr=lambda side,s:dict(hour=t+1,reason='WEEKLY',side=side,symbol=s)
    prior={'R/'+c:dict(weeks=[week(previous,'2'),week(t,'.5')],trades=[tr('SELL','ETHUSDT'),tr('BUY','BTCUSDT')],marks=[dict(hour=t+168)]) for c in p.COSTS}
    summary={'cells':{'R/'+c:dict(risks=[dict(close_known_utc=p.stamp(t+2),events=['DD15_NO_BUY_LATCH'])],last_joint_observed_utc=p.stamp(t+169)) for c in p.COSTS}}
    out=p.coverage(t,prior,summary)
    assert out['base']['risk_buy_allowed'] and out['base']['actual_rotation']
    for c in p.COSTS:
        summary['cells']['R/'+c]['risks'][0]['close_known_utc']=p.stamp(t)
        prior['R/'+c]['trades']=[tr('SELL','ETHUSDT')]
    out=p.coverage(t,prior,summary)
    assert not out['base']['risk_buy_allowed'] and not out['base']['actual_rotation']
    assert p.coverage(t+42*24,prior,summary)['base']['status']=='NOT_OBSERVED'


@pytest.mark.parametrize('timeout',[False,True])
def test_failed_attempt_consumed(tmp_path,timeout):
    def action(_):
        if timeout:time.sleep(.03)
        raise p.DataError('synthetic missing')
    with pytest.raises((p.DataError,TimeoutError)):p.once(tmp_path/'once',action,.01 if timeout else 1)
    assert json.loads((tmp_path/'once'/'attempt.json').read_text())['units_limit']==17
    with pytest.raises(FileExistsError):p.once(tmp_path/'once',lambda _:None)
