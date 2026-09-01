"""One-shot HOLDOUT/HOLDOUT_STRESS continuation for an existing ResearchRun.

This module deliberately owns only the two database boundaries needed by the
continuation slice: authorization/preparation and the all-or-nothing attachment
of two already validated later-phase artifacts.  It never creates a new
ResearchRun and never runs Development.
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
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence, Tuple, Union
from urllib.parse import urlencode, urlsplit
from uuid import uuid4

from lab.backtest_artifact import (
    SUPPORTED_FREQTRADE_VERSION,
    ArtifactImportError,
    ParsedBacktestArtifact,
    execution_result_values,
    parse_backtest_artifact,
)
from lab.database import get_connection
from lab.development_run import (
    DEVELOPMENT_CONTRACT_SCHEMA,
    DEVELOPMENT_GATE_VERSION,
    DEVELOPMENT_PIPELINE_VERSION,
    EXPECTED_GATE,
    DevelopmentRunError,
    FrozenDevelopmentCapability,
    _bound_candidate,
    _python_identity,
    _profile_gate,
    _require_ready as _require_development_ready,
    _resolve_directory,
    _resolve_executable,
    _verify_python,
    freeze_development_capability,
    load_public_research_run as load_development_public_research_run,
)
from lab.frequi import FreqUIConfig
from lab.research_candidate import (
    DEFAULT_RUNNER,
    DEFAULT_SANDBOX_EXEC,
    RESEARCH_SPEC_SCHEMA,
    SUPPORTED_DEPENDENCIES,
    SUPPORTED_FREQTRADE_TREE,
    SUPPORTED_OFFICIAL_CORE,
    ResearchCandidateError,
    _canonical_bytes,
    _mapping,
    _prepare_freqtrade_source_snapshot,
    _run_scenario,
    _runtime_config,
    _sanitize_raw_artifact,
    _validate_config,
    _validate_data_provenance,
    _validate_research_spec,
    _validate_scenario_open_receipt,
)
from lab.research_bundle import (
    BUNDLE_SCENARIOS,
    ProfileSpec,
    ResearchBundleImportError,
    _validate_cross_scenario,
)


PathLike = Union[str, Path]
HOLDOUT_AUTHORIZATION_SCHEMA = "freqtrade-lab-holdout-authorization-v1"
HOLDOUT_COMMAND_SCHEMA = "freqtrade-lab-holdout-command-v1"
HOLDOUT_INPUT_SCHEMA = "freqtrade-lab-holdout-input-v1"
HOLDOUT_RESULT_SCHEMA = "freqtrade-lab-holdout-result-v1"
HOLDOUT_ATTEMPT_NAME = ".holdout-attempt.json"
HOLDOUT_RESULT_NAME = "holdout-result.json"
_SHA256 = __import__("re").compile(r"^[0-9a-f]{64}$")
_GIT_OBJECT_ID = __import__("re").compile(r"^[0-9a-f]{40}$")
_PUBLIC_ERROR_CODES = frozenset(
    {
        "CANCELLED",
        "CONTROLLER_FAILED",
        "HOLDOUT_NONZERO_OR_INVALID",
        "NOT_OPENED_AFTER_TERMINAL",
        "OUTPUT_CREATE_FAILED",
        "PROCESS_GROUP_UNCONFIRMED",
        "RESTART_INTERRUPTED",
        "SERVER_INTERRUPTED",
        "START_FAILED",
        "START_RECEIPT_FAILED",
        "TIMED_OUT",
    }
)
_BUSINESS_TABLES = frozenset(
    {
        "research_profiles",
        "generation_runs",
        "candidates",
        "research_runs",
        "backtest_executions",
        "releases",
    }
)
_ORIGINAL_CHECKS = {
    "candidate_binding": "PASSED",
    "security_gate": "PASSED",
    "development_data": "PHYSICALLY_ISOLATED",
    "development_gate": "PASSED",
    "next_phase": "HOLDOUT_AUTHORIZATION_REQUIRED",
    "holdout": "SEALED_UNREAD",
    "holdout_stress": "SEALED_UNREAD",
}


class HoldoutRunError(ValueError):
    """Stable, public-safe continuation error."""

    def __init__(self, code: str, message: str, *, status: Optional[int] = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = (
            status
            if status is not None
            else 404
            if code == "run_not_found"
            else 503
            if code == "BLOCKED_DATA"
            else 409
        )


@dataclass(frozen=True)
class FrozenHoldoutCapability:
    """Startup-frozen later-phase contract; market values remain unopened."""

    status: str
    reason: str
    development: Optional[FrozenDevelopmentCapability] = None
    pilot_root: Optional[Path] = None
    freqtrade_python: Optional[Path] = None
    freqtrade_source: Optional[Path] = None
    plan_sha256: Optional[str] = None
    acquisition_provenance_sha256: Optional[str] = None
    config_sha256: Optional[str] = None
    runner_sha256: Optional[str] = None
    development_timerange: Optional[str] = None
    holdout_timerange: Optional[str] = None
    stress_fee_multiplier: Optional[float] = None
    pair: Optional[str] = None
    local_receipts: Tuple[Tuple[str, int, str, Optional[str]], ...] = ()

    def public(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reason": self.reason,
            "pipeline_version": DEVELOPMENT_PIPELINE_VERSION,
            "action": "AUTHORIZE_HOLDOUT",
            "holdout": (
                "READY_AFTER_AUTHORIZATION"
                if self.status == "READY"
                else "SEALED_UNREAD"
            ),
            "holdout_stress": (
                "READY_AFTER_AUTHORIZATION"
                if self.status == "READY"
                else "SEALED_UNREAD"
            ),
            "holdout_timerange": self.holdout_timerange,
            "stress_fee_multiplier": self.stress_fee_multiplier,
            "one_shot": True,
        }


@dataclass(frozen=True)
class PreparedHoldoutContinuation:
    research_run_id: str
    candidate_id: str
    run_dir: Path
    holdout_execution_id: str
    stress_execution_id: str


PreparedHoldoutRun = PreparedHoldoutContinuation


def _read_regular(path: Path, label: str, limit: int = 64 * 1024 * 1024) -> bytes:
    try:
        info = path.stat(follow_symlinks=False)
        if path.is_symlink() or not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise OSError("not a bounded regular file")
        data = path.read_bytes()
    except OSError as exc:
        raise HoldoutRunError("BLOCKED_DATA", f"{label} is unavailable") from exc
    if len(data) != info.st_size:
        raise HoldoutRunError("BLOCKED_DATA", f"{label} changed while read")
    return data


def _json_bytes(data: bytes, label: str) -> Mapping[str, Any]:
    try:
        value = json.loads(data.decode("utf-8", "strict"))
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise HoldoutRunError("BLOCKED_DATA", f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise HoldoutRunError("BLOCKED_DATA", f"{label} must be a JSON object")
    return value


def _receipt_record(value: Any, label: str) -> Tuple[int, str, Optional[str]]:
    if not isinstance(value, dict):
        raise HoldoutRunError("BLOCKED_DATA", f"{label} receipt is invalid")
    size, digest, role = value.get("bytes"), value.get("sha256"), value.get("role")
    if (
        isinstance(size, bool)
        or not isinstance(size, int)
        or size < 0
        or not isinstance(digest, str)
        or _SHA256.fullmatch(digest) is None
        or (role is not None and not isinstance(role, str))
    ):
        raise HoldoutRunError("BLOCKED_DATA", f"{label} receipt is invalid")
    return size, digest, role


def _safe_relative(value: Any, label: str) -> Path:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise HoldoutRunError("BLOCKED_DATA", f"{label} path is unsafe")
    path = Path(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise HoldoutRunError("BLOCKED_DATA", f"{label} path is unsafe")
    return path


def freeze_holdout_capability(
    pilot_root: Optional[PathLike],
    freqtrade_python: Optional[PathLike],
    freqtrade_source: Optional[PathLike],
) -> FrozenHoldoutCapability:
    """Freeze later-phase receipt metadata without reading retained market values."""
    development = freeze_development_capability(
        pilot_root, freqtrade_python, freqtrade_source
    )
    if development.status != "READY" or development.pilot_root is None:
        return FrozenHoldoutCapability(
            status="BLOCKED_DATA",
            reason=development.reason,
            development=development,
        )
    try:
        pilot = development.pilot_root
        plan_bytes = _read_regular(pilot / "pilot-spec.json", "Pilot spec", 1024 * 1024)
        plan = _json_bytes(plan_bytes, "Pilot spec")
        holdout_timerange = plan.get("holdout_timerange")
        start, stop = _timerange(holdout_timerange)
        development_timerange = plan.get("development_timerange")
        _, development_stop = _timerange(development_timerange)
        multiplier = float(plan.get("stress_fee_multiplier"))
        if (
            development_timerange != development.development_timerange
            or development_stop != start
            or not math.isfinite(multiplier)
            or multiplier <= 1.0
            or (stop - start).days <= 0
            or plan.get("holdout_policy")
            != {
                "max_open_count": 1,
                "retry_after_open": False,
                "tune_after_result": False,
            }
        ):
            raise HoldoutRunError("BLOCKED_DATA", "Pilot Holdout contract mismatch")
        acquisition = pilot / "acquisition"
        provenance_bytes = _read_regular(
            acquisition / "retained-data-provenance.json",
            "acquisition provenance",
        )
        provenance = _json_bytes(provenance_bytes, "acquisition provenance")
        contract = provenance.get("contract")
        source = provenance.get("source")
        local = provenance.get("local_only_files")
        if (
            not isinstance(contract, dict)
            or contract.get("development_timerange") != development_timerange
            or contract.get("holdout_timerange") != holdout_timerange
            or contract.get("timeframe") != "5m"
            or not isinstance(source, dict)
            or source.get("host") != "www.okx.com"
            or source.get("authentication") != "none"
            or not isinstance(source.get("pair"), str)
            or not isinstance(local, dict)
            or not local
        ):
            raise HoldoutRunError("BLOCKED_DATA", "acquisition Holdout contract mismatch")
        receipts = []
        for name, raw in local.items():
            relative = _safe_relative(name, "acquisition input")
            size, digest, role = _receipt_record(raw, f"acquisition input {name!r}")
            # Startup freezes the envelope and inode kind only.  The bytes are
            # first opened and hashed by _require_ready after explicit action.
            candidate = acquisition / relative
            info = candidate.stat(follow_symlinks=False)
            if candidate.is_symlink() or not stat.S_ISREG(info.st_mode):
                raise HoldoutRunError("BLOCKED_DATA", "acquisition input is unsafe")
            receipts.append((relative.as_posix(), size, digest, role))
        config_bytes = _read_regular(acquisition / "config.json", "Pilot config")
        runner_bytes = _read_regular(DEFAULT_RUNNER, "backtest runner", 2 * 1024 * 1024)
        return FrozenHoldoutCapability(
            status="READY",
            reason="one-shot Holdout inputs are frozen and remain sealed until authorization",
            development=development,
            pilot_root=pilot,
            freqtrade_python=development.freqtrade_python,
            freqtrade_source=development.freqtrade_source,
            plan_sha256=hashlib.sha256(plan_bytes).hexdigest(),
            acquisition_provenance_sha256=hashlib.sha256(provenance_bytes).hexdigest(),
            config_sha256=hashlib.sha256(config_bytes).hexdigest(),
            runner_sha256=hashlib.sha256(runner_bytes).hexdigest(),
            development_timerange=str(development_timerange),
            holdout_timerange=str(holdout_timerange),
            stress_fee_multiplier=multiplier,
            pair=str(source["pair"]),
            local_receipts=tuple(sorted(receipts)),
        )
    except (HoldoutRunError, OSError, TypeError, ValueError, OverflowError) as exc:
        message = exc.message if isinstance(exc, HoldoutRunError) else "Holdout capability could not be frozen"
        return FrozenHoldoutCapability(
            status="BLOCKED_DATA", reason=message, development=development
        )


def _require_ready(capability: FrozenHoldoutCapability) -> None:
    """Open and hash the frozen later-phase files only after explicit action."""
    if (
        capability.status != "READY"
        or capability.development is None
        or capability.pilot_root is None
        or capability.holdout_timerange is None
        or capability.stress_fee_multiplier is None
    ):
        raise HoldoutRunError("BLOCKED_DATA", capability.reason)
    try:
        _require_development_ready(capability.development)
        pilot = capability.pilot_root
        acquisition = pilot / "acquisition"
        fixed = (
            hashlib.sha256(_read_regular(pilot / "pilot-spec.json", "Pilot spec")).hexdigest(),
            hashlib.sha256(
                _read_regular(
                    acquisition / "retained-data-provenance.json",
                    "acquisition provenance",
                )
            ).hexdigest(),
            hashlib.sha256(_read_regular(acquisition / "config.json", "Pilot config")).hexdigest(),
            hashlib.sha256(_read_regular(DEFAULT_RUNNER, "backtest runner")).hexdigest(),
        )
        if fixed != (
            capability.plan_sha256,
            capability.acquisition_provenance_sha256,
            capability.config_sha256,
            capability.runner_sha256,
        ):
            raise HoldoutRunError("BLOCKED_DATA", "startup-frozen Holdout contract changed")
        for name, size, digest, _role in capability.local_receipts:
            data = _read_regular(acquisition / _safe_relative(name, "acquisition input"), "Holdout input")
            if len(data) != size or hashlib.sha256(data).hexdigest() != digest:
                raise HoldoutRunError("BLOCKED_DATA", "startup-frozen Holdout input changed")
    except HoldoutRunError:
        raise
    except (OSError, TypeError, ValueError) as exc:
        raise HoldoutRunError("BLOCKED_DATA", "startup-frozen Holdout inputs changed") from exc


def _canonical(value: Any) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def _json_object(raw: Any, label: str) -> dict[str, Any]:
    if not isinstance(raw, str):
        raise HoldoutRunError("run_state_conflict", f"{label} is invalid")
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError, RecursionError) as exc:
        raise HoldoutRunError("run_state_conflict", f"{label} is invalid") from exc
    if not isinstance(value, dict):
        raise HoldoutRunError("run_state_conflict", f"{label} is invalid")
    return value


def _schema_v1(connection: sqlite3.Connection) -> None:
    version = connection.execute("PRAGMA user_version").fetchone()
    tables = {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_schema "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }
    if version is None or int(version[0]) != 1 or tables != _BUSINESS_TABLES:
        raise HoldoutRunError(
            "BLOCKED_DATA", "database must remain the exact six-table schema v1"
        )


def _write_exclusive(path: Path, data: bytes, mode: int = 0o400) -> None:
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        mode,
    )
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(descriptor)


def _copy_frozen_input(source: Path, destination: Path, size: int, digest: str) -> None:
    data = _read_regular(source, "Holdout input")
    if len(data) != size or hashlib.sha256(data).hexdigest() != digest:
        raise HoldoutRunError("BLOCKED_DATA", "startup-frozen Holdout input changed")
    destination.parent.mkdir(parents=True, exist_ok=True)
    _write_exclusive(destination, data)


def _candidate_profile_row(
    connection: sqlite3.Connection,
    candidate_id: str,
    capability: FrozenHoldoutCapability,
) -> sqlite3.Row:
    try:
        candidate = _bound_candidate(connection, candidate_id)
        assert capability.development is not None
        _profile_gate(candidate, capability.development)
    except DevelopmentRunError as exc:
        raise HoldoutRunError(exc.code, exc.message) from exc
    row = connection.execute(
        """
        SELECT c.id, c.generation_run_id, c.display_name, c.class_name,
               c.strategy_family, c.idea, c.expected_failure_mode,
               c.code_text, c.code_sha256,
               gr.research_profile_id,
               rp.name AS profile_name, rp.history_start_date, rp.smoke_days,
               rp.holdout_days, rp.stress_fee_multiplier,
               rp.max_drawdown_pct, rp.min_development_trades,
               rp.min_holdout_trades, rp.min_profit_factor,
               rp.taker_fee_rate
        FROM candidates AS c
        JOIN generation_runs AS gr ON gr.id=c.generation_run_id
        JOIN research_profiles AS rp ON rp.id=gr.research_profile_id
        WHERE c.id=?
        """,
        (candidate_id,),
    ).fetchone()
    if row is None:
        raise HoldoutRunError("run_not_eligible", "approved Candidate is unavailable")
    return row


def _materialize_holdout_inputs(
    run_dir: Path,
    research_run_id: str,
    capability: FrozenHoldoutCapability,
    row: sqlite3.Row,
    development: ParsedBacktestArtifact,
) -> Tuple[Path, dict[str, Any]]:
    """Create a SHA-bound full acquisition view after the one explicit action."""
    assert capability.pilot_root is not None
    assert capability.development_timerange is not None
    assert capability.holdout_timerange is not None
    assert capability.stress_fee_multiplier is not None
    acquisition = capability.pilot_root / "acquisition"
    staging = run_dir / ".holdout-input-preparing"
    final = run_dir / "holdout-input"
    if staging.exists() or final.exists() or final.is_symlink():
        raise HoldoutRunError(
            "already_authorized", "Holdout input materialization was already consumed"
        )
    staging.mkdir(mode=0o700)
    try:
        strategy_relative = f"strategies/{row['class_name']}.py"
        strategy_bytes = str(row["code_text"]).encode("utf-8")
        if hashlib.sha256(strategy_bytes).hexdigest() != row["code_sha256"]:
            raise HoldoutRunError("run_not_eligible", "Candidate source receipt drifted")
        (staging / "strategies").mkdir()
        _write_exclusive(staging / strategy_relative, strategy_bytes)

        source_config = _read_regular(acquisition / "config.json", "Pilot config")
        if hashlib.sha256(source_config).hexdigest() != capability.config_sha256:
            raise HoldoutRunError("BLOCKED_DATA", "startup-frozen Pilot config changed")
        source_config_value = _json_bytes(source_config, "Pilot config")
        config = dict(source_config_value)
        config["strategy"] = row["class_name"]
        config_bytes = _canonical_bytes(config)
        _write_exclusive(staging / "config.json", config_bytes)

        local_records: dict[str, dict[str, Any]] = {}
        for name, size, digest, frozen_role in capability.local_receipts:
            relative = _safe_relative(name, "Holdout input")
            role = frozen_role
            if relative.as_posix() == "market_snapshot.json":
                role = "market_snapshot"
            elif relative.as_posix() == "isolated_tiers_snapshot.json":
                role = "leverage_tiers"
            _copy_frozen_input(acquisition / relative, staging / relative, size, digest)
            record: dict[str, Any] = {"bytes": size, "sha256": digest}
            if role is not None:
                record["role"] = role
            local_records[relative.as_posix()] = record

        research_spec = {
            "schema": RESEARCH_SPEC_SCHEMA,
            "profile": {
                "name": row["profile_name"],
                "history_start_date": row["history_start_date"],
                "smoke_days": row["smoke_days"],
                "holdout_days": row["holdout_days"],
                "stress_fee_multiplier": row["stress_fee_multiplier"],
                "max_drawdown_pct": row["max_drawdown_pct"],
                "min_development_trades": row["min_development_trades"],
                "min_holdout_trades": row["min_holdout_trades"],
                "min_profit_factor": row["min_profit_factor"],
            },
            "candidate": {
                "display_name": row["display_name"],
                "class_name": row["class_name"],
                "strategy_family": row["strategy_family"],
                "idea": row["idea"],
                "expected_failure_mode": row["expected_failure_mode"],
                "metadata": {
                    "candidate_id": row["id"],
                    "generation_run_id": row["generation_run_id"],
                    "research_profile_id": row["research_profile_id"],
                    "code_sha256": row["code_sha256"],
                },
            },
        }
        spec_bytes = _canonical_bytes(research_spec)
        _write_exclusive(staging / "research-spec.json", spec_bytes)

        tracked = {
            "config.json": {
                "bytes": len(config_bytes),
                "sha256": hashlib.sha256(config_bytes).hexdigest(),
            },
            "research-spec.json": {
                "bytes": len(spec_bytes),
                "sha256": hashlib.sha256(spec_bytes).hexdigest(),
            },
            strategy_relative: {
                "bytes": len(strategy_bytes),
                "sha256": row["code_sha256"],
            },
        }
        provenance = {
            "schema": "freqtrade-lab-retained-okx-data-v1",
            "portable_retained_fixture": "BLOCKED_LICENSE",
            "source": {
                "host": "www.okx.com",
                "authentication": "none",
                "pair": capability.pair,
            },
            "freqtrade": {
                "version": SUPPORTED_FREQTRADE_VERSION,
                "tag": SUPPORTED_FREQTRADE_VERSION,
                "commit": "52bc96f4480b1a0da6a9b455bd00b17fbb6786a5",
                "dependencies": dict(SUPPORTED_DEPENDENCIES),
            },
            "contract": {
                "config": "config.json",
                "strategy": strategy_relative,
                "data_dir": "data/okx",
                "market_snapshot": "market_snapshot.json",
                "leverage_tiers": "isolated_tiers_snapshot.json",
                "development_timerange": capability.development_timerange,
                "holdout_timerange": capability.holdout_timerange,
                "timeframe": "5m",
            },
            "files": tracked,
            "local_only_files": dict(sorted(local_records.items())),
        }
        provenance_bytes = _canonical_bytes(provenance)
        _write_exclusive(staging / "retained-data-provenance.json", provenance_bytes)

        # Reuse the existing producer's strict validators before the DB action is consumed.
        try:
            _validate_config(config, str(row["class_name"]))
            _validate_research_spec(
                staging / "research-spec.json",
                str(row["class_name"]),
                capability.development_timerange,
                capability.holdout_timerange,
                float(capability.stress_fee_multiplier),
            )
            _validate_data_provenance(
                staging / "retained-data-provenance.json",
                (staging / "config.json").resolve(strict=True),
                (staging / "research-spec.json").resolve(strict=True),
                (staging / strategy_relative).resolve(strict=True),
                (staging / "data" / "okx").resolve(strict=True),
                (staging / "market_snapshot.json").resolve(strict=True),
                (staging / "isolated_tiers_snapshot.json").resolve(strict=True),
                (str(capability.pair),),
                capability.development_timerange,
                capability.holdout_timerange,
            )
        except (ResearchCandidateError, OSError, RuntimeError, ValueError) as exc:
            raise HoldoutRunError(
                "BLOCKED_DATA", "materialized Holdout inputs failed validation"
            ) from exc

        input_hashes = {
            path.relative_to(staging).as_posix(): hashlib.sha256(
                _read_regular(path, "materialized Holdout input")
            ).hexdigest()
            for path in sorted(staging.rglob("*"))
            if path.is_file()
        }
        manifest = {
            "schema": HOLDOUT_INPUT_SCHEMA,
            "research_run_id": research_run_id,
            "candidate_id": row["id"],
            "class_name": row["class_name"],
            "code_sha256": row["code_sha256"],
            "research_profile_id": row["research_profile_id"],
            "development_timerange": capability.development_timerange,
            "holdout_timerange": capability.holdout_timerange,
            "stress_fee_multiplier": capability.stress_fee_multiplier,
            "development_artifact": {
                "archive_sha256": development.archive_sha256,
                "metadata_sha256": development.metadata_sha256,
                "provenance_sha256": development.provenance_sha256,
            },
            "input_hashes": input_hashes,
        }
        manifest_bytes = _canonical_bytes(manifest)
        _write_exclusive(staging / "manifest.json", manifest_bytes)
        manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
        os.rename(staging, final)
        return final, {"manifest_sha256": manifest_sha, "manifest": manifest}
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def _timestamp(value: Optional[str] = None) -> str:
    if value is not None:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (AttributeError, ValueError) as exc:
            raise HoldoutRunError("BLOCKED_DATA", "authorization timestamp is invalid") from exc
        if parsed.utcoffset() != timedelta(0):
            raise HoldoutRunError("BLOCKED_DATA", "authorization timestamp is invalid")
        return value
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def _timerange(value: Any) -> Tuple[datetime, datetime]:
    if not isinstance(value, str):
        raise HoldoutRunError("BLOCKED_DATA", "Holdout timerange is invalid")
    parts = value.split("-", 1)
    try:
        if len(parts) != 2 or any(len(part) != 8 for part in parts):
            raise ValueError
        start, stop = (
            datetime.strptime(part, "%Y%m%d").replace(tzinfo=timezone.utc)
            for part in parts
        )
    except ValueError as exc:
        raise HoldoutRunError("BLOCKED_DATA", "Holdout timerange is invalid") from exc
    if stop <= start:
        raise HoldoutRunError("BLOCKED_DATA", "Holdout timerange is invalid")
    return start, stop


def _authorization_receipt(
    raw: Mapping[str, Any],
    *,
    snapshot: Mapping[str, Any],
    profile_id: str,
    candidate_sha256: str,
    stress_multiplier: float,
    holdout_days: int,
) -> dict[str, Any]:
    required = {
        "schema",
        "action",
        "authorized_at",
        "candidate_code_sha256",
        "research_profile_id",
        "pilot_spec_sha256",
        "data_provenance_sha256",
        "freqtrade_source_tree",
        "freqtrade_python_identity",
        "runner_sha256",
        "holdout_timerange",
        "stress_fee_multiplier",
        "input_manifest_sha256",
    }
    if not isinstance(raw, dict) or set(raw) != required:
        raise HoldoutRunError("BLOCKED_DATA", "Holdout authorization receipt is invalid")
    for name in (
        "candidate_code_sha256",
        "pilot_spec_sha256",
        "data_provenance_sha256",
        "runner_sha256",
        "input_manifest_sha256",
    ):
        if not isinstance(raw[name], str) or _SHA256.fullmatch(raw[name]) is None:
            raise HoldoutRunError("BLOCKED_DATA", "Holdout authorization receipt is invalid")
    if (
        not isinstance(raw["freqtrade_source_tree"], str)
        or _GIT_OBJECT_ID.fullmatch(raw["freqtrade_source_tree"]) is None
    ):
        raise HoldoutRunError("BLOCKED_DATA", "Holdout authorization receipt is invalid")
    python_identity = raw["freqtrade_python_identity"]
    if (
        not isinstance(python_identity, list)
        or len(python_identity) != 4
        or any(isinstance(item, bool) or not isinstance(item, int) for item in python_identity)
    ):
        raise HoldoutRunError("BLOCKED_DATA", "Holdout authorization receipt is invalid")
    try:
        multiplier = float(raw["stress_fee_multiplier"])
    except (TypeError, ValueError, OverflowError) as exc:
        raise HoldoutRunError("BLOCKED_DATA", "Holdout authorization receipt is invalid") from exc
    start, stop = _timerange(raw["holdout_timerange"])
    expected = (
        raw["schema"] == HOLDOUT_AUTHORIZATION_SCHEMA
        and raw["action"] == "AUTHORIZE_HOLDOUT"
        and raw["candidate_code_sha256"] == candidate_sha256
        and raw["research_profile_id"] == profile_id
        and raw["pilot_spec_sha256"] == snapshot.get("pilot_spec_sha256")
        and raw["data_provenance_sha256"] == snapshot.get("source_provenance_sha256")
        and raw["freqtrade_source_tree"] == snapshot.get("freqtrade_source_tree")
        and python_identity == snapshot.get("freqtrade_python_identity")
        and raw["runner_sha256"] == snapshot.get("runner_sha256")
        and math.isfinite(multiplier)
        and math.isclose(multiplier, stress_multiplier, rel_tol=0.0, abs_tol=1e-15)
        and (stop - start).days == holdout_days
    )
    _timestamp(raw["authorized_at"] if isinstance(raw["authorized_at"], str) else None)
    if not expected:
        raise HoldoutRunError("BLOCKED_DATA", "Holdout authorization receipt drifted")
    return dict(raw)


def _parsed_development(
    row: sqlite3.Row,
    run_dir: Optional[PathLike] = None,
    class_name: Optional[str] = None,
) -> ParsedBacktestArtifact:
    metrics = _json_object(row["metrics_json"], "Development metrics")
    artifact = metrics.get("artifact")
    provenance_sha256 = artifact.get("provenance_sha256") if isinstance(artifact, dict) else None
    archive_path = row["result_archive_path"]
    if (
        not isinstance(archive_path, str)
        or not isinstance(provenance_sha256, str)
        or _SHA256.fullmatch(provenance_sha256) is None
    ):
        raise HoldoutRunError(
            "run_state_conflict", "Development Artifact binding is incomplete"
        )
    path = Path(archive_path)
    try:
        root_value = run_dir if run_dir is not None else row["run_dir"]
        controlled_root = (Path(str(root_value)) / "development-evidence").resolve(strict=True)
        resolved_archive = path.resolve(strict=True)
        if resolved_archive.parent != controlled_root:
            raise OSError("Development Artifact is outside its controlled root")
        parsed = parse_backtest_artifact(
            controlled_root,
            resolved_archive.name,
            class_name if class_name is not None else str(row["class_name"]),
            SUPPORTED_FREQTRADE_VERSION,
            provenance_sha256,
        )
    except (ArtifactImportError, OSError, RuntimeError, ValueError) as exc:
        raise HoldoutRunError(
            "run_state_conflict", "Development Artifact no longer matches its frozen receipt"
        ) from exc
    expected = execution_result_values(parsed)
    for name, value in expected.items():
        if name == "result_archive_path":
            if Path(str(value)) != path:
                raise HoldoutRunError(
                    "run_state_conflict", "Development Artifact path drifted"
                )
        elif row[name] != value:
            raise HoldoutRunError(
                "run_state_conflict", "Development metrics drifted from its Artifact"
            )
    return parsed


def _eligible_row(
    connection: sqlite3.Connection,
    research_run_id: str,
    *,
    parse_artifact: bool,
) -> Tuple[sqlite3.Row, Optional[ParsedBacktestArtifact], dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT rr.*, be.id AS execution_id, be.scenario, be.status AS execution_status,
               be.sequence, be.result_archive_path, be.return_code,
               be.total_trades, be.profit_pct, be.max_drawdown_pct,
               be.win_rate, be.profit_factor, be.sharpe, be.sortino, be.calmar,
               be.long_profit_pct, be.short_profit_pct, be.metrics_json,
               be.scenario_passed, be.error_message AS execution_error,
               be.finished_at AS execution_finished_at,
               c.class_name, c.code_text, c.code_sha256,
               c.generation_run_id, gr.research_profile_id AS generation_profile_id,
               gr.status AS generation_status,
               rp.holdout_days, rp.stress_fee_multiplier, rp.taker_fee_rate
        FROM research_runs AS rr
        JOIN backtest_executions AS be ON be.research_run_id=rr.id
        JOIN candidates AS c ON c.id=rr.candidate_id
        JOIN generation_runs AS gr ON gr.id=c.generation_run_id
        JOIN research_profiles AS rp ON rp.id=rr.research_profile_id
        WHERE rr.id=? ORDER BY be.sequence, be.id
        """,
        (research_run_id,),
    ).fetchall()
    if not rows:
        raise HoldoutRunError("run_not_found", "ResearchRun not found")
    if len(rows) != 1:
        raise HoldoutRunError("already_authorized", "Holdout authorization is one-shot")
    row = rows[0]
    snapshot = _json_object(row["input_snapshot_json"], "Development snapshot")
    checks = _json_object(row["checks_json"], "Development checks")
    if (
        row["pipeline_version"] != DEVELOPMENT_PIPELINE_VERSION
        or row["freqtrade_version"] != SUPPORTED_FREQTRADE_VERSION
        or row["status"] != "PENDING"
        or row["stage"] != "PENDING"
        or row["verdict"] is not None
        or row["finished_at"] is not None
        or row["scenario"] != "DEVELOPMENT"
        or row["sequence"] != 1
        or row["execution_status"] != "SUCCEEDED"
        or row["scenario_passed"] != 1
        or row["return_code"] != 0
        or row["execution_finished_at"] is None
        or row["execution_error"] is not None
        or checks != _ORIGINAL_CHECKS
        or snapshot.get("schema") != DEVELOPMENT_CONTRACT_SCHEMA
        or snapshot.get("pipeline_version") != DEVELOPMENT_PIPELINE_VERSION
        or snapshot.get("scenario") != "DEVELOPMENT"
        or snapshot.get("gate")
        != {"version": DEVELOPMENT_GATE_VERSION, **EXPECTED_GATE}
        or snapshot.get("holdout") != "SEALED_UNREAD"
        or snapshot.get("holdout_stress") != "SEALED_UNREAD"
        or "holdout_authorization" in snapshot
        or snapshot.get("candidate_id") != row["candidate_id"]
        or snapshot.get("candidate_code_sha256") != row["code_sha256"]
        or snapshot.get("research_profile_id") != row["research_profile_id"]
        or snapshot.get("generation_run_id") != row["generation_run_id"]
        or row["generation_profile_id"] != row["research_profile_id"]
        or row["generation_status"] != "COMPLETED"
        or not isinstance(row["code_text"], str)
        or __import__("hashlib").sha256(row["code_text"].encode("utf-8")).hexdigest()
        != row["code_sha256"]
        or row["total_trades"] is None
        or row["total_trades"] < EXPECTED_GATE["minimum_trades"]
        or row["profit_pct"] is None
        or row["profit_pct"] < EXPECTED_GATE["minimum_profit_pct"]
        or row["profit_factor"] is None
        or row["profit_factor"] < EXPECTED_GATE["minimum_profit_factor"]
        or row["max_drawdown_pct"] is None
        or row["max_drawdown_pct"] > EXPECTED_GATE["maximum_drawdown_pct"]
        or connection.execute(
            "SELECT COUNT(*) FROM releases WHERE research_run_id=?",
            (research_run_id,),
        ).fetchone()[0]
        != 0
    ):
        raise HoldoutRunError(
            "run_not_eligible", "ResearchRun is not eligible for Holdout authorization"
        )
    parsed = _parsed_development(row) if parse_artifact else None
    return row, parsed, snapshot


