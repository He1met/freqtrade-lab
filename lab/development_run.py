"""One approved Candidate -> one isolated DEVELOPMENT backtest.

This module is intentionally narrower than :mod:`lab.research_candidate`.
It consumes one Profile-bound frozen Development view, creates exactly one
``DEVELOPMENT`` execution, and never accepts or materializes Holdout inputs.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import sqlite3
import stat
import subprocess
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Optional, Sequence, Tuple, Union
from uuid import uuid4

from lab.backtest_artifact import (
    ArtifactImportError,
    SUPPORTED_FREQTRADE_COMMIT,
    SUPPORTED_FREQTRADE_VERSION,
    import_backtest_execution,
)
from lab.bounded_strategy import (
    BOUNDED_CAUSAL_STRATEGY_V1,
    BoundedStrategyError,
    validate_bounded_causal_strategy,
)
from lab.codex_generation import (
    GenerationContractError,
    load_approved_candidate_snapshot,
    load_profile_snapshot,
)
from lab.database import get_connection
from lab.research_candidate import (
    DEFAULT_GIT_EXECUTABLE,
    DEFAULT_RUNNER,
    DEFAULT_SANDBOX_EXEC,
    SUPPORTED_DEPENDENCIES,
    SUPPORTED_FREQTRADE_TREE,
    ResearchCandidateError,
    _canonical_bytes,
    _mapping,
    _prepare_freqtrade_source_snapshot,
    _run_scenario,
    _runtime_config,
    _sanitize_raw_artifact,
    _validate_config,
)


PathLike = Union[str, Path]
DEVELOPMENT_PIPELINE_VERSION = "BOUNDED_DEVELOPMENT_V1"
DEVELOPMENT_GATE_VERSION = "POSITIVE_DEVELOPMENT_V1"
DEVELOPMENT_INPUT_SCHEMA = "freqtrade-lab-development-input-v1"
DEVELOPMENT_CONTRACT_SCHEMA = "freqtrade-lab-development-contract-v1"
EXPECTED_GATE = {
    "minimum_trades": 30,
    "minimum_profit_pct": 0.5,
    "minimum_profit_factor": 1.1,
    "maximum_drawdown_pct": 5.0,
}
_BUSINESS_TABLES = (
    "research_profiles",
    "generation_runs",
    "candidates",
    "research_runs",
    "backtest_executions",
    "releases",
)
_SHA256 = __import__("re").compile(r"^[0-9a-f]{64}$")
_TIMERANGE = __import__("re").compile(r"^\d{8}-\d{8}$")
_LEGACY_DEVELOPMENT_TIMERANGE = "20260601-20260731"
_LEGACY_WINDOW_SCHEMA = "freqtrade-lab-okx-window-v1"
_STRICT_WINDOW_SCHEMA = "freqtrade-lab-okx-window-v2"
class DevelopmentRunError(ValueError):
    """A stable fail-closed error for the Development-only slice."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class FrozenDevelopmentCapability:
    status: str
    reason: str
    pilot_root: Optional[Path] = None
    freqtrade_python: Optional[Path] = None
    freqtrade_source: Optional[Path] = None
    pilot_identity: Optional[Tuple[int, int]] = None
    python_identity: Optional[Tuple[int, int, int, int]] = None
    source_identity: Optional[Tuple[int, int]] = None
    plan_sha256: Optional[str] = None
    source_provenance_sha256: Optional[str] = None
    source_acquisition_sha256: Optional[str] = None
    development_provenance_sha256: Optional[str] = None
    config_sha256: Optional[str] = None
    runner_sha256: Optional[str] = None
    window_schema: Optional[str] = None
    development_timerange: Optional[str] = None
    pair: Optional[str] = None
    instrument_id: Optional[str] = None
    timeframe: Optional[str] = None
    starting_balance: Optional[float] = None
    stake_amount: Optional[float] = None
    max_open_trades: Optional[int] = None
    base_fee: Optional[float] = None
    economic_gate: Optional[Mapping[str, Any]] = None
    profile_contract: Optional[Mapping[str, Any]] = None
    data_receipts: Tuple[Tuple[str, int, str], ...] = ()
    market_receipt: Optional[Tuple[int, str]] = None
    tiers_receipt: Optional[Tuple[int, str]] = None

    def public(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reason": self.reason,
            "pipeline_version": DEVELOPMENT_PIPELINE_VERSION,
            "security_gate_version": BOUNDED_CAUSAL_STRATEGY_V1,
            "economic_gate": (
                DEVELOPMENT_GATE_VERSION
                if self.profile_contract is None
                else None if self.economic_gate is None else self.economic_gate.get("name")
            ),
            "freqtrade_version": (
                SUPPORTED_FREQTRADE_VERSION if self.status == "READY" else None
            ),
            "timeframe": self.timeframe,
            "development_timerange": self.development_timerange,
            "thresholds": (
                None if self.economic_gate is None else dict(self.economic_gate)
            ),
            "holdout": "SEALED_UNREAD",
            "holdout_stress": "SEALED_UNREAD",
        }


@dataclass(frozen=True)
class PreparedDevelopmentRun:
    research_run_id: str
    candidate_id: str
    trigger_type: str
    run_dir: Path


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_relative(value: str, label: str) -> Path:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise DevelopmentRunError("BLOCKED_DATA", f"{label} path is unsafe")
    posix = PurePosixPath(value)
    if posix.is_absolute() or any(part in {"", ".", ".."} for part in posix.parts):
        raise DevelopmentRunError("BLOCKED_DATA", f"{label} path is unsafe")
    return Path(*posix.parts)


def _read_bytes(path: Path, label: str, limit: int = 64 * 1024 * 1024) -> bytes:
    try:
        info = path.stat(follow_symlinks=False)
        if path.is_symlink() or not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise OSError("not a bounded regular file")
        data = path.read_bytes()
    except OSError as exc:
        raise DevelopmentRunError("BLOCKED_DATA", f"{label} unavailable") from exc
    if len(data) != info.st_size:
        raise DevelopmentRunError("BLOCKED_DATA", f"{label} changed while read")
    return data


def _json_bytes(data: bytes, label: str) -> Mapping[str, Any]:
    try:
        value = json.loads(data.decode("utf-8", "strict"))
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise DevelopmentRunError("BLOCKED_DATA", f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise DevelopmentRunError("BLOCKED_DATA", f"{label} must be a JSON object")
    return value


def _resolve_directory(value: Optional[PathLike], label: str) -> Path:
    if value is None:
        raise DevelopmentRunError("BLOCKED_DATA", f"{label} is not configured")
    raw = Path(value).expanduser()
    try:
        if raw.is_symlink():
            raise OSError("symlink")
        resolved = raw.resolve(strict=True)
        info = os.lstat(resolved)
    except (OSError, RuntimeError, ValueError) as exc:
        raise DevelopmentRunError("BLOCKED_DATA", f"{label} unavailable") from exc
    if not stat.S_ISDIR(info.st_mode):
        raise DevelopmentRunError("BLOCKED_DATA", f"{label} is not a directory")
    return resolved


def _resolve_executable(value: Optional[PathLike]) -> Path:
    if value is None:
        raise DevelopmentRunError("BLOCKED_DATA", "Freqtrade Python is not configured")
    raw = Path(value).expanduser()
    try:
        path = Path(os.path.abspath(str(raw)))
        resolved = path.resolve(strict=True)
        info = os.stat(resolved)
    except (OSError, RuntimeError, ValueError) as exc:
        raise DevelopmentRunError("BLOCKED_DATA", "Freqtrade Python unavailable") from exc
    if not stat.S_ISREG(info.st_mode) or not os.access(path, os.X_OK):
        raise DevelopmentRunError("BLOCKED_DATA", "Freqtrade Python is not executable")
    return path


def _python_identity(path: Path) -> Tuple[int, int, int, int]:
    info = os.stat(path)
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)


