import json
import pytest
from lab.portfolio_source import SourceError
from lab.spot139_source import SpotBudget, SpotFetcher, START, TRAIN, END, validate_page, series, request_url, metadata


def parent():return dict(attempts=[{'number':i} for i in range(73)],charged_bytes=14603929,active_seconds_new=35.759239196777344)
def candle(t,step):return [t,'10','12','9','11','1',t+step-1,'10',1,'1','10','0']


def test_exact_request_domains():
    assert request_url('klines',dict(symbol='BTCUSDT',interval='1h',startTime=TRAIN,endTime=END-1,limit=1000)).startswith('https://api.binance.com/api/v3/klines?')
    with pytest.raises(SourceError):request_url('klines',dict(symbol='BTCUSDT',interval='1h',startTime=START,endTime=END-1,limit=1000))
    with pytest.raises(SourceError):request_url('fundingRate',{})


def test_18_pages_exact_and_fail_no_followup():
    class Good:
        def __init__(self):self.calls=[]
        def get(self,e,p):
            self.calls.append(p);n=min(1000,(END-p['startTime'])//3600000)
            return [candle(p['startTime']+i*3600000,3600000) for i in range(n)]
    f=Good();assert len(series(f,'BTCUSDT','1h'))==17520;assert len(f.calls)==18;assert f.calls[-1]['startTime']==TRAIN+17000*3600000
    class Short(Good):
        def get(self,e,p):return super().get(e,p)[:-1]
    f=Short()
    with pytest.raises(SourceError):series(f,'BTCUSDT','1h')
    assert len(f.calls)==1


@pytest.mark.parametrize('kind',['gap','duplicate','bound','negative','short'])
def test_invalid_page(kind):
    rows=[candle(TRAIN,3600000),candle(TRAIN+3600000,3600000)]
    if kind=='gap':rows[1][0]+=3600000
    if kind=='duplicate':rows[1]=rows[0]
    if kind=='bound':rows[0][6]+=1
    if kind=='negative':rows[0][1]='-1'
    if kind=='short':rows.pop()
    with pytest.raises(SourceError):validate_page(rows,TRAIN,3600000,2)


def test_budget_precharge_terminal_and_restart(tmp_path):
    b=SpotBudget(tmp_path/'b',tmp_path/'root',parent(),now=lambda:10)
    b.limits['gets']=1;r=b.reserve('klines',{})
    assert b.state['charged_bytes']==1048576 and b.state['historical_attempts']==parent()['attempts']
    with pytest.raises(SourceError):b.reserve('klines',{})
    with pytest.raises(SourceError):SpotBudget(tmp_path/'b',tmp_path/'other',parent())
    b.finish(r,size=20,status=200);b.terminal('BLOCKED_DATA')
    with pytest.raises(SourceError):b.reserve('klines',{})


def test_bytes_and_time_prevent_reservation(tmp_path):
    now=[10];b=SpotBudget(tmp_path/'b',tmp_path/'root',parent(),now=lambda:now[0]);b.limits['total_bytes']=1
    with pytest.raises(SourceError):b.reserve('klines',{})
    assert b.state['attempts']==[]
    b.limits['total_bytes']=16777216;now[0]=910
    with pytest.raises(SourceError):b.reserve('klines',{})


def test_network_error_permanently_stops(tmp_path):
    root=tmp_path/'r';root.mkdir();(root/'raw').mkdir();b=SpotBudget(tmp_path/'b',root,parent())
    class Fail:
        calls=0
        def open(self,*a,**k):self.calls+=1;raise OSError('synthetic')
    f=SpotFetcher(b,root);f.opener=Fail()
    with pytest.raises(OSError):f.get('exchangeInfo',{'symbols':'["BTCUSDT","ETHUSDT"]'})
    assert f.opener.calls==1 and b.state['charged_bytes']==1048576
    with pytest.raises(SourceError):f.get('exchangeInfo',{'symbols':'["BTCUSDT","ETHUSDT"]'})
    assert f.opener.calls==1


def test_complete_synthetic_capture_39_and_unrelated_metadata():
    from lab.spot139_source import collect
    rules=[dict(filterType='PRICE_FILTER',minPrice='0',maxPrice='1000000',tickSize='0.01'),dict(filterType='LOT_SIZE',minQty='0.001',maxQty='1000',stepSize='0.001'),dict(filterType='MIN_NOTIONAL',minNotional='5',applyToMarket=True)]
    class Synthetic:
        calls=0
        def get(self,e,p):
            self.calls+=1
            if e=='exchangeInfo':return {'symbols':[dict(symbol=s,status='TRADING',baseAsset=s[:-4],quoteAsset='USDT',isSpotTradingAllowed=True,filters=rules,unrelatedFutureField='ignored') for s in ['BTCUSDT','ETHUSDT']]}
            step=86400000 if p['interval']=='1d' else 3600000
            return [candle(p['startTime']+i*step,step) for i in range(min(1000,(p['endTime']+1-p['startTime'])//step))]
    f=Synthetic();r=collect(f)
    assert f.calls==39 and r['symbols']['ETHUSDT']==dict(warmup_daily_rows=274,training_hourly_rows=17520)
    assert r['economic_result'] is None


def test_manifest_own_registration_hash_and_drift(tmp_path,monkeypatch):
    import scripts.capture_spot139 as cli
    from lab.spot139_source import encoded
    from lab.portfolio_source import digest
    ledger=tmp_path/'ledger';ledger.write_bytes(b'old\n');parentfile=tmp_path/'parent';parentfile.write_bytes(b'parent')
    manifest=tmp_path/'manifest';manifest.write_bytes(b'fixed')
    monkeypatch.setattr(cli,'LEDGER',ledger);monkeypatch.setattr(cli,'PARENT',parentfile);monkeypatch.setattr(cli,'bindings',lambda:{})
    python=str(cli.Path(cli.sys.executable).resolve())
    m=dict(files={},python=python,python_sha256=digest(cli.Path(python).read_bytes()),root=str(cli.ROOT),budget=str(cli.BUDGET),native_authorized=False,control_hashes={},parent_sha256=digest(b'parent'),ledger_before=digest(b'old\n'),ledger_after=digest(b'old\n'+encoded({'own':True})))
    cli.verify(m,manifest,digest(b'fixed'))
    ledger.write_bytes(b'old\n'+encoded({'own':True}));cli.verify(m,manifest,digest(b'fixed'),post=True)
    ledger.write_bytes(ledger.read_bytes()+b'foreign\n')
    with pytest.raises(SourceError):cli.verify(m,manifest,digest(b'fixed'),post=True)


def test_retained_timestamp_shape_is_rejected_without_timezone_conversion():
    # Only observed timestamp structure is retained; prices/volumes are synthetic.
    rows=[candle(1613012400000,3600000),candle(1613019600000,3600000)]
    rows[0][6]=1613014854773
    with pytest.raises(SourceError,match='UTC coverage'):
        validate_page(rows,1613012400000,3600000,2)
