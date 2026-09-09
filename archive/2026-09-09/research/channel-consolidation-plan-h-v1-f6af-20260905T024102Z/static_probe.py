"""Synthetic/static feasibility only: no Candidate, data, engine, DB or PnL."""
import ast
import dataclasses
import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

REPO = Path("/Users/shenjianpeng/.codex/worktrees/f6af/freqtrade-lab")
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))
from lab.bounded_strategy import analyze_bounded_causal_strategy, BoundedStrategyError
from lab.codex_generation import parse_candidate_output
from lab.search_campaign import _single_factor_change, _single_entry_conjunct_change

FILTER = '(dataframe["close"].rolling(28).max().shift(1) / dataframe["close"].rolling(28).min().shift(1)) <= 1.10'
FACTOR = "entry_prior_close_channel_28_10pct_v1"
FILTERS = {s: FILTER for s in ("enter_long", "enter_short")}
sources = [(ROOT / f"ConsolidationChannelR{n}.py").read_text() for n in (1, 2)]
snapshots = [SimpleNamespace(code_text=s, class_name=f"ConsolidationChannelR{n}") for n, s in enumerate(sources, 1)]
receipt = {"kind": "SYNTHETIC_STATIC_ONLY", "analyses": [], "native_backtests": 0, "market_reads": 0}
for snap in snapshots:
    analysis = analyze_bounded_causal_strategy(snap.code_text, snap.class_name, expected_timeframe="1d")
    parsed = parse_candidate_output(json.dumps(dict(display_name=snap.class_name, class_name=snap.class_name, code_text=snap.code_text)).encode(), timeframe="1d")
    receipt["analyses"].append({**dataclasses.asdict(analysis), "class": snap.class_name, "sha256": parsed.code_sha256,
        "ast_nodes": sum(1 for _ in ast.walk(ast.parse(snap.code_text)))})
receipt["current_dispatch"] = _single_factor_change(*snapshots, FACTOR)
receipt["existing_exact_helper"] = _single_entry_conjunct_change(*snapshots, FILTERS)
assert receipt["current_dispatch"] is False
assert receipt["existing_exact_helper"] is True
negative_changes = {
    "changed_exit": ('< dataframe["exit_lower"]', '< dataframe["lower"]'),
    "changed_stop": ("stoploss = -0.08", "stoploss = -0.09"),
    "changed_width": ("<= 1.10", "<= 1.11"),
    "changed_lookback": (".rolling(28)", ".rolling(27)"),
    "removed_shift": (".max().shift(1)", ".max()"),
    "one_side_only": (' & (' + FILTER + ')', ""),
}
receipt["helper_negative_cases"] = {}
for label, (before, after) in negative_changes.items():
    changed = sources[1].replace(before, after, 1)
    assert changed != sources[1]
    child = SimpleNamespace(code_text=changed, class_name=snapshots[1].class_name)
    accepted = _single_entry_conjunct_change(snapshots[0], child, FILTERS)
    receipt["helper_negative_cases"][label] = accepted
    assert not accepted
try:
    analyze_bounded_causal_strategy(sources[0].replace("startup_candle_count = 29", "startup_candle_count = 28"), snapshots[0].class_name, expected_timeframe="1d")
    raise AssertionError("startup guard missing")
except BoundedStrategyError as exc:
    receipt["insufficient_startup_error"] = exc.code

import pandas as pd
receipt["pandas"] = pd.__version__
classes = []
for snap in snapshots:
    tree = ast.parse(snap.code_text)
    tree.body = [n for n in tree.body if isinstance(n, ast.ClassDef)]
    namespace = {"IStrategy": type("IStrategy", (), {}), "DataFrame": pd.DataFrame}
    exec(compile(tree, "<synthetic-strategy>", "exec"), namespace)
    classes.append(namespace[snap.class_name]())

def frame(prior, current):
    values = [100.0] * 5 + prior + [current]
    return pd.DataFrame({"date": pd.date_range("2000-01-01", periods=len(values), tz="UTC"),
        "open": values, "high": [v * 1.01 for v in values], "low": [v * .99 for v in values],
        "close": values, "volume": [100.0] * len(values)})

def evaluate(strategy, data):
    data = strategy.populate_indicators(data.copy(), {})
    data = strategy.populate_entry_trend(data, {})
    return strategy.populate_exit_trend(data, {})

cases = {
    "narrow_long": (frame([100.0, 109.0] * 14, 115.0), "enter_long", [True, True]),
    "wide_long": (frame([100.0, 130.0] * 14, 140.0), "enter_long", [True, False]),
    "narrow_short": (frame([100.0, 109.0] * 14, 95.0), "enter_short", [True, True]),
    "wide_short": (frame([100.0, 130.0] * 14, 90.0), "enter_short", [True, False]),
    "equal_boundary": (frame([100.0, 109.0] * 14, 109.0), "enter_long", [False, False]),
}
missing = frame([100.0, 109.0] * 14, 115.0); missing.loc[len(missing)-2, "close"] = float("nan")
zero_volume = frame([100.0, 109.0] * 14, 115.0); zero_volume.loc[len(zero_volume)-2, "volume"] = 0
cases["missing_close"] = (missing, "enter_long", [False, False])
cases["zero_volume"] = (zero_volume, "enter_long", [False, False])
receipt["synthetic_signals"] = {}
for label, (data, col, expected) in cases.items():
    results = [evaluate(strategy, data) for strategy in classes]
    observed = [bool(result[col].iloc[-1] == 1) for result in results]
    assert observed == expected, (label, observed)
    receipt["synthetic_signals"][label] = observed
    if label == "narrow_long":
        assert results[1]["upper"].iloc[-1] == 109
        assert results[1]["lower"].iloc[-1] == 100
        receipt["current_bar_excluded_from_channel"] = True
        future = pd.concat([data, frame([300.0]*28, 10.0)], ignore_index=True)
        for strategy, result in zip(classes, results):
            pd.testing.assert_frame_equal(evaluate(strategy, future).iloc[:len(data)].reset_index(drop=True), result.reset_index(drop=True))
        receipt["future_extension_preserves_prefix"] = True
receipt["scope_limit"] = "Pandas signal methods and real static dispatch only; no native fills/funding/runner/Console execution claimed."
print(json.dumps(receipt, indent=2))
