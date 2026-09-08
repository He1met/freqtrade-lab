import importlib.util,json,sys
from pathlib import Path
from decimal import Decimal as D
from datetime import date
import pytest
sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
spec=importlib.util.spec_from_file_location('p151',Path(__file__).parents[1]/'scripts/issue151_diagnostic.py');p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)

def macro():
    return {'refRates':[{'effectiveDate':d,'type':'EFFR','percent':'0.1'} for d in p.calendar_days()]}

def test_calendar_financial_services_not_exchange():
    days=p.calendar_days()
    for d in ['2021-06-18','2021-06-21','2021-12-24','2021-12-31','2021-04-02','2022-04-15']: assert d in days
    for d in ['2021-07-05','2022-06-20','2022-01-17','2022-09-05']: assert d not in days
    assert len(days)==len(set(days))

def test_macro_missing_extra_and_revision_stay_unknown():
    data=macro();data['refRates']=data['refRates'][1:]
    data['refRates'].append({'effectiveDate':'2021-02-06','type':'EFFR','percent':'.2'})
    data['refRates'][-2]['revisionIndicator']='?'
    out=p.macro_check(data,p.calendar_days())
    assert out['months']['2021-01']['mean'] is None and out['months']['2021-02']['mean'] is None
    assert out['months']['2021-03']['mean']==D('.1')
    assert out['months']['2022-10']['mean'] is None

@pytest.mark.parametrize('alter',[lambda z:z.update(type='OBFR'),lambda z:z.update(effectiveDate='2023-01-01')])
def test_identity_outside_domain_rejected(alter):
    data=macro();alter(data['refRates'][0])
    with pytest.raises(p.DataError):p.macro_check(data,p.calendar_days())

def test_formula_fixed_intervals_unknown_and_underpowered():
    bars={h:{'open':D(100),'full':True} for h in range(p.START,p.END+1)}
    mac=p.macro_check(macro(),p.calendar_days())
    out,rows=p.analyze(bars,mac)
    assert len(rows)==21 and rows[0]['entry_hour']==p.hour(date(2021,3,8)) and rows[-1]['exit_hour']==p.END
    assert out['verdict']=='UNDERPOWERED' and out['groups']=={'UP':0,'NOT_UP':21}
    f,s=p.COSTS['base']; assert abs(rows[0]['costs']['base']['net']-((1-s)/(1+s)*(1-f)**2-1))<D('1e-48')
    bars[p.END]['full']=False
    assert p.analyze(bars,mac)[1][-1]['status']=='SCORED'
    bars[rows[0]['entry_hour']+20]['full']=False
    assert p.analyze(bars,mac)[1][0]['status']=='UNKNOWN'
    assert p.analyze(bars,mac)[1][1]['status']=='SCORED'

def test_acquisition_slot_rejects_before_network(tmp_path,monkeypatch):
    monkeypatch.setattr(p,'ROOT',tmp_path);(tmp_path/'acquisition').mkdir()
    monkeypatch.setattr(p.subprocess,'run',lambda *a,**k:pytest.fail('network called'))
    with pytest.raises(FileExistsError):p.acquire({},'test')