def prepare_holdout_continuation(
    database_path: PathLike,
    run_dir: PathLike,
    research_run_id: str,
    capability: FrozenHoldoutCapability,
    *,
    now: Optional[str] = None,
) -> PreparedHoldoutContinuation:
    """Validate eligibility, materialize once, then consume authorization."""
    timestamp = _timestamp(now)
    if (
        capability.status != "READY"
        or capability.development is None
        or capability.pilot_root is None
        or capability.holdout_timerange is None
        or capability.stress_fee_multiplier is None
    ):
        raise HoldoutRunError("BLOCKED_DATA", capability.reason)
    try:
        directory = Path(run_dir).resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as exc:
        raise HoldoutRunError("run_state_conflict", "ResearchRun directory is unavailable") from exc
    if directory.name != research_run_id:
        raise HoldoutRunError("run_state_conflict", "ResearchRun directory identity mismatch")
    if _residual_authorization(directory):
        raise HoldoutRunError(
            "already_authorized", "Holdout authorization was already attempted"
        )

    with closing(get_connection(database_path, must_exist=True)) as connection:
        connection.execute("BEGIN")
        _schema_v1(connection)
        row, parsed, snapshot = _eligible_row(
            connection, research_run_id, parse_artifact=True
        )
        materialization_row = _candidate_profile_row(
            connection, str(row["candidate_id"]), capability
        )
        holdout_start, holdout_stop = _timerange(capability.holdout_timerange)
        expected_python_identity = list(
            capability.development.python_identity
            if capability.development is not None
            and capability.development.python_identity is not None
            else ()
        )
        if (
            snapshot.get("pilot_spec_sha256") != capability.plan_sha256
            or snapshot.get("source_provenance_sha256")
            != capability.acquisition_provenance_sha256
            or snapshot.get("config_sha256") != capability.config_sha256
            or snapshot.get("runner_sha256") != capability.runner_sha256
            or snapshot.get("timerange") != capability.development_timerange
            or snapshot.get("freqtrade_source_tree") != SUPPORTED_FREQTRADE_TREE
            or snapshot.get("freqtrade_python_identity")
            != expected_python_identity
            or int(materialization_row["holdout_days"])
            != (holdout_stop - holdout_start).days
            or not math.isclose(
                float(materialization_row["stress_fee_multiplier"]),
                float(capability.stress_fee_multiplier),
                rel_tol=0.0,
                abs_tol=1e-15,
            )
        ):
            connection.rollback()
            raise HoldoutRunError(
                "run_not_eligible",
                "ResearchRun does not match the startup-frozen Holdout contract",
            )
        try:
            database_run_dir = Path(str(row["run_dir"])).resolve(strict=True)
        except (OSError, RuntimeError, ValueError) as exc:
            connection.rollback()
            raise HoldoutRunError("run_state_conflict", "ResearchRun directory drifted") from exc
        if database_run_dir != directory:
            connection.rollback()
            raise HoldoutRunError("run_state_conflict", "ResearchRun directory drifted")
        connection.rollback()
    assert parsed is not None

    # Only an eligible, never-attempted Run may open and hash the startup-frozen
    # retained inputs.  The later write transaction repeats all DB checks.
    _require_ready(capability)
    try:
        _write_exclusive(
            directory / HOLDOUT_ATTEMPT_NAME,
            _canonical_bytes(
                {
                    "schema": "freqtrade-lab-holdout-attempt-v1",
                    "action": "AUTHORIZE_HOLDOUT",
                    "research_run_id": research_run_id,
                    "authorized_at": timestamp,
                }
            ),
        )
    except FileExistsError as exc:
        raise HoldoutRunError(
            "already_authorized", "Holdout authorization was already attempted"
        ) from exc
    except OSError as exc:
        raise HoldoutRunError(
            "authorization_failed", "Holdout attempt receipt could not be persisted"
        ) from exc
    # This marker is deliberately retained if materialization fails.  The user
    # action is one-shot even when no later DB rows can be created.
    _input_root, materialized = _materialize_holdout_inputs(
        directory, research_run_id, capability, materialization_row, parsed
    )
    manifest_sha256 = str(materialized["manifest_sha256"])
    receipt = {
        "schema": HOLDOUT_AUTHORIZATION_SCHEMA,
        "action": "AUTHORIZE_HOLDOUT",
        "authorized_at": timestamp,
        "candidate_code_sha256": row["code_sha256"],
        "research_profile_id": row["research_profile_id"],
        "pilot_spec_sha256": capability.plan_sha256,
        "data_provenance_sha256": capability.acquisition_provenance_sha256,
        "freqtrade_source_tree": snapshot.get("freqtrade_source_tree"),
        "freqtrade_python_identity": snapshot.get("freqtrade_python_identity"),
        "runner_sha256": capability.runner_sha256,
        "holdout_timerange": capability.holdout_timerange,
        "stress_fee_multiplier": capability.stress_fee_multiplier,
        "input_manifest_sha256": manifest_sha256,
    }
    input_root = directory / "holdout-input"
    _write_exclusive(
        input_root / "authorization.json",
        _canonical_bytes(receipt),
    )
    for child in sorted(
        (path for path in input_root.rglob("*") if path.is_dir()),
        key=lambda path: len(path.parts),
        reverse=True,
    ):
        child.chmod(0o500)
    input_root.chmod(0o500)
    # Once the O_EXCL authorization receipt exists, every subsequent failure
    # is a consumed/interrupted attempt.  Preserve the Git-external evidence so
    # public state and restart recovery cannot authorize it a second time.
    return _authorize_holdout_run(
        database_path, research_run_id, receipt, now=timestamp
    )


