"""Thin, file-backed adapter for one two-round Search-only campaign.

The ranking, budget, ledger, receipts, Freqtrade execution, and finalist Gate
remain owned by ``lab.bounded_research.screen_search``.  This
module only binds approved database Candidates to that existing file contract
and projects its receipts to a path-free Console state.
"""

from __future__ import annotations

import ast
import fcntl
import hashlib
import io
import json
import os
import re
import sqlite3
import stat
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, BinaryIO, Mapping, Optional, Sequence, Tuple, Union
from uuid import uuid4

from lab.bounded_strategy import (
    BOUNDED_CAUSAL_STRATEGY_V1,
    BoundedStrategyError,
    analyze_bounded_causal_strategy,
)
from lab.codex_generation import (
    ApprovedCandidateSnapshot,
    GenerationContractError,
    load_approved_candidate_snapshot,
    load_profile_snapshot,
)
from lab.database import get_connection
from lab.development_run import (
    _git_value,
    _python_identity,
    _resolve_directory,
    _resolve_executable,
    _verify_python,
)
from lab.research_candidate import (
    SUPPORTED_FREQTRADE_COMMIT,
    SUPPORTED_FREQTRADE_TREE,
    SUPPORTED_FREQTRADE_VERSION,
)
from lab import bounded_research as pilot


PathLike = Union[str, Path]
PROJECT_ROOT = Path(__file__).resolve().parent.parent
BOUNDED_RESEARCH_SCRIPT = PROJECT_ROOT / "scripts" / "run_bounded_research_pilot.py"
STRATEGIES = "strategies"
ROUND_ONE_CAMPAIGN = "campaign-round-1.json"
BUSINESS_TABLES = (
    "research_profiles",
    "generation_runs",
    "candidates",
    "research_runs",
    "backtest_executions",
    "releases",
)
CHANGED_FACTOR = re.compile(r"^[a-z][a-z0-9_.-]{0,62}$")
PRIVATE_OUTPUT = re.compile(r"^round-[12]\.(?:stdout|stderr)\.log$")
PUBLIC_TRIAL_FIELDS = pilot.SEARCH_PUBLIC_TRIAL_FIELDS
PUBLIC_IDENTITY_FIELDS = ("candidate_id", "class_name", "mechanism", "strategy_sha256", "search_metrics")
FINALIST_BINDING_FIELDS = {
    "candidate_id", "generation_run_id", "source_sha256", "profile_id",
    "search_generation_id", "profile_snapshot_sha256", "search_timerange",
    "development_timerange", "finalist_gate", "terminal_sha256",
    "trials_sha256", "round_receipt_sha256", "projection_sha256",
    "profile_snapshot",
}
FINALIST_BINDING_OPTIONAL_FIELDS = {"economic_gate"}
SEARCH_DATABASE_CHANGED = "SEARCH_DATABASE_CHANGED"


