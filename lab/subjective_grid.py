"""Deterministic, sample-bounded subjective grid feasibility Gate v0."""

from __future__ import annotations

import csv
import ctypes
import errno
import hashlib
import io
import json
import os
import re
import shutil
import stat
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union


TICKET_SCHEMA = "freqtrade-lab-subjective-grid-ticket-v0"
RESULT_SCHEMA = "freqtrade-lab-subjective-grid-result-v0"
RESULT_FILENAME = "result.json"
SUMMARY_FILENAME = "summary.md"
INTRABAR_PATHS = ("O-H-L-C", "O-L-H-C")
MAX_TICKET_BYTES = 1 * 1024 * 1024
MAX_DATA_BYTES = 16 * 1024 * 1024
MAX_CANDLES = 200_000
DECIMAL_PRECISION = 50

_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
_DECIMAL = re.compile(r"(?:0|[1-9]\d{0,17})(?:\.\d{1,18})?")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_PAIR = re.compile(r"[A-Z0-9][A-Z0-9._-]{0,31}/[A-Z0-9][A-Z0-9._-]{0,31}")
_CSV_HEADER = ("timestamp", "open", "high", "low", "close", "volume")
_EVIDENCE_STATUSES = {"SAMPLE_ONLY", "UNKNOWN"}
_OUT_OF_RANGE_RULES = {
    "HOLD",
    "HALT_ON_FIRST_CLOSE_OUTSIDE_RANGE_KEEP_INVENTORY",
}


class SubjectiveGridError(RuntimeError):
    """A fail-closed ticket, data, simulation, or publication error."""


PathLike = Union[str, os.PathLike[str]]


@dataclass(frozen=True)
class GridTicket:
    pair: str
    decision_time: datetime
    window_start: datetime
    window_end: datetime
    candle_interval_seconds: int
    lower: Decimal
    upper: Decimal
    grid_count: int
    spacing: Decimal
    starting_quote: Decimal
    per_grid_quote: Decimal
    max_inventory_base: Decimal
    fee_rate: Decimal
    slippage_rate: Decimal
    out_of_range_rule: str
    data_sha256: str
    evidence_status: str


@dataclass(frozen=True)
class Candle:
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal


@dataclass
class _Cell:
    buy_level: Decimal
    sell_level: Decimal
    armed: bool
    quantity: Optional[Decimal] = None


@dataclass
class _ScenarioState:
    cash: Decimal
    inventory: Decimal
    fees: Decimal = Decimal(0)
    slippage: Decimal = Decimal(0)
    turnover: Decimal = Decimal(0)
    completed_grid_profit: Decimal = Decimal(0)
    maximum_inventory: Decimal = Decimal(0)
    peak_equity: Decimal = Decimal(0)
    maximum_drawdown: Decimal = Decimal(0)
    buy_fills: int = 0
    sell_fills: int = 0
    completed_cycles: int = 0
    rejected_buys_cash: int = 0
    rejected_buys_inventory: int = 0
    halted: bool = False


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_bytes(value: Any) -> bytes:
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError, OverflowError) as exc:
        raise SubjectiveGridError(f"result cannot be encoded as strict JSON: {exc}") from exc
    return (encoded + "\n").encode("utf-8")


def _strict_json(data: bytes, label: str) -> Any:
    def no_duplicates(pairs: Iterable[Tuple[str, Any]]) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise SubjectiveGridError(f"{label}: duplicate JSON key {key!r}")
            result[key] = value
        return result

    def reject_constant(value: str) -> Any:
        raise SubjectiveGridError(f"{label}: non-finite JSON value {value}")

    try:
        return json.loads(
            data.decode("utf-8", "strict"),
            object_pairs_hook=no_duplicates,
            parse_constant=reject_constant,
        )
    except SubjectiveGridError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise SubjectiveGridError(f"{label}: invalid UTF-8 JSON: {exc}") from exc


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise SubjectiveGridError(f"{label} must be a JSON object")
    return value


def _exact_keys(value: Mapping[str, Any], required: Sequence[str], label: str) -> None:
    expected = set(required)
    actual = set(value)
    missing = sorted(expected - actual)
    unknown = sorted(actual - expected)
    if missing:
        raise SubjectiveGridError(f"{label} is missing fields: {', '.join(missing)}")
    if unknown:
        raise SubjectiveGridError(f"{label} contains unknown fields: {', '.join(unknown)}")


def _required_literal(value: Any, expected: Any, label: str) -> None:
    if isinstance(expected, bool):
        if value is not expected:
            raise SubjectiveGridError(f"{label} must equal {expected!r}")
        return
    if isinstance(expected, int) and isinstance(value, bool):
        raise SubjectiveGridError(f"{label} must equal {expected!r}")
    if value != expected:
        raise SubjectiveGridError(f"{label} must equal {expected!r}")


