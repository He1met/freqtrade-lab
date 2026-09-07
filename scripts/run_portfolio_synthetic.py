#!/usr/bin/env python3
"""Fixed native synthetic probe. Never accepts market data, arbitrary code or budget root."""
from __future__ import annotations
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.metadata
import json
import os
import signal
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lab.portfolio_budget import NativeBudget, BudgetError, RUNTIME_ROOT, canonical, verify_anchor
from lab.portfolio_preflight import load_protocol, PROTOCOL_SHA256
from lab.portfolio_execution import SYNTHETIC_VECTOR, fill_equity

SOURCE_COMMIT = "52bc96f4480b1a0da6a9b455bd00b17fbb6786a5"
MODES = ("B-risk", "A-trend", "A-reversal", "B", "C")
REPO = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_environment(source):
    expected = {"freqtrade": "2026.7", "ccxt": "4.5.68", "pandas": "3.0.3", "pyarrow": "25.0.0"}
    if sys.version.split()[0] != "3.13.13" or any(importlib.metadata.version(k) != v for k, v in expected.items()):
        raise ValueError("native dependencies differ from fixed contract")
    def git(*args):
        return subprocess.check_output(["git", "-C", str(source), *args], text=True).strip()
    if git("rev-parse", "HEAD") != SOURCE_COMMIT or git("status", "--porcelain", "--untracked-files=all"):
        raise ValueError("native Git source is not the locked clean commit")
    return git("rev-parse", "HEAD^{tree}")


def synthetic_config(mode):
    from lab.bounded_research import profile_search_config
    pairs = ["BTC/USDT:USDT", "ETH/USDT:USDT"]
    # Reuse base field conventions without changing the old single-pair API.
    config = profile_search_config(dict(exchange="binance", domain="BINANCE_CRYPTO_PERP",
        trading_mode="futures",margin_mode="isolated",pairs=pairs[:1],max_open_trades=1,
        stake_amount=400.,starting_balance=1000.,taker_fee_rate=.0006,timeframe="1d"))
    config.update(timeframe="1h", max_open_trades=2, stake_amount="unlimited",tradable_balance_ratio=1.,portfolio_probe_mode=mode)
    config["exchange"]["pair_whitelist"] = pairs
    config["order_types"] = {"entry":"market","exit":"market","stoploss":"market","stoploss_on_exchange":False}
    config["entry_pricing"]["price_side"] = "other"
    config["exit_pricing"]["price_side"] = "other"
    return config


