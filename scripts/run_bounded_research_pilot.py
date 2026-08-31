#!/usr/bin/env python3
"""Run one frozen, one-shot bounded research Pilot.

Candidate files and the selection rule are frozen before this command. The
command screens at most three Candidates on Development, seals Holdout before
one existing producer invocation, and never retries an opened Holdout.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import math
import os
import re
import shlex
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lab.database import init_database
from lab.research_candidate import (
    DEFAULT_RUNNER,
    DEFAULT_SANDBOX_EXEC,
    ResearchCandidateError,
    _prepare_freqtrade_source_snapshot,
    _run_scenario,
    _runtime_config,
    run_research_candidate,
)
from lab.strategy_library import (
    DEFAULT_PORT,
    StrategyLibraryError,
    validate_strategy_library_database,
)
from scripts.run_freqtrade_backtest import _create_scenario_data_view


SCHEMA = "freqtrade-lab-bounded-pilot-v1"
PLAN = "pilot-spec.json"
WINDOW = "window-spec.json"
ACQUISITION = "acquisition"
SELECTION = "development-selection.json"
HOLDOUT_AUTHORIZATION = "holdout-authorized.json"
HOLDOUT_SEAL = "scenario-opens/HOLDOUT.json"
STRESS_SEAL = "scenario-opens/HOLDOUT_STRESS.json"
TERMINAL = "pilot-terminal.json"
RANKING = (
    "profit_pct_desc",
    "max_drawdown_pct_asc",
    "profit_factor_desc",
    "candidate_id_asc",
)
TECHNICAL_ECONOMIC_GATE = "NONE_TECHNICAL_PILOT"
POSITIVE_ECONOMIC_GATE = "POSITIVE_DEVELOPMENT_V1"
POSITIVE_GATE_THRESHOLDS = (
    "minimum_profit_pct",
    "minimum_profit_factor",
    "maximum_drawdown_pct",
)
SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
CLASS = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
LOOPBACK_URL = re.compile(r"^http://127\.0\.0\.1:([1-9][0-9]{0,4})$")
RUNNER_SHA = hashlib.sha256(DEFAULT_RUNNER.read_bytes()).hexdigest()

EXPECTED_IMPORTS = (
    "import talib.abstract as ta",
    "from pandas import DataFrame",
    "from technical import qtpylib",
    "from freqtrade.strategy import IStrategy",
)
ALLOWED_STRATEGY_FIELDS = {
    "INTERFACE_VERSION",
    "timeframe",
    "can_short",
    "startup_candle_count",
    "process_only_new_candles",
    "minimal_roi",
    "stoploss",
}
ALLOWED_STRATEGY_METHODS = {
    "populate_indicators",
    "populate_entry_trend",
    "populate_exit_trend",
}
ALLOWED_LIBRARY_CALLS = {
    "ta.ADX",
    "ta.EMA",
    "ta.RSI",
    "qtpylib.bollinger_bands",
    "qtpylib.crossed_above",
    "qtpylib.crossed_below",
    "qtpylib.typical_price",
}
ALLOWED_DATAFRAME_CALLS = {"max", "min", "rolling", "shift"}


class PilotError(ValueError):
    """A terminal, fail-closed Pilot error."""


class PresentationUnavailableError(PilotError):
    """The isolated optional presentation target cannot be published."""


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode()


def load_json(path: Path, label: str) -> tuple[dict[str, Any], bytes]:
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 64 * 1024 * 1024:
            raise PilotError(f"{label} must be a bounded regular file")
        data = path.read_bytes()
        value = json.loads(data)
    except PilotError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PilotError(f"{label} cannot be read: {exc}") from exc
    if not isinstance(value, dict):
        raise PilotError(f"{label} must be a JSON object")
    return value, data


def finite(value: Any, label: str, minimum: Optional[float] = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PilotError(f"{label} must be a finite number")
    number = float(value)
    if not math.isfinite(number) or (minimum is not None and number < minimum):
        raise PilotError(f"{label} must be a finite number")
    return number


def timerange(value: Any, label: str) -> tuple[datetime, datetime]:
    if not isinstance(value, str) or re.fullmatch(r"\d{8}-\d{8}", value) is None:
        raise PilotError(f"{label} must use YYYYMMDD-YYYYMMDD")
    try:
        start = datetime.strptime(value[:8], "%Y%m%d").replace(tzinfo=timezone.utc)
        end = datetime.strptime(value[9:], "%Y%m%d").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise PilotError(f"{label} has an invalid date") from exc
    if end <= start:
        raise PilotError(f"{label} must have positive duration")
    return start, end


def safe_file(root: Path, value: Any, label: str) -> Path:
    if not isinstance(value, str) or not value or "\\" in value or ".." in Path(value).parts:
        raise PilotError(f"{label} must be a safe relative path")
    path = Path(value)
    if path.is_absolute():
        raise PilotError(f"{label} must be a safe relative path")
    try:
        resolved = (root / path).resolve(strict=True)
        resolved.relative_to(root.resolve(strict=True))
    except (OSError, RuntimeError, ValueError) as exc:
        raise PilotError(f"{label} escapes the Pilot root") from exc
    if resolved.is_symlink() or not resolved.is_file():
        raise PilotError(f"{label} must be a regular file")
    return resolved


def _dotted_name(node: ast.AST) -> Optional[str]:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _dotted_name(node.value)
        return None if parent is None else f"{parent}.{node.attr}"
    return None


def _literal_assignment(node: ast.Assign, label: str) -> Any:
    try:
        return ast.literal_eval(node.value)
    except (ValueError, TypeError) as exc:
        raise PilotError(f"{label} must be a literal") from exc


def causal_source(path: Path, class_name: str) -> None:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, SyntaxError) as exc:
        raise PilotError(f"{class_name} is not valid Python: {exc}") from exc
    imports = [node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]
    expected_imports = [ast.parse(value).body[0] for value in EXPECTED_IMPORTS]
    if [ast.dump(node) for node in imports] != [ast.dump(node) for node in expected_imports]:
        raise PilotError(f"{class_name} imports are outside the frozen template")
    if any(not isinstance(node, (ast.Import, ast.ImportFrom, ast.ClassDef)) for node in tree.body):
        raise PilotError(f"{class_name} has executable top-level code")
    classes = [node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name]
    if len(classes) != 1:
        raise PilotError(f"{class_name} must be declared exactly once")
    strategy_class = classes[0]
    if (
        strategy_class.decorator_list
        or strategy_class.keywords
        or [_dotted_name(base) for base in strategy_class.bases] != ["IStrategy"]
    ):
        raise PilotError(f"{class_name} must directly extend only IStrategy")
    assignments = [node for node in strategy_class.body if isinstance(node, ast.Assign)]
    methods = [node for node in strategy_class.body if isinstance(node, ast.FunctionDef)]
    if any(not isinstance(node, (ast.Assign, ast.FunctionDef)) for node in strategy_class.body):
        raise PilotError(f"{class_name} class body is outside the frozen template")
    assigned_names: dict[str, Any] = {}
    for node in assignments:
        if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
            raise PilotError(f"{class_name} has a dynamic class assignment")
        field = node.targets[0].id
        if field not in ALLOWED_STRATEGY_FIELDS or field in assigned_names:
            raise PilotError(f"{class_name} class field {field} is not allowed")
        assigned_names[field] = _literal_assignment(node, f"{class_name}.{field}")
    if set(assigned_names) != ALLOWED_STRATEGY_FIELDS:
        raise PilotError(f"{class_name} must freeze the exact strategy fields")
    if (
        assigned_names["INTERFACE_VERSION"] != 3
        or assigned_names["timeframe"] != "5m"
        or assigned_names["can_short"] is not True
        or assigned_names["startup_candle_count"] != 20
        or assigned_names["process_only_new_candles"] is not True
        or not isinstance(assigned_names["minimal_roi"], dict)
        or not isinstance(assigned_names["stoploss"], (int, float))
        or not -1 < float(assigned_names["stoploss"]) < 0
    ):
        raise PilotError(f"{class_name} strategy fields violate the fixed 5m template")
    if {method.name for method in methods} != ALLOWED_STRATEGY_METHODS or len(methods) != 3:
        raise PilotError(f"{class_name} must implement exactly the three populate methods")
    for method in methods:
        arguments = method.args
        if (
            method.decorator_list
            or arguments.posonlyargs
            or arguments.kwonlyargs
            or arguments.vararg is not None
            or arguments.kwarg is not None
            or [argument.arg for argument in arguments.args] != ["self", "dataframe", "metadata"]
        ):
            raise PilotError(f"{class_name}.{method.name} signature is not allowed")
    startup = [
        node.value.value
        for node in classes[0].body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "startup_candle_count" for target in node.targets)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, int)
    ]
    if startup != [20]:
        raise PilotError(f"{class_name} must freeze startup_candle_count = 20")
    for node in ast.walk(tree):
        if isinstance(
            node,
            (
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
            ),
        ) and node not in {*classes, *imports, *methods}:
            raise PilotError(f"{class_name} uses code outside the frozen template")
        if isinstance(node, ast.Attribute) and node.attr in {"iloc", "iat"}:
            raise PilotError(f"{class_name} uses future-ambiguous positional indexing")
        if isinstance(node, ast.Attribute) and node.attr.startswith("_"):
            raise PilotError(f"{class_name} uses a private attribute")
        if isinstance(node, ast.Subscript):
            if isinstance(node.value, ast.Attribute) and node.value.attr == "loc":
                valid_slice = (
                    isinstance(node.slice, ast.Tuple)
                    and len(node.slice.elts) == 2
                    and isinstance(node.slice.elts[1], ast.Constant)
                    and isinstance(node.slice.elts[1].value, str)
                )
            else:
                valid_slice = (
                    isinstance(node.value, ast.Name)
                    and node.value.id in {"dataframe", "bands"}
                    and isinstance(node.slice, ast.Constant)
                    and isinstance(node.slice.value, str)
                )
            if not valid_slice:
                raise PilotError(f"{class_name} uses future-ambiguous positional indexing")
        if not isinstance(node, ast.Call):
            continue
        call_name = _dotted_name(node.func)
        name = node.func.attr if isinstance(node.func, ast.Attribute) else None
        dataframe_call = (
            name in ALLOWED_DATAFRAME_CALLS
            and isinstance(node.func, ast.Attribute)
            and any(isinstance(value, ast.Name) and value.id == "dataframe" for value in ast.walk(node.func.value))
        )
        if call_name not in ALLOWED_LIBRARY_CALLS and not dataframe_call:
            raise PilotError(f"{class_name} uses forbidden call {call_name or name or 'dynamic'}()")
        if name == "shift":
            period = node.args[0] if node.args else ast.Constant(1)
            for keyword in node.keywords:
                if keyword.arg == "periods":
                    period = keyword.value
            if not isinstance(period, ast.Constant) or not isinstance(period.value, int) or period.value < 1:
                raise PilotError(f"{class_name} has a negative or dynamic shift")
        if name in {"max", "min"}:
            receiver = node.func.value
            if (
                node.args
                or node.keywords
                or not isinstance(receiver, ast.Call)
                or not isinstance(receiver.func, ast.Attribute)
                or receiver.func.attr != "rolling"
            ):
                raise PilotError(f"{class_name} uses forbidden full-sample aggregate {name}()")
        if name == "rolling":
            if (
                len(node.args) != 1
                or node.keywords
                or not isinstance(node.args[0], ast.Constant)
                or isinstance(node.args[0].value, bool)
                or not isinstance(node.args[0].value, int)
                or not 2 <= node.args[0].value <= 100
            ):
                raise PilotError(f"{class_name} uses centered/dynamic rolling")
        if call_name in {"ta.ADX", "ta.EMA", "ta.RSI"}:
            period_keywords = [keyword for keyword in node.keywords if keyword.arg == "timeperiod"]
            maximum = 10 if call_name == "ta.ADX" else 20
            if (
                len(node.args) != 1
                or not isinstance(node.args[0], ast.Name)
                or node.args[0].id != "dataframe"
                or len(period_keywords) != 1
                or len(node.keywords) != 1
                or not isinstance(period_keywords[0].value, ast.Constant)
                or isinstance(period_keywords[0].value.value, bool)
                or not isinstance(period_keywords[0].value.value, int)
                or not 2 <= period_keywords[0].value.value <= maximum
            ):
                raise PilotError(f"{class_name} indicator lookback exceeds startup bounds")


def load_plan(root: Path) -> dict[str, Any]:
    plan, plan_bytes = load_json(root / PLAN, "pilot spec")
    required = {
        "schema",
        "pilot_id",
        "freqtrade_version",
        "window_spec_sha256",
        "development_timerange",
        "holdout_timerange",
        "stress_fee_multiplier",
        "selection",
        "holdout_policy",
        "candidates",
    }
    if set(plan) != required or plan["schema"] != SCHEMA or plan["freqtrade_version"] != "2026.7":
        raise PilotError("pilot spec shape/version is not supported")
    if not isinstance(plan["pilot_id"], str) or SAFE_ID.fullmatch(plan["pilot_id"]) is None:
        raise PilotError("pilot_id is unsafe")
    if plan["window_spec_sha256"] != digest((root / WINDOW).read_bytes()):
        raise PilotError("window spec hash mismatch")
    dev_start, dev_end = timerange(plan["development_timerange"], "Development")
    hold_start, hold_end = timerange(plan["holdout_timerange"], "Holdout")
    if dev_end != hold_start or not 60 <= (hold_end - dev_start).days <= 90:
        raise PilotError("Development/Holdout must be contiguous and span 60 to 90 days")
    multiplier = finite(plan["stress_fee_multiplier"], "stress multiplier", 1.0)
    if multiplier <= 1:
        raise PilotError("stress multiplier must exceed 1")
    selection = plan["selection"]
    selection_keys = {
        "minimum_trades",
        "ranking",
        "economic_gate",
        "max_selected",
        "no_eligible",
        "missing_metric_policy",
        "visibility",
        "candidate_execution_failure",
    }
    if not isinstance(selection, dict):
        raise PilotError("selection rule shape is invalid")
    gate = selection.get("economic_gate")
    if gate == TECHNICAL_ECONOMIC_GATE:
        expected_selection_keys = selection_keys
    elif gate == POSITIVE_ECONOMIC_GATE:
        expected_selection_keys = selection_keys | set(POSITIVE_GATE_THRESHOLDS)
    else:
        raise PilotError("selection rule shape is invalid")
    if set(selection) != expected_selection_keys:
        raise PilotError("selection rule shape is invalid")
    if (
        isinstance(selection["minimum_trades"], bool)
        or not isinstance(selection["minimum_trades"], int)
        or selection["minimum_trades"] < 1
        or tuple(selection["ranking"]) != RANKING
        or selection["max_selected"] != 1
        or selection["no_eligible"] != "STOP"
        or selection["missing_metric_policy"] != "STOP"
        or selection["visibility"] != "DEVELOPMENT_ONLY_BLIND"
        or selection["candidate_execution_failure"] != "STOP"
    ):
        raise PilotError("selection rule is not the fixed technical Pilot rule")
    if gate == POSITIVE_ECONOMIC_GATE:
        finite(selection["minimum_profit_pct"], "minimum_profit_pct", 0)
        finite(selection["minimum_profit_factor"], "minimum_profit_factor", 1)
        maximum_drawdown = finite(
            selection["maximum_drawdown_pct"], "maximum_drawdown_pct", 0
        )
        if maximum_drawdown > 100:
            raise PilotError("maximum_drawdown_pct must not exceed 100")
    if plan["holdout_policy"] != {
        "max_open_count": 1,
        "retry_after_open": False,
        "tune_after_result": False,
    }:
        raise PilotError("Holdout must be one-shot and no-tuning")
    candidates = plan["candidates"]
    if not isinstance(candidates, list) or not 1 <= len(candidates) <= 3:
        raise PilotError("pilot spec must contain one to three Candidates")
    ids, classes = set(), set()
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, dict) or set(candidate) != {
            "candidate_id",
            "class_name",
            "strategy_file",
            "research_spec_file",
            "strategy_sha256",
            "research_spec_sha256",
        }:
            raise PilotError(f"candidate {index} shape is invalid")
        candidate_id, class_name = candidate["candidate_id"], candidate["class_name"]
        if (
            not isinstance(candidate_id, str)
            or SAFE_ID.fullmatch(candidate_id) is None
            or candidate_id in ids
            or not isinstance(class_name, str)
            or CLASS.fullmatch(class_name) is None
            or class_name in classes
        ):
            raise PilotError(f"candidate {index} identity is invalid")
        ids.add(candidate_id)
        classes.add(class_name)
        strategy = safe_file(root, candidate["strategy_file"], "strategy_file")
        spec = safe_file(root, candidate["research_spec_file"], "research_spec_file")
        if candidate["strategy_sha256"] != digest(strategy.read_bytes()) or candidate[
            "research_spec_sha256"
        ] != digest(spec.read_bytes()):
            raise PilotError(f"candidate {index} frozen hash mismatch")
        causal_source(strategy, class_name)
        spec_value, _ = load_json(spec, "Candidate research spec")
        metadata = spec_value.get("candidate", {}).get("metadata", {})
        if (
            spec_value.get("candidate", {}).get("class_name") != class_name
            or metadata.get("pilot_id") != plan["pilot_id"]
            or metadata.get("economic_evidence") != "NOT_EVALUATED"
            or metadata.get("generation")
            != {
                "source": "CODEX",
                "model": None,
                "returned_strategy_count": len(candidates),
                "source_item_index": index,
            }
            or spec_value.get("profile", {}).get("history_start_date")
            != dev_start.strftime("%Y-%m-%d")
            or spec_value.get("profile", {}).get("holdout_days") != (hold_end - hold_start).days
            or spec_value.get("profile", {}).get("stress_fee_multiplier") != multiplier
        ):
            raise PilotError(f"candidate {index} research spec disagrees with the Pilot")
        candidate["_strategy"] = strategy
        candidate["_spec"] = spec
    plan["_sha256"] = digest(plan_bytes)
    return plan


def verify_data(root: Path, plan: Mapping[str, Any]) -> dict[str, Any]:
    data_root = root / ACQUISITION
    provenance, provenance_bytes = load_json(
        data_root / "retained-data-provenance.json", "data provenance"
    )
    source = provenance.get("source", {})
    ft = provenance.get("freqtrade", {})
    contract = provenance.get("contract", {})
    if (
        provenance.get("schema") != "freqtrade-lab-retained-okx-data-v1"
        or source.get("host") != "www.okx.com"
        or source.get("authentication") != "none"
        or ft.get("version") != "2026.7"
        or ft.get("commit") != "52bc96f4480b1a0da6a9b455bd00b17fbb6786a5"
        or contract.get("timeframe") != "5m"
        or contract.get("development_timerange") != plan["development_timerange"]
        or contract.get("holdout_timerange") != plan["holdout_timerange"]
    ):
        raise PilotError("data provenance disagrees with the public fixed Pilot contract")
    local = provenance.get("local_only_files")
    if not isinstance(local, dict) or not local:
        raise PilotError("data provenance has no local files")
    for name, receipt in local.items():
        path = safe_file(data_root, name, "local data file")
        data = path.read_bytes()
        if not isinstance(receipt, dict) or receipt.get("bytes") != len(data) or receipt.get("sha256") != digest(data):
            raise PilotError(f"local data receipt mismatch: {name}")
    receipt_name = source.get("retrieval_receipt")
    receipt, receipt_bytes = load_json(
        safe_file(data_root, receipt_name, "retrieval receipt"), "retrieval receipt"
    )
    rows = {
        name: receipt.get("series", {}).get(name, {}).get("rows")
        for name in ("futures_5m", "mark_1h", "funding_history")
    }
    if any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in rows.values()):
        raise PilotError("retrieval receipt has an empty series")
    return {
        "status": "DATA_READY",
        "source": {"host": source["host"], "authentication": "none", "pair": source.get("pair")},
        "timeranges": [plan["development_timerange"], plan["holdout_timerange"]],
        "rows": rows,
        "retrieval_receipt_sha256": digest(receipt_bytes),
        "provenance_sha256": digest(provenance_bytes),
        "local_files": len(local),
    }


def materialize_development_isolation(
    root: Path, plan: Mapping[str, Any]
) -> dict[str, Any]:
    """Create a physical data view containing no candle at/after Holdout start."""
    isolation_root = root / "development-isolation"
    if isolation_root.exists():
        raise PilotError("Development isolation already exists; replay is forbidden")
    data_root = isolation_root / "data" / "okx"
    data_root.mkdir(parents=True)
    provenance, provenance_bytes = load_json(
        root / ACQUISITION / "retained-data-provenance.json", "data provenance"
    )
    contract = provenance.get("contract", {})
    prefix = contract.get("data_dir")
    local = provenance.get("local_only_files")
    if prefix != "data/okx" or not isinstance(local, dict):
        raise PilotError("data provenance cannot build a Development-only view")
    expected: dict[str, str] = {}
    for name, receipt in local.items():
        marker = f"{prefix}/"
        if isinstance(name, str) and name.startswith(marker):
            relative = name.removeprefix(marker)
            if not isinstance(receipt, dict) or not isinstance(receipt.get("sha256"), str):
                raise PilotError("Development source receipt is invalid")
            expected[relative] = receipt["sha256"]
    if not expected:
        raise PilotError("Development source receipt has no market data")
    view = _create_scenario_data_view(
        root / ACQUISITION / "data" / "okx",
        data_root,
        plan["development_timerange"],
        expected,
    )
    updated_local = dict(local)
    for relative, receipt in view["files"].items():
        path = data_root / relative
        data = path.read_bytes()
        if receipt.get("sha256") != digest(data):
            raise PilotError("Development isolation receipt disagrees with its file")
        updated_local[f"{prefix}/{relative}"] = {
            "bytes": len(data),
            "sha256": receipt["sha256"],
        }
    provenance["local_only_files"] = updated_local
    provenance["files"] = {}
    provenance["portable_retained_fixture"] = False
    for path in data_root.rglob("*"):
        if path.is_file():
            path.chmod(0o444)
    for path in sorted(
        (item for item in data_root.rglob("*") if item.is_dir()),
        key=lambda item: len(item.parts),
        reverse=True,
    ):
        path.chmod(0o555)
    data_root.chmod(0o555)
    provenance["development_isolation"] = {
        "kind": "PHYSICAL_EXCLUSIVE_STOP_VIEW",
        "timerange": plan["development_timerange"],
        "exclusive_stop_utc": view["exclusive_stop_utc"],
        "source_provenance_sha256": digest(provenance_bytes),
        "holdout_values_present": False,
        "filesystem_mode": "files=0444,directories=0555",
        "files": view["files"],
    }
    provenance_path = isolation_root / "retained-data-provenance.json"
    provenance_path.write_bytes(canonical(provenance))
    return {
        "data_dir": data_root,
        "provenance": provenance_path,
        "receipt": provenance["development_isolation"],
    }


def materialize_inputs(root: Path, plan: Mapping[str, Any]) -> dict[str, Path]:
    inputs_root = root / "candidate-inputs"
    if inputs_root.exists():
        raise PilotError("candidate inputs already exist; replay is forbidden")
    inputs_root.mkdir()
    result = {}
    try:
        for candidate in plan["candidates"]:
            destination = inputs_root / candidate["candidate_id"]
            destination.mkdir()
            strategies = destination / "strategies"
            strategies.mkdir()
            strategy = strategies / candidate["_strategy"].name
            shutil.copyfile(candidate["_strategy"], strategy)
            shutil.copyfile(candidate["_spec"], destination / "research-spec.json")
            for name in ("config.json", "market_snapshot.json", "isolated_tiers_snapshot.json"):
                shutil.copyfile(root / ACQUISITION / name, destination / name)
            config, _ = load_json(destination / "config.json", "config")
            config["strategy"] = candidate["class_name"]
            (destination / "config.json").write_bytes(canonical(config))
            verify_candidate_copy(candidate, destination, "Candidate controls")
            result[candidate["candidate_id"]] = destination
    except BaseException:
        shutil.rmtree(inputs_root, ignore_errors=True)
        raise
    return result


def verify_candidate_copy(
    candidate: Mapping[str, Any], root: Path, label: str
) -> None:
    strategy = root / "strategies" / candidate["_strategy"].name
    spec = root / "research-spec.json"
    for path, expected, kind in (
        (strategy, candidate["strategy_sha256"], "strategy"),
        (spec, candidate["research_spec_sha256"], "research spec"),
    ):
        if path.is_symlink() or not path.is_file() or digest(path.read_bytes()) != expected:
            raise PilotError(f"{label} {kind} changed after the frozen plan was loaded")


def materialize_selected_input(
    root: Path, candidate: Mapping[str, Any], controls: Path
) -> Path:
    destination = root / "selected-input"
    if destination.exists():
        raise PilotError("selected input already exists; replay is forbidden")
    shutil.copytree(root / ACQUISITION, destination)
    strategies = destination / "strategies"
    for child in strategies.iterdir():
        child.unlink()
    strategy = strategies / candidate["_strategy"].name
    shutil.copyfile(controls / "strategies" / candidate["_strategy"].name, strategy)
    shutil.copyfile(controls / "research-spec.json", destination / "research-spec.json")
    shutil.copyfile(controls / "config.json", destination / "config.json")
    provenance, _ = load_json(
        destination / "retained-data-provenance.json", "selected provenance"
    )
    provenance["contract"]["strategy"] = f"strategies/{strategy.name}"
    files = {
        name: value
        for name, value in provenance["files"].items()
        if name not in {"config.json", "research-spec.json", "UPSTREAM_LICENSE.txt"}
        and not name.startswith("strategies/")
    }
    for name, path, role in (
        ("config.json", destination / "config.json", "sanitized_freqtrade_config"),
        (
            "research-spec.json",
            destination / "research-spec.json",
            "user_selected_local_research_spec",
        ),
        (
            f"strategies/{strategy.name}",
            strategy,
            "user_selected_local_candidate_strategy",
        ),
    ):
        data = path.read_bytes()
        files[name] = {"role": role, "bytes": len(data), "sha256": digest(data)}
    provenance["files"] = files
    license_path = destination / "UPSTREAM_LICENSE.txt"
    if license_path.exists():
        license_path.unlink()
    (destination / "retained-data-provenance.json").write_bytes(canonical(provenance))
    verify_candidate_copy(candidate, destination, "selected input")
    strategy.chmod(0o444)
    (destination / "research-spec.json").chmod(0o444)
    return destination


def report_metrics(raw: Path, archive_name: str, class_name: str) -> dict[str, Any]:
    archive_path = raw / archive_name
    try:
        with zipfile.ZipFile(archive_path) as archive:
            names = [
                name
                for name in archive.namelist()
                if name.endswith(".json") and not name.endswith("_config.json")
            ]
            if len(names) != 1:
                raise PilotError("Development archive has no unique report")
            result = json.loads(archive.read(names[0]))["strategy"][class_name]
        total = result["total_trades"]
        if isinstance(total, bool) or not isinstance(total, int) or total < 0:
            raise PilotError("Development trade count is invalid")
        semantic_result = dict(result)
        semantic_result.pop("backtest_run_start_ts", None)
        semantic_result.pop("backtest_run_end_ts", None)
        return {
            "archive": archive_name,
            "archive_sha256": digest(archive_path.read_bytes()),
            "report_semantic_sha256": digest(canonical(semantic_result)),
            "total_trades": total,
            "profit_pct": finite(result["profit_total"], "profit_total") * 100,
            "max_drawdown_pct": finite(result["max_drawdown_account"], "drawdown", 0) * 100,
            "profit_factor": finite(result["profit_factor"], "profit_factor", 0),
        }
    except PilotError:
        raise
    except (OSError, KeyError, json.JSONDecodeError, zipfile.BadZipFile) as exc:
        raise PilotError(f"Development report cannot be read: {exc}") from exc


def screen(
    root: Path,
    plan: Mapping[str, Any],
    inputs: Mapping[str, Path],
    python: Path,
    source: Path,
    isolation: Mapping[str, Any],
) -> list[dict[str, Any]]:
    output = root / "development"
    if output.exists():
        raise PilotError("Development outputs already exist; replay is forbidden")
    output.mkdir()
    work = Path(tempfile.mkdtemp(prefix=".screen-", dir=root))
    try:
        snapshot = work / "freqtrade-source"
        source_sha = _prepare_freqtrade_source_snapshot(
            source, snapshot, work / "git-home", DEFAULT_SANDBOX_EXEC
        )
        results = []
        for candidate in plan["candidates"]:
            input_root = inputs[candidate["candidate_id"]]
            verify_candidate_copy(candidate, input_root, "Development input")
            run_root = output / candidate["candidate_id"]
            raw, user, home = run_root / "raw", run_root / "user_data", run_root / "home"
            for path in (raw, user, home, home / "tmp"):
                path.mkdir(parents=True, exist_ok=True)
            config, _ = load_json(input_root / "config.json", "Candidate config")
            fee = finite(config["fee"], "fee", 0)
            strategy_root = input_root / "strategies"
            strategy = strategy_root / candidate["_strategy"].name
            development_provenance = run_root / "retained-data-provenance.json"
            provenance, _ = load_json(
                isolation["provenance"], "Development isolation provenance"
            )
            provenance["contract"]["strategy"] = f"strategies/{strategy.name}"
            files = {
                name: value
                for name, value in provenance["files"].items()
                if not name.startswith("strategies/")
            }
            strategy_bytes = strategy.read_bytes()
            files[f"strategies/{strategy.name}"] = {
                "role": "user_selected_local_candidate_strategy",
                "bytes": len(strategy_bytes),
                "sha256": digest(strategy_bytes),
            }
            provenance["files"] = files
            development_provenance.write_bytes(canonical(provenance))
            runtime_config = run_root / "config.json"
            runtime_config.write_bytes(
                canonical(
                    _runtime_config(
                        config,
                        config_source=input_root / "config.json",
                        data_dir=isolation["data_dir"],
                        user_data_dir=user,
                        strategy_path=strategy_root,
                        strategy=candidate["class_name"],
                        timerange=plan["development_timerange"],
                        fee=fee,
                        export_dir=raw,
                    )
                )
            )
            completed, summary, _ = _run_scenario(
                scenario="DEVELOPMENT",
                timerange=plan["development_timerange"],
                fee=fee,
                python=python,
                source=snapshot,
                source_tree_sha256=source_sha,
                runner_script=DEFAULT_RUNNER,
                runner_sha256=RUNNER_SHA,
                sandbox_exec=DEFAULT_SANDBOX_EXEC,
                config_path=runtime_config,
                data_dir=isolation["data_dir"],
                user_data_dir=user,
                strategy_path=strategy_root,
                strategy_file=strategy,
                strategy_sha256=candidate["strategy_sha256"],
                strategy=candidate["class_name"],
                export_dir=raw,
                market_snapshot=input_root / "market_snapshot.json",
                leverage_tiers=input_root / "isolated_tiers_snapshot.json",
                data_provenance=development_provenance,
                home=home,
                command_runner=subprocess.run,
                allow_zero_trades=True,
            )
            metrics = report_metrics(raw, summary["archive"], candidate["class_name"])
            if metrics["total_trades"] != summary["total_trades"]:
                raise PilotError("runner/report trade counts disagree")
            item = {
                "candidate_id": candidate["candidate_id"],
                "class_name": candidate["class_name"],
                "strategy_sha256": candidate["strategy_sha256"],
                "exit_code": completed.returncode,
                "scenario_data_view": summary["scenario_data_view"],
                **metrics,
            }
            (run_root / "result.json").write_bytes(canonical(item))
            shutil.rmtree(user)
            shutil.rmtree(home)
            runtime_config.unlink()
            results.append(item)
        return results
    finally:
        shutil.rmtree(work, ignore_errors=True)


def write_once(path: Path, value: Mapping[str, Any]) -> None:
    try:
        with path.open("xb") as handle:
            handle.write(canonical(value))
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise PilotError(f"{path.name} already exists; replay is forbidden") from exc


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def select(
    root: Path,
    plan: Mapping[str, Any],
    results: Sequence[Mapping[str, Any]],
    isolation_receipt: Optional[Mapping[str, Any]] = None,
) -> Optional[str]:
    selection = plan["selection"]
    minimum = selection["minimum_trades"]
    gate = selection["economic_gate"]
    if gate == TECHNICAL_ECONOMIC_GATE:
        eligible = [item for item in results if item["total_trades"] >= minimum]
    elif gate == POSITIVE_ECONOMIC_GATE:
        eligible = []
        for item in results:
            total_trades = item["total_trades"]
            if (
                isinstance(total_trades, bool)
                or not isinstance(total_trades, int)
                or total_trades < 0
            ):
                raise PilotError("Development trade count is invalid")
            profit_pct = finite(item["profit_pct"], "Development profit_pct")
            profit_factor = finite(
                item["profit_factor"], "Development profit_factor", 0
            )
            max_drawdown_pct = finite(
                item["max_drawdown_pct"], "Development max_drawdown_pct", 0
            )
            if max_drawdown_pct > 100:
                raise PilotError("Development max_drawdown_pct must not exceed 100")
            if (
                total_trades >= minimum
                and profit_pct >= selection["minimum_profit_pct"]
                and profit_factor >= selection["minimum_profit_factor"]
                and max_drawdown_pct <= selection["maximum_drawdown_pct"]
            ):
                eligible.append(item)
    else:
        raise PilotError("selection economic gate is not supported")
    ranked = sorted(
        eligible,
        key=lambda item: (
            -item["profit_pct"],
            item["max_drawdown_pct"],
            -item["profit_factor"],
            item["candidate_id"],
        ),
    )
    chosen = None if not ranked else ranked[0]["candidate_id"]
    receipt = {
        "schema": SCHEMA,
        "pilot_id": plan["pilot_id"],
        "plan_sha256": plan["_sha256"],
        "development_timerange": plan["development_timerange"],
        "minimum_trades": minimum,
        "ranking": list(RANKING),
        "economic_gate": gate,
        "candidate_results": list(results),
        "eligible_candidate_ids": [item["candidate_id"] for item in ranked],
        "selected_candidate_id": chosen,
        "holdout_read": False,
        "development_isolation": isolation_receipt,
        "created_at_utc": now(),
    }
    if gate == POSITIVE_ECONOMIC_GATE:
        receipt.update({key: selection[key] for key in POSITIVE_GATE_THRESHOLDS})
    write_once(root / SELECTION, receipt)
    return chosen


def database_evidence(database: Path, run_id: str) -> dict[str, Any]:
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        run = connection.execute(
            """
            SELECT rr.status,rr.verdict,c.class_name,c.source_item_index,
                   g.source,g.model,g.returned_strategy_count
            FROM research_runs rr JOIN candidates c ON c.id=rr.candidate_id
            JOIN generation_runs g ON g.id=c.generation_run_id WHERE rr.id=?
            """,
            (run_id,),
        ).fetchone()
        scenarios = connection.execute(
            """
            SELECT scenario,status,total_trades,profit_pct,max_drawdown_pct,
                   profit_factor,scenario_passed FROM backtest_executions
            WHERE research_run_id=? ORDER BY sequence
            """,
            (run_id,),
        ).fetchall()
        releases = connection.execute(
            "SELECT COUNT(*) FROM releases WHERE research_run_id=?", (run_id,)
        ).fetchone()[0]
    finally:
        connection.close()
    if (
        run is None
        or run["status"] != "COMPLETED"
        or run["verdict"] is not None
        or run["source"] != "CODEX"
        or [row["scenario"] for row in scenarios]
        != ["DEVELOPMENT", "HOLDOUT", "HOLDOUT_STRESS"]
        or any(row["status"] != "SUCCEEDED" or row["scenario_passed"] is not None for row in scenarios)
        or releases != 0
    ):
        raise PilotError("database violates the no-verdict three-scenario contract")
    return {
        "research_run_id": run_id,
        "candidate_class_name": run["class_name"],
        "generation_source": run["source"],
        "generation_model": run["model"],
        "returned_strategy_count": run["returned_strategy_count"],
        "source_item_index": run["source_item_index"],
        "status": run["status"],
        "verdict": None,
        "release_count": releases,
        "scenarios": [dict(row) for row in scenarios],
    }


def development_replay_evidence(
    results: Sequence[Mapping[str, Any]],
    chosen: str,
    evidence: Mapping[str, Any],
    produced: Any,
) -> dict[str, Any]:
    screened = next((item for item in results if item["candidate_id"] == chosen), None)
    scenarios = evidence.get("scenarios")
    if screened is None or not isinstance(scenarios, list) or not scenarios:
        raise PilotError("Development replay evidence is incomplete")
    replayed = scenarios[0]
    if replayed.get("scenario") != "DEVELOPMENT":
        raise PilotError("Development replay scenario is missing")
    development_artifact = next(
        (artifact for artifact in produced.artifacts if artifact.scenario == "DEVELOPMENT"),
        None,
    )
    if development_artifact is None:
        raise PilotError("producer Development artifact is missing")
    replay_metrics = report_metrics(
        produced.bundle_root,
        development_artifact.archive,
        evidence["candidate_class_name"],
    )
    provenance_name = (
        development_artifact.archive.removesuffix(".zip") + ".provenance.json"
    )
    replay_provenance, _ = load_json(
        produced.bundle_root / provenance_name, "Development replay provenance"
    )
    replay_view = replay_provenance.get("generation", {}).get("scenario_data_view")
    if replay_view != screened.get("scenario_data_view"):
        raise PilotError("selected Development replay changed its physical data view")
    if (
        replay_metrics["report_semantic_sha256"]
        != screened["report_semantic_sha256"]
    ):
        raise PilotError("selected Development replay changed report semantics")
    comparisons = {
        "total_trades": (screened["total_trades"], replay_metrics["total_trades"]),
        "profit_pct": (screened["profit_pct"], replay_metrics["profit_pct"]),
        "max_drawdown_pct": (
            screened["max_drawdown_pct"],
            replay_metrics["max_drawdown_pct"],
        ),
        "profit_factor": (screened["profit_factor"], replay_metrics["profit_factor"]),
    }
    for label, (before, after) in comparisons.items():
        if label == "total_trades":
            equal = before == after
        else:
            equal = math.isclose(
                finite(before, f"screened {label}"),
                finite(after, f"replayed {label}"),
                rel_tol=0.0,
                abs_tol=1e-12,
            )
        if not equal:
            raise PilotError(f"selected Development replay changed {label}")
        database_value = replayed.get(label)
        if label == "total_trades":
            database_equal = after == database_value
        else:
            database_equal = math.isclose(
                finite(after, f"replayed {label}"),
                finite(database_value, f"database {label}"),
                rel_tol=0.0,
                abs_tol=1e-12,
            )
        if not database_equal:
            raise PilotError(f"Development artifact/database disagree on {label}")
    return {
        "status": "EXACT_REPORT_SEMANTICS_AND_DATA_VIEW_MATCH",
        "screened_archive_sha256": screened["archive_sha256"],
        "screened_report_semantic_sha256": screened["report_semantic_sha256"],
        "producer_report_semantic_sha256": replay_metrics[
            "report_semantic_sha256"
        ],
        "scenario_data_view": replay_view,
        "metrics": {
            label: {"screened": before, "producer_replay": after}
            for label, (before, after) in comparisons.items()
        },
    }


def validate_scenario_open_receipt(
    root: Path,
    plan: Mapping[str, Any],
    candidate: Mapping[str, Any],
    data_provenance_sha256: str,
    scenario: str,
    relative: str,
) -> dict[str, Any]:
    expected_stop = timerange(plan["holdout_timerange"], "Holdout")[1]
    value, data = load_json(root / relative, f"{scenario} open receipt")
    if set(value) != {
        "schema",
        "scenario",
        "timerange",
        "strategy",
        "strategy_sha256",
        "data_provenance_sha256",
        "exclusive_stop_utc",
        "meaning",
        "opened_at_utc",
    } or (
        value["schema"] != "freqtrade-lab-scenario-open-v1"
        or value["scenario"] != scenario
        or value["timerange"] != plan["holdout_timerange"]
        or value["strategy"] != candidate["class_name"]
        or value["strategy_sha256"] != candidate["strategy_sha256"]
        or value["data_provenance_sha256"] != data_provenance_sha256
        or value["exclusive_stop_utc"]
        != expected_stop.isoformat().replace("+00:00", "Z")
        or value["meaning"]
        != (
            "one-shot scenario execution budget was consumed before retained market data "
            "validation began"
        )
        or not isinstance(value["opened_at_utc"], str)
        or not value["opened_at_utc"].endswith("Z")
    ):
        raise PilotError(f"{scenario} open receipt is invalid")
    return {
        "sha256": digest(data),
        "opened_at_utc": value["opened_at_utc"],
    }


def scenario_open_evidence(
    root: Path,
    plan: Mapping[str, Any],
    candidate: Mapping[str, Any],
    data_provenance_sha256: str,
) -> dict[str, Any]:
    receipts = {
        scenario: validate_scenario_open_receipt(
            root,
            plan,
            candidate,
            data_provenance_sha256,
            scenario,
            relative,
        )
        for scenario, relative in (
            ("HOLDOUT", HOLDOUT_SEAL),
            ("HOLDOUT_STRESS", STRESS_SEAL),
        )
    }
    return {
        "holdout_open_count": 1,
        "stress_open_count": 1,
        "receipts": receipts,
    }


def copy_frequi_results(root: Path, chosen: str, produced: Any) -> dict[str, Any]:
    if produced.imported is None:
        raise PilotError("FreqUI copy requires an imported ResearchRun")
    destination = (
        root
        / "frequi"
        / chosen
        / produced.imported.research_run_id
        / "user_data"
        / "backtest_results"
    )
    try:
        destination.mkdir(parents=True)
    except OSError as exc:
        raise PresentationUnavailableError("FreqUI target directory is unavailable") from exc
    copied: list[dict[str, Any]] = []
    for artifact in produced.artifacts:
        archive = produced.bundle_root / artifact.archive
        provenance_name = artifact.archive.removesuffix(".zip") + ".provenance.json"
        provenance, _ = load_json(
            produced.bundle_root / provenance_name, "artifact provenance"
        )
        artifact_receipt = provenance.get("artifact")
        if not isinstance(artifact_receipt, Mapping):
            raise PilotError("FreqUI copy provenance is incomplete")
        metadata_name = artifact_receipt.get("metadata")
        metadata_sha256 = artifact_receipt.get("metadata_sha256")
        if (
            artifact_receipt.get("archive") != artifact.archive
            or artifact_receipt.get("archive_sha256") != artifact.archive_sha256
            or not isinstance(metadata_name, str)
            or Path(metadata_name).name != metadata_name
            or not isinstance(metadata_sha256, str)
        ):
            raise PilotError("FreqUI copy provenance is incomplete")
        metadata = produced.bundle_root / metadata_name
        for source_path, expected_sha in (
            (archive, artifact.archive_sha256),
            (metadata, metadata_sha256),
        ):
            try:
                data = source_path.read_bytes()
            except OSError as exc:
                raise PilotError("FreqUI source cannot be read") from exc
            if digest(data) != expected_sha:
                raise PilotError("FreqUI source changed before copy")
            target = destination / source_path.name
            try:
                if target.is_symlink():
                    raise PresentationUnavailableError("FreqUI target is a symlink")
                with target.open("xb") as handle:
                    handle.write(data)
                if (
                    target.stat().st_nlink != 1
                    or digest(target.read_bytes()) != expected_sha
                ):
                    raise PresentationUnavailableError("FreqUI target identity check failed")
            except PresentationUnavailableError:
                raise
            except OSError as exc:
                raise PresentationUnavailableError("FreqUI target copy is unavailable") from exc
        copied.append(
            {
                "scenario": artifact.scenario,
                "archive": artifact.archive,
                "archive_sha256": artifact.archive_sha256,
                "metadata": metadata_name,
                "metadata_sha256": metadata_sha256,
            }
        )
    if len(copied) != 3:
        raise PilotError("FreqUI source lacks three scenario artifacts")
    try:
        target_count = len(list(destination.iterdir()))
    except OSError as exc:
        raise PresentationUnavailableError("FreqUI target directory is unavailable") from exc
    if target_count != 6:
        raise PresentationUnavailableError("FreqUI target lacks three exact ZIP/meta pairs")
    return {"root": str(destination), "files": copied}


def strategy_library_command(terminal: Mapping[str, Any]) -> str:
    return shlex.join(
        (
            sys.executable,
            str(ROOT / "scripts" / "serve_strategy_library.py"),
            "--database",
            str(terminal["database"]),
            "--artifact-root",
            str(terminal["bundle_root"]),
            "--frequi-base-url",
            str(terminal["frequi_base_url"]),
            "--frequi-results-root",
            str(terminal["frequi_results_root"]),
            "--port",
            str(DEFAULT_PORT),
        )
    )


def run(
    root: Path,
    plan: dict[str, Any],
    python: Path,
    source: Path,
    frequi_base_url: str,
) -> dict[str, Any]:
    url_match = LOOPBACK_URL.fullmatch(frequi_base_url)
    if url_match is None or int(url_match.group(1)) > 65535:
        raise PilotError("FreqUI base URL must be exact numeric loopback HTTP origin")
    if Path(sys.executable).resolve(strict=True) != python.resolve(strict=True):
        raise PilotError("run this Pilot with the exact --freqtrade-python interpreter")
    if any(
        (root / name).exists()
        for name in (
            SELECTION,
            HOLDOUT_AUTHORIZATION,
            HOLDOUT_SEAL,
            STRESS_SEAL,
            TERMINAL,
        )
    ):
        raise PilotError("Pilot receipt already exists; replay is forbidden")
    data = verify_data(root, plan)
    inputs = materialize_inputs(root, plan)
    isolation = materialize_development_isolation(root, plan)
    results = screen(root, plan, inputs, python, source, isolation)
    chosen = select(root, plan, results, isolation["receipt"])
    if chosen is None:
        terminal = {
            "schema": SCHEMA,
            "pilot_id": plan["pilot_id"],
            "plan_sha256": plan["_sha256"],
            "status": "NO_DEVELOPMENT_FINALIST",
            "holdout_opened": False,
            "holdout_open_count": 0,
            "stress_open_count": 0,
            "retry_allowed": False,
            "data": data,
            "development_isolation": isolation["receipt"],
            "created_at_utc": now(),
        }
        write_once(root / TERMINAL, terminal)
        return terminal
    candidate = next(item for item in plan["candidates"] if item["candidate_id"] == chosen)
    workspace = root / "workspace"
    workspace.mkdir()
    database = workspace / "lab.sqlite"
    init_database(database)
    artifacts = workspace / "artifacts"
    artifacts.mkdir()
    opens = root / "scenario-opens"
    opens.mkdir()
    write_once(
        root / HOLDOUT_AUTHORIZATION,
        {
            "schema": SCHEMA,
            "pilot_id": plan["pilot_id"],
            "plan_sha256": plan["_sha256"],
            "selected_candidate_id": chosen,
            "strategy_sha256": candidate["strategy_sha256"],
            "holdout_timerange": plan["holdout_timerange"],
            "holdout_open_count": 0,
            "stress_open_count": 0,
            "retry_after_open": False,
            "tune_after_result": False,
            "meaning": "authorization frozen; no Holdout values have been opened yet",
            "authorized_at_utc": now(),
        },
    )
    input_root = materialize_selected_input(root, candidate, inputs[chosen])
    input_provenance_sha256 = digest(
        (input_root / "retained-data-provenance.json").read_bytes()
    )
    verify_candidate_copy(candidate, input_root, "producer input")
    try:
        produced = run_research_candidate(
            freqtrade_python=python,
            freqtrade_source=source,
            config=input_root / "config.json",
            data_dir=input_root / "data" / "okx",
            strategy_path=input_root / "strategies",
            strategy_file=input_root / "strategies" / candidate["_strategy"].name,
            strategy=candidate["class_name"],
            research_spec=input_root / "research-spec.json",
            data_provenance=input_root / "retained-data-provenance.json",
            market_snapshot=input_root / "market_snapshot.json",
            leverage_tiers=input_root / "isolated_tiers_snapshot.json",
            development_timerange=plan["development_timerange"],
            holdout_timerange=plan["holdout_timerange"],
            stress_fee_multiplier=plan["stress_fee_multiplier"],
            output_dir=artifacts / f"pilot-{plan['pilot_id']}",
            database=database,
            scenario_open_receipts={
                "HOLDOUT": root / HOLDOUT_SEAL,
                "HOLDOUT_STRESS": root / STRESS_SEAL,
            },
        )
    except ResearchCandidateError as exc:
        raise PilotError(f"one-shot existing producer failed: {exc}") from exc
    if produced.imported is None:
        raise PilotError("existing producer did not import a ResearchRun")
    opens_evidence = scenario_open_evidence(
        root, plan, candidate, input_provenance_sha256
    )
    evidence = database_evidence(database, produced.imported.research_run_id)
    replay = development_replay_evidence(results, chosen, evidence, produced)
    frequi_history_visibility: Optional[str] = None
    try:
        validate_strategy_library_database(database)
        frequi = copy_frequi_results(root, chosen, produced)
    except (PresentationUnavailableError, StrategyLibraryError):
        frequi = {"root": None, "files": None}
        frequi_history_visibility = "UNKNOWN"
    terminal = {
        "schema": SCHEMA,
        "pilot_id": plan["pilot_id"],
        "plan_sha256": plan["_sha256"],
        "status": "PILOT_COMPLETED_NO_VERDICT",
        "data": data,
        "development_isolation": isolation["receipt"],
        "development_results": results,
        "development_replay": replay,
        "selected_candidate_id": chosen,
        "selection_basis": plan["selection"],
        **opens_evidence,
        "retry_allowed": False,
        "tuning_after_result": False,
        "manifest_sha256": produced.manifest_sha256,
        "bundle_root": str(produced.bundle_root),
        "database": str(database),
        "database_evidence": evidence,
        "frequi_base_url": frequi_base_url,
        "frequi_results_root": frequi["root"],
        "frequi_copy_receipts": frequi["files"],
        "frequi_history_visibility": frequi_history_visibility,
        "research_claim": "NOT_EVALUATED",
        "trading_claim": "NONE",
        "created_at_utc": now(),
    }
    write_once(root / TERMINAL, terminal)
    return terminal


def failure_open_state(
    root: Path, plan: Optional[Mapping[str, Any]]
) -> dict[str, Any]:
    paths = {
        "HOLDOUT": root / HOLDOUT_SEAL,
        "HOLDOUT_STRESS": root / STRESS_SEAL,
    }
    counts: dict[str, Optional[int]] = {
        scenario: 0 if not path.exists() and not path.is_symlink() else None
        for scenario, path in paths.items()
    }
    if all(value == 0 for value in counts.values()):
        return {
            "holdout_opened": False,
            "holdout_open_count": 0,
            "stress_open_count": 0,
            "open_receipt_integrity": "NOT_OPENED",
        }
    try:
        if plan is None:
            raise PilotError("plan is unavailable")
        selection, _ = load_json(root / SELECTION, "Development selection")
        chosen = selection.get("selected_candidate_id")
        candidate = next(
            item for item in plan["candidates"] if item["candidate_id"] == chosen
        )
        provenance_sha = digest(
            (root / "selected-input" / "retained-data-provenance.json").read_bytes()
        )
        for scenario, relative in (
            ("HOLDOUT", HOLDOUT_SEAL),
            ("HOLDOUT_STRESS", STRESS_SEAL),
        ):
            if paths[scenario].exists() or paths[scenario].is_symlink():
                validate_scenario_open_receipt(
                    root, plan, candidate, provenance_sha, scenario, relative
                )
                counts[scenario] = 1
    except (KeyError, OSError, StopIteration, PilotError, TypeError, ValueError):
        pass
    if counts["HOLDOUT_STRESS"] == 1 and counts["HOLDOUT"] == 0:
        integrity = "CORRUPT_STRESS_WITHOUT_HOLDOUT"
    elif any(value is None for value in counts.values()):
        integrity = "UNKNOWN_INVALID_OR_PARTIAL_RECEIPT"
    else:
        integrity = "VALID_PARTIAL_OR_COMPLETE"
    return {
        "holdout_opened": (
            None if counts["HOLDOUT"] is None else bool(counts["HOLDOUT"])
        ),
        "holdout_open_count": counts["HOLDOUT"],
        "stress_open_count": counts["HOLDOUT_STRESS"],
        "open_receipt_integrity": integrity,
    }


def write_failure(root: Path, plan: Optional[Mapping[str, Any]], error: Exception) -> None:
    if (root / TERMINAL).exists():
        return
    open_state = failure_open_state(root, plan)
    try:
        write_once(
            root / TERMINAL,
            {
                "schema": SCHEMA,
                "pilot_id": None if plan is None else plan.get("pilot_id"),
                "plan_sha256": None if plan is None else plan.get("_sha256"),
                "status": "BLOCKED",
                "error": " ".join(str(error).split())[:1000],
                "holdout_authorized": (root / HOLDOUT_AUTHORIZATION).exists(),
                **open_state,
                "retry_allowed": False,
                "created_at_utc": now(),
            },
        )
    except PilotError:
        pass


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check-data")
    check.add_argument("--pilot-root", required=True, type=Path)
    execute = commands.add_parser("run")
    execute.add_argument("--pilot-root", required=True, type=Path)
    execute.add_argument("--freqtrade-python", required=True, type=Path)
    execute.add_argument("--freqtrade-source", required=True, type=Path)
    execute.add_argument("--frequi-base-url", required=True)
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    root = args.pilot_root.expanduser().resolve(strict=True)
    try:
        root.relative_to(ROOT.resolve(strict=True))
    except ValueError:
        pass
    else:
        raise PilotError("pilot root must stay outside Git")
    plan: Optional[dict[str, Any]] = None
    try:
        plan = load_plan(root)
        if args.command == "check-data":
            print(json.dumps(verify_data(root, plan), ensure_ascii=False, sort_keys=True))
            return 0
        terminal = run(
            root,
            plan,
            args.freqtrade_python.expanduser(),
            args.freqtrade_source.expanduser().resolve(strict=True),
            args.frequi_base_url,
        )
    except Exception as exc:
        if args.command == "run":
            write_failure(root, plan, exc)
        raise PilotError(str(exc)) from exc
    print(f"Pilot status: {terminal['status']}")
    print(f"Terminal receipt: {root / TERMINAL}")
    if terminal["status"] == "PILOT_COMPLETED_NO_VERDICT":
        print(f"Selected Candidate: {terminal['selected_candidate_id']}")
        print(f"Research run: {terminal['database_evidence']['research_run_id']}")
        if terminal.get("frequi_results_root") is None:
            print(
                "Warning: optional presentation is UNKNOWN",
                file=sys.stderr,
            )
        else:
            print(f"Strategy library command: {strategy_library_command(terminal)}")
            print(f"Strategy library URL: http://127.0.0.1:{DEFAULT_PORT}/")
    return 0 if terminal["status"] == "PILOT_COMPLETED_NO_VERDICT" else 3


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except PilotError as exc:
        print(f"Bounded research Pilot failed: {' '.join(str(exc).split())}", file=sys.stderr)
        raise SystemExit(2)
