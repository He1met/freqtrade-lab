"""Public REST contract tests using only generated rows and temporary SQLite."""
import json
import sys
import traceback
from datetime import datetime, timezone

import pytest

from tests.test_fetch_okx_public_data import (
    PROFILE_HELPER,
    _FundingExchange,
    _configure_profile_helper,
    _runtime,
    profile_acquisition_module,
)


@pytest.fixture
def rest_module(profile_acquisition_module, monkeypatch):
    module = profile_acquisition_module
    monkeypatch.setattr(module, "_configured", lambda: {})
    module.SEARCH_START = datetime(2026, 6, 10, tzinfo=timezone.utc)
    module.DATA_END_MS = int(module.SEARCH_START.timestamp() * 1000) + 86_400_000
    module.SYMBOL = "NEAR/USDT:USDT"
    module.INSTRUMENT_ID = "NEAR-USDT-SWAP"
    monkeypatch.setattr(module, "request_receipt", lambda exchange, label: {"label": label})
    return module


class FundingExchange(_FundingExchange):
    def __init__(self, module, mutate=lambda rows: None, reverse=False):
        super().__init__(module.FUNDING_INTERVAL_MS)
        self.mutate = mutate
        self.reverse = reverse
        self.parsed = False

    def publicGetPublicFundingRateHistory(self, params):
        response = super().publicGetPublicFundingRateHistory(params)
        self.mutate(response["data"])
        if self.reverse:
            response["data"].reverse()
        response["data"] = response["data"][:params["limit"]]
        self.last_http_response = json.dumps(response)
        return response

    def fetch_funding_rate_history(self, *args, **kwargs):
        result = super().fetch_funding_rate_history(*args, **kwargs)
        self.parsed = True
        return result


@pytest.mark.parametrize("reverse", [False, True], ids=["oldest-first", "newest-first"])
def test_rest_funding_valid_output_is_unchanged(rest_module, reverse):
    module = rest_module
    exchange = FundingExchange(module, reverse=reverse)
    endpoint = exchange.publicGetPublicFundingRateHistory
    rows = module.fetch_rest_funding_history(exchange, [])
    start = int(module.SEARCH_START.timestamp() * 1000)
    assert [(r["timestamp"], r["symbol"], r["fundingRate"]) for r in rows] == [
        (t, module.SYMBOL, .0001) for t in range(start, module.DATA_END_MS, module.FUNDING_INTERVAL_MS)
    ]
    assert exchange.calls == [(module.SYMBOL, start, 4, {"after": module.DATA_END_MS})]
    assert exchange.publicGetPublicFundingRateHistory == endpoint


@pytest.mark.parametrize("reverse", [False, True], ids=["oldest-first", "newest-first"])
@pytest.mark.parametrize("position", [0, 1, 3], ids=["head", "middle", "tail-counterexample"])
def test_rest_funding_extra_event_rejected_before_ccxt_can_hide_it(rest_module, reverse, position):
    module = rest_module
    start = int(module.SEARCH_START.timestamp() * 1000)
    def extra(rows):
        rows.insert(position, {**rows[-1], "fundingTime": str(start + 72_000_000)})
    exchange = FundingExchange(module, extra, reverse)
    endpoint = exchange.publicGetPublicFundingRateHistory
    with pytest.raises(RuntimeError, match="raw event count"):
        module.fetch_rest_funding_history(exchange, [])
    assert exchange.calls[0][2] == 4  # The old N=3 request could hide the tail event.
    assert not exchange.parsed
    assert exchange.publicGetPublicFundingRateHistory == endpoint


@pytest.mark.parametrize("case", [
    "missing", "duplicate", "offset200ms", "four-hour", "start-minus1ms", "exclusive-stop",
    "wrong-instrument", "missing-instrument", "boolean-time", "integer-time", "leading-zero-time",
    "float-time", "unicode-time", "missing-time", "missing-realized", "predicted-only",
    "nan-rate", "infinite-rate", "overflow-rate", "underflow-rate", "boolean-rate", "number-rate", "blank-rate",
    "non-numeric-rate", "non-object-row",
])
def test_rest_funding_invalid_raw_rows_fail_closed(rest_module, case):
    module = rest_module
    def mutate(rows):
        if case == "missing": rows.pop(); return
        if case == "duplicate": rows[1] = dict(rows[0]); return
        if case == "four-hour": rows[1]["fundingTime"] = str(int(rows[0]["fundingTime"]) + 14_400_000); return
        if case == "offset200ms": rows[1]["fundingTime"] = str(int(rows[1]["fundingTime"]) + 200); return
        if case == "start-minus1ms": rows[0]["fundingTime"] = str(int(rows[0]["fundingTime"]) - 1); return
        if case == "exclusive-stop": rows[-1]["fundingTime"] = str(module.DATA_END_MS); return
        if case == "wrong-instrument": rows[1]["instId"] = "OTHER-USDT-SWAP"; return
        if case == "missing-instrument": rows[1].pop("instId"); return
        if case == "non-object-row": rows[1] = []; return
        if case in ("missing-realized", "predicted-only"): rows[1].pop("realizedRate"); return
        if case == "missing-time": rows[1].pop("fundingTime"); return
        field, value = {
            "boolean-time": ("fundingTime", True),
            "integer-time": ("fundingTime", int(rows[1]["fundingTime"])),
            "leading-zero-time": ("fundingTime", "0" + rows[1]["fundingTime"]),
            "float-time": ("fundingTime", rows[1]["fundingTime"] + ".0"),
            "unicode-time": ("fundingTime", "１" + rows[1]["fundingTime"][1:]),
            "nan-rate": ("realizedRate", "NaN"),
            "infinite-rate": ("realizedRate", "-Infinity"),
            "overflow-rate": ("realizedRate", "1e999"),
            "underflow-rate": ("realizedRate", "1e-999"),
            "boolean-rate": ("realizedRate", True),
            "number-rate": ("realizedRate", .0001),
            "blank-rate": ("realizedRate", " "),
            "non-numeric-rate": ("realizedRate", "PRIVATE_RATE_MUST_NOT_LEAK"),
        }[case]
        rows[1][field] = value
    exchange = FundingExchange(module, mutate)
    with pytest.raises(RuntimeError) as error:
        module.fetch_rest_funding_history(exchange, [])
    assert not exchange.parsed
    assert "PRIVATE_RATE_MUST_NOT_LEAK" not in "".join(traceback.format_exception(error.value))


