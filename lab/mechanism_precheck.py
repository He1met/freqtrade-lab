"""Deterministic, evidence-linked precheck; no database, network or execution."""
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from fractions import Fraction
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
KNOWLEDGE=ROOT/'docs/research-knowledge/btc-eth-1000-central-v1.json'
KNOWLEDGE_SHA='7469c8970be61d87aa43d6a15507a12434ba0e56768d596c8ea10115cdeda69f'
MAX_CARD_BYTES=65536


class PrecheckError(ValueError):
    pass


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _pairs(items):
    result={}
    for key,value in items:
        if key in result:raise PrecheckError('duplicate JSON key')
        result[key]=value
    return result


def read_card(path):
    with Path(path).open('rb') as source:
        raw=source.read(MAX_CARD_BYTES+1)
    if len(raw)>MAX_CARD_BYTES:raise PrecheckError('card too large')
    def invalid(value):raise PrecheckError('nonfinite JSON constant')
    try:return json.loads(raw,object_pairs_hook=_pairs,parse_constant=invalid),hashlib.sha256(raw).hexdigest()
    except (ValueError,UnicodeError,RecursionError) as exc:raise PrecheckError(str(exc)) from exc


def load_knowledge():
    if digest(KNOWLEDGE)!=KNOWLEDGE_SHA:raise PrecheckError('knowledge SHA drift')
    value=json.loads(KNOWLEDGE.read_bytes())
    for source in value['sources'].values():
        path=(ROOT/source['path']).resolve()
        if not path.is_relative_to(ROOT.resolve()) or digest(path)!=source['sha256']:
            raise PrecheckError('knowledge source SHA drift')
    return value


def number(value):
    try:
        d=Decimal(str(value))
        if not d.is_finite():raise ValueError('nonfinite')
        return Fraction(d)
    except (InvalidOperation,ValueError,TypeError) as exc:raise PrecheckError('invalid numeric evidence') from exc


