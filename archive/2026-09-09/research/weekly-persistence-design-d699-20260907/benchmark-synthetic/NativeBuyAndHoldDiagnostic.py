from pandas import DataFrame, Timestamp
from freqtrade.strategy import IStrategy

class NativeBuyAndHoldDiagnostic(IStrategy):
    INTERFACE_VERSION = 3
    timeframe = "1d"
    can_short = False
    startup_candle_count = 14
    process_only_new_candles = True
    minimal_roi = {}
    # At 1x long this maps to price zero, not an arbitrary near-total-loss stop.
    stoploss = -1.0

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        first_signal = Timestamp(self.config["timerange"].split("-")[0], tz="UTC")
        dataframe.loc[dataframe["date"] == first_signal, "enter_long"] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["exit_long"] = 0
        return dataframe
