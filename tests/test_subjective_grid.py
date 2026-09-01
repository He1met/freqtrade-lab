"""T0/T1/T2 contracts for the Subjective Grid feasibility Gate v0."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from dataclasses import asdict, is_dataclass
from decimal import Decimal, localcontext
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple

import pytest

import lab.subjective_grid as subjective_grid


PROJECT_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_ROOT = PROJECT_ROOT / "tests" / "fixtures" / "subjective_grid_v0"
TICKET_PATH = FIXTURE_ROOT / "decision-ticket.json"
DATA_PATH = FIXTURE_ROOT / "ohlcv.csv"
PROVENANCE_PATH = FIXTURE_ROOT / "PROVENANCE.md"
CLI = PROJECT_ROOT / "scripts" / "evaluate_subjective_grid.py"
SCHEMA_PATH = PROJECT_ROOT / "sql" / "schema_v1.sql"

TICKET_SCHEMA = "freqtrade-lab-subjective-grid-ticket-v0"
RESULT_SCHEMA = "freqtrade-lab-subjective-grid-result-v0"
PATHS = ("O-H-L-C", "O-L-H-C")
RESULT_FILES = {"result.json", "summary.md"}
RESULT_ROOT_KEYS = {
    "schema",
    "gate",
    "input",
    "baselines",
    "scenarios",
    "assumptions_and_limits",
}
GATE_KEYS = {
    "verdict",
    "economic_evidence_status",
    "claim_boundary",
    "intrabar_path_sensitive",
    "path_metrics_differ_same_conclusion",
}
METRIC_KEYS = {
    "terminal_equity_quote",
    "total_pnl_quote",
    "total_return",
    "completed_grid_profit_quote",
    "unmatched_inventory_pnl_quote",
    "fees_quote",
    "slippage_quote",
    "turnover_quote",
    "maximum_inventory_base",
    "maximum_drawdown",
    "terminal_cash_quote",
    "terminal_inventory",
    "buy_fills",
    "sell_fills",
    "completed_cycles",
    "rejected_buys",
    "halted_after_out_of_range_close",
    "out_of_range",
    "pnl_reconciliation_error_quote",
    "accounting_identity_pass",
}
CONCLUSION_KEYS = {
    "mechanism_exercised",
    "beats_cash",
    "beats_buy_and_hold",
    "range_contained",
    "scenario_pass",
}

ROOT_KEYS = {
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
}
NESTED_KEYS = {
    "evaluation_window": {"start", "end", "candle_interval_seconds"},
    "grid": {"type", "lower", "upper", "count", "spacing"},
    "capital": {"starting_quote", "per_grid_quote", "max_inventory_base"},
    "costs": {"fee_rate", "slippage_rate"},
    "out_of_range": {"rule", "stop_price"},
}


def _ticket_value() -> Dict[str, Any]:
    return json.loads(TICKET_PATH.read_text(encoding="utf-8"))


def _json_bytes(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            indent=2,
        )
        + "\n"
    ).encode("utf-8")


def _csv_bytes(*rows: str) -> bytes:
    return (
        "timestamp,open,high,low,close,volume\n" + "\n".join(rows) + "\n"
    ).encode("utf-8")


def _ticket_for_data(
    data: bytes,
    *,
    mutate: Any = None,
) -> Tuple[Any, bytes]:
    value = _ticket_value()
    value["ohlcv_sha256"] = hashlib.sha256(data).hexdigest()
    if mutate is not None:
        mutate(value)
    raw = _json_bytes(value)
    return subjective_grid.load_ticket(raw), raw


def _plain(value: Any) -> Any:
    if is_dataclass(value):
        return _plain(asdict(value))
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _plain(child) for key, child in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(child) for child in value]
    return value


def _fixture_simulation() -> Dict[str, Any]:
    ticket = subjective_grid.load_ticket(TICKET_PATH.read_bytes())
    candles = subjective_grid.load_ohlcv(DATA_PATH.read_bytes(), ticket)
    result = _plain(subjective_grid.simulate(ticket, candles))
    assert isinstance(result, dict)
    return result


def _scenarios(result: Mapping[str, Any]) -> Dict[str, Mapping[str, Any]]:
    value = result.get("scenarios")
    assert isinstance(value, list)
    assert len(value) == 2
    assert all(isinstance(scenario, Mapping) for scenario in value)
    assert [scenario["intrabar_path"] for scenario in value] == list(PATHS)
    return {str(scenario["intrabar_path"]): scenario for scenario in value}


def _nested_mapping(value: Mapping[str, Any], *candidates: str) -> Mapping[str, Any]:
    for candidate in candidates:
        child = value.get(candidate)
        if isinstance(child, Mapping):
            return child
    raise AssertionError(f"none of {candidates!r} is a mapping")


def _grid_metrics(scenario: Mapping[str, Any]) -> Mapping[str, Any]:
    return _nested_mapping(scenario, "metrics")


def _decimal(value: Any) -> Decimal:
    assert isinstance(value, str), f"expected canonical decimal string, got {value!r}"
    return Decimal(value)


def _conclusion(scenario: Mapping[str, Any]) -> Mapping[str, Any]:
    return _nested_mapping(scenario, "conclusion", "conclusion_signature")


def test_fixture_provenance_and_hashes_are_frozen() -> None:
    data = DATA_PATH.read_bytes()
    ticket_bytes = TICKET_PATH.read_bytes()
    ticket = _ticket_value()
    provenance = PROVENANCE_PATH.read_text(encoding="utf-8")

    assert len(data) == 78
    assert hashlib.sha256(data).hexdigest() == (
        "c3050ccdd73dee1b7d671a6fa8eb53bf673964931822c5a3151b774ac48bd32f"
    )
    assert len(ticket_bytes) == 842
    assert hashlib.sha256(ticket_bytes).hexdigest() == (
        "e0898036d766ac6b3b596cb8d800d739c2b52dfe8958ddbf7798752f36972d22"
    )
    assert ticket["ohlcv_sha256"] == hashlib.sha256(data).hexdigest()
    assert "SAMPLE_ONLY" in provenance
    assert "not observed market data" in provenance
    assert ticket["ohlcv_sha256"] in provenance
    assert hashlib.sha256(ticket_bytes).hexdigest() in provenance


def test_t0_fixture_ticket_has_the_exact_frozen_shape() -> None:
    value = _ticket_value()

    assert set(value) == ROOT_KEYS
    for name, keys in NESTED_KEYS.items():
        assert set(value[name]) == keys
    assert value["schema"] == TICKET_SCHEMA
    assert value["market"] == "SPOT"
    assert value["direction"] == "LONG_ONLY"
    assert value["leverage"] == 1
    assert value["no_recenter"] is True
    assert value["evidence_status"] == "SAMPLE_ONLY"

    subjective_grid.load_ticket(TICKET_PATH.read_bytes())


@pytest.mark.parametrize(
    "section",
    (None, "evaluation_window", "grid", "capital", "costs", "out_of_range"),
)
def test_t0_ticket_rejects_unknown_fields_at_every_contract_level(
    section: Optional[str],
) -> None:
    value = _ticket_value()
    target = value if section is None else value[section]
    target["unexpected"] = "forbidden"

    with pytest.raises(subjective_grid.SubjectiveGridError, match="unknown|fields|shape"):
        subjective_grid.load_ticket(_json_bytes(value))


@pytest.mark.parametrize(
    ("section", "field"),
    (
        (None, "pair"),
        ("evaluation_window", "start"),
        ("grid", "spacing"),
        ("capital", "per_grid_quote"),
        ("costs", "fee_rate"),
        ("out_of_range", "rule"),
    ),
)
def test_t0_ticket_rejects_missing_required_fields(
    section: Optional[str],
    field: str,
) -> None:
    value = _ticket_value()
    target = value if section is None else value[section]
    del target[field]

    with pytest.raises(subjective_grid.SubjectiveGridError, match="missing|fields|shape"):
        subjective_grid.load_ticket(_json_bytes(value))


def test_t0_ticket_rejects_duplicate_json_keys() -> None:
    raw = TICKET_PATH.read_bytes().replace(
        b'  "pair": "SYNTH/USDT",',
        b'  "pair": "SYNTH/USDT",\n  "pair": "OTHER/USDT",',
        1,
    )

    with pytest.raises(subjective_grid.SubjectiveGridError, match="duplicate"):
        subjective_grid.load_ticket(raw)


@pytest.mark.parametrize("bad", ("NaN", "Infinity", "-Infinity"))
def test_t0_ticket_rejects_nonfinite_json_numbers(bad: str) -> None:
    raw = TICKET_PATH.read_bytes().replace(b'"fee_rate": "0.001"', f'"fee_rate": {bad}'.encode())

    with pytest.raises(subjective_grid.SubjectiveGridError, match="finite|JSON|decimal"):
        subjective_grid.load_ticket(raw)


@pytest.mark.parametrize("bad", ("NaN", "Infinity", "-Infinity"))
def test_t0_ticket_rejects_nonfinite_decimal_strings(bad: str) -> None:
    value = _ticket_value()
    value["costs"]["fee_rate"] = bad

    with pytest.raises(subjective_grid.SubjectiveGridError, match="finite|decimal"):
        subjective_grid.load_ticket(_json_bytes(value))


@pytest.mark.parametrize(
    ("section", "field"),
    (
        (None, "leverage"),
        ("evaluation_window", "candle_interval_seconds"),
        ("grid", "count"),
    ),
)
def test_t0_ticket_rejects_bool_as_integer(section: Optional[str], field: str) -> None:
    value = _ticket_value()
    target = value if section is None else value[section]
    target[field] = True

    with pytest.raises(subjective_grid.SubjectiveGridError, match="integer|int"):
        subjective_grid.load_ticket(_json_bytes(value))


@pytest.mark.parametrize(
    ("section", "field"),
    (
        ("grid", "lower"),
        ("grid", "upper"),
        ("grid", "spacing"),
        ("capital", "starting_quote"),
        ("capital", "per_grid_quote"),
        ("capital", "max_inventory_base"),
        ("costs", "fee_rate"),
        ("costs", "slippage_rate"),
    ),
)
def test_t0_ticket_requires_decimal_strings(section: str, field: str) -> None:
    value = _ticket_value()
    value[section][field] = 1

    with pytest.raises(subjective_grid.SubjectiveGridError, match="string|decimal"):
        subjective_grid.load_ticket(_json_bytes(value))


def test_t0_decimal_strings_are_limited_to_18_integer_and_fractional_digits() -> None:
    boundary = "999999999999999999.999999999999999999"
    value = _ticket_value()
    value["capital"]["starting_quote"] = boundary
    ticket = subjective_grid.load_ticket(_json_bytes(value))
    assert ticket.starting_quote == Decimal(boundary)

    invalid = (
        "1000000000000000000",
        "1.1234567890123456789",
    )
    for bad in invalid:
        value = _ticket_value()
        value["capital"]["starting_quote"] = bad
        with pytest.raises(subjective_grid.SubjectiveGridError, match="decimal"):
            subjective_grid.load_ticket(_json_bytes(value))

    data = _csv_bytes(
        f"2026-01-02T00:00:00Z,{boundary},{boundary},{boundary},{boundary},{boundary}"
    )
    ticket, _ = _ticket_for_data(data)
    candles = subjective_grid.load_ohlcv(data, ticket)
    assert candles[0].open == Decimal(boundary)
    assert candles[0].volume == Decimal(boundary)

    for bad in invalid:
        data = _csv_bytes(
            f"2026-01-02T00:00:00Z,{bad},{bad},{bad},{bad},{bad}"
        )
        ticket, _ = _ticket_for_data(data)
        with pytest.raises(subjective_grid.SubjectiveGridError, match="decimal"):
            subjective_grid.load_ohlcv(data, ticket)


@pytest.mark.parametrize(
    ("field", "bad"),
    (
        ("schema", "other-schema"),
        ("market", "FUTURES"),
        ("direction", "SHORT"),
        ("leverage", 2),
        ("no_recenter", False),
        ("evidence_status", "REAL"),
    ),
)
def test_t0_ticket_rejects_values_outside_the_spot_long_only_boundary(
    field: str,
    bad: Any,
) -> None:
    value = _ticket_value()
    value[field] = bad

    with pytest.raises(subjective_grid.SubjectiveGridError):
        subjective_grid.load_ticket(_json_bytes(value))


@pytest.mark.parametrize(
    ("decision_time", "start", "end"),
    (
        ("2026-01-02T00:00:00Z", "2026-01-02T00:00:00Z", "2026-01-02T01:00:00Z"),
        ("2026-01-02T00:00:01Z", "2026-01-02T00:00:00Z", "2026-01-02T01:00:00Z"),
        ("2026-01-01T00:00:00+00:00", "2026-01-02T00:00:00Z", "2026-01-02T01:00:00Z"),
        ("2026-01-01T00:00:00Z", "2026-01-02T01:00:00Z", "2026-01-02T01:00:00Z"),
        ("2026-01-01T00:00:00Z", "2026-01-02T00:30:00Z", "2026-01-02T01:00:00Z"),
    ),
)
def test_t0_ticket_enforces_causal_canonical_window(
    decision_time: str,
    start: str,
    end: str,
) -> None:
    value = _ticket_value()
    value["decision_time"] = decision_time
    value["evaluation_window"]["start"] = start
    value["evaluation_window"]["end"] = end

    with pytest.raises(subjective_grid.SubjectiveGridError, match="decision|window|UTC|interval"):
        subjective_grid.load_ticket(_json_bytes(value))


@pytest.mark.parametrize(
    ("field", "bad"),
    (
        ("type", "GEOMETRIC"),
        ("lower", "110"),
        ("upper", "90"),
        ("count", 0),
        ("count", 101),
        ("spacing", "4.999"),
    ),
)
def test_t0_grid_math_is_frozen(field: str, bad: Any) -> None:
    value = _ticket_value()
    value["grid"][field] = bad

    with pytest.raises(subjective_grid.SubjectiveGridError, match="grid|spacing|lower|upper|count"):
        subjective_grid.load_ticket(_json_bytes(value))


@pytest.mark.parametrize(
    ("section", "field", "bad"),
    (
        ("capital", "starting_quote", "0"),
        ("capital", "per_grid_quote", "0"),
        ("capital", "max_inventory_base", "0"),
        ("capital", "per_grid_quote", "1001"),
        ("costs", "fee_rate", "-0.001"),
        ("costs", "slippage_rate", "-0.001"),
        ("costs", "fee_rate", "1"),
    ),
)
def test_t0_capital_and_costs_fail_closed(
    section: str,
    field: str,
    bad: str,
) -> None:
    value = _ticket_value()
    value[section][field] = bad

    with pytest.raises(subjective_grid.SubjectiveGridError, match="capital|quote|inventory|fee|slippage|rate"):
        subjective_grid.load_ticket(_json_bytes(value))


def test_t0_out_of_range_contract_accepts_only_two_rules_and_null_stop_price() -> None:
    for rule in (
        "HOLD",
        "HALT_ON_FIRST_CLOSE_OUTSIDE_RANGE_KEEP_INVENTORY",
    ):
        value = _ticket_value()
        value["out_of_range"] = {"rule": rule, "stop_price": None}
        subjective_grid.load_ticket(_json_bytes(value))

    for rule, stop_price in (("UNSUPPORTED", None), ("HOLD", "80")):
        value = _ticket_value()
        value["out_of_range"] = {"rule": rule, "stop_price": stop_price}
        with pytest.raises(subjective_grid.SubjectiveGridError, match="out.of.range|rule|stop"):
            subjective_grid.load_ticket(_json_bytes(value))


@pytest.mark.parametrize(
    "header",
    (
        "timestamp,open,high,low,close",
        "timestamp,open,high,low,close,volume,extra",
        "timestamp,high,open,low,close,volume",
        "timestamp_utc,open,high,low,close,volume",
    ),
)
def test_t0_csv_header_is_exact(header: str) -> None:
    data = (header + "\n2026-01-02T00:00:00Z,100,110,90,100,1000\n").encode()
    ticket, _ = _ticket_for_data(data)

    with pytest.raises(subjective_grid.SubjectiveGridError, match="header|CSV"):
        subjective_grid.load_ohlcv(data, ticket)


def test_t0_ohlcv_hash_is_checked_before_parsing() -> None:
    ticket = subjective_grid.load_ticket(TICKET_PATH.read_bytes())
    changed = DATA_PATH.read_bytes().replace(b",1000\n", b",1001\n")

    with pytest.raises(subjective_grid.SubjectiveGridError, match="SHA|sha|hash"):
        subjective_grid.load_ohlcv(changed, ticket)


@pytest.mark.parametrize(
    "rows",
    (
        (
            "2026-01-02T00:00:00Z,100,110,90,100,1000",
            "2026-01-02T00:00:00Z,100,110,90,100,1000",
        ),
        (
            "2026-01-02T00:00:00Z,100,110,90,100,1000",
            "2026-01-02T02:00:00Z,100,110,90,100,1000",
        ),
        (
            "2026-01-02T01:00:00Z,100,110,90,100,1000",
            "2026-01-02T02:00:00Z,100,110,90,100,1000",
        ),
    ),
)
def test_t0_csv_requires_unique_complete_cadence(rows: Tuple[str, ...]) -> None:
    data = _csv_bytes(*rows)

    def three_hour_window(value: Dict[str, Any]) -> None:
        value["evaluation_window"]["end"] = "2026-01-02T03:00:00Z"

    ticket, _ = _ticket_for_data(data, mutate=three_hour_window)

    with pytest.raises(subjective_grid.SubjectiveGridError, match="timestamp|cadence|window|row"):
        subjective_grid.load_ohlcv(data, ticket)


@pytest.mark.parametrize(
    "row",
    (
        "2026-01-02T00:00:00+00:00,100,110,90,100,1000",
        "2026-01-02T00:00:00Z,0,110,90,100,1000",
        "2026-01-02T00:00:00Z,100,99,90,100,1000",
        "2026-01-02T00:00:00Z,100,110,101,100,1000",
        "2026-01-02T00:00:00Z,100,110,90,111,1000",
        "2026-01-02T00:00:00Z,100,110,90,100,-1",
        "2026-01-02T00:00:00Z,100,NaN,90,100,1000",
        "2026-01-02T00:00:00Z,100,110,90,100",
    ),
)
def test_t0_csv_rejects_noncanonical_or_invalid_ohlcv(row: str) -> None:
    data = _csv_bytes(row)
    ticket, _ = _ticket_for_data(data)

    with pytest.raises(subjective_grid.SubjectiveGridError, match="timestamp|OHLC|volume|row|decimal|CSV"):
        subjective_grid.load_ohlcv(data, ticket)


def test_t0_grid_levels_paths_costs_inventory_and_accounting_identity() -> None:
    result = _fixture_simulation()

    assert result["schema"] == RESULT_SCHEMA
    assert set(result) == RESULT_ROOT_KEYS
    gate = _nested_mapping(result, "gate")
    assert set(gate) == GATE_KEYS
    assert gate["economic_evidence_status"] == "SAMPLE_ONLY"
    assert gate["verdict"] == "INTRABAR_PATH_SENSITIVE"
    grid = _nested_mapping(_nested_mapping(result, "input"), "grid")
    assert grid["type"] == "ARITHMETIC"
    assert grid["spacing"] == "5"
    ticket = subjective_grid.load_ticket(TICKET_PATH.read_bytes())
    levels = [
        ticket.lower + ticket.spacing * index
        for index in range(ticket.grid_count + 1)
    ]
    assert levels == [
        Decimal("90"),
        Decimal("95"),
        Decimal("100"),
        Decimal("105"),
        Decimal("110"),
    ]

    frozen_drawdowns = {
        "O-H-L-C": "0.02458571428571428571428571428571428571428571428571",
        "O-L-H-C": "0.00556315789473684210526315789473684210526315789474",
    }
    signatures = []
    for path, scenario in _scenarios(result).items():
        assert set(scenario) == {"intrabar_path", "metrics", "conclusion"}
        assert scenario["intrabar_path"] == path
        metrics = _grid_metrics(scenario)
        assert set(metrics) == METRIC_KEYS
        total = _decimal(metrics["total_pnl_quote"])
        with localcontext() as context:
            context.prec = 100
            components = (
                _decimal(metrics["completed_grid_profit_quote"])
                + _decimal(metrics["unmatched_inventory_pnl_quote"])
                - _decimal(metrics["fees_quote"])
                - _decimal(metrics["slippage_quote"])
            )
        assert abs(total - components) <= Decimal("1e-40")
        assert _decimal(metrics["fees_quote"]) >= 0
        assert _decimal(metrics["slippage_quote"]) >= 0
        assert _decimal(metrics["turnover_quote"]) >= 0
        assert Decimal("0") <= _decimal(metrics["maximum_inventory_base"]) <= Decimal("2.2")
        assert metrics["maximum_drawdown"] == frozen_drawdowns[path]
        assert metrics["accounting_identity_pass"] is True
        assert abs(_decimal(metrics["pnl_reconciliation_error_quote"])) <= Decimal("1e-40")

        terminal = _nested_mapping(metrics, "terminal_inventory")
        assert {
            "base_quantity",
            "cost_basis_quote",
            "mark_value_quote",
            "mark_price",
        } == set(terminal)
        assert _decimal(terminal["base_quantity"]) >= 0
        assert _decimal(terminal["cost_basis_quote"]) >= 0
        assert _decimal(terminal["mark_value_quote"]) >= 0

        out_of_range = _nested_mapping(metrics, "out_of_range")
        assert set(out_of_range) == {
            "touch_candles",
            "close_candles",
            "close_sampled_seconds",
            "exact_intrabar_time",
        }
        assert out_of_range["exact_intrabar_time"] == "UNKNOWN_FROM_OHLCV"
        assert set(_nested_mapping(metrics, "rejected_buys")) == {
            "cash",
            "maximum_inventory",
        }
        for name in ("buy_fills", "sell_fills", "completed_cycles"):
            assert isinstance(metrics[name], int)

        conclusion = _conclusion(scenario)
        assert set(conclusion) == CONCLUSION_KEYS
        assert all(isinstance(value, bool) for value in conclusion.values())
        signatures.append(tuple(conclusion.values()))

    assert signatures[0] != signatures[1]
    baselines = _nested_mapping(result, "baselines")
    assert {"cash_no_trade", "buy_and_hold"} == set(baselines)
    for name in ("cash_no_trade", "buy_and_hold"):
        assert isinstance(baselines[name], Mapping)
        _decimal(baselines[name]["terminal_equity_quote"])


def test_t0_zero_costs_are_not_double_counted() -> None:
    value = _ticket_value()
    value["costs"] = {"fee_rate": "0", "slippage_rate": "0"}
    ticket = subjective_grid.load_ticket(_json_bytes(value))
    candles = subjective_grid.load_ohlcv(DATA_PATH.read_bytes(), ticket)
    result = _plain(subjective_grid.simulate(ticket, candles))

    for scenario in _scenarios(result).values():
        metrics = _grid_metrics(scenario)
        assert _decimal(metrics["fees_quote"]) == 0
        assert _decimal(metrics["slippage_quote"]) == 0
        with localcontext() as context:
            context.prec = 100
            components = (
                _decimal(metrics["completed_grid_profit_quote"])
                + _decimal(metrics["unmatched_inventory_pnl_quote"])
            )
        assert abs(_decimal(metrics["total_pnl_quote"]) - components) <= Decimal(
            "1e-40"
        )


def test_t0_all_completed_cells_leave_exactly_zero_terminal_inventory() -> None:
    data = _csv_bytes(
        "2026-01-02T00:00:00Z,110,110,90,110,1000",
    )

    def zero_costs_and_full_capacity(value: Dict[str, Any]) -> None:
        value["costs"] = {"fee_rate": "0", "slippage_rate": "0"}
        value["capital"]["max_inventory_base"] = "10"

    ticket, _ = _ticket_for_data(data, mutate=zero_costs_and_full_capacity)
    candles = subjective_grid.load_ohlcv(data, ticket)
    result = _plain(subjective_grid.simulate(ticket, candles))

    for scenario in _scenarios(result).values():
        metrics = _grid_metrics(scenario)
        assert metrics["buy_fills"] == 4
        assert metrics["sell_fills"] == 4
        assert metrics["completed_cycles"] == 4
        terminal = _nested_mapping(metrics, "terminal_inventory")
        assert terminal["base_quantity"] == "0"
        assert terminal["cost_basis_quote"] == "0"
        assert terminal["mark_value_quote"] == "0"
        assert metrics["unmatched_inventory_pnl_quote"] == "0"
        assert metrics["accounting_identity_pass"] is True


def test_t0_inventory_cap_rejects_oversized_lots_without_partial_fill_or_short() -> None:
    value = _ticket_value()
    value["capital"]["max_inventory_base"] = "0.5"
    ticket = subjective_grid.load_ticket(_json_bytes(value))
    candles = subjective_grid.load_ohlcv(DATA_PATH.read_bytes(), ticket)
    result = _plain(subjective_grid.simulate(ticket, candles))

    for scenario in _scenarios(result).values():
        metrics = _grid_metrics(scenario)
        terminal = _nested_mapping(metrics, "terminal_inventory")
        assert _decimal(metrics["maximum_inventory_base"]) <= Decimal("0.5")
        assert _decimal(terminal["base_quantity"]) >= 0
        assert _decimal(terminal["base_quantity"]) <= Decimal("0.5")


def test_t0_gap_and_turning_point_equality_do_not_duplicate_cell_state() -> None:
    data = _csv_bytes(
        "2026-01-02T00:00:00Z,100,105,95,100,1000",
        "2026-01-02T01:00:00Z,90,100,90,100,1000",
    )

    def two_candle_window(value: Dict[str, Any]) -> None:
        value["evaluation_window"]["end"] = "2026-01-02T02:00:00Z"

    ticket, _ = _ticket_for_data(data, mutate=two_candle_window)
    candles = subjective_grid.load_ohlcv(data, ticket)
    result = _plain(subjective_grid.simulate(ticket, candles))
    expected = {
        "O-H-L-C": (4, 3, 3, 2),
        "O-L-H-C": (3, 2, 2, 1),
    }

    for path, scenario in _scenarios(result).items():
        metrics = _grid_metrics(scenario)
        buy_fills, sell_fills, completed_cycles, rejected_inventory = expected[path]
        assert metrics["buy_fills"] == buy_fills
        assert metrics["sell_fills"] == sell_fills
        assert metrics["completed_cycles"] == completed_cycles
        assert metrics["rejected_buys"] == {
            "cash": 0,
            "maximum_inventory": rejected_inventory,
        }
        assert buy_fills == sell_fills + 1
        assert completed_cycles == sell_fills
        assert _decimal(metrics["maximum_inventory_base"]) <= ticket.max_inventory_base
        terminal = _nested_mapping(metrics, "terminal_inventory")
        assert terminal["base_quantity"] == "1"
        assert terminal["cost_basis_quote"] == "100"
        assert terminal["mark_value_quote"] == "100"
        assert terminal["mark_price"] == "100"
        assert metrics["accounting_identity_pass"] is True


def test_t0_halt_on_first_close_outside_range_keeps_inventory_and_reports_proxy_time() -> None:
    data = _csv_bytes(
        "2026-01-02T00:00:00Z,100,120,90,111,1000",
        "2026-01-02T01:00:00Z,111,115,90,100,1000",
    )

    def halted(value: Dict[str, Any]) -> None:
        value["evaluation_window"]["end"] = "2026-01-02T02:00:00Z"
        value["out_of_range"] = {
            "rule": "HALT_ON_FIRST_CLOSE_OUTSIDE_RANGE_KEEP_INVENTORY",
            "stop_price": None,
        }

    ticket, _ = _ticket_for_data(data, mutate=halted)
    candles = subjective_grid.load_ohlcv(data, ticket)
    result = _plain(subjective_grid.simulate(ticket, candles))

    for scenario in _scenarios(result).values():
        metrics = _grid_metrics(scenario)
        out_of_range = _nested_mapping(metrics, "out_of_range")
        assert out_of_range["touch_candles"] >= 1
        assert out_of_range["close_candles"] >= 1
        assert out_of_range["close_sampled_seconds"] >= 3600
        assert out_of_range["exact_intrabar_time"] == "UNKNOWN_FROM_OHLCV"
        assert metrics["halted_after_out_of_range_close"] is True
        terminal = _nested_mapping(metrics, "terminal_inventory")
        assert _decimal(terminal["base_quantity"]) >= 0


def test_t0_hold_resumes_after_out_of_range_close_while_halt_keeps_inventory() -> None:
    data = _csv_bytes(
        "2026-01-02T00:00:00Z,100,105,89,89,1000",
        "2026-01-02T01:00:00Z,100,105,95,100,1000",
    )

    results = {}
    for rule in (
        "HOLD",
        "HALT_ON_FIRST_CLOSE_OUTSIDE_RANGE_KEEP_INVENTORY",
    ):
        def two_candle_rule(value: Dict[str, Any], selected_rule: str = rule) -> None:
            value["evaluation_window"]["end"] = "2026-01-02T02:00:00Z"
            value["out_of_range"] = {
                "rule": selected_rule,
                "stop_price": None,
            }

        ticket, _ = _ticket_for_data(data, mutate=two_candle_rule)
        candles = subjective_grid.load_ohlcv(data, ticket)
        results[rule] = _scenarios(_plain(subjective_grid.simulate(ticket, candles)))

    halt_counts = {
        "O-H-L-C": (2, 0),
        "O-L-H-C": (4, 2),
    }
    for path in PATHS:
        hold = _grid_metrics(results["HOLD"][path])
        halt = _grid_metrics(
            results["HALT_ON_FIRST_CLOSE_OUTSIDE_RANGE_KEEP_INVENTORY"][path]
        )
        assert (halt["buy_fills"], halt["sell_fills"]) == halt_counts[path]
        assert hold["buy_fills"] > halt["buy_fills"]
        assert hold["sell_fills"] > halt["sell_fills"]
        assert hold["halted_after_out_of_range_close"] is False
        assert halt["halted_after_out_of_range_close"] is True

        for metrics in (hold, halt):
            out_of_range = _nested_mapping(metrics, "out_of_range")
            assert out_of_range["close_candles"] == 1
            assert out_of_range["close_sampled_seconds"] == 3600
            terminal = _nested_mapping(metrics, "terminal_inventory")
            base = _decimal(terminal["base_quantity"])
            mark = _decimal(terminal["mark_price"])
            mark_value = _decimal(terminal["mark_value_quote"])
            assert base > 0
            assert _decimal(terminal["cost_basis_quote"]) > 0
            with localcontext() as context:
                context.prec = 100
                assert mark_value == base * mark
            assert metrics["accounting_identity_pass"] is True


def test_t1_cli_help_and_invalid_input_are_bounded(tmp_path: Path) -> None:
    help_result = subprocess.run(
        [sys.executable, str(CLI), "--help"],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert help_result.returncode == 0
    assert "--ticket" in help_result.stdout
    assert "--data" in help_result.stdout
    assert "--output-dir" in help_result.stdout

    output = tmp_path / "must-not-exist"
    failed = subprocess.run(
        [
            sys.executable,
            str(CLI),
            "--ticket",
            str(TICKET_PATH),
            "--data",
            str(tmp_path / "missing.csv"),
            "--output-dir",
            str(output),
        ],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert failed.returncode == 2
    assert failed.stdout == ""
    assert failed.stderr.count("\n") == 1
    assert "Traceback" not in failed.stderr
    assert not output.exists()


def test_t1_evaluator_refuses_to_overwrite_an_existing_output(tmp_path: Path) -> None:
    output = tmp_path / "existing"
    output.mkdir()
    marker = output / "owned-by-user.txt"
    marker.write_text("unchanged\n", encoding="utf-8")

    with pytest.raises(subjective_grid.SubjectiveGridError, match="exist|output"):
        subjective_grid.evaluate_subjective_grid(TICKET_PATH, DATA_PATH, output)

    assert marker.read_text(encoding="utf-8") == "unchanged\n"
    assert set(output.iterdir()) == {marker}


def test_t1_atomic_publication_failure_leaves_no_output_or_temporary_residue(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "result-bundle"

    def fail_publish(_source: Path, _destination: Path) -> None:
        raise OSError("injected publication failure")

    monkeypatch.setattr(
        subjective_grid,
        "_publish_directory_exclusive",
        fail_publish,
    )

    with pytest.raises(
        (subjective_grid.SubjectiveGridError, OSError),
        match="publication|injected",
    ):
        subjective_grid.evaluate_subjective_grid(TICKET_PATH, DATA_PATH, output)

    assert not output.exists()
    assert list(tmp_path.iterdir()) == []


def test_t1_exclusive_publication_never_replaces_a_concurrent_empty_target(
    tmp_path: Path,
) -> None:
    source = tmp_path / "complete-staging"
    target = tmp_path / "concurrent-target"
    source.mkdir()
    target.mkdir()
    staged = source / "result.json"
    staged.write_text("complete\n", encoding="utf-8")

    with pytest.raises(subjective_grid.SubjectiveGridError, match="concurrent|created"):
        subjective_grid._publish_directory_exclusive(source, target)

    assert staged.read_text(encoding="utf-8") == "complete\n"
    assert list(target.iterdir()) == []


def test_t1_parent_fsync_failure_after_publish_keeps_successful_final_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "atomically-visible"
    original_fsync = os.fsync
    original_publish = subjective_grid._publish_directory_exclusive
    state = {"published": False, "post_publish_fsync_calls": 0}

    def mark_published(source: Path, destination: Path) -> None:
        original_publish(source, destination)
        state["published"] = True

    def fail_post_publish_parent_fsync(file_descriptor: int) -> None:
        if state["published"]:
            state["post_publish_fsync_calls"] += 1
            raise OSError("injected post-publish parent fsync failure")
        original_fsync(file_descriptor)

    monkeypatch.setattr(
        subjective_grid,
        "_publish_directory_exclusive",
        mark_published,
    )
    monkeypatch.setattr(subjective_grid.os, "fsync", fail_post_publish_parent_fsync)

    result = subjective_grid.evaluate_subjective_grid(TICKET_PATH, DATA_PATH, output)

    assert result["gate"]["verdict"] == "INTRABAR_PATH_SENSITIVE"
    assert state == {"published": True, "post_publish_fsync_calls": 1}
    assert output.is_dir()
    assert {path.name for path in output.iterdir()} == RESULT_FILES
    assert json.loads((output / "result.json").read_bytes()) == result
    assert not list(tmp_path.glob(".*.*.tmp"))


def test_t2_real_cli_is_deterministic_complete_atomic_and_schema_independent(
    tmp_path: Path,
) -> None:
    before_schema_sha = hashlib.sha256(SCHEMA_PATH.read_bytes()).hexdigest()
    outputs = [tmp_path / "first", tmp_path / "second"]
    completed = []
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"

    for output in outputs:
        invocation = subprocess.run(
            [
                sys.executable,
                str(CLI),
                "--ticket",
                str(TICKET_PATH),
                "--data",
                str(DATA_PATH),
                "--output-dir",
                str(output),
            ],
            cwd=PROJECT_ROOT,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )
        completed.append(invocation)
        assert invocation.returncode == 0, invocation.stderr
        assert invocation.stderr == ""
        assert output.is_dir()
        assert {path.name for path in output.iterdir()} == RESULT_FILES

    assert (outputs[0] / "result.json").read_bytes() == (
        outputs[1] / "result.json"
    ).read_bytes()
    assert (outputs[0] / "summary.md").read_bytes() == (
        outputs[1] / "summary.md"
    ).read_bytes()
    assert not list(tmp_path.glob(".*.*.tmp"))

    result_bytes = (outputs[0] / "result.json").read_bytes()
    result = json.loads(result_bytes)
    assert result["schema"] == RESULT_SCHEMA
    assert set(result) == RESULT_ROOT_KEYS
    gate = _nested_mapping(result, "gate")
    assert set(gate) == GATE_KEYS
    assert gate["economic_evidence_status"] == "SAMPLE_ONLY"
    assert gate["verdict"] == "INTRABAR_PATH_SENSITIVE"
    input_contract = _nested_mapping(result, "input")
    assert input_contract["ticket_sha256"] == hashlib.sha256(
        TICKET_PATH.read_bytes()
    ).hexdigest()
    assert input_contract["ohlcv_sha256"] == hashlib.sha256(
        DATA_PATH.read_bytes()
    ).hexdigest()
    _scenarios(result)

    for scenario in _scenarios(result).values():
        assert set(scenario) == {"intrabar_path", "metrics", "conclusion"}
        metrics = _grid_metrics(scenario)
        assert set(metrics) == METRIC_KEYS
        assert set(_conclusion(scenario)) == CONCLUSION_KEYS
        assert set(_nested_mapping(metrics, "terminal_inventory")) == {
            "base_quantity",
            "cost_basis_quote",
            "mark_value_quote",
            "mark_price",
        }
        assert _nested_mapping(metrics, "out_of_range")[
            "exact_intrabar_time"
        ] == "UNKNOWN_FROM_OHLCV"

    assert {"cash_no_trade", "buy_and_hold"} == set(
        _nested_mapping(result, "baselines")
    )

    summary = (outputs[0] / "summary.md").read_text(encoding="utf-8")
    assert "SAMPLE_ONLY" in summary
    assert "INTRABAR_PATH_SENSITIVE" in summary
    assert "O-H-L-C" in summary
    assert "O-L-H-C" in summary
    assert str(PROJECT_ROOT) not in summary
    assert str(tmp_path) not in result_bytes.decode("utf-8")
    assert hashlib.sha256(SCHEMA_PATH.read_bytes()).hexdigest() == before_schema_sha


def test_t2_changed_data_fails_hash_gate_without_publishing(tmp_path: Path) -> None:
    changed = tmp_path / "changed.csv"
    changed.write_bytes(DATA_PATH.read_bytes().replace(b",1000\n", b",1001\n"))
    output = tmp_path / "must-not-exist"

    completed = subprocess.run(
        [
            sys.executable,
            str(CLI),
            "--ticket",
            str(TICKET_PATH),
            "--data",
            str(changed),
            "--output-dir",
            str(output),
        ],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert completed.stdout == ""
    assert completed.stderr.count("\n") == 1
    assert "Traceback" not in completed.stderr
    assert not output.exists()
    assert not list(tmp_path.glob(".*.*.tmp"))
