import copy
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import pytest
from lab import mechanism_precheck as m

FIXTURE=Path(__file__).parent/'fixtures/research_precheck/candidate-card-v1.json'


def card():
    receipt=json.loads((FIXTURE.parent/'provenance.json').read_text())
    assert m.digest(FIXTURE)==receipt['files'][FIXTURE.name]
    assert m.KNOWLEDGE_SHA==receipt['knowledge_sha256']
    return json.loads(FIXTURE.read_text())


def codes(result):return {f['reason_code'] for f in result['findings']}


def test_frozen_cell_hand_calculation_and_no_manufactured_count_or_return():
    r=m.precheck(card());s=r['sizing']
    assert r['status']=='PRECHECK_BLOCKED' and 'SCENARIO_CELL_BLOCKED' in codes(r)
    assert s['risk_cell']==10 and s['floored_quantity']==Fraction(1,1000)
    assert s['quote_notional']==60 and s['native_min_stake']==63
    assert s['minimum_grid_quantity']==Fraction(2,1000) and s['minimum_grid_risk']==20
    assert s['upward_quantity_adjustment'] is False and s['market_feasibility']=='UNKNOWN'
    assert r['expected_trades'] is r['candidate_natural_clusters'] is r['new_market_returns'] is None
    assert not r['execution_authorized'] and not r['promotion_authorized']
    assert all(f['source_ids'] for f in r['findings'])


def test_arithmetic_pass_still_needs_candidate_evidence_not_llm_approval():
    c=card();c.update(symbols=['ETHUSDT'],sizing_case_id='eth_arithmetic_only',idea='Guaranteed winner with hundreds of trades',claimed_expected_trades=9999,knowledge_refs=[])
    r=m.precheck(c)
    assert r['sizing']['cell_grid_meets_native_minimum']
    assert r['status']=='NEEDS_EVIDENCE' and r['expected_trades'] is None
    assert 'EXPECTED_COUNT_UNSUPPORTED' in codes(r) and len(r['findings'])==7
    assert not r['execution_authorized']


def test_unbound_inputs_never_use_guessed_market_numbers():
    c=card();c.update(sizing_case_id=None,reserve_source_sha256=None,window=None)
    r=m.precheck(c)
    assert r['status']=='NEEDS_EVIDENCE' and r['sizing'] is None
    assert {'MISSING_FROZEN_SIZING_CASE','UNBOUND_EXECUTION_SOURCE','WINDOW_NOT_BOUND'}<=codes(r)


def test_old_source_and_mismatched_sizing_cannot_pass():
    c=card();c.update(reserve_source_sha256=m.load_knowledge()['reserve']['affected_source_sha256'],sizing_case_id='eth_arithmetic_only')
    assert {'KNOWN_ENDPOINT_DEFECT','SIZING_SCOPE_MISMATCH'}<=codes(m.precheck(c))


@pytest.mark.parametrize('kind',['ENGINEERING_TESTS','LOGICAL_EPISODES','ACTUAL_ORDERS','NATIVE_POSITION_CYCLES','SUPPORTED_NATURAL_CLUSTERS','MODEL_NET'])
def test_claimed_evidence_type_cannot_grant_real_qualification(kind):
    c=card();c.update(sample_evidence_type=kind,claims_real_qualification=True)
    r=m.precheck(c)
    assert 'QUALIFICATION_NOT_ESTABLISHED' in codes(r)
    assert r['real_economic_qualification']=='NOT_ESTABLISHED' and r['candidate_natural_clusters'] is None


def test_window_scope_half_open_seal_and_warmup_exposure():
    c=card();c['purpose']='INDEPENDENT_CONFIRMATION'
    assert 'EXPOSED_NOT_INDEPENDENT' in codes(m.precheck(c))
    c['window']=dict(warmup_start='2024-10-31T00:00:00Z',start='2024-11-01T00:00:00Z',end_exclusive='2024-11-02T00:00:00Z')
    assert 'SEALED_WINDOW_OVERLAP' in codes(m.precheck(c))
    c['window']=dict(warmup_start='2025-01-01T00:00:00Z',start='2025-01-02T00:00:00Z',end_exclusive='2025-01-03T00:00:00Z')
    r=m.precheck(c);assert r['window_exposure']=='UNKNOWN' and 'REGISTRY_REVIEW_REQUIRED' in codes(r)
    c['exchange']='another-exchange';c['window']=card()['window']
    assert m.precheck(c)['window_exposure']=='UNKNOWN'  # not a claim of independence