def _string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise SubjectiveGridError(f"{label} must be a non-empty string")
    return value


def _integer(value: Any, label: str, minimum: int, maximum: int) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < minimum
        or value > maximum
    ):
        raise SubjectiveGridError(
            f"{label} must be an integer from {minimum} through {maximum}"
        )
    return value


def _decimal_value(
    value: Any,
    label: str,
    *,
    minimum: Decimal,
    maximum: Optional[Decimal] = None,
    strictly_positive: bool = False,
) -> Decimal:
    if not isinstance(value, str) or _DECIMAL.fullmatch(value) is None:
        raise SubjectiveGridError(
            f"{label} must be a plain non-negative decimal string with at most "
            "18 integer and 18 fractional digits"
        )
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise SubjectiveGridError(f"{label} must be a valid decimal string") from exc
    if number < minimum or (strictly_positive and number == 0):
        comparator = "greater than" if strictly_positive else "greater than or equal to"
        raise SubjectiveGridError(f"{label} must be {comparator} {_format_decimal(minimum)}")
    if maximum is not None and number > maximum:
        raise SubjectiveGridError(
            f"{label} must be less than or equal to {_format_decimal(maximum)}"
        )
    return number


def _parse_timestamp(value: Any, label: str) -> datetime:
    text = _string(value, label)
    if _TIMESTAMP.fullmatch(text) is None:
        raise SubjectiveGridError(f"{label} must use YYYY-MM-DDTHH:MM:SSZ")
    try:
        return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise SubjectiveGridError(f"{label} is not a valid UTC timestamp") from exc


