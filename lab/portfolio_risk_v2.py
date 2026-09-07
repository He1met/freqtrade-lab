"""Versioned hard-cap fallback; v1 signal/core bytes and receipts stay intact."""
from dataclasses import dataclass, replace
from datetime import timedelta
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from lab.portfolio_causal import (State, Decision, PAIRS, BASE_SHA, SEMANTICS_SHA,
                                 verify_binding, daily_decision, advance, CausalError, utc)
from lab.portfolio_execution import dec, executable_quantity

V2_SHA='9773d03346b89822a8495a3d5e6566cd8895c3c83e377be63b74b9f80477e784'


def verify_v2(base,semantics):
    verify_binding(base,SEMANTICS_SHA)
    path=Path(__file__).resolve().parents[1]/'docs/protocols/btc-eth-portfolio-semantics-v2.json'
    if semantics!=V2_SHA or sha256(path.read_bytes()).hexdigest()!=V2_SHA:
        raise CausalError('unknown or changed v2 execution semantics')


@dataclass(frozen=True)
class RiskDecision:
    inner: Decision
    semantics_sha256: str=V2_SHA


@dataclass(frozen=True)
class RiskState:
    core: State
    pending_flat: tuple=()
    paused_until: tuple=()

    def __getattr__(self,name):
        return getattr(self.core,name)


def decision_v2(history,at,equity,*,base_protocol_sha256,semantics_sha256,**kwargs):
    verify_v2(base_protocol_sha256,semantics_sha256)
    return RiskDecision(daily_decision(history,at,equity,base_protocol_sha256=BASE_SHA,
                                      semantics_sha256=SEMANTICS_SHA,**kwargs))


def advance_v2(state,*,base_protocol_sha256,semantics_sha256,decision=None,**kwargs):
    verify_v2(base_protocol_sha256,semantics_sha256)
    at=utc(kwargs['at'])
    actual={p:dec(kwargs['actual_quantities'][p]) for p in PAIRS}
    prices={p:dec(kwargs['opens'][p]) for p in PAIRS}
    eq=dec(kwargs['equity'])
    pending=dict(state.pending_flat);paused=dict(state.paused_until)
    events=[]
    for pair,requested in list(pending.items()):
        receipt=kwargs['flat_confirmed_at'].get(pair)
        if actual[pair]==0 and receipt is not None and requested<=utc(receipt)<=at:
            paused[pair]=receipt.replace(hour=0,minute=0,second=0,microsecond=0)+timedelta(days=1)
            del pending[pair]
            events.append(dict(pair=pair,event='ACTUAL_FLAT_CONFIRMED',receipt=receipt.isoformat(),pause_until=paused[pair].isoformat()))
    inner=None
    if decision is not None:
        if not isinstance(decision,RiskDecision) or decision.semantics_sha256!=V2_SHA:
            raise CausalError('v2 decision envelope required')
        inner=decision.inner
        if inner.at.hour or inner.at.minute or inner.at.second or inner.at.microsecond:
            raise CausalError("v2 resume requires UTC daily boundary")
        for pair,boundary in list(paused.items()):
            if at>=boundary and inner.at==at:
                del paused[pair]
                events.append(dict(pair=pair,event='RESUME_AT_FRESH_DAILY_BOUNDARY'))
        inner=replace(inner,entries=tuple(e for e in inner.entries if e.pair not in pending and e.pair not in paused))
    core,out=advance(state.core,base_protocol_sha256=BASE_SHA,semantics_sha256=SEMANTICS_SHA,decision=inner,**kwargs)
    targets=dict(out['target_quantities'])
    risk=out['risk_target_quantities']
    actual_total=sum(abs(actual[p])*prices[p] for p in PAIRS)
    planned_total=sum(abs(targets[p])*prices[p] for p in PAIRS)
    actual_hard=actual_total>eq*Decimal('.8') or any(abs(actual[p])*prices[p]>eq*Decimal('.4') for p in PAIRS)
    for p in paused:
        if actual[p]!=0:
            pending.setdefault(p,at)
    selected=[]
    if actual_hard:
        for p in PAIRS:
            needs_reduction=abs(actual[p])>abs(risk[p])
            still_excess=abs(targets[p])*prices[p]>eq*Decimal('.4') or planned_total>eq*Decimal('.8')
            if needs_reduction and still_excess:
                selected.append(p)
                pending.setdefault(p,at)
    blocked=[]
    for p in PAIRS:
        if p in pending:
            # No rounding up or waiver: exact actual full quantity must pass
            # every frozen order limit. A target is never a flat receipt.
            delta=executable_quantity(-actual[p],prices[p],**kwargs['rules'][p])
            legal=actual[p]!=0 and delta==-actual[p]
            targets[p]=Decimal(0) if legal else actual[p]
            if not legal: blocked.append(p)
            events.append(dict(pair=p,event='FULL_REDUCE_ONLY_INTENT' if legal else 'BLOCKED_FULL_EXIT',
                               trigger='HARD_CAP' if p in selected else 'PENDING_ACTUAL_FLAT',
                               actual_quantity=str(actual[p]),delta=str(delta),reduce_only=True))
        elif p in paused:
            targets[p]=Decimal(0)
    if blocked:
        # No new risk anywhere while a mandatory liquidation is unexecutable.
        for p in PAIRS:
            if targets[p]*actual[p]<=0: targets[p]=Decimal(0) if actual[p]==0 else targets[p]
            elif abs(targets[p])>abs(actual[p]): targets[p]=actual[p]
    unresolved=tuple(p for p in out['unexecutable_reductions'] if p not in pending or p in blocked)
    return RiskState(core,tuple(pending.items()),tuple(paused.items())),{
        **out,'target_quantities':targets,'semantics_sha256':V2_SHA,
        'v1_unexecutable_reductions':out['unexecutable_reductions'],
        'unexecutable_reductions':unresolved,'hard_cap_fallback':events,
        'pending_actual_flat':tuple(pending),'paused_assets':tuple(paused),
        'blocked_assets':tuple(blocked),'market_execution_allowed':False}