@pytest.mark.parametrize("case", ["absent", "malformed", "duplicate-key", "nan-json", "error", "wrong-data", "disagrees"])
def test_rest_funding_raw_response_evidence_required(rest_module, case):
    module = rest_module
    exchange = FundingExchange(module)
    endpoint = exchange.publicGetPublicFundingRateHistory
    def changed(params):
        response = endpoint(params)
        if case == "absent": exchange.last_http_response = None
        elif case == "malformed": exchange.last_http_response = "PRIVATE_RATE_MUST_NOT_LEAK"
        elif case == "duplicate-key": exchange.last_http_response = '{"code":"0","code":"0","data":[]}'
        elif case == "nan-json": exchange.last_http_response = '{"code":"0","data":NaN}'
        elif case == "error":
            response["code"] = "1"; response["msg"] = "PRIVATE_RATE_MUST_NOT_LEAK"
            exchange.last_http_response = json.dumps(response)
        elif case == "wrong-data": response["data"] = {}; exchange.last_http_response = json.dumps(response)
        elif case == "disagrees": response = {"code": "0", "data": []}
        return response
    exchange.publicGetPublicFundingRateHistory = changed
    with pytest.raises(RuntimeError) as error:
        module.fetch_rest_funding_history(exchange, [])
    assert not exchange.parsed
    assert "PRIVATE_RATE_MUST_NOT_LEAK" not in "".join(traceback.format_exception(error.value))


@pytest.mark.parametrize("case", ["drop", "duplicate", "filtered-raw-only", "timestamp", "rate", "symbol", "bool-rate", "bool-time"])
def test_rest_funding_ccxt_output_must_match_unfiltered_evidence(rest_module, case):
    module = rest_module
    exchange = FundingExchange(module)
    fetch = exchange.fetch_funding_rate_history
    def changed(*args, **kwargs):
        if case == "filtered-raw-only":
            return [{"timestamp": int(module.SEARCH_START.timestamp()*1000)+i*module.FUNDING_INTERVAL_MS,
                     "fundingRate": .0001, "symbol": module.SYMBOL} for i in range(3)]
        rows = fetch(*args, **kwargs)
        if case == "drop": rows.pop()
        elif case == "duplicate": rows[1] = rows[0]
        elif case == "timestamp": rows[1]["timestamp"] += 1
        elif case == "rate": rows[1]["fundingRate"] = .9
        elif case == "symbol": rows[1]["symbol"] = "OTHER/USDT:USDT"
        elif case == "bool-rate": rows[1]["fundingRate"] = True
        elif case == "bool-time": rows[1]["timestamp"] = True
        return rows
    exchange.fetch_funding_rate_history = changed
    with pytest.raises(RuntimeError, match="CCXT parsed"):
        module.fetch_rest_funding_history(exchange, [])


def test_rest_funding_endpoint_exception_is_sanitized_and_restored(rest_module):
    exchange = FundingExchange(rest_module)
    def endpoint(params): raise ValueError("PRIVATE_RATE_MUST_NOT_LEAK")
    exchange.publicGetPublicFundingRateHistory = endpoint
    with pytest.raises(RuntimeError, match="public funding request failed") as error:
        rest_module.fetch_rest_funding_history(exchange, [])
    assert "PRIVATE_RATE_MUST_NOT_LEAK" not in "".join(traceback.format_exception(error.value))
    assert exchange.publicGetPublicFundingRateHistory is endpoint


