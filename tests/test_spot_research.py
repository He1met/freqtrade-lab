"""Narrow spot contracts; all inputs synthetic, no market requests."""
import sqlite3

import pytest

from lab import bounded_research as pilot
from lab.database import get_connection
from lab.market_contract import validate_spot_source
from lab.research_candidate import _validate_config
from tests.test_search_data_producer import _profile_search_database
from tests.test_fetch_okx_public_data import _write_profile_window


def spot_profile(tmp_path):
    database, profile = _profile_search_database(tmp_path)
    profile.update(domain="OKX_CRYPTO_SPOT", trading_mode="spot", margin_mode="", pairs=["ADA/USDT"])
    return database, profile


def test_spot_profile_config_and_six_table_database(tmp_path):
    database, profile = spot_profile(tmp_path)
    contract = pilot.validate_profile_runtime_contract(profile)
    config = pilot.profile_search_config(profile)
    assert contract["pair"] == "ADA/USDT"
    assert config["trading_mode"] == "spot" and config["margin_mode"] == ""
    assert _validate_config(config, "SpotStrategy")[1] == ("ADA/USDT",)
    with get_connection(database) as conn:
        conn.execute("UPDATE research_profiles SET domain='OKX_CRYPTO_SPOT', trading_mode='spot', margin_mode='', pairs_json='[\"ADA/USDT\"]' WHERE id=?", (profile["id"],))
        assert conn.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchone()[0] == 6
        for change in ("margin_mode='isolated'", "trading_mode='futures'", "domain='OKX_CRYPTO_PERP'"):
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(f"UPDATE research_profiles SET {change} WHERE id=?", (profile["id"],))


@pytest.mark.parametrize("change", [dict(margin_mode="isolated"), dict(domain="OKX_CRYPTO_PERP"),
                                   dict(pairs=["ADA/USDT:USDT"]), dict(pairs=["ADA/BTC"]),
                                   dict(trading_mode=[]), dict(margin_mode={})])
def test_spot_profile_rejects_wrong_identity(tmp_path, change):
    _, profile = spot_profile(tmp_path)
    profile.update(change)
    with pytest.raises(pilot.PilotError):
        pilot.validate_profile_runtime_contract(profile)


@pytest.mark.parametrize("source", ["can_short = True", "can_short = 0", "can_short = False\nx = 'enter_short'",
                                     "can_short = False\nx = 'lagged_funding'"])
def test_spot_source_rejects_short_and_funding(source):
    with pytest.raises(ValueError):
        validate_spot_source(source)


def test_spot_source_accepts_long_only():
    validate_spot_source("class SpotStrategy:\n    can_short = False\n")


@pytest.mark.parametrize("mutation", ["unconfirmed", "duplicate", "wrong_clock", "wrong_shape"])
def test_spot_raw_candle_gate_rejects_before_parsing(mutation):
    pytest.importorskip("freqtrade")
    from scripts.fetch_okx_profile_data import _validate_spot_candle_page
    row = ["86400000", "100", "101", "99", "100", "1", "1", "100", "1"]
    raw = {"code":"0", "msg":"", "data":[row]}
    if mutation == "unconfirmed": row[8] = "0"
    elif mutation == "duplicate": raw["data"].append(row.copy())
    elif mutation == "wrong_clock": row[0] = "86400001"
    else: row.pop()
    with pytest.raises(RuntimeError):
        _validate_spot_candle_page(raw, raw, 86400000, 172800000, 86400000)