def _timestamp_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _format_decimal(value: Decimal) -> str:
    if value == 0:
        return "0"
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def load_ticket(data: bytes) -> GridTicket:
    """Parse and validate one exact decision-ticket v0 document."""
    document = _mapping(_strict_json(data, "decision ticket"), "decision ticket")
    _exact_keys(
        document,
        (
            "schema",
            "pair",
            "market",
            "direction",
            "leverage",
            "decision_time",
            "evaluation_window",
            "grid",
            "capital",
            "costs",
            "out_of_range",
            "no_recenter",
            "ohlcv_sha256",
            "evidence_status",
        ),
        "decision ticket",
    )
    _required_literal(document["schema"], TICKET_SCHEMA, "decision ticket.schema")
    pair = _string(document["pair"], "decision ticket.pair")
    if _PAIR.fullmatch(pair) is None:
        raise SubjectiveGridError("decision ticket.pair must use uppercase BASE/QUOTE")
    _required_literal(document["market"], "SPOT", "decision ticket.market")
    _required_literal(document["direction"], "LONG_ONLY", "decision ticket.direction")
    if isinstance(document["leverage"], bool):
        raise SubjectiveGridError("decision ticket.leverage must be integer 1")
    _required_literal(document["leverage"], 1, "decision ticket.leverage")
    _required_literal(document["no_recenter"], True, "decision ticket.no_recenter")

    decision_time = _parse_timestamp(document["decision_time"], "decision ticket.decision_time")

    window = _mapping(document["evaluation_window"], "decision ticket.evaluation_window")
    _exact_keys(
        window,
        ("start", "end", "candle_interval_seconds"),
        "decision ticket.evaluation_window",
    )
    window_start = _parse_timestamp(window["start"], "decision ticket.evaluation_window.start")
    window_end = _parse_timestamp(window["end"], "decision ticket.evaluation_window.end")
    interval = _integer(
        window["candle_interval_seconds"],
        "decision ticket.evaluation_window.candle_interval_seconds",
        1,
        86_400,
    )
    if decision_time >= window_start:
        raise SubjectiveGridError("decision_time must be strictly before the evaluation window")
    if window_end <= window_start:
        raise SubjectiveGridError("evaluation window end must be after its start")
    window_seconds = int((window_end - window_start).total_seconds())
    if window_seconds % interval != 0:
        raise SubjectiveGridError("evaluation window must contain a whole number of candles")
    expected_candles = window_seconds // interval
    if expected_candles < 1 or expected_candles > MAX_CANDLES:
        raise SubjectiveGridError(
            f"evaluation window must contain from 1 through {MAX_CANDLES} candles"
        )

    grid = _mapping(document["grid"], "decision ticket.grid")
    _exact_keys(grid, ("type", "lower", "upper", "count", "spacing"), "decision ticket.grid")
    _required_literal(grid["type"], "ARITHMETIC", "decision ticket.grid.type")
    lower = _decimal_value(
        grid["lower"],
        "decision ticket.grid.lower",
        minimum=Decimal(0),
        strictly_positive=True,
    )
    upper = _decimal_value(
        grid["upper"],
        "decision ticket.grid.upper",
        minimum=Decimal(0),
        strictly_positive=True,
    )
    grid_count = _integer(grid["count"], "decision ticket.grid.count", 1, 100)
    spacing = _decimal_value(
        grid["spacing"],
        "decision ticket.grid.spacing",
        minimum=Decimal(0),
        strictly_positive=True,
    )
    with localcontext() as context:
        context.prec = DECIMAL_PRECISION
        if upper <= lower:
            raise SubjectiveGridError("grid upper must be greater than grid lower")
        if upper - lower != spacing * grid_count:
            raise SubjectiveGridError(
                "grid spacing must equal (upper - lower) / count exactly"
            )

    capital = _mapping(document["capital"], "decision ticket.capital")
    _exact_keys(
        capital,
        ("starting_quote", "per_grid_quote", "max_inventory_base"),
        "decision ticket.capital",
    )
    starting_quote = _decimal_value(
        capital["starting_quote"],
        "decision ticket.capital.starting_quote",
        minimum=Decimal(0),
        strictly_positive=True,
    )
    per_grid_quote = _decimal_value(
        capital["per_grid_quote"],
        "decision ticket.capital.per_grid_quote",
        minimum=Decimal(0),
        strictly_positive=True,
    )
    max_inventory = _decimal_value(
        capital["max_inventory_base"],
        "decision ticket.capital.max_inventory_base",
        minimum=Decimal(0),
        strictly_positive=True,
    )

    costs = _mapping(document["costs"], "decision ticket.costs")
    _exact_keys(costs, ("fee_rate", "slippage_rate"), "decision ticket.costs")
    fee_rate = _decimal_value(
        costs["fee_rate"],
        "decision ticket.costs.fee_rate",
        minimum=Decimal(0),
        maximum=Decimal("0.1"),
    )
    slippage_rate = _decimal_value(
        costs["slippage_rate"],
        "decision ticket.costs.slippage_rate",
        minimum=Decimal(0),
        maximum=Decimal("0.1"),
    )
    with localcontext() as context:
        context.prec = DECIMAL_PRECISION
        if per_grid_quote * (Decimal(1) + fee_rate + slippage_rate) > starting_quote:
            raise SubjectiveGridError(
                "per-grid quote plus frozen fee and slippage must fit starting capital"
            )

    out_of_range = _mapping(document["out_of_range"], "decision ticket.out_of_range")
    _exact_keys(out_of_range, ("rule", "stop_price"), "decision ticket.out_of_range")
    rule = _string(out_of_range["rule"], "decision ticket.out_of_range.rule")
    if rule not in _OUT_OF_RANGE_RULES:
        raise SubjectiveGridError(
            "decision ticket.out_of_range.rule is not supported by Gate v0"
        )
    if out_of_range["stop_price"] is not None:
        raise SubjectiveGridError(
            "decision ticket.out_of_range.stop_price must be null; Gate v0 never forces a liquidation"
        )

    data_sha256 = _string(document["ohlcv_sha256"], "decision ticket.ohlcv_sha256")
    if _SHA256.fullmatch(data_sha256) is None:
        raise SubjectiveGridError("decision ticket.ohlcv_sha256 must be lowercase SHA-256")
    evidence_status = _string(document["evidence_status"], "decision ticket.evidence_status")
    if evidence_status not in _EVIDENCE_STATUSES:
        raise SubjectiveGridError(
            "decision ticket.evidence_status must be SAMPLE_ONLY or UNKNOWN"
        )

    return GridTicket(
        pair=pair,
        decision_time=decision_time,
        window_start=window_start,
        window_end=window_end,
        candle_interval_seconds=interval,
        lower=lower,
        upper=upper,
        grid_count=grid_count,
        spacing=spacing,
        starting_quote=starting_quote,
        per_grid_quote=per_grid_quote,
        max_inventory_base=max_inventory,
        fee_rate=fee_rate,
        slippage_rate=slippage_rate,
        out_of_range_rule=rule,
        data_sha256=data_sha256,
        evidence_status=evidence_status,
    )


