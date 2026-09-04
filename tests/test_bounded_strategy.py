from textwrap import indent

import pytest

from lab.bounded_strategy import (
    BOUNDED_CAUSAL_STRATEGY_V1,
    MAX_STATIC_LOOKBACK,
    BoundedStrategyError,
    analyze_bounded_causal_strategy,
    validate_bounded_causal_strategy,
)


CLASS_NAME = "BoundedCandidate"


def _source(
    indicators: str = "return dataframe",
    entry: str = "return dataframe",
    exit_: str = "return dataframe",
    *,
    class_header: str = f"class {CLASS_NAME}(IStrategy):",
    class_extra: str = "",
    module_prefix: str = "",
    module_suffix: str = "",
    timeframe: str = "5m",
    startup_candle_count: int = 20,
    can_short: bool = True,
) -> str:
    extra = "" if not class_extra else indent(class_extra.strip(), "    ") + "\n"
    return (
        module_prefix
        + "import talib.abstract as ta\n"
        + "from pandas import DataFrame\n"
        + "from technical import qtpylib\n"
        + "from freqtrade.strategy import IStrategy\n\n"
        + class_header
        + "\n"
        + "    INTERFACE_VERSION = 3\n"
        + f"    timeframe = {timeframe!r}\n"
        + f"    can_short = {can_short!r}\n"
        + f"    startup_candle_count = {startup_candle_count}\n"
        + "    process_only_new_candles = True\n"
        + '    minimal_roi = {"0": 0.0}\n'
        + "    stoploss = -0.02\n"
        + extra
        + "\n"
        + "    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:\n"
        + indent(indicators.strip(), "        ")
        + "\n\n"
        + "    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:\n"
        + indent(entry.strip(), "        ")
        + "\n\n"
        + "    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:\n"
        + indent(exit_.strip(), "        ")
        + "\n"
        + module_suffix
    )


def _error(source: str) -> BoundedStrategyError:
    with pytest.raises(BoundedStrategyError) as raised:
        validate_bounded_causal_strategy(source, CLASS_NAME)
    return raised.value


def test_t0_contract_allows_only_the_frozen_causal_5m_surface() -> None:
    source = _source(
        indicators="""
bands = qtpylib.bollinger_bands(
    qtpylib.typical_price(dataframe), window=20, stds=2
)
dataframe["bb_lower"] = bands["lower"]
dataframe["ema_fast"] = ta.EMA(dataframe, timeperiod=10)
dataframe["ema_slow"] = ta.EMA(dataframe, timeperiod=20)
dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
dataframe["recent_high"] = dataframe["high"].rolling(10).max()
dataframe["previous_low"] = dataframe["low"].shift(periods=1)
return dataframe
""",
        entry="""
dataframe.loc[
    qtpylib.crossed_above(dataframe["ema_fast"], dataframe["ema_slow"])
    & (dataframe["volume"] > 0),
    "enter_long",
] = 1
dataframe.loc[
    qtpylib.crossed_below(dataframe["ema_fast"], dataframe["ema_slow"]),
    "enter_short",
] = 1
return dataframe
""",
        exit_="""
dataframe.loc[dataframe["rsi"] > 70, "exit_long"] = 1
dataframe.loc[dataframe["rsi"] < 30, "exit_short"] = 1
return dataframe
""",
    )

    assert BOUNDED_CAUSAL_STRATEGY_V1 == "BOUNDED_CAUSAL_STRATEGY_V1"
    assert validate_bounded_causal_strategy(source, CLASS_NAME) is None
    assert analyze_bounded_causal_strategy(source, CLASS_NAME).max_lookback == 20


def test_t0_profile_bound_daily_rolling_mean_reports_84_candle_lookback() -> None:
    source = _source(
        indicators='dataframe["trend"] = dataframe["close"].rolling(84).mean()\nreturn dataframe',
        timeframe="1d",
        startup_candle_count=84,
        can_short=False,
    )

    analysis = analyze_bounded_causal_strategy(
        source, CLASS_NAME, expected_timeframe="1d"
    )

    assert analysis.timeframe == "1d"
    assert analysis.startup_candle_count == 84
    assert analysis.max_lookback == 84
    assert (
        validate_bounded_causal_strategy(
            source, CLASS_NAME, expected_timeframe="1d"
        )
        is None
    )


