"""Versioned, fail-closed validation for a bounded Profile-driven strategy.

This is deliberately a narrow source contract, not a general Python security
analyser or sandbox. A strategy outside the exact allowlist must not be
imported or executed by a caller.
"""

from __future__ import annotations

import ast
import keyword
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Union


BOUNDED_CAUSAL_STRATEGY_V1 = "BOUNDED_CAUSAL_STRATEGY_V1"
MAX_SOURCE_BYTES = 128 * 1024
MAX_AST_NODES = 1024
MAX_AST_DEPTH = 64
MAX_METHOD_STATEMENTS = 64
MAX_ASSIGNED_COLUMNS = 64
MAX_MINIMAL_ROI_ENTRIES = 16
MAX_MINIMAL_ROI_MINUTE = 10_080
MAX_STATIC_LOOKBACK = 512
EXPECTED_IMPORTS = (
    "import talib.abstract as ta",
    "from pandas import DataFrame",
    "from technical import qtpylib",
    "from freqtrade.strategy import IStrategy",
)
ALLOWED_STRATEGY_FIELDS = frozenset(
    {
        "INTERFACE_VERSION",
        "timeframe",
        "can_short",
        "startup_candle_count",
        "process_only_new_candles",
        "minimal_roi",
        "stoploss",
    }
)
ALLOWED_STRATEGY_METHODS = frozenset(
    {"populate_indicators", "populate_entry_trend", "populate_exit_trend"}
)
ALLOWED_LIBRARY_CALLS = frozenset(
    {
        "ta.ADX",
        "ta.EMA",
        "ta.RSI",
        "qtpylib.bollinger_bands",
        "qtpylib.crossed_above",
        "qtpylib.crossed_below",
        "qtpylib.typical_price",
    }
)
ALLOWED_DATAFRAME_CALLS = frozenset({"max", "mean", "min", "rolling", "shift"})

_CLASS_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,79}$")
_COLUMN_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,79}$")
_ROI_MINUTE = re.compile(r"^(?:0|[1-9][0-9]{0,4})$")
_FORBIDDEN_CALLS = frozenset({"exec", "eval", "compile", "__import__", "setattr"})
_MAX_LITERAL_NUMBER = 1_000_000
_SUPPORTED_TIMEFRAMES = frozenset({"5m", "1d"})
_SOURCE_COLUMNS = frozenset({"date", "open", "high", "low", "close", "volume"})
_ENTRY_SIGNAL_COLUMNS = frozenset({"enter_long", "enter_short"})
_EXIT_SIGNAL_COLUMNS = frozenset({"exit_long", "exit_short"})
_FORBIDDEN_METHOD_NODES = (
    ast.AsyncFunctionDef,
    ast.Await,
    ast.ClassDef,
    ast.Delete,
    ast.DictComp,
    ast.For,
    ast.FunctionDef,
    ast.GeneratorExp,
    ast.Global,
    ast.If,
    ast.IfExp,
    ast.Import,
    ast.ImportFrom,
    ast.JoinedStr,
    ast.Lambda,
    ast.ListComp,
    ast.NamedExpr,
    ast.Nonlocal,
    ast.Raise,
    ast.SetComp,
    ast.Try,
    ast.While,
    ast.With,
    ast.Yield,
    ast.YieldFrom,
)


