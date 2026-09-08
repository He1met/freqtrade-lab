import importlib.util
import json
from decimal import Decimal as D
from fractions import Fraction as F
from pathlib import Path
import time
import pytest
spec=importlib.util.spec_from_file_location('p141',Path(__file__).parents[1]/'scripts/issue141_prescreen.py')
p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)


def bars():
    return {s:{t:dict(open=D(100+t),close=D(100+t),full=True) for t in range(6)} for s in ['BTCUSDT','ETHUSDT']}


def test_sign_and_timing():
    b=bars();b['BTCUSDT'][0]['close']=D(101)
    out,ev=p.analyze(b,0,6)
    assert out['cells']['C/base']['triggered']==1
    assert out['cells']['R/base']['triggered']==6
    assert ev[0]['gross']==D(102)/101-1 and ev[0]['entry_hour']==1 and ev[0]['exit_hour']==2
    assert ev[-1]['status']=='ENTRY_OPEN_MISSING+EXIT_OPEN_MISSING'
    b['ETHUSDT'][0]['close']=D(101)
    assert p.analyze(b,0,6)[0]['cells']['C/base']['triggered']==0


def test_short_input_not_future_filter_and_missing():
    b=bars();b['BTCUSDT'][0]['close']=D(101);b['ETHUSDT'][1]['full']=False
    out,ev=p.analyze(b,0,6)
    assert 1 in out['input_unscorable_hours'] and ev[0]['status']=='SCORED'
    assert ev[0]['execution_short_hours']==[1]
    del b['ETHUSDT'][2]
    out,ev=p.analyze(b,0,6)
    assert ev[0]['status']=='EXIT_OPEN_MISSING' and 2 in out['input_unscorable_hours']


def test_formula():
    for cost,(fee,slip) in p.COSTS.items():
        exact=F(11,10)*(1-F(slip))/(1+F(slip))*(1-F(fee))**2-1
        expected=D(exact.numerator)/D(exact.denominator)
        assert abs(p.net(D('.1'),cost)-expected)<D('1e-48')
    assert p.net(D(0),'stress')<p.net(D(0),'base')<0


def test_null_and_no_positive_denominator():
    out=p.summarize([], 'base',['2021-01','2021-02'])
    assert out['net']['mean'] is None and out['largest_positive_month_share'] is None
    row=dict(t=0,month='2021-01',status='SCORED',gross=D(0))
    out=p.summarize([row], 'base',['2021-01','2021-02'])
    assert out['months']['2021-02']['net']['n']==0 and out['net']['stddev'] is None
    assert out['largest_positive_event_share'] is None


@pytest.mark.parametrize('timeout',[False,True])
def test_failure_consumed_no_retry(tmp_path,timeout):
    root=tmp_path/'one'
    def fail(r):
        if timeout:time.sleep(.05)
        raise ValueError('fixture fail')
    with pytest.raises((ValueError,TimeoutError)):p.once(root,fail,.01 if timeout else 1)
    assert json.loads((root/'attempt.json').read_text())['invocations']==1
    assert json.loads((root/'terminal.json').read_text())['status']=='FAILED'
    with pytest.raises(FileExistsError):p.once(root,lambda _:pytest.fail('retry'),1)


def test_inventory_exact_and_warmup_hash_only(tmp_path):
    def source(name,rows,q):
        path=tmp_path/name;path.write_text(json.dumps(rows));return dict(path=str(path),sha256=p.sha(path),request=q)
    # Warmup deliberately invalid JSON payload for prices, never decoded.
    warm=tmp_path/'warm';warm.write_text('not price JSON')
    sources=[dict(path=str(warm),sha256=p.sha(warm),request={'interval':'1d'})]
    anomalies={}
    for s in ['BTCUSDT','ETHUSDT']:
        rows=[[0,'1','1','1','1','0',3599999,'0',0,'0','0','0'],[7200000,'1','1','1','1','0',7200100,'0',0,'0','0','0']]
        sources.append(source(s,rows,dict(symbol=s,interval='1h',startTime=0,endTime=10799999)))
        anomalies[s]=[dict(kind='MISSING',open_ms=3600000,cause='UNKNOWN'),dict(kind='SHORT',open_ms=7200000,cause='UNKNOWN')]
    m=dict(sources=sources,start=0,end=3,anomalies=anomalies)
    assert len(p.load_sources(m)['ETHUSDT'])==2
    m['anomalies']['BTCUSDT']=[]
    with pytest.raises(ValueError,match='inventory'):p.load_sources(m)
