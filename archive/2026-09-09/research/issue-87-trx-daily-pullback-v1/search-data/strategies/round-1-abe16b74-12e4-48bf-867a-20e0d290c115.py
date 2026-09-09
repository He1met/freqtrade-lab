import talib.abstract as ta
from pandas import DataFrame
from technical import qtpylib
from freqtrade.strategy import IStrategy


class TrxDailyPullbackV1(IStrategy):
    INTERFACE_VERSION = 3
    timeframe = "1d"
    can_short = False
    startup_candle_count = 10
    process_only_new_candles = True
    minimal_roi = {}
    stoploss = -0.08

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["mean5"] = dataframe["close"].rolling(5).mean()
        dataframe["return3"] = dataframe["close"] / dataframe["close"].shift(3) - 1
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (dataframe["return3"] <= -0.03)
            & (dataframe["close"] < dataframe["mean5"])
            & (dataframe["volume"] > 0),
            "enter_long",
        ] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (dataframe["close"] >= dataframe["mean5"])
            & (dataframe["volume"] > 0),
            "exit_long",
        ] = 1
        return dataframe