def test_t0_startup_must_cover_derived_rolling_and_shift_lookback() -> None:
    insufficient = _source(
        indicators='dataframe["trend"] = dataframe["close"].rolling(84).mean()\nreturn dataframe',
        timeframe="1d",
        startup_candle_count=83,
        can_short=False,
    )
    with pytest.raises(BoundedStrategyError) as raised:
        analyze_bounded_causal_strategy(
            insufficient, CLASS_NAME, expected_timeframe="1d"
        )
    assert raised.value.code == "INSUFFICIENT_STARTUP_CANDLES"

    shifted = _source(
        indicators=(
            'dataframe["trend"] = '
            'dataframe["close"].rolling(84).mean().shift(1)\n'
            "return dataframe"
        ),
        timeframe="1d",
        startup_candle_count=85,
        can_short=False,
    )
    assert analyze_bounded_causal_strategy(
        shifted, CLASS_NAME, expected_timeframe="1d"
    ).max_lookback == 85


@pytest.mark.parametrize(
    "source,code",
    [
        (_source(module_prefix="import os\n"), "MODULE_OUTSIDE_TEMPLATE"),
        (
            _source(module_suffix=f"\nsetattr({CLASS_NAME}, 'timeframe', '1h')\n"),
            "MODULE_OUTSIDE_TEMPLATE",
        ),
        (_source(module_suffix="\nclass Other:\n    pass\n"), "MODULE_OUTSIDE_TEMPLATE"),
        (
            _source(class_header=f"@staticmethod\nclass {CLASS_NAME}(IStrategy):"),
            "CLASS_OUTSIDE_TEMPLATE",
        ),
        (
            _source(class_header=f"class {CLASS_NAME}(IStrategy, metaclass=type):"),
            "CLASS_OUTSIDE_TEMPLATE",
        ),
        (_source(class_extra="print('class body')"), "CLASS_OUTSIDE_TEMPLATE"),
    ],
)
def test_t0_rejects_module_and_class_execution_surfaces(source: str, code: str) -> None:
    assert _error(source).code == code


@pytest.mark.parametrize(
    "statement,code",
    [
        ("exec('pass')", "FORBIDDEN_CALL"),
        ("eval('1')", "FORBIDDEN_CALL"),
        ("compile('1', '<x>', 'eval')", "FORBIDDEN_CALL"),
        ("__import__('os')", "FORBIDDEN_CALL"),
        ("setattr(self, 'x', 1)", "FORBIDDEN_CALL"),
        ("import os", "METHOD_BODY_MISMATCH"),
        ("global signal", "METHOD_BODY_MISMATCH"),
        ("nonlocal signal", "METHOD_BODY_MISMATCH"),
    ],
)
def test_t0_rejects_dynamic_imports_and_executable_escape_calls(
    statement: str, code: str
) -> None:
    error = _error(_source(indicators=f"{statement}\nreturn dataframe"))

    assert error.code == code


@pytest.mark.parametrize(
    "assignment,code",
    [
        (
            'signal = ta.EMA(dataframe, timeperiod=10)',
            "DYNAMIC_METHOD_BINDING",
        ),
        ("self.signal = 1", "DYNAMIC_METHOD_BINDING"),
        ('dataframe[column] = 1', "DYNAMIC_DATAFRAME_ASSIGNMENT"),
        (
            'dataframe.loc[dataframe["close"] > 0, column] = 1',
            "DYNAMIC_DATAFRAME_ASSIGNMENT",
        ),
        ('other["signal"] = 1', "DYNAMIC_DATAFRAME_ASSIGNMENT"),
        ('dataframe.at[0, "signal"] = 1', "DYNAMIC_DATAFRAME_ASSIGNMENT"),
    ],
)
def test_t0_rejects_non_dataframe_and_dynamic_assignment_targets(
    assignment: str, code: str
) -> None:
    error = _error(_source(indicators=f"{assignment}\nreturn dataframe"))

    assert error.code == code


