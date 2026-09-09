import talib.abstract as ta
from pandas import DataFrame
from technical import qtpylib
from freqtrade.strategy import IStrategy


class BchPriorCloseTrend28(IStrategy):
    INTERFACE_VERSION = 3
    timeframe = "1d"
    can_short = True
    startup_candle_count = 29
    process_only_new_candles = True
    minimal_roi = {}
    stoploss = -0.08

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe['prior_upper_28'] = dataframe['close'].rolling(28).max().shift(1)
        dataframe['prior_lower_28'] = dataframe['close'].rolling(28).min().shift(1)
        dataframe['prior_upper_14'] = dataframe['close'].rolling(14).max().shift(1)
        dataframe['prior_lower_14'] = dataframe['close'].rolling(14).min().shift(1)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (dataframe['close'] > dataframe['prior_upper_28'])
            & (dataframe['volume'] > 0),
            'enter_long',
        ] = 1
        dataframe.loc[
            (dataframe['close'] < dataframe['prior_lower_28'])
            & (dataframe['volume'] > 0),
            'enter_short',
        ] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            dataframe['close'] < dataframe['prior_lower_14'],
            'exit_long',
        ] = 1
        dataframe.loc[
            dataframe['close'] > dataframe['prior_upper_14'],
            'exit_short',
        ] = 1
        return dataframe
