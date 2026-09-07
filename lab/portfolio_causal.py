"""Causal, protocol-bound family intentions. No fills, PnL, networking or engine.

Daily decisions use only closed bars. Executable net positions and settled cash
must come from a separately verified execution consumer, never this model.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import math
from statistics import mean, median, stdev

from lab.portfolio_preflight import load_protocol, _validate_protocol
from lab.portfolio_execution import dec


class CausalError(ValueError):
    pass


def utc(value):
    if not isinstance(value,datetime) or value.utcoffset()!=timedelta(0):
        raise CausalError("explicit UTC timestamp required")
    return value


@dataclass(frozen=True)
class PriceBar:
    closed_at: datetime
    open: float
    high: float
    low: float
    close: float


@dataclass(frozen=True)
class Indicators:
    closed_at: datetime
    count: int
    close: float
    atr20: float | None
    trend_direction: int
    exit_lower: float | None
    exit_upper: float | None
    reversal_z: float | None
    reversal_direction: int
    reversal_target: float | None
    sigma20: float | None
    raw_multiplier: float | None


def valid_bar(bar, *, daily):
    utc(bar.closed_at)
    if bar.closed_at.minute or bar.closed_at.second or bar.closed_at.microsecond or (daily and bar.closed_at.hour):
        raise CausalError("bar must close on exact UTC boundary")
    values=(bar.open,bar.high,bar.low,bar.close)
    if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or v<=0 for v in values):
        raise CausalError("OHLC must be positive finite numbers")
    if not bar.low<=min(bar.open,bar.close)<=max(bar.open,bar.close)<=bar.high:
        raise CausalError("invalid OHLC ordering")


def indicators(bars, at, *, trend_lookback=63, reversal_threshold="2", protocol=None):
    protocol=load_protocol() if protocol is None else protocol
    _validate_protocol(protocol); utc(at)
    params=protocol["signals"]
    if type(trend_lookback) is not int or trend_lookback not in params["trend_lookbacks"] or reversal_threshold not in params["reversal_thresholds"]:
        raise CausalError("signal version outside frozen six versions")
    # Future price values are not touched or validated. Their timestamps only
    # determine whether a bar was closed and available at this decision time.
    closed=[b for b in bars if utc(b.closed_at)<=at]
    if not closed: raise CausalError("no closed daily observations")
    for index,bar in enumerate(closed):
        valid_bar(bar,daily=True)
        if index and bar.closed_at-closed[index-1].closed_at!=timedelta(days=1):
            raise CausalError("daily history unordered, duplicated or discontinuous")
    prices=[b.close for b in closed]
    returns=[None]+[math.log(prices[i]/prices[i-1]) for i in range(1,len(prices))]
    i=len(prices)-1
    atr=None
    if i>=20:
        atr=mean(max(closed[j].high-closed[j].low,abs(closed[j].high-prices[j-1]),abs(closed[j].low-prices[j-1])) for j in range(i-19,i+1))
    direction=0
    if i>=trend_lookback:
        history=prices[i-trend_lookback:i]
        direction=1 if prices[i]>max(history) else (-1 if prices[i]<min(history) else 0)
    lower=min(prices[i-21:i]) if i>=21 else None
    upper=max(prices[i-21:i]) if i>=21 else None
    z=None
    if i>=61:
        previous_vol=stdev(returns[i-60:i])
        if previous_vol>0: z=math.log(prices[i]/prices[i-3])/(previous_vol*math.sqrt(3))
    reverse=0 if z is None or abs(z)<float(reversal_threshold) else (-1 if z>0 else 1)
    vol=stdev(returns[i-19:i+1]) if i>=20 else None
    raw=None
    if i>=272 and vol is not None and vol>0:
        prior=[stdev(returns[j-19:j+1]) for j in range(i-252,i)]
        raw=min(1.,median(prior)/vol)
    return Indicators(closed[-1].closed_at,len(closed),prices[-1],atr,direction,lower,upper,z,reverse,
                      mean(prices[-5:]) if i>=4 else None,vol,raw)


def consumer_costs(*, protocol=None, stress=False, known_taker=None):
    protocol=load_protocol() if protocol is None else protocol
    _validate_protocol(protocol)
    if type(stress) is not bool: raise CausalError("stress must be explicit boolean")
    cost=protocol["cost"]
    fee=dec(cost["taker_rate_each_side"])
    if known_taker is not None and dec(known_taker)<0:
        raise CausalError("negative known Taker")
    if known_taker is not None and dec(known_taker)>fee:
        raise CausalError("known applicable Taker is higher: refreeze before scoring")
    factor=dec(cost["stress_multiplier"]) if stress else Decimal(1)
    return {"native_fee_each_side":str(fee*factor),
            "audit_slippage_each_side":str(dec(cost["slippage_rate_each_side"])*factor),
            "funding":cost["funding"],"funding_boundary_status":"UNVERIFIED",
            "native_inclusive_endpoints_are_settlement_authority":False,
            "settlement_precision":cost["settlement_precision"],"economic_result":None}


# Both immutable contracts are required at the consumer boundary. The original
# budget remains anchored to the base; this module cannot reserve native calls.
BASE_SHA = "e664b6447879a350663fa7940036a2682d3970af65f7c218c540e2e62ff28e85"
SEMANTICS_SHA = "5fb7ee5d01920eaa91eafd936569c6c7a15fbdf5708c16162fd49537d8b7848a"
PAIRS = ("BTC/USDT:USDT", "ETH/USDT:USDT")
MODES = ("A-trend", "A-reversal", "B", "C", "half-risk-B")


def verify_binding(base_protocol_sha256, semantics_sha256):
    from hashlib import sha256
    from pathlib import Path
    if (base_protocol_sha256, semantics_sha256) != (BASE_SHA, SEMANTICS_SHA):
        raise CausalError("missing or mismatched dual protocol binding")
    root = Path(__file__).resolve().parents[1] / "docs/protocols"
    for filename, expected in (("btc-eth-portfolio-v1.json", BASE_SHA),
                               ("btc-eth-portfolio-semantics-v1.json", SEMANTICS_SHA)):
        if sha256((root / filename).read_bytes()).hexdigest() != expected:
            raise CausalError("contract bytes changed: explicit refreeze required")


@dataclass(frozen=True)
class Entry:
    pair: str
    family: str
    direction: int
    units: Decimal
    distance: Decimal
    target: Decimal | None


@dataclass(frozen=True)
class Decision:
    at: datetime
    mode: str
    snapshots: tuple
    entries: tuple[Entry, ...]
    base_protocol_sha256: str
    semantics_sha256: str


def daily_decision(history, at, equity, *, mode, selection,
                   base_protocol_sha256, semantics_sha256):
    """Selection is an externally frozen training choice, never inferred here.

    None means cash for that family. Quantities have no execution-open input.
    """
    verify_binding(base_protocol_sha256, semantics_sha256)
    utc(at)
    if at.hour or at.minute or at.second or at.microsecond or mode not in MODES:
        raise CausalError("invalid daily decision boundary or mode")
    if set(history) != set(PAIRS) or set(selection) != {"trend", "reversal"}:
        raise CausalError("exact pair and family coverage required")
    eq = dec(equity)
    if eq <= 0: raise CausalError("positive decision equity required")
    trend, reversal = selection["trend"], selection["reversal"]
    if trend is not None and (type(trend) is not int or trend not in (42,63,84)):
        raise CausalError("invalid selected trend")
    if reversal is not None and reversal not in ("1.5","2","2.5"):
        raise CausalError("invalid selected reversal")
    entries, snapshots = [], []
    for pair in PAIRS:
        snap = indicators(history[pair], at, trend_lookback=trend or 63,
                          reversal_threshold=reversal or "2")
        if snap.closed_at != at or snap.count < 274:
            raise CausalError("fresh daily close and full warmup required")
        snapshots.append((pair,snap))
        for family, selected, direction, distance in (
            ("trend",trend,snap.trend_direction,3),
            ("reversal",reversal,snap.reversal_direction,2)):
            if selected is None or (mode.startswith("A-") and mode != "A-"+family): continue
            if not direction or snap.atr20 is None or snap.atr20 <= 0: continue
            stop_distance = dec(snap.atr20)*distance
            risk = Decimal("0.01") if mode.startswith("A-") else Decimal("0.005")
            entries.append(Entry(pair,family,direction,eq*risk/stop_distance,stop_distance,
                                 dec(snap.reversal_target) if family=="reversal" else None))
    return Decision(at,mode,tuple(snapshots),tuple(entries),base_protocol_sha256,semantics_sha256)


@dataclass(frozen=True)
class Episode:
    entry: Entry
    started: datetime
    reference: Decimal
    stop: Decimal
    expires: datetime


@dataclass(frozen=True)
class State:
    mode: str
    episodes: tuple = ()
    cooldowns: tuple = ()
    multipliers: tuple = ()
    last_at: datetime | None = None
    last_daily: datetime | None = None
    peak: Decimal = Decimal("1000")
    warning: bool = False
    halted: bool = False
    complete_checks: int = 3
    max_drawdown: Decimal = Decimal(0)


def advance(state, *, at, opens, completed, actual_quantities, equity, free_cash,
            rules, flat_confirmed_at, base_protocol_sha256, semantics_sha256,
            decision=None, data_complete=True, stress=False):
    """Pure hourly transition: return immutable state and net target intentions.

    No actual position, fill, funding or economic evidence is manufactured.
    Caller supplies known snapshots and actual exchange precision/minimum rules.
    """
    from lab.portfolio_execution import capped_targets, executable_quantity
    verify_binding(base_protocol_sha256, semantics_sha256)
    costs=consumer_costs(stress=stress)
    utc(at)
    if state.mode not in MODES or at.minute or at.second or at.microsecond:
        raise CausalError("invalid hourly boundary or mode")
    if state.last_at is not None and at <= state.last_at:
        raise CausalError("nonincreasing execution timestamp")
    if type(data_complete) is not bool: raise CausalError("explicit completeness required")
    if any(set(mapping)!=set(PAIRS) for mapping in (opens,completed,actual_quantities,rules)):
        raise CausalError("exact pair coverage required")
    prices={p:dec(opens[p]) for p in PAIRS}
    actual={p:dec(actual_quantities[p]) for p in PAIRS}
    eq,cash=dec(equity),dec(free_cash)
    if eq<0 or cash<0 or any(p<=0 for p in prices.values()):
        raise CausalError("invalid equity/cash/open")
    for p in PAIRS:
        valid_bar(completed[p],daily=False)
        if completed[p].closed_at!=at: raise CausalError("stale or future completed hour")
        rule=rules[p]
        if set(rule)!={"step","min_qty","min_notional","max_qty"}:
            raise CausalError("complete execution rules required")
        if any(dec(v)<0 for v in rule.values()) or dec(rule["step"])<=0 or dec(rule["max_qty"])<=0:
            raise CausalError("invalid execution rules")
    for p,timestamp in flat_confirmed_at.items():
        if p not in PAIRS or utc(timestamp)>at: raise CausalError("invalid flat receipt time")
    snapshots={}
    if decision is not None:
        if (decision.at!=at or decision.mode!=state.mode or state.last_daily==at or
            (decision.base_protocol_sha256,decision.semantics_sha256)!=(BASE_SHA,SEMANTICS_SHA)):
            raise CausalError("late, duplicate or mismatched daily decision")
        snapshots=dict(decision.snapshots)
        if set(snapshots)!=set(PAIRS) or any(s.closed_at!=at or s.count<274 for s in snapshots.values()):
            raise CausalError("invalid daily snapshots")
        seen=set()
        for e in decision.entries:
            key=(e.pair,e.family)
            if (key in seen or e.pair not in PAIRS or e.family not in ("trend","reversal") or
                type(e.direction) is not int or e.direction not in (-1,1) or
                dec(e.units)<=0 or dec(e.distance)<=0 or
                (e.family=="reversal" and (e.target is None or dec(e.target)<=0)) or
                (state.mode.startswith("A-") and state.mode!="A-"+e.family)):
                raise CausalError("invalid entry intention")
            seen.add(key)
    peak=max(state.peak,eq)
    dd=1-eq/peak
    max_dd=max(state.max_drawdown,dd)
    warning=state.warning or dd>=Decimal("0.10")
    halted=state.halted or dd>=Decimal("0.15")
    consecutive = state.last_at is None or at-state.last_at==timedelta(hours=1)
    checks=min(3,state.complete_checks+1) if data_complete and consecutive else 0
    cooldown=dict(state.cooldowns)
    multipliers=dict(state.multipliers)
    if decision is not None:
        for pair,snap in decision.snapshots:
            raw=Decimal(0) if snap.raw_multiplier is None else dec(snap.raw_multiplier)
            multipliers[pair]=min(raw,multipliers[pair]+Decimal("0.1")) if pair in multipliers else raw
    active,exits=[],[]
    for episode in state.episodes:
        e=episode.entry
        bar=completed[e.pair]
        stopped=(dec(bar.low)<=episode.stop or prices[e.pair]<=episode.stop) if e.direction==1 else (dec(bar.high)>=episode.stop or prices[e.pair]>=episode.stop)
        # Never inspect the completed bar preceding this episode's activation.
        if episode.started>=at: raise CausalError("episode starts in current/future hour")
        snap=snapshots.get(e.pair)
        signal_exit=False
        if snap:
            if e.family=="trend":
                bound=snap.exit_lower if e.direction==1 else snap.exit_upper
                signal_exit=bound is not None and (snap.close<bound if e.direction==1 else snap.close>bound)
            else:
                signal_exit=dec(snap.close)>=e.target if e.direction==1 else dec(snap.close)<=e.target
        if stopped or at>=episode.expires or signal_exit or halted:
            exits.append((e.pair,e.family,"stop" if stopped else "halt" if halted else "expiry" if at>=episode.expires else "signal"))
            if stopped:
                midnight=at.replace(hour=0)
                cooldown[(e.pair,e.family)]=midnight+timedelta(days=1 if at==midnight else 2)
        else: active.append(episode)
    exited={(p,f) for p,f,_ in exits}
    occupied={(x.entry.pair,x.entry.family) for x in active}
    if decision is not None and not halted and checks==3:
        for e in decision.entries:
            key=(e.pair,e.family)
            if key in occupied or key in exited or (key in cooldown and at<cooldown[key]): continue
            price=prices[e.pair]
            if e.target is not None and (e.target-price)*e.direction<=0: continue
            stop=price-e.direction*e.distance
            if stop<=0: continue
            active.append(Episode(e,at,price,stop,at+timedelta(days=42 if e.family=="trend" else 5)))
    families=[]
    for episode in active:
        e=episode.entry
        mult=multipliers.get(e.pair,Decimal(0)) if state.mode=="C" else Decimal(1)
        families.append({e.pair:e.direction*e.units*mult})
    scale=(Decimal("0.5") if state.mode=="half-risk-B" else Decimal(1))*(Decimal("0.5") if warning else Decimal(1))
    targets=capped_targets(families,prices,eq,scale)
    for p in PAIRS:
        target,current=targets[p],actual[p]
        if halted: target=Decimal(0)
        elif target*current<0: target=Decimal(0)
        elif current==0 and target and (p not in flat_confirmed_at or flat_confirmed_at[p]>=at):
            target=Decimal(0)
        if checks<3:
            target=min(abs(target),abs(current))*(1 if current>0 else -1) if target*current>0 else Decimal(0)
        targets[p]=target
    additions={p:max(Decimal(0),abs(targets[p])-abs(actual[p])) for p in PAIRS}
    reserve=1+dec(costs["native_fee_each_side"])+dec(costs["audit_slippage_each_side"])
    required=sum(additions[p]*prices[p]*reserve for p in PAIRS)
    cash_scale=min(Decimal(1),cash/required) if required else Decimal(1)
    intended=dict(targets)
    for p in PAIRS:
        target=targets[p]
        if additions[p]: target=(abs(actual[p])+additions[p]*cash_scale)*(1 if target>0 else -1)
        # Minimum rules apply to the change/order, not the whole held position.
        delta=target-actual[p]
        executable=executable_quantity(delta,prices[p],**rules[p])
        targets[p]=actual[p]+executable
    next_state=State(state.mode,tuple(active),tuple(cooldown.items()),tuple(multipliers.items()),at,
                     at if decision is not None else state.last_daily,peak,warning,halted,checks,max_dd)
    return next_state,{"target_quantities":targets,"family_exits":tuple(exits),
                       "actual_quantities":actual,"risk_target_quantities":intended,
                       "unexecutable_reductions":tuple(p for p in PAIRS if abs(targets[p])>abs(intended[p])),
                       "market_execution_allowed":False,
                       "max_drawdown":max_dd,"risk_limit_passed":max_dd<=Decimal("0.20"),
                       "native_stop_routing":"BLOCKED_UNVERIFIED","economic_result":None,
                       "costs":costs,"base_protocol_sha256":BASE_SHA,
                       "semantics_sha256":SEMANTICS_SHA}
