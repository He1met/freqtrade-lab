import talib.abstract as ta
from pandas import DataFrame
from technical import qtpylib
from freqtrade.strategy import IStrategy


class SessionBaselineV1(IStrategy):
    INTERFACE_VERSION = 3
    timeframe = "5m"
    can_short = True
    startup_candle_count = 72
    process_only_new_candles = True
    minimal_roi = {}
    stoploss = -0.02

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["ny_hour"] = dataframe["date"].dt.tz_convert("America/New_York").dt.hour
        dataframe["ny_minute"] = dataframe["date"].dt.tz_convert("America/New_York").dt.minute
        dataframe["ny_weekday"] = dataframe["date"].dt.tz_convert("America/New_York").dt.dayofweek
        dataframe["morning"] = dataframe["close"].shift(66) / dataframe["open"].shift(71) - 1
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (dataframe["ny_weekday"] < 5)
            & (dataframe["ny_hour"] == 15)
            & (dataframe["ny_minute"] == 25)
            & (dataframe["morning"] > 0)
            & (dataframe["volume"] > 0),
            "enter_long",
        ] = 1
        dataframe.loc[
            (dataframe["ny_weekday"] < 5)
            & (dataframe["ny_hour"] == 15)
            & (dataframe["ny_minute"] == 25)
            & (dataframe["morning"] < 0)
            & (dataframe["volume"] > 0),
            "enter_short",
        ] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (dataframe["ny_hour"] == 15) & (dataframe["ny_minute"] == 55),
            "exit_long",
        ] = 1
        dataframe.loc[
            (dataframe["ny_hour"] == 15) & (dataframe["ny_minute"] == 55),
            "exit_short",
        ] = 1
        return dataframe
