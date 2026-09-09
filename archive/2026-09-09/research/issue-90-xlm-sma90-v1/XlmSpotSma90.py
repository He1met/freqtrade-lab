import talib.abstract as ta
from pandas import DataFrame
from technical import qtpylib
from freqtrade.strategy import IStrategy


class XlmSpotSma90(IStrategy):
    INTERFACE_VERSION = 3
    timeframe = "1d"
    can_short = False
    startup_candle_count = 90
    process_only_new_candles = True
    minimal_roi = {}
    stoploss = -0.20

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["sma90"] = dataframe["close"].rolling(90).mean()
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[dataframe["close"] > dataframe["sma90"], "enter_long"] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[dataframe["close"] < dataframe["sma90"], "exit_long"] = 1
        return dataframe