def test_t0_rejects_repeated_local_class_method_and_column_bindings() -> None:
    bands = "bands = qtpylib.bollinger_bands(dataframe[\"close\"], window=10, stds=2)"
    assert (
        _error(_source(indicators=f"{bands}\n{bands}\nreturn dataframe")).code
        == "DYNAMIC_METHOD_BINDING"
    )

    before_binding = _source(
        indicators=(
            'dataframe["x"] = bands["mid"]\n'
            + bands
            + "\nreturn dataframe"
        )
    )
    assert _error(before_binding).code == "DYNAMIC_METHOD_BINDING"

    duplicate_field = _source(class_extra='timeframe = "5m"')
    assert _error(duplicate_field).code == "DYNAMIC_CLASS_BINDING"

    duplicate_method = _source(
        class_extra="""
def populate_indicators(self, dataframe, metadata):
    return dataframe
"""
    )
    assert _error(duplicate_method).code == "STRATEGY_METHODS_MISMATCH"

    repeated_column = _source(
        indicators='dataframe["enter_long"] = dataframe["close"]\nreturn dataframe',
        entry='dataframe.loc[dataframe["volume"] > 0, "enter_long"] = 1\nreturn dataframe',
    )
    assert _error(repeated_column).code == "REPEATED_DATAFRAME_ASSIGNMENT"


@pytest.mark.parametrize(
    "body,code",
    [
        (
            'dataframe["x"] = dataframe["close"].shift(-1)\nreturn dataframe',
            "FUTURE_AMBIGUOUS_SHIFT",
        ),
        (
            'dataframe["x"] = dataframe["close"].rolling(3, center=True).max()\nreturn dataframe',
            "DYNAMIC_ROLLING",
        ),
        ('dataframe["x"] = dataframe.iloc[-1]\nreturn dataframe', "DYNAMIC_INDEXING"),
        ('dataframe["x"] = dataframe["close"].max()\nreturn dataframe', "FULL_SAMPLE_AGGREGATE"),
        ('dataframe["x"] = dataframe["close"].mean()\nreturn dataframe', "FULL_SAMPLE_AGGREGATE"),
    ],
)
def test_t0_rejects_known_future_ambiguous_patterns(body: str, code: str) -> None:
    assert _error(_source(indicators=body)).code == code


def test_t0_rejects_executable_defaults_and_annotations() -> None:
    default = _source().replace(
        "metadata: dict) -> DataFrame:",
        "metadata: dict = eval('1')) -> DataFrame:",
        1,
    )
    assert _error(default).code == "METHOD_SIGNATURE_MISMATCH"

    annotation = _source().replace(
        "dataframe: DataFrame, metadata: dict",
        "dataframe: eval('DataFrame'), metadata: dict",
        1,
    )
    assert _error(annotation).code == "METHOD_SIGNATURE_MISMATCH"


@pytest.mark.parametrize(
    "expression",
    [
        '"x" * 1000000000',
        'b"x" * 1000000000',
        '"short"',
        "True",
        "[0] * 1000000000",
        "(0,) * 1000000000",
        "10 ** 1000000",
        "1 << 1000000",
        "1 >> 1000000",
        "1000001",
        "9" * 1000,
        "1e309",
        '{"value": dataframe["close"]}',
    ],
)
def test_t0_rejects_resource_amplifying_or_arbitrary_rhs(expression: str) -> None:
    source = _source(indicators=f'dataframe["bomb"] = {expression}\nreturn dataframe')

    assert _error(source).code == "EXPRESSION_OUTSIDE_TEMPLATE"


@pytest.mark.parametrize(
    "expression,code",
    [
        (
            f'dataframe["close"].shift({MAX_STATIC_LOOKBACK + 1})',
            "LOOKBACK_RESOURCE_LIMIT",
        ),
        (
            'dataframe["close"].rolling(21).mean()',
            "INSUFFICIENT_STARTUP_CANDLES",
        ),
        (
            'qtpylib.bollinger_bands(dataframe["close"], window=20, stds=6)',
            "LIBRARY_CALL_OUTSIDE_TEMPLATE",
        ),
        (
            'qtpylib.bollinger_bands(dataframe["close"], window=20)',
            "LIBRARY_CALL_OUTSIDE_TEMPLATE",
        ),
        (
            'qtpylib.bollinger_bands(dataframe["close"], window=dataframe["volume"])',
            "LIBRARY_CALL_OUTSIDE_TEMPLATE",
        ),
        (
            'qtpylib.crossed_above(dataframe["close"])',
            "LIBRARY_CALL_OUTSIDE_TEMPLATE",
        ),
    ],
)
def test_t0_rejects_unbounded_periods_and_library_arguments(
    expression: str, code: str
) -> None:
    source = _source(indicators=f'dataframe["bomb"] = {expression}\nreturn dataframe')

    assert _error(source).code == code


