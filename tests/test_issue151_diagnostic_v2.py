import sys
from pathlib import Path
from decimal import Decimal as D
import pytest
sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
import issue151_diagnostic_v2 as p

def payload():
    return {'refRates':[{'type':'EFFR','effectiveDate':d,'percentRate':'0.1'} for d in p.v1.calendar_days()]}

def test_exact_adapter_preserves_rate_calendar_revision():
    x=payload();x['refRates'][0]['revisionIndicator']='Y'
    out=p.macro_check(x,p.v1.calendar_days())
    assert out['months']['2021-01']['mean']==D('.1') and len(out['revisions'])==1
    assert 'percent' not in x['refRates'][0]
    del x['refRates'][0]
    assert p.macro_check(x,p.v1.calendar_days())['months']['2021-01']['mean'] is None

@pytest.mark.parametrize('change',[{'percent':'0.2'},{'type':'OBFR'},{'percentRate':'NaN'},{'percentRate':True}])
def test_no_fallback_or_invalid_identity(change):
    x=payload();x['refRates'][0].update(change)
    with pytest.raises(p.DataError):p.macro_check(x,p.v1.calendar_days())