def load_ohlcv(data: bytes, ticket: GridTicket) -> Tuple[Candle, ...]:
    """Verify the frozen bytes and parse one exact, contiguous OHLCV window."""
    actual_sha256 = _sha256(data)
    if actual_sha256 != ticket.data_sha256:
        raise SubjectiveGridError(
            f"OHLCV SHA-256 mismatch: expected {ticket.data_sha256}, got {actual_sha256}"
        )
    try:
        text = data.decode("utf-8", "strict")
    except UnicodeDecodeError as exc:
        raise SubjectiveGridError(f"OHLCV must be valid UTF-8 CSV: {exc}") from exc

    try:
        rows = list(csv.reader(io.StringIO(text, newline="")))
    except csv.Error as exc:
        raise SubjectiveGridError(f"OHLCV CSV cannot be parsed: {exc}") from exc
    if not rows or tuple(rows[0]) != _CSV_HEADER:
        raise SubjectiveGridError(
            f"OHLCV CSV header must be exactly {','.join(_CSV_HEADER)}"
        )
    raw_rows = rows[1:]
    expected_count = int(
        (ticket.window_end - ticket.window_start).total_seconds()
    ) // ticket.candle_interval_seconds
    if len(raw_rows) != expected_count:
        raise SubjectiveGridError(
            f"OHLCV must contain exactly {expected_count} contiguous evaluation rows"
        )

    candles: List[Candle] = []
    for index, row in enumerate(raw_rows):
        if len(row) != len(_CSV_HEADER):
            raise SubjectiveGridError(f"OHLCV row {index + 2} must contain exactly 6 fields")
        timestamp = _parse_timestamp(row[0], f"OHLCV row {index + 2} timestamp")
        expected_timestamp = ticket.window_start + timedelta(
            seconds=index * ticket.candle_interval_seconds
        )
        if timestamp != expected_timestamp:
            raise SubjectiveGridError(
                f"OHLCV row {index + 2} must start at {_timestamp_text(expected_timestamp)}"
            )
        open_price = _decimal_value(
            row[1], f"OHLCV row {index + 2} open", minimum=Decimal(0), strictly_positive=True
        )
        high = _decimal_value(
            row[2], f"OHLCV row {index + 2} high", minimum=Decimal(0), strictly_positive=True
        )
        low = _decimal_value(
            row[3], f"OHLCV row {index + 2} low", minimum=Decimal(0), strictly_positive=True
        )
        close = _decimal_value(
            row[4], f"OHLCV row {index + 2} close", minimum=Decimal(0), strictly_positive=True
        )
        volume = _decimal_value(
            row[5], f"OHLCV row {index + 2} volume", minimum=Decimal(0)
        )
        if low > min(open_price, close) or high < max(open_price, close) or low > high:
            raise SubjectiveGridError(
                f"OHLCV row {index + 2} violates low <= open/close <= high"
            )
        candles.append(Candle(timestamp, open_price, high, low, close, volume))
    return tuple(candles)


def _scenario_signature(
    metrics: Mapping[str, Any], baselines: Mapping[str, Mapping[str, str]]
) -> Dict[str, bool]:
    terminal = Decimal(metrics["terminal_equity_quote"])
    cash = Decimal(baselines["cash_no_trade"]["terminal_equity_quote"])
    buy_hold = Decimal(baselines["buy_and_hold"]["terminal_equity_quote"])
    mechanism_exercised = metrics["completed_cycles"] >= 1
    beats_cash = terminal > cash
    beats_buy_hold = terminal > buy_hold
    range_contained = metrics["out_of_range"]["touch_candles"] == 0
    return {
        "mechanism_exercised": mechanism_exercised,
        "beats_cash": beats_cash,
        "beats_buy_and_hold": beats_buy_hold,
        "range_contained": range_contained,
        "scenario_pass": (
            mechanism_exercised and beats_cash and beats_buy_hold and range_contained
        ),
    }


def _baselines(ticket: GridTicket, candles: Sequence[Candle]) -> Dict[str, Dict[str, str]]:
    first_open = candles[0].open
    final_close = candles[-1].close
    with localcontext() as context:
        context.prec = DECIMAL_PRECISION
        gross_entry = ticket.starting_quote / (
            Decimal(1) + ticket.fee_rate + ticket.slippage_rate
        )
        quantity = gross_entry / first_open
        entry_fee = gross_entry * ticket.fee_rate
        entry_slippage = gross_entry * ticket.slippage_rate
        terminal_equity = quantity * final_close
        total_return = (terminal_equity - ticket.starting_quote) / ticket.starting_quote
    return {
        "cash_no_trade": {
            "terminal_equity_quote": _format_decimal(ticket.starting_quote),
            "total_return": "0",
            "fees_quote": "0",
            "slippage_quote": "0",
            "terminal_inventory_base": "0",
        },
        "buy_and_hold": {
            "entry_price": _format_decimal(first_open),
            "gross_entry_quote": _format_decimal(gross_entry),
            "fees_quote": _format_decimal(entry_fee),
            "slippage_quote": _format_decimal(entry_slippage),
            "terminal_inventory_base": _format_decimal(quantity),
            "terminal_equity_quote": _format_decimal(terminal_equity),
            "total_return": _format_decimal(total_return),
        },
    }


