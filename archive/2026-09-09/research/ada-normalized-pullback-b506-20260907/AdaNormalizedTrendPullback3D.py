import talib.abstract as ta
from pandas import DataFrame
from technical import qtpylib
from freqtrade.strategy import IStrategy


class AdaNormalizedTrendPullback3D(IStrategy):
    INTERFACE_VERSION = 3
    timeframe = "1d"
    can_short = True
    startup_candle_count = 72
    process_only_new_candles = True
    minimal_roi = {}
    stoploss = -0.08

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["r"] = dataframe["close"] / dataframe["close"].shift(1) - 1
        dataframe["r_squared"] = dataframe["r"] * dataframe["r"]
        dataframe["v"] = dataframe["r_squared"].rolling(20).mean().shift(1)
        dataframe["m"] = dataframe["close"].rolling(60).mean()
        dataframe["gap"] = dataframe["close"].shift(1) - dataframe["m"].shift(1)
        dataframe["slope"] = dataframe["m"].shift(1) - dataframe["m"].shift(6)
        dataframe["trend_activity"] = dataframe["gap"] * dataframe["slope"] * dataframe["v"] * dataframe["volume"]
        dataframe["shock_alignment"] = dataframe["r"] * dataframe["gap"]
        dataframe["normalized_excess"] = dataframe["r_squared"] - 2.25 * dataframe["v"]
        dataframe["liquidity_floor"] = (dataframe["low"] * dataframe["volume"]).rolling(30).min().shift(1)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[(((dataframe["trend_activity"] > 0) & (dataframe["shock_alignment"] < 0) & (dataframe["r_squared"] >= 0.00015625) & (dataframe["normalized_excess"] >= 0) & (dataframe["liquidity_floor"] >= 500000)) & ~((dataframe["trend_activity"].shift(1) > 0) & (dataframe["shock_alignment"].shift(1) < 0) & (dataframe["r_squared"].shift(1) >= 0.00015625) & (dataframe["normalized_excess"].shift(1) >= 0) & (dataframe["liquidity_floor"].shift(1) >= 500000)) & ~((dataframe["trend_activity"].shift(2) > 0) & (dataframe["shock_alignment"].shift(2) < 0) & (dataframe["r_squared"].shift(2) >= 0.00015625) & (dataframe["normalized_excess"].shift(2) >= 0) & (dataframe["liquidity_floor"].shift(2) >= 500000)) & ~((dataframe["trend_activity"].shift(3) > 0) & (dataframe["shock_alignment"].shift(3) < 0) & (dataframe["r_squared"].shift(3) >= 0.00015625) & (dataframe["normalized_excess"].shift(3) >= 0) & (dataframe["liquidity_floor"].shift(3) >= 500000))) & (dataframe["r"] < 0), "enter_long"] = 1
        dataframe.loc[(((dataframe["trend_activity"] > 0) & (dataframe["shock_alignment"] < 0) & (dataframe["r_squared"] >= 0.00015625) & (dataframe["normalized_excess"] >= 0) & (dataframe["liquidity_floor"] >= 500000)) & ~((dataframe["trend_activity"].shift(1) > 0) & (dataframe["shock_alignment"].shift(1) < 0) & (dataframe["r_squared"].shift(1) >= 0.00015625) & (dataframe["normalized_excess"].shift(1) >= 0) & (dataframe["liquidity_floor"].shift(1) >= 500000)) & ~((dataframe["trend_activity"].shift(2) > 0) & (dataframe["shock_alignment"].shift(2) < 0) & (dataframe["r_squared"].shift(2) >= 0.00015625) & (dataframe["normalized_excess"].shift(2) >= 0) & (dataframe["liquidity_floor"].shift(2) >= 500000)) & ~((dataframe["trend_activity"].shift(3) > 0) & (dataframe["shock_alignment"].shift(3) < 0) & (dataframe["r_squared"].shift(3) >= 0.00015625) & (dataframe["normalized_excess"].shift(3) >= 0) & (dataframe["liquidity_floor"].shift(3) >= 500000))) & (dataframe["r"] > 0), "enter_short"] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[(dataframe["enter_long"].shift(3) == 1) | (dataframe["enter_short"].shift(3) == 1), "exit_long"] = 1
        dataframe.loc[(dataframe["enter_long"].shift(3) == 1) | (dataframe["enter_short"].shift(3) == 1), "exit_short"] = 1
        return dataframe
