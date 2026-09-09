import talib.abstract as ta
from pandas import DataFrame
from technical import qtpylib
from freqtrade.strategy import IStrategy


class DogeConfirmedShockReversal3D(IStrategy):
    INTERFACE_VERSION = 3
    timeframe = "1d"
    can_short = True
    startup_candle_count = 35
    process_only_new_candles = True
    minimal_roi = {}
    stoploss = -0.08

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["r"] = dataframe["close"] / dataframe["close"].shift(1) - 1
        dataframe["shock"] = dataframe["r"].shift(1)
        dataframe["gap"] = dataframe["close"] / dataframe["close"].shift(2) - 1
        dataframe["shock_squared"] = dataframe["shock"] * dataframe["shock"]
        dataframe["reversal_product"] = dataframe["shock"] * dataframe["r"]
        dataframe["gap_squared"] = dataframe["gap"] * dataframe["gap"]
        dataframe["gap_alignment"] = dataframe["gap"] * dataframe["shock"]
        dataframe["liquidity_floor"] = (dataframe["low"] * dataframe["volume"]).rolling(30).min().shift(1)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[(((dataframe["shock_squared"] >= 0.0016) & (dataframe["reversal_product"] < 0) & (dataframe["gap_squared"] >= 0.0004) & (dataframe["gap_alignment"] > 0) & (dataframe["liquidity_floor"] >= 500000) & (dataframe["volume"] > 0)) & ~((dataframe["shock_squared"].shift(1) >= 0.0016) & (dataframe["reversal_product"].shift(1) < 0) & (dataframe["gap_squared"].shift(1) >= 0.0004) & (dataframe["gap_alignment"].shift(1) > 0) & (dataframe["liquidity_floor"].shift(1) >= 500000) & (dataframe["volume"].shift(1) > 0)) & ~((dataframe["shock_squared"].shift(2) >= 0.0016) & (dataframe["reversal_product"].shift(2) < 0) & (dataframe["gap_squared"].shift(2) >= 0.0004) & (dataframe["gap_alignment"].shift(2) > 0) & (dataframe["liquidity_floor"].shift(2) >= 500000) & (dataframe["volume"].shift(2) > 0)) & ~((dataframe["shock_squared"].shift(3) >= 0.0016) & (dataframe["reversal_product"].shift(3) < 0) & (dataframe["gap_squared"].shift(3) >= 0.0004) & (dataframe["gap_alignment"].shift(3) > 0) & (dataframe["liquidity_floor"].shift(3) >= 500000) & (dataframe["volume"].shift(3) > 0))) & (dataframe["shock"] < 0), "enter_long"] = 1
        dataframe.loc[(((dataframe["shock_squared"] >= 0.0016) & (dataframe["reversal_product"] < 0) & (dataframe["gap_squared"] >= 0.0004) & (dataframe["gap_alignment"] > 0) & (dataframe["liquidity_floor"] >= 500000) & (dataframe["volume"] > 0)) & ~((dataframe["shock_squared"].shift(1) >= 0.0016) & (dataframe["reversal_product"].shift(1) < 0) & (dataframe["gap_squared"].shift(1) >= 0.0004) & (dataframe["gap_alignment"].shift(1) > 0) & (dataframe["liquidity_floor"].shift(1) >= 500000) & (dataframe["volume"].shift(1) > 0)) & ~((dataframe["shock_squared"].shift(2) >= 0.0016) & (dataframe["reversal_product"].shift(2) < 0) & (dataframe["gap_squared"].shift(2) >= 0.0004) & (dataframe["gap_alignment"].shift(2) > 0) & (dataframe["liquidity_floor"].shift(2) >= 500000) & (dataframe["volume"].shift(2) > 0)) & ~((dataframe["shock_squared"].shift(3) >= 0.0016) & (dataframe["reversal_product"].shift(3) < 0) & (dataframe["gap_squared"].shift(3) >= 0.0004) & (dataframe["gap_alignment"].shift(3) > 0) & (dataframe["liquidity_floor"].shift(3) >= 500000) & (dataframe["volume"].shift(3) > 0))) & (dataframe["shock"] > 0), "enter_short"] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[(dataframe["enter_long"].shift(3) == 1) | (dataframe["enter_short"].shift(3) == 1), "exit_long"] = 1
        dataframe.loc[(dataframe["enter_long"].shift(3) == 1) | (dataframe["enter_short"].shift(3) == 1), "exit_short"] = 1
        return dataframe