def _simulate_path(
    ticket: GridTicket,
    candles: Sequence[Candle],
    intrabar_path: str,
) -> Dict[str, Any]:
    if intrabar_path not in INTRABAR_PATHS:
        raise SubjectiveGridError(f"unsupported intrabar path {intrabar_path!r}")
    levels = tuple(ticket.lower + ticket.spacing * index for index in range(ticket.grid_count + 1))
    if levels[-1] != ticket.upper:
        raise SubjectiveGridError("grid levels do not terminate at the frozen upper bound")
    first_open = candles[0].open
    cells = [
        _Cell(levels[index], levels[index + 1], first_open > levels[index])
        for index in range(ticket.grid_count)
    ]
    state = _ScenarioState(
        cash=ticket.starting_quote,
        inventory=Decimal(0),
        peak_equity=ticket.starting_quote,
    )

    def track(price: Decimal) -> None:
        equity = state.cash + state.inventory * price
        if equity > state.peak_equity:
            state.peak_equity = equity
        if state.peak_equity > 0:
            drawdown = (state.peak_equity - equity) / state.peak_equity
            if drawdown > state.maximum_drawdown:
                state.maximum_drawdown = drawdown

    def sync_inventory() -> None:
        state.inventory = sum(
            (cell.quantity or Decimal(0) for cell in cells),
            Decimal(0),
        )

    def buy(cell: _Cell) -> None:
        track(cell.buy_level)
        quantity = ticket.per_grid_quote / cell.buy_level
        gross = quantity * cell.buy_level
        fee = gross * ticket.fee_rate
        slippage = gross * ticket.slippage_rate
        debit = gross + fee + slippage
        if state.cash < debit:
            state.rejected_buys_cash += 1
            cell.armed = False
            return
        if state.inventory + quantity > ticket.max_inventory_base:
            state.rejected_buys_inventory += 1
            cell.armed = False
            return
        state.cash -= debit
        state.fees += fee
        state.slippage += slippage
        state.turnover += gross
        state.buy_fills += 1
        cell.quantity = quantity
        cell.armed = False
        sync_inventory()
        if state.inventory > state.maximum_inventory:
            state.maximum_inventory = state.inventory
        track(cell.buy_level)

    def sell(cell: _Cell) -> None:
        assert cell.quantity is not None
        track(cell.sell_level)
        quantity = cell.quantity
        gross = quantity * cell.sell_level
        fee = gross * ticket.fee_rate
        slippage = gross * ticket.slippage_rate
        state.cash += gross - fee - slippage
        state.fees += fee
        state.slippage += slippage
        state.turnover += gross
        state.completed_grid_profit += quantity * (cell.sell_level - cell.buy_level)
        state.sell_fills += 1
        state.completed_cycles += 1
        cell.quantity = None
        cell.armed = True
        sync_inventory()
        track(cell.sell_level)

    def move(start: Decimal, end: Decimal) -> None:
        if start == end:
            track(end)
            return
        if not state.halted and end < start:
            for cell in reversed(cells):
                if end <= cell.buy_level < start and cell.quantity is None and cell.armed:
                    buy(cell)
        elif not state.halted and end > start:
            for cell in cells:
                if start < cell.sell_level <= end and cell.quantity is not None:
                    sell(cell)
            for cell in cells:
                if cell.quantity is None and end > cell.buy_level:
                    cell.armed = True
        track(end)

    touch_candles = 0
    close_candles = 0
    close_sampled_seconds = 0
    previous_close: Optional[Decimal] = None
    track(first_open)
    for candle in candles:
        if candle.low < ticket.lower or candle.high > ticket.upper:
            touch_candles += 1
        close_outside = candle.close < ticket.lower or candle.close > ticket.upper
        if close_outside:
            close_candles += 1
            close_sampled_seconds += ticket.candle_interval_seconds
        if previous_close is not None:
            move(previous_close, candle.open)
        if intrabar_path == "O-H-L-C":
            points = (candle.open, candle.high, candle.low, candle.close)
        else:
            points = (candle.open, candle.low, candle.high, candle.close)
        for start, end in zip(points, points[1:]):
            move(start, end)
        if (
            close_outside
            and ticket.out_of_range_rule
            == "HALT_ON_FIRST_CLOSE_OUTSIDE_RANGE_KEEP_INVENTORY"
        ):
            state.halted = True
        previous_close = candle.close

    final_close = candles[-1].close
    terminal_cost_basis = sum(
        (cell.quantity or Decimal(0)) * cell.buy_level for cell in cells
    )
    terminal_mark_value = state.inventory * final_close
    unmatched_inventory_pnl = terminal_mark_value - terminal_cost_basis
    terminal_equity = state.cash + terminal_mark_value
    total_pnl = terminal_equity - ticket.starting_quote
    total_return = total_pnl / ticket.starting_quote
    explained_pnl = (
        state.completed_grid_profit
        + unmatched_inventory_pnl
        - state.fees
        - state.slippage
    )
    reconciliation_error = total_pnl - explained_pnl
    reconciliation_tolerance = max(
        Decimal("1e-30"), abs(ticket.starting_quote) * Decimal("1e-30")
    )
    accounting_identity_pass = abs(reconciliation_error) <= reconciliation_tolerance
    if not accounting_identity_pass:
        raise SubjectiveGridError("internal PnL accounting identity did not reconcile")

    return {
        "intrabar_path": intrabar_path,
        "metrics": {
            "terminal_equity_quote": _format_decimal(terminal_equity),
            "total_pnl_quote": _format_decimal(total_pnl),
            "total_return": _format_decimal(total_return),
            "completed_grid_profit_quote": _format_decimal(state.completed_grid_profit),
            "unmatched_inventory_pnl_quote": _format_decimal(unmatched_inventory_pnl),
            "fees_quote": _format_decimal(state.fees),
            "slippage_quote": _format_decimal(state.slippage),
            "turnover_quote": _format_decimal(state.turnover),
            "maximum_inventory_base": _format_decimal(state.maximum_inventory),
            "maximum_drawdown": _format_decimal(state.maximum_drawdown),
            "terminal_cash_quote": _format_decimal(state.cash),
            "terminal_inventory": {
                "base_quantity": _format_decimal(state.inventory),
                "cost_basis_quote": _format_decimal(terminal_cost_basis),
                "mark_value_quote": _format_decimal(terminal_mark_value),
                "mark_price": _format_decimal(final_close),
            },
            "buy_fills": state.buy_fills,
            "sell_fills": state.sell_fills,
            "completed_cycles": state.completed_cycles,
            "rejected_buys": {
                "cash": state.rejected_buys_cash,
                "maximum_inventory": state.rejected_buys_inventory,
            },
            "halted_after_out_of_range_close": state.halted,
            "out_of_range": {
                "touch_candles": touch_candles,
                "close_candles": close_candles,
                "close_sampled_seconds": close_sampled_seconds,
                "exact_intrabar_time": "UNKNOWN_FROM_OHLCV",
            },
            "pnl_reconciliation_error_quote": _format_decimal(reconciliation_error),
            "accounting_identity_pass": accounting_identity_pass,
        },
    }


