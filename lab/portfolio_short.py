"""Pure consumers for the proposed short feasibility slice; no network/native."""
from decimal import Decimal, ROUND_FLOOR
from datetime import datetime
from lab.portfolio_causal import State, daily_decision, BASE_SHA, SEMANTICS_SHA, PAIRS
from lab.portfolio_causal_account import account_snapshot
from lab.portfolio_source import SourceError, Budget, digest, write_json, exclusive
from pathlib import Path
import json
import time

MODES = ('A-trend', 'A-reversal', 'B', 'C', 'half-risk-B')


def configuration(mode, cost):
    if mode not in MODES or cost not in ('base', 'stress'):
        raise SourceError('unsupported short feasibility job')
    rate = '0.0006' if cost == 'base' else '0.0012'
    return dict(mode=mode, selection={'trend':63,'reversal':'2'},fee=rate,slippage=rate,
                native_fee=rate, leverage=1, qualification='FEASIBILITY_ONLY')


def decision(history, at, equity, config):
    if config != configuration(config['mode'], 'base' if config['fee']=='0.0006' else 'stress'):
        raise SourceError('configuration drift')
    return daily_decision(history,at,equity,mode=config['mode'],selection=config['selection'],
                          base_protocol_sha256=BASE_SHA,semantics_sha256=SEMANTICS_SHA)


def funding_cash(events, at):
    """Events are externally certified eligibility records, not inferred fills.

    Future events are ignored without reading their values. Due but unresolved
    events BLOCK risk decisions. No future-window mark/quantity is backfilled.
    No event mark proxy, timestamp shift or settlement-rounding claim.
    """
    seen=set(); cash=Decimal(0)
    for event in events:
        key=(event['pair'],event['event_at'])
        if key in seen:raise SourceError('duplicate funding event')
        seen.add(key)
        if event['event_at']>at:continue
        if event['pair'] not in PAIRS:raise SourceError('funding pair mismatch')
        if event['available_at']>at or event['eligibility_resolved_at']>at:
            raise SourceError('due funding unresolved: risk decision blocked')
        if not event['eligibility_verified'] or not event['associated_mark_verified']:
            raise SourceError('funding source/eligibility unresolved')
        q,r,m=(Decimal(str(event[k])) for k in ('signed_quantity','rate','associated_mark'))
        if not all(x.is_finite() for x in (q,r,m)) or m<=0:
            raise SourceError('invalid funding event values')
        cash-=q*r*m
    return cash


def account(orders, at, marks, events, config):
    expected=configuration(config['mode'],'base' if config['fee']=='0.0006' else 'stress')
    if config!=expected:raise SourceError('cost configuration drift')
    result=account_snapshot(orders,at=at,marks=marks,funding=funding_cash(events,at),
                            fee=config['fee'],slippage=config['slippage'])
    result['funding_boundary']='EXPLICIT_CERTIFIED_EVENT_ELIGIBILITY_ONLY'
    result['settlement_rounding']='UNKNOWN_NO_ECONOMIC_QUALIFICATION'
    return result


def reserve_additions(equity, actual, desired, prices, steps, config):
    """Only same-direction additions. Reductions remain the existing V2 path.

    Bisection scales additions; final quantities floor to lot steps and are
    rechecked using net equity after new fee+slippage. Old cap breaches block.
    """
    if config != configuration(config['mode'],'base' if config['fee']=='0.0006' else 'stress'):
        raise SourceError('cost configuration drift')
    E=Decimal(str(equity));c=Decimal(config['fee'])+Decimal(config['slippage'])
    a={p:Decimal(str(actual[p])) for p in PAIRS};d={p:Decimal(str(desired[p])) for p in PAIRS}
    px={p:Decimal(str(prices[p])) for p in PAIRS};step={p:Decimal(str(steps[p])) for p in PAIRS}
    if E<=0 or any(px[p]<=0 or step[p]<=0 for p in PAIRS):raise SourceError('invalid addition inputs')
    if any(a[p]*d[p]<0 or abs(d[p])<abs(a[p]) for p in PAIRS):
        raise SourceError('reduction/reversal must use actual V2 execution path first')
    def valid(q):
        cost=sum(abs(q[p]-a[p])*px[p]*c for p in PAIRS)
        net=E-cost
        ns=[abs(q[p])*px[p] for p in PAIRS]
        return net>0 and sum(ns)<=Decimal('.8')*net and all(n<=Decimal('.4')*net for n in ns)
    if not valid(a):raise SourceError('existing exposure breach: no additions')
    low,high=Decimal(0),Decimal(1)
    for _ in range(96):
        mid=(low+high)/2;q={p:a[p]+mid*(d[p]-a[p]) for p in PAIRS}
        if valid(q):low=mid
        else:high=mid
    q={p:a[p]+low*(d[p]-a[p]) for p in PAIRS}
    q={p:(abs(q[p])/step[p]).to_integral_value(rounding=ROUND_FLOOR)*step[p]*(1 if q[p]>=0 else -1) for p in PAIRS}
    if any(abs(q[p])<abs(a[p]) for p in PAIRS) or not valid(q):raise SourceError('quantized cap check failed')
    return q


def continuation_allowance(parent_raw, spec):
    if digest(parent_raw)!=spec['parent_budget_sha256']:raise SourceError('parent budget drift')
    parent=json.loads(parent_raw)
    if parent['status']!='BLOCKED_DATA' or len(parent['attempts'])!=37 or parent['charged_bytes']!=7697705:
        raise SourceError('unexpected parent terminal/counters')
    spent=spec['parent_seconds_charged']
    if spent<130:raise SourceError('parent time cannot be refunded')
    return dict(gets=122-37,total_bytes=64*1024*1024-parent['charged_bytes'],seconds=1800-spent)


class ContinuationBudget(Budget):
    """Single v2 cumulative file at the same global budget root, no resets.

    Preparation never constructs this. A future specific activation must bind
    the new approval and parent SHA; original 37 attempts are copied verbatim.
    """
    def __init__(self,parent_path,spec,approval,now=time.time):
        if not approval or approval==spec['preparation_authorization']:
            raise SourceError('specific continuation activation authorization required')
        parent_path=Path(parent_path)
        parent_raw=parent_path.read_bytes();continuation_allowance(parent_raw,spec)
        self.path=parent_path.with_name('acquisition-continuation-v2.json')
        if self.path.exists():raise SourceError('continuation already started; no new-root reset')
        self.now=now;self.limits=dict(gets=91,total_bytes=64*1024*1024,response_bytes=5*1024*1024,seconds=1800)
        self.state=json.loads(parent_raw)
        self.state.update(status='CONTINUATION_STARTED',parent_budget_sha256=digest(parent_raw),
                          activation=approval,continuation_started=now(),
                          parent_seconds_charged=spec['parent_seconds_charged'],
                          segment_root=str(Path(self.state['root'])/'continuation-v2'))
        with exclusive(str(parent_path)+'.lock'):
            if self.path.exists():raise SourceError('continuation already started; no new-root reset')
            if parent_path.read_bytes()!=parent_raw:raise SourceError('parent changed during activation')
            write_json(self.path,self.state)

    def remaining_time(self):
        return 1800-self.state['parent_seconds_charged']-(self.now()-self.state['continuation_started'])
