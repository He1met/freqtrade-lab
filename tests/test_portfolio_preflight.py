"""Synthetic control metadata only: no price, native engine, or database."""
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys

import pytest

from lab.portfolio_preflight import AdmissionError, load_protocol, native_job_plan, preflight, read_json

NOW = datetime(2026, 9, 7, 12, tzinfo=timezone.utc)


def registry():
    return {"schema": "portfolio-window-metadata-v1", "ledger_sha256": "a"*64,
            "restrictions_complete": True, "pool": {"start": "2022-01-01", "end": "2024-01-01"},
            "allowed_seen": [{"symbol": s, "start": "2021-04-02", "end": "2024-01-01",
                              "evidence_sha256": "b"*64} for s in ("BTCUSDT", "ETHUSDT")],
            "protected": []}


def exchange():
    return {"schema": "portfolio-exchange-metadata-v1", "observed_at": "2026-09-07T10:00:00Z",
            "source": "https://fapi.binance.com/fapi/v1/exchangeInfo", "response_sha256": "c"*64,
            "symbols": [{"symbol": s, "status": "TRADING", "contractType": "PERPETUAL",
                         "quoteAsset": "USDT", "marginAsset": "USDT", "min_notional": "20",
                         "min_qty": "0.001", "max_qty": "1000", "step_size": "0.001",
                         "tick_size": "0.01"} for s in ("BTCUSDT", "ETHUSDT")]}


def report(r=None, e=None):
    return preflight(load_protocol(), registry=r if r is not None else registry(),
                     exchange=e if e is not None else exchange(), now=NOW)


def test_budget_unique_jobs_and_no_pair_double_counting():
    jobs = native_job_plan(load_protocol())
    assert len(jobs) == len({j["key"] for j in jobs}) == 92
    assert Counter(j["role"] for j in jobs) == {"SYNTHETIC": 8, "TRAINING": 24, "VALIDATION": 48, "FINAL_DIAGNOSTIC": 12}
    assert all(j["native_calls"] == 1 and j["symbols"] == ["BTCUSDT", "ETHUSDT"] for j in jobs)
    assert report()["budget"]["maximum"] == len(jobs)+4


def test_frozen_selection_does_not_reintroduce_all_fold_profit_or_degenerate_C():
    """Contract regression; not a fabricated implementation of economic tests.

    Native statistics are a later slice. Binding BOTH comparators and strict
    positive increments ensures the future evaluator cannot pass C == B solely
    on half-risk-B. Calendar means prevent weighting overlap dates four times.
    """
    p = load_protocol()
    selection = p["selection"]
    assert selection["final_parameters"] == "UNIQUE_DATE_MEAN_TRAINING_RETURN_CHAIN_NET_GE_ZERO_THEN_UTILITY"
    assert selection["final_training_risk_gate"] == "EACH_FOLD_DD_LE_20_SOURCE_CAUSAL_COST_VALID"
    assert selection["training_overlap_weight"] == "EQUAL_MEAN_OF_AVAILABLE_FOLD_RETURNS_PER_UTC_DATE_THEN_EACH_DATE_ONCE"
    assert selection["C_required_comparators"] == ["B", "half-risk-B"]
    assert selection["C_adoption"] == "POSITIVE_PAIRED_42_DAY_BLOCK_UTILITY_INCREMENT_VS_EACH_REQUIRED_COMPARATOR_CI_LOW_GT_ZERO"
    assert selection["half_risk_B_label"] == "FIXED_LOWER_RISK_CONTROL_NOT_REALIZED_RISK_MATCH"
    assert "risk_matched_B_multiplier" not in p["signals"]


def test_metadata_success_never_promotes_data_economics_or_execution():
    r = report()
    assert r["status"] == "METADATA_VALIDATED_ONLY"
    assert r["market_execution_allowed"] is r["market_data_ready"] is False
    assert r["economic_result"] is r["forward_start"] is None
    assert r["budget"]["global_calls_consumed"] is None
    assert r["folds"][0] == {"fold": 1, "training_start": "2022-01-01", "training_end": "2023-01-01", "validation_start": "2023-01-01", "validation_end": "2023-04-01"}
    assert r["folds"][-1]["validation_end"] == "2024-01-01"


def test_missing_inputs_preserve_unknown():
    r = preflight(load_protocol(), now=NOW)
    assert r["status"] == "BLOCKED_DATA"
    assert r["ledger_snapshot_sha256"] is None
    assert r["economic_result"] is None


@pytest.mark.parametrize("symbol", ["BTCUSDT", "ETHUSDT", "*"])
def test_protected_warmup_is_not_opened(symbol):
    r = registry()
    r["protected"] = [{"symbol": symbol, "start": "2021-12-01", "end": "2022-01-01", "evidence_sha256": "d"*64}]
    assert "PROTECTED_CALENDAR_OVERLAP_INCLUDING_WARMUP" in report(r)["blockers"]