def simulate(
    ticket: GridTicket,
    candles: Sequence[Candle],
    *,
    ticket_sha256: str = "UNKNOWN_NOT_PROVIDED",
    data_sha256: Optional[str] = None,
) -> Dict[str, Any]:
    """Run both frozen intrabar paths and return one deterministic result object."""
    if not candles:
        raise SubjectiveGridError("at least one OHLCV candle is required")
    if data_sha256 is None:
        data_sha256 = ticket.data_sha256
    with localcontext() as context:
        context.prec = DECIMAL_PRECISION
        levels = tuple(
            ticket.lower + ticket.spacing * index
            for index in range(ticket.grid_count + 1)
        )
        baselines = _baselines(ticket, candles)
        scenarios = [_simulate_path(ticket, candles, path) for path in INTRABAR_PATHS]
    for scenario in scenarios:
        scenario["conclusion"] = _scenario_signature(scenario["metrics"], baselines)
    signatures = [scenario["conclusion"] for scenario in scenarios]
    if signatures[0] != signatures[1]:
        verdict = "INTRABAR_PATH_SENSITIVE"
    elif signatures[0]["scenario_pass"]:
        verdict = "MECHANISM_GATE_PASS"
    else:
        verdict = "MECHANISM_GATE_FAIL"
    metrics_differ = scenarios[0]["metrics"] != scenarios[1]["metrics"]
    claim_boundary = (
        "SAMPLE_ONLY_NOT_REAL_ECONOMIC_EVIDENCE"
        if ticket.evidence_status == "SAMPLE_ONLY"
        else "UNKNOWN_ECONOMIC_EVIDENCE"
    )
    return {
        "schema": RESULT_SCHEMA,
        "gate": {
            "verdict": verdict,
            "economic_evidence_status": ticket.evidence_status,
            "claim_boundary": claim_boundary,
            "intrabar_path_sensitive": verdict == "INTRABAR_PATH_SENSITIVE",
            "path_metrics_differ_same_conclusion": metrics_differ and signatures[0] == signatures[1],
        },
        "input": {
            "pair": ticket.pair,
            "market": "SPOT",
            "direction": "LONG_ONLY",
            "leverage": 1,
            "ticket_sha256": ticket_sha256,
            "ohlcv_sha256": data_sha256,
            "decision_time": _timestamp_text(ticket.decision_time),
            "evaluation_window": {
                "start": _timestamp_text(ticket.window_start),
                "end": _timestamp_text(ticket.window_end),
                "candle_interval_seconds": ticket.candle_interval_seconds,
                "row_count": len(candles),
            },
            "grid": {
                "type": "ARITHMETIC",
                "lower": _format_decimal(ticket.lower),
                "upper": _format_decimal(ticket.upper),
                "count": ticket.grid_count,
                "spacing": _format_decimal(ticket.spacing),
                "levels": [_format_decimal(level) for level in levels],
            },
            "capital": {
                "starting_quote": _format_decimal(ticket.starting_quote),
                "per_grid_quote": _format_decimal(ticket.per_grid_quote),
                "max_inventory_base": _format_decimal(ticket.max_inventory_base),
            },
            "costs": {
                "fee_rate": _format_decimal(ticket.fee_rate),
                "slippage_rate": _format_decimal(ticket.slippage_rate),
            },
            "out_of_range_rule": ticket.out_of_range_rule,
            "no_recenter": True,
        },
        "baselines": baselines,
        "scenarios": scenarios,
        "assumptions_and_limits": [
            "The declared decision_time is causally ordered but is not an independent historical timestamp receipt.",
            "Each grid cell has one full-fill lot; trigger-level fills ignore order-book depth, tick size, lot size, and minimum notional.",
            "An empty cell is armed only after price is observed strictly above its buy level, then fills on a downward crossing.",
            "Close-to-open gaps are traversed at trigger levels; this is a deterministic idealization, not an exchange gap-fill model.",
            "Fee and slippage are separate deterministic costs on trigger notional; there is no leverage, shorting, or capital addition.",
            "O-H-L-C and O-L-H-C are two deterministic orderings, not real matching bounds; neither path may be selected after the fact.",
            "Exact intrabar out-of-range duration is unavailable from OHLCV and remains UNKNOWN_FROM_OHLCV.",
            "Terminal inventory is marked at the final close and is not given a fictional liquidation fill.",
            "Maximum drawdown uses total equity sampled at the initial price, gap/path vertices, and immediately before and after fills.",
            "A passing technical Gate on one frozen input does not prove positive expectancy, robustness, tradability, or fund safety.",
        ],
    }