def sizing(case):
    """Necessary conditions for one frozen, flat-account, 1x calibration cell."""
    e,r,w,dist,px,step,mq,mn=(number(case[k]) for k in ('equity_usdt','risk_fraction','family_scale','stop_distance','open_price','lot_step','min_qty','min_notional'))
    if min(e,r,w,dist,px,step,mq,mn)<=0 or case['leverage']!='1':raise PrecheckError('unsupported sizing domain')
    cell=e*r*w;raw=cell/dist;q=(raw//step)*step
    # Same fresh-entry stop argument and .05 reserve as the pinned native call.
    stop=abs(number(case['native_stop_arg']))
    if stop>=1:raise PrecheckError('unsupported native stop argument')
    minimum=max(mn*max(Fraction(1),min(Fraction(3,2),Fraction(21,20)/(1-stop))),mq*px*Fraction(21,20))
    required=max(mq,minimum/px)/step
    minimum_units=-(-required.numerator//required.denominator)
    fee=number(case['fee'])+number(case['slippage'])
    net=e-q*px*fee
    return dict(scope='FROZEN_SYNTHETIC_NECESSARY_CONDITION_ONLY',risk_cell=cell,raw_quantity=raw,
        floored_quantity=q,quote_notional=q*px,native_min_stake=minimum,
        minimum_grid_quantity=minimum_units*step,minimum_grid_risk=minimum_units*step*dist,
        cell_grid_meets_native_minimum=q>=mq and q*px>=minimum,
        post_cost_single_asset_cap_ok=net>0 and q*px<=Fraction(2,5)*net,
        upward_quantity_adjustment=False,market_feasibility='UNKNOWN',historical_exchange_rules_verified=False)


def utc(text):
    try:
        d=datetime.fromisoformat(text.replace('Z','+00:00'))
        if d.utcoffset()!=timedelta(0):raise ValueError()
        return d
    except (AttributeError,ValueError,TypeError) as exc:raise PrecheckError('explicit UTC window required') from exc


def precheck(card):
    knowledge=load_knowledge()
    fields={'schema','candidate_id','idea','strategy_family','expected_failure_mode','knowledge_refs','mechanism_id',
        'exchange','instrument_type','symbols','purpose','window','reserve_source_sha256','sizing_case_id',
        'sample_evidence_type','claimed_expected_trades','claims_real_qualification','native_calls_requested','reuse_keys'}
    if not isinstance(card,dict) or set(card)-fields or card.get('schema')!='mechanism-precheck-card-v1':
        raise PrecheckError('invalid card schema or fields')
    for key in ('candidate_id','idea','strategy_family','expected_failure_mode','mechanism_id'):
        if not isinstance(card.get(key),str) or not 0<len(card[key])<=2000:raise PrecheckError('invalid candidate text fields')
    lessons={r['id']:r for r in knowledge['lessons']}
    refs=card.get('knowledge_refs',[])
    if not isinstance(refs,list) or any(not isinstance(r,str) or r not in lessons for r in refs):raise PrecheckError('unknown knowledge reference')
    symbols=card.get('symbols')
    if not isinstance(symbols,list) or not symbols or any(not isinstance(s,str) for s in symbols) or len(set(symbols))!=len(symbols):raise PrecheckError('invalid symbols')
    calls=card.get('native_calls_requested',0)
    if type(calls) is not int or calls<0:raise PrecheckError('invalid requested calls')
    claimed=card.get('claimed_expected_trades')
    if claimed is not None and (type(claimed) is not int or claimed<0):raise PrecheckError('invalid expected-count claim')
    reuse=card.get('reuse_keys',[])
    if not isinstance(reuse,list) or any(not isinstance(k,str) for k in reuse):raise PrecheckError('invalid reuse keys')
    if type(card.get('claims_real_qualification',False)) is not bool:raise PrecheckError('invalid qualification claim')
    if card.get('purpose') not in ('EXPLORATORY_TRAINING','INDEPENDENT_CONFIRMATION'):raise PrecheckError('invalid purpose')
    if card.get('sample_evidence_type','UNKNOWN') not in ('UNKNOWN','ENGINEERING_TESTS','LOGICAL_EPISODES','ACTUAL_ORDERS','NATIVE_POSITION_CYCLES','SUPPORTED_NATURAL_CLUSTERS','MODEL_NET'):
        raise PrecheckError('unknown sample evidence type')
    findings=[]
    def add(lesson,state,code,detail):
        findings.append(dict(knowledge_id=lesson,state=state,reason_code=code,detail=detail,
            explicitly_referenced=lesson in refs,source_ids=lessons[lesson]['source_ids']))
    code=card.get('reserve_source_sha256')
    if code==knowledge['reserve']['affected_source_sha256']:
        add('RESERVE_ENDPOINT','BLOCKED','KNOWN_ENDPOINT_DEFECT','Bound historical source loses legal lots at Decimal60.')
    elif code==knowledge['reserve']['fixed_source_sha256']:
        add('RESERVE_ENDPOINT','SATISFIED','REVIEWED_SIZING_SOURCE','Known fixed source identity only; does not qualify this candidate.')
    else:add('RESERVE_ENDPOINT','UNKNOWN','UNBOUND_EXECUTION_SOURCE','Need reviewed source and actual-context sizing evidence.')
    case_id=card.get('sizing_case_id')
    if case_id is not None and not isinstance(case_id,str):
        raise PrecheckError('sizing_case_id must be a string or null')
    case=knowledge['sizing_cases'].get(case_id)
    calculation=None
    if case is None:add('NATIVE_CELL_MINIMUM','UNKNOWN','MISSING_FROZEN_SIZING_CASE','No verified sizing inputs; no invented price or risk distance.')
    elif (case['exchange']!=card.get('exchange') or case['instrument_type']!=card.get('instrument_type') or
          symbols!=[case['symbol']]):
        add('NATIVE_CELL_MINIMUM','BLOCKED','SIZING_SCOPE_MISMATCH','A calibration for another instrument cannot certify this card.')
    else:
        calculation=sizing(case)
        ok=calculation['cell_grid_meets_native_minimum'] and calculation['post_cost_single_asset_cap_ok']
        add('NATIVE_CELL_MINIMUM','SATISFIED' if ok else 'BLOCKED','SCENARIO_NECESSARY_GATE_ONLY' if ok else 'SCENARIO_CELL_BLOCKED',
            'Frozen synthetic arithmetic only; no market feasibility, upsize, capital recommendation or profitability inference.')
    add('SAMPLE_EVIDENCE_TYPE','UNKNOWN','EXPECTED_COUNT_UNSUPPORTED' if claimed is not None else 'EXPECTED_COUNT_UNKNOWN',
        'No future-count estimator or verified candidate sample receipt in this slice. Historical counts are not transferable; free-text claims are not evidence.')
    if card.get('claims_real_qualification'):
        add('QUALIFICATION_LAYERS','BLOCKED','QUALIFICATION_NOT_ESTABLISHED',
            f"{card.get('sample_evidence_type','UNKNOWN')} cannot grant real qualification through a mechanism card.")
    else:add('QUALIFICATION_LAYERS','UNKNOWN','RESEARCH_LAYERS_UNPROVEN','Code/tests, native cycles, modeled net and real qualification remain separate.')
    scope=knowledge['scope']
    matches=(card.get('exchange')==scope['exchange'] and card.get('instrument_type')==scope['instrument_type'] and bool(set(symbols)&set(scope['symbols'])))
    window=card.get('window')
    exposure='UNKNOWN'
    if window is None:add('EXPOSED_WINDOW','UNKNOWN','WINDOW_NOT_BOUND','Need reviewed UTC source scope and protected-window registry.')
    else:
        if not isinstance(window,dict) or set(window)!={'warmup_start','start','end_exclusive'}:raise PrecheckError('invalid window fields')
        warm,start,end=(utc(window[k]) for k in ('warmup_start','start','end_exclusive'))
        if not warm<=start<end:raise PrecheckError('invalid window order')
        w=knowledge['windows']
        if matches and warm<utc(w['sealed_end_exclusive']) and utc(w['sealed_start'])<end:
            exposure='SEALED_OVERLAP';add('EXPOSED_WINDOW','BLOCKED','SEALED_WINDOW_OVERLAP','Includes warmup; later pilot slice remains sealed.')
        elif matches and warm<utc(w['exposed_end_exclusive']) and utc(w['exposed_start'])<end:
            exposure='EXPOSED';ind=card['purpose']=='INDEPENDENT_CONFIRMATION'
            add('EXPOSED_WINDOW','BLOCKED' if ind else 'UNKNOWN','EXPOSED_NOT_INDEPENDENT',
                'Known exposed data; training reuse still needs a separate reviewed protocol, not the old pilot authority.')
        else:add('EXPOSED_WINDOW','UNKNOWN','REGISTRY_REVIEW_REQUIRED','Outside this study is not proof of unexposed or authorized data; cross-asset exposure is not certified.')
    budget=knowledge['budget'];forbidden=set(budget['consumed_market_keys']+budget['sealed_keys']+budget['retired_resource_keys'])
    if set(reuse)&forbidden or any(k.startswith(('synthetic/','retry/','BTC_ETH_PORTFOLIO_V1/synthetic/','BTC_ETH_PORTFOLIO_V1/retry/')) for k in reuse):
        add('BUDGET_NO_REPLAY','BLOCKED','CONSUMED_RETIRED_OR_SEALED_KEY','Old keys and retry resources cannot be reused by this card.')
    elif calls>budget['unallocated']:
        add('BUDGET_NO_REPLAY','BLOCKED','EXCEEDS_UNALLOCATED_SNAPSHOT','Requested calls exceed 58 unallocated slots in the terminal snapshot; no live allocation performed.')
    else:add('BUDGET_NO_REPLAY','UNKNOWN','NO_EXECUTION_ALLOCATION','28/96 historical snapshot only; remaining slots do not authorize a call.')
    if card['mechanism_id']==knowledge['terminal']['study_id']:
        add('TERMINAL_NO_RETUNE','BLOCKED','CLOSED_PILOT','Exact closed pilot is not eligible for automatic replay or retuning.')
    else:add('TERMINAL_NO_RETUNE','UNKNOWN','MECHANISM_DEDUP_REVIEW_REQUIRED','Different ID is not proof of an independent mechanism; semantic deduplication is not implemented.')
    return dict(schema='mechanism-precheck-result-v1',candidate_id=card['candidate_id'],
        status='PRECHECK_BLOCKED' if any(f['state']=='BLOCKED' for f in findings) else 'NEEDS_EVIDENCE',
        knowledge_sha256=KNOWLEDGE_SHA,rule_source_sha256=digest(__file__),findings=findings,sizing=calculation,
        expected_trades=None,expected_trades_state='UNKNOWN',claimed_expected_trades_not_used=claimed,
        candidate_natural_clusters=None,real_economic_qualification='NOT_ESTABLISHED',window_exposure=exposure,
        budget_snapshot={k:budget[k] for k in ('total','consumed','remaining','sealed','unallocated','snapshot_only')},
        execution_authorized=False,promotion_authorized=False,market_feasibility='UNKNOWN',new_market_returns=None,
        next_dependency='REVIEW_BOUNDED_IDEA_INGESTION_AND_DEDUP_TO_CARD; NO_EXECUTION',sources=knowledge['sources'])


def serial(value):
    if isinstance(value,Fraction):return {'numerator':value.numerator,'denominator':value.denominator}
    if isinstance(value,dict):return {k:serial(v) for k,v in value.items()}
    if isinstance(value,list):return [serial(v) for v in value]
    return value
