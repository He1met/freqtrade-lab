import talib.abstract as ta
from pandas import DataFrame
from technical import qtpylib
from freqtrade.strategy import IStrategy


class BtcWeeklyMomentumFixedStake(IStrategy):
    INTERFACE_VERSION = 3
    timeframe = "1d"
    can_short = False
    startup_candle_count = 29
    process_only_new_candles = True
    minimal_roi = {}
    stoploss = -0.08

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["momentum28"] = dataframe["close"] / dataframe["close"].shift(28) - 1
        dataframe["weekday"] = dataframe["date"].dt.tz_convert("UTC").dt.dayofweek
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[(dataframe["weekday"] == 6) & (dataframe["momentum28"] > 0) & (dataframe["volume"] > 0), "enter_long"] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[(dataframe["weekday"] == 6) & (dataframe["momentum28"] <= 0), "exit_long"] = 1
        return dataframe