def test_closed_pilot_replay_resource_and_budget_snapshot():
    k=m.load_knowledge();c=card();c.update(mechanism_id=k['terminal']['study_id'])
    assert 'CLOSED_PILOT' in codes(m.precheck(c))
    for key in (k['budget']['consumed_market_keys'][0],k['budget']['sealed_keys'][0],k['budget']['retired_resource_keys'][0],'retry/2'):
        c=card();c['reuse_keys']=[key]
        assert 'CONSUMED_RETIRED_OR_SEALED_KEY' in codes(m.precheck(c))
    c=card();c['native_calls_requested']=59
    assert 'EXCEEDS_UNALLOCATED_SNAPSHOT' in codes(m.precheck(c))


def test_changed_knowledge_or_source_fails_before_precheck(tmp_path,monkeypatch):
    p=tmp_path/'knowledge.json';p.write_bytes(m.KNOWLEDGE.read_bytes()+b' ')
    monkeypatch.setattr(m,'KNOWLEDGE',p)
    with pytest.raises(m.PrecheckError,match='knowledge SHA'):m.precheck(card())
    p.write_bytes(p.read_bytes()[:-1]);monkeypatch.setattr(m,'ROOT',tmp_path)
    with pytest.raises(OSError):m.load_knowledge()  # missing pinned source cannot become positive evidence


@pytest.mark.parametrize('change',[{'native_calls_requested':True},{'claimed_expected_trades':-1},{'execution_authorized':True},{'knowledge_refs':['invented']},{'symbols':[]},{'sample_evidence_type':'llm_likes_it'}])
def test_invalid_card_fails_closed(change):
    c=card();c.update(change)
    with pytest.raises(m.PrecheckError):m.precheck(c)


@pytest.mark.parametrize('raw',[b'{"x":1,"x":2}',b'{"x":NaN}',b'[]'+b' '*65536])
def test_invalid_json_or_size(raw,tmp_path):
    p=tmp_path/'card.json';p.write_bytes(raw)
    with pytest.raises(m.PrecheckError):m.read_card(p)


def test_cli_deterministic_example_no_output_side_effect(tmp_path):
    command=[sys.executable,str(m.ROOT/'scripts/precheck_mechanism.py'),'--card',str(FIXTURE)]
    one=subprocess.run(command,cwd=tmp_path,capture_output=True,text=True,check=True)
    two=subprocess.run(command,cwd=tmp_path,capture_output=True,text=True,check=True)
    assert one.stdout==two.stdout and not list(tmp_path.iterdir())
    assert json.loads(one.stdout)['status']=='PRECHECK_BLOCKED'


@pytest.mark.parametrize('value',[[],{},1,True])
def test_cli_invalid_sizing_id_is_structured_and_has_no_side_effects(value,tmp_path):
    c=card();c['sizing_case_id']=value
    path=tmp_path/'card.json';path.write_text(json.dumps(c));before=path.read_bytes()
    out=subprocess.run([sys.executable,str(m.ROOT/'scripts/precheck_mechanism.py'),'--card',str(path)],
                       cwd=tmp_path,capture_output=True,text=True)
    result=json.loads(out.stdout)
    assert out.returncode==2 and not out.stderr
    assert result['status']=='PRECHECK_BLOCKED' and result['reason_code']=='INVALID_OR_DRIFTED_INPUT'
    assert 'string or null' in result['detail']
    assert list(tmp_path.iterdir())==[path] and path.read_bytes()==before


def test_deep_json_cli_error_is_structured(tmp_path):
    path=tmp_path/'deep.json';raw='['*2000+'0'+']'*2000;path.write_text(raw)
    out=subprocess.run([sys.executable,str(m.ROOT/'scripts/precheck_mechanism.py'),'--card',str(path)],
                       cwd=tmp_path,capture_output=True,text=True)
    assert out.returncode==2 and not out.stderr
    assert json.loads(out.stdout)['reason_code']=='INVALID_OR_DRIFTED_INPUT'
    assert path.read_text()==raw and list(tmp_path.iterdir())==[path]


def test_card_read_is_bounded_before_json_parsing(monkeypatch):
    from io import BytesIO
    requests=[]
    class Input(BytesIO):
        def read(self,size=-1):
            requests.append(size)
            assert 0<=size<=m.MAX_CARD_BYTES+1
            return super().read(size)
    monkeypatch.setattr(Path,'open',lambda *args,**kwargs:Input(b' '* (m.MAX_CARD_BYTES*2)))
    with pytest.raises(m.PrecheckError,match='too large'):m.read_card('unused')
    assert requests==[m.MAX_CARD_BYTES+1]
