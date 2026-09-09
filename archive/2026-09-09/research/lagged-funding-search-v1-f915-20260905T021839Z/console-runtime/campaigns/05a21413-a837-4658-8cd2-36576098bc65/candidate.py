from pandas import DataFrame
from freqtrade.strategy import IStrategy, merge_informative_pair


class LaggedFundingR1(IStrategy):
    INTERFACE_VERSION = 3
    timeframe = "5m"
    can_short = True
    startup_candle_count = 289
    process_only_new_candles = True
    minimal_roi = {}
    stoploss = -0.03

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        funding = self.dp.get_pair_dataframe(metadata["pair"], timeframe="1h", candle_type="funding_rate")
        funding = funding.loc[(funding["date"].dt.hour % 8 == 0) & (funding["date"].dt.minute == 0)].copy()
        funding["settled_mean"] = funding["open"].rolling(3).mean()
        funding = funding[["date", "settled_mean"]]
        dataframe = merge_informative_pair(dataframe, funding, "5m", "1h", ffill=True)
        dataframe["lagged_funding"] = dataframe["settled_mean_1h"].shift(288)
        dataframe["funding_event"] = dataframe["date_1h"].shift(288)
        dataframe["price_valid"] = ((dataframe["open"] > 0) & (dataframe["high"] > 0) & (dataframe["low"] > 0) & (dataframe["close"] > 0) & (dataframe["volume"] > 0)).rolling(289).min() == 1
        dataframe["time_valid"] = (dataframe["date"].diff().dt.total_seconds() == 300).rolling(288).min() == 1
        dataframe["return_24h"] = dataframe["close"] / dataframe["close"].shift(288) - 1
        dataframe["funding_valid"] = dataframe["lagged_funding"].notna() & ((dataframe["date"] - dataframe["funding_event"]).dt.total_seconds() == 115200)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[(dataframe["date"].dt.hour == 0) & (dataframe["date"].dt.minute == 0) & dataframe["price_valid"] & dataframe["time_valid"] & dataframe["funding_valid"] & (dataframe["return_24h"] <= -0.02), "enter_short"] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[(dataframe["date"].dt.hour == 8) & (dataframe["date"].dt.minute == 0), "exit_short"] = 1
        return dataframe
