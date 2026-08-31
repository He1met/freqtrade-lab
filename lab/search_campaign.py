"""Thin, file-backed adapter for one two-round Search-only campaign.

The ranking, budget, ledger, receipts, Freqtrade execution, and finalist Gate
remain owned by ``scripts.run_bounded_research_pilot.screen_search``.  This
module only binds approved database Candidates to that existing file contract
and projects its receipts to a path-free Console state.
"""

from __future__ import annotations

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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO, Mapping, Optional, Sequence, Tuple, Union
from uuid import uuid4

from lab.bounded_strategy import (
    BOUNDED_CAUSAL_STRATEGY_V1,
    BoundedStrategyError,
    validate_bounded_causal_strategy,
)
from lab.codex_generation import (
    ApprovedCandidateSnapshot,
    GenerationContractError,
    load_approved_candidate_snapshot,
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
from scripts import run_bounded_research_pilot as pilot


PathLike = Union[str, Path]
PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATUS_FILE = "console-status.json"
STATUS_SCHEMA = "freqtrade-lab-search-console-status-v1"
ROUND_PLAN = "campaign-round-{round_number}.json"
STRATEGIES = "strategies"
BUSINESS_TABLES = (
    "research_profiles",
    "generation_runs",
    "candidates",
    "research_runs",
    "backtest_executions",
    "releases",
)
SEARCH_STATUSES = frozenset(
    {
        "SEARCH_READY",
        "BLOCKED_DATA",
        "RUNNING",
        "SEARCH_ROUND_READY_FOR_CHILDREN",
        "SEARCH_FINALIST_FROZEN",
        "SEARCH_TERMINATED_NO_PARENT",
        "SEARCH_TERMINATED_NO_FINALIST",
        "CANCELLED",
        "FAILED",
        "INTERRUPTED",
    }
)
CHANGED_FACTOR = re.compile(r"^[a-z][a-z0-9_.-]{0,62}$")
PRIVATE_OUTPUT = re.compile(r"^round-[12]\.(?:stdout|stderr)\.log$")
PUBLIC_TRIAL_FIELDS = ("round", "attempt_number", "candidate_id", "class_name", "mechanism", "strategy_sha256", "relationship", "changed_factor", "technical_status", "failure_reason", "search_metrics")
PUBLIC_IDENTITY_FIELDS = ("candidate_id", "class_name", "mechanism", "strategy_sha256", "search_metrics")


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
    pair: Optional[str] = None
    timeframe: Optional[str] = None
    base_fee: Optional[float] = None
    _directory_fd: int = field(default=-1, repr=False, compare=False)

    def public(self) -> dict[str, Any]:
        return {
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
            "maximum_attempts": pilot.SEARCH_MAX_ATTEMPTS,
            "maximum_rounds": pilot.SEARCH_MAX_ROUNDS,
            "ranking": list(pilot.SEARCH_RANKING),
            "finalist_gate": dict(pilot.SEARCH_GATE_CONTRACT),
            "security_gate": BOUNDED_CAUSAL_STRATEGY_V1,
            "outside_git": self.status == "READY",
            "single_owner_lock": self.status == "READY",
        }

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
    candidate_ids: Tuple[str, ...]
    argv: Tuple[str, ...]
    database_digest_before: str
    database_digest_after: str
    database_total_changes: int


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


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


def _acquisition_snapshot(root: Path) -> dict[str, Any]:
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
        start, end = pilot.timerange(timerange, "Search")
    except pilot.PilotError as exc:
        raise SearchCampaignError("BLOCKED_DATA", "Search timerange is invalid", status=503) from exc
    if (end - start).days != 30:
        raise SearchCampaignError("BLOCKED_DATA", "Search timerange must span exactly 30 days", status=503)
    synthetic_plan = {"schema": pilot.SEARCH_SCHEMA, "search_timerange": timerange,
                      "data_provenance_sha256": _sha256(provenance_bytes)}
    try:
        pilot.verify_data(root, synthetic_plan)
    except (pilot.PilotError, OSError, KeyError, TypeError, ValueError) as exc:
        raise SearchCampaignError(
            "BLOCKED_DATA", "Search-only data contract could not be verified", status=503
        ) from exc
    config = _strict_json(_read_regular(acquisition / "config.json", "Search config"), "Search config")
    exchange = config.get("exchange")
    pair = source.get("pair")
    timeframe = contract.get("timeframe")
    fee = config.get("fee")
    if (
        not isinstance(exchange, dict)
        or exchange.get("name") != "okx"
        or exchange.get("pair_whitelist") != [pair]
        or not isinstance(pair, str)
        or not pair
        or timeframe != "5m"
        or config.get("timeframe") != timeframe
        or config.get("trading_mode") != "futures"
        or config.get("margin_mode") != "isolated"
        or isinstance(fee, bool)
        or not isinstance(fee, (int, float))
        or float(fee) < 0
    ):
        raise SearchCampaignError(
            "BLOCKED_DATA", "Search config/profile contract mismatch", status=503
        )
    return {
        "search_timerange": timerange,
        "data_provenance_sha256": _sha256(provenance_bytes),
        "pair": pair,
        "timeframe": timeframe,
        "base_fee": float(fee),
    }


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
        acquisition = _acquisition_snapshot(root)
        freqtrade = _freqtrade_snapshot(freqtrade_python, freqtrade_source)
        return FrozenSearchCapability(
            status="READY",
            reason="Search-only 30-day data and Freqtrade 2026.7 are frozen",
            search_root=root,
            root_identity=(opened.st_dev, opened.st_ino),
            _directory_fd=descriptor,
            **freqtrade,
            **{key: acquisition[key] for key in ("search_timerange", "data_provenance_sha256", "pair", "timeframe", "base_fee")},
        )
    except Exception as exc:
        if descriptor >= 0:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)
        reason = exc.message if isinstance(exc, SearchCampaignError) else "Search capability could not be frozen"
        return FrozenSearchCapability(status="BLOCKED_DATA", reason=reason)


