#!/usr/bin/env python3
"""Frozen read-only support counts and quantity diagnostics; no matcher or returns."""
from collections import Counter,defaultdict
from datetime import datetime,timedelta
from decimal import Decimal,localcontext
from fractions import Fraction
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from lab.portfolio_execution import capped_targets,executable_quantity
from lab.portfolio_short import reserve_additions,configuration

PROTOCOL=ROOT/'docs/protocols/issue127-readonly-diagnosis-v1.json'
PROTOCOL_SHA='e60fcfb8423e2e2484bf02c0d78a6b06191e8393373afcadc24553ab74dc3274'
INPUT=ROOT/'docs/issue127-input-manifest.json'
INPUT_SHA='fc7fe8ce635ed0bf5aa5cd2b8d3ef9fef297e70e5462feeb4d6442bc5cb8fb3d'
OUTPUT=Path('/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue127-readonly-diagnosis')
NATURAL={'stop','expiry','signal'}


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read(path):return json.loads(Path(path).read_bytes())
def at(value):return datetime.fromisoformat(value)
def num(value):
    if isinstance(value,dict):return Fraction(value['numerator'],value['denominator'])
    return Fraction(str(value))
def dec(value):
    v=num(value)
    with localcontext() as c:
        c.prec=60
        return Decimal(v.numerator)/Decimal(v.denominator)
def serial(v):
    if isinstance(v,Fraction):return {'numerator':v.numerator,'denominator':v.denominator,'display':str(dec(v))}
    if isinstance(v,(Decimal,datetime)):return str(v)
    if isinstance(v,dict):return {str(k):serial(x) for k,x in v.items()}
    if isinstance(v,(list,tuple)):return [serial(x) for x in v]
    return v
def encoded(v):return json.dumps(serial(v),sort_keys=True,allow_nan=False).encode()
def verify_inputs():
    if sha(PROTOCOL)!=PROTOCOL_SHA or sha(INPUT)!=INPUT_SHA:raise ValueError('frozen rule/input SHA drift')
    m=read(INPUT)
    for name,h in {**m['files'],**m['unchanged_controls']}.items():
        if sha(name)!=h:raise ValueError('bound input/control SHA drift: '+name)
    return m


def native_minimum(market,price,stop_arg):
    reserve=Fraction(21,20)
    factor=max(Fraction(1),min(Fraction(3,2),reserve/(1-abs(num(stop_arg)))))
    return max(num(market['limits']['cost']['min'])*factor,
               num(market['limits']['amount']['min'])*num(price)*reserve)


