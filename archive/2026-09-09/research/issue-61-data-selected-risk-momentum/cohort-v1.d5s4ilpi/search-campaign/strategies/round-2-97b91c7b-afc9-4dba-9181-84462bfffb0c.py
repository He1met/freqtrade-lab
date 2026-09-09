import talib.abstract as ta
from pandas import DataFrame
from technical import qtpylib
from freqtrade.strategy import IStrategy


class DataSelectedRiskMomentumR2(IStrategy):
    INTERFACE_VERSION = 3
    timeframe = "1d"
    can_short = False
    startup_candle_count = 40
    process_only_new_candles = True
    minimal_roi = {}
    stoploss = -0.10

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["close_30"] = dataframe["close"].shift(30)
        dataframe["prior_high_30"] = dataframe["high"].rolling(30).max().shift(1)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (dataframe["close"] > dataframe["close_30"])
            & (dataframe["close"] > dataframe["prior_high_30"] * 0.85),
            "enter_long",
        ] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (dataframe["close"] < dataframe["close_30"])
            | (dataframe["close"] < dataframe["prior_high_30"] * 0.85),
            "exit_long",
        ] = 1
        return dataframe