def _authorize_holdout_run(
    database_path: PathLike,
    research_run_id: str,
    receipt: Mapping[str, Any],
    *,
    now: Optional[str] = None,
) -> PreparedHoldoutContinuation:
    """Atomically consume the one-shot authorization and create two control rows."""
    timestamp = _timestamp(now)
    with closing(get_connection(database_path, must_exist=True)) as connection:
        try:
            connection.execute("BEGIN IMMEDIATE")
            _schema_v1(connection)
            row, _, snapshot = _eligible_row(
                connection, research_run_id, parse_artifact=True
            )
            authorization = _authorization_receipt(
                receipt,
                snapshot=snapshot,
                profile_id=str(row["research_profile_id"]),
                candidate_sha256=str(row["code_sha256"]),
                stress_multiplier=float(row["stress_fee_multiplier"]),
                holdout_days=int(row["holdout_days"]),
            )
            run_dir = Path(str(row["run_dir"]))
            start, stop = _timerange(authorization["holdout_timerange"])
            end = stop - timedelta(minutes=5)
            holdout_id, stress_id = str(uuid4()), str(uuid4())
            command_base = {
                "schema": HOLDOUT_COMMAND_SCHEMA,
                "timerange": authorization["holdout_timerange"],
                "runner_sha256": authorization["runner_sha256"],
                "browser_overrides": False,
            }
            for execution_id, scenario, sequence, multiplier in (
                (holdout_id, "HOLDOUT", 2, 1.0),
                (
                    stress_id,
                    "HOLDOUT_STRESS",
                    3,
                    float(row["stress_fee_multiplier"]),
                ),
            ):
                command = {**command_base, "scenario": scenario}
                connection.execute(
                    """
                    INSERT INTO backtest_executions (
                        id, research_run_id, scenario, status, sequence,
                        timerange_start, timerange_end, timeframe, detail_timeframe,
                        fee_rate, fee_multiplier, command_json, config_path,
                        strategy_path, metrics_json, created_at, started_at
                    ) VALUES (?, ?, ?, 'PENDING', ?, ?, ?, '5m', NULL,
                              ?, ?, ?, ?, ?, '{}', ?, ?)
                    """,
                    (
                        execution_id,
                        research_run_id,
                        scenario,
                        sequence,
                        start.isoformat().replace("+00:00", "Z"),
                        end.isoformat().replace("+00:00", "Z"),
                        float(row["taker_fee_rate"]) * multiplier,
                        multiplier,
                        _canonical(command),
                        str(run_dir / "holdout-input" / "config.json"),
                        str(
                            run_dir
                            / "holdout-input"
                            / "strategies"
                            / f"{row['class_name']}.py"
                        ),
                        timestamp,
                        timestamp,
                    ),
                )
            snapshot = dict(snapshot)
            snapshot["holdout_authorization"] = authorization
            checks = {
                **_ORIGINAL_CHECKS,
                "authorization": "AUTHORIZED",
                "next_phase": "HOLDOUT_IN_PROGRESS",
                "holdout": "PENDING",
                "holdout_stress": "PENDING",
                "judge": "NOT_RUN",
            }
            update = connection.execute(
                """
                UPDATE research_runs
                SET status='RUNNING', stage='HOLDOUT_BACKTEST', verdict=NULL,
                    input_snapshot_json=?, checks_json=?, error_stage=NULL,
                    error_message=NULL, finished_at=NULL
                WHERE id=? AND status='PENDING' AND stage='PENDING'
                  AND verdict IS NULL
                """,
                (_canonical(snapshot), _canonical(checks), research_run_id),
            )
            if update.rowcount != 1:
                raise HoldoutRunError(
                    "run_state_conflict", "ResearchRun changed during authorization"
                )
            connection.commit()
        except HoldoutRunError:
            if connection.in_transaction:
                connection.rollback()
            raise
        except (sqlite3.Error, OSError, TypeError, ValueError, OverflowError) as exc:
            if connection.in_transaction:
                connection.rollback()
            raise HoldoutRunError(
                "authorization_failed", "Holdout authorization could not be persisted"
            ) from exc
    return PreparedHoldoutContinuation(
        research_run_id=research_run_id,
        candidate_id=str(row["candidate_id"]),
        run_dir=run_dir,
        holdout_execution_id=holdout_id,
        stress_execution_id=stress_id,
    )