def test_spot_synthetic_producer_to_search_and_development(tmp_path, monkeypatch):
    import json
    import pyarrow.feather as feather
    from tests.test_development_run import _approved_candidate_database
    from scripts.run_freqtrade_backtest import _verify_market_inputs
    pytest.importorskip("freqtrade")
    from scripts import fetch_okx_profile_data as producer
    database, _ = _approved_candidate_database(tmp_path / "db", timeframe="1d")
    with get_connection(database) as conn:
        conn.execute("UPDATE research_profiles SET domain='OKX_CRYPTO_SPOT', trading_mode='spot', margin_mode='', pairs_json='[\"ADA/USDT\"]', history_start_date='2025-01-01', min_development_trades=5")
        profile_id = conn.execute("SELECT id FROM research_profiles").fetchone()[0]
        conn.commit()
    window = _write_profile_window(tmp_path, data_start_utc="2025-12-01T00:00:00Z",
                                   search_start_utc="2026-01-01T00:00:00Z",
                                   development_start_utc="2026-03-01T00:00:00Z",
                                   end_exclusive_utc="2026-05-01T00:00:00Z")
    producer.configure_profile_acquisition(database, profile_id, window, 31)
    market = {"symbol": "ADA/USDT", "id": "ADA-USDT", "active": True,
              "spot": True, "contract": False, "type": "spot"}
    class Exchange:
        def public_get_public_instruments(self, params):
            assert params == {"instType": "SPOT", "instId": "ADA-USDT"}
            return {"code": "0", "msg": "", "data": [{"instId": "ADA-USDT", "instType": "SPOT", "quoteCcy": "USDT", "state": "live", "listTime": "1500000000000"}]}
        def parse_market(self, value): return market
        def set_markets(self, *args): pass
        def close(self): pass
        def parse_timeframe(self, tf): return 86400
        def publicGetMarketHistoryCandles(self, params):
            data = [[str(params["before"]+1+i*86400000), "100", "101", "99", "100", "1", "1", "100", "1"] for i in range(params["limit"])]
            response = {"code":"0", "msg":"", "data":data}
            self.last_http_response = json.dumps(response)
            return response
        def fetch_ohlcv(self, symbol, *, timeframe, since, limit, params):
            assert symbol == "ADA/USDT" and timeframe == "1d" and "price" not in params
            self.publicGetMarketHistoryCandles({"instId":"ADA-USDT", "bar":"1Dutc", "limit":limit,
                                               "before":since-1, "after":params["until"]})
            return [[since + i * 86400000, 100., 101., 99., 100., 1.] for i in range(limit)]
    monkeypatch.setattr(producer.transport.ccxt, "okx", lambda config: Exchange())
    monkeypatch.setattr(producer, "install_request_guard", lambda exchange: None)
    monkeypatch.setattr(producer, "request_receipt", lambda exchange, label: {"label": label})
    runtime = {"freqtrade_tag": "2026.7", "freqtrade_commit": "52bc96f4480b1a0da6a9b455bd00b17fbb6786a5", "versions": pilot.RUNNER_DEPENDENCIES}
    source = tmp_path / "source"
    receipt = producer.acquire(source, runtime)
    provenance = producer.write_profile_provenance(source, receipt, runtime)
    assert json.loads(receipt.read_text())["series"].keys() == {"spot_1d"}
    tiers = json.loads((source / "isolated_tiers_snapshot.json").read_text())
    _verify_market_inputs(market, tiers, pair="ADA/USDT", provenance=json.loads(provenance.read_text()))
    kwargs = dict(database_path=database, profile_id=profile_id, search_timerange="20260101-20260301",
                  development_timerange="20260301-20260501", pre_roll_candles=31)
    search = tmp_path / "search"
    development = tmp_path / "development"
    sha, receipt_sha = pilot.digest(provenance.read_bytes()), pilot.digest(receipt.read_bytes())
    pilot.prepare_search_data(source, search, sha, receipt_sha, **kwargs)
    pilot.prepare_development_data(source, development, sha, receipt_sha, **kwargs)
    files = list((search / pilot.ACQUISITION / "data/okx").rglob("*.feather"))
    assert len(files) == 1 and files[0].name == "ADA_USDT-1d.feather"
    dates = feather.read_table(files[0], columns=["date"]).column("date").to_pylist()
    assert dates[-1].isoformat().startswith("2026-02-28")
    assert len(dates) == 90
