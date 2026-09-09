import talib.abstract as ta
from pandas import DataFrame
from technical import qtpylib
from freqtrade.strategy import IStrategy


class AtomRegimePullbackV1(IStrategy):
    INTERFACE_VERSION = 3
    timeframe = "1d"
    can_short = False
    startup_candle_count = 200
    process_only_new_candles = True
    minimal_roi = {}
    stoploss = -0.08

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["mean20"] = dataframe["close"].rolling(20).mean()
        dataframe["mean200"] = dataframe["close"].rolling(200).mean()
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (dataframe["close"] <= dataframe["mean20"] * 0.96)
            & (dataframe["close"] > dataframe["mean200"])
            & (dataframe["volume"] > 0), "enter_long",
        ] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            ((dataframe["close"] >= dataframe["mean20"])
             | (dataframe["close"] < dataframe["mean200"]))
            & (dataframe["volume"] > 0), "exit_long",
        ] = 1
        return dataframe
