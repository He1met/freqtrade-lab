"""Conservative audit of native 1x, single-position Binance funding accounting.

This consumes native trades; it does not generate signals, fills, or artifacts.
The native result is preserved. A separate pessimistic cost/equity projection
decides eligibility, including uncertain event membership at entry/exit.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

CONTRACT = "BINANCE_ASSOCIATED_MARK_BOUNDARY_V1"
BOUNDARY_MS = 60_000
HOUR_MS = 3_600_000


class FuturesCostError(ValueError):
    pass


def number(value: Any, name: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise FuturesCostError(f"{name} is not numeric")
    try:
        result = float(value)
    except (ValueError, OverflowError) as exc:
        raise FuturesCostError(f"{name} is not numeric") from exc
    if not math.isfinite(result) or (positive and result <= 0):
        raise FuturesCostError(f"{name} is not finite/positive")
    return result


def timestamp(value: Any) -> int:
    if not isinstance(value, str):
        raise FuturesCostError("trade timestamp must be explicit UTC")
    try:
        date = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise FuturesCostError("trade timestamp invalid") from exc
    if date.utcoffset() != timezone.utc.utcoffset(date):
        raise FuturesCostError("trade timestamp must be UTC")
    return int(date.timestamp() * 1000)


def validate_events(
    events: Sequence[Mapping[str, Any]], marks: Sequence[Sequence[Any]],
    *, symbol: str, start_ms: int, end_ms: int,
) -> tuple[list[dict[str, Any]], dict[int, tuple[float, float, float, float]]]:
    """Scoring events require final fee marks; indicator prehistory does not."""
    candles: dict[int, tuple[float, float, float, float]] = {}
    for row in marks:
        if len(row) < 5 or isinstance(row[0], bool) or not isinstance(row[0], int):
            raise FuturesCostError("mark candle shape invalid")
        t = row[0]
        o, h, l, c = [number(v, "mark OHLC", positive=True) for v in row[1:5]]
        if t % HOUR_MS or t in candles or not l <= min(o, c) <= max(o, c) <= h:
            raise FuturesCostError("mark date/OHLC invalid")
        candles[t] = (o, h, l, c)
    required_hours = list(range(start_ms // HOUR_MS * HOUR_MS, end_ms, HOUR_MS))
    if any(t not in candles for t in required_hours):
        raise FuturesCostError("mark history incomplete")
    normalized = []
    previous = -1
    buckets: set[int] = set()
    for raw in events:
        t = raw.get("fundingTime")
        if isinstance(t, bool) or not isinstance(t, int) or t <= previous:
            raise FuturesCostError("funding events unordered or duplicated")
        previous = t
        if raw.get("symbol") != symbol or raw.get("rateType", "Regular") != "Regular":
            raise FuturesCostError("funding source identity/type mismatch")
        if not start_ms <= t < end_ms:
            continue
        bucket = t // BOUNDARY_MS * BOUNDARY_MS
        if bucket in buckets or bucket % (8 * HOUR_MS) or bucket not in candles:
            raise FuturesCostError("funding/native mark mapping is not one-to-one")
        buckets.add(bucket)
        rate = number(raw.get("fundingRate"), "settled funding rate")
        associated = number(raw.get("markPrice"), "associated settlement mark", positive=True)
        normalized.append({"time_ms": t, "native_time_ms": bucket, "rate": rate,
                           "associated_mark": associated, "native_mark": candles[bucket][0]})
    expected = set(range(start_ms, end_ms, 8 * HOUR_MS))
    if buckets != expected:
        raise FuturesCostError("scoring funding event calendar incomplete")
    return normalized, candles


def audit_native_trades(
    trades: Sequence[Mapping[str, Any]], events: Sequence[Mapping[str, Any]],
    marks: Sequence[Sequence[Any]], *, symbol: str, start_ms: int,
    end_ms: int, starting_balance: float,
) -> dict[str, Any]:
    """Audit native fills with adverse funding and intrahour MTM risk.

    A one-minute boundary is the existing native timestamp bucket, not a
    data-fitted tolerance. At an uncertain boundary, a debit is included and
    a credit excluded. For interior events, use the worse of native/exact
    associated-mark cash flows. This never adds favorable corrections.
    Normal MTM uses confirmed full-hour close observations within positions,
    entry cost and native exit fills. An independently labelled high/low
    ordering stress is supplemental and never replaces the normal DD gate.
    """
    funding, candles = validate_events(events, marks, symbol=symbol,
                                      start_ms=start_ms, end_ms=end_ms)
    initial = number(starting_balance, "starting balance", positive=True)
    wallet, peak, max_dd, total_penalty = initial, initial, 0.0, 0.0
    stress_peak, stress_dd = initial, 0.0
    min_free = initial
    previous_close = start_ms
    details: list[dict[str, Any]] = []
    for trade in trades:
        opened, closed = timestamp(trade.get("open_date")), timestamp(trade.get("close_date"))
        if not start_ms <= opened <= closed < end_ms or opened < previous_close:
            raise FuturesCostError("native trades overlap or escape scoring window")
        previous_close = closed
        if trade.get("pair") != symbol.replace("USDT", "/USDT:USDT", 1):
            raise FuturesCostError("native trade pair mismatch")
        if not isinstance(trade.get("is_short"), bool) or number(trade.get("leverage"), "leverage") != 1:
            raise FuturesCostError("only explicit direction and 1x supported")
        side = -1 if trade["is_short"] else 1
        amount = number(trade.get("amount"), "amount", positive=True)
        op = number(trade.get("open_rate"), "open rate", positive=True)
        cp = number(trade.get("close_rate"), "close rate", positive=True)
        fee_open = number(trade.get("fee_open"), "entry fee")
        fee_close = number(trade.get("fee_close"), "exit fee")
        if min(fee_open, fee_close) < 0:
            raise FuturesCostError("negative trading fee unsupported")
        entry_cost, exit_cost = amount * op * fee_open, amount * cp * fee_close
        stake = number(trade.get("stake_amount"), "stake", positive=True)
        if not math.isclose(stake, amount * op, rel_tol=1e-7, abs_tol=1e-7):
            raise FuturesCostError("native stake does not bind 1x exposure")
        flows: list[tuple[int, float, float]] = []
        native_sum, penalty = 0.0, 0.0
        for event in funding:
            t, bucket = event["time_ms"], event["native_time_ms"]
            native = -side * event["rate"] * event["native_mark"] * amount if opened <= bucket <= closed else 0.0
            native_sum += native
            if not opened - BOUNDARY_MS <= t <= closed + BOUNDARY_MS:
                continue
            exact = -side * event["rate"] * event["associated_mark"] * amount
            boundary = abs(t - opened) <= BOUNDARY_MS or abs(t - closed) <= BOUNDARY_MS
            conservative = min(native, exact, 0.0) if boundary else min(native, exact)
            deduction = native - conservative
            if deduction < -1e-12:
                raise FuturesCostError("conservative adjustment increased cash")
            penalty += deduction
            flows.append((min(max(bucket, opened), closed), native, deduction))
        stated_funding = number(trade.get("funding_fees"), "native funding fees")
        if opened == closed and stated_funding == 0 and native_sum != 0:
            # A native same-bar stop may never accrue funding. Preserve its
            # zero flow, but retain any possible boundary debit conservatively.
            flows = [(t, 0.0, max(0.0, d-n)) for t,n,d in flows]
            penalty = sum(d for _,_,d in flows)
            native_sum = 0.0
        native_profit = number(trade.get("profit_abs"), "native profit")
        calculated = side * (cp-op)*amount-entry_cost-exit_cost+native_sum
        if not math.isclose(native_sum, stated_funding, rel_tol=1e-7, abs_tol=1e-7):
            raise FuturesCostError("native funding does not reconcile with source events")
        if not math.isclose(calculated, native_profit, rel_tol=1e-7, abs_tol=1e-6):
            raise FuturesCostError("native trade profit does not reconcile with fills/fees")
        cash = wallet-entry_cost
        min_free = min(min_free, cash-stake)
        max_dd = max(max_dd,(peak-cash)/peak)
        flow_index = 0
        flows.sort(key=lambda item:item[0])
        for hour in range(opened//HOUR_MS*HOUR_MS, closed, HOUR_MS):
            if hour not in candles:
                raise FuturesCostError("position MTM mark unavailable")
            _, high, low, mark_close = candles[hour]
            point = min(hour+HOUR_MS,closed)
            while flow_index < len(flows) and flows[flow_index][0] <= point:
                _,n,d=flows[flow_index]
                cash += n-d
                min_free = min(min_free,cash-stake)
                flow_index += 1
            # Only a wholly held bar supplies an unambiguous normal mark
            # observation. At exit use the native fill, below.
            if hour >= opened and point < closed:
                equity=cash+side*(mark_close-op)*amount-mark_close*amount*fee_close
                peak=max(peak,equity)
                max_dd=max(max_dd,(peak-equity)/peak)
            favorable = high if side == 1 else low
            adverse = low if side == 1 else high
            # Reserve eventual exit fee at the observed adverse/favorable mark.
            best = cash+side*(favorable-op)*amount-favorable*amount*fee_close
            worst = cash+side*(adverse-op)*amount-adverse*amount*fee_close
            stress_peak = max(stress_peak,best)
            stress_dd = max(stress_dd,(stress_peak-worst)/stress_peak)
        # Includes same-bar stops and flows precisely at close, before margin
        # release. Do not defer a cash shortfall until final wallet balance.
        while flow_index < len(flows):
            _,n,d=flows[flow_index]
            cash += n-d
            min_free=min(min_free,cash-stake)
            flow_index += 1
        wallet += native_profit-penalty
        total_penalty += penalty
        peak = max(peak,wallet)
        max_dd = max(max_dd,(peak-wallet)/peak)
        min_free = min(min_free,wallet)
        details.append({"open_date":trade["open_date"],"close_date":trade["close_date"],
                        "native_profit_abs":native_profit,"funding_deduction_abs":penalty,
                        "conservative_profit_abs":native_profit-penalty})
    adjusted=[d["conservative_profit_abs"] for d in details]
    gains=sum(max(v,0) for v in adjusted)
    losses=-sum(min(v,0) for v in adjusted)
    return {"contract":CONTRACT,"native_artifact_unchanged":True,
            "funding_deduction_abs":total_penalty,"conservative_final_balance":wallet,
            "conservative_net_profit_pct":(wallet/initial-1)*100,
            "conservative_mtm_drawdown_pct":max_dd*100,
            "intrahour_ordering_stress_drawdown_pct":stress_dd*100,
            "minimum_free_cash":min_free,"cash_executable":min_free>=0,
            "conservative_profit_factor":gains/losses if losses else None,
            "conservative_loss_count":sum(v<0 for v in adjusted),
            "trade_adjustments":details,
            "risk_model":"confirmed hourly close observations plus fills/costs; partial bars omitted; not continuous MTM",
            "supplemental_stress":"hourly favorable-before-adverse extrema, includes partial-bar risk; not normal DD or native Holdout Stress"}


def audit_from_source(result: Mapping[str, Any], source: Mapping[str, Any], data_dir: Any,
                      timerange: str) -> dict[str, Any]:
    import hashlib
    import json
    import pandas as pd
    from pathlib import Path
    if source.get('exchange')!='binance' or source.get('funding_model')!=CONTRACT:
        raise FuturesCostError('Binance funding audit requires frozen source model')
    start,stop=[datetime.strptime(s,'%Y%m%d').replace(tzinfo=timezone.utc) for s in timerange.split('-')]
    path=Path(data_dir)/'futures/BCH_USDT_USDT-1h-mark.feather'
    raw=path.read_bytes()
    import io
    frame=pd.read_feather(io.BytesIO(raw))
    marks=[[int(r.date.value//1_000_000),r.open,r.high,r.low,r.close] for r in frame.itertuples()]
    audit=audit_native_trades(result['trades'],source['funding_events'],marks,symbol='BCHUSDT',
        start_ms=int(start.timestamp()*1000),end_ms=int(stop.timestamp()*1000),starting_balance=result['starting_balance'])
    audit['source_events_sha256']=hashlib.sha256(json.dumps(source['funding_events'],sort_keys=True,separators=(',',':')).encode()).hexdigest()
    audit['mark_data_sha256']=hashlib.sha256(raw).hexdigest()
    audit['scoring_timerange']=timerange
    validate_audit(audit,float(result['profit_total'])*100,float(result['starting_balance']),len(result['trades']))
    return audit


def validate_audit(audit: Any, native_profit_pct: float, initial: float, trades: int) -> dict[str, Any]:
    initial=number(initial,'starting balance',positive=True)
    native_profit_pct=number(native_profit_pct,'native profit percent')
    if not isinstance(audit,dict) or audit.get('contract')!=CONTRACT or audit.get('native_artifact_unchanged') is not True:
        raise FuturesCostError('required conservative funding audit missing')
    penalty=number(audit.get('funding_deduction_abs'),'funding deduction')
    final=number(audit.get('conservative_final_balance'),'conservative balance')
    net=number(audit.get('conservative_net_profit_pct'),'conservative net')
    dd=number(audit.get('conservative_mtm_drawdown_pct'),'conservative DD')
    cash=number(audit.get('minimum_free_cash'),'conservative cash')
    rows=audit.get('trade_adjustments')
    if (penalty<0 or dd<0 or audit.get('cash_executable') is not (cash>=0)
            or not isinstance(rows,list) or len(rows)!=trades
            or not math.isclose(final,initial*(1+native_profit_pct/100)-penalty,abs_tol=1e-6)
            or not math.isclose(net,(final/initial-1)*100,abs_tol=1e-9)):
        raise FuturesCostError('funding audit does not reconcile with native result')
    native_values, deductions, adjusted_values = [], [], []
    for row in rows:
        if not isinstance(row,dict):
            raise FuturesCostError('funding audit trade row invalid')
        native=number(row.get('native_profit_abs'),'trade native profit')
        deduction=number(row.get('funding_deduction_abs'),'trade deduction')
        adjusted=number(row.get('conservative_profit_abs'),'trade conservative profit')
        if deduction<0 or not math.isclose(native-deduction,adjusted,rel_tol=1e-9,abs_tol=1e-6):
            raise FuturesCostError('funding audit trade does not reconcile')
        native_values.append(native)
        deductions.append(deduction)
        adjusted_values.append(adjusted)
    if (not math.isclose(math.fsum(deductions),penalty,rel_tol=1e-9,abs_tol=1e-6)
            or not math.isclose(math.fsum(native_values),initial*native_profit_pct/100,rel_tol=1e-9,abs_tol=1e-6)
            or not math.isclose(initial+math.fsum(adjusted_values),final,rel_tol=1e-9,abs_tol=1e-6)):
        raise FuturesCostError('funding audit trade totals do not reconcile')
    loss_count=sum(value<0 for value in adjusted_values)
    stated_count=audit.get('conservative_loss_count')
    if type(stated_count) is not int or stated_count!=loss_count:
        raise FuturesCostError('funding audit loss count does not reconcile')
    if 'conservative_profit_factor' not in audit:
        raise FuturesCostError('funding audit profit factor missing')
    losses=-math.fsum(value for value in adjusted_values if value<0)
    gains=math.fsum(value for value in adjusted_values if value>0)
    if losses:
        factor=number(audit['conservative_profit_factor'],'conservative profit factor')
        if not math.isclose(factor,gains/losses,rel_tol=1e-9,abs_tol=1e-9):
            raise FuturesCostError('funding audit profit factor does not reconcile')
    elif audit['conservative_profit_factor'] is not None:
        raise FuturesCostError('funding audit profit factor must be unknown without losses')
    return audit


def funding_gate_passed(audit: Mapping[str, Any], gate: Mapping[str, Any]) -> bool:
    factor=audit.get('conservative_profit_factor')
    factor_pass=(factor is None and audit.get('conservative_loss_count')==0
                 and audit.get('conservative_net_profit_pct',0)>0) or (
                     isinstance(factor,(int,float)) and not isinstance(factor,bool)
                     and math.isfinite(factor) and factor>=gate['minimum_profit_factor'])
    return (audit.get('contract')==CONTRACT and audit.get('cash_executable') is True
            and audit['conservative_net_profit_pct']>0
            and audit['conservative_net_profit_pct']>=gate.get('minimum_profit_pct',0)
            and audit['conservative_mtm_drawdown_pct']<=gate['maximum_drawdown_pct'] and factor_pass)