def test_rest_funding_parser_exception_is_sanitized_and_endpoint_restored(rest_module):
    exchange = FundingExchange(rest_module)
    endpoint = exchange.publicGetPublicFundingRateHistory
    fetch = exchange.fetch_funding_rate_history
    def failing_parser(*args, **kwargs):
        fetch(*args, **kwargs)
        raise ValueError("PRIVATE_RATE_MUST_NOT_LEAK")
    exchange.fetch_funding_rate_history = failing_parser
    with pytest.raises(RuntimeError, match="CCXT funding parsing failed") as error:
        rest_module.fetch_rest_funding_history(exchange, [])
    assert "PRIVATE_RATE_MUST_NOT_LEAK" not in "".join(traceback.format_exception(error.value))
    assert exchange.publicGetPublicFundingRateHistory == endpoint


def test_rest_funding_checks_all_timestamps_before_rates(rest_module):
    exchange = FundingExchange(rest_module)
    def mutate(rows):
        rows[0]["realizedRate"] = "PRIVATE_RATE_MUST_NOT_LEAK"
        rows[-1]["fundingTime"] = str(rest_module.DATA_END_MS)
    exchange.mutate = mutate
    with pytest.raises(RuntimeError, match="raw timestamps"):
        rest_module.fetch_rest_funding_history(exchange, [])


def test_rest_funding_preserves_actual_positive_negative_zero_and_scientific_rates(rest_module):
    values = ["0", "-2e-4", "3.5e-5"]
    def mutate(rows):
        for row, rate in zip(rows, values):
            row["realizedRate"] = rate
            row["fundingRate"] = "PRIVATE_PREDICTED_RATE_NOT_A_SOURCE"
    rows = rest_module.fetch_rest_funding_history(FundingExchange(rest_module, mutate), [])
    assert [row["fundingRate"] for row in rows] == [0., -.0002, .000035]


@pytest.mark.parametrize("drift", ["before", "limit"])
def test_rest_funding_rejects_ccxt_request_contract_drift(rest_module, drift):
    exchange = FundingExchange(rest_module)
    def fetch(symbol, *, since, limit, params):
        return exchange.publicGetPublicFundingRateHistory({
            "instId": rest_module.INSTRUMENT_ID,
            "before": since - 1 + (1 if drift == "before" else 0),
            "limit": limit - (1 if drift == "limit" else 0), **params,
        })
    exchange.fetch_funding_rate_history = fetch
    with pytest.raises(RuntimeError, match="CCXT request contract changed"):
        rest_module.fetch_rest_funding_history(exchange, [])


def test_rest_funding_main_failure_cleans_output_without_publication(
    profile_acquisition_module, monkeypatch, tmp_path, capsys
):
    module = profile_acquisition_module
    database, profile_id, _, window = _configure_profile_helper(module, tmp_path)
    output = tmp_path / "failed-source"
    sibling = tmp_path / "keep.txt"; sibling.write_text("keep")
    monkeypatch.setattr(sys, "argv", [str(PROFILE_HELPER), "--output-root", str(output),
        "--window-spec", str(window), "--profile-database", str(database),
        "--profile-id", profile_id, "--pre-roll-candles", "24"])
    monkeypatch.setattr(module, "validate_runtime", lambda: _runtime(module))
    # Force the REST branch without changing the global clock or obtaining real values.
    monkeypatch.setattr(module, "fetch_funding_history", lambda exchange, requests, **kwargs:
                        module.fetch_rest_funding_history(exchange, requests))
    def extra(rows): rows.append({**rows[-1], "fundingTime": str(int(rows[-1]["fundingTime"])+1),
                                 "realizedRate": "PRIVATE_RATE_MUST_NOT_LEAK"})
    exchange = FundingExchange(module, extra)
    closed = []
    market = {"id": module.INSTRUMENT_ID, "symbol": module.SYMBOL, "swap": True, "linear": True}
    exchange.public_get_public_instruments = lambda params: {"code": "0", "data": [{
        "instId": module.INSTRUMENT_ID, "instType": "SWAP", "settleCcy": "USDT", "state": "live"}]}
    exchange.parse_market = lambda instrument: market
    exchange.set_markets = lambda *args: None
    exchange.fetch_market_leverage_tiers = lambda *args: [{"symbol": module.SYMBOL}]
    exchange.close = lambda: closed.append(True)
    monkeypatch.setattr(module.transport.ccxt, "okx", lambda config: exchange)
    monkeypatch.setattr(module, "install_request_guard", lambda exchange: None)
    monkeypatch.setattr(module, "request_receipt", lambda exchange, label: {"label": label})
    monkeypatch.setattr(module, "fetch_profile_candles", lambda *args, **kwargs: [])
    monkeypatch.setattr(module, "store_profile_market_data", lambda *args: pytest.fail("source published"))
    monkeypatch.setattr(module, "write_profile_provenance", lambda *args: pytest.fail("provenance published"))
    with pytest.raises(RuntimeError, match="raw event count") as error:
        module.main()
    assert closed == [True]
    assert not output.exists()
    assert sibling.read_text() == "keep"
    assert "PRIVATE_RATE_MUST_NOT_LEAK" not in "".join(traceback.format_exception(error.value))
    assert capsys.readouterr().out == ""
