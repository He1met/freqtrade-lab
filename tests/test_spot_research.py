"""Narrow spot contracts; all inputs synthetic, no market requests."""
from copy import deepcopy
import sqlite3

import pytest

from lab import bounded_research as pilot
from lab.database import get_connection
from lab.market_contract import validate_spot_source
from lab.research_candidate import _validate_config
from tests.test_search_data_producer import _profile_search_database


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
                                   dict(pairs=["ADA/USDT:USDT"]), dict(pairs=["ADA/BTC"])])
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