def render_summary(result: Mapping[str, Any]) -> str:
    """Render a short human-readable view derived only from the result object."""
    gate = result["gate"]
    input_contract = result["input"]
    baselines = result["baselines"]
    lines = [
        "# Subjective Grid Feasibility Gate v0",
        "",
        f"- Pair: `{input_contract['pair']}` (`SPOT`, `LONG_ONLY`, `1x`)",
        f"- Verdict: `{gate['verdict']}`",
        f"- Economic evidence: `{gate['economic_evidence_status']}`",
        f"- Claim boundary: `{gate['claim_boundary']}`",
        f"- Cash/no-trade terminal equity: `{baselines['cash_no_trade']['terminal_equity_quote']}`",
        f"- Buy-and-hold terminal equity: `{baselines['buy_and_hold']['terminal_equity_quote']}`",
        "",
        "| Intrabar path | Terminal equity | Total return | Completed grid profit | Unmatched inventory PnL | Fees | Slippage | Max drawdown | Terminal inventory | Conclusion |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for scenario in result["scenarios"]:
        metrics = scenario["metrics"]
        conclusion = scenario["conclusion"]
        lines.append(
            "| "
            + " | ".join(
                (
                    scenario["intrabar_path"],
                    metrics["terminal_equity_quote"],
                    metrics["total_return"],
                    metrics["completed_grid_profit_quote"],
                    metrics["unmatched_inventory_pnl_quote"],
                    metrics["fees_quote"],
                    metrics["slippage_quote"],
                    metrics["maximum_drawdown"],
                    metrics["terminal_inventory"]["base_quantity"],
                    "PASS" if conclusion["scenario_pass"] else "FAIL",
                )
            )
            + " |"
        )
    lines.extend(
        (
            "",
            "Out-of-range duration is only close-sampled; exact intrabar time is `UNKNOWN_FROM_OHLCV`.",
            "Completed grid profit is not total return: terminal inventory, fees, slippage, and both baselines remain visible.",
            "This output is a deterministic mechanism check, not a profitability, robustness, execution, or trading claim.",
            "",
        )
    )
    return "\n".join(lines)


def _read_regular_file(path_value: PathLike, label: str, limit: int) -> bytes:
    value = Path(path_value).expanduser()
    try:
        if value.is_symlink():
            raise SubjectiveGridError(f"{label} must not be a symlink")
        path = value.resolve(strict=True)
        info = path.stat()
        if not stat.S_ISREG(info.st_mode):
            raise SubjectiveGridError(f"{label} must be a regular file")
        if info.st_size > limit:
            raise SubjectiveGridError(f"{label} exceeds the {limit}-byte limit")
        data = path.read_bytes()
    except SubjectiveGridError:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise SubjectiveGridError(f"{label} cannot be read safely: {exc}") from exc
    if len(data) > limit:
        raise SubjectiveGridError(f"{label} exceeds the {limit}-byte limit")
    return data


def _resolve_output(path_value: PathLike) -> Path:
    value = Path(path_value).expanduser()
    if value.name in ("", ".", ".."):
        raise SubjectiveGridError("output directory must name one new directory")
    try:
        if value.parent.is_symlink():
            raise SubjectiveGridError("output parent must not be a symlink")
        parent = value.parent.resolve(strict=True)
    except SubjectiveGridError:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise SubjectiveGridError(f"output parent cannot be resolved safely: {exc}") from exc
    if not parent.is_dir():
        raise SubjectiveGridError("output parent must be a directory")
    output = parent / value.name
    if output.exists() or output.is_symlink():
        raise SubjectiveGridError("output directory already exists")
    return output


def _publish_directory_exclusive(source: Path, destination: Path) -> None:
    """Publish one fully written directory without replacing a concurrent target."""
    if sys.platform == "darwin":
        libc = ctypes.CDLL(None, use_errno=True)
        rename_exclusive = getattr(libc, "renameatx_np", None)
        if rename_exclusive is None:
            raise SubjectiveGridError("exclusive output publication is unavailable")
        rename_exclusive.argtypes = (
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        )
        rename_exclusive.restype = ctypes.c_int
        result = rename_exclusive(
            -2,
            os.fsencode(source),
            -2,
            os.fsencode(destination),
            0x00000004,
        )
        if result == 0:
            return
        error_number = ctypes.get_errno()
        if error_number in (errno.EEXIST, errno.ENOTEMPTY):
            raise SubjectiveGridError(
                "output directory was created concurrently; nothing was published"
            )
        raise SubjectiveGridError(
            f"exclusive output publication failed: {os.strerror(error_number)}"
        )
    if sys.platform.startswith("linux"):
        libc = ctypes.CDLL(None, use_errno=True)
        rename_exclusive = getattr(libc, "renameat2", None)
        if rename_exclusive is None:
            raise SubjectiveGridError("exclusive output publication is unavailable")
        rename_exclusive.argtypes = (
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        )
        rename_exclusive.restype = ctypes.c_int
        result = rename_exclusive(
            -100,
            os.fsencode(source),
            -100,
            os.fsencode(destination),
            0x00000001,
        )
        if result == 0:
            return
        error_number = ctypes.get_errno()
        if error_number in (errno.EEXIST, errno.ENOTEMPTY):
            raise SubjectiveGridError(
                "output directory was created concurrently; nothing was published"
            )
        raise SubjectiveGridError(
            f"exclusive output publication failed: {os.strerror(error_number)}"
        )
    raise SubjectiveGridError("exclusive output publication is unavailable")


def _write_synced(path: Path, data: bytes) -> None:
    try:
        with path.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise SubjectiveGridError(f"output staging write failed: {exc}") from exc


def _publish_output(output: Path, result_bytes: bytes, summary_bytes: bytes) -> None:
    try:
        staging = Path(
            tempfile.mkdtemp(
                prefix=f".{output.name}.", suffix=".tmp", dir=str(output.parent)
            )
        )
    except OSError as exc:
        raise SubjectiveGridError(f"output staging directory cannot be created: {exc}") from exc
    published = False
    parent_fd = -1
    try:
        _write_synced(staging / RESULT_FILENAME, result_bytes)
        _write_synced(staging / SUMMARY_FILENAME, summary_bytes)
        directory_fd = os.open(staging, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        parent_fd = os.open(output.parent, os.O_RDONLY | os.O_DIRECTORY)
        os.fsync(parent_fd)
        _publish_directory_exclusive(staging, output)
        published = True
        try:
            os.fsync(parent_fd)
        except OSError:
            # The complete directory is already atomically visible. Reporting
            # failure now would falsely imply that no final output exists.
            pass
    except SubjectiveGridError:
        raise
    except OSError as exc:
        raise SubjectiveGridError(f"output publication failed: {exc}") from exc
    finally:
        if parent_fd >= 0:
            try:
                os.close(parent_fd)
            except OSError:
                pass
        if not published:
            shutil.rmtree(staging, ignore_errors=True)


def evaluate_subjective_grid(
    ticket_path: PathLike,
    data_path: PathLike,
    output_dir: PathLike,
) -> Dict[str, Any]:
    """Validate frozen inputs, run both paths, and atomically publish two files."""
    ticket_bytes = _read_regular_file(ticket_path, "decision ticket", MAX_TICKET_BYTES)
    data_bytes = _read_regular_file(data_path, "OHLCV data", MAX_DATA_BYTES)
    ticket = load_ticket(ticket_bytes)
    candles = load_ohlcv(data_bytes, ticket)
    output = _resolve_output(output_dir)
    result = simulate(
        ticket,
        candles,
        ticket_sha256=_sha256(ticket_bytes),
        data_sha256=_sha256(data_bytes),
    )
    result_bytes = _canonical_bytes(result)
    summary_bytes = render_summary(result).encode("utf-8")
    _publish_output(output, result_bytes, summary_bytes)
    return result


__all__ = [
    "Candle",
    "GridTicket",
    "RESULT_FILENAME",
    "SUMMARY_FILENAME",
    "SubjectiveGridError",
    "evaluate_subjective_grid",
    "load_ohlcv",
    "load_ticket",
    "render_summary",
    "simulate",
]
