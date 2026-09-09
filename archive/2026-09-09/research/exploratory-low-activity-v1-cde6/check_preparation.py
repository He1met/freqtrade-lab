"""One bounded AST/synthetic-data check; no market IO and no backtest runner."""
import ast
import hashlib
import json
import sys
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

from lab.bounded_strategy import analyze_bounded_causal_strategy
from lab.search_campaign import _single_factor_change

ROOT = Path(__file__).resolve().parent
FACTOR = "entry_low_activity_filter_72_v1"
checks = []


def require(name, condition, **details):
    checks.append({"name": name, "passed": bool(condition), **details})
    if not condition:
        raise AssertionError(name)


def bars(close=95.0, volume=49.0):
    prices = [99.8, 100.2] * 40 + [close]
    return pd.DataFrame({
        "date": pd.date_range("2000-01-01", periods=81, freq="5min", tz="UTC"),
        "open": prices, "high": np.array(prices) + 0.1,
        "low": np.array(prices) - 0.1, "close": prices,
        "volume": [100.0] * 80 + [volume],
    })


def signals(strategy, frame):
    frame = frame.copy()
    for field in ("enter_long", "enter_short", "exit_long", "exit_short"):
        frame[field] = 0
    for method in ("populate_indicators", "populate_entry_trend", "populate_exit_trend"):
        frame = getattr(strategy, method)(frame, {"pair": "SYNTHETIC/USDT:USDT"})
    return frame


report = {"kind": "PREPARATION_ONLY", "market_reads": 0, "native_backtests": 0}
try:
    sources, instances, snapshots = [], [], []
    for class_name in ("LowActivityR1", "LowActivityR2"):
        source = (ROOT / (class_name + ".py")).read_text()
        analysis = analyze_bounded_causal_strategy(source, class_name, expected_timeframe="5m")
        require(class_name + "_bounded_ast", analysis.max_lookback == 73
                and analysis.startup_candle_count == 73, analysis=asdict(analysis))
        namespace = {}
        exec(compile(source, str(ROOT / (class_name + ".py")), "exec"), namespace)
        instances.append(namespace[class_name]({}))
        sources.append(source)
        snapshots.append(SimpleNamespace(code_text=source, class_name=class_name))
    require("existing_single_factor_support_is_missing",
            not _single_factor_change(*snapshots, FACTOR))

    # Evidence for A's future exact semantic validator, not an alternative runner.
    parent, child = [ast.parse(s) for s in sources]
    parent.body[-1].name = child.body[-1].name = "FrozenStrategy"
    expected = ast.parse('(dataframe["volume"] < dataframe["prior_volume_mean"] * 0.5)', mode="eval").body
    method = next(n for n in child.body[-1].body
                  if isinstance(n, ast.FunctionDef) and n.name == "populate_entry_trend")
    removed = 0
    for assignment in method.body[:-1]:
        mask = assignment.targets[0].slice.elts[0]
        require("exact_filter_tail_" + str(removed), isinstance(mask, ast.BinOp)
                and isinstance(mask.op, ast.BitAnd)
                and ast.dump(mask.right) == ast.dump(expected))
        assignment.targets[0].slice.elts[0] = mask.left
        removed += 1
    require("only_two_same_entry_conjuncts_differ",
            removed == 2 and ast.dump(parent) == ast.dump(child))

    r1, r2 = instances
    for close, side in ((95.0, "enter_long"), (105.0, "enter_short")):
        for volume in (49.0, 50.0, 51.0):
            a, b = [signals(s, bars(close, volume)).iloc[-1] for s in instances]
            require(f"{side}_volume_{volume}", a[side] == 1
                    and b[side] == (1 if volume < 50 else 0),
                    baseline_signal=int(a[side]), filtered_signal=int(b[side]),
                    prior_mean=float(b["prior_volume_mean"]))
    frame = bars()
    result = signals(r2, frame)
    last = result.iloc[-1]
    reference = frame["close"].iloc[-72:]
    require("full_window_sample_std_and_current_price",
            np.isclose(last["reversion_mean"], reference.mean())
            and np.isclose(last["reversion_upper"], reference.mean() + 2 * reference.std(ddof=1))
            and last["prior_volume_mean"] == 100)
    for column, index, value in (("volume", 80, 0), ("volume", 80, np.nan),
                                 ("volume", 10, 0), ("volume", 10, np.nan),
                                 ("close", 10, np.nan)):
        modified = frame.copy()
        modified.loc[index, column] = value
        require(f"invalid_{column}_{index}_{value}", all(
            signals(s, modified).iloc[-1][["enter_long", "enter_short"]].sum() == 0
            for s in instances))
    flat = frame.copy()
    flat["close"] = 100.0
    require("zero_std_no_entry", all(signals(s, flat).iloc[-1][["enter_long", "enter_short"]].sum() == 0 for s in instances))
    require("incomplete_window_no_entry", all(
        signals(s, frame.iloc[:60])[ ["enter_long", "enter_short"] ].to_numpy().sum() == 0
        for s in instances))
    for close, side in ((101.0, "exit_long"), (99.0, "exit_short")):
        a, b = [signals(s, bars(close)).iloc[-1] for s in instances]
        require("same_dynamic_mean_" + side, a[side] == b[side] == 1)
    future = pd.concat([frame, bars(130, 5000).iloc[-1:]], ignore_index=True)
    future.loc[81, "date"] = future.loc[80, "date"] + pd.Timedelta(minutes=5)
    require("future_append_cannot_change_prior_signals", all(
        signals(s, future).iloc[:81].equals(signals(s, frame)) for s in instances))
    report["status"] = "AST_AND_SYNTHETIC_PASS_PUBLIC_ADAPTER_REQUIRED"
except Exception as exc:
    report["status"] = "PREPARATION_CHECK_FAILED"
    report["error"] = {"type": type(exc).__name__, "message": str(exc)}
finally:
    report["checks"] = checks
    report["source_sha256"] = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (ROOT / "LowActivityR1.py", ROOT / "LowActivityR2.py")
    }
    (ROOT / "preparation-check.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
if report["status"] == "PREPARATION_CHECK_FAILED":
    sys.exit(1)
