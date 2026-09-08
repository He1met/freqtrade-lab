import json
import pytest
from lab.portfolio_source import SourceError
from lab.spot139_source import SpotFetcher,TRAIN,END
from lab.spot139_continuation import GapStream,ContinuationBudget,reuse,collect_continuation
from lab.spot139_gap_proposal import HOUR,KNOWN_START,KNOWN_END


def candle(t):return [t,'10','12','9','11','1',1613014854773 if t==KNOWN_START else t+HOUR-1,'10',1,'1','10','0']
def page(cursor):
    out=[]
    while cursor<END and len(out)<1000:
        if cursor!=KNOWN_START+HOUR:out.append(candle(cursor))
        cursor+=HOUR
    return out

def parent():return dict(status='BLOCKED_DATA',attempts=[dict(number=i) for i in range(1,5)],charged_bytes=290928,historical_attempts=[dict(number=i) for i in range(1,74)])


def test_complete_continuation_35_actual_cursors_and_lost_calendar_days():
    class Fetch:
        def __init__(self):self.calls=[]
        def get(self,e,p):self.calls.append(p);return page(p['startTime'])
    f=Fetch();r=collect_continuation(f,{'004-klines.json':page(TRAIN)})
    assert len(f.calls)==35 and f.calls[0]['startTime']==1613062800000
    assert r['symbols']['BTCUSDT']['hourly_rows']==17519
    assert r['symbols']['ETHUSDT']['signal_days_unavailable_due_to_85_day_rule']==85
    assert r['full_data_pass'] is False


def test_cross_page_known_exception_and_cumulative_unknown_not_reset():
    s=GapStream();s.cursor=KNOWN_START-999*HOUR
    first=[candle(s.cursor+i*HOUR) for i in range(1000)];s.consume(first)
    assert s.cursor==KNOWN_START+HOUR and len(s.affected)==1
    s.consume(page(s.cursor));assert len(s.affected)==2 and s.saw_recovery
    more=page(s.cursor);more[7][6]-=1
    with pytest.raises(SourceError,match='UNKNOWN'):s.consume(more)
    assert len(s.affected)==2


def test_duplicate_unknown_gap_and_premature_tail_stop():
    for kind in ['duplicate','gap','tail']:
        s=GapStream();rows=page(TRAIN)
        if kind=='duplicate':rows[1]=rows[0]
        elif kind=='gap':rows.pop(10)
        else:rows=rows[:5]
        with pytest.raises(SourceError):s.consume(rows)


def test_last_page_requires_end_and_preserves_gap():
    s=GapStream();s.cursor=END-3*HOUR
    with pytest.raises(SourceError,match='tail'):s.consume([candle(END-3*HOUR),candle(END-2*HOUR)])
    s=GapStream();s.cursor=END-3*HOUR;s.consume(page(s.cursor));assert s.finish()['hourly_rows']==3


def test_unknown_anomaly_stops_after_current_request():
    class Fetch:
        calls=0
        def get(self,e,p):self.calls+=1;r=page(p['startTime']);r[1][6]-=1;return r
    f=Fetch()
    with pytest.raises(SourceError,match='UNKNOWN'):collect_continuation(f,{'004-klines.json':page(TRAIN)})
    assert f.calls==1


def test_reuse_hash_mismatch_before_consumption(tmp_path):
    (tmp_path/'raw').mkdir();(tmp_path/'raw'/'001-exchangeInfo.json').write_bytes(b'{}')
    with pytest.raises(SourceError,match='hash'):reuse(tmp_path,{'001-exchangeInfo.json':'0'*64})


def test_failure_charges_and_cannot_restart_or_resume(tmp_path):
    root=tmp_path/'r';root.mkdir();(root/'raw').mkdir();b=ContinuationBudget(tmp_path/'b',root,parent())
    class Fail:
        calls=0
        def open(self,*a,**k):self.calls+=1;raise OSError('synthetic failure')
    f=SpotFetcher(b,root);f.opener=Fail()
    args=dict(symbol='BTCUSDT',interval='1h',startTime=1613062800000,endTime=END-1,limit=1000)
    with pytest.raises(OSError):f.get('klines',args)
    assert f.opener.calls==1 and b.state['charged_bytes']==290928+1048576 and b.state['attempts'][-1]['number']==5
    with pytest.raises(SourceError):f.get('klines',args)
    with pytest.raises(SourceError):ContinuationBudget(tmp_path/'b',tmp_path/'new',parent())
    assert f.opener.calls==1
