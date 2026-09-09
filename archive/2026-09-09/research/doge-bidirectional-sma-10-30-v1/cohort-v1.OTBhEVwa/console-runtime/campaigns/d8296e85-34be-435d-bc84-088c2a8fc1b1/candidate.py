import talib.abstract as ta
from pandas import DataFrame
from technical import qtpylib
from freqtrade.strategy import IStrategy


class DogeBidirectionalSmaR2(IStrategy):
    INTERFACE_VERSION = 3
    timeframe = "1d"
    can_short = True
    startup_candle_count = 90
    process_only_new_candles = True
    minimal_roi = {}
    stoploss = -0.10

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe['fast'] = dataframe['close'].rolling(10).mean()
        dataframe['slow'] = dataframe['close'].rolling(30).mean()
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[dataframe['fast'] > dataframe['slow'], 'enter_long'] = 1
        dataframe.loc[dataframe['fast'] < dataframe['slow'], 'enter_short'] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[dataframe['fast'] < dataframe['slow'], 'exit_long'] = 1
        dataframe.loc[dataframe['fast'] > dataframe['slow'], 'exit_short'] = 1
        return dataframe
