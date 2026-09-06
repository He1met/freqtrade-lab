"""One synthetic native spot probe; not a market research runner.

Run with the pinned Python and explicit native/repository PYTHONPATH:
  tests/native_spot_timing.py NEW_OUTPUT_ROOT STRATEGY_FILE

The parser call uses Synthetic phase only. It does not exercise the production
Search Profile binding or prove that the original ZIP passes the full importer.
"""
import ast
import json
import sys
from pathlib import Path

import pandas as pd
from freqtrade.commands.optimize_commands import setup_optimize_configuration
from freqtrade.data.history.datahandlers import get_datahandler
from freqtrade.enums import CandleType, RunMode
from freqtrade.exchange.okx import Okx
from freqtrade.optimize.backtesting import Backtesting

from lab import bounded_research as pilot
from scripts.run_freqtrade_backtest import _validate_results, _verify_market_inputs


def main():
    root, source = map(Path, sys.argv[1:])
    root.mkdir(parents=True, exist_ok=False)
    name = next(node.name for node in ast.parse(source.read_text()).body if isinstance(node, ast.ClassDef))
    pair = "ADA/USDT"
    dates = pd.date_range("2023-12-01T00:00Z", "2024-03-03T00:00Z", freq="1D")
    prices = pd.Series([100. + i * .1 for i in range(len(dates))])
    frame = pd.DataFrame(dict(date=dates, open=prices, high=prices+.15, low=prices-.15, close=prices+.05, volume=10000.))
    # A Wednesday intrabar stop and a final partial week exercise exceptions.
    frame.loc[frame.date.eq(pd.Timestamp("2024-01-17T00:00Z")), "low"] = 80.
    data_root = root / "data"; data_root.mkdir()
    get_datahandler(data_root, "feather").ohlcv_store(pair, "1d", frame, CandleType.SPOT)
    market = dict(id="ADA-USDT", symbol=pair, base="ADA", quote="USDT", settle=None,
                  baseId="ADA", quoteId="USDT", active=True, contract=False, swap=False,
                  spot=True, future=False, option=False, linear=None, inverse=None, type="spot",
                  contractSize=None, expiry=None, precision={"amount":.01,"price":.001},
                  limits={"amount":{"min":.01,"max":1000000},"price":{"min":.001,"max":None},
                          "cost":{"min":1.,"max":None},"leverage":{"min":None,"max":None}},
                  maker=.001, taker=.001, info={})
    profile = dict(domain="OKX_CRYPTO_SPOT", trading_mode="spot", margin_mode="", pairs=[pair],
                   max_open_trades=1, stake_amount=250., starting_balance=1000., taker_fee_rate=.001, timeframe="1d")
    config_path = root / "config.json"; config_path.write_text(json.dumps(pilot.profile_search_config(profile)))
    for directory in ("user", "exports"): (root / directory).mkdir()
    _verify_market_inputs(market, {"status":"NOT_APPLICABLE","trading_mode":"spot"},
                          pair=pair, provenance={"source":{"instrument_id":"ADA-USDT"}})
    config = setup_optimize_configuration(dict(command="backtesting", config=[str(config_path)],
        datadir=str(data_root), user_data_dir=str(root/"user"), strategy_path=str(source.parent),
        strategy=name, timerange="20240101-20240304", fee=.001, export="trades",
        exportdirectory=str(root/"exports"), dataformat_ohlcv="feather", disableparamexport=True,
        backtest_cache="none"), RunMode.BACKTEST)
    exchange = Okx(config, validate=False, load_leverage_tiers=False)
    def deny(*args, **kwargs): raise AssertionError("synthetic probe attempted network")
    exchange._api.fetch = deny; exchange._api_async.fetch = deny
    exchange._api.set_markets([market], {}); exchange._api_async.set_markets([market], {})
    exchange._markets = exchange._api.markets
    backtest = Backtesting(config, exchange=exchange)
    backtest.start()
    count = _validate_results(backtest.results, name, pair, .001)
    trades = backtest.results["strategy"][name]["trades"]
    assert count == 9, count
    assert sum(t["exit_reason"] == "stop_loss" for t in trades) == 1
    for trade in trades:
        opened, closed = pd.Timestamp(trade["open_date"]), pd.Timestamp(trade["close_date"])
        assert opened.dayofweek == 1 and opened.hour == 0
        assert opened >= pd.Timestamp("2024-01-01T00:00Z")
        assert trade["is_short"] is False and trade["leverage"] == 1
        assert trade["funding_fees"] == 0  # Native placeholder; product semantics N/A.
        assert trade["fee_open"] == trade["fee_close"] == .001
        assert abs(trade["amount"]/.01 - round(trade["amount"]/.01)) < 1e-8
        if trade["exit_reason"] == "exit_signal":
            assert closed.dayofweek == 5 and trade["trade_duration"] == 5760
        else:
            assert closed == pd.Timestamp("2024-01-17T00:00Z")
        gross = trade["amount"] * (trade["close_rate"]-trade["open_rate"])
        fees = trade["amount"] * (trade["close_rate"]+trade["open_rate"]) * .001
        assert abs(trade["profit_abs"]-(gross-fees)) < 1e-6
    archive = next((root/"exports").glob("*.zip"))
    metrics = pilot.report_metrics(root/"exports", archive.name, name, "Synthetic", configured_fee=.001)
    evidence = dict(status="PASS", synthetic_only=True, native_attempt=1, trades=count,
                    archive=str(archive), archive_sha256=pilot.digest(archive.read_bytes()),
                    source_sha256=pilot.digest(source.read_bytes()), funding="NOT_APPLICABLE",
                    project_parser=metrics, checks=["next_bar","96h_exit","stoploss","precision","fee_cashflow","no_short_or_leverage","pre_roll_no_entry"])
    (root/"evidence.json").write_bytes(pilot.canonical(evidence))
    backtest.cleanup(); exchange.close()
    print(json.dumps(evidence))


if __name__ == "__main__": main()
