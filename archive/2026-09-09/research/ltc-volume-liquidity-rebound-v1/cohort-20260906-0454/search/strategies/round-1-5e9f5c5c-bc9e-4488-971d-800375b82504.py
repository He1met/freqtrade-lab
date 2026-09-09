import talib.abstract as ta
from pandas import DataFrame
from technical import qtpylib
from freqtrade.strategy import IStrategy


class LtcVolumeLiquidityReboundV1(IStrategy):
    INTERFACE_VERSION = 3
    timeframe = "1d"
    can_short = False
    startup_candle_count = 40
    process_only_new_candles = True
    minimal_roi = {}
    stoploss = -0.08

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["ret"] = dataframe["close"] / dataframe["close"].shift(1) - 1
        dataframe["r2"] = dataframe["ret"] * dataframe["ret"]
        dataframe["prior_m2"] = dataframe["r2"].shift(1).rolling(30).mean()
        dataframe["prior_volume"] = dataframe["volume"].shift(1).rolling(30).mean()
        dataframe["turnover_lower"] = dataframe["volume"] * dataframe["low"]
        dataframe["prior_liquidity"] = dataframe["turnover_lower"].shift(1).rolling(30).min()
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            ((dataframe["ret"] <= -0.02) & (dataframe["r2"] >= 2.25 * dataframe["prior_m2"]) & (dataframe["volume"] >= 2 * dataframe["prior_volume"]) & (dataframe["prior_m2"] > 0) & (dataframe["prior_volume"] > 0))
            & ~((dataframe["ret"].shift(1) <= -0.02) & (dataframe["r2"].shift(1) >= 2.25 * dataframe["prior_m2"].shift(1)) & (dataframe["volume"].shift(1) >= 2 * dataframe["prior_volume"].shift(1)) & (dataframe["prior_m2"].shift(1) > 0) & (dataframe["prior_volume"].shift(1) > 0))
            & ~((dataframe["ret"].shift(2) <= -0.02) & (dataframe["r2"].shift(2) >= 2.25 * dataframe["prior_m2"].shift(2)) & (dataframe["volume"].shift(2) >= 2 * dataframe["prior_volume"].shift(2)) & (dataframe["prior_m2"].shift(2) > 0) & (dataframe["prior_volume"].shift(2) > 0))
            & ~((dataframe["ret"].shift(3) <= -0.02) & (dataframe["r2"].shift(3) >= 2.25 * dataframe["prior_m2"].shift(3)) & (dataframe["volume"].shift(3) >= 2 * dataframe["prior_volume"].shift(3)) & (dataframe["prior_m2"].shift(3) > 0) & (dataframe["prior_volume"].shift(3) > 0))
            & (dataframe["prior_liquidity"] >= 500000),
            "enter_long",
        ] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[dataframe["enter_long"].shift(2) == 1, "exit_long"] = 1
        return dataframe
