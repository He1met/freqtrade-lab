import sys
from pathlib import Path
from decimal import Decimal as D
from datetime import date
import pytest
sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
import issue153_diagnostic as p

def payload():
    return {'data':[{'asset':'usdc_eth','time':d+'T00:00:00.000000000Z','SplyCur':100} for d in p.expected_days()]}

def test_daily_stock_equal_values_numeric_strings_and_complete_calendar():
    x=payload();x['data'][0]['SplyCur']='100.0'
    c=p.supply_check(x)
    assert c['expected_days']==669 and c['unique_days']==669
    assert all(m['value']==D(100) and not m['issues'] for m in c['months'].values())

def test_missing_invalid_and_duplicate_months_do_not_fill():
    x=payload();x['data']=x['data'][1:];x['data'][50]['SplyCur']=None
    x['data'].append(dict(x['data'][80],time=x['data'][80]['time'].replace('.000000000Z','+00:00')))
    c=p.supply_check(x)
    assert all(c['months'][m]['value'] is None for m in ['2021-01','2021-02','2021-03'])
    assert c['months']['2021-04']['value']==D(100)

@pytest.mark.parametrize('edit',[lambda x:x.update(next_page_url='https://example.invalid'),lambda x:x['data'][0].update(asset='usdc'),lambda x:x['data'][0].update(time='2021-01-01T01:00:00Z')])
def test_pagination_identity_non_daily_rejected(edit):
    x=payload();edit(x)
    with pytest.raises(p.DataError):p.supply_check(x)

def test_exact_signal_intervals_costs_and_held_failure():
    bars={h:{'open':D(100),'full':True} for h in range(p.START,p.END+1)}
    c=p.supply_check(payload());c['months']['2021-02']['value']=D(110)
    out,rows=p.analyze(bars,c)
    assert len(rows)==21 and rows[0]['supply_growth']==D('.1') and rows[0]['group']=='EXPAND'
    assert rows[1]['group']=='OTHER' and out['verdict']=='UNDERPOWERED'
    assert rows[-1]['exit_hour']==p.END and rows[0]['entry_hour']==p.hour(date(2021,3,8))
    f,s=p.COSTS['base'];assert abs(rows[0]['costs']['base']['net']-((1-s)/(1+s)*(1-f)**2-1))<D('1e-48')
    bars[p.END]['full']=False;assert p.analyze(bars,c)[1][-1]['status']=='SCORED'
    bars[rows[0]['entry_hour']+1]['full']=False;assert p.analyze(bars,c)[1][0]['status']=='UNKNOWN'

def test_acquisition_no_repeat(tmp_path,monkeypatch):
    monkeypatch.setattr(p,'ROOT',tmp_path);(tmp_path/'acquisition').mkdir()
    monkeypatch.setattr(p.subprocess,'run',lambda *a,**k:pytest.fail('network repeated'))
    with pytest.raises(FileExistsError):p.acquire({},'test')