def _clean_later_execution(row: sqlite3.Row) -> None:
    nullable = (
        "result_archive_path",
        "stdout_path",
        "stderr_path",
        "return_code",
        "total_trades",
        "profit_pct",
        "max_drawdown_pct",
        "win_rate",
        "profit_factor",
        "sharpe",
        "sortino",
        "calmar",
        "long_profit_pct",
        "short_profit_pct",
        "scenario_passed",
        "error_message",
        "finished_at",
    )
    if (
        row["status"] != "PENDING"
        or any(row[name] is not None for name in nullable)
        or _json_object(row["metrics_json"], "later execution metrics") != {}
    ):
        raise HoldoutRunError(
            "run_state_conflict", "later execution already contains result state"
        )


def _same_number(left: Any, right: Any, *, fee: bool = False) -> bool:
    try:
        return math.isclose(
            float(left),
            float(right),
            rel_tol=0.0,
            abs_tol=1e-15 if fee else 1e-12,
        )
    except (TypeError, ValueError, OverflowError):
        return False


def _require_execution_contract(row: sqlite3.Row, parsed: ParsedBacktestArtifact) -> None:
    if (
        row["timerange_start"] != parsed.backtest_start
        or row["timerange_end"] != parsed.backtest_end
        or row["timeframe"] != parsed.timeframe
        or row["detail_timeframe"] != parsed.detail_timeframe
        or not _same_number(row["fee_rate"], parsed.configured_fee, fee=True)
    ):
        raise HoldoutRunError(
            "run_state_conflict", "later Artifact disagrees with its frozen execution"
        )


def _authorized_state(
    connection: sqlite3.Connection,
    research_run_id: str,
) -> Tuple[sqlite3.Row, Sequence[sqlite3.Row], dict[str, Any], dict[str, Any]]:
    run = connection.execute(
        """
        SELECT rr.*, c.*, gr.research_profile_id AS generation_profile_id,
               gr.source AS generation_source, gr.model AS generation_model,
               gr.returned_strategy_count AS generation_returned_strategy_count,
               gr.status AS generation_status, rp.*
        FROM research_runs AS rr
        JOIN candidates AS c ON c.id=rr.candidate_id
        JOIN generation_runs AS gr ON gr.id=c.generation_run_id
        JOIN research_profiles AS rp ON rp.id=rr.research_profile_id
        WHERE rr.id=?
        """,
        (research_run_id,),
    ).fetchone()
    if run is None:
        raise HoldoutRunError("run_not_found", "ResearchRun not found")
    executions = connection.execute(
        "SELECT * FROM backtest_executions WHERE research_run_id=? ORDER BY sequence, id",
        (research_run_id,),
    ).fetchall()
    snapshot = _json_object(run["input_snapshot_json"], "continuation snapshot")
    checks = _json_object(run["checks_json"], "continuation checks")
    authorization = snapshot.get("holdout_authorization")
    expected_checks = {
        **_ORIGINAL_CHECKS,
        "authorization": "AUTHORIZED",
        "next_phase": "HOLDOUT_IN_PROGRESS",
        "holdout": "PENDING",
        "holdout_stress": "PENDING",
        "judge": "NOT_RUN",
    }
    if (
        run["pipeline_version"] != DEVELOPMENT_PIPELINE_VERSION
        or run["status"] != "RUNNING"
        or run["stage"] != "HOLDOUT_BACKTEST"
        or run["verdict"] is not None
        or run["finished_at"] is not None
        or checks != expected_checks
        or not isinstance(authorization, dict)
        or len(executions) != 3
        or [row["scenario"] for row in executions] != list(BUNDLE_SCENARIOS)
        or [row["sequence"] for row in executions] != [1, 2, 3]
        or executions[0]["status"] != "SUCCEEDED"
        or executions[0]["scenario_passed"] != 1
        or connection.execute(
            "SELECT COUNT(*) FROM releases WHERE research_run_id=?",
            (research_run_id,),
        ).fetchone()[0]
        != 0
    ):
        raise HoldoutRunError(
            "run_state_conflict", "ResearchRun continuation state changed"
        )
    _clean_later_execution(executions[1])
    _clean_later_execution(executions[2])
    return run, executions, snapshot, checks


def holdout_worker_argv(
    database_path: PathLike,
    prepared: PreparedHoldoutContinuation,
    capability: FrozenHoldoutCapability,
    worker_python: PathLike,
) -> Tuple[str, ...]:
    """Return the fixed child argv; no browser-controlled field is accepted."""
    if capability.freqtrade_python is None or capability.freqtrade_source is None:
        raise HoldoutRunError("BLOCKED_DATA", "Holdout runtime is not configured")
    script = Path(__file__).resolve().parent.parent / "scripts" / "run_holdout_continuation.py"
    return (
        str(Path(worker_python).resolve(strict=True)),
        str(script.resolve(strict=True)),
        "--database",
        str(Path(database_path).resolve(strict=True)),
        "--run-dir",
        str(prepared.run_dir.resolve(strict=True)),
        "--research-run-id",
        prepared.research_run_id,
        "--freqtrade-python",
        str(capability.freqtrade_python),
        "--freqtrade-source",
        str(capability.freqtrade_source),
    )


def _load_holdout_input(
    run_dir: Path,
    research_run_id: str,
) -> Tuple[Mapping[str, Any], Mapping[str, Any]]:
    root = run_dir / "holdout-input"
    manifest_bytes = _read_regular(root / "manifest.json", "Holdout manifest")
    manifest = _json_bytes(manifest_bytes, "Holdout manifest")
    required = {
        "schema",
        "research_run_id",
        "candidate_id",
        "class_name",
        "code_sha256",
        "research_profile_id",
        "development_timerange",
        "holdout_timerange",
        "stress_fee_multiplier",
        "development_artifact",
        "input_hashes",
    }
    if (
        set(manifest) != required
        or manifest.get("schema") != HOLDOUT_INPUT_SCHEMA
        or manifest.get("research_run_id") != research_run_id
    ):
        raise HoldoutRunError("BLOCKED_DATA", "Holdout manifest identity mismatch")
    hashes = manifest.get("input_hashes")
    if not isinstance(hashes, dict) or not hashes:
        raise HoldoutRunError("BLOCKED_DATA", "Holdout manifest hashes are invalid")
    expected_files = {"manifest.json", "authorization.json"}
    for name, digest in hashes.items():
        if (
            not isinstance(name, str)
            or not isinstance(digest, str)
            or _SHA256.fullmatch(digest) is None
        ):
            raise HoldoutRunError("BLOCKED_DATA", "Holdout manifest hashes are invalid")
        relative = _safe_relative(name, "Holdout manifest input")
        # The retained market snapshot, leverage tiers, and candle files are
        # deliberately not opened here.  The existing runner consumes the
        # first scenario-open receipt before _validate_data_provenance reads
        # and hashes those bytes.  Non-market control inputs remain safe to
        # verify before the receipt.
        if relative.as_posix() not in {
            "market_snapshot.json",
            "isolated_tiers_snapshot.json",
        } and not relative.as_posix().startswith("data/okx/"):
            data = _read_regular(root / relative, f"Holdout input {name!r}")
            if hashlib.sha256(data).hexdigest() != digest:
                raise HoldoutRunError(
                    "BLOCKED_DATA", "materialized Holdout input changed"
                )
        expected_files.add(relative.as_posix())
    actual_files = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
    }
    if actual_files != expected_files:
        raise HoldoutRunError("BLOCKED_DATA", "Holdout input file set changed")
    authorization_bytes = _read_regular(
        root / "authorization.json", "Holdout authorization"
    )
    authorization = _json_bytes(authorization_bytes, "Holdout authorization")
    return manifest, authorization


def _child_runtime_paths(
    freqtrade_python: PathLike,
    freqtrade_source: PathLike,
    authorization: Mapping[str, Any],
) -> Tuple[Path, Path]:
    try:
        python = _resolve_executable(freqtrade_python)
        source = _resolve_directory(freqtrade_source, "Freqtrade source")
        expected_identity = authorization.get("freqtrade_python_identity")
        if not isinstance(expected_identity, list) or tuple(expected_identity) != _python_identity(python):
            raise HoldoutRunError("BLOCKED_DATA", "Freqtrade Python identity changed")
        _verify_python(python)
        return python, source
    except HoldoutRunError:
        raise
    except DevelopmentRunError as exc:
        raise HoldoutRunError(exc.code, exc.message) from exc


