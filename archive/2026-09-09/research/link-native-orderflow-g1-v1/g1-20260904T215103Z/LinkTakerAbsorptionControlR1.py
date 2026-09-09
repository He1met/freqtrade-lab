import talib.abstract as ta
from pandas import DataFrame
from technical import qtpylib
from freqtrade.strategy import IStrategy

class LinkTakerAbsorptionControlR1(IStrategy):
    INTERFACE_VERSION = 3
    timeframe = "5m"
    can_short = False
    startup_candle_count = 30
    process_only_new_candles = True
    minimal_roi = {}
    stoploss = -0.03

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["prior_close"] = dataframe["close"].shift(1)
        dataframe["prior_close_2"] = dataframe["close"].shift(2)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[(dataframe["close"] > dataframe["prior_close"]) & (dataframe["prior_close"] <= dataframe["prior_close_2"]) & (dataframe["volume"] > 0), "enter_long"] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[dataframe["enter_long"].shift(1) > 0, "exit_long"] = 1
        return dataframe