class SearchCampaignError(ValueError):
    """A normalized Search adapter failure safe for the local JSON API."""

    def __init__(self, code: str, message: str, *, status: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


@dataclass(frozen=True)
class FrozenSearchCapability:
    status: str
    reason: str
    search_root: Optional[Path] = None
    freqtrade_python: Optional[Path] = None
    freqtrade_source: Optional[Path] = None
    root_identity: Optional[Tuple[int, int]] = None
    python_identity: Optional[Tuple[int, int, int, int]] = None
    source_identity: Optional[Tuple[int, int]] = None
    search_timerange: Optional[str] = None
    data_provenance_sha256: Optional[str] = None
    source_acquisition_sha256: Optional[str] = None
    pair: Optional[str] = None
    timeframe: Optional[str] = None
    base_fee: Optional[float] = None
    database_path: Optional[Path] = None
    profile_snapshot: Optional[Mapping[str, Any]] = None
    profile_snapshot_sha256: Optional[str] = None
    development_timerange: Optional[str] = None
    pre_roll_candles: Optional[int] = None
    economic_gate: Optional[Mapping[str, Any]] = None
    _directory_fd: int = field(default=-1, repr=False, compare=False)

    def public(self) -> dict[str, Any]:
        profile = self.profile_snapshot
        result = {
            "status": self.status,
            "reason": self.reason,
            "data_contract": "freqtrade-lab-retained-search-data-v2",
            "freqtrade_version": (
                SUPPORTED_FREQTRADE_VERSION if self.status == "READY" else None
            ),
            "search_timerange": self.search_timerange,
            "pair": self.pair,
            "timeframe": self.timeframe,
            "base_fee": self.base_fee,
            "profile_id": profile.get("id") if profile is not None else None,
            "profile_snapshot_sha256": self.profile_snapshot_sha256,
            "development_timerange": self.development_timerange,
            "maximum_attempts": pilot.SEARCH_MAX_ATTEMPTS,
            "active_attempt_limit": pilot.PROFILE_ACTIVE_ATTEMPTS,
            "maximum_rounds": pilot.SEARCH_MAX_ROUNDS,
            "ranking": list(pilot.SEARCH_RANKING),
            "finalist_gate": (
                pilot.profile_search_finalist_gate(profile)
                if profile is not None
                else None
            ),
            "economic_gate": (
                None
                if self.economic_gate is None
                else dict(self.economic_gate)
            ),
            "security_gate": BOUNDED_CAUSAL_STRATEGY_V1,
            "outside_git": self.status == "READY",
            "single_owner_lock": self.status == "READY",
        }
        return result

    def open_private_output(self, name: str) -> BinaryIO:
        if self.status != "READY" or self._directory_fd < 0:
            raise SearchCampaignError("BLOCKED_DATA", self.reason, status=503)
        if PRIVATE_OUTPUT.fullmatch(name) is None:
            raise SearchCampaignError("invalid_output", "Search output name is invalid")
        descriptor = -1
        try:
            descriptor = os.open(
                name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                0o600,
                dir_fd=self._directory_fd,
            )
            return os.fdopen(descriptor, "wb", closefd=True)
        except OSError as exc:
            if descriptor >= 0:
                os.close(descriptor)
            raise SearchCampaignError("output_create_failed", "Search private output cannot be created", status=500) from exc

    def close(self) -> None:
        descriptor = self._directory_fd
        if descriptor < 0:
            return
        object.__setattr__(self, "_directory_fd", -1)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


@dataclass(frozen=True)
class PreparedSearchRound:
    campaign_id: str
    round_number: int
    argv: Tuple[str, ...]
    database_digest_before: str


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _strict_json(data: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(data)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise SearchCampaignError("BLOCKED_DATA", f"{label} is invalid", status=503) from exc
    if not isinstance(value, dict):
        raise SearchCampaignError("BLOCKED_DATA", f"{label} is invalid", status=503)
    return value


def _read_regular(path: Path, label: str, limit: int = 64 * 1024 * 1024) -> bytes:
    try:
        info = os.lstat(path)
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise OSError("unsafe file")
        return path.read_bytes()
    except OSError as exc:
        raise SearchCampaignError("BLOCKED_DATA", f"{label} unavailable", status=503) from exc


def _database_profile_snapshot(database_path: PathLike, profile_id: str) -> dict[str, Any]:
    try:
        with closing(get_connection(database_path, read_only=True)) as connection:
            return load_profile_snapshot(connection, profile_id)
    except GenerationContractError as exc:
        raise SearchCampaignError("BLOCKED_DATA", exc.message, status=503) from exc
    except (FileNotFoundError, OSError, RuntimeError, sqlite3.Error) as exc:
        raise SearchCampaignError("BLOCKED_DATA", "Profile database is unavailable", status=503) from exc


def _acquisition_snapshot(root: Path, database_path: PathLike) -> dict[str, Any]:
    acquisition = root / pilot.ACQUISITION
    provenance_bytes = _read_regular(
        acquisition / "retained-data-provenance.json", "Search provenance"
    )
    provenance = _strict_json(provenance_bytes, "Search provenance")
    contract = provenance.get("contract")
    source = provenance.get("source")
    if not isinstance(contract, dict) or not isinstance(source, dict):
        raise SearchCampaignError("BLOCKED_DATA", "Search provenance is incomplete", status=503)
    timerange = contract.get("search_timerange")
    if not isinstance(timerange, str):
        raise SearchCampaignError("BLOCKED_DATA", "Search timerange is missing", status=503)
    try:
        profile = pilot.validate_profile_search_contract(contract)
        database_profile = _database_profile_snapshot(
            database_path, str(profile["profile_snapshot"]["id"])
        )
        if database_profile != profile["profile_snapshot"]:
            raise pilot.PilotError("Profile changed after Search data freeze")
        verification = {
            "search_timerange": timerange,
            "data_provenance_sha256": _sha256(provenance_bytes),
            **{
                key: contract[key]
                for key in (
                    "profile_snapshot",
                    "profile_snapshot_sha256",
                    "development_timerange",
                    "pre_roll_candles",
                    "capacity",
                    "finalist_gate",
                    "holdout",
                    "holdout_stress",
                )
            },
        }
        if "economic_gate" in contract:
            verification["economic_gate"] = contract["economic_gate"]
        verified = pilot._verify_search_data(
            acquisition,
            provenance,
            provenance_bytes,
            verification,
        )
        source_acquisition = provenance["source_acquisition"]
        result = {
            "search_timerange": timerange,
            "data_provenance_sha256": _sha256(provenance_bytes),
            "source_acquisition_sha256": _sha256(
                pilot.canonical(source_acquisition)
            ),
            "pair": verified["source"]["pair"],
            "timeframe": profile["timeframe"],
            "base_fee": profile["fee"],
            "profile_snapshot": contract["profile_snapshot"],
            "profile_snapshot_sha256": contract["profile_snapshot_sha256"],
            "development_timerange": contract["development_timerange"],
            "pre_roll_candles": contract["pre_roll_candles"],
        }
        if "economic_gate" in contract:
            result["economic_gate"] = pilot.validate_profile_economic_gate(
                contract["economic_gate"]
            )
        return result
    except pilot.PilotError as exc:
        if str(exc) == "BLOCKED_INSUFFICIENT_CAPACITY":
            raise SearchCampaignError(
                "BLOCKED_INSUFFICIENT_CAPACITY", str(exc), status=409
            ) from exc
        raise SearchCampaignError(
            "BLOCKED_DATA", "Profile Search data contract could not be verified", status=503
        ) from exc
    except (OSError, KeyError, TypeError, ValueError) as exc:
        raise SearchCampaignError(
            "BLOCKED_DATA", "Profile Search data contract could not be verified", status=503
        ) from exc


def _freqtrade_snapshot(
    freqtrade_python: Optional[PathLike], freqtrade_source: Optional[PathLike]
) -> dict[str, Any]:
    try:
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
            raise ValueError("source mismatch")
        source_info = os.stat(source)
        return {
            "freqtrade_python": python,
            "freqtrade_source": source,
            "python_identity": _python_identity(python),
            "source_identity": (source_info.st_dev, source_info.st_ino),
        }
    except Exception as exc:
        raise SearchCampaignError(
            "BLOCKED_DATA", "Freqtrade 2026.7 capability is unavailable", status=503
        ) from exc


def freeze_search_capability(
    database_path: PathLike,
    search_root: Optional[PathLike],
    freqtrade_python: Optional[PathLike],
    freqtrade_source: Optional[PathLike],
) -> FrozenSearchCapability:
    """Freeze one private root without making Search availability a server gate."""
    descriptor = -1
    try:
        if search_root is None:
            raise SearchCampaignError("BLOCKED_DATA", "Search root is not configured", status=503)
        raw = Path(search_root).expanduser()
        root = raw.resolve(strict=True)
        if raw.is_symlink() or any(
            (ancestor / ".git").exists() or (ancestor / ".git").is_symlink()
            for ancestor in (root, *root.parents)
        ):
            raise SearchCampaignError("BLOCKED_DATA", "Search root is unsafe", status=503)
        info = os.lstat(root)
        if not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o700:
            raise SearchCampaignError("BLOCKED_DATA", "Search root must be a private mode-0700 directory", status=503)
        descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
            raise SearchCampaignError("BLOCKED_DATA", "Search root identity changed", status=503)
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        acquisition = _acquisition_snapshot(root, database_path)
        freqtrade = _freqtrade_snapshot(freqtrade_python, freqtrade_source)
        return FrozenSearchCapability(
            status="READY",
            reason="Search-only data and Freqtrade 2026.7 are frozen",
            database_path=Path(database_path),
            search_root=root,
            root_identity=(opened.st_dev, opened.st_ino),
            _directory_fd=descriptor,
            **freqtrade,
            **{
                key: acquisition.get(key)
                for key in (
                    "search_timerange", "data_provenance_sha256",
                    "source_acquisition_sha256", "pair",
                    "timeframe", "base_fee", "profile_snapshot",
                    "profile_snapshot_sha256", "development_timerange",
                    "pre_roll_candles",
                    "economic_gate",
                )
            },
        )
    except Exception as exc:
        if descriptor >= 0:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)
        reason = exc.message if isinstance(exc, SearchCampaignError) else "Search capability could not be frozen"
        status_value = (
            exc.code
            if isinstance(exc, SearchCampaignError)
            and exc.code == "BLOCKED_INSUFFICIENT_CAPACITY"
            else "BLOCKED_DATA"
        )
        return FrozenSearchCapability(status=status_value, reason=reason)


def _require_frozen_identity(capability: FrozenSearchCapability) -> None:
    if (
        capability.status != "READY"
        or capability.search_root is None
        or capability.freqtrade_python is None
        or capability.freqtrade_source is None
        or capability.root_identity is None
        or capability._directory_fd < 0
    ):
        code = (
            "BLOCKED_INSUFFICIENT_CAPACITY"
            if capability.status == "BLOCKED_INSUFFICIENT_CAPACITY"
            else "BLOCKED_DATA"
        )
        raise SearchCampaignError(
            code,
            capability.reason,
            status=409 if code == "BLOCKED_INSUFFICIENT_CAPACITY" else 503,
        )
    try:
        root = os.stat(capability.search_root)
        opened = os.fstat(capability._directory_fd)
        python = os.stat(capability.freqtrade_python)
        source = os.stat(capability.freqtrade_source)
        valid = (
            stat.S_ISDIR(root.st_mode) and stat.S_IMODE(root.st_mode) == 0o700
            and (root.st_dev, root.st_ino) == (opened.st_dev, opened.st_ino) == capability.root_identity
            and (python.st_dev, python.st_ino, python.st_size, python.st_mtime_ns) == capability.python_identity
            and (source.st_dev, source.st_ino) == capability.source_identity
        )
    except OSError:
        valid = False
    if not valid:
        raise SearchCampaignError("BLOCKED_DATA", "Startup-frozen Search identities changed", status=503)


def _require_ready(capability: FrozenSearchCapability) -> None:
    """Revalidate the writer-owned data contract immediately before mutation."""
    _require_frozen_identity(capability)
    assert capability.search_root is not None
    try:
        if capability.database_path is None:
            raise SearchCampaignError("BLOCKED_DATA", "Profile database is unavailable", status=503)
        current_acquisition = _acquisition_snapshot(
            capability.search_root, capability.database_path
        )
    except SearchCampaignError as exc:
        raise SearchCampaignError(
            "BLOCKED_DATA", "Startup-frozen Search inputs changed", status=503
        ) from exc
    frozen = (
        capability.search_timerange,
        capability.data_provenance_sha256,
        capability.source_acquisition_sha256,
        capability.pair,
        capability.timeframe,
        capability.base_fee,
        capability.profile_snapshot,
        capability.profile_snapshot_sha256,
        capability.development_timerange,
        capability.pre_roll_candles,
        capability.economic_gate,
    )
    current = (
        current_acquisition["search_timerange"],
        current_acquisition["data_provenance_sha256"],
        current_acquisition.get("source_acquisition_sha256"),
        current_acquisition["pair"],
        current_acquisition["timeframe"],
        current_acquisition["base_fee"],
        current_acquisition.get("profile_snapshot"),
        current_acquisition.get("profile_snapshot_sha256"),
        current_acquisition.get("development_timerange"),
        current_acquisition.get("pre_roll_candles"),
        current_acquisition.get("economic_gate"),
    )
    if frozen != current:
        raise SearchCampaignError(
            "BLOCKED_DATA", "Startup-frozen Search inputs changed", status=503
        )


def _atomic_json_at(directory_fd: int, name: str, value: Mapping[str, Any], *, replace: bool) -> None:
    if Path(name).name != name:
        raise SearchCampaignError("state_write_failed", "Search state filename is invalid", status=500)
    target = f".{name}.{uuid4().hex}.tmp" if replace else name
    descriptor = -1
    try:
        descriptor = os.open(
            target,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
            dir_fd=directory_fd,
        )
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            descriptor = -1
            handle.write(pilot.canonical(value))
            handle.flush()
            os.fsync(handle.fileno())
        if replace:
            os.replace(target, name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
        os.fsync(directory_fd)
    except FileExistsError as exc:
        raise SearchCampaignError("campaign_consumed", "Search state already exists") from exc
    except OSError as exc:
        raise SearchCampaignError("state_write_failed", "Search state cannot be written", status=500) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if replace:
            try:
                os.unlink(target, dir_fd=directory_fd)
            except FileNotFoundError:
                pass


def _database_digest_connection(
    connection: sqlite3.Connection, exclude_generation_id: Optional[str] = None
) -> str:
    tables = tuple(
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_schema WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    )
    version_row = connection.execute("PRAGMA user_version").fetchone()
    if tables != tuple(sorted(BUSINESS_TABLES)) or version_row is None or int(version_row[0]) != 1:
        raise SearchCampaignError(
            "BLOCKED_DATA", "database must be exact six-table schema v1", status=503
        )
    document: dict[str, Any] = {"user_version": 1, "tables": {}}
    for table in BUSINESS_TABLES:
        columns = [str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")]
        if table == "generation_runs" and exclude_generation_id is not None:
            query, params = f"SELECT * FROM {table} WHERE id<>? ORDER BY id", (exclude_generation_id,)
        else:
            query, params = f"SELECT * FROM {table} ORDER BY id", ()
        rows = [list(row) for row in connection.execute(query, params)]
        document["tables"][table] = {"columns": columns, "rows": rows}
    return _sha256(pilot.canonical(document))


def business_table_digest(
    database_path: PathLike, exclude_generation_id: Optional[str] = None
) -> str:
    try:
        with closing(get_connection(database_path, read_only=True)) as connection:
            connection.execute("BEGIN")
            return _database_digest_connection(connection, exclude_generation_id)
    except SearchCampaignError:
        raise
    except (FileNotFoundError, OSError, RuntimeError, sqlite3.Error) as exc:
        raise SearchCampaignError("BLOCKED_DATA", "database is unavailable", status=503) from exc


def _profile_bound(snapshot: ApprovedCandidateSnapshot, capability: FrozenSearchCapability) -> None:
    profile = snapshot.profile
    frozen = capability.profile_snapshot
    if (
        frozen is None
        or profile.get("domain") != "OKX_CRYPTO_PERP"
        or profile.get("exchange") != "okx"
        or profile.get("trading_mode") != "futures"
        or profile.get("margin_mode") != "isolated"
        or profile.get("pairs") != [capability.pair]
        or snapshot.timeframe != capability.timeframe
        or profile.get("timeframe") != capability.timeframe
        or isinstance(profile.get("taker_fee_rate"), bool)
        or not isinstance(profile.get("taker_fee_rate"), (int, float))
        or float(profile["taker_fee_rate"]) != capability.base_fee
        or profile != frozen
        or snapshot.profile_id != frozen.get("id")
        or _sha256(pilot.canonical(profile)) != capability.profile_snapshot_sha256
    ):
        raise SearchCampaignError(
            "candidate_profile_mismatch",
            "Candidate Profile does not match the frozen Search pair/timeframe/base fee",
        )


def _bound_candidate(
    connection: sqlite3.Connection,
    candidate_id: str,
    capability: FrozenSearchCapability,
) -> ApprovedCandidateSnapshot:
    try:
        snapshot = load_approved_candidate_snapshot(connection, candidate_id)
        analyze_bounded_causal_strategy(
            snapshot.code_text,
            snapshot.class_name,
            expected_timeframe=str(capability.timeframe),
        )
        _profile_bound(snapshot, capability)
    except GenerationContractError as exc:
        raise SearchCampaignError(exc.code, exc.message, status=exc.status) from exc
    except BoundedStrategyError as exc:
        raise SearchCampaignError("BLOCKED_SECURITY", exc.message) from exc
    return snapshot


def _candidate_public(snapshot: ApprovedCandidateSnapshot, role: str) -> dict[str, Any]:
    return {
        "candidate_id": snapshot.candidate_id, "display_name": snapshot.display_name,
        "class_name": snapshot.class_name, "profile_id": snapshot.profile_id,
        "strategy_family": snapshot.strategy_family, "parent_candidate_id": snapshot.parent_candidate_id,
        "strategy_sha256": snapshot.code_sha256, "status": "READY", "role": role,
    }


def _load_eligible_candidates(
    database_path: PathLike,
    capability: FrozenSearchCapability,
    state: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], Optional[ApprovedCandidateSnapshot]]:
    if state.get("status") not in {"SEARCH_READY", "SEARCH_ROUND_READY_FOR_CHILDREN"}:
        return [], None
    try:
        with closing(get_connection(database_path, read_only=True)) as connection:
            connection.execute("BEGIN")
            rows = connection.execute("""SELECT c.id FROM candidates c JOIN generation_runs g
                ON g.id=c.generation_run_id WHERE g.source='CODEX' AND g.status='COMPLETED'
                ORDER BY c.created_at,c.id""")
            result: list[dict[str, Any]] = []
            parent: Optional[ApprovedCandidateSnapshot] = None
            if state["status"] == "SEARCH_ROUND_READY_FOR_CHILDREN":
                selected = state.get("selected_parent")
                if not isinstance(selected, Mapping):
                    raise SearchCampaignError("search_state_invalid", "Selected parent is unavailable")
                parent = _bound_candidate(connection, str(selected.get("candidate_id")), capability)
                if parent.strategy_family != selected.get("mechanism"):
                    raise SearchCampaignError("search_state_invalid", "Selected parent binding changed")
            for row in rows:
                try:
                    snapshot = _bound_candidate(connection, str(row[0]), capability)
                except SearchCampaignError:
                    continue
                family = snapshot.strategy_family
                if not isinstance(family, str) or pilot.SAFE_ID.fullmatch(family) is None:
                    continue
                if state["status"] == "SEARCH_READY" and snapshot.parent_candidate_id is None:
                    result.append(_candidate_public(snapshot, "MECHANISM_SEED"))
                elif parent is not None and snapshot.parent_candidate_id == parent.candidate_id and snapshot.profile_id == parent.profile_id and family == parent.strategy_family:
                    result.append(_candidate_public(snapshot, "SINGLE_FACTOR_CHILD"))
            return result, parent
    except SearchCampaignError:
        raise
    except (FileNotFoundError, OSError, RuntimeError, sqlite3.Error) as exc:
        raise SearchCampaignError("BLOCKED_DATA", "database is unavailable", status=503) from exc


def _ledger_state(root: Path, campaign_id: str) -> tuple[list[dict[str, Any]], bytes]:
    path = root / pilot.SEARCH_TRIALS
    if not path.exists() and not path.is_symlink():
        return [], b""
    try:
        with pilot._open_search_ledger(path, create=False) as ledger:
            try:
                fcntl.flock(ledger.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise SearchCampaignError(
                    "search_state_busy",
                    "Search trial ledger is actively being written",
                    status=409,
                ) from exc
            try:
                ledger.seek(0)
                data = ledger.read(2 * 1024 * 1024 + 1)
                if len(data) > 2 * 1024 * 1024:
                    raise pilot.PilotError("Search trial ledger is too large")
                records = pilot._load_search_records(io.BytesIO(data), campaign_id)
            finally:
                fcntl.flock(ledger.fileno(), fcntl.LOCK_UN)
    except SearchCampaignError:
        raise
    except pilot.PilotError as exc:
        raise SearchCampaignError("search_state_invalid", "Search trial ledger is invalid") from exc
    return records, data


def _round_one_plan(
    capability: FrozenSearchCapability, current: Mapping[str, Any]
) -> Mapping[str, Any]:
    """Load Round 1 only from its immutable campaign-file snapshot."""
    if capability.search_root is None:
        raise SearchCampaignError(
            "search_state_invalid", "Round 1 campaign binding is unavailable"
        )
    data = _read_regular(
        capability.search_root / ROUND_ONE_CAMPAIGN, "Round 1 campaign"
    )
    try:
        document = _strict_json(data, "Round 1 campaign")
        if pilot.canonical(document) != data:
            raise ValueError("non-canonical Round 1 campaign")
        prior = pilot._load_search_campaign(document, data)
    except (KeyError, TypeError, ValueError, pilot.PilotError) as exc:
        raise SearchCampaignError(
            "search_state_invalid", "Round 1 campaign is invalid"
        ) from exc
    if (
        prior["round"] != 1
        or prior["campaign_id"] != current["campaign_id"]
        or prior["_contract_sha256"] != current["_contract_sha256"]
        or (current["round"] == 1 and prior != current)
    ):
        raise SearchCampaignError(
            "search_state_invalid", "Round 1 campaign binding changed"
        )
    return prior


def _validate_records(
    records: Sequence[Mapping[str, Any]], current: Mapping[str, Any], prior: Mapping[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], bool]:
    plans = {1: prior, int(current["round"]): current}
    receipts: list[dict[str, Any]] = []
    trials: list[dict[str, Any]] = []
    active_round: Optional[int] = None
    reserved: list[int] = []
    round_trials: list[dict[str, Any]] = []
    next_attempt = 1
    completed_round = 0
    try:
        for index, item in enumerate(records):
            kind = item["record_type"]
            round_number = int(item["round"])
            plan = plans.get(round_number)
            if kind == "ROUND_STARTED":
                expected = list(range(next_attempt, next_attempt + len(plan["candidates"]))) if plan else []
                if active_round is not None or round_number != completed_round + 1 or item.get("campaign_sha256") != plan["_sha256"] or item.get("attempt_numbers") != expected:
                    raise ValueError("round start")
                active_round, reserved, round_trials = round_number, expected, []
            elif kind == "TRIAL":
                if active_round != round_number or len(round_trials) >= len(reserved) or item.get("attempt_number") != reserved[len(round_trials)]:
                    raise ValueError("trial order")
                candidate = plan["candidates"][len(round_trials)] if plan else None
                if candidate is None or any(
                    item.get(field) != candidate.get(field)
                    for field in ("candidate_id", "class_name", "mechanism", "strategy_sha256", "relationship", "changed_factor")
                ):
                    raise ValueError("trial Candidate binding")
                copied = dict(item)
                round_trials.append(copied)
                trials.append(copied)
            elif kind == "ROUND_RECEIPT":
                current_results = [
                    {
                        key: value
                        for key, value in trial.items()
                        if key
                        not in {
                            "schema", "record_type", "campaign_id", "round",
                            "attempt_number",
                        }
                    }
                    for trial in round_trials
                ]
                expected_brief, expected_status, _ = pilot._search_round_outcome(
                    plan,
                    trials,
                    current_results,
                    len(trials) - len(round_trials),
                )
                if (
                    active_round != round_number
                    or len(round_trials) != len(reserved)
                    or item.get("campaign_sha256") != plan["_sha256"]
                    or item.get("contract_sha256") != plan["_contract_sha256"]
                    or item.get("ledger_prefix_sha256")
                    != _sha256(
                        b"".join(
                            pilot.canonical(value) for value in records[:index]
                        )
                    )
                    or item.get("status") != expected_status
                    or item.get("brief") != expected_brief
                ):
                    raise ValueError("receipt binding")
                receipts.append(dict(item))
                completed_round, active_round, next_attempt = round_number, None, reserved[-1] + 1
    except (IndexError, KeyError, TypeError, ValueError) as exc:
        raise SearchCampaignError("search_state_invalid", "Search ledger order/binding is invalid") from exc
    if current["round"] == 2:
        if not receipts or receipts[0].get("status") != "SEARCH_ROUND_READY_FOR_CHILDREN":
            raise SearchCampaignError("search_state_invalid", "Round 2 lacks its Round 1 receipt")
        parent = receipts[0].get("brief", {}).get("selected_parent")
        try:
            bound = current.get("previous_round_receipt_sha256") == _sha256(pilot.canonical(receipts[0])) and current.get("parent") == pilot._search_identity(parent)
        except (KeyError, TypeError) as exc:
            raise SearchCampaignError("search_state_invalid", "Round 2 parent is invalid") from exc
        if not bound:
            raise SearchCampaignError("search_state_invalid", "Round 2 receipt binding changed")
    return receipts, trials, completed_round < int(current["round"])


def _validate_profile_artifact_evidence(
    root: Path, trials: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    projection = []
    for trial in trials:
        evidence = trial.get("evidence")
        if trial.get("technical_status") != "VALID":
            if evidence is not None:
                raise SearchCampaignError(
                    "search_state_invalid", "Invalid Search trial has artifact evidence"
                )
        else:
            if not pilot._projection_evidence_shape(evidence, trial):
                raise SearchCampaignError(
                    "search_state_invalid", "Search artifact evidence is incomplete"
                )
            try:
                for label in ("archive", "result"):
                    pointer = evidence[label]
                    data = _read_regular(
                        pilot.safe_file(root, pointer["path"], f"Search {label}"),
                        f"Search {label}",
                    )
                    if _sha256(data) != pointer["sha256"]:
                        raise ValueError(label)
            except (KeyError, TypeError, ValueError, pilot.PilotError) as exc:
                raise SearchCampaignError(
                    "search_state_invalid", "Search artifact evidence changed"
                ) from exc
        projection.append({key: trial.get(key) for key in PUBLIC_TRIAL_FIELDS})
    return projection


def _verified_projection(
    root: Path,
    current: Mapping[str, Any],
    prior: Mapping[str, Any],
    terminal: Mapping[str, Any],
    terminal_bytes: bytes,
    receipts: Sequence[Mapping[str, Any]],
    trials: Sequence[Mapping[str, Any]],
    ledger_bytes: bytes,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    evidence: dict[str, Any] = {
        "terminal": {"path": pilot.SEARCH_TERMINAL, "sha256": _sha256(terminal_bytes)},
        "attempts": _validate_profile_artifact_evidence(root, trials),
    }
    if (root / pilot.SEARCH_TRIALS).is_file():
        evidence["trials"] = {"path": pilot.SEARCH_TRIALS, "sha256": _sha256(ledger_bytes)}
    if terminal.get("status") == "SEARCH_BLOCKED":
        if str(root) in str(terminal.get("error")):
            raise SearchCampaignError("search_state_invalid", "Search blocked terminal is invalid")
    elif (
        not receipts
        or receipts[-1].get("round") != current["round"]
        or terminal.get("round_receipt_sha256") != _sha256(pilot.canonical(receipts[-1]))
    ):
        raise SearchCampaignError("search_state_invalid", "Search terminal lacks its round receipt")
    request = pilot.search_projection_request(
        [prior] if current["round"] == 1 else [prior, current]
    )
    try:
        verified = pilot.verify_search_terminal_projection(request, terminal, evidence)
    except pilot.PilotError as exc:
        raise SearchCampaignError(
            "search_state_invalid", "Search terminal projection is invalid"
        ) from exc
    return request, evidence, verified


def _public_projection(value: Any, fields: Sequence[str]) -> Optional[dict[str, Any]]:
    if not isinstance(value, Mapping):
        return None
    return {key: value.get(key) for key in fields if key in value}


def _base_public_state(capability: FrozenSearchCapability, status_value: str) -> dict[str, Any]:
    return {
        "status": status_value, "campaign_id": None, "current_round": None,
        "attempts": [], "frozen_ranking": [],
        "budget": {
            "maximum_attempts": pilot.SEARCH_MAX_ATTEMPTS,
            "active_attempt_limit": pilot.PROFILE_ACTIVE_ATTEMPTS,
            "consumed_total": 0,
            "remaining": pilot.PROFILE_ACTIVE_ATTEMPTS,
            "hard_remaining": pilot.SEARCH_MAX_ATTEMPTS,
        },
        "selected_parent": None, "search_finalist": None,
        "message": capability.reason if status_value.startswith("BLOCKED_") else "Search-only campaign is ready",
        "boundaries": {
            "holdout": "SEALED_UNREAD",
            "holdout_stress": "SEALED_UNREAD",
            "research_runs_created_by_search": 0,
            "backtest_executions_created_by_search": 0,
            "releases_created_by_search": 0,
        },
    }


def _future_or_forbidden_artifact(root: Path, round_number: int) -> bool:
    future = False
    forbidden_names = {pilot.PLAN, pilot.WINDOW, pilot.TERMINAL, "workspace", "artifacts", "selected-input", "scenario-opens"}
    try:
        for child in root.iterdir():
            name = child.name.lower()
            if name in forbidden_names or any(token in name for token in ("development", "validation", "holdout", "stress")):
                raise SearchCampaignError("search_state_invalid", "Search root contains a later-phase artifact")
            future = future or (round_number == 1 and "round-2" in name)
        strategies = root / STRATEGIES
        if round_number == 1 and strategies.is_dir():
            future = future or any(item.name.startswith("round-2-") for item in strategies.iterdir())
    except OSError as exc:
        raise SearchCampaignError("search_state_invalid", "Search root cannot be inspected") from exc
    return future


def load_public_search_state(
    capability: FrozenSearchCapability, *, active: bool = False
) -> dict[str, Any]:
    if capability.status != "READY" or capability.search_root is None:
        return _base_public_state(capability, capability.status)
    _require_frozen_identity(capability)
    root = capability.search_root
    campaign_path = root / pilot.SEARCH_CAMPAIGN
    if not campaign_path.exists() and not campaign_path.is_symlink():
        _future_or_forbidden_artifact(root, 1)
        names = {item.name for item in root.iterdir()}
        if names == {pilot.ACQUISITION}:
            return _base_public_state(capability, "SEARCH_READY")
        raise SearchCampaignError(
            "BLOCKED_DATA", "Fresh Search root must contain only acquisition", status=503
        )
    try:
        plan = pilot.load_plan(root, pilot.SEARCH_CAMPAIGN)
    except (OSError, pilot.PilotError):
        state = _base_public_state(capability, "INTERRUPTED")
        state["message"] = "Search campaign contract is incomplete or invalid"
        return state
    campaign_id = str(plan["campaign_id"])
    terminal_path = root / pilot.SEARCH_TERMINAL
    terminal = None
    if terminal_path.exists() or terminal_path.is_symlink():
        terminal_bytes = _read_regular(terminal_path, "Search terminal")
        terminal = _strict_json(terminal_bytes, "Search terminal")
        if pilot.canonical(terminal) != terminal_bytes:
            raise SearchCampaignError(
                "search_state_invalid", "Search terminal is not canonical"
            )
    if _future_or_forbidden_artifact(root, int(plan["round"])):
        state = _base_public_state(capability, "INTERRUPTED")
        state["campaign_id"] = campaign_id
        state["current_round"] = int(plan["round"])
        state["message"] = "Search contains a partial next-round preparation"
        return state
    prior = _round_one_plan(capability, plan)
    try:
        records, ledger_bytes = _ledger_state(root, campaign_id)
    except SearchCampaignError as exc:
        if exc.code != "search_state_busy":
            raise
        state = _base_public_state(capability, "RUNNING")
        state["campaign_id"] = campaign_id
        state["current_round"] = int(plan["round"])
        state["message"] = "Search round is running"
        return state
    receipts, trials, partial = _validate_records(records, plan, prior)
    latest_receipt = receipts[-1] if receipts else None
    database_changed = False
    if terminal is not None:
        _verified_projection(
            root, plan, prior, terminal, terminal_bytes, receipts, trials, ledger_bytes
        )
        if capability.database_path is None:
            raise SearchCampaignError(
                "search_generation_invalid",
                "Search terminal database binding is unavailable",
            )
        file_projection = _terminal_projection(capability)
        assert file_projection is not None
        persisted_projection = _load_terminal_generation(
            capability.database_path, file_projection
        )
        database_changed = (
            persisted_projection is not None
            and persisted_projection.get("error_code") == SEARCH_DATABASE_CHANGED
        )
    else:
        _validate_profile_artifact_evidence(root, trials)
    projection_missing = terminal is not None and persisted_projection is None
    if projection_missing:
        status_value = "RUNNING" if active else "INTERRUPTED"
    elif database_changed:
        status_value = "FAILED"
    elif terminal is not None:
        status_value = (
            "FAILED"
            if terminal.get("status") == "SEARCH_BLOCKED"
            else str(terminal["status"])
        )
    elif partial:
        status_value = "RUNNING" if active else "INTERRUPTED"
    elif latest_receipt is not None:
        status_value = str(latest_receipt.get("status"))
        if latest_receipt.get("round") != 1 or status_value != "SEARCH_ROUND_READY_FOR_CHILDREN":
            raise SearchCampaignError("search_state_invalid", "Search receipt/terminal state is invalid")
    else:
        status_value = "INTERRUPTED"
    state = _base_public_state(capability, status_value)
    state["campaign_id"] = campaign_id
    state["current_round"] = int(plan["round"])
    state["attempts"] = [_public_projection(item, PUBLIC_TRIAL_FIELDS) for item in trials]
    if latest_receipt is not None:
        brief = latest_receipt.get("brief", {})
        campaign = brief.get("campaign", {}) if isinstance(brief, Mapping) else {}
        budget = campaign.get("budget") if isinstance(campaign, Mapping) else None
        ranking = brief.get("frozen_ranking") if isinstance(brief, Mapping) else None
        if isinstance(budget, Mapping):
            state["budget"] = dict(budget)
        if isinstance(ranking, list):
            state["frozen_ranking"] = [dict(item) for item in ranking if isinstance(item, Mapping)]
        selected = _public_projection(brief.get("selected_parent"), PUBLIC_IDENTITY_FIELDS) if isinstance(brief, Mapping) else None
        if selected is not None:
            selected["profile_id"] = capability.profile_snapshot.get("id") if capability.profile_snapshot else None
        state["selected_parent"] = selected
    if (
        terminal is not None
        and not database_changed
        and not projection_missing
    ):
        state["search_finalist"] = _public_projection(terminal.get("search_finalist"), PUBLIC_IDENTITY_FIELDS)
    if database_changed or (
        terminal is not None and terminal.get("status") == "SEARCH_BLOCKED"
    ):
        state["budget"].update(
            consumed_total=None,
            remaining=None,
            hard_remaining=None,
        )
    if database_changed:
        state["error_code"] = SEARCH_DATABASE_CHANGED
    messages = {
        "RUNNING": "Search round is running",
        "SEARCH_ROUND_READY_FOR_CHILDREN": "Round 1 selected parent is frozen; generate and approve children manually",
        "SEARCH_FINALIST_FROZEN": "Round 2 finalist is frozen; Development remains a separate manual action",
        "SEARCH_TERMINATED_NO_PARENT": "Round 1 ended with no valid parent",
        "SEARCH_TERMINATED_NO_FINALIST": "Round 2 ended with no finalist; thresholds were not changed",
        "FAILED": "Search failed closed; private diagnostics are not returned",
        "INTERRUPTED": "Search state is partial or interrupted; it will not be replayed",
    }
    state["message"] = messages.get(status_value, state["message"])
    return state


def recover_interrupted_search(
    capability: FrozenSearchCapability, database_path: PathLike
) -> dict[str, Any]:
    state = load_public_search_state(capability, active=False)
    campaign_id = state.get("campaign_id")
    if not isinstance(campaign_id, str):
        return state
    if state.get("status") == "INTERRUPTED":
        projection = _terminal_projection(capability)
        if projection is not None and projection["status"] == "COMPLETED":
            # A successful engine terminal without its atomic DB adjudication
            # has lost the in-memory baseline.  Recovery cannot infer success.
            return state
        return fail_search_campaign(
            database_path,
            capability,
            campaign_id,
            "SERVER_RESTART",
        )
    return state


def _blocked_search_context(
    capability: FrozenSearchCapability, message: str
) -> dict[str, Any]:
    status_value = (
        capability.status
        if capability.status == "BLOCKED_INSUFFICIENT_CAPACITY"
        else "BLOCKED_DATA"
    )
    state = _base_public_state(capability, status_value)
    state["message"] = message
    public_capability = capability.public()
    public_capability["status"] = status_value
    public_capability["reason"] = message
    return {
        "capability": public_capability,
        "state": state,
        "candidates": [],
        "codex_parent_lock": None,
        "limits": {
            "maximum_candidates_per_round": 2,
            "maximum_attempts": pilot.SEARCH_MAX_ATTEMPTS,
            "active_attempt_limit": pilot.PROFILE_ACTIVE_ATTEMPTS,
        },
        "boundaries": state["boundaries"],
    }


def load_search_context(
    database_path: PathLike,
    capability: FrozenSearchCapability,
    *,
    active: bool = False,
) -> dict[str, Any]:
    try:
        state = load_public_search_state(capability, active=active)
        candidates, parent = ([], None) if capability.status != "READY" else _load_eligible_candidates(database_path, capability, state)
        selected = state.get("selected_parent")
        parent_lock = None
        if state.get("status") == "SEARCH_ROUND_READY_FOR_CHILDREN" and isinstance(selected, dict) and parent is not None:
            if parent.strategy_family != selected.get("mechanism"):
                raise SearchCampaignError("search_state_invalid", "Selected parent binding changed")
            state["selected_parent"] = {
                **selected,
                "profile_id": parent.profile_id,
                "display_name": parent.display_name,
            }
            parent_lock = {
                "parent_candidate_id": parent.candidate_id,
                "profile_id": parent.profile_id,
                "strategy_family": parent.strategy_family,
            }
        terminal_projection = (
            _terminal_projection(capability)
            if capability.profile_snapshot is not None and state.get("campaign_id")
            else None
        )
        if terminal_projection is not None:
            terminal_projection = _load_terminal_generation(
                database_path, terminal_projection
            )
            if (
                terminal_projection is not None
                and terminal_projection.get("error_code")
                == SEARCH_DATABASE_CHANGED
            ):
                state["status"] = "FAILED"
                state["search_finalist"] = None
                state["error_code"] = SEARCH_DATABASE_CHANGED
                state["message"] = (
                    "Search failed closed; private diagnostics are not returned"
                )
                state["budget"].update(
                    consumed_total=None,
                    remaining=None,
                    hard_remaining=None,
                )
        return {
            "capability": capability.public(),
            "state": state,
            "generation_run": (
                {
                    key: value
                    for key, value in terminal_projection.items()
                    if not key.startswith("_")
                }
                if terminal_projection is not None
                else None
            ),
            "candidates": candidates,
            "codex_parent_lock": parent_lock,
            "limits": {
                "maximum_candidates_per_round": 2,
                "maximum_attempts": pilot.SEARCH_MAX_ATTEMPTS,
                "active_attempt_limit": pilot.PROFILE_ACTIVE_ATTEMPTS,
            },
            "boundaries": state["boundaries"],
        }
    except SearchCampaignError as exc:
        # Search is an optional local capability.  Corrupt Search receipts or a
        # now-unavailable Search database projection must not block the rest of
        # Console, Codex generation, or Development.
        return _blocked_search_context(capability, exc.message)


def _materialize_strategy(
    capability: FrozenSearchCapability,
    snapshot: ApprovedCandidateSnapshot,
    round_number: int,
) -> str:
    assert capability.search_root is not None
    strategy_file = _planned_strategy_file(snapshot, round_number)
    name = Path(strategy_file).name
    strategies = capability.search_root / STRATEGIES
    try:
        strategies.mkdir(mode=0o700, exist_ok=True)
        if strategies.is_symlink() or not strategies.is_dir():
            raise OSError("unsafe strategies directory")
        data = snapshot.code_text.encode("utf-8", "strict")
        if _sha256(data) != snapshot.code_sha256:
            raise SearchCampaignError("candidate_binding_changed", "Candidate source binding changed")
        with (strategies / name).open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
            os.fchmod(handle.fileno(), 0o400)
    except (OSError, UnicodeEncodeError) as exc:
        raise SearchCampaignError("materialize_failed", "Candidate source could not be materialized", status=500) from exc
    return strategy_file


def _planned_strategy_file(
    snapshot: ApprovedCandidateSnapshot, round_number: int
) -> str:
    return f"{STRATEGIES}/round-{round_number}-{snapshot.candidate_id}.py"


def _candidate_plan(
    snapshot: ApprovedCandidateSnapshot,
    strategy_file: str,
    *,
    round_number: int,
    changed_factor: Optional[str],
    parent_sha256: Optional[str],
) -> dict[str, Any]:
    return {
        "candidate_id": snapshot.candidate_id,
        "class_name": snapshot.class_name,
        "mechanism": snapshot.strategy_family,
        "relationship": "MECHANISM_SEED" if round_number == 1 else "SINGLE_FACTOR_CHILD",
        "changed_factor": changed_factor,
        "parent_strategy_sha256": parent_sha256,
        "strategy_file": strategy_file,
        "strategy_sha256": snapshot.code_sha256,
        "generation_run_id": snapshot.generation_run_id,
        "profile_id": snapshot.profile_id,
    }


def _strategy_analyses(
    snapshots: Sequence[ApprovedCandidateSnapshot], capability: FrozenSearchCapability
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for snapshot in snapshots:
        analysis = analyze_bounded_causal_strategy(
            snapshot.code_text,
            snapshot.class_name,
            expected_timeframe=str(capability.timeframe),
        )
        result[snapshot.candidate_id] = {
            "timeframe": analysis.timeframe,
            "startup_candle_count": analysis.startup_candle_count,
            "maximum_lookback": analysis.max_lookback,
        }
    return result


def _single_literal_factor_change(
    parent: ApprovedCandidateSnapshot,
    child: ApprovedCandidateSnapshot,
    changed_factor: str,
) -> bool:
    """Accept a child only when one literal class setting changed."""
    if not changed_factor.isidentifier():
        return False

    def normalized(source: str, class_name: str) -> tuple[type, Any, str]:
        tree = ast.parse(source)
        classes = [
            item for item in tree.body
            if isinstance(item, ast.ClassDef) and item.name == class_name
        ]
        if len(classes) != 1:
            raise ValueError("strategy class")
        assignments = [
            item for item in classes[0].body
            if isinstance(item, ast.Assign)
            and len(item.targets) == 1
            and isinstance(item.targets[0], ast.Name)
            and item.targets[0].id == changed_factor
        ]
        if len(assignments) != 1:
            raise ValueError("literal factor")
        node = assignments[0].value
        if changed_factor == "startup_candle_count":
            if (
                not isinstance(node, ast.Constant)
                or isinstance(node.value, bool)
                or type(node.value) is not int
                or node.value <= 0
            ):
                raise ValueError("lookback factor")
            value = node.value
            rolling_literals: list[ast.Constant] = []
            for candidate in ast.walk(classes[0]):
                if (
                    not isinstance(candidate, ast.Call)
                    or not isinstance(candidate.func, ast.Attribute)
                    or candidate.func.attr != "mean"
                    or candidate.args
                    or candidate.keywords
                    or not isinstance(candidate.func.value, ast.Call)
                ):
                    continue
                rolling = candidate.func.value
                if (
                    not isinstance(rolling.func, ast.Attribute)
                    or rolling.func.attr != "rolling"
                    or len(rolling.args) != 1
                    or rolling.keywords
                    or not isinstance(rolling.args[0], ast.Constant)
                    or isinstance(rolling.args[0].value, bool)
                    or type(rolling.args[0].value) is not int
                    or rolling.args[0].value != value
                ):
                    continue
                rolling_literals.append(rolling.args[0])
            if not rolling_literals:
                raise ValueError("lookback factor")
            classes[0].name = "FrozenStrategy"
            assignments[0].value = ast.Constant(value="__CHANGED_FACTOR__")
            for literal in rolling_literals:
                literal.value = "__CHANGED_FACTOR__"
            return int, value, ast.dump(tree, include_attributes=False)
        if not isinstance(node, ast.Constant) and not (
            isinstance(node, ast.UnaryOp)
            and isinstance(node.op, (ast.UAdd, ast.USub))
            and isinstance(node.operand, ast.Constant)
            and not isinstance(node.operand.value, bool)
            and isinstance(node.operand.value, (int, float))
        ):
            raise ValueError("literal factor")
        value = ast.literal_eval(node)
        classes[0].name = "FrozenStrategy"
        assignments[0].value = ast.Constant(value="__CHANGED_FACTOR__")
        return type(value), value, ast.dump(tree, include_attributes=False)

    try:
        parent_type, parent_value, parent_tree = normalized(
            parent.code_text, parent.class_name
        )
        child_type, child_value, child_tree = normalized(
            child.code_text, child.class_name
        )
    except (SyntaxError, ValueError):
        return False
    return (
        parent_type is child_type
        and parent_value != child_value
        and parent_tree == child_tree
    )


def _search_plan(
    capability: FrozenSearchCapability,
    campaign_id: str,
    round_number: int,
    candidates: Sequence[Mapping[str, Any]],
    *,
    receipt_sha256: Optional[str] = None,
    parent: Optional[Mapping[str, Any]] = None,
    strategy_analyses: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    profile = capability.profile_snapshot
    if (
        profile is None
        or capability.search_timerange is None
        or capability.development_timerange is None
        or capability.pre_roll_candles is None
    ):
        raise SearchCampaignError("BLOCKED_DATA", capability.reason, status=503)
    try:
        contract = pilot.profile_search_contract(
            profile,
            capability.search_timerange,
            capability.development_timerange,
            capability.pre_roll_candles,
            capability.economic_gate,
        )
    except pilot.PilotError as exc:
        raise SearchCampaignError(
            "BLOCKED_DATA", "Frozen Profile Search contract is invalid", status=503
        ) from exc
    if contract["profile_snapshot_sha256"] != capability.profile_snapshot_sha256:
        raise SearchCampaignError(
            "BLOCKED_DATA", "Frozen Profile Search contract changed", status=503
        )
    plan = {
        "schema": pilot.SEARCH_SCHEMA, "campaign_id": campaign_id,
        "freqtrade_version": SUPPORTED_FREQTRADE_VERSION, "round": round_number,
        "previous_round_receipt_sha256": receipt_sha256,
        "data_provenance_sha256": capability.data_provenance_sha256,
        "budget": {"maximum_attempts": pilot.SEARCH_MAX_ATTEMPTS},
        "ranking": list(pilot.SEARCH_RANKING),
        "parent": parent, "candidates": list(candidates),
        **contract,
        "strategy_analyses": dict(strategy_analyses or {}),
        "active_attempt_limit": pilot.PROFILE_ACTIVE_ATTEMPTS,
    }
    return plan


def _write_plan(capability: FrozenSearchCapability, plan: Mapping[str, Any], round_number: int) -> None:
    if round_number == 1:
        _atomic_json_at(
            capability._directory_fd,
            ROUND_ONE_CAMPAIGN,
            plan,
            replace=False,
        )
    _atomic_json_at(
        capability._directory_fd,
        pilot.SEARCH_CAMPAIGN,
        plan,
        replace=round_number == 2,
    )


def _validate_plan_before_materialization(
    capability: FrozenSearchCapability, plan: Mapping[str, Any]
) -> None:
    plan_bytes = pilot.canonical(plan)
    document = json.loads(plan_bytes)
    try:
        pilot._load_search_campaign(document, plan_bytes)
        assert capability.search_root is not None
        pilot.verify_data(capability.search_root, document)
    except pilot.PilotError as exc:
        raise SearchCampaignError(
            "invalid_search_request", "Search campaign plan is invalid", status=400
        ) from exc


def _argv(capability: FrozenSearchCapability) -> Tuple[str, ...]:
    assert capability.freqtrade_python is not None
    assert capability.freqtrade_source is not None
    assert capability.search_root is not None
    return (str(capability.freqtrade_python), str(BOUNDED_RESEARCH_SCRIPT.resolve(strict=True)),
            "screen-search", "--campaign-root", str(capability.search_root),
            "--freqtrade-python", str(capability.freqtrade_python),
            "--freqtrade-source", str(capability.freqtrade_source))


def _prepare_transaction(database_path: PathLike) -> tuple[sqlite3.Connection, str]:
    try:
        connection = get_connection(database_path, read_only=True)
        connection.execute("BEGIN")
        return connection, _database_digest_connection(connection)
    except SearchCampaignError:
        raise
    except (FileNotFoundError, OSError, RuntimeError, sqlite3.Error) as exc:
        raise SearchCampaignError("BLOCKED_DATA", "database is unavailable", status=503) from exc


def _finalist_projection_binding(
    request: Mapping[str, Any],
    terminal: Mapping[str, Any],
    evidence: Mapping[str, Any],
    verified: Mapping[str, Any],
) -> tuple[dict[str, Any], Mapping[str, Any]]:
    rounds = verified["round_contracts"]
    finalist = verified["finalist"]
    candidates = [
        item
        for contract in rounds
        for item in contract["candidates"]
        if item["candidate_id"] == finalist["candidate_id"]
    ]
    if len(rounds) != 2 or len(candidates) != 1:
        raise SearchCampaignError(
            "search_generation_invalid", "Search finalist projection is invalid"
        )
    round_one, candidate = rounds[0], candidates[0]
    binding = {
            "candidate_id": candidate["candidate_id"],
            "generation_run_id": candidate["generation_run_id"],
            "source_sha256": candidate["strategy_sha256"],
            "profile_id": candidate["profile_id"],
            "search_generation_id": request["campaign_id"],
            "profile_snapshot_sha256": round_one["profile_snapshot_sha256"],
            "search_timerange": round_one["search_timerange"],
            "development_timerange": round_one["development_timerange"],
            "finalist_gate": round_one["finalist_gate"],
            "terminal_sha256": evidence["terminal"]["sha256"],
            "trials_sha256": evidence["trials"]["sha256"],
            "round_receipt_sha256": terminal["round_receipt_sha256"],
            "projection_sha256": pilot.search_projection_sha256(
                request, terminal, evidence
            ),
        }
    if "economic_gate" in round_one:
        binding["economic_gate"] = pilot.validate_profile_economic_gate(
            round_one["economic_gate"]
        )
    return binding, candidate


def _terminal_projection(
    capability: FrozenSearchCapability,
) -> Optional[dict[str, Any]]:
    """Read and verify the file-authoritative terminal, if one exists."""
    if capability.status != "READY" or capability.search_root is None:
        raise SearchCampaignError("BLOCKED_DATA", capability.reason, status=503)
    _require_frozen_identity(capability)
    root = capability.search_root
    terminal_path = root / pilot.SEARCH_TERMINAL
    if not terminal_path.exists() and not terminal_path.is_symlink():
        return None
    try:
        current = pilot.load_plan(root, pilot.SEARCH_CAMPAIGN)
    except (OSError, pilot.PilotError) as exc:
        raise SearchCampaignError("search_state_invalid", "Search terminal plan is invalid") from exc
    round_one = _round_one_plan(capability, current)
    terminal_bytes = _read_regular(terminal_path, "Search terminal")
    terminal = _strict_json(terminal_bytes, "Search terminal")
    if pilot.canonical(terminal) != terminal_bytes:
        raise SearchCampaignError("search_state_invalid", "Search terminal is not canonical")
    terminal_status = terminal.get("status")
    if terminal_status not in {"SEARCH_BLOCKED", "SEARCH_FINALIST_FROZEN",
                               "SEARCH_TERMINATED_NO_PARENT", "SEARCH_TERMINATED_NO_FINALIST"}:
        raise SearchCampaignError("search_state_invalid", "Search terminal evidence is incomplete")
    finalist_binding = None
    _future_or_forbidden_artifact(root, int(current["round"]))
    records, ledger_bytes = _ledger_state(root, str(current["campaign_id"]))
    receipts, trials, _ = _validate_records(records, current, round_one)
    request, evidence, verified = _verified_projection(
        root,
        current,
        round_one,
        terminal,
        terminal_bytes,
        receipts,
        trials,
        ledger_bytes,
    )
    if terminal_status != "SEARCH_BLOCKED":
        finalist = terminal.get("search_finalist")
        if isinstance(finalist, Mapping):
            try:
                finalist_binding, _ = _finalist_projection_binding(
                    request, terminal, evidence, verified
                )
            except SearchCampaignError as exc:
                raise SearchCampaignError(
                    "search_state_invalid", "Finalist Candidate binding is missing"
                ) from exc
    timestamp = terminal.get("created_at_utc")
    if not isinstance(timestamp, str) or not timestamp:
        raise SearchCampaignError("search_state_invalid", "Search terminal timestamp is invalid")
    return {
        "id": str(terminal["campaign_id"]),
        "status": "FAILED" if terminal_status == "SEARCH_BLOCKED" else "COMPLETED",
        "profile_id": round_one["profile_snapshot"]["id"],
        "finished_at": timestamp, "terminal": terminal, "evidence": evidence,
        "finalist_binding": finalist_binding,
        "_request": request,
        "_report": {"evidence": evidence, "finalist_binding": finalist_binding},
        "_error": terminal.get("error") if terminal_status == "SEARCH_BLOCKED" else None,
    }


def _terminal_generation_values(
    projection: Mapping[str, Any], *, database_changed: bool = False
) -> dict[str, Any]:
    """Return the one exact schema-v1 row allowed for this terminal verdict."""
    report = dict(projection["_report"])
    status_value = projection["status"]
    error_message = projection["_error"]
    if database_changed:
        report["finalist_binding"] = None
        status_value = "FAILED"
        error_message = SEARCH_DATABASE_CHANGED
    timestamp = projection["finished_at"]
    return {
        "id": projection["id"],
        "research_profile_id": projection["profile_id"],
        "source": "MANUAL",
        "model": None,
        "status": status_value,
        "request_json": pilot.canonical(projection["_request"]).decode("utf-8"),
        "response_raw_text": None,
        "response_json": pilot.canonical(projection["terminal"]).decode("utf-8"),
        "returned_strategy_count": 0,
        "parse_report_json": pilot.canonical(report).decode("utf-8"),
        "error_message": error_message,
        **dict.fromkeys(
            ("started_at", "finished_at", "created_at", "updated_at"),
            timestamp,
        ),
    }


def _row_matches_terminal_generation(
    row: sqlite3.Row, expected: Mapping[str, Any]
) -> bool:
    return set(row.keys()) == set(expected) and all(
        row[key] == value for key, value in expected.items()
    )


def _public_terminal_generation(
    projection: Mapping[str, Any], *, database_changed: bool
) -> dict[str, Any]:
    public = {
        key: value for key, value in projection.items() if not key.startswith("_")
    }
    if database_changed:
        terminal = dict(public["terminal"])
        terminal["search_finalist"] = None
        public.update(
            status="FAILED",
            terminal=terminal,
            finalist_binding=None,
            error_code=SEARCH_DATABASE_CHANGED,
        )
    return public


def _load_terminal_generation(
    database_path: PathLike, projection: Mapping[str, Any]
) -> Optional[dict[str, Any]]:
    """Load only an exact normal row or the exact database-change override."""
    normal = _terminal_generation_values(projection)
    changed = _terminal_generation_values(projection, database_changed=True)
    try:
        with closing(get_connection(database_path, read_only=True)) as connection:
            connection.execute("BEGIN")
            row = connection.execute(
                "SELECT * FROM generation_runs WHERE id=?", (projection["id"],)
            ).fetchone()
            connection.rollback()
    except (FileNotFoundError, OSError, RuntimeError, sqlite3.Error) as exc:
        raise SearchCampaignError(
            "search_generation_write_failed",
            "Search generation could not be read",
            status=409,
        ) from exc
    if row is None:
        return None
    if _row_matches_terminal_generation(row, normal):
        return _public_terminal_generation(projection, database_changed=False)
    if _row_matches_terminal_generation(row, changed):
        return _public_terminal_generation(projection, database_changed=True)
    raise SearchCampaignError(
        "search_generation_invalid", "Search terminal projection changed"
    )


def parse_finalist_projection(
    request_text: str,
    terminal_text: str,
    report_text: str,
) -> dict[str, Any]:
    """Purely validate the canonical three-document finalist projection."""
    message = "Search finalist projection is invalid"
    try:
        texts = (request_text, terminal_text, report_text)
        if not all(isinstance(value, str) for value in texts):
            raise ValueError(message)
        documents = tuple(json.loads(value) for value in texts)
        if not all(isinstance(value, dict) for value in documents) or any(
            pilot.canonical(document).decode() != text
            for document, text in zip(documents, texts)
        ):
            raise ValueError(message)
        request, terminal, report = documents
        evidence = report["evidence"]
        if set(report) != {"evidence", "finalist_binding"} or set(evidence) != {
            "terminal", "trials", "attempts"}:
            raise ValueError(message)
        verified = pilot.verify_search_terminal_projection(request, terminal, evidence)
        rounds = verified["round_contracts"]
        if verified["status"] != "SEARCH_FINALIST_FROZEN":
            raise ValueError(message)
        binding, candidate = _finalist_projection_binding(
            request, terminal, evidence, verified
        )
        round_one = rounds[0]
        profile_contract = pilot.profile_search_contract(
            *(round_one[key] for key in (
                "profile_snapshot", "search_timerange",
                "development_timerange", "pre_roll_candles")),
            economic_gate=round_one.get("economic_gate"),
        )
        _, search_stop = pilot.timerange(binding["search_timerange"], "Search")
        development_start, _ = pilot.timerange(binding["development_timerange"], "Development")
        if (
            report["finalist_binding"] != binding
            or {key: round_one[key] for key in profile_contract} != profile_contract
            or search_stop != development_start
        ):
            raise ValueError(message)
        timestamp = terminal["created_at_utc"]
        if not isinstance(timestamp, str) or not timestamp:
            raise ValueError(message)
    except (
        KeyError,
        TypeError,
        UnicodeError,
        ValueError,
        pilot.PilotError,
        SearchCampaignError,
    ) as exc:
        raise SearchCampaignError("search_generation_invalid", message) from exc
    return {
        "binding": binding,
        "candidate": candidate,
        "profile_snapshot": dict(round_one["profile_snapshot"]),
        "profile_contract": profile_contract,
        "timestamp": timestamp,
    }


def verify_persisted_finalist_projection(
    database_path: PathLike,
    value: Mapping[str, Any],
) -> dict[str, Any]:
    """Perform the heavy projection parse before Development opens a write transaction."""
    message = "Search finalist handoff binding is invalid"
    try:
        if not isinstance(value, Mapping) or set(value) not in (
            FINALIST_BINDING_FIELDS,
            FINALIST_BINDING_FIELDS | FINALIST_BINDING_OPTIONAL_FIELDS,
        ):
            raise ValueError(message)
        binding = dict(value)
        search_id = binding["search_generation_id"]
        if not isinstance(search_id, str) or pilot.SAFE_ID.fullmatch(search_id) is None:
            raise ValueError(message)
        with closing(get_connection(database_path, read_only=True)) as connection:
            connection.execute("BEGIN")
            projection = connection.execute(
                "SELECT * FROM generation_runs WHERE id=?", (search_id,)
            ).fetchone()
            if projection is None:
                raise ValueError(message)
            texts = tuple(projection[key] for key in (
                "request_json", "response_json", "parse_report_json"))
            parsed = parse_finalist_projection(*texts)
            profile = load_profile_snapshot(connection, binding["profile_id"])
            candidate = connection.execute(
                """SELECT c.id,c.class_name,c.generation_run_id,c.code_sha256,
                          g.research_profile_id
                   FROM candidates AS c JOIN generation_runs AS g
                     ON g.id=c.generation_run_id WHERE c.id=?""",
                (binding["candidate_id"],),
            ).fetchone()
            connection.rollback()
        timestamp = parsed["timestamp"]
        projection_values = {
            "id": search_id, "research_profile_id": binding["profile_id"],
            "source": "MANUAL", "model": None, "status": "COMPLETED",
            "response_raw_text": None, "returned_strategy_count": 0,
            "error_message": None, **dict.fromkeys(
                ("started_at", "finished_at", "created_at", "updated_at"), timestamp),
        }
        if (
            binding != {**parsed["binding"], "profile_snapshot": profile}
            or profile != parsed["profile_snapshot"]
            or candidate is None
            or (
                candidate["id"], candidate["class_name"],
                candidate["generation_run_id"], candidate["code_sha256"],
                candidate["research_profile_id"],
            ) != (
                binding["candidate_id"], parsed["candidate"]["class_name"],
                binding["generation_run_id"], binding["source_sha256"],
                binding["profile_id"],
            )
            or any(projection[key] != expected for key, expected in projection_values.items())
        ):
            raise ValueError(message)
        document_hashes = {
            key: pilot.digest(text.encode())
            for key, text in zip(("request", "terminal", "report"), texts)
        }
    except (GenerationContractError, OSError, RuntimeError, sqlite3.Error,
            KeyError, TypeError, ValueError, SearchCampaignError) as exc:
        raise SearchCampaignError("search_generation_invalid", message) from exc
    return {
        "binding": binding,
        "profile_contract": parsed["profile_contract"],
        "projection_values": projection_values,
        "document_hashes": document_hashes,
    }


def _project_terminal_generation(
    database_path: PathLike,
    capability: FrozenSearchCapability,
    projection: Optional[dict[str, Any]] = None,
    *,
    database_digest_before: Optional[str] = None,
) -> dict[str, Any]:
    """Atomically adjudicate DB drift and insert one immutable terminal row."""
    projection = projection or _terminal_projection(capability)
    if projection is None:
        raise SearchCampaignError("search_generation_invalid", "Search has no legal terminal to project")
    if database_digest_before is not None and (
        not isinstance(database_digest_before, str)
        or re.fullmatch(r"[0-9a-f]{64}", database_digest_before) is None
    ):
        raise SearchCampaignError(
            "search_generation_invalid", "Search database baseline is invalid"
        )
    campaign_id = projection["id"]
    normal = _terminal_generation_values(projection)
    changed = _terminal_generation_values(projection, database_changed=True)
    if projection["finalist_binding"] is not None:
        parsed = parse_finalist_projection(
            normal["request_json"],
            normal["response_json"],
            normal["parse_report_json"],
        )
        if parsed["binding"] != projection["finalist_binding"]:
            raise SearchCampaignError(
                "search_generation_invalid", "Search finalist projection changed"
            )
    try:
        with closing(get_connection(database_path)) as connection:
            connection.execute("BEGIN IMMEDIATE")
            before = _database_digest_connection(connection, campaign_id)
            database_changed = (
                database_digest_before is not None
                and before != database_digest_before
            )
            expected = changed if database_changed else normal
            row = connection.execute("SELECT * FROM generation_runs WHERE id=?", (campaign_id,)).fetchone()
            if row is None:
                if projection["status"] == "COMPLETED" and database_digest_before is None:
                    raise SearchCampaignError(
                        "search_generation_invalid",
                        "Successful Search terminal lacks its frozen database baseline",
                    )
                connection.execute(
                    """INSERT INTO generation_runs
                    (id,research_profile_id,source,model,status,request_json,
                     response_raw_text,response_json,returned_strategy_count,
                     parse_report_json,error_message,started_at,finished_at,
                     created_at,updated_at)
                    VALUES (?,?,'MANUAL',NULL,?,?,NULL,?,0,?,?,?,?,?,?)""",
                    (
                        campaign_id,
                        expected["research_profile_id"],
                        expected["status"],
                        expected["request_json"],
                        expected["response_json"],
                        expected["parse_report_json"],
                        expected["error_message"],
                        expected["started_at"],
                        expected["finished_at"],
                        expected["created_at"],
                        expected["updated_at"],
                    ),
                )
                row = connection.execute("SELECT * FROM generation_runs WHERE id=?", (campaign_id,)).fetchone()
            if _database_digest_connection(connection, campaign_id) != before:
                raise SearchCampaignError("database_write_detected", "Search changed data outside its terminal projection")
            if row is None:
                raise SearchCampaignError("search_generation_invalid", "Search terminal projection changed")
            row_is_normal = _row_matches_terminal_generation(row, normal)
            row_is_changed = _row_matches_terminal_generation(row, changed)
            if not row_is_normal and not row_is_changed:
                raise SearchCampaignError("search_generation_invalid", "Search terminal projection changed")
            if database_changed and not row_is_changed:
                raise SearchCampaignError(
                    "search_generation_invalid",
                    "Search database-change verdict could not be persisted",
                )
            connection.commit()
            return _public_terminal_generation(
                projection, database_changed=row_is_changed and not row_is_normal
            )
    except SearchCampaignError:
        raise
    except (OSError, RuntimeError, sqlite3.Error) as exc:
        raise SearchCampaignError(
            "search_generation_write_failed",
            "Search generation could not be persisted",
            status=409,
        ) from exc


def verified_finalist_binding(
    database_path: PathLike, capability: FrozenSearchCapability, candidate_id: str
) -> Optional[dict[str, Any]]:
    generation = _terminal_projection(capability)
    if generation is None:
        return None
    persisted_generation = _load_terminal_generation(database_path, generation)
    if persisted_generation is None:
        raise SearchCampaignError(
            "search_finalist_required",
            "Search finalist has no completed database adjudication",
        )
    generation = persisted_generation
    binding = generation.get("finalist_binding")
    if generation["status"] != "COMPLETED" or not isinstance(binding, dict) or binding.get("candidate_id") != candidate_id:
        raise SearchCampaignError("search_finalist_required", "Candidate is not the verified Search finalist")
    try:
        with closing(get_connection(database_path, read_only=True)) as connection:
            connection.execute("BEGIN")
            snapshot = _bound_candidate(connection, candidate_id, capability)
    except (OSError, RuntimeError, sqlite3.Error) as exc:
        raise SearchCampaignError("BLOCKED_DATA", "Finalist Candidate is unavailable", status=503) from exc
    if (snapshot.generation_run_id, snapshot.code_sha256, snapshot.profile_id) != (
        binding["generation_run_id"], binding["source_sha256"], binding["profile_id"]
    ):
        raise SearchCampaignError("search_generation_invalid", "Finalist binding changed")
    return {**binding, "profile_snapshot": dict(snapshot.profile)}


def fail_search_campaign(
    database_path: PathLike,
    capability: FrozenSearchCapability,
    campaign_id: str,
    error_code: str,
    *,
    database_digest_before: Optional[str] = None,
) -> dict[str, Any]:
    _require_frozen_identity(capability)
    assert capability.search_root is not None
    try:
        current = pilot.load_plan(capability.search_root, pilot.SEARCH_CAMPAIGN)
    except (OSError, pilot.PilotError) as exc:
        raise SearchCampaignError("search_state_invalid", "Search campaign contract is invalid") from exc
    if current.get("campaign_id") != campaign_id:
        raise SearchCampaignError("search_generation_invalid", "Search generation identity changed")
    pilot.write_search_failure(capability.search_root, current, RuntimeError(error_code), allow_completed_round=True)
    state = load_public_search_state(capability, active=False)
    if state.get("status") == "RUNNING":
        return state
    if state.get("status") == "INTERRUPTED":
        projection = _terminal_projection(capability)
        if projection is None:
            raise SearchCampaignError(
                "state_write_failed",
                "Search failure terminal could not be written",
                status=500,
            )
        if projection["status"] == "COMPLETED" and database_digest_before is None:
            return state
    _project_terminal_generation(
        database_path,
        capability,
        database_digest_before=database_digest_before,
    )
    return load_public_search_state(capability, active=False)


def prepare_round_one(
    database_path: PathLike,
    capability: FrozenSearchCapability,
    candidate_ids: Sequence[str],
    *,
    campaign_id: Optional[str] = None,
    profile_id: str,
) -> PreparedSearchRound:
    _require_ready(capability)
    profile = capability.profile_snapshot
    if (not isinstance(candidate_ids, Sequence) or isinstance(candidate_ids, (str, bytes))
            or not 1 <= len(candidate_ids) <= 2
            or any(not isinstance(value, str) for value in candidate_ids)
            or len(set(candidate_ids)) != len(candidate_ids)
            or profile is None
            or profile_id != profile.get("id")):
        raise SearchCampaignError("invalid_search_request", "Round 1 Candidate ids are invalid", status=400)
    if load_public_search_state(capability)["status"] != "SEARCH_READY":
        raise SearchCampaignError("campaign_consumed", "Search root already contains a campaign")
    selected_campaign_id = campaign_id or str(uuid4())
    if pilot.SAFE_ID.fullmatch(selected_campaign_id) is None:
        raise SearchCampaignError("invalid_search_request", "Search campaign id is invalid", status=400)
    connection, before = _prepare_transaction(database_path)
    try:
        if connection.execute(
            "SELECT 1 FROM generation_runs WHERE id=?", (selected_campaign_id,)
        ).fetchone() is not None:
            raise SearchCampaignError(
                "campaign_consumed", "Search campaign id already exists"
            )
        snapshots = [_bound_candidate(connection, value, capability) for value in candidate_ids]
        profile_ids = {item.profile_id for item in snapshots}
        mechanisms = [item.strategy_family for item in snapshots]
        if (len(profile_ids) != 1 or any(item.parent_candidate_id is not None for item in snapshots)
                or any(not isinstance(item, str) or pilot.SAFE_ID.fullmatch(item) is None for item in mechanisms)
                or len(set(mechanisms)) != len(mechanisms)):
            raise SearchCampaignError("invalid_seed_set", "Round 1 seeds must share one Profile, have no parent, and use distinct safe mechanisms")
        candidates = [
            _candidate_plan(snapshot, _planned_strategy_file(snapshot, 1), round_number=1,
                            changed_factor=None, parent_sha256=None)
            for snapshot in snapshots
        ]
        analyses = _strategy_analyses(snapshots, capability)
        plan = _search_plan(
            capability, selected_campaign_id, 1, candidates,
            strategy_analyses=analyses,
        )
        _validate_plan_before_materialization(capability, plan)
        total_changes = connection.total_changes
    finally:
        connection.close()
    if total_changes != 0:
        raise SearchCampaignError("database_write_detected", "Search preflight changed business tables", status=500)
    _write_plan(capability, plan, 1)
    try:
        for snapshot in snapshots:
            _materialize_strategy(capability, snapshot, 1)
    except Exception:
        try:
            fail_search_campaign(
                database_path,
                capability,
                selected_campaign_id,
                "ROUND_ONE_PREPARATION_FAILED",
            )
        except SearchCampaignError:
            pass
        raise
    return PreparedSearchRound(
        selected_campaign_id, 1, _argv(capability), before
    )


def _round_one_receipt(root: Path, campaign_id: str) -> dict[str, Any]:
    try:
        current_plan = pilot.load_plan(root, pilot.SEARCH_CAMPAIGN)
    except (OSError, pilot.PilotError) as exc:
        raise SearchCampaignError("search_state_invalid", "Search campaign contract is invalid") from exc
    records, _ = _ledger_state(root, campaign_id)
    receipts, _, _ = _validate_records(records, current_plan, current_plan)
    if len(receipts) != 1 or receipts[0].get("round") != 1:
        raise SearchCampaignError("round_not_ready", "Round 1 receipt is unavailable")
    return receipts[0]


def prepare_round_two(
    database_path: PathLike,
    capability: FrozenSearchCapability,
    campaign_id: str,
    candidates: Sequence[Mapping[str, Any]],
) -> PreparedSearchRound:
    _require_ready(capability)
    if (not isinstance(candidates, Sequence) or isinstance(candidates, (str, bytes))
            or len(candidates) != 1
            or any(not isinstance(item, Mapping) or set(item) != {"candidate_id", "changed_factor"}
                   or not isinstance(item.get("candidate_id"), str)
                   or not isinstance(item.get("changed_factor"), str) for item in candidates)):
        raise SearchCampaignError("invalid_search_request", "Round 2 request is invalid", status=400)
    candidate_ids = [str(item["candidate_id"]) for item in candidates]
    changed_factors = [str(item["changed_factor"]) for item in candidates]
    if CHANGED_FACTOR.fullmatch(changed_factors[0]) is None:
        raise SearchCampaignError(
            "invalid_search_request", "Round 2 changed_factor must be safe", status=400
        )
    state = load_public_search_state(capability)
    if state.get("status") != "SEARCH_ROUND_READY_FOR_CHILDREN" or state.get("campaign_id") != campaign_id:
        raise SearchCampaignError("round_not_ready", "Search is not ready for Round 2")
    selected = state.get("selected_parent")
    if not isinstance(selected, Mapping):
        raise SearchCampaignError("search_state_invalid", "Round 1 selected parent is invalid")
    assert capability.search_root is not None
    receipt = _round_one_receipt(capability.search_root, campaign_id)
    connection, before = _prepare_transaction(database_path)
    try:
        parent = _bound_candidate(connection, str(selected.get("candidate_id")), capability)
        snapshots = [_bound_candidate(connection, value, capability) for value in candidate_ids]
        if any(item.parent_candidate_id != parent.candidate_id or item.profile_id != parent.profile_id
               or item.strategy_family != parent.strategy_family for item in snapshots):
            raise SearchCampaignError("invalid_child_set", "Round 2 children must bind the exact selected parent/Profile/mechanism")
        if any(
            not _single_literal_factor_change(parent, snapshot, changed_factor)
            for snapshot, changed_factor in zip(
                snapshots, changed_factors, strict=True
            )
        ):
            raise SearchCampaignError(
                "invalid_child_set",
                "Profile Round 2 must change exactly one literal class setting",
            )
        candidate_plans = [
            _candidate_plan(snapshot, _planned_strategy_file(snapshot, 2), round_number=2,
                            changed_factor=changed_factor, parent_sha256=parent.code_sha256)
            for snapshot, changed_factor in zip(snapshots, changed_factors)
        ]
        parent_identity = {
            "candidate_id": parent.candidate_id,
            "class_name": parent.class_name,
            "mechanism": parent.strategy_family,
            "strategy_sha256": parent.code_sha256,
        }
        if parent_identity != pilot._search_identity(selected):
            raise SearchCampaignError(
                "candidate_binding_changed",
                "Round 1 selected parent Candidate binding changed",
            )
        plan = _search_plan(
            capability, campaign_id, 2, candidate_plans,
            receipt_sha256=_sha256(pilot.canonical(receipt)), parent=parent_identity,
            strategy_analyses=_strategy_analyses(snapshots, capability),
        )
        _validate_plan_before_materialization(capability, plan)
        after = _database_digest_connection(connection)
        total_changes = connection.total_changes
    finally:
        connection.close()
    if before != after or total_changes != 0:
        raise SearchCampaignError("database_write_detected", "Search action changed business tables", status=500)
    _write_plan(capability, plan, 2)
    try:
        for snapshot in snapshots:
            _materialize_strategy(capability, snapshot, 2)
    except Exception:
        fail_search_campaign(
            database_path, capability, campaign_id, "ROUND_TWO_PREPARATION_FAILED"
        )
        raise
    return PreparedSearchRound(campaign_id, 2, _argv(capability), before)


def complete_search_round(
    capability: FrozenSearchCapability, campaign_id: str, return_code: int,
    database_path: PathLike, database_digest_before: str,
) -> dict[str, Any]:
    if return_code not in {0, 3}:
        raise SearchCampaignError("search_nonzero", "Search process failed")
    projection = _terminal_projection(capability)
    if projection is None:
        state = load_public_search_state(capability, active=False)
        engine_status = state.get("status")
        engine_campaign_id = state.get("campaign_id")
    else:
        engine_status = projection["terminal"].get("status")
        engine_campaign_id = projection["id"]
    if engine_campaign_id != campaign_id:
        raise SearchCampaignError("search_state_invalid", "Search identity mismatch")
    expected = (
        {"SEARCH_ROUND_READY_FOR_CHILDREN", "SEARCH_FINALIST_FROZEN"}
        if return_code == 0
        else {"SEARCH_TERMINATED_NO_PARENT", "SEARCH_TERMINATED_NO_FINALIST"}
    )
    if engine_status not in expected:
        raise SearchCampaignError("search_state_invalid", "Search exit/status mapping is invalid")
    if engine_status != "SEARCH_ROUND_READY_FOR_CHILDREN":
        if projection is None:
            raise SearchCampaignError(
                "search_state_invalid", "Search terminal evidence is missing"
            )
        _project_terminal_generation(
            database_path,
            capability,
            projection,
            database_digest_before=database_digest_before,
        )
    return load_public_search_state(capability, active=False)


__all__ = [
    "FrozenSearchCapability",
    "PreparedSearchRound",
    "SearchCampaignError",
    "business_table_digest",
    "complete_search_round",
    "fail_search_campaign",
    "freeze_search_capability",
    "load_public_search_state",
    "load_search_context",
    "parse_finalist_projection",
    "prepare_round_one",
    "prepare_round_two",
    "recover_interrupted_search",
    "verify_persisted_finalist_projection",
    "verified_finalist_binding",
]
