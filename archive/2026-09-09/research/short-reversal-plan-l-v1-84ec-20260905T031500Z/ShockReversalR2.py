import talib.abstract as ta
from pandas import DataFrame
from technical import qtpylib
from freqtrade.strategy import IStrategy

# PROPOSED / NOT_EXECUTED. Feasibility specimen, not a generated Candidate.
class ShockReversalR2(IStrategy):
    INTERFACE_VERSION = 3
    timeframe = "5m"
    can_short = True
    startup_candle_count = 73
    process_only_new_candles = True
    minimal_roi = {"360": -1}
    stoploss = -0.03

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["shock"] = dataframe["close"] / dataframe["open"].shift(11) - 1
        dataframe["prior_price_mean"] = dataframe["close"].shift(1).rolling(72).mean()
        dataframe["prior_volume_mean"] = dataframe["volume"].shift(1).rolling(72).mean()
        dataframe["valid_low"] = dataframe["low"].rolling(73).min()
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[(qtpylib.crossed_below(dataframe["shock"], -0.02) & (dataframe["close"] < dataframe["prior_price_mean"] * 0.985) & (dataframe["valid_low"] > 0) & (dataframe["volume"] > 0)) & (dataframe["volume"] < dataframe["prior_volume_mean"] * 0.5), "enter_long"] = 1
        dataframe.loc[(qtpylib.crossed_above(dataframe["shock"], 0.02) & (dataframe["close"] > dataframe["prior_price_mean"] * 1.015) & (dataframe["valid_low"] > 0) & (dataframe["volume"] > 0)) & (dataframe["volume"] < dataframe["prior_volume_mean"] * 0.5), "enter_short"] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[(dataframe["close"] >= dataframe["prior_price_mean"]) & (dataframe["volume"] > 0), "exit_long"] = 1
        dataframe.loc[(dataframe["close"] <= dataframe["prior_price_mean"]) & (dataframe["volume"] > 0), "exit_short"] = 1
        return dataframe
