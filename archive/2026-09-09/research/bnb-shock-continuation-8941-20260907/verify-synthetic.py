"""Artificial sequences only; no backtest, exchange, database, prices or PnL read."""
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
from freqtrade.configuration import TimeRange
from freqtrade.enums import CandleType
from freqtrade.optimize.backtesting import Backtesting, HEADERS
from lab.bounded_strategy import analyze_bounded_causal_strategy

ROOT = Path(__file__).resolve().parent
source = ROOT / "BnbDailyShockContinuation48H.py"
analysis = analyze_bounded_causal_strategy(source.read_text(), "BnbDailyShockContinuation48H", expected_timeframe="1d")
spec = importlib.util.spec_from_file_location("synthetic_bnb", source)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
strategy = module.BnbDailyShockContinuation48H({})
columns = ["enter_long", "enter_short", "exit_long", "exit_short"]

def frame(shocks, n=120):
    close = [100.0]
    for t in range(1, n):
        close.append(close[-1] * (1 + shocks.get(t, 0)))
    return pd.DataFrame({"date": pd.date_range("2000-01-01", periods=n, tz="UTC", freq="D"),
                         "open": close, "high": np.array(close) * 1.01, "low": np.array(close) * .99,
                         "close": close, "volume": 100000.0})

def run(df):
    return strategy.ft_advise_signals(strategy.populate_indicators(df.copy(), {}), {"pair": "BNB/USDT:USDT"})

def oracle(df):
    c, lows, vols = df.close.tolist(), df.low.tolist(), df.volume.tolist()
    q, e = [0] * len(df), [0] * len(df)
    for t in range(30, len(df)):
        r = c[t] / c[t-1] - 1
        valid = vols[t] > 0 and min(lows[j] * vols[j] for j in range(t-30, t)) >= 500000
        q[t] = (1 if r >= .03 else -1 if r <= -.03 else 0) if valid else 0
        e[t] = q[t] if q[t-1] == q[t-2] == 0 else 0
    output = np.zeros((len(df), 4), dtype=int)
    for t in range(len(df)):
        output[t, 0], output[t, 1] = int(e[t] == 1), int(e[t] == -1)
        output[t, 2:] = int(t >= 2 and e[t-2] != 0)
    return output, q, e

checks = []
for side in (1, -1):
    df = frame({40: .04*side, 41: -.04*side, 43: .04*side, 46: -.04*side, 60: .04*side, 85: .04*side})
    df.loc[60, "volume"] = 0
    got = run(df)[columns].fillna(0).astype(int).to_numpy()
    expected, q, e = oracle(df)
    assert np.array_equal(got, expected)
    assert e[40] and q[41] and not e[41] and q[43] and not e[43] and e[46]
    assert not q[60] and not q[85]
    assert not ((got[:, 0] == 1) & (got[:, 1] == 1)).any()
    for stop in (35, 41, 42, 44, 47, 61, 86, 119):
        assert np.array_equal(run(df.iloc[:stop])[columns].fillna(0).astype(int).to_numpy(), got[:stop])
    checks.append({"side": side, "oracle_equal": True, "prefix_checks": 8,
                   "raw_event_rows": [i for i, x in enumerate(q) if x],
                   "entry_event_rows": [i for i, x in enumerate(e) if x]})
assert run(frame({}))[columns].fillna(0).to_numpy().sum() == 0

# Invoke only the real conversion/shift helper, with no Backtesting constructor,
# exchange, wallet, trade matching, native command or backtest() call.
df = frame({34: .04, 40: .04, 46: -.04, 78: .04}, n=80)
timerange = TimeRange.parse_timerange("20000205-20000321")
stub = SimpleNamespace(strategy=strategy, timeframe="1d", timerange=timerange,
    required_startup=35, config={"candle_type_def": CandleType.FUTURES},
    dataprovider=SimpleNamespace(_set_cached_df=lambda *args: None),
    _set_progress_step=lambda *args: None, _increment_progress=lambda *args: None,
    check_abort=lambda: None)
rows = Backtesting._get_ohlcv_as_lists(stub, {"BNB/USDT:USDT": strategy.populate_indicators(df.copy(), {})})["BNB/USDT:USDT"]
converted = pd.DataFrame(rows, columns=HEADERS)
entry_dates = converted.loc[(converted.enter_long == 1) | (converted.enter_short == 1), "date"].tolist()
exit_dates = converted.loc[(converted.exit_long == 1) | (converted.exit_short == 1), "date"].tolist()
assert df.date.iloc[35] not in entry_dates  # preheat shock cannot carry a position
assert df.date.iloc[41] in entry_dates and df.date.iloc[43] in exit_dates
assert df.date.iloc[47] in entry_dates and df.date.iloc[49] in exit_dates
assert (df.date.iloc[43] - df.date.iloc[41]).total_seconds() == 48*3600
assert (df.date.iloc[49] - df.date.iloc[47]).total_seconds() == 48*3600
assert df.date.iloc[79] in entry_dates  # incomplete final event is not a natural completion
assert not any(x >= df.date.iloc[79] for x in exit_dates)
report = {"status": "PASS", "scope": "SYNTHETIC_ONLY_NO_MATCHING_ENGINE_NO_PNL",
    "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
    "ast_max_lookback": analysis.max_lookback, "startup": analysis.startup_candle_count,
    "oracle_checks": checks, "flat_no_events": True,
    "actual_native_shift_helper_called": True, "native_backtest_invocations": 0,
    "next_open_entry_and_48h_exit": True, "preheat_entry_excluded": True,
    "incomplete_tail_not_natural": True,
    "note": "Validates native signal dispatch/trim/shift, not fills, stop-loss outcomes or actual profitability."}
(ROOT / "synthetic-proof.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report, indent=2))