def run_native(root, mode, source):
    # The budget is already fsynced before any Freqtrade import or constructor.
    sys.path.insert(0, str(source))
    denied = []
    def deny_network(event, args):
        if event in {"socket.connect", "socket.getaddrinfo", "socket.bind"}:
            denied.append(event)
            raise RuntimeError("synthetic native network denied")
    sys.addaudithook(deny_network)
    import pandas as pd
    import freqtrade
    if Path(freqtrade.__file__).resolve() != (source/"freqtrade/__init__.py").resolve():
        raise ValueError("native import source mismatch")
    from freqtrade.commands.optimize_commands import setup_optimize_configuration
    from freqtrade.enums import CandleType, RunMode
    from freqtrade.data.history.datahandlers import get_datahandler
    from freqtrade.exchange.binance import Binance
    from freqtrade.optimize.backtesting import Backtesting
    from lab.portfolio_probe_strategy import PAIRS, PRICES, START, synthetic_mark

    for name in ("data", "user", "exports"): (root/name).mkdir()
    handler = get_datahandler(root/"data", "feather")
    dates = pd.date_range("2020-01-01T00:00Z", "2020-01-08T00:00Z", freq="1h", inclusive="left")
    markets, tiers = [], {}
    for pair in PAIRS:
        price = PRICES[pair]
        frame = pd.DataFrame(dict(date=dates, open=price, high=price*1.001, low=price*.999, close=price, volume=10000.))
        handler.ohlcv_store(pair, "1h", frame, CandleType.FUTURES)
        mark = frame.copy()
        for col in ("open", "high", "low", "close"):
            mark[col] = dates.map(lambda d: synthetic_mark(pair, d.to_pydatetime(), mode))
        handler.ohlcv_store(pair, "1h", mark, CandleType.MARK)
        funding = frame.iloc[::8].copy()
        funding[["open", "high", "low", "close"]] = .0001
        # Freqtrade's Binance funding storage label is 1h even when events are
        # eight-hourly; sparse event timestamps stay unchanged, no zero filling.
        handler.ohlcv_store(pair, "1h", funding, CandleType.FUNDING_RATE)
        base = pair.split("/")[0]
        markets.append(dict(id=base+"USDT", symbol=pair, base=base, quote="USDT", settle="USDT",
            baseId=base, quoteId="USDT", settleId="USDT", active=True, contract=True, swap=True,
            spot=False, future=False, option=False, linear=True, inverse=False, type="swap", contractSize=1.,
            expiry=None, precision={"amount":.001,"price":.1 if base=="BTC" else .01},
            limits={"amount":{"min":.001,"max":120. if base=="BTC" else 2000.},
                    "price":{"min":.01,"max":None},"cost":{"min":50. if base=="BTC" else 20.,"max":None},
                    "leverage":{"min":1.,"max":20.}}, maker=.0006,taker=.0006,info={}))
        tiers[pair] = [{"minNotional":0.,"maxNotional":1000000.,"maintenanceMarginRate":.005,"maxLeverage":20.,"maintAmt":0.}]
    config_value = synthetic_config(mode)
    config_path = root/"config.json"; config_path.write_bytes(canonical(config_value))
    config = setup_optimize_configuration(dict(command="backtesting",config=[str(config_path)],
        datadir=str(root/"data"),user_data_dir=str(root/"user"),strategy_path=str(REPO/"lab"),
        strategy="PortfolioSyntheticProbe",timerange="20200102-20200108",fee=.0006,export="trades",
        exportdirectory=str(root/"exports"),dataformat_ohlcv="feather",disableparamexport=True,
        backtest_cache="none"),RunMode.BACKTEST)
    exchange = Binance(config,validate=False,load_leverage_tiers=False)
    def deny(*a, **k): raise RuntimeError("native attempted exchange request")
    exchange._api.fetch = deny; exchange._api_async.fetch = deny
    exchange._api.set_markets(markets,{}); exchange._api_async.set_markets(markets,{})
    exchange._markets = exchange._api.markets; exchange._leverage_tiers = tiers
    bt = None
    try:
        bt = Backtesting(config, exchange=exchange)
        if len(bt.strategylist) != 1 or set(bt.pairlists.whitelist) != set(PAIRS):
            raise ValueError("native account/strategy/pair scope mismatch")
        bt.start()
        strategy = bt.strategylist[0]
        result = bt.results["strategy"]["PortfolioSyntheticProbe"]
        trades = result["trades"]
        # Preserve full native result and probe trace externally before assertions.
        (root/"trace.json").write_bytes(canonical(strategy.trace))
        (root/"native-result.json").write_bytes(canonical(result))
        evidence = audit_probe(trades, strategy.trace, mode, result, PAIRS, PRICES)
        evidence.update(archive_sha256={p.name:sha(p) for p in (root/"exports").glob("*.zip")},
                        source_commit=SOURCE_COMMIT, protocol_sha256=PROTOCOL_SHA256,
                        denied_network_attempts=denied, native_accounts=1, synthetic_only=True)
        return evidence
    finally:
        if bt is not None: bt.cleanup()
        exchange.close()


