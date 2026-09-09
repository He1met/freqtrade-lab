import talib.abstract as ta
from pandas import DataFrame
from technical import qtpylib
from freqtrade.strategy import IStrategy

class BoundedCandidate(IStrategy):
    INTERFACE_VERSION = 3
    timeframe = "1d"
    can_short = False
    startup_candle_count = 20
    process_only_new_candles = True
    minimal_roi = {}
    stoploss = -0.20

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[dataframe["date"].dt.tz_convert("UTC").dt.dayofweek == 0, "enter_long"] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[dataframe["date"].dt.tz_convert("UTC").dt.dayofweek == 3, "exit_long"] = 1
        return dataframe
