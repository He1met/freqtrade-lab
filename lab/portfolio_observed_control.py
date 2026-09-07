"""00 frozen intentions, 01 bounded activation, existing V2 exits every hour."""
from dataclasses import dataclass,replace
from datetime import timedelta
from decimal import Decimal,localcontext
from lab.portfolio_causal import State,Episode,PAIRS,BASE_SHA
from lab.portfolio_risk_v2 import RiskState,RiskDecision,V2_SHA,decision_v2,advance_v2
from lab.portfolio_execution import capped_targets,executable_quantity,dec
from lab.portfolio_short import reserve_additions,configuration
from lab.portfolio_source import SourceError
from lab.portfolio_observed_money import decimal


@dataclass(frozen=True)
class ObservedState:
    risk:RiskState
    pending:tuple=()
    equity00:Decimal=Decimal(1000)
    pending_at:object=None


def advance_observed(state,view,at,equity,free_cash,actual,rules,flat,config,ledger):
    with localcontext() as context:
        context.prec=60
        return _advance_observed(state,view,at,equity,free_cash,actual,rules,flat,config,ledger)


def _advance_observed(state,view,at,equity,free_cash,actual,rules,flat,config,ledger):
    completed,opens,marks=view.known(at)
    core=replace(state.risk.core,peak=max(state.risk.peak,decimal(ledger.peak)),
                 warning=state.risk.warning or ledger.warning,halted=state.risk.halted or ledger.halted)
    risk=replace(state.risk,core=core)
    daily=None;pending=state.pending;eq00=state.equity00;pending_at=state.pending_at
    if at.hour==0 and at>=view.start:
        daily=decision_v2(view.daily,at,equity,mode=core.mode,selection=config['selection'],base_protocol_sha256=BASE_SHA,semantics_sha256=V2_SHA)
        pending=daily.inner.entries;eq00=dec(equity);pending_at=at
        # Existing-family daily exits, aging, C and V2 resume are still processed.
        daily=RiskDecision(replace(daily.inner,entries=()))
    with localcontext() as context:
        context.prec=60
        risk,out=advance_v2(risk,at=at,opens=opens,completed=completed,actual_quantities=actual,
                            equity=equity,free_cash=free_cash,rules=rules,flat_confirmed_at=flat,
                            decision=daily,stress=config['fee']=='0.0012',
                            base_protocol_sha256=BASE_SHA,semantics_sha256=V2_SHA)
    if at.hour==0:
        occupied={(e.entry.pair,e.entry.family) for e in risk.episodes}
        exited={(p,f) for p,f,_ in out['family_exits']}
        cooldown=dict(risk.cooldowns)
        pending=tuple(e for e in pending if (e.pair,e.family) not in occupied|exited and
                      at>=cooldown.get((e.pair,e.family),at) and e.pair not in dict(risk.pending_flat) and e.pair not in dict(risk.paused_until))
    activated=[]
    if at.hour==1 and pending_at==at-timedelta(hours=1):
        active=list(risk.episodes);occupied={(e.entry.pair,e.entry.family) for e in active}
        blocked=set(dict(risk.pending_flat))|set(dict(risk.paused_until))
        if not risk.halted and risk.complete_checks==3:
            for e in pending:
                if e.pair in blocked or (e.pair,e.family) in occupied:continue
                if e.target is not None and (e.target-dec(opens[e.pair]))*e.direction<=0:continue
                units=min(e.units,e.units*min(Decimal(1),dec(equity)/eq00))
                if units<=0:continue
                entry=replace(e,units=units);price=dec(opens[e.pair]);stop=price-e.direction*e.distance
                if stop<=0:continue
                active.append(Episode(entry,at,price,stop,at+timedelta(days=42 if e.family=='trend' else 5)))
                activated.append(dict(pair=e.pair,family=e.family,frozen_units=e.units,activated_units=units,started=at))
        pending=();pending_at=None
        risk=replace(risk,core=replace(risk.core,episodes=tuple(active)))
        families=[{e.entry.pair:e.entry.direction*e.entry.units*(dict(risk.multipliers).get(e.entry.pair,Decimal(0)) if core.mode=='C' else Decimal(1))} for e in risk.episodes]
        scale=(Decimal('.5') if core.mode=='half-risk-B' else Decimal(1))*(Decimal('.5') if risk.warning else Decimal(1))
        targets=capped_targets(families,opens,equity,scale)
    else:targets=dict(out['target_quantities'])
    blocked=set(out['pending_actual_flat'])|set(out['paused_assets'])
    for p in PAIRS:
        if p in blocked or risk.halted:targets[p]=out['target_quantities'][p]
        if targets[p]*actual[p]<0:targets[p]=Decimal(0)
        if actual[p]==0 and targets[p] and (p not in flat or flat[p]>=at):targets[p]=Decimal(0)
        if at.hour in (0,8,16) and abs(targets[p])>abs(actual[p]):targets[p]=actual[p]
    if at==view.end-timedelta(hours=1):targets={p:Decimal(0) for p in PAIRS}
    # Reserve new costs against actual (not an assumed reduction fill). If any
    # reduction is required, do it first and defer ALL additions to a later hour.
    reductions=any(abs(targets[p])<abs(actual[p]) for p in PAIRS)
    if reductions:
        for p in PAIRS:
            if abs(targets[p])>abs(actual[p]):targets[p]=actual[p]
    elif any(abs(targets[p])>abs(actual[p]) for p in PAIRS):
        targets=reserve_additions(equity,actual,targets,opens,{p:rules[p]['step'] for p in PAIRS},config)
        need=sum(max(Decimal(0),abs(targets[p])-abs(actual[p]))*dec(opens[p])*(1+dec(config['fee'])+dec(config['slippage'])) for p in PAIRS)
        if need>dec(free_cash):
            ratio=max(Decimal(0),dec(free_cash))/need
            targets={p:actual[p]+(targets[p]-actual[p])*ratio for p in PAIRS}
    blocked_exit=[]
    for p in PAIRS:
        delta=executable_quantity(targets[p]-actual[p],opens[p],**rules[p])
        targets[p]=actual[p]+delta
        if at==view.end-timedelta(hours=1) and targets[p]!=0:blocked_exit.append(p)
    return ObservedState(risk,pending,eq00,pending_at),{**out,'target_quantities':targets,'activated':activated,
          'frozen_at':pending_at,'blocked_final_exit':blocked_exit,'model':'SIMULATED_UNDER_ASSUMPTIONS'}
