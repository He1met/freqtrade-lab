import talib.abstract as ta
from pandas import DataFrame
from technical import qtpylib
from freqtrade.strategy import IStrategy


class DogeConfirmedShockReversal3D(IStrategy):
    INTERFACE_VERSION = 3
    timeframe = "1d"
    can_short = True
    startup_candle_count = 35
    process_only_new_candles = True
    minimal_roi = {}
    stoploss = -0.08

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["r"] = dataframe["close"] / dataframe["close"].shift(1) - 1
        dataframe["liquidity_floor"] = (dataframe["low"] * dataframe["volume"]).rolling(30).min().shift(1)
        dataframe["raw_long"] = (dataframe["r"].shift(1) <= -0.04) & (dataframe["r"] > 0) & (dataframe["close"] <= 0.98 * dataframe["close"].shift(2)) & (dataframe["liquidity_floor"] >= 500000) & (dataframe["volume"] > 0)
        dataframe["raw_short"] = (dataframe["r"].shift(1) >= 0.04) & (dataframe["r"] < 0) & (dataframe["close"] >= 1.02 * dataframe["close"].shift(2)) & (dataframe["liquidity_floor"] >= 500000) & (dataframe["volume"] > 0)
        dataframe["raw_event"] = dataframe["raw_long"] | dataframe["raw_short"]
        dataframe["previous_event"] = dataframe["raw_event"].rolling(3).max().shift(1)
        dataframe["admitted_event"] = dataframe["raw_event"] & (dataframe["previous_event"] == 0)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[dataframe["raw_long"] & dataframe["admitted_event"], "enter_long"] = 1
        dataframe.loc[dataframe["raw_short"] & dataframe["admitted_event"], "enter_short"] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[dataframe["admitted_event"].shift(3) == 1, "exit_long"] = 1
        dataframe.loc[dataframe["admitted_event"].shift(3) == 1, "exit_short"] = 1
        return dataframe
