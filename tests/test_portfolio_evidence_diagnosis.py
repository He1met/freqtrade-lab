from datetime import datetime,timedelta,timezone
from fractions import Fraction
import pytest
from scripts.diagnose_portfolio_evidence import (components,component_upper_bound,native_minimum,
    certify_episode,actual_increases,ceil_step,validate_interval_mapping)

T=datetime(2024,8,1,tzinfo=timezone.utc)
def interval(name,start,end):return dict(id=name,start=T+timedelta(hours=start),end=T+timedelta(hours=end))


def test_ambiguous_bridge_does_not_create_false_tight_upper_bound():
    items=[interval('a',0,1),interval('bridge',0,4),interval('b',3,4)]
    assert len(components(items))==1
    assert component_upper_bound(items)==2  # subset a,b can produce 2 true components
    assert component_upper_bound([interval('a',0,1),interval('touch',1,2)])==1


def test_component_upper_bound_covers_every_subset_of_intervals():
    from itertools import combinations
    items=[interval('a',0,1),interval('b',1,3),interval('c',2,4),interval('d',5,6),interval('bridge',0,6)]
    bound=component_upper_bound(items)
    for n in range(len(items)+1):
        for subset in combinations(items,n):assert len(components(subset))<=bound


def test_real_native_callsite_padding_not_sentinel_stoploss():
    market={'limits':{'cost':{'min':100},'amount':{'min':'.001'}}}
    assert native_minimum(market,60000,'-.05')==Fraction(2100,19)
    assert native_minimum(market,60000,'-.1')==Fraction(350,3)
    assert native_minimum(market,60000,'0')==105
    assert native_minimum(market,60000,'-.99')==150  # not entry callsite
    assert ceil_step(Fraction(1,3),'.1')==Fraction(2,5)


def test_reduction_and_virtual_intent_are_not_increase_support():
    rows=[dict(id='1',pair='p',filled_at=str(T),side='buy',amount='2'),
          dict(id='2',pair='p',filled_at=str(T+timedelta(hours=1)),side='sell',amount='1'),
          dict(id='3',pair='p',filled_at=str(T+timedelta(hours=2)),side='sell',amount='1')]
    assert [r['id'] for r in actual_increases(rows)]==['1']


def test_unique_whole_cycle_required_no_family_pnl_split():
    ep=dict(interval('e',0,2),pair='p',family='trend',direction=1)
    cycle=dict(id='c',pair='p',is_open=False,is_short=False,opened_at=str(T),closed_at=str(ep['end']))
    intent=dict(id='e',pair='p',family='trend',raw_signed_units='1',risk_scale='1',C_multiplier='1')
    rows={T+timedelta(hours=i):{'family_intents':[intent.copy()]} for i in range(2)}
    assert certify_episode(ep,[cycle],rows)=='c'
    rows[T+timedelta(hours=1)]['family_intents'].append(dict(intent,id='other',family='reversal'))
    assert certify_episode(ep,[cycle],rows) is None
    cycle['closed_at']=str(T+timedelta(hours=1))
    assert certify_episode(ep,[cycle],rows) is None


def test_missing_interval_mapping_is_not_given_a_math_bound():
    ep=dict(interval('e',0,2),pair='p',family='trend',direction=1,reason='expiry')
    rows=[dict(time=str(T),family_intents=[],episodes={})]
    with pytest.raises(ValueError,match='mapping'):validate_interval_mapping({'e':ep},rows,[])


def test_original_valid_one_lot_can_disappear_in_reserve_without_a_fill():
    from decimal import Decimal,localcontext
    from lab.portfolio_short import configuration
    reserve_additions = legacy_reserve()
    from lab.portfolio_causal import PAIRS
    with localcontext() as c:
        c.prec=60
        actual={p:Decimal(0) for p in PAIRS};desired={PAIRS[0]:Decimal('.001'),PAIRS[1]:Decimal(0)}
        result=reserve_additions(1000,actual,desired,{PAIRS[0]:60000,PAIRS[1]:3000},
                                 {p:'.001' for p in PAIRS},configuration('A-trend','base'))
        assert result[PAIRS[0]]==0  # documents frozen original behavior; does not fix it


def test_changed_input_fails_before_output_creation(tmp_path,monkeypatch):
    import json,hashlib
    import scripts.diagnose_portfolio_evidence as d
    source=tmp_path/'source';source.write_bytes(b'changed')
    protocol=tmp_path/'protocol';protocol.write_bytes(b'{}')
    inputs=tmp_path/'inputs';inputs.write_text(json.dumps({'files':{str(source):hashlib.sha256(b'original').hexdigest()},'unchanged_controls':{}}))
    monkeypatch.setattr(d,'PROTOCOL',protocol);monkeypatch.setattr(d,'PROTOCOL_SHA',d.sha(protocol))
    monkeypatch.setattr(d,'INPUT',inputs);monkeypatch.setattr(d,'INPUT_SHA',d.sha(inputs))
    out=tmp_path/'out'
    with pytest.raises(ValueError,match='input/control'):d.run(out)
    assert not out.exists()


def test_endpoint_defect_depends_on_actual_decimal60_context():
    from decimal import Decimal,localcontext
    from lab.portfolio_short import configuration
    reserve_additions = legacy_reserve()
    from lab.portfolio_causal import PAIRS
    actual={p:Decimal(0) for p in PAIRS};desired={PAIRS[0]:Decimal('.001'),PAIRS[1]:Decimal(0)}
    results={}
    for precision in (28,60):
        with localcontext() as c:
            c.prec=precision
            results[precision]=reserve_additions(1000,actual,desired,{PAIRS[0]:60000,PAIRS[1]:3000},
                {p:'.001' for p in PAIRS},configuration('A-trend','base'))[PAIRS[0]]
    assert results=={28:Decimal('.001'),60:Decimal(0)}


def legacy_reserve():
    """Freeze old defect evidence independently of the repaired production code."""
    import hashlib, json
    from pathlib import Path
    from decimal import Decimal, ROUND_FLOOR
    from lab.portfolio_short import configuration
    from lab.portfolio_causal import PAIRS
    from lab.portfolio_source import SourceError
    root = Path(__file__).parent / 'fixtures'
    source = (root / 'reserve_additions_legacy.py.txt').read_bytes()
    receipt = json.loads((root / 'reserve_additions_legacy.json').read_text())
    assert hashlib.sha256(source).hexdigest() == receipt['sha256']
    namespace = dict(Decimal=Decimal, ROUND_FLOOR=ROUND_FLOOR,
                     PAIRS=PAIRS, SourceError=SourceError, configuration=configuration)
    exec(compile(source, 'reserve_additions_legacy.py.txt', 'exec'), namespace)
    return namespace['reserve_additions']
