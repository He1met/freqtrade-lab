"""Small native hourly perpetual strategy; no custom matching or trade engine."""
from datetime import timedelta

import numpy as np
from freqtrade.strategy import IStrategy

PAIRS = ("BTC/USDT:USDT", "ETH/USDT:USDT")
VARIANTS = ("baseline", "persistence", "volatility", "fixed")


def features(frame):
    """Each row is available only at its candle close; native shifts signals."""
    out = frame.copy()
    returns = np.log(out.close / out.close.shift(1))
    out["persistence"] = returns.rolling(24).sum() / returns.abs().rolling(24).sum().replace(0, np.nan)
    short = returns.rolling(24).std(ddof=0)
    long = returns.rolling(168).std(ddof=0)
    out["risk_multiplier"] = (long / short.replace(0, np.nan)).clip(.25, 1.)
    out["baseline_long"] = out.close > out.high.shift(1).rolling(24).max()
    out["baseline_short"] = out.close < out.low.shift(1).rolling(24).min()
    out["channel_exit_long"] = out.close < out.low.shift(1).rolling(12).min()
    out["channel_exit_short"] = out.close > out.high.shift(1).rolling(12).max()
    return out


def calibrate_fixed(frames, start, end):
    values = []
    for frame in frames.values():
        f = features(frame)
        # date is candle OPEN; only closes strictly before train boundary qualify.
        eligible = ((f.date + timedelta(hours=1) >= start) &
                    (f.date + timedelta(hours=1) < end) &
                    (f.baseline_long | f.baseline_short))
        values.extend(f.loc[eligible, "risk_multiplier"].dropna().tolist())
    if not values:
        raise ValueError("no training baseline signals for fixed-risk calibration")
    return float(np.mean(values)), len(values)


class PerpBaseline(IStrategy):
    INTERFACE_VERSION = 3
    timeframe = "1h"
    can_short = True
    startup_candle_count = 168
    minimal_roi = {}
    stoploss = -.20
    position_adjustment_enable = False
    process_only_new_candles = True
    use_exit_signal = True

    def bot_start(self, **kwargs):
        if (self.config.get("dry_run") is not True or
                self.config.get("runmode").value != "backtest" or
                tuple(self.config["exchange"]["pair_whitelist"]) != PAIRS or
                self.config.get("perp_variant") not in VARIANTS):
            raise ValueError("offline two-pair experiment configuration required")
        self.entry_audit = []

    def populate_indicators(self, dataframe, metadata):
        return features(dataframe)

    def populate_entry_trend(self, dataframe, metadata):
        valid = dataframe.risk_multiplier.notna() & (dataframe.volume > 0)
        long = dataframe.baseline_long & valid
        short = dataframe.baseline_short & valid
        if self.config["perp_variant"] == "persistence":
            long &= dataframe.persistence >= .25
            short &= dataframe.persistence <= -.25
        # Source declares close + 60s availability. Hourly execution therefore
        # waits one further candle before the native next-bar shift.
        dataframe["enter_long"] = long.shift(1, fill_value=False).astype(int)
        dataframe["enter_short"] = short.shift(1, fill_value=False).astype(int)
        dataframe["enter_tag"] = "hourly_breakout_v1"
        return dataframe

    def populate_exit_trend(self, dataframe, metadata):
        dataframe["exit_long"] = dataframe.channel_exit_long.shift(1, fill_value=False).astype(int)
        dataframe["exit_short"] = dataframe.channel_exit_short.shift(1, fill_value=False).astype(int)
        return dataframe

    def custom_exit(self, pair, trade, current_time, current_rate, current_profit, **kwargs):
        if current_time - trade.open_date_utc >= timedelta(hours=72):
            return "holding_72h"
        return None

    def custom_stake_amount(self, pair, current_time, current_rate, proposed_stake,
                            min_stake, max_stake, leverage, entry_tag, side, **kwargs):
        frame, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if len(frame) < 2:
            return 0.
        row = frame.iloc[-2]
        if row.date + timedelta(hours=1, seconds=60) > current_time:
            raise ValueError("incomplete candle in native stake callback")
        variant = self.config["perp_variant"]
        multiplier = (float(row.risk_multiplier) if variant == "volatility" else
                      float(self.config["perp_fixed_multiplier"]) if variant == "fixed" else 1.)
        if not np.isfinite(multiplier) or not .25 <= multiplier <= 1.:
            return 0.
        # A single native wallet controls both pairs. Realized wallet capital is
        # used for allocation, with native free-margin clamping; MTM is separately
        # audited from real native fills. No claim of continuous 80% MTM cap.
        desired = min(self.wallets.get_total_stake_amount() * .4 * multiplier, max_stake)
        accepted = desired if desired >= (min_stake or 0.) else 0.
        self.entry_audit.append(dict(pair=pair, at=current_time.isoformat(),
            signal_candle=row.date.isoformat(), multiplier=multiplier,
            desired_stake=desired, accepted_stake=accepted, native_minimum=min_stake))
        return accepted

    def leverage(self, **kwargs):
        return 1.
