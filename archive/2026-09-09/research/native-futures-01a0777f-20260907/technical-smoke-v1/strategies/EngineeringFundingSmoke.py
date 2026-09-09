from pandas import DataFrame
from freqtrade.strategy import IStrategy

class EngineeringFundingSmoke(IStrategy):
    INTERFACE_VERSION = 3
    timeframe = "1d"
    can_short = True
    startup_candle_count = 14
    process_only_new_candles = True
    minimal_roi = {}
    stoploss = -0.99

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[dataframe["date"].dt.dayofweek == 0, "enter_long"] = 1
        dataframe.loc[dataframe["date"].dt.dayofweek == 3, "enter_short"] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[dataframe["date"].dt.dayofweek == 2, "exit_long"] = 1
        dataframe.loc[dataframe["date"].dt.dayofweek == 5, "exit_short"] = 1
        return dataframe