def execute_holdout_continuation(
    database_path: PathLike,
    run_dir: PathLike,
    research_run_id: str,
    freqtrade_python: PathLike,
    freqtrade_source: PathLike,
    command_runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> dict[str, Any]:
    """Run only HOLDOUT then HOLDOUT_STRESS; never run or import Development."""
    try:
        directory = Path(run_dir).resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as exc:
        raise HoldoutRunError("BLOCKED_DATA", "ResearchRun directory is unavailable") from exc
    if directory.name != research_run_id:
        raise HoldoutRunError("BLOCKED_DATA", "ResearchRun directory identity mismatch")
    manifest, authorization = _load_holdout_input(directory, research_run_id)
    manifest_sha = hashlib.sha256(
        _read_regular(directory / "holdout-input" / "manifest.json", "Holdout manifest")
    ).hexdigest()

    with closing(get_connection(database_path, read_only=True, must_exist=True)) as connection:
        connection.execute("BEGIN")
        run, executions, snapshot, _checks = _authorized_state(connection, research_run_id)
        frozen_authorization = snapshot.get("holdout_authorization")
        development = _parsed_development(
            executions[0], run["run_dir"], str(run["class_name"])
        )
        try:
            bound_run_dir = Path(str(run["run_dir"])).resolve(strict=True)
        except (OSError, RuntimeError, ValueError) as exc:
            connection.rollback()
            raise HoldoutRunError("BLOCKED_DATA", "ResearchRun directory drifted") from exc
        if (
            bound_run_dir != directory
            or frozen_authorization != authorization
            or authorization.get("input_manifest_sha256") != manifest_sha
            or manifest.get("candidate_id") != run["candidate_id"]
            or manifest.get("class_name") != run["class_name"]
            or manifest.get("code_sha256") != run["code_sha256"]
            or manifest.get("research_profile_id") != run["research_profile_id"]
            or manifest.get("development_artifact")
            != {
                "archive_sha256": development.archive_sha256,
                "metadata_sha256": development.metadata_sha256,
                "provenance_sha256": development.provenance_sha256,
            }
        ):
            connection.rollback()
            raise HoldoutRunError("BLOCKED_DATA", "Holdout manifest disagrees with database")
        connection.rollback()

    input_root = directory / "holdout-input"
    strategy = str(manifest["class_name"])
    strategy_file = input_root / "strategies" / f"{strategy}.py"
    strategy_bytes = _read_regular(strategy_file, "Candidate strategy", 256 * 1024)
    config_path = input_root / "config.json"
    spec_path = input_root / "research-spec.json"
    provenance_path = input_root / "retained-data-provenance.json"
    market_path = input_root / "market_snapshot.json"
    tiers_path = input_root / "isolated_tiers_snapshot.json"
    data_path = input_root / "data" / "okx"
    base_config = _json_bytes(_read_regular(config_path, "Holdout config"), "Holdout config")
    try:
        base_fee, pairs = _validate_config(base_config, strategy)
        _validate_research_spec(
            spec_path,
            strategy,
            str(manifest["development_timerange"]),
            str(manifest["holdout_timerange"]),
            float(manifest["stress_fee_multiplier"]),
        )
        provenance_bytes = _read_regular(
            provenance_path, "Holdout retained-data provenance"
        )
        provenance = _json_bytes(provenance_bytes, "Holdout retained-data provenance")
        provenance_sha = hashlib.sha256(provenance_bytes).hexdigest()
    except (ResearchCandidateError, OSError, RuntimeError, TypeError, ValueError) as exc:
        raise HoldoutRunError("BLOCKED_DATA", "Holdout inputs failed child validation") from exc

    python, source = _child_runtime_paths(
        freqtrade_python, freqtrade_source, authorization
    )
    runner_bytes = _read_regular(DEFAULT_RUNNER, "backtest runner", 2 * 1024 * 1024)
    runner_sha = hashlib.sha256(runner_bytes).hexdigest()
    if runner_sha != authorization.get("runner_sha256"):
        raise HoldoutRunError("BLOCKED_DATA", "backtest runner changed")
    producer_path = Path(__file__).resolve(strict=True)
    producer_bytes = _read_regular(producer_path, "Holdout producer", 2 * 1024 * 1024)
    implementation_receipts = {
        "producer": {
            "bytes": len(producer_bytes),
            "sha256": hashlib.sha256(producer_bytes).hexdigest(),
        },
        "runner": {"bytes": len(runner_bytes), "sha256": runner_sha},
    }

    runtime = directory / "holdout-runtime"
    evidence = directory / "holdout-evidence"
    receipts = directory / "holdout-receipts"
    if any(path.exists() or path.is_symlink() for path in (runtime, evidence, receipts)):
        raise HoldoutRunError("already_authorized", "Holdout continuation cannot be rerun")
    runtime.mkdir(mode=0o700)
    evidence.mkdir(mode=0o700)
    receipts.mkdir(mode=0o700)
    try:
        real_execution = command_runner is subprocess.run
        execution_source = source
        source_tree_sha = "0" * 64
        network_policy = "test command runner; network isolation not attested"
        if real_execution:
            execution_source = runtime / "freqtrade-source"
            source_tree_sha = _prepare_freqtrade_source_snapshot(
                source,
                execution_source,
                runtime / "git-home",
                DEFAULT_SANDBOX_EXEC,
            )
            network_policy = (
                "deny-by-default /usr/bin/sandbox-exec profile with explicit "
                "read/write/process allowlists and network denied"
            )
        produced = []
        scenario_views: dict[str, Any] = {}
        expected_receipts: Optional[Mapping[str, Any]] = None
        for scenario, slug, multiplier, receipt_name in (
            ("HOLDOUT", "holdout-02", 1.0, "holdout-open.json"),
            (
                "HOLDOUT_STRESS",
                "holdout-stress-03",
                float(manifest["stress_fee_multiplier"]),
                "holdout-stress-open.json",
            ),
        ):
            scenario_root = runtime / slug
            raw = scenario_root / "raw"
            user_data = scenario_root / "user_data"
            home = scenario_root / "home"
            raw.mkdir(parents=True)
            user_data.mkdir()
            home.mkdir()
            (home / "tmp").mkdir()
            runtime_config = scenario_root / "config.json"
            runtime_config.write_bytes(
                _canonical_bytes(
                    _runtime_config(
                        base_config,
                        config_source=config_path,
                        data_dir=data_path,
                        user_data_dir=user_data,
                        strategy_path=strategy_file.parent,
                        strategy=strategy,
                        timerange=str(manifest["holdout_timerange"]),
                        fee=base_fee * multiplier,
                        export_dir=raw,
                    )
                )
            )
            open_receipt = receipts / receipt_name
            completed, summary, command_shape = _run_scenario(
                scenario=scenario,
                timerange=str(manifest["holdout_timerange"]),
                fee=base_fee * multiplier,
                python=python,
                source=execution_source,
                source_tree_sha256=source_tree_sha,
                runner_script=DEFAULT_RUNNER,
                runner_sha256=runner_sha,
                sandbox_exec=DEFAULT_SANDBOX_EXEC,
                config_path=runtime_config,
                data_dir=data_path,
                user_data_dir=user_data,
                strategy_path=strategy_file.parent,
                strategy_file=strategy_file,
                strategy_sha256=str(manifest["code_sha256"]),
                strategy=strategy,
                export_dir=raw,
                market_snapshot=market_path,
                leverage_tiers=tiers_path,
                data_provenance=provenance_path,
                home=home,
                command_runner=command_runner,
                scenario_open_receipt=open_receipt,
            )
            open_sha = _validate_scenario_open_receipt(
                open_receipt,
                scenario=scenario,
                timerange=str(manifest["holdout_timerange"]),
                strategy=strategy,
                strategy_sha256=str(manifest["code_sha256"]),
                data_provenance_sha256=provenance_sha,
            )
            if expected_receipts is None:
                # The runner has already consumed the one-shot open receipt before
                # this producer reads and hashes retained market files.
                (
                    provenance,
                    validated_provenance_sha,
                    expected_receipts,
                ) = _validate_data_provenance(
                    provenance_path,
                    config_path.resolve(strict=True),
                    spec_path.resolve(strict=True),
                    strategy_file.resolve(strict=True),
                    data_path.resolve(strict=True),
                    market_path.resolve(strict=True),
                    tiers_path.resolve(strict=True),
                    pairs,
                    str(manifest["development_timerange"]),
                    str(manifest["holdout_timerange"]),
                )
                if validated_provenance_sha != provenance_sha:
                    raise HoldoutRunError(
                        "BLOCKED_DATA", "Holdout data provenance changed after scenario open"
                    )
            assert expected_receipts is not None
            scenario_views[scenario] = summary.get("scenario_data_view")
            artifact = _sanitize_raw_artifact(
                scenario=scenario,
                slug=slug,
                raw_dir=raw,
                runner_summary=summary,
                completed=completed,
                command_shape=command_shape,
                bundle_dir=evidence,
                strategy=strategy,
                strategy_source=strategy_bytes,
                data_provenance=provenance,
                data_provenance_sha256=provenance_sha,
                expected_input_receipts=expected_receipts,
                source_tree_sha256=source_tree_sha,
                implementation_receipts=implementation_receipts,
                timerange=str(manifest["holdout_timerange"]),
                network_policy=network_policy,
            )
            produced.append((artifact, open_sha))
        if scenario_views["HOLDOUT"] != scenario_views["HOLDOUT_STRESS"]:
            raise HoldoutRunError(
                "artifact_invalid", "Holdout scenarios used different retained data views"
            )
        result = {
            "schema": HOLDOUT_RESULT_SCHEMA,
            "research_run_id": research_run_id,
            "candidate_id": manifest["candidate_id"],
            "input_manifest_sha256": manifest_sha,
            "data_provenance_sha256": provenance_sha,
            "source_tree_sha256": source_tree_sha,
            "producer_sha256": implementation_receipts["producer"]["sha256"],
            "runner_sha256": runner_sha,
            "artifacts": [
                {
                    "scenario": artifact.scenario,
                    "archive": artifact.archive,
                    "archive_sha256": artifact.archive_sha256,
                    "provenance_sha256": artifact.provenance_sha256,
                    "scenario_open_sha256": open_sha,
                }
                for artifact, open_sha in produced
            ],
        }
        _write_exclusive(
            directory / HOLDOUT_RESULT_NAME,
            _canonical_bytes(result),
            0o400,
        )
        return {
            "research_run_id": research_run_id,
            "status": "RESULTS_READY",
            "scenarios": ["HOLDOUT", "HOLDOUT_STRESS"],
        }
    except HoldoutRunError:
        raise
    except (ResearchCandidateError, OSError, RuntimeError, TypeError, ValueError) as exc:
        raise HoldoutRunError(
            "HOLDOUT_FAILED", "Holdout continuation failed closed"
        ) from exc
    finally:
        shutil.rmtree(runtime, ignore_errors=True)


def _load_holdout_result(
    run_dir: Path,
    research_run_id: str,
) -> Tuple[Mapping[str, Any], str]:
    data = _read_regular(run_dir / HOLDOUT_RESULT_NAME, "Holdout result", 1024 * 1024)
    value = _json_bytes(data, "Holdout result")
    required = {
        "schema",
        "research_run_id",
        "candidate_id",
        "input_manifest_sha256",
        "data_provenance_sha256",
        "source_tree_sha256",
        "producer_sha256",
        "runner_sha256",
        "artifacts",
    }
    artifacts = value.get("artifacts")
    if (
        set(value) != required
        or value.get("schema") != HOLDOUT_RESULT_SCHEMA
        or value.get("research_run_id") != research_run_id
        or any(
            not isinstance(value.get(name), str)
            or _SHA256.fullmatch(str(value.get(name))) is None
            for name in (
                "input_manifest_sha256",
                "data_provenance_sha256",
                "source_tree_sha256",
                "producer_sha256",
                "runner_sha256",
            )
        )
        or not isinstance(artifacts, list)
        or len(artifacts) != 2
    ):
        raise HoldoutRunError("artifact_invalid", "Holdout result receipt is invalid")
    expected = (
        ("HOLDOUT", "backtest-result-holdout-02.zip"),
        ("HOLDOUT_STRESS", "backtest-result-holdout-stress-03.zip"),
    )
    for record, (scenario, archive) in zip(artifacts, expected):
        if (
            not isinstance(record, dict)
            or set(record)
            != {
                "scenario",
                "archive",
                "archive_sha256",
                "provenance_sha256",
                "scenario_open_sha256",
            }
            or record.get("scenario") != scenario
            or record.get("archive") != archive
            or any(
                not isinstance(record.get(name), str)
                or _SHA256.fullmatch(str(record.get(name))) is None
                for name in (
                    "archive_sha256",
                    "provenance_sha256",
                    "scenario_open_sha256",
                )
            )
        ):
            raise HoldoutRunError("artifact_invalid", "Holdout artifact receipt is invalid")
    return value, hashlib.sha256(data).hexdigest()


def _profile_spec_from_row(row: sqlite3.Row) -> ProfileSpec:
    try:
        return ProfileSpec(
            name=str(row["name"]),
            history_start_date=str(row["history_start_date"]),
            smoke_days=int(row["smoke_days"]),
            holdout_days=int(row["holdout_days"]),
            stress_fee_multiplier=float(row["stress_fee_multiplier"]),
            max_drawdown_pct=float(row["max_drawdown_pct"]),
            min_development_trades=int(row["min_development_trades"]),
            min_holdout_trades=int(row["min_holdout_trades"]),
            min_profit_factor=float(row["min_profit_factor"]),
        )
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise HoldoutRunError("run_state_conflict", "Research Profile contract is invalid") from exc


def _verify_later_provenance(
    evidence: Path,
    record: Mapping[str, Any],
    result: Mapping[str, Any],
    strategy: str,
    strategy_sha256: str,
    timerange: str,
) -> Mapping[str, Any]:
    archive = str(record["archive"])
    provenance_path = evidence / archive.removesuffix(".zip")
    provenance_path = provenance_path.with_suffix(".provenance.json")
    provenance = _json_bytes(
        _read_regular(provenance_path, "later Artifact provenance", 1024 * 1024),
        "later Artifact provenance",
    )
    acquisition = provenance.get("acquisition")
    freqtrade = provenance.get("freqtrade")
    generation = provenance.get("generation")
    implementation = generation.get("implementation_receipts") if isinstance(generation, dict) else None
    runner = implementation.get("runner") if isinstance(implementation, dict) else None
    producer = implementation.get("producer") if isinstance(implementation, dict) else None
    scenario_view = generation.get("scenario_data_view") if isinstance(generation, dict) else None
    _, holdout_stop = _timerange(timerange)
    if (
        not isinstance(acquisition, dict)
        or acquisition.get("retained_data_provenance_sha256")
        != result["data_provenance_sha256"]
        or not isinstance(freqtrade, dict)
        or freqtrade.get("source_tree_sha256") != result["source_tree_sha256"]
        or freqtrade.get("dependencies")
        != {"freqtrade": SUPPORTED_FREQTRADE_VERSION, **SUPPORTED_DEPENDENCIES}
        or not isinstance(generation, dict)
        or generation.get("scenario") != record["scenario"]
        or generation.get("return_code") != 0
        or generation.get("official_core") != SUPPORTED_OFFICIAL_CORE
        or not isinstance(runner, dict)
        or runner.get("sha256") != result["runner_sha256"]
        or not isinstance(producer, dict)
        or producer.get("sha256") != result["producer_sha256"]
        or not isinstance(scenario_view, dict)
        or set(scenario_view) != {"exclusive_stop_utc", "files"}
        or scenario_view.get("exclusive_stop_utc")
        != holdout_stop.isoformat().replace("+00:00", "Z")
        or not isinstance(scenario_view.get("files"), dict)
        or not scenario_view["files"]
    ):
        raise HoldoutRunError("artifact_invalid", "later Artifact provenance drifted")
    receipt_name = (
        "holdout-open.json"
        if record["scenario"] == "HOLDOUT"
        else "holdout-stress-open.json"
    )
    try:
        receipt_sha = _validate_scenario_open_receipt(
            evidence.parent / "holdout-receipts" / receipt_name,
            scenario=str(record["scenario"]),
            timerange=timerange,
            strategy=strategy,
            strategy_sha256=strategy_sha256,
            data_provenance_sha256=str(result["data_provenance_sha256"]),
        )
    except (ResearchCandidateError, OSError, RuntimeError, ValueError) as exc:
        raise HoldoutRunError("artifact_invalid", "scenario open receipt is invalid") from exc
    if receipt_sha != record["scenario_open_sha256"]:
        raise HoldoutRunError("artifact_invalid", "scenario open receipt drifted")
    return scenario_view


def _parse_later_artifacts(
    run_dir: Path,
    result: Mapping[str, Any],
    strategy: str,
    strategy_sha256: str,
    timerange: str,
) -> dict[str, ParsedBacktestArtifact]:
    evidence = run_dir / "holdout-evidence"
    try:
        if evidence.is_symlink() or not evidence.resolve(strict=True).is_dir():
            raise OSError("unsafe evidence root")
    except (OSError, RuntimeError, ValueError) as exc:
        raise HoldoutRunError("artifact_invalid", "Holdout evidence root is unavailable") from exc
    parsed: dict[str, ParsedBacktestArtifact] = {}
    scenario_views: list[Mapping[str, Any]] = []
    for record in result["artifacts"]:
        try:
            artifact = parse_backtest_artifact(
                evidence,
                Path(str(record["archive"])),
                strategy,
                SUPPORTED_FREQTRADE_VERSION,
                str(record["provenance_sha256"]),
            )
        except (ArtifactImportError, OSError, RuntimeError, ValueError) as exc:
            raise HoldoutRunError("artifact_invalid", "later Artifact is invalid") from exc
        if (
            artifact.archive_sha256 != record["archive_sha256"]
            or artifact.strategy_sha256 != strategy_sha256
        ):
            raise HoldoutRunError("artifact_invalid", "later Artifact identity drifted")
        scenario_views.append(
            _verify_later_provenance(
                evidence, record, result, strategy, strategy_sha256, timerange
            )
        )
        parsed[str(record["scenario"])] = artifact
    if set(parsed) != {"HOLDOUT", "HOLDOUT_STRESS"}:
        raise HoldoutRunError("artifact_invalid", "later Artifact scenarios are incomplete")
    if len(scenario_views) != 2 or scenario_views[0] != scenario_views[1]:
        raise HoldoutRunError(
            "artifact_invalid", "later Artifacts used different retained data views"
        )
    return parsed


def _result_matches_authorized_identity(
    result: Mapping[str, Any],
    run: sqlite3.Row,
    snapshot: Mapping[str, Any],
    directory: Path,
) -> bool:
    authorization = snapshot.get("holdout_authorization")
    if not isinstance(authorization, dict):
        return False
    try:
        database_run_dir = Path(str(run["run_dir"])).resolve(strict=True)
    except (OSError, RuntimeError, ValueError):
        return False
    return (
        database_run_dir == directory
        and result.get("candidate_id") == run["candidate_id"]
        and result.get("input_manifest_sha256")
        == authorization.get("input_manifest_sha256")
        and result.get("runner_sha256") == authorization.get("runner_sha256")
    )


def finalize_holdout_continuation(
    database_path: PathLike,
    run_dir: PathLike,
    research_run_id: str,
    *,
    now: Optional[str] = None,
) -> dict[str, Any]:
    """Pure-validate all three scenarios, then attach both later results atomically."""
    timestamp = _timestamp(now)
    directory = Path(run_dir).resolve(strict=True)
    if directory.name != research_run_id:
        raise HoldoutRunError("run_state_conflict", "ResearchRun directory identity mismatch")
    result, result_sha = _load_holdout_result(directory, research_run_id)
    if (
        hashlib.sha256(_read_regular(Path(__file__).resolve(), "Holdout producer")).hexdigest()
        != result["producer_sha256"]
        or hashlib.sha256(_read_regular(DEFAULT_RUNNER, "backtest runner")).hexdigest()
        != result["runner_sha256"]
    ):
        raise HoldoutRunError(
            "artifact_invalid", "Holdout implementation receipt changed before attach"
        )

    # File validation is deliberately completed before acquiring the write lock.
    with closing(get_connection(database_path, read_only=True, must_exist=True)) as connection:
        connection.execute("BEGIN")
        run, executions, snapshot, _ = _authorized_state(connection, research_run_id)
        if not _result_matches_authorized_identity(
            result, run, snapshot, directory
        ):
            connection.rollback()
            raise HoldoutRunError("artifact_invalid", "Holdout result identity drifted")
        validated_snapshot = snapshot
        development = _parsed_development(
            executions[0], run["run_dir"], str(run["class_name"])
        )
        later = _parse_later_artifacts(
            directory,
            result,
            str(run["class_name"]),
            str(run["code_sha256"]),
            str(snapshot["holdout_authorization"]["holdout_timerange"]),
        )
        artifacts = {"DEVELOPMENT": development, **later}
        try:
            _validate_cross_scenario(_profile_spec_from_row(run), artifacts)
        except ResearchBundleImportError as exc:
            connection.rollback()
            raise HoldoutRunError("artifact_invalid", "three-scenario contract is invalid") from exc
        for execution, scenario in zip(executions[1:], ("HOLDOUT", "HOLDOUT_STRESS")):
            _require_execution_contract(execution, later[scenario])
        connection.rollback()

    with closing(get_connection(database_path, must_exist=True)) as connection:
        try:
            connection.execute("BEGIN IMMEDIATE")
            _schema_v1(connection)
            run, executions, snapshot, _ = _authorized_state(connection, research_run_id)
            if snapshot != validated_snapshot:
                raise HoldoutRunError(
                    "run_state_conflict",
                    "Holdout authorization snapshot changed before atomic attach",
                )
            current_development = _parsed_development(
                executions[0], run["run_dir"], str(run["class_name"])
            )
            if (
                current_development.archive_sha256 != development.archive_sha256
                or current_development.metadata_sha256 != development.metadata_sha256
                or current_development.provenance_sha256 != development.provenance_sha256
                or current_development.metrics_json() != development.metrics_json()
            ):
                raise HoldoutRunError("run_state_conflict", "Development Artifact changed")
            locked_result, locked_result_sha = _load_holdout_result(
                directory, research_run_id
            )
            if locked_result != result or locked_result_sha != result_sha:
                raise HoldoutRunError(
                    "artifact_invalid", "Holdout result changed before atomic attach"
                )
            if not _result_matches_authorized_identity(
                locked_result, run, snapshot, directory
            ):
                raise HoldoutRunError(
                    "artifact_invalid",
                    "Holdout authorization changed before atomic attach",
                )
            if (
                hashlib.sha256(
                    _read_regular(Path(__file__).resolve(), "Holdout producer")
                ).hexdigest()
                != locked_result["producer_sha256"]
                or hashlib.sha256(
                    _read_regular(DEFAULT_RUNNER, "backtest runner")
                ).hexdigest()
                != locked_result["runner_sha256"]
            ):
                raise HoldoutRunError(
                    "artifact_invalid",
                    "Holdout implementation receipt changed before atomic attach",
                )
            locked_later = _parse_later_artifacts(
                directory,
                locked_result,
                str(run["class_name"]),
                str(run["code_sha256"]),
                str(snapshot["holdout_authorization"]["holdout_timerange"]),
            )
            try:
                _validate_cross_scenario(
                    _profile_spec_from_row(run),
                    {"DEVELOPMENT": current_development, **locked_later},
                )
            except ResearchBundleImportError as exc:
                raise HoldoutRunError(
                    "artifact_invalid", "three-scenario contract changed before attach"
                ) from exc
            for execution, scenario in zip(
                executions[1:], ("HOLDOUT", "HOLDOUT_STRESS")
            ):
                _require_execution_contract(execution, locked_later[scenario])
            later = locked_later
            result_sha = locked_result_sha
            for execution, scenario in zip(
                executions[1:], ("HOLDOUT", "HOLDOUT_STRESS")
            ):
                parsed = later[scenario]
                _require_execution_contract(execution, parsed)
                values = execution_result_values(parsed)
                changed = connection.execute(
                    """
                    UPDATE backtest_executions
                    SET status='SUCCEEDED', result_archive_path=:result_archive_path,
                        stdout_path=NULL, stderr_path=NULL, return_code=0,
                        total_trades=:total_trades, profit_pct=:profit_pct,
                        max_drawdown_pct=:max_drawdown_pct, win_rate=:win_rate,
                        profit_factor=:profit_factor, sharpe=:sharpe,
                        sortino=:sortino, calmar=:calmar,
                        long_profit_pct=:long_profit_pct,
                        short_profit_pct=:short_profit_pct,
                        metrics_json=:metrics_json, scenario_passed=NULL,
                        error_message=NULL, finished_at=:finished_at
                    WHERE id=:id AND research_run_id=:research_run_id
                      AND scenario=:scenario AND status='PENDING'
                    """,
                    {
                        **values,
                        "finished_at": timestamp,
                        "id": execution["id"],
                        "research_run_id": research_run_id,
                        "scenario": scenario,
                    },
                ).rowcount
                if changed != 1:
                    raise HoldoutRunError(
                        "run_state_conflict", "later execution changed before attach"
                    )
            checks = {
                **_ORIGINAL_CHECKS,
                "authorization": "AUTHORIZED",
                "next_phase": "HUMAN_ECONOMIC_REVIEW",
                "holdout": "SUCCEEDED",
                "holdout_stress": "SUCCEEDED",
                "judge": "NOT_RUN",
            }
            updated_snapshot = dict(snapshot)
            updated_snapshot["holdout_results"] = {
                "result_sha256": result_sha,
                "artifacts": [
                    {
                        "scenario": scenario,
                        "archive_sha256": later[scenario].archive_sha256,
                        "provenance_sha256": later[scenario].provenance_sha256,
                    }
                    for scenario in ("HOLDOUT", "HOLDOUT_STRESS")
                ],
            }
            changed = connection.execute(
                """
                UPDATE research_runs
                SET status='COMPLETED', stage='COMPLETED', verdict=NULL,
                    input_snapshot_json=?, checks_json=?, finished_at=?,
                    error_stage=NULL, error_message=NULL
                WHERE id=? AND status='RUNNING' AND stage='HOLDOUT_BACKTEST'
                  AND verdict IS NULL
                """,
                (
                    _canonical(updated_snapshot),
                    _canonical(checks),
                    timestamp,
                    research_run_id,
                ),
            ).rowcount
            if changed != 1:
                raise HoldoutRunError(
                    "run_state_conflict", "ResearchRun changed before atomic completion"
                )
            terminal = connection.execute(
                "SELECT scenario,status,scenario_passed FROM backtest_executions "
                "WHERE research_run_id=? ORDER BY sequence,id",
                (research_run_id,),
            ).fetchall()
            releases = connection.execute(
                "SELECT COUNT(*) FROM releases WHERE research_run_id=?",
                (research_run_id,),
            ).fetchone()[0]
            if (
                [(item["scenario"], item["status"]) for item in terminal]
                != [
                    ("DEVELOPMENT", "SUCCEEDED"),
                    ("HOLDOUT", "SUCCEEDED"),
                    ("HOLDOUT_STRESS", "SUCCEEDED"),
                ]
                or terminal[0]["scenario_passed"] != 1
                or any(item["scenario_passed"] is not None for item in terminal[1:])
                or releases != 0
            ):
                raise HoldoutRunError("run_state_conflict", "atomic terminal proof failed")
            connection.commit()
        except HoldoutRunError:
            if connection.in_transaction:
                connection.rollback()
            raise
        except (sqlite3.Error, OSError, RuntimeError, TypeError, ValueError) as exc:
            if connection.in_transaction:
                connection.rollback()
            raise HoldoutRunError(
                "attach_failed", "Holdout results could not be attached atomically"
            ) from exc
    return load_public_research_run(database_path, research_run_id)


def _scenario_opened(run_dir: Path, scenario: str) -> bool:
    name = (
        "holdout-open.json"
        if scenario == "HOLDOUT"
        else "holdout-stress-open.json"
    )
    path = run_dir / "holdout-receipts" / name
    try:
        info = path.stat(follow_symlinks=False)
    except OSError:
        return False
    return not path.is_symlink() and stat.S_ISREG(info.st_mode) and info.st_nlink == 1


def fail_holdout_continuation(
    database_path: PathLike,
    run_dir: PathLike,
    research_run_id: str,
    terminal_status: str,
    error_code: str,
    *,
    now: Optional[str] = None,
) -> dict[str, Any]:
    """Close the consumed one-shot budget; no retry or partial metrics survive."""
    mapped = {
        "FAILED": "FAILED",
        "TIMED_OUT": "FAILED",
        "CANCELLED": "CANCELLED",
        "INTERRUPTED": "INTERRUPTED",
    }.get(terminal_status)
    if mapped is None:
        raise HoldoutRunError("invalid_terminal", "Holdout terminal status is invalid")
    if error_code not in _PUBLIC_ERROR_CODES - {"NOT_OPENED_AFTER_TERMINAL"}:
        raise HoldoutRunError("invalid_terminal", "Holdout error code is invalid")
    timestamp = _timestamp(now)
    directory = Path(run_dir).resolve(strict=True)
    if directory.name != research_run_id:
        raise HoldoutRunError("run_state_conflict", "ResearchRun directory identity mismatch")
    with closing(get_connection(database_path, must_exist=True)) as connection:
        try:
            connection.execute("BEGIN IMMEDIATE")
            _schema_v1(connection)
            run = connection.execute(
                "SELECT * FROM research_runs WHERE id=?",
                (research_run_id,),
            ).fetchone()
            executions = connection.execute(
                "SELECT * FROM backtest_executions WHERE research_run_id=? "
                "ORDER BY sequence,id",
                (research_run_id,),
            ).fetchall()
            if run is None:
                raise HoldoutRunError("run_not_found", "ResearchRun not found")
            if Path(str(run["run_dir"])).resolve(strict=True) != directory:
                raise HoldoutRunError("run_state_conflict", "ResearchRun directory drifted")
            if (
                run["status"] == "COMPLETED"
                and run["stage"] == "COMPLETED"
                and run["verdict"] is None
                and len(executions) == 3
                and all(item["status"] == "SUCCEEDED" for item in executions)
            ):
                connection.rollback()
                return load_public_research_run(database_path, research_run_id)
            if (
                run["status"] in {"FAILED", "CANCELLED", "INTERRUPTED"}
                and run["stage"] == "HOLDOUT_BACKTEST"
                and run["verdict"] is None
            ):
                connection.rollback()
                # The public loader validates the full FAILED/SKIPPED mapping,
                # error-code allowlist, empty result fields, and open receipts.
                # A valid terminal DB state is authoritative and idempotent.
                return load_public_research_run(database_path, research_run_id)
            if (
                run["pipeline_version"] != DEVELOPMENT_PIPELINE_VERSION
                or run["status"] != "RUNNING"
                or run["stage"] != "HOLDOUT_BACKTEST"
                or run["verdict"] is not None
                or len(executions) != 3
                or [item["scenario"] for item in executions]
                != ["DEVELOPMENT", "HOLDOUT", "HOLDOUT_STRESS"]
                or executions[0]["status"] != "SUCCEEDED"
                or executions[0]["scenario_passed"] != 1
                or any(item["status"] != "PENDING" for item in executions[1:])
            ):
                raise HoldoutRunError(
                    "run_state_conflict", "Holdout continuation is not fail-closeable"
                )
            later_states: dict[str, str] = {}
            for execution in executions[1:]:
                scenario = str(execution["scenario"])
                opened = _scenario_opened(directory, scenario)
                state = "FAILED" if opened else "SKIPPED"
                later_states[scenario] = state
                changed = connection.execute(
                    """
                    UPDATE backtest_executions
                    SET status=?, result_archive_path=NULL, stdout_path=NULL,
                        stderr_path=NULL, return_code=NULL, total_trades=NULL,
                        profit_pct=NULL, max_drawdown_pct=NULL, win_rate=NULL,
                        profit_factor=NULL, sharpe=NULL, sortino=NULL, calmar=NULL,
                        long_profit_pct=NULL, short_profit_pct=NULL,
                        metrics_json='{}', scenario_passed=NULL,
                        error_message=?, finished_at=?
                    WHERE id=? AND research_run_id=? AND status='PENDING'
                    """,
                    (
                        state,
                        error_code if opened else "NOT_OPENED_AFTER_TERMINAL",
                        timestamp,
                        execution["id"],
                        research_run_id,
                    ),
                ).rowcount
                if changed != 1:
                    raise HoldoutRunError(
                        "run_state_conflict", "later execution changed during failure close"
                    )
            checks = {
                **_ORIGINAL_CHECKS,
                "authorization": "AUTHORIZED",
                "next_phase": "NONE_CONTINUATION_TERMINAL",
                "holdout": later_states["HOLDOUT"],
                "holdout_stress": later_states["HOLDOUT_STRESS"],
                "judge": "NOT_RUN",
            }
            changed = connection.execute(
                """
                UPDATE research_runs
                SET status=?, stage='HOLDOUT_BACKTEST', verdict=NULL,
                    checks_json=?, error_stage='HOLDOUT_BACKTEST',
                    error_message=?, finished_at=?
                WHERE id=? AND status='RUNNING' AND stage='HOLDOUT_BACKTEST'
                  AND verdict IS NULL
                """,
                (
                    mapped,
                    _canonical(checks),
                    error_code,
                    timestamp,
                    research_run_id,
                ),
            ).rowcount
            if changed != 1:
                raise HoldoutRunError(
                    "run_state_conflict", "ResearchRun changed during failure close"
                )
            connection.commit()
        except HoldoutRunError:
            if connection.in_transaction:
                connection.rollback()
            raise
        except (sqlite3.Error, OSError, RuntimeError, TypeError, ValueError) as exc:
            if connection.in_transaction:
                connection.rollback()
            raise HoldoutRunError(
                "failure_close_failed", "Holdout failure state could not be persisted"
            ) from exc
    return load_public_research_run(database_path, research_run_id)


def _strategy_detail_url(profile_id: str, candidate_id: str, run_id: str) -> str:
    return "/strategy?" + urlencode(
        (
            ("profile_id", profile_id),
            ("candidate_id", candidate_id),
            ("research_run_id", run_id),
        )
    )


def _public_execution(row: sqlite3.Row, opened: bool) -> dict[str, Any]:
    if row["error_message"] is not None and (
        not isinstance(row["error_message"], str)
        or row["error_message"] not in _PUBLIC_ERROR_CODES
    ):
        raise HoldoutRunError("run_state_conflict", "execution error receipt is invalid")
    for name in (
        "total_trades",
        "profit_pct",
        "max_drawdown_pct",
        "win_rate",
        "profit_factor",
        "sharpe",
        "sortino",
        "calmar",
        "long_profit_pct",
        "short_profit_pct",
    ):
        value = row[name]
        if value is not None and (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
        ):
            raise HoldoutRunError("run_state_conflict", "execution metric is invalid")
    return {
        "scenario": row["scenario"],
        "sequence": row["sequence"],
        "status": row["status"],
        "scenario_opened": opened,
        "total_trades": row["total_trades"],
        "profit_pct": row["profit_pct"],
        "total_profit_pct": row["profit_pct"],
        "max_drawdown_pct": row["max_drawdown_pct"],
        "win_rate": row["win_rate"],
        "profit_factor": row["profit_factor"],
        "sharpe": row["sharpe"],
        "sortino": row["sortino"],
        "calmar": row["calmar"],
        "long_profit_pct": row["long_profit_pct"],
        "short_profit_pct": row["short_profit_pct"],
        "scenario_passed": (
            None if row["scenario_passed"] is None else bool(row["scenario_passed"])
        ),
        "created_at": row["created_at"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "error_message": row["error_message"],
    }


def _residual_authorization(run_dir: Path) -> bool:
    targets = (
        run_dir / HOLDOUT_ATTEMPT_NAME,
        run_dir / ".holdout-input-preparing",
        run_dir / "holdout-input",
        run_dir / "holdout-runtime",
        run_dir / "holdout-receipts",
        run_dir / "holdout-evidence",
        run_dir / HOLDOUT_RESULT_NAME,
        run_dir / "holdout-request.json",
        run_dir / "holdout-status.json",
        run_dir / "holdout-owner.json",
        run_dir / "holdout.stdout.log",
        run_dir / "holdout.stderr.log",
    )
    return any(path.exists() or path.is_symlink() for path in targets)


def _decorate_development_public(
    database_path: PathLike,
    research_run_id: str,
    capability: Optional[FrozenHoldoutCapability],
) -> dict[str, Any]:
    try:
        payload = load_development_public_research_run(database_path, research_run_id)
    except DevelopmentRunError as exc:
        raise HoldoutRunError(exc.code, exc.message) from exc
    with closing(get_connection(database_path, read_only=True, must_exist=True)) as connection:
        connection.execute("BEGIN")
        run = connection.execute(
            "SELECT research_profile_id,run_dir FROM research_runs WHERE id=?",
            (research_run_id,),
        ).fetchone()
        execution = connection.execute(
            "SELECT * FROM backtest_executions WHERE research_run_id=?",
            (research_run_id,),
        ).fetchone()
        if run is None or execution is None:
            connection.rollback()
            raise HoldoutRunError("run_not_found", "ResearchRun not found")
        run_dir = Path(str(run["run_dir"]))
        residual = _residual_authorization(run_dir)
        can_authorize = False
        reason = "ResearchRun is not eligible for Holdout authorization"
        authorization_status = "NOT_ELIGIBLE"
        if residual:
            authorization_status = "CONSUMED_OR_INTERRUPTED"
            reason = "Holdout authorization files already exist; manual confirmation is required"
        elif payload["status"] == "PENDING" and payload["stage"] == "PENDING":
            try:
                eligible, _, _ = _eligible_row(
                    connection, research_run_id, parse_artifact=True
                )
                _bound_candidate(connection, str(eligible["candidate_id"]))
                can_authorize = True
                authorization_status = "AVAILABLE"
                reason = "fixed one-shot Holdout continuation is available"
            except (HoldoutRunError, DevelopmentRunError):
                can_authorize = False
        connection.rollback()
    if capability is not None and capability.status != "READY":
        can_authorize = False
        if authorization_status == "AVAILABLE":
            authorization_status = "BLOCKED_DATA"
            reason = capability.reason
    development = dict(payload["development"])
    execution_public = {
        "scenario": "DEVELOPMENT",
        "sequence": 1,
        "status": development["status"],
        "scenario_opened": development["status"] in {"SUCCEEDED", "FAILED"},
        "total_trades": development["total_trades"],
        "profit_pct": development["profit_pct"],
        "total_profit_pct": development["profit_pct"],
        "max_drawdown_pct": development["max_drawdown_pct"],
        "win_rate": development["win_rate"],
        "profit_factor": development["profit_factor"],
        "scenario_passed": development["scenario_passed"],
        "started_at": development["started_at"],
        "finished_at": development["finished_at"],
    }
    result = dict(payload)
    result.update(
        {
            "research_profile_id": run["research_profile_id"],
            "authorization": {
                "status": authorization_status,
                "can_authorize": can_authorize,
                "reason": reason,
            },
            "executions": [execution_public],
            "strategy_detail_url": _strategy_detail_url(
                str(run["research_profile_id"]),
                str(payload["candidate_id"]),
                research_run_id,
            ),
            "economic_review": "NOT_RUN",
            "profitability_claim": "NOT_ESTABLISHED",
            "tradability_claim": "NOT_ESTABLISHED",
        }
    )
    return result


def load_public_research_run(
    database_path: PathLike,
    research_run_id: str,
    capability: Optional[FrozenHoldoutCapability] = None,
) -> dict[str, Any]:
    """Return one honest public shape for Development-only and continuation states."""
    with closing(get_connection(database_path, read_only=True, must_exist=True)) as connection:
        connection.execute("BEGIN")
        run = connection.execute(
            "SELECT * FROM research_runs WHERE id=?",
            (research_run_id,),
        ).fetchone()
        if run is None or run["pipeline_version"] != DEVELOPMENT_PIPELINE_VERSION:
            connection.rollback()
            raise HoldoutRunError("run_not_found", "ResearchRun not found")
        executions = connection.execute(
            "SELECT * FROM backtest_executions WHERE research_run_id=? "
            "ORDER BY sequence,id",
            (research_run_id,),
        ).fetchall()
        release_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM releases WHERE research_run_id=?",
                (research_run_id,),
            ).fetchone()[0]
        )
        connection.rollback()
    if len(executions) == 1:
        return _decorate_development_public(
            database_path, research_run_id, capability
        )
    if (
        len(executions) != 3
        or [item["scenario"] for item in executions]
        != ["DEVELOPMENT", "HOLDOUT", "HOLDOUT_STRESS"]
        or [item["sequence"] for item in executions] != [1, 2, 3]
        or executions[0]["status"] != "SUCCEEDED"
        or executions[0]["scenario_passed"] != 1
        or release_count != 0
    ):
        raise HoldoutRunError("run_state_conflict", "continuation execution set is invalid")
    checks = _json_object(run["checks_json"], "continuation checks")
    try:
        snapshot = _json_object(run["input_snapshot_json"], "continuation snapshot")
        rejection_reasons = json.loads(run["rejection_reasons_json"])
    except (TypeError, json.JSONDecodeError, RecursionError) as exc:
        raise HoldoutRunError("run_state_conflict", "continuation state is invalid") from exc
    if not isinstance(rejection_reasons, list) or rejection_reasons:
        raise HoldoutRunError("run_state_conflict", "continuation rejection state is invalid")
    directory = Path(str(run["run_dir"]))
    opened = {
        "HOLDOUT": _scenario_opened(directory, "HOLDOUT"),
        "HOLDOUT_STRESS": _scenario_opened(directory, "HOLDOUT_STRESS"),
    }
    running_checks = {
        **_ORIGINAL_CHECKS,
        "authorization": "AUTHORIZED",
        "next_phase": "HOLDOUT_IN_PROGRESS",
        "holdout": "PENDING",
        "holdout_stress": "PENDING",
        "judge": "NOT_RUN",
    }
    completed_checks = {
        **_ORIGINAL_CHECKS,
        "authorization": "AUTHORIZED",
        "next_phase": "HUMAN_ECONOMIC_REVIEW",
        "holdout": "SUCCEEDED",
        "holdout_stress": "SUCCEEDED",
        "judge": "NOT_RUN",
    }
    later = executions[1:]
    later_metrics = [
        _json_object(item["metrics_json"], "later execution metrics")
        for item in later
    ]
    empty_fields = (
        "result_archive_path",
        "stdout_path",
        "stderr_path",
        "return_code",
        "total_trades",
        "profit_pct",
        "max_drawdown_pct",
        "win_rate",
        "profit_factor",
        "sharpe",
        "sortino",
        "calmar",
        "long_profit_pct",
        "short_profit_pct",
        "scenario_passed",
    )
    running = (
        run["status"] == "RUNNING"
        and run["stage"] == "HOLDOUT_BACKTEST"
        and run["verdict"] is None
        and all(item["status"] == "PENDING" for item in later)
        and all(item[name] is None for item in later for name in empty_fields)
        and all(item["error_message"] is None for item in later)
        and all(item["finished_at"] is None for item in later)
        and all(metrics == {} for metrics in later_metrics)
        and checks == running_checks
        and run["error_stage"] is None
        and run["error_message"] is None
        and run["finished_at"] is None
    )
    completed = (
        run["status"] == "COMPLETED"
        and run["stage"] == "COMPLETED"
        and run["verdict"] is None
        and all(item["status"] == "SUCCEEDED" for item in later)
        and all(item["scenario_passed"] is None for item in later)
        and all(
            isinstance(item["result_archive_path"], str)
            and bool(item["result_archive_path"])
            and item["return_code"] == 0
            and item["total_trades"] is not None
            and item["profit_pct"] is not None
            and item["max_drawdown_pct"] is not None
            and item["win_rate"] is not None
            and item["profit_factor"] is not None
            and item["stdout_path"] is None
            and item["stderr_path"] is None
            and item["error_message"] is None
            and item["finished_at"] is not None
            for item in later
        )
        and all(bool(metrics) for metrics in later_metrics)
        and all(opened.values())
        and checks == completed_checks
        and run["error_stage"] is None
        and run["error_message"] is None
        and run["finished_at"] is not None
    )
    failure_checks = {
        **_ORIGINAL_CHECKS,
        "authorization": "AUTHORIZED",
        "next_phase": "NONE_CONTINUATION_TERMINAL",
        "holdout": str(later[0]["status"]),
        "holdout_stress": str(later[1]["status"]),
        "judge": "NOT_RUN",
    }
    failed = (
        run["status"] in {"FAILED", "INTERRUPTED", "CANCELLED"}
        and run["stage"] == "HOLDOUT_BACKTEST"
        and run["verdict"] is None
        and all(item["status"] in {"FAILED", "SKIPPED"} for item in later)
        and all(item[name] is None for item in later for name in empty_fields)
        and all(metrics == {} for metrics in later_metrics)
        and all(
            (item["status"] == "FAILED") == opened[str(item["scenario"])]
            for item in later
        )
        and checks == failure_checks
        and run["error_stage"] == "HOLDOUT_BACKTEST"
        and isinstance(run["error_message"], str)
        and run["error_message"] in _PUBLIC_ERROR_CODES
        and all(item["finished_at"] is not None for item in later)
        and all(
            (
                item["status"] == "FAILED"
                and item["error_message"] == run["error_message"]
            )
            or (
                item["status"] == "SKIPPED"
                and item["error_message"] == "NOT_OPENED_AFTER_TERMINAL"
            )
            for item in later
        )
        and run["finished_at"] is not None
    )
    if not (running or completed or failed):
        raise HoldoutRunError("run_state_conflict", "continuation public state is invalid")
    execution_values = [
        _public_execution(executions[0], True),
        _public_execution(executions[1], opened["HOLDOUT"]),
        _public_execution(executions[2], opened["HOLDOUT_STRESS"]),
    ]
    authorization = snapshot.get("holdout_authorization")
    if not isinstance(authorization, dict):
        raise HoldoutRunError("run_state_conflict", "Holdout authorization is missing")
    return {
        "research_run_id": run["id"],
        "candidate_id": run["candidate_id"],
        "research_profile_id": run["research_profile_id"],
        "trigger_type": run["trigger_type"],
        "status": run["status"],
        "stage": run["stage"],
        "verdict": run["verdict"],
        "pipeline_version": run["pipeline_version"],
        "freqtrade_version": run["freqtrade_version"],
        "checks": checks,
        "rejection_reasons": rejection_reasons,
        "error_stage": run["error_stage"],
        "error_message": run["error_message"],
        "created_at": run["created_at"],
        "started_at": run["started_at"],
        "finished_at": run["finished_at"],
        "authorization": {
            "status": "CONSUMED",
            "can_authorize": False,
            "reason": "one-shot Holdout authorization has been consumed",
        },
        "executions": execution_values,
        "development": {**execution_values[0], "execution_rows": 1},
        "holdout": {**execution_values[1], "execution_rows": 1},
        "holdout_stress": {**execution_values[2], "execution_rows": 1},
        "strategy_detail_url": _strategy_detail_url(
            str(run["research_profile_id"]),
            str(run["candidate_id"]),
            research_run_id,
        ),
        "economic_review": "NOT_RUN",
        "profitability_claim": "NOT_ESTABLISHED",
        "tradability_claim": "NOT_ESTABLISHED",
        "release_count": 0,
    }


