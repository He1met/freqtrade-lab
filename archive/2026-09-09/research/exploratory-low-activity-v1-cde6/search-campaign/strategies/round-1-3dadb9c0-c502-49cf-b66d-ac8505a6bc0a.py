import talib.abstract as ta
from pandas import DataFrame
from technical import qtpylib
from freqtrade.strategy import IStrategy


class LowActivityR1(IStrategy):
    INTERFACE_VERSION = 3
    timeframe = "5m"
    can_short = True
    startup_candle_count = 73
    process_only_new_candles = True
    minimal_roi = {}
    stoploss = -0.02

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        bands = qtpylib.bollinger_bands(dataframe["close"], window=72, stds=2)
        dataframe["reversion_mean"] = bands["mid"]
        dataframe["reversion_lower"] = bands["lower"]
        dataframe["reversion_upper"] = bands["upper"]
        dataframe["full_price_min"] = dataframe["close"].rolling(72).min()
        dataframe["prior_volume_mean"] = dataframe["volume"].shift(1).rolling(72).mean()
        dataframe["prior_volume_min"] = dataframe["volume"].shift(1).rolling(72).min()
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (dataframe["close"] < dataframe["reversion_lower"])
            & (dataframe["reversion_upper"] > dataframe["reversion_lower"])
            & (dataframe["full_price_min"] > 0)
            & (dataframe["prior_volume_min"] > 0)
            & (dataframe["volume"] > 0),
            "enter_long",
        ] = 1
        dataframe.loc[
            (dataframe["close"] > dataframe["reversion_upper"])
            & (dataframe["reversion_upper"] > dataframe["reversion_lower"])
            & (dataframe["full_price_min"] > 0)
            & (dataframe["prior_volume_min"] > 0)
            & (dataframe["volume"] > 0),
            "enter_short",
        ] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (dataframe["close"] >= dataframe["reversion_mean"])
            & (dataframe["full_price_min"] > 0)
            & (dataframe["volume"] > 0),
            "exit_long",
        ] = 1
        dataframe.loc[
            (dataframe["close"] <= dataframe["reversion_mean"])
            & (dataframe["full_price_min"] > 0)
            & (dataframe["volume"] > 0),
            "exit_short",
        ] = 1
        return dataframe
