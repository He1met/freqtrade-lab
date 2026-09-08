import pytest
from lab.portfolio_source import SourceError
from lab.spot139_source import TRAIN,END
from lab.spot139_inventory import InventoryStream,InventoryBudget,collect_inventory,reuse
H=3600000
MISSING={1613016000000,1614996000000}

def row(t):return [t,'10','12','9','11','1',1613014854773 if t==1613012400000 else t+H-1,'10',1,'1','10','0']
def page(cursor):
    out=[]
    while cursor<END and len(out)<1000:
        if cursor not in MISSING:out.append(row(cursor))
        cursor+=H
    return out

def test_full_inventory_reuse_two_pages_and_34_requests():
    first=page(TRAIN);second=page(first[-1][0]+H);cursor=second[-1][0]+H
    assert cursor==1616666400000
    class F:
        calls=[]
        def get(self,e,p):self.calls.append(p);return page(p['startTime'])
    f=F();r=collect_inventory(f,dict(BTC_page1=first,BTC_page2=second),cursor)
    assert len(f.calls)==34 and f.calls[0]['startTime']==cursor
    b=r['symbols']['BTCUSDT'];assert b['hourly_rows']==17518 and b['missing_hours']==2 and b['short_candles']==1
    assert b['complete_training_days']==728 and b['available_training_decision_days_by_dependency']=={'85':622,'273':434}
    assert r['complete_data_pass'] is False and r['economic_result'] is None


def test_unknown_anomalies_across_pages_accumulate_no_fill():
    s=InventoryStream();a=page(TRAIN);s.consume(a);s.consume(page(s.cursor))
    assert s.rows==2000 and len(s.anomalies)==3 and all(x['cause']=='UNKNOWN' for x in s.anomalies)


@pytest.mark.parametrize('kind',['duplicate','type','open','close','ohlc','negative'])
def test_fatal_structure(kind):
    s=InventoryStream();r=page(TRAIN)
    if kind=='duplicate':r[1]=r[0]
    if kind=='type':r[0][0]=str(r[0][0])
    if kind=='open':r[0][0]+=1
    if kind=='close':r[0][6]+=1
    if kind=='ohlc':r[0][2]='1'
    if kind=='negative':r[0][5]='-1'
    with pytest.raises(SourceError):s.consume(r)


def test_short_page_not_endpoint_stops_and_wrong_cursor_pre_network():
    with pytest.raises(SourceError):InventoryStream().consume(page(TRAIN)[:3])
    class Never:
        def get(self,*a):raise AssertionError('network touched')
    first=page(TRAIN);second=page(first[-1][0]+H)
    with pytest.raises(SourceError,match='cursor'):collect_inventory(Never(),dict(BTC_page1=first,BTC_page2=second),TRAIN)


def test_hash_before_any_market_use(tmp_path):
    p=tmp_path/'raw';p.write_bytes(b'[]')
    with pytest.raises(SourceError,match='SHA'):reuse({'metadata':dict(path=str(p),sha256='0'*64)})


def test_budget_34_and_no_reset(tmp_path):
    parent=dict(attempts=[dict(number=i) for i in range(1,6)],charged_bytes=472114,status='BLOCKED_DATA',historical_attempts=[{}]*73)
    b=InventoryBudget(tmp_path/'b',tmp_path/'root',parent)
    for _ in range(34):
        r=b.reserve('klines',{});b.finish(r,size=10,status=200)
    with pytest.raises(SourceError):b.reserve('klines',{})
    assert len(b.state['attempts'])==39
    with pytest.raises(SourceError):InventoryBudget(tmp_path/'b',tmp_path/'new',parent)
    b.terminal('BLOCKED_DATA')
    with pytest.raises(SourceError):b.reserve('klines',{})
