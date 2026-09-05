"""One closed, standalone historical funding template for exploratory Search.

The source is matched as a whole AST. It has no deployment dependency on lab.
Original funding events must pass the source/consumer grid checks BEFORE native
hourly fill. Its 32h minimum settlement lag is an assumption, not proof of archive
publication timing. No arbitrary DataProvider or UTC expression surface is opened.
"""

import ast
import keyword
import re

FAMILY = "lagged_funding_signal_v1"
FACTOR = "entry_lagged_funding_positive_v1"


def signal_contract():
    return {
        "name": "LAGGED_FUNDING_SIGNAL_V1", "version": 1,
        "native_version": "2026.7", "series": "funding_history",
        "native_timeframe": "1h", "rate_column": "open",
        "original_grid_utc_hours": [0, 8, 16],
        "decision_event_lags_hours": [48, 40, 32],
        "ohlcv_pre_roll_candles": 289, "funding_internal_burn_in_hours": 48,
        "historical_publication_time": "UNKNOWN",
        "research_scope": "EXPLORATORY_ONLY",
    }


def funding_source(class_name="LaggedFundingR1", filtered=False):
    if not isinstance(class_name, str) or re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,79}', class_name) is None or keyword.iskeyword(class_name):
        raise ValueError("Invalid funding strategy class name")
    if type(filtered) is not bool:
        raise ValueError("Funding variant must be a boolean")
    extra = ' & (dataframe["lagged_funding"] > 0.0001)' if filtered else ''
    return '''from pandas import DataFrame
from freqtrade.strategy import IStrategy, merge_informative_pair


class CLASS_NAME(IStrategy):
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
        dataframe.loc[(dataframe["date"].dt.hour == 0) & (dataframe["date"].dt.minute == 0) & dataframe["price_valid"] & dataframe["time_valid"] & dataframe["funding_valid"] & (dataframe["return_24h"] <= -0.02)EXTRA, "enter_short"] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[(dataframe["date"].dt.hour == 8) & (dataframe["date"].dt.minute == 0), "exit_short"] = 1
        return dataframe
'''.replace('EXTRA', extra).replace('CLASS_NAME', class_name)


def template_variant(tree, class_name):
    """Return R1/R2 only for complete AST equality; never execute candidate text."""
    try:
        actual = ast.dump(tree)
        for filtered, variant in ((False, "R1"), (True, "R2")):
            if actual == ast.dump(ast.parse(funding_source(class_name, filtered))):
                return variant
    except (ValueError, SyntaxError, RecursionError):
        return None
    return None