def _require_frozen_identity(capability: FrozenSearchCapability) -> None:
    if (
        capability.status != "READY"
        or capability.search_root is None
        or capability.freqtrade_python is None
        or capability.freqtrade_source is None
        or capability.root_identity is None
        or capability._directory_fd < 0
    ):
        raise SearchCampaignError("BLOCKED_DATA", capability.reason, status=503)
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
        current_acquisition = _acquisition_snapshot(capability.search_root)
    except SearchCampaignError as exc:
        raise SearchCampaignError(
            "BLOCKED_DATA", "Startup-frozen Search inputs changed", status=503
        ) from exc
    frozen = (
        capability.search_timerange,
        capability.data_provenance_sha256,
        capability.pair,
        capability.timeframe,
        capability.base_fee,
    )
    current = (
        current_acquisition["search_timerange"],
        current_acquisition["data_provenance_sha256"],
        current_acquisition["pair"],
        current_acquisition["timeframe"],
        current_acquisition["base_fee"],
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


def record_search_runtime_status(
    capability: FrozenSearchCapability,
    campaign_id: str,
    status: str,
    round_number: int,
    *,
    error_code: Optional[str] = None,
) -> dict[str, Any]:
    _require_frozen_identity(capability)
    if (
        not isinstance(campaign_id, str)
        or pilot.SAFE_ID.fullmatch(campaign_id) is None
        or status not in SEARCH_STATUSES
        or round_number not in {1, 2}
        or (error_code is not None and (not isinstance(error_code, str) or len(error_code) > 80))
    ):
        raise SearchCampaignError("invalid_status", "Search runtime status is invalid")
    document = {
        "schema": STATUS_SCHEMA,
        "campaign_id": campaign_id,
        "status": status,
        "round": round_number,
        "error_code": error_code,
        "updated_at_utc": _utc_now(),
    }
    if status in {"CANCELLED", "FAILED", "INTERRUPTED"}:
        _atomic_json_at(capability._directory_fd, STATUS_FILE, document, replace=True)
    return document


def _read_optional_status(root: Path) -> Optional[dict[str, Any]]:
    path = root / STATUS_FILE
    if not path.exists() and not path.is_symlink():
        return None
    value = _strict_json(_read_regular(path, "Search Console status"), "Search Console status")
    if (
        set(value) != {"schema", "campaign_id", "status", "round", "error_code", "updated_at_utc"}
        or value.get("schema") != STATUS_SCHEMA
        or value.get("status") not in SEARCH_STATUSES
        or value.get("round") not in {1, 2}
        or not isinstance(value.get("campaign_id"), str)
    ):
        raise SearchCampaignError("search_state_invalid", "Search Console status is invalid")
    return value


def _database_digest_connection(connection: sqlite3.Connection) -> str:
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
        rows = [list(row) for row in connection.execute(f"SELECT * FROM {table} ORDER BY id")]
        document["tables"][table] = {"columns": columns, "rows": rows}
    return _sha256(pilot.canonical(document))


def business_table_digest(database_path: PathLike) -> str:
    try:
        with closing(get_connection(database_path, read_only=True)) as connection:
            connection.execute("BEGIN")
            return _database_digest_connection(connection)
    except SearchCampaignError:
        raise
    except (FileNotFoundError, OSError, RuntimeError, sqlite3.Error) as exc:
        raise SearchCampaignError("BLOCKED_DATA", "database is unavailable", status=503) from exc


def _profile_bound(snapshot: ApprovedCandidateSnapshot, capability: FrozenSearchCapability) -> None:
    profile = snapshot.profile
    if (
        profile.get("domain") != "OKX_CRYPTO_PERP"
        or profile.get("exchange") != "okx"
        or profile.get("trading_mode") != "futures"
        or profile.get("margin_mode") != "isolated"
        or profile.get("pairs") != [capability.pair]
        or snapshot.timeframe != capability.timeframe
        or profile.get("timeframe") != capability.timeframe
        or isinstance(profile.get("taker_fee_rate"), bool)
        or not isinstance(profile.get("taker_fee_rate"), (int, float))
        or float(profile["taker_fee_rate"]) != capability.base_fee
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
        validate_bounded_causal_strategy(snapshot.code_text, snapshot.class_name)
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
    data = _read_regular(path, "Search trial ledger", 2 * 1024 * 1024)
    try:
        records = pilot._load_search_records(io.BytesIO(data), campaign_id)
    except pilot.PilotError as exc:
        raise SearchCampaignError("search_state_invalid", "Search trial ledger is invalid") from exc
    return records, data


def _round_one_plan(root: Path, current: Mapping[str, Any]) -> Mapping[str, Any]:
    if current["round"] == 1:
        return current
    data = _read_regular(root / ROUND_PLAN.format(round_number=1), "Round 1 plan")
    try:
        prior = pilot._load_search_campaign(_strict_json(data, "Round 1 plan"), data)
    except (KeyError, TypeError, ValueError, pilot.PilotError) as exc:
        raise SearchCampaignError("search_state_invalid", "Round 1 plan is invalid") from exc
    if prior["round"] != 1 or prior["campaign_id"] != current["campaign_id"] or prior["_contract_sha256"] != current["_contract_sha256"]:
        raise SearchCampaignError("search_state_invalid", "Round 1 plan binding changed")
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
                if active_round != round_number or len(round_trials) != len(reserved) or item.get("campaign_sha256") != plan["_sha256"] or item.get("contract_sha256") != plan["_contract_sha256"] or item.get("ledger_prefix_sha256") != _sha256(b"".join(pilot.canonical(value) for value in records[:index])):
                    raise ValueError("receipt binding")
                parent = item.get("brief", {}).get("selected_parent")
                if parent is not None and pilot._search_identity(parent) not in [pilot._search_identity(value) for value in trials]:
                    raise ValueError("parent")
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


def _public_projection(value: Any, fields: Sequence[str]) -> Optional[dict[str, Any]]:
    if not isinstance(value, Mapping):
        return None
    return {key: value.get(key) for key in fields if key in value}


def _base_public_state(capability: FrozenSearchCapability, status_value: str) -> dict[str, Any]:
    return {
        "status": status_value, "campaign_id": None, "current_round": None,
        "attempts": [], "frozen_ranking": [],
        "budget": {"maximum_attempts": pilot.SEARCH_MAX_ATTEMPTS, "consumed_total": 0,
                   "remaining": pilot.SEARCH_MAX_ATTEMPTS},
        "selected_parent": None, "search_finalist": None,
        "message": capability.reason if status_value == "BLOCKED_DATA" else "Search-only campaign is ready",
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


def _validate_terminal(
    plan: Mapping[str, Any],
    terminal: Mapping[str, Any],
    receipts: Sequence[Mapping[str, Any]],
    ledger_bytes: bytes,
) -> bool:
    bound = (
        terminal.get("schema") == pilot.SEARCH_TERMINAL_SCHEMA
        and terminal.get("campaign_id") == plan["campaign_id"]
        and terminal.get("campaign_sha256") == plan["_sha256"]
        and terminal.get("contract_sha256") == plan["_contract_sha256"]
        and terminal.get("round") == plan["round"]
    )
    if terminal.get("status") == "SEARCH_BLOCKED":
        if not bound or not isinstance(terminal.get("error"), str):
            raise SearchCampaignError("search_state_invalid", "Search blocked terminal is invalid")
        return True
    if not receipts or receipts[-1].get("round") != plan["round"]:
        raise SearchCampaignError("search_state_invalid", "Search terminal lacks its round receipt")
    latest_receipt = receipts[-1]
    if (
        not bound
        or terminal.get("status") != latest_receipt.get("status")
        or terminal.get("brief") != latest_receipt.get("brief")
        or terminal.get("round_receipt_sha256")
        != _sha256(pilot.canonical(latest_receipt))
        or terminal.get("trials_sha256") != _sha256(ledger_bytes)
    ):
        raise SearchCampaignError("search_state_invalid", "Search terminal binding is invalid")
    return False


def load_public_search_state(
    capability: FrozenSearchCapability, *, active: bool = False
) -> dict[str, Any]:
    if capability.status != "READY" or capability.search_root is None:
        return _base_public_state(capability, "BLOCKED_DATA")
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
    except (OSError, pilot.PilotError) as exc:
        state = _base_public_state(capability, "INTERRUPTED")
        state["message"] = "Search campaign contract is incomplete or invalid"
        return state
    campaign_id = str(plan["campaign_id"])
    if _future_or_forbidden_artifact(root, int(plan["round"])):
        state = _base_public_state(capability, "INTERRUPTED")
        state["campaign_id"] = campaign_id
        state["current_round"] = int(plan["round"])
        state["message"] = "Search contains a partial next-round preparation"
        return state
    prior = _round_one_plan(root, plan)
    records, ledger_bytes = _ledger_state(root, campaign_id)
    receipts, trials, partial = _validate_records(records, plan, prior)
    status_receipt = _read_optional_status(root)
    if status_receipt is not None and status_receipt.get("campaign_id") != campaign_id:
        raise SearchCampaignError("search_state_invalid", "Search status identity mismatch")
    if status_receipt is not None and int(status_receipt.get("round", 0)) > int(plan["round"]):
        state = _base_public_state(capability, "INTERRUPTED")
        state["campaign_id"] = campaign_id
        state["current_round"] = int(plan["round"])
        state["message"] = "Search contains a partial next-round preparation"
        return state
    latest_receipt = receipts[-1] if receipts else None
    terminal_path = root / pilot.SEARCH_TERMINAL
    terminal = None
    blocked_terminal = False
    if terminal_path.exists() or terminal_path.is_symlink():
        terminal = _strict_json(_read_regular(terminal_path, "Search terminal"), "Search terminal")
        blocked_terminal = _validate_terminal(plan, terminal, receipts, ledger_bytes)
    runtime_terminal = (status_receipt is not None
        and status_receipt.get("status") in {"CANCELLED", "FAILED", "INTERRUPTED"}
        and int(status_receipt.get("round", 0)) == int(plan["round"])
        and (latest_receipt is None or int(status_receipt["round"]) >= int(latest_receipt.get("round", 0))))
    if blocked_terminal:
        status_value = "FAILED"
    elif terminal is not None:
        status_value = str(terminal["status"])
    elif runtime_terminal:
        status_value = str(status_receipt["status"])
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
            selected["profile_id"] = None
        state["selected_parent"] = selected
    if terminal is not None and not blocked_terminal:
        state["search_finalist"] = _public_projection(terminal.get("search_finalist"), PUBLIC_IDENTITY_FIELDS)
    messages = {
        "RUNNING": "Search round is running",
        "SEARCH_ROUND_READY_FOR_CHILDREN": "Round 1 selected parent is frozen; generate and approve children manually",
        "SEARCH_FINALIST_FROZEN": "Round 2 finalist is frozen; Development remains a separate manual action",
        "SEARCH_TERMINATED_NO_PARENT": "Round 1 ended with no valid parent",
        "SEARCH_TERMINATED_NO_FINALIST": "Round 2 ended with no finalist; thresholds were not changed",
        "CANCELLED": "Search was cancelled; use a new root for another campaign",
        "FAILED": "Search failed closed; private diagnostics are not returned",
        "INTERRUPTED": "Search state is partial or interrupted; it will not be replayed",
    }
    state["message"] = messages.get(status_value, state["message"])
    return state


def recover_interrupted_search(capability: FrozenSearchCapability) -> dict[str, Any]:
    state = load_public_search_state(capability, active=False)
    if state.get("status") == "INTERRUPTED" and state.get("campaign_id"):
        record_search_runtime_status(
            capability,
            str(state["campaign_id"]),
            "INTERRUPTED",
            int(state.get("current_round") or 1),
            error_code="SERVER_RESTART",
        )
    return state


def _blocked_search_context(
    capability: FrozenSearchCapability, message: str
) -> dict[str, Any]:
    state = _base_public_state(capability, "BLOCKED_DATA")
    state["message"] = message
    public_capability = capability.public()
    public_capability["status"] = "BLOCKED_DATA"
    public_capability["reason"] = message
    return {
        "capability": public_capability,
        "state": state,
        "candidates": [],
        "codex_parent_lock": None,
        "limits": {"maximum_candidates_per_round": 3, "maximum_attempts": 6},
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
        return {
            "capability": capability.public(),
            "state": state,
            "candidates": candidates,
            "codex_parent_lock": parent_lock,
            "limits": {"maximum_candidates_per_round": 3, "maximum_attempts": 6},
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
    name = f"round-{round_number}-{snapshot.candidate_id}.py"
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
    return f"{STRATEGIES}/{name}"


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
    }


def _search_plan(
    capability: FrozenSearchCapability,
    campaign_id: str,
    round_number: int,
    candidates: Sequence[Mapping[str, Any]],
    *,
    receipt_sha256: Optional[str] = None,
    parent: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    return {
        "schema": pilot.SEARCH_SCHEMA, "campaign_id": campaign_id,
        "freqtrade_version": SUPPORTED_FREQTRADE_VERSION, "round": round_number,
        "previous_round_receipt_sha256": receipt_sha256,
        "search_timerange": capability.search_timerange,
        "data_provenance_sha256": capability.data_provenance_sha256,
        "budget": {"maximum_attempts": pilot.SEARCH_MAX_ATTEMPTS},
        "ranking": list(pilot.SEARCH_RANKING), "finalist_gate": dict(pilot.SEARCH_GATE_CONTRACT),
        "parent": parent, "candidates": list(candidates),
    }


def _write_plan(capability: FrozenSearchCapability, plan: Mapping[str, Any], round_number: int) -> None:
    if round_number == 1:
        _atomic_json_at(capability._directory_fd, ROUND_PLAN.format(round_number=1), plan, replace=False)
    _atomic_json_at(capability._directory_fd, pilot.SEARCH_CAMPAIGN, plan, replace=round_number == 2)


def _argv(capability: FrozenSearchCapability) -> Tuple[str, ...]:
    assert capability.freqtrade_python is not None
    assert capability.freqtrade_source is not None
    assert capability.search_root is not None
    return (str(capability.freqtrade_python), str(Path(pilot.__file__).resolve(strict=True)),
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


def prepare_round_one(
    database_path: PathLike,
    capability: FrozenSearchCapability,
    candidate_ids: Sequence[str],
    *,
    campaign_id: Optional[str] = None,
) -> PreparedSearchRound:
    _require_ready(capability)
    if (not isinstance(candidate_ids, Sequence) or isinstance(candidate_ids, (str, bytes))
            or not 1 <= len(candidate_ids) <= 3 or any(not isinstance(value, str) for value in candidate_ids)
            or len(set(candidate_ids)) != len(candidate_ids)):
        raise SearchCampaignError("invalid_search_request", "Round 1 Candidate ids are invalid", status=400)
    if load_public_search_state(capability)["status"] != "SEARCH_READY":
        raise SearchCampaignError("campaign_consumed", "Search root already contains a campaign")
    selected_campaign_id = campaign_id or str(uuid4())
    if pilot.SAFE_ID.fullmatch(selected_campaign_id) is None:
        raise SearchCampaignError("invalid_search_request", "Search campaign id is invalid", status=400)
    connection, before = _prepare_transaction(database_path)
    try:
        snapshots = [_bound_candidate(connection, value, capability) for value in candidate_ids]
        profile_ids = {item.profile_id for item in snapshots}
        mechanisms = [item.strategy_family for item in snapshots]
        if (len(profile_ids) != 1 or any(item.parent_candidate_id is not None for item in snapshots)
                or any(not isinstance(item, str) or pilot.SAFE_ID.fullmatch(item) is None for item in mechanisms)
                or len(set(mechanisms)) != len(mechanisms)):
            raise SearchCampaignError("invalid_seed_set", "Round 1 seeds must share one Profile, have no parent, and use distinct safe mechanisms")
        candidates = [
            _candidate_plan(snapshot, _materialize_strategy(capability, snapshot, 1),
                            round_number=1, changed_factor=None, parent_sha256=None)
            for snapshot in snapshots
        ]
        plan = _search_plan(capability, selected_campaign_id, 1, candidates)
        _write_plan(capability, plan, 1)
        after = _database_digest_connection(connection)
        total_changes = connection.total_changes
    finally:
        connection.close()
    if before != after or total_changes != 0:
        raise SearchCampaignError("database_write_detected", "Search action changed business tables", status=500)
    return PreparedSearchRound(selected_campaign_id, 1, tuple(candidate_ids), _argv(capability), before, after, total_changes)


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
            or not 1 <= len(candidates) <= 3
            or any(not isinstance(item, Mapping) or set(item) != {"candidate_id", "changed_factor"}
                   or not isinstance(item.get("candidate_id"), str)
                   or not isinstance(item.get("changed_factor"), str) for item in candidates)):
        raise SearchCampaignError("invalid_search_request", "Round 2 request is invalid", status=400)
    candidate_ids = [str(item["candidate_id"]) for item in candidates]
    changed_factors = [str(item["changed_factor"]) for item in candidates]
    if (len(set(candidate_ids)) != len(candidate_ids) or len(set(changed_factors)) != len(changed_factors)
            or any(CHANGED_FACTOR.fullmatch(value) is None for value in changed_factors)):
        raise SearchCampaignError("invalid_search_request", "Round 2 ids and changed_factor slugs must be unique and safe", status=400)
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
        candidate_plans = [
            _candidate_plan(snapshot, _materialize_strategy(capability, snapshot, 2), round_number=2,
                            changed_factor=changed_factor, parent_sha256=parent.code_sha256)
            for snapshot, changed_factor in zip(snapshots, changed_factors, strict=True)
        ]
        parent_identity = {
            "candidate_id": parent.candidate_id,
            "class_name": parent.class_name,
            "mechanism": parent.strategy_family,
            "strategy_sha256": parent.code_sha256,
        }
        plan = _search_plan(
            capability, campaign_id, 2, candidate_plans,
            receipt_sha256=_sha256(pilot.canonical(receipt)), parent=parent_identity,
        )
        _write_plan(capability, plan, 2)
        after = _database_digest_connection(connection)
        total_changes = connection.total_changes
    finally:
        connection.close()
    if before != after or total_changes != 0:
        raise SearchCampaignError("database_write_detected", "Search action changed business tables", status=500)
    return PreparedSearchRound(campaign_id, 2, tuple(candidate_ids), _argv(capability), before, after, total_changes)


def complete_search_round(
    capability: FrozenSearchCapability, campaign_id: str, return_code: int
) -> dict[str, Any]:
    if return_code not in {0, 3}:
        raise SearchCampaignError("search_nonzero", "Search process failed")
    state = load_public_search_state(capability, active=False)
    if state.get("campaign_id") != campaign_id:
        raise SearchCampaignError("search_state_invalid", "Search identity mismatch")
    expected = (
        {"SEARCH_ROUND_READY_FOR_CHILDREN", "SEARCH_FINALIST_FROZEN"}
        if return_code == 0
        else {"SEARCH_TERMINATED_NO_PARENT", "SEARCH_TERMINATED_NO_FINALIST"}
    )
    if state.get("status") not in expected:
        raise SearchCampaignError("search_state_invalid", "Search exit/status mapping is invalid")
    record_search_runtime_status(
        capability,
        campaign_id,
        str(state["status"]),
        int(state.get("current_round") or 1),
        error_code=None,
    )
    return load_public_search_state(capability, active=False)


__all__ = [
    "FrozenSearchCapability",
    "PreparedSearchRound",
    "SearchCampaignError",
    "business_table_digest",
    "complete_search_round",
    "freeze_search_capability",
    "load_public_search_state",
    "load_search_context",
    "prepare_round_one",
    "prepare_round_two",
    "record_search_runtime_status",
    "recover_interrupted_search",
]