@pytest.mark.parametrize(
    "method,column,value",
    [
        ("entry", "enter_long", "dataframe[\"close\"]"),
        ("entry", "unexpected", "1"),
        ("exit", "exit_short", "0"),
    ],
)
def test_t0_rejects_nonliteral_or_unrecognized_signal_assignments(
    method: str, column: str, value: str
) -> None:
    body = (
        f'dataframe.loc[dataframe["volume"] > 0, "{column}"] = {value}\n'
        "return dataframe"
    )
    source = _source(entry=body) if method == "entry" else _source(exit_=body)

    assert _error(source).code in {
        "DYNAMIC_DATAFRAME_ASSIGNMENT",
        "EXPRESSION_OUTSIDE_TEMPLATE",
    }


def test_t0_rejects_2200_valid_shift_assignments_with_a_bounded_error() -> None:
    assignments = "\n".join(
        f'dataframe["a{index}"]=dataframe["c"].shift()'
        for index in range(2200)
    )
    source = _source(indicators=assignments + "\nreturn dataframe")

    error = _error(source)

    assert error.code in {
        "SOURCE_COMPLEXITY_LIMIT",
        "METHOD_STATEMENT_LIMIT",
        "ASSIGNED_COLUMN_LIMIT",
    }


def test_t0_deep_series_arithmetic_never_leaks_recursion_error() -> None:
    expression = " + ".join('dataframe["close"]' for _ in range(1200))
    source = _source(indicators=f'dataframe["deep"] = {expression}\nreturn dataframe')

    error = _error(source)

    assert error.code == "SOURCE_COMPLEXITY_LIMIT"


def test_t0_rejects_9000_entry_minimal_roi() -> None:
    roi = "{" + ",".join(f'"{index}":0' for index in range(9000)) + "}"
    source = _source().replace('{"0": 0.0}', roi, 1)

    error = _error(source)

    assert error.code in {"SOURCE_COMPLEXITY_LIMIT", "MINIMAL_ROI_LIMIT"}


def test_t0_enforces_method_statement_and_global_assigned_column_limits() -> None:
    too_many_statements = "\n".join(
        f'dataframe["statement_{index}"] = dataframe["close"]'
        for index in range(65)
    )
    assert _error(
        _source(indicators=too_many_statements + "\nreturn dataframe")
    ).code == "METHOD_STATEMENT_LIMIT"

    indicators = "\n".join(
        f'dataframe["column_{index}"] = dataframe["close"]'
        for index in range(63)
    )
    entry = """
dataframe.loc[dataframe["close"] > 0, "enter_long"] = 1
dataframe.loc[dataframe["close"] < 0, "enter_short"] = 1
return dataframe
"""
    assert _error(
        _source(indicators=indicators + "\nreturn dataframe", entry=entry)
    ).code == "ASSIGNED_COLUMN_LIMIT"


@pytest.mark.parametrize(
    "roi,code",
    [
        (
            "{" + ",".join(f'"{index}":0' for index in range(17)) + "}",
            "MINIMAL_ROI_LIMIT",
        ),
        ('{"10081": 0.0}', "MINIMAL_ROI_KEY_LIMIT"),
        ('{"01": 0.0}', "MINIMAL_ROI_KEY_LIMIT"),
        ('{"0": 0.0, "0": 0.1}', "MINIMAL_ROI_KEY_LIMIT"),
    ],
)
def test_t0_bounds_minimal_roi_entries_and_minute_keys(roi: str, code: str) -> None:
    source = _source().replace('{"0": 0.0}', roi, 1)

    assert _error(source).code == code
