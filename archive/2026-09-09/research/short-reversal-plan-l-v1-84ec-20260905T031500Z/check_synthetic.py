"""No prices from any market, no DB, no Backtesting instance or execution loop."""
import dataclasses
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

from lab import bounded_research as pilot
from lab.bounded_strategy import analyze_bounded_causal_strategy, BoundedStrategyError
from lab.search_campaign import _single_factor_change, ENTRY_LOW_ACTIVITY_FILTER_72_V1
from freqtrade.optimize.backtesting import Backtesting

ROOT = Path(__file__).resolve().parent
sources = {}
classes = {}
checks = []

def check(name, passed, detail=None):
    assert passed, (name, detail)
    checks.append({"name": name, "passed": True, "detail": detail})

for name in ("ShockReversalR1", "ShockReversalR2"):
    text = (ROOT / (name + ".py")).read_text()
    analysis = analyze_bounded_causal_strategy(text, name, expected_timeframe="5m")
    sources[name] = SimpleNamespace(class_name=name, code_text=text)
    check(name + "_bounded", analysis.max_lookback == 73, dataclasses.asdict(analysis))
    namespace = {}
    exec(compile(text, name + ".py", "exec"), namespace)
    classes[name] = namespace[name]

parent, child = sources.values()
factor = ENTRY_LOW_ACTIVITY_FILTER_72_V1
check("formal_dispatch", _single_factor_change(parent, child, factor))
for label, old, new in (
    ("threshold", " * 0.5", " * 0.6"),
    ("stop", "stoploss = -0.03", "stoploss = -0.02"),
    ("expiry", '{"360": -1}', '{"355": -1}'),
    ("window", "rolling(72)", "rolling(71)"),
):
    mutated = SimpleNamespace(class_name=child.class_name, code_text=child.code_text.replace(old, new))
    check("dispatch_reject_" + label, not _single_factor_change(parent, mutated, factor))
check("dispatch_reject_unchanged", not _single_factor_change(parent, parent, factor))
check("dispatch_reject_reversed", not _single_factor_change(child, parent, factor))
check("dispatch_reject_wrong_factor", not _single_factor_change(parent, child, "stoploss"))
# A future *unselected* same-interval hypothesis: syntax only, no signals evaluated.
# This does not replace either of the two source files under review.
future_expression = '(dataframe["volume"].rolling(12).mean() < dataframe["volume"].shift(12).rolling(72).mean() * 0.5)'
future_parent = SimpleNamespace(class_name=parent.class_name,
    code_text=parent.code_text.replace("startup_candle_count = 73", "startup_candle_count = 84"))
future_child = SimpleNamespace(class_name=child.class_name,
    code_text=child.code_text.replace("startup_candle_count = 73", "startup_candle_count = 84")
    .replace('(dataframe["volume"] < dataframe["prior_volume_mean"] * 0.5)', future_expression))
check("unselected_same_interval_ast", analyze_bounded_causal_strategy(
    future_child.code_text, future_child.class_name).max_lookback == 84)
check("unselected_same_interval_existing_factor_rejected", not _single_factor_change(
    future_parent, future_child, factor))
check("unselected_same_interval_unregistered_factor_rejected", not _single_factor_change(
    future_parent, future_child, "entry_same_hour_activity_v1"))
for label, old, new in (
    ("future", "shift(11)", "shift(-11)"),
    ("startup", "startup_candle_count = 73", "startup_candle_count = 72"),
):
    try:
        analyze_bounded_causal_strategy(parent.code_text.replace(old, new), parent.class_name)
    except BoundedStrategyError as error:
        check("bounded_reject_" + label, True, error.code)
    else:
        check("bounded_reject_" + label, False)

def frame(sign=-1, volume_mode="low"):
    n = 400
    close = np.full(n, 100.0)
    close[110:130] = 100 + sign * 3
    close[130:] = 100.0
    opens = np.r_[close[0], close[:-1]]
    volume = np.full(n, 100.0)
    if volume_mode == "low":
        volume[110] = 20.0
    elif volume_mode == "high_hour_low_last":
        volume[99:110] = 2000.0
        volume[110] = 20.0
    elif volume_mode == "low_hour_high_last":
        volume[99:110] = 10.0
        volume[110] = 90.0
    return pd.DataFrame({"date": pd.date_range("2000-01-01", periods=n, freq="5min", tz="UTC"),
                         "open": opens, "high": np.maximum(opens, close) + .1,
                         "low": np.minimum(opens, close) - .1, "close": close, "volume": volume})

def signal(name, df):
    strategy = classes[name]({})
    out = strategy.populate_indicators(df.copy(), {})
    out = strategy.populate_entry_trend(out, {})
    return strategy.populate_exit_trend(out, {})

signal_columns = ["enter_long", "enter_short", "exit_long", "exit_short"]
for sign, entry, opposite in ((-1, "enter_long", "enter_short"), (1, "enter_short", "enter_long")):
    for name in classes:
        out = signal(name, frame(sign))
        check(name + entry + "_known_shock", out.loc[110, entry] == 1 and pd.isna(out.loc[110, opposite]))
        check(name + entry + "_no_repeated_level_trigger", pd.isna(out.loc[111, entry]))
        check(name + entry + "_mean_exit", out.loc[130, "exit_long" if sign < 0 else "exit_short"] == 1)
        check(name + entry + "_entry_exit_no_collision", pd.isna(out.loc[110, "exit_long" if sign < 0 else "exit_short"]))

