import talib.abstract as ta
from pandas import DataFrame
from technical import qtpylib
from freqtrade.strategy import IStrategy


class ClosedShockContinuationR1(IStrategy):
    INTERFACE_VERSION = 3
    timeframe = "5m"
    can_short = True
    startup_candle_count = 18
    process_only_new_candles = True
    minimal_roi = {"180": -1.0}
    stoploss = -0.02

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["minute"] = dataframe["date"].dt.tz_convert("America/New_York").dt.minute
        dataframe["closed_shock"] = dataframe["close"].shift(6) / dataframe["open"].shift(17) - 1
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[(dataframe["minute"] == 25) & (dataframe["closed_shock"] >= 0.01) & (dataframe["volume"] > 0), "enter_long"] = 1
        dataframe.loc[(dataframe["minute"] == 25) & (dataframe["closed_shock"] <= -0.01) & (dataframe["volume"] > 0), "enter_short"] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        return dataframe