class BoundedStrategyError(ValueError):
    """A normalized source-contract failure safe for a caller to classify."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class BoundedStrategyAnalysis:
    """Static execution requirements derived without importing strategy code."""

    timeframe: str
    startup_candle_count: int
    max_lookback: int


def _reject(code: str, message: str) -> None:
    raise BoundedStrategyError(code, message)


def _dotted_name(node: ast.AST) -> Optional[str]:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _dotted_name(node.value)
        return None if parent is None else f"{parent}.{node.attr}"
    return None


def _is_name(node: Optional[ast.AST], value: str) -> bool:
    return isinstance(node, ast.Name) and node.id == value


def _static_column(node: ast.AST) -> Optional[str]:
    if (
        isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and _COLUMN_NAME.fullmatch(node.value) is not None
    ):
        return node.value
    return None


def _subscript_column(node: ast.Subscript) -> Optional[str]:
    return _static_column(node.slice) if _is_name(node.value, "dataframe") else None


def _loc_parts(node: ast.Subscript) -> Optional[tuple[ast.AST, str]]:
    if not (
        isinstance(node.value, ast.Attribute)
        and node.value.attr == "loc"
        and _is_name(node.value.value, "dataframe")
        and isinstance(node.slice, ast.Tuple)
        and len(node.slice.elts) == 2
    ):
        return None
    column = _static_column(node.slice.elts[1])
    return None if column is None else (node.slice.elts[0], column)


def _literal_assignment(node: ast.Assign, label: str) -> Any:
    try:
        return ast.literal_eval(node.value)
    except (ValueError, TypeError, RecursionError) as exc:
        raise BoundedStrategyError(
            "CLASS_FIELD_NOT_LITERAL", f"{label} must be a literal"
        ) from exc


def _finite_number(value: Any, *, maximum: float) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    if isinstance(value, float) and not math.isfinite(value):
        return False
    return abs(value) <= maximum


def _validate_ast_budget(class_name: str, tree: ast.AST) -> None:
    """Bound source structure iteratively before any recursive expression checks."""

    count = 0
    stack = [(tree, 1)]
    while stack:
        node, depth = stack.pop()
        count += 1
        if count > MAX_AST_NODES or depth > MAX_AST_DEPTH:
            _reject(
                "SOURCE_COMPLEXITY_LIMIT",
                f"{class_name} source exceeds the frozen AST budget",
            )
        stack.extend(
            (child, depth + 1) for child in ast.iter_child_nodes(node)
        )


def _validate_roi_literal(class_name: str, node: ast.AST) -> None:
    if not isinstance(node, ast.Dict) or len(node.keys) > MAX_MINIMAL_ROI_ENTRIES:
        _reject(
            "MINIMAL_ROI_LIMIT",
            f"{class_name}.minimal_roi exceeds the frozen entry limit",
        )
    keys: set[str] = set()
    for key_node in node.keys:
        if (
            not isinstance(key_node, ast.Constant)
            or not isinstance(key_node.value, str)
            or _ROI_MINUTE.fullmatch(key_node.value) is None
            or int(key_node.value) > MAX_MINIMAL_ROI_MINUTE
            or key_node.value in keys
        ):
            _reject(
                "MINIMAL_ROI_KEY_LIMIT",
                f"{class_name}.minimal_roi has a key outside the frozen minute range",
            )
        keys.add(key_node.value)


def _validate_fields(
    class_name: str,
    assignments: list[ast.Assign],
    expected_timeframe: str,
) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for node in assignments:
        if (
            len(node.targets) != 1
            or not isinstance(node.targets[0], ast.Name)
            or node.type_comment is not None
        ):
            _reject("DYNAMIC_CLASS_BINDING", f"{class_name} has a dynamic class assignment")
        field = node.targets[0].id
        if field not in ALLOWED_STRATEGY_FIELDS or field in values:
            _reject(
                "DYNAMIC_CLASS_BINDING",
                f"{class_name} class field {field} is not allowed or is repeated",
            )
        if field == "minimal_roi":
            _validate_roi_literal(class_name, node.value)
        values[field] = _literal_assignment(node, f"{class_name}.{field}")
    if set(values) != ALLOWED_STRATEGY_FIELDS:
        _reject(
            "STRATEGY_FIELDS_MISMATCH",
            f"{class_name} must freeze the exact strategy fields",
        )
    roi = values["minimal_roi"]
    valid_roi = isinstance(roi, dict) and all(
        isinstance(key, str)
        and key.isdigit()
        and _finite_number(value, maximum=_MAX_LITERAL_NUMBER)
        for key, value in roi.items()
    )
    stoploss = values["stoploss"]
    startup_candle_count = values["startup_candle_count"]
    if (
        values["INTERFACE_VERSION"] != 3
        or values["timeframe"] != expected_timeframe
        or type(values["can_short"]) is not bool
        or type(startup_candle_count) is not int
        or not 1 <= startup_candle_count <= MAX_STATIC_LOOKBACK
        or values["process_only_new_candles"] is not True
        or not valid_roi
        or not _finite_number(stoploss, maximum=1)
        or not -1 < stoploss < 0
    ):
        _reject(
            "STRATEGY_FIELDS_MISMATCH",
            f"{class_name} strategy fields violate the bounded Profile template",
        )
    return values


def _static_annotation(node: Optional[ast.AST], expected: str) -> bool:
    return node is None or _is_name(node, expected)


def _validate_signature(class_name: str, method: ast.FunctionDef) -> None:
    arguments = method.args
    annotations = [argument.annotation for argument in arguments.args]
    if (
        method.decorator_list
        or arguments.posonlyargs
        or arguments.kwonlyargs
        or arguments.defaults
        or arguments.kw_defaults
        or arguments.vararg is not None
        or arguments.kwarg is not None
        or [argument.arg for argument in arguments.args]
        != ["self", "dataframe", "metadata"]
        or annotations[0] is not None
        or not _static_annotation(annotations[1], "DataFrame")
        or not _static_annotation(annotations[2], "dict")
        or not _static_annotation(method.returns, "DataFrame")
        or method.type_comment is not None
        or getattr(method, "type_params", ())
    ):
        _reject(
            "METHOD_SIGNATURE_MISMATCH",
            f"{class_name}.{method.name} signature is not allowed",
        )


def _dataframe_receiver(node: ast.AST) -> bool:
    return any(_is_name(value, "dataframe") for value in ast.walk(node))


def _session_clock(node: ast.AST) -> bool:
    """Only date.dt.tz_convert('America/New_York').dt.{hour,minute,dayofweek}."""
    if not isinstance(node, ast.Attribute) or node.attr not in {"hour", "minute", "dayofweek"}:
        return False
    accessor = node.value
    if not isinstance(accessor, ast.Attribute) or accessor.attr != "dt":
        return False
    return _session_timezone_call(accessor.value)


def _session_timezone_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call) or node.keywords or len(node.args) != 1:
        return False
    func = node.func
    return (
        isinstance(func, ast.Attribute) and func.attr == "tz_convert"
        and isinstance(func.value, ast.Attribute) and func.value.attr == "dt"
        and isinstance(func.value.value, ast.Subscript)
        and _subscript_column(func.value.value) == "date"
        and isinstance(node.args[0], ast.Constant)
        and node.args[0].value == "America/New_York"
    )


def _validate_call(class_name: str, node: ast.Call) -> None:
    if _session_timezone_call(node):
        return
    call_name = _dotted_name(node.func)
    simple_name = node.func.id if isinstance(node.func, ast.Name) else None
    name = node.func.attr if isinstance(node.func, ast.Attribute) else None
    if simple_name in _FORBIDDEN_CALLS or call_name in _FORBIDDEN_CALLS:
        _reject(
            "FORBIDDEN_CALL",
            f"{class_name} uses forbidden call {simple_name or call_name}()",
        )
    if any(isinstance(argument, ast.Starred) for argument in node.args) or any(
        keyword_node.arg is None for keyword_node in node.keywords
    ):
        _reject("FORBIDDEN_CALL", f"{class_name} uses dynamic call arguments")
    dataframe_call = (
        name in ALLOWED_DATAFRAME_CALLS
        and isinstance(node.func, ast.Attribute)
        and _dataframe_receiver(node.func.value)
    )
    if call_name not in ALLOWED_LIBRARY_CALLS and not dataframe_call:
        _reject(
            "FORBIDDEN_CALL",
            f"{class_name} uses forbidden call {call_name or simple_name or name or 'dynamic'}()",
        )
    if name == "shift":
        if len(node.args) > 1:
            period = None
        else:
            periods = [item for item in node.keywords if item.arg == "periods"]
            unexpected = [item for item in node.keywords if item.arg != "periods"]
            period = (
                None
                if unexpected or len(periods) > 1 or (node.args and periods)
                else node.args[0]
                if node.args
                else periods[0].value
                if periods
                else ast.Constant(1)
            )
        if (
            not isinstance(period, ast.Constant)
            or isinstance(period.value, bool)
            or not isinstance(period.value, int)
            or period.value < 1
        ):
            _reject(
                "FUTURE_AMBIGUOUS_SHIFT",
                f"{class_name} has a negative or dynamic shift",
            )
        if period.value > MAX_STATIC_LOOKBACK:
            _reject(
                "LOOKBACK_RESOURCE_LIMIT",
                f"{class_name} shift lookback exceeds the global resource limit",
            )
    if name in {"max", "mean", "min"}:
        receiver = node.func.value
        if (
            node.args
            or node.keywords
            or not isinstance(receiver, ast.Call)
            or not isinstance(receiver.func, ast.Attribute)
            or receiver.func.attr != "rolling"
        ):
            _reject(
                "FULL_SAMPLE_AGGREGATE",
                f"{class_name} uses forbidden full-sample aggregate {name}()",
            )
    if name == "rolling" and (
        len(node.args) != 1
        or node.keywords
        or not isinstance(node.args[0], ast.Constant)
        or isinstance(node.args[0].value, bool)
        or not isinstance(node.args[0].value, int)
        or node.args[0].value < 2
    ):
        _reject("DYNAMIC_ROLLING", f"{class_name} uses centered/dynamic rolling")
    if (
        name == "rolling"
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, int)
        and not isinstance(node.args[0].value, bool)
        and node.args[0].value > MAX_STATIC_LOOKBACK
    ):
        _reject(
            "LOOKBACK_RESOURCE_LIMIT",
            f"{class_name} rolling lookback exceeds the global resource limit",
        )
    if call_name in {"ta.ADX", "ta.EMA", "ta.RSI"}:
        periods = [item for item in node.keywords if item.arg == "timeperiod"]
        if (
            len(node.args) != 1
            or not _is_name(node.args[0], "dataframe")
            or len(periods) != 1
            or len(node.keywords) != 1
            or not isinstance(periods[0].value, ast.Constant)
            or isinstance(periods[0].value.value, bool)
            or not isinstance(periods[0].value.value, int)
            or not 2 <= periods[0].value.value <= MAX_STATIC_LOOKBACK
        ):
            _reject(
                "LOOKBACK_OUTSIDE_TEMPLATE",
                f"{class_name} indicator lookback exceeds startup bounds",
            )


def _literal_kind(class_name: str, node: ast.Constant) -> str:
    value = node.value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if not _finite_number(value, maximum=_MAX_LITERAL_NUMBER):
            _reject(
                "EXPRESSION_OUTSIDE_TEMPLATE",
                f"{class_name} uses a numeric literal outside the bounded template",
            )
        return "number"
    _reject(
        "EXPRESSION_OUTSIDE_TEMPLATE",
        f"{class_name} uses a literal outside the bounded template",
    )


def _library_call_kind(
    class_name: str,
    node: ast.Call,
    call_name: str,
    bands_bound: bool,
) -> str:
    if call_name in {"ta.ADX", "ta.EMA", "ta.RSI"}:
        return "series"
    if call_name == "qtpylib.typical_price":
        if len(node.args) != 1 or not _is_name(node.args[0], "dataframe") or node.keywords:
            _reject(
                "LIBRARY_CALL_OUTSIDE_TEMPLATE",
                f"{class_name} uses qtpylib.typical_price outside the frozen template",
            )
        return "series"
    if call_name in {"qtpylib.crossed_above", "qtpylib.crossed_below"}:
        if len(node.args) != 2 or node.keywords:
            _reject(
                "LIBRARY_CALL_OUTSIDE_TEMPLATE",
                f"{class_name} uses {call_name} outside the frozen template",
            )
        left = _expression_kind(class_name, node.args[0], bands_bound)
        right = _expression_kind(class_name, node.args[1], bands_bound)
        if left != "series" or right not in {"series", "number"}:
            _reject(
                "LIBRARY_CALL_OUTSIDE_TEMPLATE",
                f"{class_name} uses {call_name} outside the frozen template",
            )
        return "mask"

    if len(node.args) != 1:
        _reject(
            "LIBRARY_CALL_OUTSIDE_TEMPLATE",
            f"{class_name} uses qtpylib.bollinger_bands outside the frozen template",
        )
    if _expression_kind(class_name, node.args[0], bands_bound) != "series":
        _reject(
            "LIBRARY_CALL_OUTSIDE_TEMPLATE",
            f"{class_name} uses qtpylib.bollinger_bands outside the frozen template",
        )
    names = [keyword_node.arg for keyword_node in node.keywords]
    if (
        None in names
        or len(names) != len(set(names))
        or set(names) != {"window", "stds"}
    ):
        _reject(
            "LIBRARY_CALL_OUTSIDE_TEMPLATE",
            f"{class_name} uses qtpylib.bollinger_bands outside the frozen template",
        )
    for keyword_node in node.keywords:
        value = keyword_node.value
        if keyword_node.arg == "window":
            valid = (
                isinstance(value, ast.Constant)
                and not isinstance(value.value, bool)
                and isinstance(value.value, int)
                and 2 <= value.value <= MAX_STATIC_LOOKBACK
            )
        else:
            valid = (
                isinstance(value, ast.Constant)
                and not isinstance(value.value, bool)
                and isinstance(value.value, (int, float))
                and _finite_number(value.value, maximum=5)
                and 0 < value.value <= 5
            )
        if not valid:
            _reject(
                "LIBRARY_CALL_OUTSIDE_TEMPLATE",
                f"{class_name} uses qtpylib.bollinger_bands outside the frozen template",
            )
    return "mapping"


def _dataframe_call_kind(
    class_name: str,
    node: ast.Call,
    bands_bound: bool,
) -> str:
    assert isinstance(node.func, ast.Attribute)
    name = node.func.attr
    receiver = _expression_kind(class_name, node.func.value, bands_bound)
    if name in {"rolling", "shift"} and receiver != "series":
        _reject(
            "EXPRESSION_OUTSIDE_TEMPLATE",
            f"{class_name} uses {name}() on a non-series expression",
        )
    if name == "rolling":
        return "rolling"
    if name == "shift":
        return "series"
    if name in {"max", "mean", "min"} and receiver == "rolling":
        return "series"
    _reject(
        "EXPRESSION_OUTSIDE_TEMPLATE",
        f"{class_name} uses {name}() outside the bounded expression template",
    )


def _expression_kind(class_name: str, node: ast.AST, bands_bound: bool) -> str:
    """Return a small semantic kind while recursively enforcing the allowlist."""

    if _session_clock(node):
        return "series"
    if isinstance(node, ast.Constant):
        return _literal_kind(class_name, node)
    if isinstance(node, ast.Subscript):
        if _subscript_column(node) is not None:
            return "series"
        if (
            bands_bound
            and _is_name(node.value, "bands")
            and _static_column(node.slice) is not None
        ):
            return "series"
        _reject(
            "EXPRESSION_OUTSIDE_TEMPLATE",
            f"{class_name} uses a subscript outside the bounded expression template",
        )
    if isinstance(node, ast.Call):
        _validate_call(class_name, node)
        call_name = _dotted_name(node.func)
        if call_name in ALLOWED_LIBRARY_CALLS:
            return _library_call_kind(class_name, node, call_name, bands_bound)
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr in ALLOWED_DATAFRAME_CALLS
        ):
            return _dataframe_call_kind(class_name, node, bands_bound)
        _reject(
            "EXPRESSION_OUTSIDE_TEMPLATE",
            f"{class_name} uses a call outside the bounded expression template",
        )
    if isinstance(node, ast.Compare):
        if (
            len(node.ops) != 1
            or len(node.comparators) != 1
            or not isinstance(node.ops[0], (ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE))
        ):
            _reject(
                "EXPRESSION_OUTSIDE_TEMPLATE",
                f"{class_name} uses a comparison outside the bounded template",
            )
        left = _expression_kind(class_name, node.left, bands_bound)
        right = _expression_kind(class_name, node.comparators[0], bands_bound)
        if (
            "series" not in {left, right}
            or left not in {"series", "number"}
            or right not in {"series", "number"}
        ):
            _reject(
                "EXPRESSION_OUTSIDE_TEMPLATE",
                f"{class_name} comparison operands are outside the bounded template",
            )
        return "mask"
    if isinstance(node, ast.BinOp):
        left = _expression_kind(class_name, node.left, bands_bound)
        right = _expression_kind(class_name, node.right, bands_bound)
        if isinstance(node.op, (ast.BitAnd, ast.BitOr)):
            if left not in {"series", "mask"} or right not in {"series", "mask"}:
                _reject(
                    "EXPRESSION_OUTSIDE_TEMPLATE",
                    f"{class_name} boolean operands are outside the bounded template",
                )
            return "mask"
        if not isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
            _reject(
                "EXPRESSION_OUTSIDE_TEMPLATE",
                f"{class_name} uses an operator outside the bounded template",
            )
        if left not in {"series", "number"} or right not in {
            "series",
            "number",
        } or "series" not in {left, right}:
            _reject(
                "EXPRESSION_OUTSIDE_TEMPLATE",
                f"{class_name} arithmetic operands are outside the bounded template",
            )
        return "series"
    if isinstance(node, ast.UnaryOp):
        operand = _expression_kind(class_name, node.operand, bands_bound)
        if isinstance(node.op, ast.Invert) and operand in {"series", "mask"}:
            return "mask"
        if isinstance(node.op, (ast.UAdd, ast.USub)) and operand in {
            "series",
            "number",
        }:
            return operand
        _reject(
            "EXPRESSION_OUTSIDE_TEMPLATE",
            f"{class_name} uses a unary operator outside the bounded template",
        )
    _reject(
        "EXPRESSION_OUTSIDE_TEMPLATE",
        f"{class_name} uses an expression outside the bounded template",
    )


def _keyword_integer(node: ast.Call, name: str) -> int:
    value = next(item.value for item in node.keywords if item.arg == name)
    assert isinstance(value, ast.Constant) and type(value.value) is int
    return value.value


def _expression_lookback(
    node: ast.AST,
    column_lookbacks: dict[str, int],
    bands_lookback: Optional[int],
) -> int:
    """Return candles required for an already-validated bounded expression."""

    if _session_clock(node):
        return 1
    if isinstance(node, ast.Constant):
        return 1
    if isinstance(node, ast.Name) and node.id == "dataframe":
        return 1
    if isinstance(node, ast.Subscript):
        column = _subscript_column(node)
        if column is not None:
            if column not in column_lookbacks:
                _reject(
                    "UNBOUND_DATAFRAME_COLUMN",
                    f"dataframe column {column} is read before a bounded binding",
                )
            return column_lookbacks[column]
        if _is_name(node.value, "bands") and _static_column(node.slice) is not None:
            assert bands_lookback is not None
            return bands_lookback
    if isinstance(node, ast.Call):
        call_name = _dotted_name(node.func)
        if call_name in {"ta.ADX", "ta.EMA", "ta.RSI"}:
            period = _keyword_integer(node, "timeperiod")
            return 2 * period if call_name == "ta.ADX" else period
        if call_name == "qtpylib.typical_price":
            return 1
        if call_name in {"qtpylib.crossed_above", "qtpylib.crossed_below"}:
            return max(
                _expression_lookback(value, column_lookbacks, bands_lookback)
                for value in node.args
            )
        if call_name == "qtpylib.bollinger_bands":
            upstream = _expression_lookback(
                node.args[0], column_lookbacks, bands_lookback
            )
            return upstream + _keyword_integer(node, "window") - 1
        assert isinstance(node.func, ast.Attribute)
        receiver = _expression_lookback(
            node.func.value, column_lookbacks, bands_lookback
        )
        if node.func.attr == "rolling":
            period = node.args[0]
            assert isinstance(period, ast.Constant) and type(period.value) is int
            return receiver + period.value - 1
        if node.func.attr == "shift":
            if node.args:
                period = node.args[0]
            else:
                periods = [item.value for item in node.keywords if item.arg == "periods"]
                period = periods[0] if periods else ast.Constant(1)
            assert isinstance(period, ast.Constant) and type(period.value) is int
            return receiver + period.value
        if node.func.attr in {"max", "mean", "min"}:
            return receiver
    if isinstance(node, ast.Compare):
        return max(
            _expression_lookback(node.left, column_lookbacks, bands_lookback),
            *(
                _expression_lookback(value, column_lookbacks, bands_lookback)
                for value in node.comparators
            ),
        )
    if isinstance(node, ast.BinOp):
        return max(
            _expression_lookback(node.left, column_lookbacks, bands_lookback),
            _expression_lookback(node.right, column_lookbacks, bands_lookback),
        )
    if isinstance(node, ast.UnaryOp):
        return _expression_lookback(node.operand, column_lookbacks, bands_lookback)
    raise AssertionError("validated bounded expression has no lookback rule")


def _validate_method_nodes(
    class_name: str, method: ast.FunctionDef, statement: ast.stmt, bands_bound: bool
) -> None:
    for node in ast.walk(statement):
        if isinstance(node, _FORBIDDEN_METHOD_NODES):
            _reject(
                "METHOD_SYNTAX_OUTSIDE_TEMPLATE",
                f"{class_name}.{method.name} uses code outside the frozen template",
            )
        if isinstance(node, ast.Call):
            _validate_call(class_name, node)
        elif isinstance(node, ast.Subscript):
            valid = (
                _subscript_column(node) is not None
                or (_is_name(node.value, "bands") and _static_column(node.slice) is not None)
                or _loc_parts(node) is not None
            )
            if not valid:
                _reject(
                    "DYNAMIC_INDEXING",
                    f"{class_name} uses future-ambiguous positional indexing",
                )
        elif isinstance(node, ast.Attribute) and (
            node.attr.startswith("_") or node.attr in {"iloc", "iat", "at"}
        ):
            _reject(
                "DYNAMIC_INDEXING",
                f"{class_name} uses future-ambiguous positional indexing",
            )
        elif isinstance(node, ast.Name):
            if isinstance(node.ctx, (ast.Store, ast.Del)) and node.id != "bands":
                _reject(
                    "DYNAMIC_METHOD_BINDING",
                    f"{class_name}.{method.name} has a dynamic binding",
                )
            if isinstance(node.ctx, ast.Load) and node.id not in {
                "self",
                "dataframe",
                "metadata",
                "bands",
                "ta",
                "qtpylib",
            }:
                _reject(
                    "DYNAMIC_METHOD_BINDING",
                    f"{class_name}.{method.name} loads name {node.id} outside the frozen template",
                )
            if isinstance(node.ctx, ast.Load) and node.id == "bands" and not bands_bound:
                _reject(
                    "DYNAMIC_METHOD_BINDING",
                    f"{class_name}.{method.name} uses bands without one fixed binding",
                )


def _validate_method(
    class_name: str,
    method: ast.FunctionDef,
    assigned_columns: set[str],
    column_lookbacks: dict[str, int],
) -> int:
    _validate_signature(class_name, method)
    if len(method.body) > MAX_METHOD_STATEMENTS:
        _reject(
            "METHOD_STATEMENT_LIMIT",
            f"{class_name}.{method.name} exceeds the frozen statement limit",
        )
    if not method.body or not isinstance(method.body[-1], ast.Return):
        _reject(
            "METHOD_BODY_MISMATCH",
            f"{class_name}.{method.name} must end with return dataframe",
        )
    bands_bound = False
    bands_lookback: Optional[int] = None
    method_lookback = 1
    for index, statement in enumerate(method.body):
        if isinstance(statement, ast.Return):
            if index != len(method.body) - 1 or not _is_name(statement.value, "dataframe"):
                _reject(
                    "METHOD_BODY_MISMATCH",
                    f"{class_name}.{method.name} must end with return dataframe",
                )
            _validate_method_nodes(class_name, method, statement, bands_bound)
            continue
        if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call):
            _validate_call(class_name, statement.value)
        if (
            not isinstance(statement, ast.Assign)
            or statement.type_comment is not None
            or len(statement.targets) != 1
        ):
            _reject(
                "METHOD_BODY_MISMATCH",
                f"{class_name}.{method.name} contains a statement outside the frozen template",
            )
        target = statement.targets[0]
        assigned_column: Optional[str] = None
        loc: Optional[tuple[ast.AST, str]] = None
        binds_bands = isinstance(target, ast.Name) and target.id == "bands"
        if binds_bands:
            if (
                method.name != "populate_indicators"
                or bands_bound
                or not isinstance(statement.value, ast.Call)
                or _dotted_name(statement.value.func) != "qtpylib.bollinger_bands"
            ):
                _reject(
                    "DYNAMIC_METHOD_BINDING",
                    f"{class_name}.{method.name} has a dynamic or repeated binding",
                )
        elif not isinstance(target, ast.Subscript):
            _reject(
                "DYNAMIC_METHOD_BINDING",
                f"{class_name}.{method.name} may only assign fixed dataframe columns",
            )
        else:
            column = _subscript_column(target)
            if column is None:
                loc = _loc_parts(target)
                column = None if loc is None else loc[1]
            if column is None:
                _reject(
                    "DYNAMIC_DATAFRAME_ASSIGNMENT",
                    f"{class_name}.{method.name} may only assign fixed dataframe columns or loc targets",
                )
            if column in _SOURCE_COLUMNS:
                _reject(
                    "SOURCE_COLUMN_ASSIGNMENT",
                    f"{class_name} may not overwrite source OHLCV column {column}",
                )
            if method.name == "populate_indicators" and loc is not None:
                _reject(
                    "DYNAMIC_DATAFRAME_ASSIGNMENT",
                    f"{class_name}.populate_indicators may not assign signal loc targets",
                )
            if method.name != "populate_indicators" and loc is None:
                _reject(
                    "DYNAMIC_DATAFRAME_ASSIGNMENT",
                    f"{class_name}.{method.name} may only assign fixed signal loc targets",
                )
            allowed_signals = (
                _ENTRY_SIGNAL_COLUMNS
                if method.name == "populate_entry_trend"
                else _EXIT_SIGNAL_COLUMNS
            )
            if loc is not None and column not in allowed_signals:
                _reject(
                    "DYNAMIC_DATAFRAME_ASSIGNMENT",
                    f"{class_name}.{method.name} signal column is outside the frozen template",
                )
            if column in assigned_columns:
                _reject(
                    "REPEATED_DATAFRAME_ASSIGNMENT",
                    f"{class_name} dataframe column {column} is assigned more than once",
                )
            if len(assigned_columns) >= MAX_ASSIGNED_COLUMNS:
                _reject(
                    "ASSIGNED_COLUMN_LIMIT",
                    f"{class_name} exceeds the frozen assigned-column limit",
                )
            assigned_columns.add(column)
            assigned_column = column
        _validate_method_nodes(class_name, method, statement, bands_bound)
        expression_kind = _expression_kind(
            class_name, statement.value, bands_bound
        )
        expression_lookback = _expression_lookback(
            statement.value, column_lookbacks, bands_lookback
        )
        method_lookback = max(method_lookback, expression_lookback)
        if binds_bands and expression_kind != "mapping":
            _reject(
                "EXPRESSION_OUTSIDE_TEMPLATE",
                f"{class_name}.{method.name} bands must bind one fixed mapping call",
            )
        if not binds_bands and isinstance(target, ast.Subscript):
            if loc is not None:
                mask_kind = _expression_kind(class_name, loc[0], bands_bound)
                mask_lookback = _expression_lookback(
                    loc[0], column_lookbacks, bands_lookback
                )
                method_lookback = max(
                    method_lookback,
                    mask_lookback,
                )
                if mask_kind != "mask":
                    _reject(
                        "EXPRESSION_OUTSIDE_TEMPLATE",
                        f"{class_name}.{method.name} loc mask is outside the template",
                    )
                if not (
                    isinstance(statement.value, ast.Constant)
                    and type(statement.value.value) is int
                    and statement.value.value == 1
                ):
                    _reject(
                        "EXPRESSION_OUTSIDE_TEMPLATE",
                        f"{class_name}.{method.name} signal assignment must be literal 1",
                    )
                assert assigned_column is not None
                column_lookbacks[assigned_column] = mask_lookback
            elif expression_kind != "series":
                _reject(
                    "EXPRESSION_OUTSIDE_TEMPLATE",
                    f"{class_name}.populate_indicators RHS must be one bounded series",
                )
        if binds_bands:
            bands_bound = True
            bands_lookback = expression_lookback
        elif assigned_column is not None and loc is None:
            column_lookbacks[assigned_column] = expression_lookback
    return method_lookback


def _validate_bounded_causal_strategy(
    source: str,
    class_name: str,
    expected_timeframe: str,
) -> BoundedStrategyAnalysis:
    """Validate one source string against ``BOUNDED_CAUSAL_STRATEGY_V1``."""

    if (
        not isinstance(class_name, str)
        or _CLASS_NAME.fullmatch(class_name) is None
        or keyword.iskeyword(class_name)
    ):
        _reject("INVALID_CLASS_NAME", "class_name must be a simple Python identifier")
    if expected_timeframe not in _SUPPORTED_TIMEFRAMES:
        _reject(
            "UNSUPPORTED_TIMEFRAME",
            "expected_timeframe must be one supported Profile timeframe",
        )
    if not isinstance(source, str) or not source or "\x00" in source:
        _reject("INVALID_SOURCE", f"{class_name} source must be non-empty UTF-8 text")
    try:
        encoded = source.encode("utf-8", "strict")
    except UnicodeEncodeError as exc:
        raise BoundedStrategyError(
            "INVALID_SOURCE", f"{class_name} source must be UTF-8"
        ) from exc
    if len(encoded) > MAX_SOURCE_BYTES:
        _reject("INVALID_SOURCE", f"{class_name} source exceeds the fixed byte limit")
    try:
        tree = ast.parse(source, filename="<bounded-candidate>", mode="exec")
    except (SyntaxError, ValueError, RecursionError) as exc:
        raise BoundedStrategyError(
            "INVALID_PYTHON", f"{class_name} is not valid Python: {exc}"
        ) from exc
    _validate_ast_budget(class_name, tree)
    expected = [ast.parse(value).body[0] for value in EXPECTED_IMPORTS]
    if (
        len(tree.body) != len(expected) + 1
        or [ast.dump(node) for node in tree.body[: len(expected)]]
        != [ast.dump(node) for node in expected]
    ):
        _reject(
            "MODULE_OUTSIDE_TEMPLATE",
            f"{class_name} imports or module statements are outside the frozen template",
        )
    strategy_class = tree.body[-1]
    if not isinstance(strategy_class, ast.ClassDef) or strategy_class.name != class_name:
        _reject(
            "CLASS_OUTSIDE_TEMPLATE",
            f"{class_name} must be declared exactly once and be the only class",
        )
    if (
        strategy_class.decorator_list
        or strategy_class.keywords
        or len(strategy_class.bases) != 1
        or not _is_name(strategy_class.bases[0], "IStrategy")
        or getattr(strategy_class, "type_params", ())
    ):
        _reject(
            "CLASS_OUTSIDE_TEMPLATE",
            f"{class_name} must directly extend only IStrategy without decorators or metaclass",
        )
    assignments = [node for node in strategy_class.body if isinstance(node, ast.Assign)]
    methods = [node for node in strategy_class.body if isinstance(node, ast.FunctionDef)]
    if any(not isinstance(node, (ast.Assign, ast.FunctionDef)) for node in strategy_class.body):
        _reject(
            "CLASS_OUTSIDE_TEMPLATE",
            f"{class_name} class body is outside the frozen template",
        )
    values = _validate_fields(class_name, assignments, expected_timeframe)
    if len(methods) != 3 or {method.name for method in methods} != ALLOWED_STRATEGY_METHODS:
        _reject(
            "STRATEGY_METHODS_MISMATCH",
            f"{class_name} must implement exactly the three populate methods",
        )
    assigned_columns: set[str] = set()
    column_lookbacks = {column: 1 for column in _SOURCE_COLUMNS}
    methods_by_name = {method.name: method for method in methods}
    max_lookback = 1
    for method_name in (
        "populate_indicators",
        "populate_entry_trend",
        "populate_exit_trend",
    ):
        max_lookback = max(
            max_lookback,
            _validate_method(
                class_name,
                methods_by_name[method_name],
                assigned_columns,
                column_lookbacks,
            ),
        )
    if values["can_short"] is False and assigned_columns & {
        "enter_short",
        "exit_short",
    }:
        _reject(
            "SHORT_SIGNAL_DISABLED",
            f"{class_name} assigns short signals while can_short is false",
        )
    if max_lookback > MAX_STATIC_LOOKBACK:
        _reject(
            "LOOKBACK_RESOURCE_LIMIT",
            f"{class_name} derived lookback exceeds the global resource limit",
        )
    startup_candle_count = int(values["startup_candle_count"])
    if startup_candle_count < max_lookback:
        _reject(
            "INSUFFICIENT_STARTUP_CANDLES",
            f"{class_name}.startup_candle_count is below the derived maximum lookback",
        )
    return BoundedStrategyAnalysis(
        timeframe=expected_timeframe,
        startup_candle_count=startup_candle_count,
        max_lookback=max_lookback,
    )


def analyze_bounded_causal_strategy(
    source: str,
    class_name: str,
    *,
    expected_timeframe: str = "5m",
) -> BoundedStrategyAnalysis:
    """Analyze one bounded source without importing or executing it."""

    try:
        return _validate_bounded_causal_strategy(
            source, class_name, expected_timeframe
        )
    except BoundedStrategyError:
        raise
    except RecursionError as exc:
        raise BoundedStrategyError(
            "SOURCE_COMPLEXITY_LIMIT",
            f"{class_name} source exceeds the frozen AST budget",
        ) from exc


def validate_bounded_causal_strategy(
    source: str,
    class_name: str,
    *,
    expected_timeframe: str = "5m",
) -> None:
    """Fail closed on both contract violations and recursion exhaustion."""

    analyze_bounded_causal_strategy(
        source, class_name, expected_timeframe=expected_timeframe
    )


def validate_bounded_causal_strategy_file(
    path: Union[str, Path],
    class_name: str,
    *,
    expected_timeframe: str = "5m",
) -> None:
    """Read one bounded UTF-8 file and validate it without importing it."""

    analyze_bounded_causal_strategy_file(
        path, class_name, expected_timeframe=expected_timeframe
    )


def analyze_bounded_causal_strategy_file(
    path: Union[str, Path],
    class_name: str,
    *,
    expected_timeframe: str = "5m",
) -> BoundedStrategyAnalysis:
    """Read and analyze one bounded UTF-8 file without importing it."""

    candidate = Path(path)
    try:
        if candidate.is_symlink() or not candidate.is_file():
            _reject("INVALID_SOURCE", f"{class_name} source must be a regular file")
        raw = candidate.read_bytes()
        if len(raw) > MAX_SOURCE_BYTES:
            _reject("INVALID_SOURCE", f"{class_name} source exceeds the fixed byte limit")
        source = raw.decode("utf-8", "strict")
    except BoundedStrategyError:
        raise
    except (OSError, UnicodeDecodeError) as exc:
        raise BoundedStrategyError(
            "INVALID_SOURCE", f"{class_name} source cannot be read as UTF-8"
        ) from exc
    return analyze_bounded_causal_strategy(
        source, class_name, expected_timeframe=expected_timeframe
    )


__all__ = [
    "BOUNDED_CAUSAL_STRATEGY_V1",
    "MAX_STATIC_LOOKBACK",
    "BoundedStrategyAnalysis",
    "BoundedStrategyError",
    "analyze_bounded_causal_strategy",
    "analyze_bounded_causal_strategy_file",
    "validate_bounded_causal_strategy",
    "validate_bounded_causal_strategy_file",
]
