import talib.abstract as ta
from pandas import DataFrame
from technical import qtpylib
from freqtrade.strategy import IStrategy


class EthFiveDayReversalR1(IStrategy):
    INTERFACE_VERSION = 3
    timeframe = "1d"
    can_short = True
    startup_candle_count = 30
    process_only_new_candles = True
    minimal_roi = {}
    stoploss = -0.15

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["close_5"] = dataframe["close"].shift(5)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[dataframe["close"] < dataframe["close_5"], "enter_long"] = 1
        dataframe.loc[dataframe["close"] > dataframe["close_5"], "enter_short"] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[dataframe["close"] > dataframe["close_5"], "exit_long"] = 1
        dataframe.loc[dataframe["close"] < dataframe["close_5"], "exit_short"] = 1
        return dataframe
