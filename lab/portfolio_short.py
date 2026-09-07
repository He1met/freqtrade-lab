"""Pure consumers for the proposed short feasibility slice; no network/native."""
from decimal import Decimal, InvalidOperation
from fractions import Fraction
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


RESERVE_SEMANTICS_VERSION = 'EXACT_COMMON_SCALE_V1'


def reserve_additions(equity, actual, desired, prices, steps, config):
    """Maximal continuous common addition scale, then conservative lot projection.

    Exact rational inequalities include new fee+slippage in equity. This is not
    a globally optimal discrete allocation. No caller Decimal context is used
    for arithmetic or output construction. Reductions use the existing path.
    """
    if not isinstance(config, dict) or config.get('mode') not in MODES:
        raise SourceError('cost configuration drift')
    if config != configuration(config['mode'], 'base' if config.get('fee') == '0.0006' else 'stress'):
        raise SourceError('cost configuration drift')

    def finite(value):
        try:
            value = Decimal(str(value))
            if not value.is_finite():
                raise ValueError('nonfinite')
            return value
        except (ValueError, TypeError, InvalidOperation) as exc:
            raise SourceError('invalid addition inputs') from exc

    try:
        E = Fraction(finite(equity))
        a = {p: Fraction(finite(actual[p])) for p in PAIRS}
        d = {p: Fraction(finite(desired[p])) for p in PAIRS}
        px = {p: Fraction(finite(prices[p])) for p in PAIRS}
        lots = {p: finite(steps[p]) for p in PAIRS}
    except (KeyError, TypeError) as exc:
        raise SourceError('invalid addition inputs') from exc
    step = {p: Fraction(lots[p]) for p in PAIRS}
    c = Fraction(config['fee']) + Fraction(config['slippage'])
    if E <= 0 or any(px[p] <= 0 or step[p] <= 0 for p in PAIRS):
        raise SourceError('invalid addition inputs')
    if any(a[p] * d[p] < 0 or abs(d[p]) < abs(a[p]) for p in PAIRS):
        raise SourceError('reduction/reversal must use actual V2 execution path first')

    def valid(q):
        net = E - sum(abs(q[p] - a[p]) * px[p] * c for p in PAIRS)
        ns = [abs(q[p]) * px[p] for p in PAIRS]
        return net > 0 and sum(ns) <= Fraction(4, 5) * net and all(
            n <= Fraction(2, 5) * net for n in ns)

    if not valid(a):
        raise SourceError('existing exposure breach: no additions')
    scale = Fraction(1)
    if not valid(d):
        base = {p: abs(a[p]) * px[p] for p in PAIRS}
        added = {p: (abs(d[p]) - abs(a[p])) * px[p] for p in PAIRS}
        cost = sum(added.values()) * c
        constraints = [(base[p], added[p], Fraction(2, 5)) for p in PAIRS]
        constraints.append((sum(base.values()), sum(added.values()), Fraction(4, 5)))
        for exposure, increase, cap in constraints:
            slope = increase + cap * cost
            if slope:
                scale = min(scale, (cap * E - exposure) / slope)
    q = {p: a[p] + scale * (d[p] - a[p]) for p in PAIRS}
    units = {p: abs(q[p]) // step[p] for p in PAIRS}
    q = {p: units[p] * step[p] * (-1 if q[p] < 0 else 1) for p in PAIRS}
    if any(abs(q[p]) < abs(a[p]) or abs(q[p]) > abs(d[p]) for p in PAIRS) or not valid(q):
        raise SourceError('quantized cap check failed')

    # Multiplication/unary minus on Decimal would round under caller context.
    # Construct the exact integer coefficient at the original lot exponent.
    result = {}
    for p in PAIRS:
        parts = lots[p].as_tuple()
        coefficient = int(''.join(map(str, parts.digits))) * units[p]
        result[p] = Decimal((int(q[p] < 0), tuple(map(int, str(coefficient))), parts.exponent))
    return result


from lab.portfolio_source_continuation import continuation_allowance, ContinuationBudget