def _relative_artifact_path(root: Path, supplied: PathLike, label: str) -> Path:
    try:
        path = Path(supplied)
        if not path.is_absolute():
            raise ValueError("relative path")
        relative = path.relative_to(root)
    except (OSError, RuntimeError, ValueError) as exc:
        raise HoldoutRunError(
            "presentation_unavailable", f"{label} is unavailable"
        ) from exc
    if not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
        raise HoldoutRunError("presentation_unavailable", f"{label} is unsafe")
    return relative


def _read_regular_relative_at(
    root_fd: int,
    relative: Path,
    label: str,
    maximum: int = 4 * 1024 * 1024,
) -> bytes:
    directory_fd = os.dup(root_fd)
    file_fd: Optional[int] = None
    try:
        for component in relative.parts[:-1]:
            next_fd = os.open(
                component,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=directory_fd,
            )
            inspected = os.fstat(next_fd)
            if not stat.S_ISDIR(inspected.st_mode):
                os.close(next_fd)
                raise OSError("unsafe source directory")
            os.close(directory_fd)
            directory_fd = next_fd
        file_fd = os.open(
            relative.parts[-1],
            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
            dir_fd=directory_fd,
        )
        before = os.fstat(file_fd)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_size > maximum
        ):
            raise OSError("unsafe source file")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(file_fd, min(64 * 1024, maximum + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > maximum:
                raise OSError("source file is too large")
        after = os.fstat(file_fd)
        if (
            (after.st_dev, after.st_ino) != (before.st_dev, before.st_ino)
            or after.st_size != before.st_size
            or after.st_mtime_ns != before.st_mtime_ns
        ):
            raise OSError("source file changed while reading")
        return b"".join(chunks)
    except (OSError, RuntimeError, ValueError) as exc:
        raise HoldoutRunError(
            "presentation_unavailable", f"{label} is unavailable"
        ) from exc
    finally:
        if file_fd is not None:
            os.close(file_fd)
        os.close(directory_fd)


def _write_exclusive_at(
    directory_fd: int, name: str, data: bytes, mode: int = 0o400
) -> None:
    if not name or Path(name).name != name:
        raise ValueError("unsafe destination filename")
    descriptor = os.open(
        name,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
        mode,
        dir_fd=directory_fd,
    )
    try:
        inspected = os.fstat(descriptor)
        if not stat.S_ISREG(inspected.st_mode) or inspected.st_nlink != 1:
            raise OSError("unsafe destination file")
        with os.fdopen(descriptor, "wb", closefd=False) as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(descriptor)
    os.fsync(directory_fd)


def _exclusive_verified_copy_at(
    source_fd: int,
    source_relative: Path,
    destination_fd: int,
    destination_name: str,
    expected_sha: str,
) -> None:
    data = _read_regular_relative_at(source_fd, source_relative, "FreqUI source")
    if hashlib.sha256(data).hexdigest() != expected_sha:
        raise HoldoutRunError("presentation_unavailable", "FreqUI source receipt drifted")
    _write_exclusive_at(destination_fd, destination_name, data, 0o400)
    copied = _read_regular_relative_at(
        destination_fd, Path(destination_name), "FreqUI copy"
    )
    if hashlib.sha256(copied).hexdigest() != expected_sha:
        raise HoldoutRunError("presentation_unavailable", "FreqUI copy verification failed")


def copy_frequi_results(
    database_path: PathLike,
    research_run_id: str,
    artifact_root: Optional[PathLike],
    frequi_config: Optional[FreqUIConfig],
) -> dict[str, Any]:
    """Best-effort flat copy after DB success; it never changes research state."""
    if (
        artifact_root is None
        or frequi_config is None
        or frequi_config.base_url is None
        or frequi_config.results_root is None
        or frequi_config.results_root_identity is None
    ):
        return {"status": "UNAVAILABLE", "reason": "FreqUI is not configured"}
    source_fd: Optional[int] = None
    destination_fd: Optional[int] = None
    try:
        parsed_url = urlsplit(frequi_config.base_url)
        if (
            parsed_url.scheme != "http"
            or parsed_url.hostname != "127.0.0.1"
            or parsed_url.port is None
            or parsed_url.username is not None
            or parsed_url.password is not None
            or parsed_url.path not in {"", "/"}
            or parsed_url.query
            or parsed_url.fragment
        ):
            raise ValueError("non-loopback FreqUI URL")
        source_root_raw = Path(artifact_root)
        destination_raw = Path(frequi_config.results_root)
        if source_root_raw.is_symlink() or destination_raw.is_symlink():
            raise OSError("symlink root")
        source_root = source_root_raw.resolve(strict=True)
        destination = destination_raw.resolve(strict=True)
        source_info = os.lstat(source_root)
        destination_info = os.lstat(destination)
        if (
            not stat.S_ISDIR(source_info.st_mode)
            or not stat.S_ISDIR(destination_info.st_mode)
            or (destination_info.st_dev, destination_info.st_ino)
            != frequi_config.results_root_identity
            or source_root == destination
            or source_root in destination.parents
            or destination in source_root.parents
        ):
            raise OSError("unsafe root separation")
        directory_flags = (
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        )
        source_fd = os.open(source_root, directory_flags)
        destination_fd = os.open(destination, directory_flags)
        opened_source = os.fstat(source_fd)
        opened_destination = os.fstat(destination_fd)
        if (
            (opened_source.st_dev, opened_source.st_ino)
            != (source_info.st_dev, source_info.st_ino)
            or (opened_destination.st_dev, opened_destination.st_ino)
            != frequi_config.results_root_identity
            or (opened_source.st_dev, opened_source.st_ino)
            == (opened_destination.st_dev, opened_destination.st_ino)
        ):
            raise OSError("root identity changed")
        if os.listdir(destination_fd):
            raise HoldoutRunError(
                "presentation_unavailable",
                "FreqUI disposable results root is already occupied",
            )
    except HoldoutRunError:
        if destination_fd is not None:
            os.close(destination_fd)
        if source_fd is not None:
            os.close(source_fd)
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        if destination_fd is not None:
            os.close(destination_fd)
        if source_fd is not None:
            os.close(source_fd)
        raise HoldoutRunError(
            "presentation_unavailable", "FreqUI roots are unavailable"
        ) from exc
    assert source_fd is not None and destination_fd is not None
    try:
        public = load_public_research_run(database_path, research_run_id)
        if public.get("status") != "COMPLETED" or public.get("release_count") != 0:
            raise HoldoutRunError(
                "presentation_unavailable",
                "FreqUI copy requires a completed continuation",
            )
        with closing(
            get_connection(database_path, read_only=True, must_exist=True)
        ) as connection:
            rows = connection.execute(
                "SELECT scenario,result_archive_path,metrics_json "
                "FROM backtest_executions WHERE research_run_id=? "
                "ORDER BY sequence,id",
                (research_run_id,),
            ).fetchall()
        copied: list[dict[str, Any]] = []
        expected_names: set[str] = set()
        for row in rows:
            metrics = _json_object(row["metrics_json"], "FreqUI execution metrics")
            artifact = metrics.get("artifact")
            if not isinstance(artifact, dict):
                raise HoldoutRunError(
                    "presentation_unavailable", "FreqUI Artifact receipt is incomplete"
                )
            archive = _relative_artifact_path(
                source_root, str(row["result_archive_path"]), "FreqUI archive"
            )
            archive_sha = artifact.get("archive_sha256")
            metadata_sha = artifact.get("metadata_sha256")
            if (
                not isinstance(archive_sha, str)
                or _SHA256.fullmatch(archive_sha) is None
                or not isinstance(metadata_sha, str)
                or _SHA256.fullmatch(metadata_sha) is None
            ):
                raise HoldoutRunError(
                    "presentation_unavailable", "FreqUI Artifact receipt is invalid"
                )
            metadata = archive.with_name(archive.stem + ".meta.json")
            archive_name = archive.name
            metadata_name = metadata.name
            if archive_name in expected_names or metadata_name in expected_names:
                raise HoldoutRunError(
                    "presentation_unavailable", "FreqUI flat filenames conflict"
                )
            expected_names.update((archive_name, metadata_name))
            _exclusive_verified_copy_at(
                source_fd,
                archive,
                destination_fd,
                archive_name,
                archive_sha,
            )
            _exclusive_verified_copy_at(
                source_fd,
                metadata,
                destination_fd,
                metadata_name,
                metadata_sha,
            )
            copied.append(
                {
                    "scenario": row["scenario"],
                    "archive": archive_name,
                    "metadata": metadata_name,
                }
            )
        if set(os.listdir(destination_fd)) != expected_names:
            raise HoldoutRunError(
                "presentation_unavailable",
                "FreqUI disposable results root changed during copy",
            )
        try:
            current_destination = os.stat(
                frequi_config.results_root, follow_symlinks=False
            )
        except OSError as exc:
            raise HoldoutRunError(
                "presentation_unavailable",
                "FreqUI disposable results root changed during copy",
            ) from exc
        if (
            not stat.S_ISDIR(current_destination.st_mode)
            or (current_destination.st_dev, current_destination.st_ino)
            != frequi_config.results_root_identity
        ):
            raise HoldoutRunError(
                "presentation_unavailable",
                "FreqUI disposable results root changed during copy",
            )
        return {
            "status": "COPIED",
            "base_url": frequi_config.base_url,
            "research_run_id": research_run_id,
            "files": copied,
            "meaning": (
                "optional local discovery only; not profitability or "
                "tradability evidence"
            ),
        }
    finally:
        os.close(destination_fd)
        os.close(source_fd)