def ceil_step(value,step):
    x=num(value)/num(step)
    return (-(-x.numerator//x.denominator))*num(step)


def components(intervals):
    """Touching merges. This count is exact only for a known supported set."""
    result=[]
    for e in sorted(intervals,key=lambda e:(e['start'],e['end'],e['id'])):
        if not result or e['start']>result[-1]['end']:
            result.append(dict(start=e['start'],end=e['end'],episode_ids=[e['id']]))
        else:
            result[-1]['end']=max(result[-1]['end'],e['end']);result[-1]['episode_ids'].append(e['id'])
    return result


def component_upper_bound(possible):
    """Any subset's component representatives form a disjoint interval set."""
    n=0;end=None
    for e in sorted(possible,key=lambda e:(e['end'],e['start'],e['id'])):
        if end is None or e['start']>end:n+=1;end=e['end']
    return n


def effective(intent):
    return num(intent['raw_signed_units'])*num(intent['risk_scale'])*num(intent['C_multiplier'])


def actual_increases(orders):
    q=defaultdict(Fraction);events=[]
    for o in sorted(orders,key=lambda o:(at(o['filled_at']),o['id'])):
        p=o['pair'];before=q[p];delta=num(o['amount'])*(1 if o['side']=='buy' else -1);after=before+delta
        if before*after<0:raise ValueError('unsupported same-fill reversal in approved evidence')
        if abs(after)>abs(before):events.append(dict(**o,direction=1 if after>0 else -1,actual_increase=abs(after)-abs(before)))
        q[p]=after
    if any(q.values()):raise ValueError('original final inventory not flat')
    return events


def episodes_from(events):
    episodes={}
    for event in events:
        identity=event['id'];ep=event['episode'];entry=ep['entry']
        if event['event']=='ACTIVATED':
            if identity in episodes:raise ValueError('duplicate episode activation')
            episodes[identity]=dict(id=identity,pair=entry['pair'],family=entry['family'],direction=entry['direction'],
                start=at(event['at']),end=None,reason=None,source=ep)
        else:
            if identity not in episodes or episodes[identity]['end'] is not None:raise ValueError('unmatched/duplicate episode end')
            episodes[identity].update(end=at(event['at']),reason=event['reason'])
    if any(e['end'] is None for e in episodes.values()):raise ValueError('episode endpoint missing')
    return episodes


def certify_episode(ep,cycles,bytime):
    for cycle in cycles:
        if (cycle['pair']!=ep['pair'] or cycle['is_open'] or
            (-1 if cycle['is_short'] else 1)!=ep['direction'] or
            not ep['start']<=at(cycle['opened_at'])<ep['end'] or at(cycle['closed_at'])!=ep['end']):continue
        t=at(cycle['opened_at']);ok=True
        while t<ep['end']:
            row=bytime.get(t)
            if row is None:raise ValueError('missing original hourly trace')
            contributors=[i for i in row['family_intents'] if i['pair']==ep['pair'] and effective(i)]
            if len(contributors)!=1 or contributors[0]['id']!=ep['id'] or effective(contributors[0])*ep['direction']<=0:
                ok=False;break
            t+=timedelta(hours=1)
        if ok:return cycle['id']
    return None


def validate_interval_mapping(eps,trace,orders):
    previous=None
    for row in trace:
        t=at(row['time'])
        if previous is not None and t-previous!=timedelta(hours=1):raise ValueError('cannot prove mapping: trace gap')
        previous=t
        ids=[i['id'] for i in row['family_intents']]
        keys=[(i['pair'],i['family']) for i in row['family_intents']]
        if len(ids)!=len(set(ids)) or len(keys)!=len(set(keys)):raise ValueError('cannot prove one episode per pair/family')
        active={e['id'] for e in eps.values() if e['start']<=t<e['end']}
        if set(ids)!=active or set(row['episodes'])!=active:raise ValueError('cannot prove original full interval mapping')
    for o in orders:
        t=at(o['filled_at'])
        if t.minute or t.second or t.microsecond:raise ValueError('unmapped non-hour actual fill')
    known=NATURAL|{'halt','RISK_OR_CONTROL_REMOVAL','PHASE_END_NOT_NATURAL_EXIT'}
    if any(e['reason'] not in known or e['end']<=e['start'] for e in eps.values()):
        raise ValueError('cannot prove original episode endpoint/reason')


def sample_support(events,trace,orders,cycles,mode):
    eps=episodes_from(events);bytime={at(r['time']):r for r in trace};increases=actual_increases(orders)
    validate_interval_mapping(eps,trace,orders)
    for e in eps.values():
        e['possible_fill_ids']=[];e['certified_cycle_id']=None
        if e['reason'] not in NATURAL:continue
        for o in increases:
            t=at(o['filled_at'])
            if o['pair']!=e['pair'] or o['direction']!=e['direction'] or not e['start']<=t<e['end']:continue
            row=bytime.get(t)
            if row is None:raise ValueError('missing actual fill control row')
            matches=[i for i in row['family_intents'] if i['id']==e['id'] and effective(i)*e['direction']>0]
            if matches:e['possible_fill_ids'].append(o['id'])
        if e['possible_fill_ids']:e['certified_cycle_id']=certify_episode(e,cycles,bytime)
    result={}
    for family in ('trend','reversal'):
        rows=[e for e in eps.values() if e['family']==family]
        enabled=not mode.startswith('A-') or mode=='A-'+family
        possible=[e for e in rows if e['possible_fill_ids']]
        certified=[e for e in possible if e['certified_cycle_id'] is not None]
        groups=[];upper=0
        for direction in (-1,1):
            groups+=components([e for e in certified if e['direction']==direction])
            upper+=component_upper_bound([e for e in possible if e['direction']==direction])
        known=len(possible)==len(certified)
        bound_fills=len({x for e in possible for x in e['possible_fill_ids']})
        assert upper<=bound_fills
        result[family]=dict(enabled=enabled,activated_episodes=len(rows),natural_exit_episodes=sum(e['reason'] in NATURAL for e in rows),
            possible_supported_episodes=len(possible),certified_episodes=len(certified),
            natural_clusters=len(groups) if known and enabled else None,
            attribution='CERTIFIED_EXCLUSIVE_CYCLES' if known and enabled else 'UNKNOWN_NETTED_OR_UNPROVEN_EXECUTION' if enabled else 'NOT_ENABLED',
            proven_cluster_upper_bound=upper if enabled else None,increase_fill_upper_bound=bound_fills if enabled else None,
            minimum_required=30,verdict='UNDERPOWERED' if enabled and upper<30 else 'NOT_QUALIFIED',
            certified_subset_components=groups,certified_subset_component_count_is_not_a_lower_bound_when_ambiguous=True,
            statistical_independence='UNKNOWN',original_full_logical_intervals_preserved=True,
            upper_bound_mapping_verified=True,upper_bound_conditional_on_frozen_support_definition=True,
            upper_bound_proof='Every eligible supported interval has an actual increase in its original interval and is in the possible set. Choose one interval from each cluster of any true supported subset: representatives are strictly disjoint. Earliest-finish maximum disjoint count bounds their number. Unique pair/family occupancy also maps each possible support episode to a distinct compatible increase event within a family; no interval is trimmed to actual partial holding.')
    return result,list(eps.values()),increases


def summary(values):
    values=sorted(values)
    if not values:return dict(count=0,min=None,median=None,max=None)
    n=len(values);median=values[n//2] if n%2 else (values[n//2-1]+values[n//2])/2
    return dict(count=n,min=values[0],median=median,max=values[-1])


def recorded_core_grid(row,opens,markets):
    """Recompute only the old per-hour cash/lot arithmetic from recorded targets."""
    with localcontext() as context:
        context.prec=60
        actual={p:dec(row['actual_inventory'][p]) for p in markets}
        targets={p:dec(row['control']['risk_target_quantities'][p]) for p in markets}
        adds={p:max(Decimal(0),abs(targets[p])-abs(actual[p])) for p in markets}
        reserve=1+dec(row['control']['costs']['native_fee_each_side'])+dec(row['control']['costs']['audit_slippage_each_side'])
        required=sum(adds[p]*dec(opens[p])*reserve for p in markets)
        scale=min(Decimal(1),dec(row['model_free'])/required) if required else Decimal(1)
        for p,market in markets.items():
            if adds[p]:targets[p]=(abs(actual[p])+adds[p]*scale)*(1 if targets[p]>0 else -1)
            rules=dict(step=str(market['precision']['amount']),min_qty=str(market['limits']['amount']['min']),
                       max_qty=str(market['limits']['amount']['max']),min_notional=str(market['limits']['cost']['min']))
            targets[p]=actual[p]+executable_quantity(targets[p]-actual[p],dec(opens[p]),**rules)
    return actual,targets


def diagnose_job(job,prices,markets,start,end,detail_stream):
    p=Path(job['output_root']);events=read(p/'episode-events.json');trace=read(p/'trace.json')
    orders=read(p/'actual-orders.json');cycles=read(p/'position-cycles.json')
    samples,eps,increases=sample_support(events,trace,orders,cycles,job['mode'])
    bytime={at(r['time']):r for r in trace};order_at=defaultdict(list)
    for o in orders:order_at[(at(o['filled_at']),o['pair'])].append(o)
    counters={pair:Counter() for pair in markets};activation_rows=[];previous_targets={};previous_q={}
    for row in trace:
        t=at(row['time'])
        if not start<=t<end:continue
        opens={p:prices[p][t] for p in markets};equity=num(row['equity'])
        weighted=[{i['pair']:dec(effective(i))} for i in row['family_intents']]
        with localcontext() as c:
            c.prec=60
            capped=capped_targets(weighted,{p:dec(v) for p,v in opens.items()},dec(equity))
        for pair,market in markets.items():
            c=counters[pair];c['hours']+=1;price=opens[pair]
            intents=[i for i in row['family_intents'] if i['pair']==pair]
            gross_raw=sum((abs(num(i['raw_signed_units'])) for i in intents),Fraction(0))
            gross=sum((abs(effective(i)) for i in intents),Fraction(0));net=sum((effective(i) for i in intents),Fraction(0))
            current=num(row['actual_inventory'][pair]);target=num(row['targets'][pair]);cap=num(capped[pair]);delta=cap-current
            step=num(market['precision']['amount']);minqty=num(market['limits']['amount']['min']);minnotional=num(market['limits']['cost']['min'])
            maxqty=num(market['limits']['amount']['max']);floor=(abs(delta)//step)*step
            flags=[]
            if gross_raw:flags.append('ACTIVE_RAW_FAMILY_INTENTION')
            if gross_raw and not gross:flags.append('RECORDED_SCALE_ZERO')
            if gross and not net:flags.append('EXACT_NET_CANCELLATION')
            elif gross>abs(net):flags.append('PARTIAL_NET_CANCELLATION')
            # Compare actual cap inequalities, not a Fraction-vs-Decimal last digit.
            whole_net={p:sum((effective(i) for i in row['family_intents'] if i['pair']==p),Fraction(0)) for p in markets}
            if abs(net)*price>equity*Fraction(2,5) or sum(abs(whole_net[p])*opens[p] for p in markets)>equity*Fraction(4,5):
                flags.append('CAP_40_80_RECOMPUTED')
            if delta:
                if not floor:flags.append('LOT_FLOOR_ZERO_RECOMPUTED')
                if floor<minqty:flags.append('BELOW_MIN_QTY_RECOMPUTED')
                if floor*price<minnotional:flags.append('BELOW_RAW_MIN_NOTIONAL_RECOMPUTED')
                if floor>maxqty:flags.append('ABOVE_MAX_QTY_RECOMPUTED')
            if pair in row['control']['paused_assets']:flags.append('RECORDED_RISK_PAUSE')
            if pair in row['control']['pending_actual_flat']:flags.append('RECORDED_PENDING_FLAT')
            if t.hour in (0,8,16) and abs(cap)>abs(current) and abs(target)<=abs(current):flags.append('FUNDING_HOUR_NO_ADD_RULE_DIAGNOSIS')
            fresh=current==0 and target!=0
            addition=current*target>0 and abs(target)>abs(current)
            entrymin=native_minimum(market,price,'-.05');adjustmin=native_minimum(market,price,'-.1')
            reserve_before=None;reserve_after=None
            # At 01 the controller rebuilds unrounded family targets; at funding
            # hours it forbids adds. Do not count those as grid-reserve invocations.
            if t<end-timedelta(hours=1) and t.hour not in (0,1,8,16) and not any(row['control'][k] for k in ('hard_cap_fallback','paused_assets','pending_actual_flat','blocked_assets')):
                actual,desired=recorded_core_grid(row,opens,markets)
                reductions=any(abs(desired[p])<abs(actual[p]) for p in markets)
                adds=any(abs(desired[p])>abs(actual[p]) for p in markets)
                if not reductions and adds and abs(desired[pair])>abs(actual[pair]):
                    try:
                        with localcontext() as context:
                            context.prec=60
                            reserved=reserve_additions(dec(equity),actual,desired,{p:dec(v) for p,v in opens.items()},
                                {p:str(markets[p]['precision']['amount']) for p in markets},configuration(job['mode'],job['cost']))
                        reserve_before=abs(num(desired[pair]));reserve_after=abs(num(reserved[pair]))
                        if reserve_after<reserve_before:
                            flags.append('VALID_GRID_TARGET_LOSES_LOT_IN_ORIGINAL_RESERVE_DIAGNOSIS')
                            if num(reserved[pair])==target:flags.append('RESERVE_LOSS_MATCHES_RECORDED_FINAL_TARGET')
                            else:flags.append('RESERVE_LOSS_OTHER_FINAL_CONSTRAINT_UNRESOLVED')
                            if reserve_after==0 and target==0:flags.append('RESERVE_LOSS_TO_ZERO_MATCHES_RECORDED_ZERO_TARGET')
                    except ValueError:flags.append('RESERVE_DIAGNOSTIC_PRECONDITION_NOT_MET')
            actual_fills=order_at[(t,pair)];wanted=abs(target-current)*price
            if fresh:
                flags.append('RECORDED_FRESH_ENTRY_TARGET')
                flags.append('BELOW_NATIVE_ENTRY_PADDING_RECOMPUTED' if wanted<entrymin else 'NATIVE_ENTRY_MIN_PASSES_RECOMPUTED')
                if not actual_fills:flags.append('RECORDED_ENTRY_TARGET_WITHOUT_ACTUAL_FILL_REASON_UNKNOWN')
            if addition:
                flags.append('RECORDED_ADD_TARGET')
                if wanted<adjustmin:flags.append('BELOW_NATIVE_ADJUST_CALLBACK_PADDING_RECOMPUTED')
            if abs(target)<abs(current):flags.append('RECORDED_REDUCE_TARGET')
            if actual_fills:flags.append('ACTUAL_FILL_HOUR')
            if pair in previous_targets and previous_targets[pair]!=target:flags.append('RECORDED_TARGET_CHANGED')
            if pair in previous_q and previous_q[pair]!=current:flags.append('RECORDED_ACTUAL_QUANTITY_CHANGED')
            previous_targets[pair]=target;previous_q[pair]=current
            for flag in flags:c[flag]+=1
            detail_stream.write(encoded(dict(job=job['key'],time=t,pair=pair,raw_gross_units=gross_raw,
                weighted_gross_units=gross,net_units=net,capped_units=cap,recorded_target=target,actual_before=current,
                original_open=price,lot_step=step,recomputed_floor_abs_delta=floor,raw_min_notional=minnotional,
                native_entry_min=entrymin,native_adjust_callback_min=adjustmin,
                original_reserve_grid_quantity_before=reserve_before,original_reserve_grid_quantity_after=reserve_after,flags=flags,actual_order_ids=[o['id'] for o in actual_fills],
                basis='DIAGNOSTIC_RECOMPUTATION_NOT_NATIVE_REJECTION',actual_unfilled_reason='UNKNOWN_NOT_RECORDED'))+b'\n')
    for ep in eps:
        t=ep['start'];row=bytime[t];pair=ep['pair'];market=markets[pair];price=prices[pair][t]
        activation=next(x for x in row['control']['activated'] if x['pair']==pair and x['family']==ep['family'])
        intent=next(i for i in row['family_intents'] if i['id']==ep['id'])
        units=num(ep['source']['entry']['units']);distance=num(ep['source']['entry']['distance'])
        fraction=Fraction(1,100) if job['mode'].startswith('A-') else Fraction(1,200)
        scale=num(intent['risk_scale'])*num(intent['C_multiplier']);step=num(market['precision']['amount'])
        entrymin=native_minimum(market,price,'-.05');minimum_quote=ceil_step(entrymin/price,step)*price
        necessary=None if scale==0 else max(minimum_quote/Fraction(2,5),minimum_quote*distance/(price*fraction*scale))
        nominal_units=Fraction(1000)*fraction/distance*scale
        nominal_cap=min(nominal_units,Fraction(400)/price)
        floor=(nominal_cap//step)*step
        nominal_pass=floor*price>=entrymin and floor>=num(market['limits']['amount']['min']) and floor<=num(market['limits']['amount']['max'])
        activation_rows.append(dict(job=job['key'],episode_id=ep['id'],pair=pair,family=ep['family'],time=t,direction=ep['direction'],
            original_frozen00_units=num(activation['frozen_units']),activated01_units=units,quantity_downscaled_at01=units<num(activation['frozen_units']),
            original_frozen_risk_dollars=num(activation['frozen_units'])*distance,initial_nominal_cell_dollars=Fraction(1000)*fraction,
            activated_risk_dollars=units*distance,recorded_family_scale=scale,stop_distance=distance,relative_stop_distance=distance/price,
            raw_notional=units*price,effective_notional=units*price*scale,native_min_quote=entrymin,ceil_lot_min_quote=minimum_quote,
            necessary_equity_bound=necessary,necessary_equity_is_not_sufficient_or_authorized=True,
            isolated_1000_cell_meets_native_entry_min=nominal_pass,
            recorded_total_asset_target=num(row['targets'][pair]),actual_fill_ids=[o['id'] for o in order_at[(t,pair)]],
            natural_exit_reason=ep['reason'],possible_support_fill_ids=ep['possible_fill_ids'],certified_cycle_id=ep['certified_cycle_id'],
            basis='RECORDED_ACTIVATION_PLUS_DIAGNOSTIC_RECOMPUTATION_NOT_NATIVE_REJECTION'))
    perpair={}
    for pair in markets:
        a=[x for x in activation_rows if x['pair']==pair]
        perpair[pair]=dict(hour_counts=dict(counters[pair]),activated_episodes=len(a),
            natural_exit_reasons=dict(Counter(e['reason'] for e in eps if e['pair']==pair)),
            quantity_downscaled_at01=sum(x['quantity_downscaled_at01'] for x in a),
            isolated_1000_cell_minimum_passes=sum(x['isolated_1000_cell_meets_native_entry_min'] for x in a),
            raw_notional=summary([x['raw_notional'] for x in a]),effective_notional=summary([x['effective_notional'] for x in a]),
            necessary_equity_bound=summary([x['necessary_equity_bound'] for x in a if x['necessary_equity_bound'] is not None]),
            actual_orders=sum(o['pair']==pair for o in orders),actual_closed_cycles=sum(c['pair']==pair for c in cycles),
            actual_increase_fills=sum(o['pair']==pair for o in increases))
    return dict(key=job['key'],mode=job['mode'],cost=job['cost'],samples=samples,assets=perpair,
                preactivation_candidate_count=None,preactivation_candidate_reason='NOT_RECORDED_NOT_REPLAYED',
                actual_native_rejection_reasons=None,family_pnl=None),activation_rows


def run(output):
    output=Path(output)
    if output.exists():raise ValueError('new output directory required; never overwrite')
    m=verify_inputs();script_sha=sha(__file__)
    import pandas as pd
    import pyarrow
    if sys.version.split()[0]!='3.13.13' or pd.__version__!='3.0.3' or pyarrow.__version__!='25.0.0':
        raise ValueError('use unchanged pinned source-processing environment')
    prepared=Path(m['prepared_root']);markets={x['symbol']:x for x in read(prepared/'assembly.json')['markets']}
    prices={};start=at(m['score_start'].replace('Z','+00:00'));end=at(m['allowed_data_end_exclusive'].replace('Z','+00:00'))
    for pair in markets:
        name=pair.replace('/','_').replace(':','_')+'-1h-futures.feather'
        frame=pd.read_feather(prepared/'data/futures'/name)
        if len(frame)!=8784 or frame['date'].duplicated().any() or frame['date'].max()>=end:raise ValueError('unapproved price view')
        prices[pair]={t.to_pydatetime():num(v) for t,v in zip(frame['date'],frame['open'])}
    output.mkdir(parents=True);summaries=[];activations=[]
    with (output/'hourly-diagnostics.jsonl').open('xb') as stream:
        for job in m['jobs']:
            result,rows=diagnose_job(job,prices,markets,start,end,stream);summaries.append(result);activations+=rows
    (output/'activation-diagnostics.json').write_bytes(encoded(activations))
    verify_inputs()
    if sha(__file__)!=script_sha:raise ValueError('diagnostic script changed')
    enabled=[s for j in summaries for s in j['samples'].values() if s['enabled']]
    underpowered=all(s['proven_cluster_upper_bound']<30 for s in enabled)
    result=dict(schema='issue127-readonly-diagnostic-result-v1',protocol_sha256=PROTOCOL_SHA,input_sha256=INPUT_SHA,
        script_sha256=script_sha,source_execution_commit=m['source_execution_commit'],jobs=summaries,
        verdict='UNDERPOWERED' if underpowered else 'NOT_QUALIFIED',economic_qualification='UNKNOWN_NO_REAL_ECONOMIC_QUALIFICATION',
        family_pnl=None,new_returns=None,new_fills=0,native_constructors=0,native_starts=0,new_gets=0,reserved_slice_read=False,
        controls_unchanged=True,output_root=str(output),
        detail_files={p.name:sha(p) for p in output.iterdir() if p.is_file()},
        execution_fidelity='OLD_EXECUTED_PATHS_AFFECTED_BY_DECIMAL60_ENDPOINT_LOT_DEFECT; INTEGRITY_PASS_IS_NOT_RULE_FIDELITY',
        sample_bounds_do_not_predict_repaired_paths=True,
        recommendation='SEPARATE_FIXED_PACKAGE_REVIEW_OF_MINIMAL_RESERVE_ENDPOINT_GRID_FIX; NO_MARKET_REPLAY_OR_RESERVED_CONSUMPTION',
        recommendation_is_authorization=False)
    (output/'summary.json').write_bytes(encoded(result))
    return dict(output_root=str(output),summary_sha256=sha(output/'summary.json'),verdict=result['verdict'],native_calls=0,new_gets=0)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,default=OUTPUT)
    args=parser.parse_args();print(encoded(run(args.output)).decode())
