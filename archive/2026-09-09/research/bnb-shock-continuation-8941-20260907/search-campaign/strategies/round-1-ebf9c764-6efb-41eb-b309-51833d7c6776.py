import talib.abstract as ta
from pandas import DataFrame
from technical import qtpylib
from freqtrade.strategy import IStrategy


class BnbDailyShockContinuation48H(IStrategy):
    INTERFACE_VERSION = 3
    timeframe = "1d"
    can_short = True
    startup_candle_count = 35
    process_only_new_candles = True
    minimal_roi = {}
    stoploss = -0.08

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["daily_return"] = dataframe["close"] / dataframe["close"].shift(1) - 1
        dataframe["prior_liquidity"] = (dataframe["low"] * dataframe["volume"]).shift(1).rolling(30).min()
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[((((dataframe["daily_return"] >= 0.03) | (dataframe["daily_return"] <= -0.03)) & (dataframe["volume"] > 0) & (dataframe["prior_liquidity"] >= 500000)) & ~(((dataframe["daily_return"].shift(1) >= 0.03) | (dataframe["daily_return"].shift(1) <= -0.03)) & (dataframe["volume"].shift(1) > 0) & (dataframe["prior_liquidity"].shift(1) >= 500000)) & ~(((dataframe["daily_return"].shift(2) >= 0.03) | (dataframe["daily_return"].shift(2) <= -0.03)) & (dataframe["volume"].shift(2) > 0) & (dataframe["prior_liquidity"].shift(2) >= 500000))) & (dataframe["daily_return"] >= 0.03), "enter_long"] = 1
        dataframe.loc[((((dataframe["daily_return"] >= 0.03) | (dataframe["daily_return"] <= -0.03)) & (dataframe["volume"] > 0) & (dataframe["prior_liquidity"] >= 500000)) & ~(((dataframe["daily_return"].shift(1) >= 0.03) | (dataframe["daily_return"].shift(1) <= -0.03)) & (dataframe["volume"].shift(1) > 0) & (dataframe["prior_liquidity"].shift(1) >= 500000)) & ~(((dataframe["daily_return"].shift(2) >= 0.03) | (dataframe["daily_return"].shift(2) <= -0.03)) & (dataframe["volume"].shift(2) > 0) & (dataframe["prior_liquidity"].shift(2) >= 500000))) & (dataframe["daily_return"] <= -0.03), "enter_short"] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[(dataframe["enter_long"].shift(2) == 1) | (dataframe["enter_short"].shift(2) == 1), "exit_long"] = 1
        dataframe.loc[(dataframe["enter_long"].shift(2) == 1) | (dataframe["enter_short"].shift(2) == 1), "exit_short"] = 1
        return dataframe
