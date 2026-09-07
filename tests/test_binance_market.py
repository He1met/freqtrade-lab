import sqlite3

import pytest

from lab.bounded_research import profile_search_config, validate_profile_runtime_contract, PilotError
from lab.database import get_connection, init_database
from lab.market_contract import valid_market
from tests.test_database import insert_profile, BUSINESS_TABLES
from tests.test_spot_research import spot_profile


@pytest.mark.parametrize("exchange",[None,[],{}, {"name":[]}, {"name":None},"unknown"])
def test_invalid_exchange_is_rejected_without_type_error(exchange):
    assert not valid_market({"exchange":exchange,"trading_mode":"futures","margin_mode":"isolated"})


def test_domain_exchange_and_six_tables_in_new_database(tmp_path):
    path=tmp_path/'new.sqlite';init_database(path)
    with get_connection(path) as conn:
        profile=insert_profile(conn)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE research_profiles SET exchange='binance' WHERE id=?",(profile,))
        conn.execute("UPDATE research_profiles SET domain='BINANCE_CRYPTO_PERP',exchange='binance' WHERE id=?",(profile,))
        assert {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}==BUSINESS_TABLES


@pytest.mark.parametrize('pair', ['BCH/USDT:USDT', 'DOGE/USDT:USDT'])
def test_binance_profile_passes_exchange_without_expanding_market_scope(tmp_path, pair):
    _,profile=spot_profile(tmp_path)
    profile.update(domain="BINANCE_CRYPTO_PERP",exchange="binance",trading_mode="futures",
                   margin_mode="isolated",pairs=[pair],timeframe="1d",max_open_trades=1)
    assert profile_search_config(profile)["exchange"]["name"]=="binance"
    assert validate_profile_runtime_contract(profile)["pair"]==pair
    profile["pairs"]=["BTC/USDT:USDT"]
    with pytest.raises(PilotError,match="BCH or DOGE perpetual"):
        validate_profile_runtime_contract(profile)


def test_existing_okx_markets_still_valid():
    assert valid_market({"domain":"OKX_CRYPTO_PERP","exchange":"okx","trading_mode":"futures","margin_mode":"isolated"},profile=True)
    assert valid_market({"domain":"OKX_CRYPTO_SPOT","exchange":"okx","trading_mode":"spot","margin_mode":""},profile=True)
    assert not valid_market({"domain":"OKX_CRYPTO_PERP","exchange":"binance","trading_mode":"futures","margin_mode":"isolated"},profile=True)