def test_other_asset_protection_is_not_a_blanket_calendar_ban():
    r = registry()
    r["protected"] = [{"symbol": "SOLUSDT", "start": "2022-01-01", "end": "2024-01-01", "evidence_sha256": "d"*64}]
    assert report(r)["status"] == "METADATA_VALIDATED_ONLY"


@pytest.mark.parametrize("change", ["gap", "one_pair", "no_warmup", "unknown", "short_pool", "future"])
def test_missing_permission_coverage_blocks(change):
    r = registry()
    if change == "gap": r["allowed_seen"][0]["end"] = "2023-12-31"
    elif change == "one_pair": r["allowed_seen"].pop()
    elif change == "no_warmup": r["allowed_seen"][0]["start"] = "2022-01-01"
    elif change == "unknown": r["restrictions_complete"] = False
    elif change == "short_pool": r["pool"]["end"] = "2023-01-01"
    elif change == "future": r["pool"] = {"start": "2025-01-01", "end": "2027-01-01"}
    assert report(r)["status"] == "BLOCKED_DATA"


@pytest.mark.parametrize("change", ["bool", "extra", "sha", "date", "spot", "reversed"])
def test_malformed_registry_rejected(change):
    r = registry()
    if change == "bool": r["restrictions_complete"] = 1
    elif change == "extra": r["command"] = "untrusted"
    elif change == "sha": r["ledger_sha256"] = "unknown"
    elif change == "date": r["pool"]["start"] = "20220101"
    elif change == "spot": r["allowed_seen"][0]["symbol"] = "BTC/USDT"
    elif change == "reversed": r["allowed_seen"][0]["end"] = "2021-01-01"
    with pytest.raises(AdmissionError): report(r)


@pytest.mark.parametrize("change", ["nan", "zero", "bool", "identity", "duplicate", "bounds", "source", "timestamp"])
def test_bad_exchange_metadata_rejected(change):
    e = exchange()
    if change == "nan": e["symbols"][0]["step_size"] = "NaN"
    elif change == "zero": e["symbols"][0]["step_size"] = "0"
    elif change == "bool": e["symbols"][0]["step_size"] = True
    elif change == "identity": e["symbols"][0]["symbol"] = "BTCUSD"
    elif change == "duplicate": e["symbols"][1] = deepcopy(e["symbols"][0])
    elif change == "bounds": e["symbols"][0]["min_qty"] = "2000"
    elif change == "source": e["source"] = "https://example.invalid"
    elif change == "timestamp": e["observed_at"] = False
    with pytest.raises(AdmissionError): report(e=e)


@pytest.mark.parametrize("time", ["2026-09-05T00:00:00Z", "2026-09-08T00:00:00Z", "2026-09-07T10:00:00"])
def test_metadata_freshness_is_required(time):
    e = exchange(); e["observed_at"] = time
    assert report(e=e)["status"] == "BLOCKED_METADATA"


def test_protocol_cannot_expand_budget_or_change_economic_floor(tmp_path):
    p = load_protocol(); p["budget"]["max_native_calls"] = 97
    with pytest.raises(AdmissionError): preflight(p)
    path = tmp_path/"protocol.json"; path.write_text(json.dumps(p))
    with pytest.raises(AdmissionError): load_protocol(path)
    p = load_protocol(); p["evidence"]["net_usdt_floor"] = "-0.01"
    with pytest.raises(AdmissionError): native_job_plan(p)


@pytest.mark.parametrize("raw", ['{"a":1,"a":2}', '{"a":NaN}', '[]'])
def test_json_ambiguity_rejected(tmp_path, raw):
    p = tmp_path/"bad.json"; p.write_text(raw)
    with pytest.raises(AdmissionError): read_json(p)


def test_real_cli_success_and_failure_without_side_effects(tmp_path):
    r, e = tmp_path/"registry.json", tmp_path/"exchange.json"
    r.write_text(json.dumps(registry()))
    snapshot = exchange(); snapshot["observed_at"] = datetime.now(timezone.utc).isoformat()
    e.write_text(json.dumps(snapshot))
    script = Path(__file__).resolve().parents[1]/"scripts/check_portfolio_pilot.py"
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    result = subprocess.run([sys.executable, str(script), "--registry", str(r), "--exchange-info", str(e)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["status"] == "METADATA_VALIDATED_ONLY"
    result = subprocess.run([sys.executable, str(script)], capture_output=True, text=True)
    assert result.returncode == 2
    assert json.loads(result.stdout)["status"] == "BLOCKED_DATA"
    result = subprocess.run([sys.executable, str(script), "--registry", str(tmp_path/"missing-secret-path")], capture_output=True, text=True)
    assert result.returncode == 2 and "missing-secret-path" not in result.stdout
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == before