for name in classes:
    base = frame()
    full = signal(name, base)
    for n in (73, 110, 111, 131, 200, 399):
        pd.testing.assert_frame_equal(signal(name, base.iloc[:n])[full.columns], full.iloc[:n])
    poisoned = base.copy()
    poisoned.loc[200:, ["open", "high", "low", "close", "volume"]] *= 17
    pd.testing.assert_frame_equal(signal(name, poisoned).iloc[:200], full.iloc[:200])
    check(name + "_prefix_and_future_tail", True, "6 prefixes and one changed future tail; synthetic 2000 timestamps")
    flat = base.copy()
    flat[["open", "close"]] = 100.0
    flat["high"], flat["low"] = 100.1, 99.9
    out = signal(name, flat)
    check(name + "_flat_no_entry", int(out[["enter_long", "enter_short"]].count().sum()) == 0)
    zero = base.copy()
    zero["volume"] = 0.0
    out = signal(name, zero)
    check(name + "_zero_volume_no_entry", int(out[["enter_long", "enter_short"]].count().sum()) == 0)

classification = []
for mode, accepted in (("high_hour_low_last", True), ("low_hour_high_last", False)):
    data = frame(volume_mode=mode)
    out = signal("ShockReversalR2", data)
    actual = bool(out.loc[110, "enter_long"] == 1)
    check("volume_proxy_" + mode, actual == accepted)
    classification.append({"case": mode, "prior_baseline_hour_volume": 1200,
                           "shock_hour_volume": float(data.loc[99:110, "volume"].sum()),
                           "last_bar_volume": float(data.loc[110, "volume"]),
                           "last_bar_prior72_mean": float(out.loc[110, "prior_volume_mean"]),
                           "r2_accepts": actual})

# Native pure method probes, not a backtest or execution simulation.
strategy = classes["ShockReversalR1"]({})
strategy.minimal_roi = {int(k): v for k, v in strategy.minimal_roi.items()}
strategy.use_custom_roi = False
t0 = datetime(2000, 1, 1, tzinfo=timezone.utc)
trade = SimpleNamespace(open_date_utc=t0, is_short=False)
for duration, expected in ((0, False), (359, False), (360, True), (365, True)):
    for pnl_input in (-.02, .05):
        actual = strategy.min_roi_reached(trade, pnl_input, t0 + timedelta(minutes=duration))
        check(f"native_roi_{duration}_{pnl_input}", actual is expected)
for short in (False, True):
    trade.is_short = short
    rate = Backtesting._get_close_rate_for_roi(
        SimpleNamespace(strategy=strategy, timeframe_min=5),
        (t0 + timedelta(hours=6), 97.25, 100, 96, 98), trade,
        t0 + timedelta(hours=6), None, 360)
    check("native_expiry_bar_open_" + str(short), rate == 97.25)

profile = {
    "id": "proposed-l-not-a-database-id", "name": "L proposed feasibility contract",
    "domain": "OKX_CRYPTO_PERP", "exchange": "okx", "trading_mode": "futures", "margin_mode": "isolated",
    "pairs": ["LINK/USDT:USDT"], "timeframe": "5m", "detail_timeframe": None,
    "history_start_date": "2024-07-31", "smoke_days": 1, "holdout_days": 90,
    "starting_balance": 2000.0, "stake_amount": 400.0, "max_open_trades": 1,
    "taker_fee_rate": .0005, "stress_fee_multiplier": 2.0,
    "max_drawdown_pct": 10.0, "min_development_trades": 48, "min_holdout_trades": 48,
    "min_profit_factor": 1.1, "is_default": False, "created_at": "PROPOSED", "updated_at": "PROPOSED",
}
economic = {"name": pilot.PROFILE_ECONOMIC_GATE, "version": 1,
            "minimum_net_profit_after_base_fees_pct": 1.25,
            "minimum_average_holding_period_minutes": 5.0, "maximum_roi_exit_count": 30000}
contract = pilot.profile_search_contract(profile, "20240801-20241031", "20241031-20250131", 73, economic)
check("pure_profile_search_contract", contract["holdout"] == "SEALED_UNREAD")
windows = {}
for phase, span in (("Search", "20240801-20241031"), ("Development", "20241031-20250131"), ("Holdout", "20250131-20250501")):
    window = pilot._profile_window_contract(span, phase=phase, timeframe="5m", pre_roll_candles=73)
    windows[phase] = {"timerange": span, "rows": window["rows"], "startup_start": window["startup_start"].isoformat(),
                      "starts": {k: v.isoformat() for k, v in window["starts"].items()}}
    check("pure_window_arithmetic_" + phase, True, "not a source/consumer data-readiness check")

receipt = {"status": "SYNTHETIC_ONLY_NOT_EXECUTED_ON_MARKET", "checks": checks,
           "volume_proxy_counterexamples": classification,
           "proposed_contract": contract, "window_arithmetic": windows,
           "source_sha256": {n: hashlib.sha256(s.code_text.encode()).hexdigest() for n, s in sources.items()},
           "real_backtest_count": 0, "backtesting_instances": 0, "databases_opened": 0,
           "economic_results": None,
           "future_unselected_hypothesis": {"expression": future_expression,
               "minimum_static_lookback": 84, "source_files_written": False,
               "candidate_created": False, "signal_or_profit_evaluated": False,
               "existing_r2_dispatch_accepts": False}}
(ROOT / "synthetic-checks.json").write_text(json.dumps(receipt, indent=2) + "\n")
print(json.dumps({"passed": len(checks), "volume_proxy_counterexamples": classification,
                  "source_sha256": receipt["source_sha256"]}, indent=2))
