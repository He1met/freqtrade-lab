import talib.abstract as ta
from pandas import DataFrame
from technical import qtpylib
from freqtrade.strategy import IStrategy


class CausalPriceChannel20x10TightStop(IStrategy):
    INTERFACE_VERSION = 3
    timeframe = "1d"
    can_short = False
    startup_candle_count = 21
    process_only_new_candles = True
    minimal_roi = {}
    stoploss = -0.12

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["entry_channel"] = dataframe["high"].rolling(20).max().shift(1)
        dataframe["exit_channel"] = dataframe["low"].rolling(10).min().shift(1)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[dataframe["close"] > dataframe["entry_channel"], "enter_long"] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[dataframe["close"] < dataframe["exit_channel"], "exit_long"] = 1
        return dataframe
