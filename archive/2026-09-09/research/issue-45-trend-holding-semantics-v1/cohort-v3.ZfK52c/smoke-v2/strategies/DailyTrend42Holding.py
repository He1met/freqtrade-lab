from pandas import DataFrame
from freqtrade.strategy import IStrategy


class DailyTrend42Holding(IStrategy):
    INTERFACE_VERSION = 3
    timeframe = "1d"
    can_short = False
    startup_candle_count = 42
    process_only_new_candles = True
    minimal_roi = {}
    stoploss = -0.99

    def populate_indicators(
        self, dataframe: DataFrame, metadata: dict
    ) -> DataFrame:
        dataframe["trend_42"] = dataframe["close"].rolling(42).mean()
        return dataframe

    def populate_entry_trend(
        self, dataframe: DataFrame, metadata: dict
    ) -> DataFrame:
        dataframe.loc[
            dataframe["close"] > dataframe["trend_42"], "enter_long"
        ] = 1
        return dataframe

    def populate_exit_trend(
        self, dataframe: DataFrame, metadata: dict
    ) -> DataFrame:
        dataframe.loc[
            dataframe["close"] < dataframe["trend_42"], "exit_long"
        ] = 1
        return dataframe