def _git_value(source: Path, *arguments: str) -> str:
    try:
        completed = subprocess.run(
            [str(DEFAULT_GIT_EXECUTABLE), "-C", str(source), *arguments],
            env={
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_GLOBAL": "/dev/null",
                "GIT_OPTIONAL_LOCKS": "0",
                "GIT_TERMINAL_PROMPT": "0",
                "HOME": "/var/empty",
                "LC_ALL": "C",
                "PATH": "/usr/bin:/bin",
            },
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise DevelopmentRunError("BLOCKED_DATA", "Freqtrade source cannot be verified") from exc
    if completed.returncode != 0:
        raise DevelopmentRunError("BLOCKED_DATA", "Freqtrade source cannot be verified")
    return completed.stdout.strip()


def _verify_python(python: Path) -> None:
    program = (
        "import importlib.metadata as m,platform,json;"
        "print(json.dumps({'python':platform.python_version(),"
        "'freqtrade':m.version('freqtrade'),'ccxt':m.version('ccxt'),"
        "'pandas':m.version('pandas'),'pyarrow':m.version('pyarrow')},sort_keys=True))"
    )
    try:
        completed = subprocess.run(
            [str(python), "-I", "-c", program],
            env={"HOME": "/var/empty", "LC_ALL": "C", "PATH": "/usr/bin:/bin"},
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        value = json.loads(completed.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        raise DevelopmentRunError("BLOCKED_DATA", "Freqtrade Python cannot be verified") from exc
    expected = {"freqtrade": SUPPORTED_FREQTRADE_VERSION, **SUPPORTED_DEPENDENCIES}
    if completed.returncode != 0 or value != expected:
        raise DevelopmentRunError("BLOCKED_DATA", "Freqtrade Python version contract mismatch")


def _receipt(value: Any, label: str) -> Tuple[int, str]:
    if not isinstance(value, dict):
        raise DevelopmentRunError("BLOCKED_DATA", f"{label} receipt is invalid")
    size, digest = value.get("bytes"), value.get("sha256")
    if (
        isinstance(size, bool)
        or not isinstance(size, int)
        or size < 0
        or not isinstance(digest, str)
        or _SHA256.fullmatch(digest) is None
    ):
        raise DevelopmentRunError("BLOCKED_DATA", f"{label} receipt is invalid")
    return size, digest


def _check_receipt(path: Path, record: Tuple[int, str], label: str) -> bytes:
    data = _read_bytes(path, label)
    if len(data) != record[0] or _sha256(data) != record[1]:
        raise DevelopmentRunError("BLOCKED_DATA", f"{label} receipt mismatch")
    return data


def _verified_market_identity(
    source: Any,
    market_bytes: bytes,
    expected_pair: Any,
) -> Tuple[str, str]:
    """Bind the SHA-verified source identity to its market snapshot."""
    if not isinstance(source, dict):
        raise DevelopmentRunError("BLOCKED_DATA", "source market identity is invalid")
    pair = source.get("pair")
    instrument_id = source.get("instrument_id")
    market = _json_bytes(market_bytes, "market snapshot")
    if (
        source.get("host") != "www.okx.com"
        or source.get("authentication") != "none"
        or not isinstance(pair, str)
        or not pair
        or pair != expected_pair
        or not isinstance(instrument_id, str)
        or not instrument_id
        or market.get("symbol") != pair
        or market.get("id") != instrument_id
    ):
        raise DevelopmentRunError(
            "BLOCKED_DATA", "source market identity disagrees with its snapshot"
        )
    return pair, instrument_id


def _timerange_dates(value: Any, label: str) -> Tuple[datetime, datetime]:
    if not isinstance(value, str) or _TIMERANGE.fullmatch(value) is None:
        raise DevelopmentRunError(
            "BLOCKED_DATA", f"Pilot {label} timerange must use YYYYMMDD-YYYYMMDD"
        )
    try:
        start = datetime.strptime(value[:8], "%Y%m%d").replace(tzinfo=timezone.utc)
        stop = datetime.strptime(value[9:], "%Y%m%d").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise DevelopmentRunError(
            "BLOCKED_DATA", f"Pilot {label} timerange has an invalid date"
        ) from exc
    return start, stop


def _development_window(value: Any) -> Tuple[datetime, datetime, str]:
    """Parse the frozen Pilot Development window and derive its exclusive stop."""
    start, stop = _timerange_dates(value, "Development")
    if stop <= start or stop - start > timedelta(days=366):
        raise DevelopmentRunError(
            "BLOCKED_DATA", "Pilot Development timerange must span 1 to 366 days"
        )
    return start, stop, stop.isoformat().replace("+00:00", "Z")


def _strict_rolling_window(
    pilot_root: Path,
    plan: Mapping[str, Any],
    development_start: datetime,
    development_stop: datetime,
    profile_contract: Optional[Mapping[str, Any]] = None,
) -> str:
    """Bind the one legacy baseline or an explicit rolling-v2 receipt."""
    from lab import bounded_research as pilot

    window_bytes = _read_bytes(
        pilot_root / "window-spec.json", "window spec", 1024 * 1024
    )
    if (
        not isinstance(plan.get("window_spec_sha256"), str)
        or _SHA256.fullmatch(plan["window_spec_sha256"]) is None
        or _sha256(window_bytes) != plan["window_spec_sha256"]
    ):
        raise DevelopmentRunError("BLOCKED_DATA", "rolling window receipt mismatch")
    window = _json_bytes(window_bytes, "window spec")
    required = {
        "schema",
        "data_start_utc",
        "development_start_utc",
        "holdout_start_utc",
        "end_exclusive_utc",
    }
    schema = window.get("schema")
    if set(window) != required or not (
        schema == _STRICT_WINDOW_SCHEMA
        or (
            schema == _LEGACY_WINDOW_SCHEMA
            and plan.get("development_timerange")
            == _LEGACY_DEVELOPMENT_TIMERANGE
        )
    ):
        raise DevelopmentRunError("BLOCKED_DATA", "rolling window receipt is invalid")
    try:
        timestamps = {
            key: datetime.strptime(window[key], "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=timezone.utc
            )
            for key in (
                "data_start_utc",
                "development_start_utc",
                "holdout_start_utc",
                "end_exclusive_utc",
            )
        }
        holdout_start, holdout_stop = _timerange_dates(
            plan.get("holdout_timerange"), "Holdout"
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise DevelopmentRunError("BLOCKED_DATA", "rolling window receipt is invalid") from exc
    holdout_duration = holdout_stop - holdout_start
    frozen_profile: Optional[dict[str, Any]] = None
    if profile_contract is not None:
        try:
            frozen_profile = pilot.validate_profile_search_contract(profile_contract)
        except pilot.PilotError as exc:
            raise DevelopmentRunError(
                "BLOCKED_PROFILE", "Profile Development contract is invalid"
            ) from exc
    if frozen_profile is None:
        valid_holdout = (
            holdout_duration == timedelta(days=30)
            if schema == _STRICT_WINDOW_SCHEMA
            else holdout_duration > timedelta(0)
        )
        valid_pre_roll = (
            timestamps["data_start_utc"] < development_start
            and development_start - timestamps["data_start_utc"] <= timedelta(days=1)
        )
    else:
        snapshot = frozen_profile["profile_snapshot"]
        valid_holdout = holdout_duration == timedelta(days=int(snapshot["holdout_days"]))
        required_start = development_start - timedelta(
            seconds=(
                int(frozen_profile["timeframe_step_seconds"])
                * int(profile_contract["pre_roll_candles"])
            )
        )
        valid_pre_roll = timestamps["data_start_utc"] == required_start
    valid_data_start_alignment = frozen_profile is not None or not any(
        (
            timestamps["data_start_utc"].minute,
            timestamps["data_start_utc"].second,
            timestamps["data_start_utc"].microsecond,
        )
    )
    if (
        (
            timestamps["development_start_utc"],
            timestamps["holdout_start_utc"],
            timestamps["end_exclusive_utc"],
        )
        != (development_start, development_stop, holdout_stop)
        or holdout_start != development_stop
        or not valid_holdout
        or not valid_pre_roll
        or not valid_data_start_alignment
    ):
        raise DevelopmentRunError("BLOCKED_DATA", "rolling window receipt is invalid")
    return str(schema)


def freeze_development_capability(
    pilot_root: Optional[PathLike],
    freqtrade_python: Optional[PathLike],
    freqtrade_source: Optional[PathLike],
    *,
    profile_contract: Optional[Mapping[str, Any]] = None,
) -> FrozenDevelopmentCapability:
    """Freeze the exact local Development capability without mutating Pilot data."""
    from lab import bounded_research as pilot

    profile_public: dict[str, Any] = (
        {"profile_contract": {}} if profile_contract is not None else {}
    )
    try:
        frozen_profile = (
            None
            if profile_contract is None
            else pilot.validate_profile_search_contract(profile_contract)
        )
        if frozen_profile is not None:
            profile_public.update(
                timeframe=str(frozen_profile["timeframe"]),
                economic_gate=dict(frozen_profile["finalist_gate"]),
            )
        root = _resolve_directory(pilot_root, "Pilot root")
        python = _resolve_executable(freqtrade_python)
        source = _resolve_directory(freqtrade_source, "Freqtrade source")
        _verify_python(python)
        if (
            _git_value(source, "rev-parse", "HEAD") != SUPPORTED_FREQTRADE_COMMIT
            or _git_value(source, "rev-parse", "HEAD^{tree}") != SUPPORTED_FREQTRADE_TREE
            or _git_value(source, "describe", "--exact-match", "--tags", "HEAD")
            != SUPPORTED_FREQTRADE_VERSION
            or _git_value(source, "status", "--porcelain=v1", "--untracked-files=all")
        ):
            raise DevelopmentRunError("BLOCKED_DATA", "Freqtrade source contract mismatch")

        plan_bytes = _read_bytes(root / "pilot-spec.json", "Pilot spec", 1024 * 1024)
        plan = _json_bytes(plan_bytes, "Pilot spec")
        development_start, development_stop, development_stop_utc = _development_window(
            plan.get("development_timerange")
        )
        if (
            frozen_profile is None
            and development_stop - development_start != timedelta(days=60)
        ):
            raise DevelopmentRunError(
                "BLOCKED_DATA",
                "Pilot Development timerange must span exactly 60 days",
            )
        window_schema = _strict_rolling_window(
            root,
            plan,
            development_start,
            development_stop,
            profile_contract,
        )
        selection = plan.get("selection")
        if (
            plan.get("freqtrade_version") != SUPPORTED_FREQTRADE_VERSION
            or not isinstance(selection, dict)
            or selection.get("economic_gate") != DEVELOPMENT_GATE_VERSION
            or selection.get("max_selected") != 1
            or selection.get("visibility") != "DEVELOPMENT_ONLY_BLIND"
            or selection.get("candidate_execution_failure") != "STOP"
        ):
            raise DevelopmentRunError("BLOCKED_DATA", "Pilot Development gate contract mismatch")

        acquisition = root / "acquisition"
        isolation = root / "development-isolation"
        provenance_bytes = _read_bytes(
            isolation / "retained-data-provenance.json", "Development provenance"
        )
        provenance = _json_bytes(provenance_bytes, "Development provenance")
        contract = provenance.get("contract")
        source_value = provenance.get("source")
        freqtrade = provenance.get("freqtrade")
        local = provenance.get("local_only_files")
        isolated = provenance.get("development_isolation")
        if (
            provenance.get("schema") != "freqtrade-lab-retained-okx-data-v1"
            or not isinstance(contract, dict)
            or contract.get("timeframe")
            != (frozen_profile or {}).get("timeframe", contract.get("timeframe"))
            or contract.get("development_timerange") != plan["development_timerange"]
            or not isinstance(source_value, dict)
            or source_value.get("host") != "www.okx.com"
            or source_value.get("authentication") != "none"
            or not isinstance(freqtrade, dict)
            or freqtrade.get("version") != SUPPORTED_FREQTRADE_VERSION
            or freqtrade.get("tag") != SUPPORTED_FREQTRADE_VERSION
            or freqtrade.get("commit") != SUPPORTED_FREQTRADE_COMMIT
            or not isinstance(local, dict)
            or not isinstance(isolated, dict)
            or isolated.get("holdout_values_present") is not False
            or isolated.get("timerange") != plan["development_timerange"]
            or isolated.get("exclusive_stop_utc") != development_stop_utc
        ):
            raise DevelopmentRunError("BLOCKED_DATA", "Development isolation contract mismatch")

        acquisition_provenance = _read_bytes(
            acquisition / "retained-data-provenance.json", "source provenance"
        )
        if _sha256(acquisition_provenance) != isolated.get("source_provenance_sha256"):
            raise DevelopmentRunError("BLOCKED_DATA", "Development source provenance mismatch")

        acquisition_provenance_value = _json_bytes(
            acquisition_provenance, "source provenance"
        )
        acquisition_contract = acquisition_provenance_value.get("contract")
        acquisition_files = acquisition_provenance_value.get("files")
        acquisition_source = acquisition_provenance_value.get("source")
        source_acquisition = acquisition_provenance_value.get("source_acquisition")
        if (
            not isinstance(acquisition_contract, dict)
            or acquisition_contract.get("config") != "config.json"
            or not isinstance(acquisition_files, dict)
            or "config.json" not in acquisition_files
            or not isinstance(acquisition_source, dict)
        ):
            raise DevelopmentRunError(
                "BLOCKED_DATA", "Pilot config provenance receipt is missing"
            )
        if frozen_profile is not None:
            if (
                not isinstance(source_acquisition, dict)
                or set(source_acquisition)
                != {
                    "provenance_sha256",
                    "retrieval_receipt_sha256",
                    "data_sha256",
                }
                or _SHA256.fullmatch(
                    str(source_acquisition.get("provenance_sha256"))
                )
                is None
                or _SHA256.fullmatch(
                    str(source_acquisition.get("retrieval_receipt_sha256"))
                )
                is None
                or not isinstance(source_acquisition.get("data_sha256"), dict)
                or any(
                    not isinstance(value, str) or _SHA256.fullmatch(value) is None
                    for value in source_acquisition["data_sha256"].values()
                )
            ):
                raise DevelopmentRunError(
                    "BLOCKED_DATA", "Development source acquisition binding is invalid"
                )
        config_record = _receipt(acquisition_files["config.json"], "Pilot config")
        config_data = _check_receipt(
            acquisition / "config.json", config_record, "Pilot config"
        )
        config = _json_bytes(config_data, "Pilot config")
        validation_config = dict(config)
        validation_config["strategy"] = "DevelopmentCandidate"
        try:
            validated_fee, validated_pairs = _validate_config(
                validation_config,
                "DevelopmentCandidate",
                expected_timeframe=str(contract.get("timeframe")),
            )
            if frozen_profile is not None:
                pilot.validate_profile_runtime_contract(
                    frozen_profile["profile_snapshot"],
                    runtime_config=config,
                    finalist_gate=frozen_profile["finalist_gate"],
                )
        except (pilot.PilotError, ResearchCandidateError) as exc:
            raise DevelopmentRunError(
                "BLOCKED_DATA", "Pilot config contract mismatch"
            ) from exc
        configured_ratio = config.get("tradable_balance_ratio")
        provisional_gate = {
            "version": DEVELOPMENT_GATE_VERSION,
            **EXPECTED_GATE,
        }
        gate = (
            provisional_gate
            if frozen_profile is None
            else dict(frozen_profile["finalist_gate"])
        )
        runtime = {
            "pair": validated_pairs[0],
            "timeframe": config.get("timeframe"),
            "fee": validated_fee,
            "starting_balance": float(config.get("dry_run_wallet")),
            "stake_amount": float(config.get("stake_amount")),
            "max_open_trades": int(config.get("max_open_trades")),
        }
        if (
            runtime["pair"] != source_value.get("pair")
            or runtime["timeframe"] != contract.get("timeframe")
            or configured_ratio != pilot.PROFILE_TRADABLE_BALANCE_RATIO
            or runtime["stake_amount"]
            > runtime["starting_balance"] * pilot.PROFILE_TRADABLE_BALANCE_RATIO
            or any(
                selection.get(key) != gate[key]
                for key in (
                    "minimum_trades",
                    "minimum_profit_factor",
                    "maximum_drawdown_pct",
                )
            )
            or (
                frozen_profile is None
                and selection.get("minimum_profit_pct")
                != EXPECTED_GATE["minimum_profit_pct"]
            )
            or config.get("cancel_open_orders_on_exit") is not False
            or config.get("disableparamexport") is not True
            or config.get("backtest_cache") != "none"
        ):
            raise DevelopmentRunError("BLOCKED_DATA", "Pilot config contract mismatch")

        data_records: list[Tuple[str, int, str]] = []
        market_record: Optional[Tuple[int, str]] = None
        market_bytes: Optional[bytes] = None
        tiers_record: Optional[Tuple[int, str]] = None
        for name, raw_record in local.items():
            if not isinstance(name, str):
                raise DevelopmentRunError(
                    "BLOCKED_DATA", "Development provenance path is invalid"
                )
            safe_name = _safe_relative(name, "Development provenance input")
            record = _receipt(raw_record, "Development input")
            if name == contract.get("market_snapshot"):
                market_bytes = _check_receipt(
                    acquisition / safe_name, record, "market snapshot"
                )
                market_record = record
            elif name == contract.get("leverage_tiers"):
                _check_receipt(acquisition / safe_name, record, "leverage tiers")
                tiers_record = record
            elif name.startswith("data/okx/"):
                relative = name.removeprefix("data/okx/")
                safe_relative = _safe_relative(relative, "Development data")
                _check_receipt(
                    isolation / "data" / "okx" / safe_relative,
                    record,
                    "Development data",
                )
                data_records.append((relative, record[0], record[1]))
            else:
                raise DevelopmentRunError("BLOCKED_DATA", "Development provenance has extra input")
        if (
            not data_records
            or market_record is None
            or market_bytes is None
            or tiers_record is None
        ):
            raise DevelopmentRunError("BLOCKED_DATA", "Development input set is incomplete")
        pair, instrument_id = _verified_market_identity(
            acquisition_source,
            market_bytes,
            source_value.get("pair"),
        )
        if (
            source_value.get("pair") != pair
            or source_value.get("instrument_id") != instrument_id
            or (
                frozen_profile is not None
                and set(source_acquisition["data_sha256"])
                != set(pilot._search_data_names(pair, str(runtime["timeframe"])).values())
            )
        ):
            raise DevelopmentRunError(
                "BLOCKED_DATA", "Development source market identity mismatch"
            )

        runner_data = _read_bytes(DEFAULT_RUNNER, "backtest runner", 2 * 1024 * 1024)
        pilot_info = os.stat(root)
        source_info = os.stat(source)
        return FrozenDevelopmentCapability(
            status="READY",
            reason="Development-only Freqtrade 2026.7 capability is frozen",
            pilot_root=root,
            freqtrade_python=python,
            freqtrade_source=source,
            pilot_identity=(pilot_info.st_dev, pilot_info.st_ino),
            python_identity=_python_identity(python),
            source_identity=(source_info.st_dev, source_info.st_ino),
            plan_sha256=_sha256(plan_bytes),
            source_provenance_sha256=_sha256(acquisition_provenance),
            source_acquisition_sha256=(
                None
                if not isinstance(source_acquisition, dict)
                else _sha256(pilot.canonical(source_acquisition))
            ),
            development_provenance_sha256=_sha256(provenance_bytes),
            config_sha256=_sha256(config_data),
            runner_sha256=_sha256(runner_data),
            window_schema=window_schema,
            development_timerange=str(plan["development_timerange"]),
            pair=pair,
            instrument_id=instrument_id,
            timeframe=str(runtime["timeframe"]),
            starting_balance=float(runtime["starting_balance"]),
            stake_amount=float(runtime["stake_amount"]),
            max_open_trades=int(runtime["max_open_trades"]),
            base_fee=float(runtime["fee"]),
            economic_gate=gate,
            profile_contract=(
                None if profile_contract is None else dict(profile_contract)
            ),
            data_receipts=tuple(sorted(data_records)),
            market_receipt=market_record,
            tiers_receipt=tiers_record,
        )
    except DevelopmentRunError as exc:
        return FrozenDevelopmentCapability(
            status="BLOCKED_DATA",
            reason=exc.message,
            **profile_public,
        )
    except (KeyError, OSError, TypeError, ValueError, sqlite3.Error, pilot.PilotError) as exc:
        return FrozenDevelopmentCapability(
            status="BLOCKED_DATA",
            reason="Development capability could not be frozen",
            **profile_public,
        )


def _require_ready(capability: FrozenDevelopmentCapability) -> None:
    if capability.status != "READY":
        raise DevelopmentRunError("BLOCKED_DATA", capability.reason)
    assert capability.pilot_root is not None
    refreshed = freeze_development_capability(
        capability.pilot_root,
        capability.freqtrade_python,
        capability.freqtrade_source,
        profile_contract=capability.profile_contract,
    )
    frozen = (
        capability.pilot_identity,
        capability.python_identity,
        capability.source_identity,
        capability.plan_sha256,
        capability.source_provenance_sha256,
        capability.source_acquisition_sha256,
        capability.development_provenance_sha256,
        capability.config_sha256,
        capability.runner_sha256,
        capability.data_receipts,
        capability.market_receipt,
        capability.tiers_receipt,
        capability.window_schema,
        capability.development_timerange,
        capability.pair,
        capability.instrument_id,
        capability.timeframe,
        capability.starting_balance,
        capability.stake_amount,
        capability.max_open_trades,
        capability.base_fee,
        capability.economic_gate,
        capability.profile_contract,
    )
    current = (
        refreshed.pilot_identity,
        refreshed.python_identity,
        refreshed.source_identity,
        refreshed.plan_sha256,
        refreshed.source_provenance_sha256,
        refreshed.source_acquisition_sha256,
        refreshed.development_provenance_sha256,
        refreshed.config_sha256,
        refreshed.runner_sha256,
        refreshed.data_receipts,
        refreshed.market_receipt,
        refreshed.tiers_receipt,
        refreshed.window_schema,
        refreshed.development_timerange,
        refreshed.pair,
        refreshed.instrument_id,
        refreshed.timeframe,
        refreshed.starting_balance,
        refreshed.stake_amount,
        refreshed.max_open_trades,
        refreshed.base_fee,
        refreshed.economic_gate,
        refreshed.profile_contract,
    )
    if refreshed.status != "READY" or current != frozen:
        raise DevelopmentRunError("BLOCKED_DATA", "startup-frozen Development inputs changed")


def _schema_v1(connection: sqlite3.Connection) -> None:
    row = connection.execute("PRAGMA user_version").fetchone()
    tables = {
        str(item[0])
        for item in connection.execute(
            "SELECT name FROM sqlite_schema WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }
    if row is None or int(row[0]) != 1 or tables != set(_BUSINESS_TABLES):
        raise DevelopmentRunError("BLOCKED_DATA", "database must be exact six-table schema v1")


def _bound_candidate(
    connection: sqlite3.Connection,
    candidate_id: str,
    expected_timeframe: Optional[str] = None,
) -> sqlite3.Row:
    try:
        approved = load_approved_candidate_snapshot(connection, candidate_id)
    except GenerationContractError as exc:
        raise DevelopmentRunError("BLOCKED_SECURITY", exc.message) from exc
    row = connection.execute(
        """
        SELECT c.*, gr.research_profile_id,
               rp.domain, rp.exchange, rp.trading_mode, rp.margin_mode,
               rp.pairs_json, rp.timeframe AS profile_timeframe,
               rp.detail_timeframe, rp.history_start_date, rp.starting_balance,
               rp.stake_amount, rp.max_open_trades, rp.taker_fee_rate,
               rp.min_development_trades, rp.min_profit_factor,
               rp.max_drawdown_pct
        FROM candidates AS c
        JOIN generation_runs AS gr ON gr.id = c.generation_run_id
        JOIN research_profiles AS rp ON rp.id = gr.research_profile_id
        WHERE c.id = ?
        """,
        (candidate_id,),
    ).fetchone()
    if row is None:
        raise DevelopmentRunError("BLOCKED_SECURITY", "Candidate not found")
    try:
        validate_bounded_causal_strategy(
            row["code_text"],
            row["class_name"],
            expected_timeframe=expected_timeframe or approved.timeframe,
        )
    except BoundedStrategyError as exc:
        raise DevelopmentRunError("BLOCKED_SECURITY", exc.message) from exc
    return row


def _profile_gate(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
    capability: FrozenDevelopmentCapability,
) -> dict[str, Any]:
    from lab import bounded_research as pilot

    if not isinstance(capability.pair, str) or not capability.pair:
        raise DevelopmentRunError("BLOCKED_DATA", "Development market pair is unavailable")
    try:
        profile_snapshot = load_profile_snapshot(
            connection, str(row["research_profile_id"])
        )
        normalized = pilot.validate_profile_runtime_contract(
            profile_snapshot,
            finalist_gate=(
                capability.economic_gate
                if capability.profile_contract is not None
                else None
            ),
        )
        frozen = (
            None
            if capability.profile_contract is None
            else pilot.validate_profile_search_contract(capability.profile_contract)
        )
    except GenerationContractError as exc:
        raise DevelopmentRunError("BLOCKED_PROFILE", exc.message) from exc
    except pilot.PilotError as exc:
        code = (
            "BLOCKED_INSUFFICIENT_CAPACITY"
            if str(exc) == "BLOCKED_INSUFFICIENT_CAPACITY"
            else "BLOCKED_PROFILE"
        )
        raise DevelopmentRunError(code, str(exc)) from exc
    def close(actual: float, expected: Optional[float], tolerance: float = 1e-09) -> bool:
        return expected is None or math.isclose(actual, expected, abs_tol=tolerance)

    matches = (
        row["timeframe"] == row["profile_timeframe"] == normalized["timeframe"]
        and normalized["pair"] == capability.pair
        and normalized["timeframe"] == (capability.timeframe or normalized["timeframe"])
        and close(normalized["starting_balance"], capability.starting_balance)
        and close(normalized["stake_amount"], capability.stake_amount)
        and (capability.max_open_trades is None or normalized["max_open_trades"] == capability.max_open_trades)
        and close(normalized["fee"], capability.base_fee, 1e-15)
        and (frozen is None or (frozen["profile_snapshot"] == profile_snapshot
                                and frozen["finalist_gate"] == normalized["finalist_gate"]))
    )
    if frozen is None:
        matches = matches and (
            normalized["timeframe"] == "5m"
            and close(normalized["starting_balance"], 1000.0)
            and close(normalized["stake_amount"], 100.0)
            and normalized["max_open_trades"] == 1
            and close(normalized["fee"], 0.0005, 1e-15)
            and normalized["minimum_trades"] == EXPECTED_GATE["minimum_trades"]
            and close(normalized["minimum_profit_factor"], EXPECTED_GATE["minimum_profit_factor"], 1e-15)
            and close(normalized["maximum_drawdown_pct"], EXPECTED_GATE["maximum_drawdown_pct"], 1e-15)
        )
    if not matches:
        raise DevelopmentRunError(
            "BLOCKED_PROFILE", "Profile does not match the frozen Pilot Development contract"
        )
    return normalized


def _verified_search_finalist_binding(
    connection: sqlite3.Connection,
    capability: FrozenDevelopmentCapability,
    row: sqlite3.Row,
    value: Optional[Mapping[str, Any]],
    projection_receipt: Optional[Mapping[str, Any]],
) -> Optional[dict[str, Any]]:
    if value is None:
        if capability.profile_contract is not None:
            raise DevelopmentRunError(
                "BLOCKED_SECURITY", "Profile Development requires a verified Search finalist binding"
            )
        return None
    message = "Search finalist handoff binding is invalid"
    if (
        not isinstance(value, Mapping)
        or not isinstance(projection_receipt, Mapping)
        or projection_receipt.get("binding") != value
    ):
        raise DevelopmentRunError("BLOCKED_SECURITY", message)
    binding = dict(value)
    try:
        profile = load_profile_snapshot(connection, str(row["research_profile_id"]))
        projection = connection.execute(
            "SELECT * FROM generation_runs WHERE id=?",
            (binding["search_generation_id"],),
        ).fetchone()
        projection_values = projection_receipt["projection_values"]
        document_hashes = projection_receipt["document_hashes"]
        texts = {
            "request": projection["request_json"],
            "terminal": projection["response_json"],
            "report": projection["parse_report_json"],
        } if projection is not None else {}
        if (
            binding["profile_snapshot"] != profile
            or not isinstance(capability.profile_contract, Mapping)
            or dict(capability.profile_contract)
            != projection_receipt["profile_contract"]
            or (
                binding["candidate_id"], binding["generation_run_id"],
                binding["source_sha256"], binding["profile_id"],
            ) != (
                row["id"], row["generation_run_id"], row["code_sha256"],
                row["research_profile_id"],
            )
            or projection is None
            or any(projection[key] != expected for key, expected in projection_values.items())
            or not all(isinstance(text, str) for text in texts.values())
            or any(
                _sha256(texts[key].encode("utf-8")) != expected
                for key, expected in document_hashes.items()
            )
            or binding["development_timerange"] != capability.development_timerange
        ):
            raise ValueError(message)
    except (KeyError, TypeError, UnicodeError, ValueError, GenerationContractError) as exc:
        raise DevelopmentRunError("BLOCKED_SECURITY", message) from exc
    return binding


def _snapshot(
    capability: FrozenDevelopmentCapability,
    row: sqlite3.Row,
    profile_contract: Optional[Mapping[str, Any]] = None,
    search_finalist_binding: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    resolved_profile = profile_contract or {
        "timeframe": row["profile_timeframe"],
        "finalist_gate": {"version": DEVELOPMENT_GATE_VERSION, **EXPECTED_GATE},
    }
    _, _, exclusive_stop_utc = _development_window(capability.development_timerange)
    snapshot = {
        "schema": DEVELOPMENT_CONTRACT_SCHEMA,
        "pipeline_version": DEVELOPMENT_PIPELINE_VERSION,
        "candidate_id": row["id"],
        "candidate_code_sha256": row["code_sha256"],
        "generation_run_id": row["generation_run_id"],
        "research_profile_id": row["research_profile_id"],
        "security_gate_version": BOUNDED_CAUSAL_STRATEGY_V1,
        "pilot_spec_sha256": capability.plan_sha256,
        "source_provenance_sha256": capability.source_provenance_sha256,
        "development_provenance_sha256": capability.development_provenance_sha256,
        "config_sha256": capability.config_sha256,
        "runner_sha256": capability.runner_sha256,
        "freqtrade_version": SUPPORTED_FREQTRADE_VERSION,
        "freqtrade_commit": SUPPORTED_FREQTRADE_COMMIT,
        "freqtrade_source_tree": SUPPORTED_FREQTRADE_TREE,
        "freqtrade_python_identity": list(capability.python_identity or ()),
        "scenario": "DEVELOPMENT",
        "timeframe": resolved_profile["timeframe"],
        "timerange": capability.development_timerange,
        "exclusive_stop_utc": exclusive_stop_utc,
        "gate": (
            {"version": DEVELOPMENT_GATE_VERSION, **EXPECTED_GATE}
            if capability.profile_contract is None
            else dict(resolved_profile["finalist_gate"])
        ),
        "holdout": "SEALED_UNREAD",
        "holdout_stress": "SEALED_UNREAD",
    }
    if capability.profile_contract is not None:
        snapshot["normalized_profile_contract"] = dict(resolved_profile)
    if search_finalist_binding is not None:
        snapshot["search_finalist_binding"] = dict(search_finalist_binding)
    return snapshot


def _prior_state(
    connection: sqlite3.Connection,
    candidate_id: str,
    current_snapshot: Mapping[str, Any],
) -> str:
    rows = connection.execute(
        """
        SELECT trigger_type, status, input_snapshot_json
        FROM research_runs WHERE candidate_id = ? ORDER BY created_at, id
        """,
        (candidate_id,),
    ).fetchall()
    if not rows:
        return "MANUAL"
    if any(row["status"] in {"PENDING", "RUNNING", "COMPLETED"} for row in rows):
        raise DevelopmentRunError("ALREADY_PENDING", "Candidate was already consumed")
    if any(row["trigger_type"] == "RETRY" for row in rows):
        raise DevelopmentRunError("ALREADY_PENDING", "Candidate retry budget was already consumed")
    if len(rows) != 1:
        raise DevelopmentRunError("ALREADY_PENDING", "Candidate has ambiguous prior attempts")
    try:
        previous = json.loads(rows[0]["input_snapshot_json"])
    except (TypeError, json.JSONDecodeError) as exc:
        raise DevelopmentRunError("ALREADY_PENDING", "Prior attempt contract is unreadable") from exc
    comparable = dict(current_snapshot)
    previous_comparable = dict(previous) if isinstance(previous, dict) else {}
    comparable.pop("materialized_input_hashes", None)
    previous_comparable.pop("materialized_input_hashes", None)
    if previous_comparable != comparable:
        raise DevelopmentRunError("ALREADY_PENDING", "Prior attempt used a different frozen contract")
    return "RETRY"


def _write_exclusive(path: Path, data: bytes, mode: int = 0o600) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(descriptor)


def _copy_input(source: Path, destination: Path, record: Tuple[int, str]) -> None:
    data = _check_receipt(source, record, "Development input")
    destination.parent.mkdir(parents=True, exist_ok=True)
    _write_exclusive(destination, data, 0o400)


def _materialize_inputs(
    run_dir: Path,
    capability: FrozenDevelopmentCapability,
    row: sqlite3.Row,
    snapshot: Mapping[str, Any],
) -> Mapping[str, Any]:
    assert capability.pilot_root is not None
    _, _, exclusive_stop_utc = _development_window(capability.development_timerange)
    input_root = run_dir / "development-input"
    strategies = input_root / "strategies"
    data_root = input_root / "data" / "okx"
    strategies.mkdir(parents=True)
    data_root.mkdir(parents=True)
    acquisition = capability.pilot_root / "acquisition"
    isolation = capability.pilot_root / "development-isolation"

    strategy_bytes = row["code_text"].encode("utf-8")
    strategy_relative = f"strategies/{row['class_name']}.py"
    _write_exclusive(input_root / strategy_relative, strategy_bytes, 0o400)
    source_config_bytes = _read_bytes(acquisition / "config.json", "Pilot config")
    if _sha256(source_config_bytes) != capability.config_sha256:
        raise DevelopmentRunError("BLOCKED_DATA", "startup-frozen Pilot config changed")
    config = _json_bytes(source_config_bytes, "Pilot config")
    config = dict(config)
    config["strategy"] = row["class_name"]
    config_bytes = _canonical_bytes(config)
    _write_exclusive(input_root / "config.json", config_bytes, 0o400)
    assert capability.market_receipt is not None and capability.tiers_receipt is not None
    _copy_input(
        acquisition / "market_snapshot.json",
        input_root / "market_snapshot.json",
        capability.market_receipt,
    )
    _copy_input(
        acquisition / "isolated_tiers_snapshot.json",
        input_root / "isolated_tiers_snapshot.json",
        capability.tiers_receipt,
    )
    local_receipts: dict[str, Any] = {
        "market_snapshot.json": {
            "bytes": capability.market_receipt[0],
            "sha256": capability.market_receipt[1],
            "role": "market_snapshot",
        },
        "isolated_tiers_snapshot.json": {
            "bytes": capability.tiers_receipt[0],
            "sha256": capability.tiers_receipt[1],
            "role": "leverage_tiers",
        },
    }
    input_hashes: dict[str, str] = {
        "config.json": _sha256(config_bytes),
        strategy_relative: row["code_sha256"],
        "market_snapshot.json": capability.market_receipt[1],
        "isolated_tiers_snapshot.json": capability.tiers_receipt[1],
    }
    for relative, size, digest in capability.data_receipts:
        _copy_input(
            isolation / "data" / "okx" / relative,
            data_root / relative,
            (size, digest),
        )
        local_receipts[f"data/okx/{relative}"] = {"bytes": size, "sha256": digest}
        input_hashes[f"data/okx/{relative}"] = digest
    provenance = {
        "schema": "freqtrade-lab-retained-okx-data-v1",
        "portable_retained_fixture": False,
        "source": {
            "host": "www.okx.com",
            "authentication": "none",
            "pair": capability.pair,
            "instrument_id": capability.instrument_id,
        },
        "freqtrade": {
            "version": SUPPORTED_FREQTRADE_VERSION,
            "tag": SUPPORTED_FREQTRADE_VERSION,
            "commit": SUPPORTED_FREQTRADE_COMMIT,
            "dependencies": dict(SUPPORTED_DEPENDENCIES),
        },
        "contract": {
            "config": "config.json",
            "strategy": strategy_relative,
            "data_dir": "data/okx",
            "market_snapshot": "market_snapshot.json",
            "leverage_tiers": "isolated_tiers_snapshot.json",
            "development_timerange": capability.development_timerange,
            "timeframe": snapshot["timeframe"],
        },
        "files": {
            strategy_relative: {
                "bytes": len(strategy_bytes),
                "sha256": row["code_sha256"],
            }
        },
        "local_only_files": local_receipts,
        "development_isolation": {
            "kind": "PHYSICAL_EXCLUSIVE_STOP_VIEW",
            "timerange": capability.development_timerange,
            "exclusive_stop_utc": exclusive_stop_utc,
            "holdout_values_present": False,
        },
    }
    normalized_profile = snapshot.get("normalized_profile_contract")
    if isinstance(normalized_profile, Mapping):
        provenance["contract"]["profile_snapshot"] = normalized_profile[
            "profile_snapshot"
        ]
        provenance["contract"]["profile_snapshot_sha256"] = normalized_profile[
            "profile_snapshot_sha256"
        ]
    provenance_bytes = _canonical_bytes(provenance)
    _write_exclusive(input_root / "retained-data-provenance.json", provenance_bytes, 0o400)
    input_hashes["retained-data-provenance.json"] = _sha256(provenance_bytes)
    final_snapshot = dict(snapshot)
    final_snapshot["materialized_input_hashes"] = dict(sorted(input_hashes.items()))
    manifest = {
        "schema": DEVELOPMENT_INPUT_SCHEMA,
        "research_run_id": run_dir.name,
        "candidate_id": row["id"],
        "class_name": row["class_name"],
        "code_sha256": row["code_sha256"],
        "profile_id": row["research_profile_id"],
        "snapshot": final_snapshot,
        "input_hashes": final_snapshot["materialized_input_hashes"],
    }
    _write_exclusive(input_root / "manifest.json", _canonical_bytes(manifest), 0o400)
    for directory in sorted(
        (item for item in input_root.rglob("*") if item.is_dir()),
        key=lambda item: len(item.parts),
        reverse=True,
    ):
        directory.chmod(0o500)
    input_root.chmod(0o500)
    return final_snapshot


def prepare_development_run(
    database_path: PathLike,
    run_dir: PathLike,
    candidate_id: str,
    capability: FrozenDevelopmentCapability,
    *,
    research_run_id: Optional[str] = None,
    now: Optional[str] = None,
    search_finalist_binding: Optional[Mapping[str, Any]] = None,
) -> PreparedDevelopmentRun:
    """Materialize isolated inputs and atomically consume one Candidate slot."""
    _require_ready(capability)
    run_id = research_run_id or str(uuid4())
    directory = Path(run_dir).resolve(strict=True)
    if directory.name != run_id or any(directory.iterdir()):
        raise DevelopmentRunError("BLOCKED_DATA", "Development run directory must be new and empty")
    timestamp = now or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    database = Path(database_path).resolve(strict=True)
    if capability.profile_contract is not None and search_finalist_binding is None:
        raise DevelopmentRunError(
            "BLOCKED_SECURITY",
            "Profile Development requires a verified Search finalist binding",
        )
    projection_receipt: Optional[Mapping[str, Any]] = None
    if search_finalist_binding is not None:
        from lab import search_campaign

        try:
            projection_receipt = search_campaign.verify_persisted_finalist_projection(
                database, search_finalist_binding
            )
        except search_campaign.SearchCampaignError as exc:
            raise DevelopmentRunError(
                "BLOCKED_SECURITY", "Search finalist handoff binding is invalid"
            ) from exc
    try:
        connection = get_connection(database, must_exist=True)
    except (OSError, sqlite3.Error) as exc:
        raise DevelopmentRunError("BLOCKED_DATA", "database is unavailable") from exc
    materialized = False
    try:
        connection.execute("BEGIN IMMEDIATE")
        _schema_v1(connection)
        row = _bound_candidate(connection, candidate_id, capability.timeframe)
        profile_contract = _profile_gate(connection, row, capability)
        binding = _verified_search_finalist_binding(
            connection,
            capability,
            row,
            search_finalist_binding,
            projection_receipt,
        )
        snapshot = _snapshot(capability, row, profile_contract, binding)
        materialized = True
        snapshot = _materialize_inputs(directory, capability, row, snapshot)
        trigger = _prior_state(connection, candidate_id, snapshot)
        start, stop = (
            datetime.strptime(part, "%Y%m%d").replace(tzinfo=timezone.utc)
            for part in str(capability.development_timerange).split("-", 1)
        )
        execution_end = stop - timedelta(
            seconds=int(profile_contract["timeframe_step_seconds"])
        )
        execution_id = str(uuid4())
        checks = {
            "candidate_binding": "PASSED",
            "security_gate": "PASSED",
            "development_data": "PHYSICALLY_ISOLATED",
            "development_gate": "PENDING",
            "next_phase": "DEVELOPMENT_GATE",
            "holdout": "SEALED_UNREAD",
            "holdout_stress": "SEALED_UNREAD",
        }
        connection.execute(
            """
            INSERT INTO research_runs (
                id, candidate_id, research_profile_id, trigger_type, status, stage,
                verdict, pipeline_version, freqtrade_version, input_snapshot_json,
                checks_json, run_dir, rejection_reasons_json, error_stage,
                error_message, created_at, started_at, finished_at
            ) VALUES (?, ?, ?, ?, 'RUNNING', 'DEVELOPMENT_BACKTEST', NULL, ?, ?, ?, ?, ?, '[]', NULL, NULL, ?, ?, NULL)
            """,
            (
                run_id,
                candidate_id,
                row["research_profile_id"],
                trigger,
                DEVELOPMENT_PIPELINE_VERSION,
                SUPPORTED_FREQTRADE_VERSION,
                json.dumps(snapshot, sort_keys=True, separators=(",", ":")),
                json.dumps(checks, sort_keys=True, separators=(",", ":")),
                str(directory),
                timestamp,
                timestamp,
            ),
        )
        command_receipt = {
            "schema": "freqtrade-lab-development-command-v1",
            "scenario": "DEVELOPMENT",
            "timeframe": profile_contract["timeframe"],
            "timerange": capability.development_timerange,
            "runner_sha256": capability.runner_sha256,
            "browser_overrides": False,
            "holdout_inputs": False,
        }
        connection.execute(
            """
            INSERT INTO backtest_executions (
                id, research_run_id, scenario, status, sequence,
                timerange_start, timerange_end, timeframe, detail_timeframe,
                fee_rate, fee_multiplier, command_json, config_path,
                strategy_path, metrics_json, created_at, started_at
            ) VALUES (?, ?, 'DEVELOPMENT', 'PENDING', 1, ?, ?, ?, NULL, ?, 1.0, ?, ?, ?, '{}', ?, ?)
            """,
            (
                execution_id,
                run_id,
                start.isoformat().replace("+00:00", "Z"),
                execution_end.isoformat().replace("+00:00", "Z"),
                profile_contract["timeframe"],
                float(profile_contract["fee"]),
                json.dumps(command_receipt, sort_keys=True, separators=(",", ":")),
                str(directory / "development-input" / "config.json"),
                str(directory / "development-input" / "strategies" / f"{row['class_name']}.py"),
                timestamp,
                timestamp,
            ),
        )
        connection.commit()
        return PreparedDevelopmentRun(run_id, candidate_id, trigger, directory)
    except DevelopmentRunError:
        if connection.in_transaction:
            connection.rollback()
        if materialized:
            shutil.rmtree(directory / "development-input", ignore_errors=True)
        raise
    except (sqlite3.Error, OSError, ValueError) as exc:
        if connection.in_transaction:
            connection.rollback()
        if materialized:
            shutil.rmtree(directory / "development-input", ignore_errors=True)
        raise DevelopmentRunError("BLOCKED_DATA", "Development run could not be created") from exc
    finally:
        connection.close()


def development_worker_argv(
    database_path: PathLike,
    prepared: PreparedDevelopmentRun,
    capability: FrozenDevelopmentCapability,
    worker_python: PathLike,
) -> Tuple[str, ...]:
    assert capability.freqtrade_python is not None and capability.freqtrade_source is not None
    script = Path(__file__).resolve().parent.parent / "scripts" / "run_development_candidate.py"
    return (
        str(worker_python),
        str(script),
        "--database",
        str(Path(database_path).resolve(strict=True)),
        "--run-dir",
        str(prepared.run_dir),
        "--research-run-id",
        prepared.research_run_id,
        "--freqtrade-python",
        str(capability.freqtrade_python),
        "--freqtrade-source",
        str(capability.freqtrade_source),
    )


def _load_manifest(run_dir: Path, research_run_id: str) -> Mapping[str, Any]:
    root = run_dir / "development-input"
    value = _json_bytes(_read_bytes(root / "manifest.json", "Development manifest"), "Development manifest")
    if value.get("schema") != DEVELOPMENT_INPUT_SCHEMA or value.get("research_run_id") != research_run_id:
        raise DevelopmentRunError("BLOCKED_DATA", "Development manifest identity mismatch")
    hashes = value.get("input_hashes")
    if not isinstance(hashes, dict):
        raise DevelopmentRunError("BLOCKED_DATA", "Development manifest hashes missing")
    for name, digest in hashes.items():
        if not isinstance(name, str) or not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
            raise DevelopmentRunError("BLOCKED_DATA", "Development manifest hash invalid")
        relative = _safe_relative(name, "Development manifest input")
        if _sha256(_read_bytes(root / relative, f"Development input {name!r}")) != digest:
            raise DevelopmentRunError("BLOCKED_DATA", "Development input changed")
    snapshot = value.get("snapshot")
    if (
        not isinstance(snapshot, dict)
        or snapshot.get("materialized_input_hashes") != hashes
    ):
        raise DevelopmentRunError("BLOCKED_DATA", "Development manifest is not bound to its snapshot")
    return value


def _input_receipts(provenance: Mapping[str, Any]) -> dict[str, Any]:
    contract = _mapping(provenance["contract"], "provenance contract")
    local = _mapping(provenance["local_only_files"], "provenance local inputs")
    data_prefix = str(contract["data_dir"]) + "/"
    data: dict[str, str] = {}
    market = tiers = None
    for name, record in local.items():
        if not isinstance(name, str):
            raise DevelopmentRunError("BLOCKED_DATA", "Development provenance path is invalid")
        _safe_relative(name, "Development provenance input")
        value = _mapping(record, f"provenance receipt {name}")
        if name == contract["market_snapshot"]:
            market = value["sha256"]
        elif name == contract["leverage_tiers"]:
            tiers = value["sha256"]
        elif isinstance(name, str) and name.startswith(data_prefix):
            data[name.removeprefix(data_prefix)] = value["sha256"]
    if market is None or tiers is None or not data:
        raise DevelopmentRunError("BLOCKED_DATA", "Development provenance inputs are incomplete")
    return {
        "market_snapshot_sha256": market,
        "leverage_tiers_sha256": tiers,
        "data_sha256": data,
    }


def execute_development_run(
    database_path: PathLike,
    run_dir: PathLike,
    research_run_id: str,
    freqtrade_python: PathLike,
    freqtrade_source: PathLike,
) -> dict[str, Any]:
    """Child-process entrypoint for one real isolated DEVELOPMENT scenario."""
    directory = Path(run_dir).resolve(strict=True)
    if directory.name != research_run_id:
        raise DevelopmentRunError("BLOCKED_DATA", "Development run directory identity mismatch")
    manifest = _load_manifest(directory, research_run_id)
    with closing(
        get_connection(database_path, read_only=True, must_exist=True)
    ) as connection:
        connection.execute("BEGIN")
        bound = connection.execute(
            """
            SELECT rr.candidate_id, rr.pipeline_version, rr.status, rr.stage,
                   rr.verdict, rr.input_snapshot_json, rr.run_dir,
                   c.class_name, c.code_sha256
            FROM research_runs AS rr
            JOIN candidates AS c ON c.id=rr.candidate_id
            WHERE rr.id=?
            """,
            (research_run_id,),
        ).fetchone()
        if bound is None:
            raise DevelopmentRunError("BLOCKED_DATA", "Development database identity missing")
        try:
            database_snapshot = json.loads(bound["input_snapshot_json"])
        except (TypeError, json.JSONDecodeError) as exc:
            raise DevelopmentRunError("BLOCKED_DATA", "Development database snapshot is invalid") from exc
        if (
            bound["pipeline_version"] != DEVELOPMENT_PIPELINE_VERSION
            or bound["status"] != "RUNNING"
            or bound["stage"] != "DEVELOPMENT_BACKTEST"
            or bound["verdict"] is not None
            or Path(bound["run_dir"]).resolve(strict=True) != directory
            or bound["candidate_id"] != manifest.get("candidate_id")
            or bound["class_name"] != manifest.get("class_name")
            or bound["code_sha256"] != manifest.get("code_sha256")
            or database_snapshot != manifest.get("snapshot")
        ):
            raise DevelopmentRunError("BLOCKED_DATA", "Development manifest disagrees with database snapshot")
        connection.rollback()
    input_root = directory / "development-input"
    runtime = directory / "development-runtime"
    evidence = directory / "development-evidence"
    runtime.mkdir()
    evidence.mkdir()
    strategy = str(manifest["class_name"])
    strategy_file = input_root / "strategies" / f"{strategy}.py"
    strategy_bytes = _read_bytes(strategy_file, "Candidate strategy", 256 * 1024)
    provenance_path = input_root / "retained-data-provenance.json"
    provenance_bytes = _read_bytes(provenance_path, "Development provenance")
    provenance = _json_bytes(provenance_bytes, "Development provenance")
    provenance_sha = _sha256(provenance_bytes)
    runner_bytes = _read_bytes(DEFAULT_RUNNER, "backtest runner", 2 * 1024 * 1024)
    runner_sha = _sha256(runner_bytes)
    snapshot = _mapping(manifest["snapshot"], "Development snapshot")
    if runner_sha != snapshot.get("runner_sha256"):
        raise DevelopmentRunError("BLOCKED_DATA", "backtest runner changed")

    python = _resolve_executable(freqtrade_python)
    expected_python_identity = snapshot.get("freqtrade_python_identity")
    if (
        not isinstance(expected_python_identity, list)
        or len(expected_python_identity) != 4
        or any(
            isinstance(value, bool) or not isinstance(value, int)
            for value in expected_python_identity
        )
        or tuple(expected_python_identity) != _python_identity(python)
    ):
        raise DevelopmentRunError(
            "BLOCKED_DATA", "Freqtrade Python identity changed"
        )
    _verify_python(python)

    source_snapshot = runtime / "freqtrade-source"
    source_tree = _prepare_freqtrade_source_snapshot(
        _resolve_directory(freqtrade_source, "Freqtrade source"),
        source_snapshot,
        runtime / "git-home",
        DEFAULT_SANDBOX_EXEC,
    )
    base_config = _json_bytes(_read_bytes(input_root / "config.json", "Development config"), "Development config")
    raw = runtime / "raw"
    user_data = runtime / "user_data"
    home = runtime / "home"
    raw.mkdir()
    user_data.mkdir()
    home.mkdir()
    (home / "tmp").mkdir()
    runtime_config = runtime / "config.json"
    runtime_config.write_bytes(
        _canonical_bytes(
            _runtime_config(
                base_config,
                config_source=input_root / "config.json",
                data_dir=input_root / "data" / "okx",
                user_data_dir=user_data,
                strategy_path=input_root / "strategies",
                strategy=strategy,
                timerange=str(snapshot["timerange"]),
                fee=float(base_config["fee"]),
                export_dir=raw,
            )
        )
    )
    try:
        completed, summary, command_shape = _run_scenario(
            scenario="DEVELOPMENT",
            timerange=str(snapshot["timerange"]),
            fee=float(base_config["fee"]),
            python=python,
            source=source_snapshot,
            source_tree_sha256=source_tree,
            runner_script=DEFAULT_RUNNER,
            runner_sha256=runner_sha,
            sandbox_exec=DEFAULT_SANDBOX_EXEC,
            config_path=runtime_config,
            data_dir=input_root / "data" / "okx",
            user_data_dir=user_data,
            strategy_path=input_root / "strategies",
            strategy_file=strategy_file,
            strategy_sha256=str(manifest["code_sha256"]),
            strategy=strategy,
            export_dir=raw,
            market_snapshot=input_root / "market_snapshot.json",
            leverage_tiers=input_root / "isolated_tiers_snapshot.json",
            data_provenance=provenance_path,
            home=home,
            command_runner=subprocess.run,
            allow_zero_trades=True,
            scenario_open_receipt=None,
        )
        produced = _sanitize_raw_artifact(
            scenario="DEVELOPMENT",
            slug="development-01",
            raw_dir=raw,
            runner_summary=summary,
            completed=completed,
            command_shape=command_shape,
            bundle_dir=evidence,
            strategy=strategy,
            strategy_source=strategy_bytes,
            data_provenance=provenance,
            data_provenance_sha256=provenance_sha,
            expected_input_receipts=_input_receipts(provenance),
            source_tree_sha256=source_tree,
            implementation_receipts={
                "producer": {
                    "bytes": Path(__file__).stat().st_size,
                    "sha256": _sha256(Path(__file__).read_bytes()),
                },
                "runner": {"bytes": len(runner_bytes), "sha256": runner_sha},
            },
            timerange=str(snapshot["timerange"]),
            network_policy="deny-by-default sandbox; network denied; Development-only inputs",
            allow_zero_trades=True,
        )
        import_backtest_execution(
            database_path,
            evidence,
            Path(produced.archive),
            research_run_id,
            "DEVELOPMENT",
            strategy,
            SUPPORTED_FREQTRADE_VERSION,
            produced.provenance_sha256,
            allow_zero_trades=True,
            mark_execution_finished=True,
        )
        result = finalize_development_gate(database_path, research_run_id)
    except (
        ArtifactImportError,
        ResearchCandidateError,
        OSError,
        sqlite3.Error,
    ) as exc:
        raise DevelopmentRunError("DEVELOPMENT_FAILED", "Development execution failed closed") from exc
    finally:
        shutil.rmtree(runtime, ignore_errors=True)
    return result


def _development_gate_contract(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Return the sole executable Gate encoded by a Development snapshot."""
    normalized = snapshot.get("normalized_profile_contract")
    if normalized is None:
        expected = {"version": DEVELOPMENT_GATE_VERSION, **EXPECTED_GATE}
        if snapshot.get("gate") not in (None, expected):
            raise DevelopmentRunError(
                "run_state_conflict", "Development frozen Gate is invalid"
            )
        return {**EXPECTED_GATE, "strictly_positive": False}
    from lab import bounded_research as pilot

    if not isinstance(normalized, Mapping):
        raise DevelopmentRunError(
            "run_state_conflict", "Development frozen Profile is invalid"
        )
    try:
        verified = pilot.validate_profile_runtime_contract(
            normalized.get("profile_snapshot"),
            finalist_gate=snapshot.get("gate"),
        )
    except pilot.PilotError as exc:
        raise DevelopmentRunError(
            "run_state_conflict", "Development frozen Profile is invalid"
        ) from exc
    if dict(normalized) != verified:
        raise DevelopmentRunError(
            "run_state_conflict", "Development frozen Profile changed"
        )
    return {
        "minimum_trades": verified["minimum_trades"],
        "minimum_profit_pct": 0.0,
        "minimum_profit_factor": verified["minimum_profit_factor"],
        "maximum_drawdown_pct": verified["maximum_drawdown_pct"],
        "strictly_positive": True,
    }


def finalize_development_gate(database_path: PathLike, research_run_id: str) -> dict[str, Any]:
    """Idempotently turn imported Development metrics into the fixed gate result."""
    with closing(get_connection(database_path, must_exist=True)) as connection:
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT rr.status AS run_status, rr.stage, rr.verdict,
                       rr.pipeline_version, rr.freqtrade_version,
                       rr.input_snapshot_json, rr.checks_json, be.*
                FROM research_runs AS rr
                JOIN backtest_executions AS be ON be.research_run_id = rr.id
                WHERE rr.id = ? AND be.scenario = 'DEVELOPMENT'
                """,
                (research_run_id,),
            ).fetchone()
            if row is None:
                raise DevelopmentRunError("run_not_found", "Research run not found")
            execution_rows = int(
                connection.execute(
                    "SELECT COUNT(*) FROM backtest_executions WHERE research_run_id=?",
                    (research_run_id,),
                ).fetchone()[0]
            )
            snapshot = json.loads(row["input_snapshot_json"])
            gate_contract = _development_gate_contract(snapshot)
            if (
                execution_rows != 1
                or row["pipeline_version"] != DEVELOPMENT_PIPELINE_VERSION
                or row["freqtrade_version"] != SUPPORTED_FREQTRADE_VERSION
                or snapshot.get("schema") != DEVELOPMENT_CONTRACT_SCHEMA
                or snapshot.get("pipeline_version") != DEVELOPMENT_PIPELINE_VERSION
                or snapshot.get("freqtrade_version") != SUPPORTED_FREQTRADE_VERSION
                or snapshot.get("scenario") != "DEVELOPMENT"
            ):
                raise DevelopmentRunError(
                    "run_state_conflict", "Development frozen contract is invalid"
                )
            if row["run_status"] in {"PENDING", "COMPLETED"}:
                try:
                    terminal_checks = json.loads(row["checks_json"])
                except (TypeError, json.JSONDecodeError) as exc:
                    raise DevelopmentRunError(
                        "run_state_conflict", "Development terminal checks are invalid"
                    ) from exc
                valid_pending = (
                    row["run_status"] == "PENDING"
                    and row["stage"] == "PENDING"
                    and row["verdict"] is None
                    and row["status"] == "SUCCEEDED"
                    and row["scenario_passed"] == 1
                    and terminal_checks.get("development_gate") == "PASSED"
                    and terminal_checks.get("next_phase")
                    == "HOLDOUT_AUTHORIZATION_REQUIRED"
                    and terminal_checks.get("holdout") == "SEALED_UNREAD"
                    and terminal_checks.get("holdout_stress") == "SEALED_UNREAD"
                )
                valid_rejected = (
                    row["run_status"] == "COMPLETED"
                    and row["stage"] == "COMPLETED"
                    and row["verdict"] == "REJECTED"
                    and row["status"] == "SUCCEEDED"
                    and row["scenario_passed"] == 0
                    and terminal_checks.get("development_gate") == "REJECTED"
                    and terminal_checks.get("next_phase") == "NONE_REJECTED"
                    and terminal_checks.get("holdout") == "SEALED_UNREAD"
                    and terminal_checks.get("holdout_stress") == "SEALED_UNREAD"
                )
                if not (valid_pending or valid_rejected):
                    raise DevelopmentRunError(
                        "run_state_conflict", "Development terminal state is inconsistent"
                    )
                connection.rollback()
                return load_public_research_run(database_path, research_run_id)
            if (
                row["run_status"] != "RUNNING"
                or row["stage"] != "DEVELOPMENT_BACKTEST"
                or row["verdict"] is not None
                or row["status"] != "SUCCEEDED"
                or row["scenario_passed"] is not None
            ):
                raise DevelopmentRunError("run_state_conflict", "Development result is not ready for Gate")
            metrics = {
                "total_trades": row["total_trades"],
                "profit_pct": row["profit_pct"],
                "profit_factor": row["profit_factor"],
                "max_drawdown_pct": row["max_drawdown_pct"],
            }
            reasons: list[str] = []
            if metrics["total_trades"] < gate_contract["minimum_trades"]:
                reasons.append("MINIMUM_TRADES_NOT_MET")
            if (
                metrics["profit_pct"] <= gate_contract["minimum_profit_pct"]
                if gate_contract["strictly_positive"]
                else metrics["profit_pct"] < gate_contract["minimum_profit_pct"]
            ):
                reasons.append("MINIMUM_PROFIT_PCT_NOT_MET")
            if metrics["profit_factor"] is None or metrics["profit_factor"] < gate_contract["minimum_profit_factor"]:
                reasons.append("MINIMUM_PROFIT_FACTOR_NOT_MET")
            if metrics["max_drawdown_pct"] > gate_contract["maximum_drawdown_pct"]:
                reasons.append("MAXIMUM_DRAWDOWN_EXCEEDED")
            passed = not reasons
            checks = {
                "candidate_binding": "PASSED",
                "security_gate": "PASSED",
                "development_data": "PHYSICALLY_ISOLATED",
                "development_gate": "PASSED" if passed else "REJECTED",
                "next_phase": (
                    "HOLDOUT_AUTHORIZATION_REQUIRED" if passed else "NONE_REJECTED"
                ),
                "holdout": "SEALED_UNREAD",
                "holdout_stress": "SEALED_UNREAD",
            }
            finished = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            connection.execute(
                """
                UPDATE backtest_executions
                SET scenario_passed = ?, return_code = 0,
                    finished_at = COALESCE(finished_at, ?)
                WHERE research_run_id = ? AND scenario = 'DEVELOPMENT' AND status = 'SUCCEEDED'
                """,
                (1 if passed else 0, finished, research_run_id),
            )
            connection.execute(
                """
                UPDATE research_runs
                SET status = ?, stage = ?, verdict = ?, checks_json = ?,
                    rejection_reasons_json = ?, finished_at = ?,
                    error_stage = NULL, error_message = NULL
                WHERE id = ? AND status = 'RUNNING' AND stage = 'DEVELOPMENT_BACKTEST'
                """,
                (
                    "PENDING" if passed else "COMPLETED",
                    "PENDING" if passed else "COMPLETED",
                    None if passed else "REJECTED",
                    json.dumps(checks, sort_keys=True, separators=(",", ":")),
                    json.dumps(reasons, separators=(",", ":")),
                    None if passed else finished,
                    research_run_id,
                ),
            )
            connection.commit()
        except DevelopmentRunError:
            if connection.in_transaction:
                connection.rollback()
            raise
        except (sqlite3.Error, TypeError, ValueError, KeyError) as exc:
            if connection.in_transaction:
                connection.rollback()
            raise DevelopmentRunError("gate_failed", "Development Gate could not be finalized") from exc
    return load_public_research_run(database_path, research_run_id)


def fail_development_run(
    database_path: PathLike,
    research_run_id: str,
    terminal_status: str,
    error_code: str,
) -> dict[str, Any]:
    """Persist one fail-closed terminal state; imported metrics are never overwritten."""
    mapped = {
        "FAILED": "FAILED",
        "TIMED_OUT": "FAILED",
        "CANCELLED": "CANCELLED",
        "INTERRUPTED": "INTERRUPTED",
    }.get(terminal_status)
    if mapped is None:
        raise DevelopmentRunError("invalid_terminal", "Development terminal status is invalid")
    with closing(get_connection(database_path, must_exist=True)) as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT status FROM backtest_executions WHERE research_run_id=? AND scenario='DEVELOPMENT'",
            (research_run_id,),
        ).fetchone()
        if row is None:
            connection.rollback()
            raise DevelopmentRunError("run_not_found", "Research run not found")
        if row["status"] == "SUCCEEDED":
            connection.rollback()
            return finalize_development_gate(database_path, research_run_id)
        finished = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        connection.execute(
            """
            UPDATE backtest_executions SET status='FAILED', result_archive_path=NULL,
                stdout_path=NULL, stderr_path=NULL, return_code=NULL,
                total_trades=NULL, profit_pct=NULL, max_drawdown_pct=NULL,
                win_rate=NULL, profit_factor=NULL, sharpe=NULL, sortino=NULL,
                calmar=NULL, long_profit_pct=NULL, short_profit_pct=NULL,
                metrics_json='{}', scenario_passed=NULL, error_message=?, finished_at=?
            WHERE research_run_id=? AND scenario='DEVELOPMENT' AND status IN ('PENDING','RUNNING')
            """,
            (error_code, finished, research_run_id),
        )
        connection.execute(
            """
            UPDATE research_runs SET status=?, stage='DEVELOPMENT_BACKTEST', verdict=NULL,
                error_stage='DEVELOPMENT_BACKTEST', error_message=?, finished_at=?
            WHERE id=? AND status='RUNNING' AND verdict IS NULL
            """,
            (mapped, error_code, finished, research_run_id),
        )
        connection.commit()
    return load_public_research_run(database_path, research_run_id)


_PUBLIC_CHECK_VALUES = {
    "candidate_binding": frozenset({"PASSED"}),
    "security_gate": frozenset({"PASSED"}),
    "development_data": frozenset({"PHYSICALLY_ISOLATED"}),
    "development_gate": frozenset({"PENDING", "PASSED", "REJECTED"}),
    "next_phase": frozenset(
        {"DEVELOPMENT_GATE", "HOLDOUT_AUTHORIZATION_REQUIRED", "NONE_REJECTED"}
    ),
    "holdout": frozenset({"SEALED_UNREAD"}),
    "holdout_stress": frozenset({"SEALED_UNREAD"}),
}
_PUBLIC_REJECTION_REASONS = frozenset(
    {
        "MINIMUM_TRADES_NOT_MET",
        "MINIMUM_PROFIT_PCT_NOT_MET",
        "MINIMUM_PROFIT_FACTOR_NOT_MET",
        "MAXIMUM_DRAWDOWN_EXCEEDED",
    }
)
_PUBLIC_ERROR_CODES = frozenset(
    {
        "CANCELLED",
        "CONTROLLER_FAILED",
        "DEVELOPMENT_FAILED",
        "DEVELOPMENT_NONZERO_OR_INVALID",
        "OUTPUT_CREATE_FAILED",
        "RESTART_INTERRUPTED",
        "SERVER_INTERRUPTED",
        "SERVER_RESTARTED",
        "START_FAILED",
        "START_RECEIPT_FAILED",
        "TIMED_OUT",
    }
)


def _public_checks(raw: Any) -> dict[str, str]:
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise DevelopmentRunError(
            "run_state_conflict", "Development checks contract is invalid"
        ) from exc
    if not isinstance(value, dict):
        raise DevelopmentRunError(
            "run_state_conflict", "Development checks contract is invalid"
        )
    required = frozenset(
        {
            "candidate_binding",
            "security_gate",
            "development_data",
            "development_gate",
            "next_phase",
            "holdout",
            "holdout_stress",
        }
    )
    if frozenset(value) != required:
        raise DevelopmentRunError(
            "run_state_conflict", "Development checks contract has unknown fields"
        )
    public: dict[str, str] = {}
    for key, allowed in _PUBLIC_CHECK_VALUES.items():
        if key not in value:
            continue
        selected = value[key]
        if not isinstance(selected, str) or selected not in allowed:
            raise DevelopmentRunError(
                "run_state_conflict", "Development checks contract is invalid"
            )
        public[key] = selected
    return public


def _public_rejection_reasons(raw: Any) -> list[str]:
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise DevelopmentRunError(
            "run_state_conflict", "Development rejection contract is invalid"
        ) from exc
    if (
        not isinstance(value, list)
        or any(
            not isinstance(reason, str) or reason not in _PUBLIC_REJECTION_REASONS
            for reason in value
        )
        or len(set(value)) != len(value)
    ):
        raise DevelopmentRunError(
            "run_state_conflict", "Development rejection contract is invalid"
        )
    return list(value)


def _public_error(
    raw_stage: Any, raw_message: Any
) -> tuple[Optional[str], Optional[str]]:
    if raw_stage is None and raw_message is None:
        return None, None
    code = (
        raw_message
        if isinstance(raw_message, str) and raw_message in _PUBLIC_ERROR_CODES
        else "DEVELOPMENT_FAILED"
    )
    return "DEVELOPMENT_BACKTEST", code


_PUBLIC_UTC_TIMESTAMP = __import__("re").compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]{1,6})?Z$"
)


def _public_timestamp(value: Any) -> tuple[str, datetime]:
    if not isinstance(value, str) or _PUBLIC_UTC_TIMESTAMP.fullmatch(value) is None:
        raise DevelopmentRunError(
            "run_state_conflict", "Development timestamp contract is invalid"
        )
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise DevelopmentRunError(
            "run_state_conflict", "Development timestamp contract is invalid"
        ) from exc
    if parsed.utcoffset() != timedelta(0):
        raise DevelopmentRunError(
            "run_state_conflict", "Development timestamp contract is invalid"
        )
    return value, parsed


def _public_timestamps(row: Any, execution: Any) -> dict[str, Optional[str]]:
    run_created, run_created_at = _public_timestamp(row["created_at"])
    run_started, run_started_at = _public_timestamp(row["started_at"])
    execution_created, execution_created_at = _public_timestamp(
        execution["created_at"]
    )
    execution_started, execution_started_at = _public_timestamp(
        execution["started_at"]
    )
    run_requires_finish = row["status"] in {
        "COMPLETED",
        "FAILED",
        "INTERRUPTED",
        "CANCELLED",
    }
    run_finished = row["finished_at"]
    execution_finished = execution["finished_at"]
    execution_status = execution["status"]
    execution_requires_finish = execution_status in {"SUCCEEDED", "FAILED"}
    execution_finish_invalid = (
        execution_finished is None
    ) == execution_requires_finish
    if (run_finished is None) == run_requires_finish or execution_finish_invalid:
        raise DevelopmentRunError(
            "run_state_conflict", "Development timestamp state is invalid"
        )
    run_finished_at = None
    if run_finished is not None:
        run_finished, run_finished_at = _public_timestamp(run_finished)
    execution_finished_at = None
    if execution_finished is not None:
        execution_finished, execution_finished_at = _public_timestamp(
            execution_finished
        )
    if not (
        run_created_at <= run_started_at
        and run_created_at <= execution_created_at <= execution_started_at
        and (
            run_finished_at is None
            or run_started_at <= run_finished_at
        )
        and (
            execution_finished_at is None
            or execution_started_at <= execution_finished_at
        )
        and (
            run_finished_at is None
            or execution_finished_at is None
            or execution_finished_at <= run_finished_at
        )
    ):
        raise DevelopmentRunError(
            "run_state_conflict", "Development timestamp order is invalid"
        )
    return {
        "created_at": run_created,
        "started_at": run_started,
        "finished_at": run_finished,
        "execution_created_at": execution_created,
        "execution_started_at": execution_started,
        "execution_finished_at": execution_finished,
    }


def _public_number(
    value: Any,
    *,
    integer: bool = False,
    minimum: Optional[float] = None,
    maximum: Optional[float] = None,
) -> Optional[Union[int, float]]:
    if value is None:
        return None
    if isinstance(value, bool) or (
        integer and not isinstance(value, int)
    ) or (not integer and not isinstance(value, (int, float))):
        raise DevelopmentRunError(
            "run_state_conflict", "Development metric contract is invalid"
        )
    number = float(value)
    if (
        not math.isfinite(number)
        or (minimum is not None and number < minimum)
        or (maximum is not None and number > maximum)
    ):
        raise DevelopmentRunError(
            "run_state_conflict", "Development metric contract is invalid"
        )
    return value


def _public_gate_results(
    row: Any, execution: Any
) -> tuple[list[dict[str, Any]], Optional[list[str]], dict[str, Any]]:
    try:
        snapshot = json.loads(row["input_snapshot_json"])
    except (TypeError, json.JSONDecodeError) as exc:
        raise DevelopmentRunError(
            "run_state_conflict", "Development frozen contract is invalid"
        ) from exc
    if not isinstance(snapshot, dict):
        raise DevelopmentRunError(
            "run_state_conflict", "Development frozen contract is invalid"
        )
    gate_contract = _development_gate_contract(snapshot)
    actual = {
        "total_trades": _public_number(
            execution["total_trades"], integer=True, minimum=0.0
        ),
        "profit_pct": _public_number(execution["profit_pct"]),
        "profit_factor": _public_number(
            execution["profit_factor"], minimum=0.0
        ),
        "max_drawdown_pct": _public_number(
            execution["max_drawdown_pct"], minimum=0.0, maximum=100.0
        ),
        "win_rate": _public_number(
            execution["win_rate"], minimum=0.0, maximum=100.0
        ),
    }
    terminal = row["status"] in {"PENDING", "COMPLETED"}
    gate_actual = {
        "minimum_trades": actual["total_trades"],
        "minimum_profit_pct": actual["profit_pct"],
        "minimum_profit_factor": actual["profit_factor"],
        "maximum_drawdown_pct": actual["max_drawdown_pct"],
    }
    if terminal and any(
        gate_actual[criterion] is None
        for criterion in (
            "minimum_trades",
            "minimum_profit_pct",
            "maximum_drawdown_pct",
        )
    ):
        raise DevelopmentRunError(
            "run_state_conflict", "Development terminal Gate metrics are incomplete"
        )
    passed: dict[str, Optional[bool]] = {
        criterion: None for criterion in gate_actual
    }
    reasons: Optional[list[str]] = None
    if terminal:
        passed = {
            "minimum_trades": gate_actual["minimum_trades"]
            >= gate_contract["minimum_trades"],
            "minimum_profit_pct": (
                gate_actual["minimum_profit_pct"]
                > gate_contract["minimum_profit_pct"]
                if gate_contract["strictly_positive"]
                else gate_actual["minimum_profit_pct"]
                >= gate_contract["minimum_profit_pct"]
            ),
            "minimum_profit_factor": gate_actual["minimum_profit_factor"]
            is not None
            and gate_actual["minimum_profit_factor"]
            >= gate_contract["minimum_profit_factor"],
            "maximum_drawdown_pct": gate_actual["maximum_drawdown_pct"]
            <= gate_contract["maximum_drawdown_pct"],
        }
        reasons = []
        for criterion, reason in (
            ("minimum_trades", "MINIMUM_TRADES_NOT_MET"),
            ("minimum_profit_pct", "MINIMUM_PROFIT_PCT_NOT_MET"),
            ("minimum_profit_factor", "MINIMUM_PROFIT_FACTOR_NOT_MET"),
            ("maximum_drawdown_pct", "MAXIMUM_DRAWDOWN_EXCEEDED"),
        ):
            if passed[criterion] is not True:
                reasons.append(reason)
    gate_results = [
        {
            "criterion": criterion,
            "threshold": gate_contract[criterion],
            "actual": gate_actual[criterion],
            "passed": passed[criterion],
        }
        for criterion in (
            "minimum_trades",
            "minimum_profit_pct",
            "minimum_profit_factor",
            "maximum_drawdown_pct",
        )
    ]
    return gate_results, reasons, actual


def _validate_public_run_state(
    row: Any,
    execution: Any,
    checks: Mapping[str, str],
    rejection_reasons: Sequence[str],
    error_stage: Optional[str],
    error_message: Optional[str],
    expected_reasons: Optional[Sequence[str]],
) -> None:
    if (
        row["freqtrade_version"] != SUPPORTED_FREQTRADE_VERSION
        or row["trigger_type"] not in {"MANUAL", "RETRY"}
    ):
        raise DevelopmentRunError(
            "run_state_conflict", "Development public run contract is invalid"
        )
    metric_fields = (
        "total_trades",
        "profit_pct",
        "max_drawdown_pct",
        "win_rate",
        "profit_factor",
    )
    empty_metrics = all(execution[field] is None for field in metric_fields)
    imported_metrics = all(
        execution[field] is not None
        for field in (
            "total_trades",
            "profit_pct",
            "max_drawdown_pct",
            "win_rate",
        )
    )
    running_execution = (
        execution["status"] in {"PENDING", "RUNNING"} and empty_metrics
    ) or (execution["status"] == "SUCCEEDED" and imported_metrics)
    running = (
        row["status"] == "RUNNING"
        and row["stage"] == "DEVELOPMENT_BACKTEST"
        and row["verdict"] is None
        and running_execution
        and execution["scenario_passed"] is None
    )
    pending = (
        row["status"] == "PENDING"
        and row["stage"] == "PENDING"
        and row["verdict"] is None
        and execution["status"] == "SUCCEEDED"
        and execution["scenario_passed"] == 1
    )
    rejected = (
        row["status"] == "COMPLETED"
        and row["stage"] == "COMPLETED"
        and row["verdict"] == "REJECTED"
        and execution["status"] == "SUCCEEDED"
        and execution["scenario_passed"] == 0
    )
    failed = (
        row["status"] in {"FAILED", "INTERRUPTED", "CANCELLED"}
        and row["stage"] == "DEVELOPMENT_BACKTEST"
        and row["verdict"] is None
        and execution["status"] == "FAILED"
        and execution["scenario_passed"] is None
        and empty_metrics
    )
    evidence_matches = (
        running
        and checks["development_gate"] == "PENDING"
        and checks["next_phase"] == "DEVELOPMENT_GATE"
        and not rejection_reasons
        and error_stage is None
        and error_message is None
    ) or (
        pending
        and checks["development_gate"] == "PASSED"
        and checks["next_phase"] == "HOLDOUT_AUTHORIZATION_REQUIRED"
        and expected_reasons == []
        and not rejection_reasons
        and error_stage is None
        and error_message is None
    ) or (
        rejected
        and checks["development_gate"] == "REJECTED"
        and checks["next_phase"] == "NONE_REJECTED"
        and expected_reasons is not None
        and list(rejection_reasons) == list(expected_reasons)
        and bool(expected_reasons)
        and error_stage is None
        and error_message is None
    ) or (
        failed
        and checks["development_gate"] == "PENDING"
        and checks["next_phase"] == "DEVELOPMENT_GATE"
        and not rejection_reasons
        and error_stage == "DEVELOPMENT_BACKTEST"
        and error_message is not None
    )
    if not evidence_matches:
        raise DevelopmentRunError(
            "run_state_conflict", "Development public run state is invalid"
        )


def load_public_research_run(
    database_path: PathLike, research_run_id: str
) -> dict[str, Any]:
    with closing(
        get_connection(database_path, read_only=True, must_exist=True)
    ) as connection:
        connection.execute("BEGIN")
        identity = connection.execute(
            "SELECT pipeline_version FROM research_runs WHERE id=?",
            (research_run_id,),
        ).fetchone()
        if (
            identity is None
            or identity["pipeline_version"] != DEVELOPMENT_PIPELINE_VERSION
        ):
            connection.rollback()
            raise DevelopmentRunError("run_not_found", "Research run not found")
        row = connection.execute(
            """
            SELECT id, candidate_id, trigger_type, status, stage, verdict,
                   pipeline_version, freqtrade_version, checks_json,
                   input_snapshot_json,
                   rejection_reasons_json, error_stage, error_message,
                   created_at, started_at, finished_at
            FROM research_runs WHERE id=?
            """,
            (research_run_id,),
        ).fetchone()
        executions = connection.execute(
            """
            SELECT scenario, status, total_trades, profit_pct,
                   max_drawdown_pct, win_rate, profit_factor, scenario_passed,
                   created_at, started_at, finished_at
            FROM backtest_executions
            WHERE research_run_id=? AND scenario='DEVELOPMENT'
            ORDER BY sequence, id
            """,
            (research_run_id,),
        ).fetchall()
        connection.rollback()
    if row is None:
        raise DevelopmentRunError("run_not_found", "Research run not found")
    if len(executions) != 1:
        raise DevelopmentRunError(
            "run_state_conflict",
            "Development run must contain exactly one DEVELOPMENT execution",
        )
    execution = executions[0]
    checks = _public_checks(row["checks_json"])
    rejection_reasons = _public_rejection_reasons(row["rejection_reasons_json"])
    error_stage, error_message = _public_error(
        row["error_stage"], row["error_message"]
    )
    gate_results, expected_reasons, actual = _public_gate_results(row, execution)
    timestamps = _public_timestamps(row, execution)
    _validate_public_run_state(
        row,
        execution,
        checks,
        rejection_reasons,
        error_stage,
        error_message,
        expected_reasons,
    )
    return {
        "research_run_id": row["id"],
        "candidate_id": row["candidate_id"],
        "trigger_type": row["trigger_type"],
        "status": row["status"],
        "stage": row["stage"],
        "verdict": row["verdict"],
        "pipeline_version": row["pipeline_version"],
        "freqtrade_version": row["freqtrade_version"],
        "checks": checks,
        "gate_results": gate_results,
        "rejection_reasons": rejection_reasons,
        "error_stage": error_stage,
        "error_message": error_message,
        "created_at": timestamps["created_at"],
        "started_at": timestamps["started_at"],
        "finished_at": timestamps["finished_at"],
        "development": {
            "status": execution["status"],
            "total_trades": actual["total_trades"],
            "profit_pct": actual["profit_pct"],
            "max_drawdown_pct": actual["max_drawdown_pct"],
            "win_rate": actual["win_rate"],
            "profit_factor": actual["profit_factor"],
            "scenario_passed": (
                None
                if execution["scenario_passed"] is None
                else bool(execution["scenario_passed"])
            ),
            "started_at": timestamps["execution_started_at"],
            "finished_at": timestamps["execution_finished_at"],
        },
        "holdout": {"status": "SEALED_UNREAD", "execution_rows": 0},
        "holdout_stress": {"status": "SEALED_UNREAD", "execution_rows": 0},
    }


def research_context(
    database_path: PathLike,
    capability: FrozenDevelopmentCapability,
) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    try:
        connection = get_connection(database_path, read_only=True, must_exist=True)
    except (OSError, sqlite3.Error):
        return {
            "capability": capability.public(),
            "candidates": [],
            "latest_research_run_id": None,
        }
    with closing(connection):
        connection.execute("BEGIN")
        latest_row = connection.execute(
            """
            SELECT id FROM research_runs
            WHERE pipeline_version=?
            ORDER BY created_at DESC, id DESC LIMIT 1
            """,
            (DEVELOPMENT_PIPELINE_VERSION,),
        ).fetchone()
        ids = [
            str(row[0])
            for row in connection.execute(
                """
                SELECT id FROM candidates
                WHERE json_extract(metadata_json, '$.review.status') = 'APPROVED'
                ORDER BY created_at DESC, id
                """
            ).fetchall()
        ]
        for candidate_id in ids:
            state, reason = "READY", "Approved Candidate is ready for one Development run"
            display_name = candidate_id
            try:
                row = _bound_candidate(
                    connection, candidate_id, capability.timeframe
                )
                display_name = row["display_name"]
                if not isinstance(capability.pair, str) or not capability.pair:
                    _require_ready(capability)
                _profile_gate(connection, row, capability)
                _require_ready(capability)
                _prior_state(connection, candidate_id, _snapshot(capability, row))
            except DevelopmentRunError as exc:
                state = exc.code
                reason = exc.message
            candidates.append(
                {
                    "candidate_id": candidate_id,
                    "display_name": display_name,
                    "status": state,
                    "reason": reason,
                }
            )
        connection.rollback()
    return {
        "capability": capability.public(),
        "candidates": candidates,
        "latest_research_run_id": (
            None if latest_row is None else str(latest_row["id"])
        ),
    }
