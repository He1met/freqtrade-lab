import talib.abstract as ta
from pandas import DataFrame
from technical import qtpylib
from freqtrade.strategy import IStrategy

class ConsolidationChannelR2(IStrategy):
    INTERFACE_VERSION = 3
    timeframe = "1d"
    can_short = True
    startup_candle_count = 29
    process_only_new_candles = True
    minimal_roi = {}
    stoploss = -0.08

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["upper"] = dataframe["close"].rolling(28).max().shift(1)
        dataframe["lower"] = dataframe["close"].rolling(28).min().shift(1)
        dataframe["exit_upper"] = dataframe["close"].rolling(14).max().shift(1)
        dataframe["exit_lower"] = dataframe["close"].rolling(14).min().shift(1)
        dataframe["valid_close"] = dataframe["close"].rolling(29).min()
        dataframe["valid_volume"] = dataframe["volume"].rolling(29).min()
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[(((dataframe["valid_close"] > 0) & (dataframe["valid_volume"] > 0)) & (dataframe["close"] > dataframe["upper"])) & ((dataframe["close"].rolling(28).max().shift(1) / dataframe["close"].rolling(28).min().shift(1)) <= 1.10), "enter_long"] = 1
        dataframe.loc[(((dataframe["valid_close"] > 0) & (dataframe["valid_volume"] > 0)) & (dataframe["close"] < dataframe["lower"])) & ((dataframe["close"].rolling(28).max().shift(1) / dataframe["close"].rolling(28).min().shift(1)) <= 1.10), "enter_short"] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[((dataframe["valid_close"] > 0) & (dataframe["valid_volume"] > 0)) & (dataframe["close"] < dataframe["exit_lower"]), "exit_long"] = 1
        dataframe.loc[((dataframe["valid_close"] > 0) & (dataframe["valid_volume"] > 0)) & (dataframe["close"] > dataframe["exit_upper"]), "exit_short"] = 1
        return dataframe