def audit_probe(trades, trace, mode, result, pairs, prices):
    from lab.portfolio_probe_strategy import synthetic_mark
    fills = []
    source_funding = 0.
    for trade in trades:
        assert trade["leverage"] == 1 and trade["fee_open"] == trade["fee_close"] == .0006
        quantity, previous = 0., None
        for order in sorted(trade["orders"], key=lambda o:o["order_filled_timestamp"]):
            stamp = order["order_filled_timestamp"]
            if previous is not None and quantity > 1e-9:
                step = 8*3600000
                for event in range((previous+step-1)//step*step, stamp+1, step):
                    mark = synthetic_mark(trade["pair"],datetime.fromtimestamp(event/1000,timezone.utc),mode)
                    source_funding += (1 if trade["is_short"] else -1)*quantity*.0001*mark
            quantity += order["amount"]*(1 if order["ft_is_entry"] else -1)
            previous = stamp
            fills.append({"pair":trade["pair"],"side":order["ft_order_side"],"amount":order["amount"],
                          "price":order["safe_price"],"time":order["order_filled_timestamp"]})
    fills.sort(key=lambda f:f["time"])
    funding = sum(t["funding_fees"] for t in trades)
    assert abs(funding-source_funding) < 1e-6, "native funding does not match synthetic raw events/position segments"
    audit = fill_equity(fills, prices, funding=funding)
    native_profit = sum(t["profit_abs"] for t in trades)
    assert abs(float(audit["equity"])-1000-native_profit) < 1e-6, "native fills/fee/profit reconciliation"
    assert all(abs(q)<1e-8 for q in audit["inventory"].values()), "final open inventory"
    assert trades and set(t["pair"] for t in trades) == set(pairs), "both pairs must actually trade"
    assert any(p.get("inventory",{}).get(pairs[0],0) and p.get("inventory",{}).get(pairs[1],0) for p in trace), "simultaneous positions"
    assert all(sum(abs(q)*prices[pair] for pair,q in p["targets"].items()) <= .8*p["equity"]+1e-6 for p in trace if "targets" in p)
    if mode == "B-risk":
        assert any(p.get("wallet_total",0)-p.get("equity",0)>50 for p in trace), "MTM differs from closed wallet"
        assert any(p.get("halted") for p in trace), "floating loss must trigger stop"
        assert max(sum(abs(q)*prices[pair] for pair,q in p.get("inventory",{}).items()) for p in trace) <= 800.001
    else:
        assert not any(t["open_date"].startswith("2020-01-06") for t in trades), "below-minimum day must produce no fill"
        if mode in {"B", "C"}:
            assert not any(t["pair"] == pairs[0] and t["open_date"].startswith("2020-01-02") for t in trades), "opposed BTC signals must net to zero"
        longs = [t for t in trades if t["pair"]==pairs[0] and not t["is_short"]]
        shorts = [t for t in trades if t["pair"]==pairs[0] and t["is_short"]]
        if mode != "A-reversal":
            assert longs and shorts, "long and short native paths"
            assert min(t["open_timestamp"] for t in shorts) >= max(t["close_timestamp"] for t in longs)+3600000, "flip must wait next hour"
    return {"status":"PASS", "mode":mode, "trades":len(trades), "orders":len(fills),
            "native_profit_synthetic_only":native_profit,"native_funding":funding,"source_funding":source_funding,
            "native_final_equity":str(audit["equity"]),"fill_fees":str(audit["costs"]),
            "minimum_mark_equity":min(p["equity"] for p in trace if "equity" in p),
            "market_economic_result":None, "full_economic_signal_template":"NOT_IMPLEMENTED"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", required=True, choices=MODES)
    parser.add_argument("--native-source", required=True, type=Path)
    parser.add_argument("--retry-of", help="failed slot; consumes next of four technical retry slots")
    args = parser.parse_args()
    protocol = load_protocol()
    verify_anchor()
    source = args.native_source.resolve(strict=True)
    tree = verify_environment(source)
    bindings = {str(p.relative_to(REPO)):sha(p) for p in [REPO/"scripts/run_portfolio_synthetic.py",
                REPO/"lab/portfolio_budget.py",REPO/"lab/portfolio_execution.py",REPO/"lab/portfolio_probe_strategy.py"]}
    input_hash = hashlib.sha256(canonical({"vector":SYNTHETIC_VECTOR,"mode":args.mode})).hexdigest()
    code_hash = hashlib.sha256(canonical(bindings)).hexdigest()
    source_hash = hashlib.sha256(tree.encode()).hexdigest()
    with NativeBudget(RUNTIME_ROOT).locked() as budget:
        key = f"synthetic/{MODES.index(args.mode)+1}"
        if args.retry_of:
            used = {r["key"] for r in budget.events}
            key = next((f"retry/{n}" for n in range(1,5) if f"retry/{n}" not in used), "retry/5")
        root = RUNTIME_ROOT/"runs"/key.replace("/", "-")
        if root.exists():
            raise BudgetError("output already exists; never overwrite an old attempt")
        budget.reserve(key,input_sha256=input_hash,code_sha256=code_hash,source_sha256=source_hash,retry_of=args.retry_of)
        root.mkdir(parents=True, exist_ok=False, mode=0o700)
        def timed_out(*_):
            raise TimeoutError("fixed 180 second synthetic worker budget expired")
        signal.signal(signal.SIGALRM, timed_out)
        signal.alarm(180)
        try:
            (root/"bindings.json").write_bytes(canonical({"code":bindings,"input_sha256":input_hash,"source_tree":tree,"mode":args.mode}))
            evidence = run_native(root,args.mode,source)
            if any(sha(REPO/name) != value for name,value in bindings.items()):
                raise ValueError("probe code changed during native execution")
            status = "SUCCEEDED"
        except Exception as exc:
            evidence = {"status":"FAILED", "error_type":type(exc).__name__,"reason":str(exc),"mode":args.mode,
                        "market_economic_result":None,"synthetic_only":True}
            status = "FAILED"
        finally:
            signal.alarm(0)
        raw = canonical(evidence)
        (root/"evidence.json").write_bytes(raw)
        budget.finish(key,status,hashlib.sha256(raw).hexdigest())
        print(json.dumps({"status":status,"key":key,"evidence":str(root/"evidence.json"),"market_economic_result":None}))
        return 0 if status=="SUCCEEDED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
