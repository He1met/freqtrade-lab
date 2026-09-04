"""Single-process local Research Console for fixed, bounded actions.

The console deliberately exposes no generic command runner.  It can only run
the existing fixed actions, including one one-shot Holdout continuation whose
runtime inputs are frozen at startup.
"""

from __future__ import annotations

import hmac
import html
import fcntl
import json
import os
import re
import secrets
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO, Dict, Mapping, Optional, Sequence, Tuple, Union
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from lab.codex_generation import (
    CODEX_DISABLED_FEATURES,
    CODEX_REQUIRED_FALSE_FEATURES,
    GenerationContractError,
    GenerationRequest,
    MAX_CODE_BYTES,
    MAX_JSONL_BYTES,
    PreparedGeneration,
    build_codex_argv,
    build_codex_feature_probe_argv,
    build_prompt,
    codex_output_schema,
    complete_generation,
    fail_generation,
    load_generation,
    load_generation_context,
    parse_candidate_output,
    review_generation as review_candidate_generation,
    start_generation,
    validate_codex_jsonl,
    validate_generation_request,
    validate_model_name,
)
from lab.frequi import (
    FreqUIConfig,
    FreqUIConfigurationError,
    _loopback_base_url,
    probe_frequi,
)
from lab.development_run import (
    DEVELOPMENT_PIPELINE_VERSION,
    DevelopmentRunError,
    FrozenDevelopmentCapability,
    development_worker_argv,
    fail_development_run,
    finalize_development_gate,
    freeze_development_capability,
    load_public_research_run as load_public_development_run,
    prepare_development_run,
    research_context,
)
from lab.holdout_run import (
    FrozenHoldoutCapability,
    HoldoutRunError,
    copy_frequi_results,
    fail_holdout_continuation,
    finalize_holdout_continuation,
    freeze_holdout_capability,
    holdout_worker_argv,
    load_public_research_run as load_public_holdout_run,
    prepare_holdout_continuation,
)
from lab.manual_release import (
    FrozenReleaseRoot,
    ManualReleaseError,
    freeze_release_root,
    inspect_manual_review,
    pass_and_create_release,
    reject_research_run,
)
from lab.search_campaign import (
    FrozenSearchCapability,
    PreparedSearchRound,
    SearchCampaignError,
    complete_search_round,
    fail_search_campaign,
    freeze_search_capability,
    load_public_search_state,
    load_search_context,
    prepare_round_one,
    prepare_round_two,
    recover_interrupted_search,
    verified_finalist_binding,
)
from lab.strategy_library import (
    DEFAULT_PORT,
    LOOPBACK_HOST,
    StrategyLibraryError,
    StrategyLibraryRequestHandler,
    _open_read_only_database,
    create_strategy_library_server,
    validate_strategy_library_database,
)


PathLike = Union[str, Path]
PROJECT_ROOT = Path(__file__).resolve().parent.parent
PILOT_SCRIPT = PROJECT_ROOT / "scripts" / "run_bounded_research_pilot.py"
STATUS_SCHEMA = "freqtrade-lab-research-console-status-v1"
EVENTS_SCHEMA = "freqtrade-lab-research-console-events-v1"
EXPLICIT_SEARCH_SEALED_REASON = (
    "Explicit Search mode keeps Holdout and Holdout Stress sealed"
)
REQUEST_SCHEMA = "freqtrade-lab-research-console-request-v1"
OWNER_SCHEMA = "freqtrade-lab-research-console-owner-v1"
MAX_REQUEST_BYTES = 16 * 1024
MAX_STATE_BYTES = 256 * 1024
MAX_CODEX_STDERR_BYTES = 256 * 1024
MAX_EVENTS = 128
PROBE_OUTPUT_BYTES = 64 * 1024
GROUP_EXIT_CONFIRM_SECONDS = 0.25
GROUP_TERMINATION_CONFIRM_SECONDS = 1.0
TERMINAL_STATUSES = frozenset(
    {
        "SUCCEEDED",
        "FAILED",
        "CANCELLED",
        "TIMED_OUT",
        "INTERRUPTED",
        "INTERRUPTED_NEEDS_CONFIRMATION",
    }
)
NONTERMINAL_STATUSES = frozenset(
    {
        "STARTING",
        "RUNNING",
        "CANCEL_REQUESTED",
        "TIMEOUT_TERMINATING",
        "OUTPUT_LIMIT_TERMINATING",
        "INTERRUPTING",
    }
)
CODEX_REQUIRED_FLAGS = (
    "--cd",
    "--disable",
    "--ephemeral",
    "--ignore-user-config",
    "--ignore-rules",
    "--json",
    "--output-schema",
    "--output-last-message",
    "--sandbox",
    "--skip-git-repo-check",
    "--color",
    "--config",
)
BUSINESS_TABLES = (
    "research_profiles",
    "generation_runs",
    "candidates",
    "research_runs",
    "backtest_executions",
    "releases",
)
CAMPAIGN_ID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)


class ResearchConsoleError(StrategyLibraryError):
    """Raised when the local console cannot be configured safely."""


class ControlRequestError(RuntimeError):
    """A normalized error safe to return through the local JSON API."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ResearchConsoleConfig:
    database_path: Path
    runtime_root: Path
    pilot_root: Path
    runtime_identity: Tuple[int, int]
    campaigns_identity: Tuple[int, int]
    pilot_identity: Optional[Tuple[int, int]]
    codex_binary: Optional[Path]
    codex_identity: Optional[Tuple[int, int, int]]
    codex_model: Optional[str]
    check_data_python: Path
    freqtrade_python: Optional[Path]
    freqtrade_source: Optional[Path]
    task_timeout_seconds: float


@dataclass
class _ActiveJob:
    campaign_id: str
    action: str
    process: subprocess.Popen[bytes]
    process_group_id: int
    deadline: float
    monitor: Optional[threading.Thread] = None
    cancel_requested: bool = False
    timed_out: bool = False
    signal_sent_at: Optional[float] = None
    shutdown_requested: bool = False
    output_limit_exceeded: bool = False
    termination_identity_verified: bool = False
    lifecycle_lock: threading.RLock = field(default_factory=threading.RLock)
    receipt_lock: threading.Lock = field(default_factory=threading.Lock)
    prepared_generation: Optional[PreparedGeneration] = None
    prepared_search_round: Optional[PreparedSearchRound] = None
    status_filename: str = "status.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def _resolve_external_directory(value: PathLike, label: str) -> Tuple[Path, Tuple[int, int]]:
    try:
        selected = Path(value).expanduser()
        if selected.is_symlink():
            raise ResearchConsoleError(f"{label} must not be a symlink")
        resolved = selected.resolve(strict=True)
        inspected = os.lstat(resolved)
        project = PROJECT_ROOT.resolve(strict=True)
    except ResearchConsoleError:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise ResearchConsoleError(f"{label} cannot be resolved safely: {exc}") from exc
    if not stat.S_ISDIR(inspected.st_mode):
        raise ResearchConsoleError(f"{label} must be a directory")
    try:
        resolved.relative_to(project)
    except ValueError:
        pass
    else:
        raise ResearchConsoleError(f"{label} must stay outside Git")
    return resolved, (inspected.st_dev, inspected.st_ino)


def _resolve_pilot_directory(
    value: PathLike,
) -> Tuple[Path, Optional[Tuple[int, int]]]:
    """Keep a missing external Pilot as a blocked capability, not a server failure."""
    selected = Path(value).expanduser()
    if selected.exists() or selected.is_symlink():
        return _resolve_external_directory(selected, "pilot root")
    try:
        resolved = selected.resolve(strict=False)
        resolved.relative_to(PROJECT_ROOT.resolve(strict=True))
    except ValueError:
        return resolved, None
    except (OSError, RuntimeError) as exc:
        raise ResearchConsoleError(
            f"pilot root cannot be resolved safely: {exc}"
        ) from exc
    raise ResearchConsoleError("pilot root must stay outside Git")


def _resolve_executable(
    value: Optional[PathLike], default_name: Optional[str]
) -> Optional[Path]:
    candidate = shutil.which(default_name) if value is None and default_name else str(value)
    if not candidate:
        return None
    raw = Path(candidate).expanduser()
    if not raw.is_absolute():
        found = shutil.which(str(raw))
        if not found:
            return None
        raw = Path(found)
    try:
        resolved = raw.resolve(strict=True)
        inspected = os.stat(resolved)
    except (OSError, RuntimeError, ValueError):
        return None
    if not stat.S_ISREG(inspected.st_mode) or not os.access(resolved, os.X_OK):
        return None
    return resolved


def _executable_identity(path: Optional[Path]) -> Optional[Tuple[int, int, int]]:
    if path is None:
        return None
    try:
        inspected = os.lstat(path)
    except OSError:
        return None
    if not stat.S_ISREG(inspected.st_mode) or not os.access(path, os.X_OK):
        return None
    return (inspected.st_dev, inspected.st_ino, inspected.st_mode)


def _minimal_environment() -> Dict[str, str]:
    return {
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": os.environ.get("PATH", "/usr/bin:/bin:/usr/sbin:/sbin"),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUNBUFFERED": "1",
    }


def _codex_environment() -> Dict[str, str]:
    """Pass only fixed locale/path plus the existing auth-location variables."""
    environment = _minimal_environment()
    for name in ("HOME", "CODEX_HOME"):
        value = os.environ.get(name)
        if value:
            environment[name] = value
    return environment


def build_check_data_argv(
    pilot_root: Path,
    python_executable: PathLike = sys.executable,
    *,
    profile_development: bool = False,
) -> Tuple[str, ...]:
    """Return the only child argv exposed by this console slice."""
    script = PILOT_SCRIPT.resolve(strict=True)
    return (
        str(python_executable),
        str(script),
        "check-development-data" if profile_development else "check-data",
        "--pilot-root",
        str(pilot_root),
    )


def _bounded_capability(
    argv: Sequence[str], timeout_seconds: float = 1.0
) -> Tuple[Optional[int], bytes, bool]:
    with tempfile.TemporaryFile() as output:
        try:
            process = subprocess.Popen(
                tuple(argv),
                cwd=str(PROJECT_ROOT),
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=output,
                env=_minimal_environment(),
                shell=False,
                start_new_session=True,
                close_fds=True,
            )
        except OSError:
            return None, b"", False
        try:
            return_code = process.wait(timeout=timeout_seconds)
            timed_out = False
        except subprocess.TimeoutExpired:
            timed_out = True
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
            return_code = None
        output.seek(0)
        return return_code, output.read(PROBE_OUTPUT_BYTES), timed_out


def _safe_version_line(raw: bytes) -> Optional[str]:
    try:
        line = " ".join(raw.decode("utf-8", "strict").splitlines()[0].split())
    except (UnicodeDecodeError, IndexError):
        return None
    if (
        not line
        or len(line) > 120
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 ._+()-]*", line) is None
    ):
        return None
    return line


def _atomic_write_json_at(
    directory_fd: int, name: str, payload: Mapping[str, Any]
) -> None:
    if not name or Path(name).name != name:
        raise ValueError("invalid state filename")
    body = (
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")
    temporary = f".{name}.{uuid4().hex}.tmp"
    descriptor: Optional[int] = None
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | os.O_NOFOLLOW
            | os.O_CLOEXEC,
            0o600,
            dir_fd=directory_fd,
        )
        inspected = os.fstat(descriptor)
        if not stat.S_ISREG(inspected.st_mode) or inspected.st_nlink != 1:
            raise OSError("temporary state file is unsafe")
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            descriptor = None
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(
            temporary,
            name,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
        )
        os.fsync(directory_fd)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            os.unlink(temporary, dir_fd=directory_fd)
        except FileNotFoundError:
            pass


def _atomic_publish_bytes_at(directory_fd: int, name: str, body: bytes) -> None:
    """Publish one immutable private file without replacing an existing target."""
    if not name or Path(name).name != name:
        raise ValueError("invalid private filename")
    temporary = f".{name}.{uuid4().hex}.tmp"
    descriptor: Optional[int] = None
    linked = False
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | os.O_NOFOLLOW
            | os.O_CLOEXEC,
            0o600,
            dir_fd=directory_fd,
        )
        inspected = os.fstat(descriptor)
        if not stat.S_ISREG(inspected.st_mode) or inspected.st_nlink != 1:
            raise OSError("temporary private file is unsafe")
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            descriptor = None
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(
            temporary,
            name,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
            follow_symlinks=False,
        )
        linked = True
        os.unlink(temporary, dir_fd=directory_fd)
        os.fsync(directory_fd)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if not linked:
            try:
                os.unlink(temporary, dir_fd=directory_fd)
            except FileNotFoundError:
                pass


def _read_bounded_private_file_at(
    directory_fd: int, name: str, maximum: int
) -> bytes:
    if not name or Path(name).name != name or maximum <= 0:
        raise ValueError("invalid private file request")
    descriptor = os.open(
        name,
        os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
        dir_fd=directory_fd,
    )
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_size > maximum
        ):
            raise ValueError("private file is unsafe")
        chunks = []
        total = 0
        while True:
            chunk = os.read(descriptor, min(64 * 1024, maximum + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > maximum:
                raise ValueError("private file is too large")
        after = os.fstat(descriptor)
        if (
            (after.st_dev, after.st_ino) != (before.st_dev, before.st_ino)
            or after.st_size != before.st_size
            or after.st_mtime_ns != before.st_mtime_ns
        ):
            raise ValueError("private file changed while reading")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _read_json_object_at(directory_fd: int, name: str) -> Dict[str, Any]:
    if not name or Path(name).name != name:
        raise ValueError("invalid state filename")
    descriptor = os.open(
        name,
        os.O_RDONLY
        | os.O_NOFOLLOW
        | os.O_NONBLOCK
        | os.O_CLOEXEC,
        dir_fd=directory_fd,
    )
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_size > MAX_STATE_BYTES
        ):
            raise ValueError("invalid state file")
        chunks = []
        total = 0
        while True:
            chunk = os.read(
                descriptor,
                min(64 * 1024, MAX_STATE_BYTES + 1 - total),
            )
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > MAX_STATE_BYTES:
                raise ValueError("state file is too large")
        after = os.fstat(descriptor)
        if (
            (after.st_dev, after.st_ino) != (before.st_dev, before.st_ino)
            or after.st_size != before.st_size
            or after.st_mtime_ns != before.st_mtime_ns
        ):
            raise ValueError("state file changed while reading")
        value = _strict_json_object(b"".join(chunks))
    finally:
        os.close(descriptor)
    if not isinstance(value, dict):
        raise ValueError("state document must be an object")
    return value


def _open_private_output_at(directory_fd: int, name: str):
    descriptor = os.open(
        name,
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | os.O_NOFOLLOW
        | os.O_CLOEXEC,
        0o600,
        dir_fd=directory_fd,
    )
    try:
        inspected = os.fstat(descriptor)
        if stat.S_ISREG(inspected.st_mode) and inspected.st_nlink == 1:
            return os.fdopen(descriptor, "wb", closefd=True)
    except Exception:
        os.close(descriptor)
        raise
    os.close(descriptor)
    raise OSError("private output is not an independent regular file")


def _acquire_runtime_lock(
    runtime_root: Path, expected_identity: Tuple[int, int]
) -> int:
    flags = (
        os.O_RDONLY
        | os.O_DIRECTORY
        | os.O_NOFOLLOW
        | os.O_CLOEXEC
    )
    descriptor: Optional[int] = None
    try:
        descriptor = os.open(runtime_root, flags)
        inspected = os.fstat(descriptor)
        if (
            not stat.S_ISDIR(inspected.st_mode)
            or (inspected.st_dev, inspected.st_ino) != expected_identity
        ):
            raise ResearchConsoleError("runtime root identity changed before lock")
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return descriptor
    except BlockingIOError as exc:
        if descriptor is not None:
            os.close(descriptor)
        raise ResearchConsoleError(
            "runtime root is already owned by another Research Console"
        ) from exc
    except Exception:
        if descriptor is not None:
            os.close(descriptor)
        raise


def _public_status(value: Mapping[str, Any]) -> Dict[str, Any]:
    allowed = (
        "schema",
        "campaign_id",
        "action",
        "status",
        "created_at_utc",
        "started_at_utc",
        "finished_at_utc",
        "return_code",
        "requires_confirmation",
        "message",
    )
    return {key: value.get(key) for key in allowed}


class ResearchConsoleController:
    """Own one child process and Git-external campaign receipts."""

    def __init__(
        self,
        database_path: Path,
        runtime_root: PathLike,
        pilot_root: PathLike,
        *,
        search_root: Optional[PathLike] = None,
        codex_binary: Optional[PathLike] = None,
        codex_model: Optional[str] = None,
        check_data_python: PathLike = sys.executable,
        freqtrade_python: Optional[PathLike] = None,
        freqtrade_source: Optional[PathLike] = None,
        webserver_base_url: str = "http://127.0.0.1:8080",
        artifact_root: Optional[PathLike] = None,
        release_root: Optional[PathLike] = None,
        frequi_config: Optional[FreqUIConfig] = None,
        task_timeout_seconds: float = 300.0,
    ) -> None:
        if (
            isinstance(task_timeout_seconds, bool)
            or not isinstance(task_timeout_seconds, (int, float))
            or not 0.1 <= float(task_timeout_seconds) <= 86400
        ):
            raise ResearchConsoleError(
                "task timeout must be between 0.1 and 86400 seconds"
            )
        runtime, runtime_identity = _resolve_external_directory(
            runtime_root, "runtime root"
        )
        pilot, pilot_identity = _resolve_pilot_directory(pilot_root)
        resolved_python = _resolve_executable(check_data_python, None)
        if resolved_python is None:
            raise ResearchConsoleError("CHECK_DATA Python is unavailable")
        try:
            normalized_webserver = _loopback_base_url(webserver_base_url)
        except FreqUIConfigurationError as exc:
            raise ResearchConsoleError("webserver probe URL is unsafe") from exc
        try:
            selected_codex_model = validate_model_name(codex_model)
        except GenerationContractError as exc:
            raise ResearchConsoleError("Codex model is unsafe") from exc
        self._runtime_lock_fd = _acquire_runtime_lock(runtime, runtime_identity)
        self._campaigns_fd = -1
        self._lock = threading.RLock()
        self._active: Optional[_ActiveJob] = None
        self._state_unavailable: set[str] = set()
        self._restart_confirmation_required = False
        self._shutting_down = False
        self._closed = False
        # Only an explicitly configured root selects the Profile Search path.
        # A broken explicit capability remains fail closed for this controller,
        # while unrelated database history cannot disable legacy Development.
        self._search_mode_configured = search_root is not None
        self._search_capability: Optional[FrozenSearchCapability] = None
        self._release_root: Optional[FrozenReleaseRoot] = None
        try:
            campaigns = runtime / "campaigns"
            try:
                try:
                    os.mkdir("campaigns", 0o700, dir_fd=self._runtime_lock_fd)
                except FileExistsError:
                    pass
                self._campaigns_fd = os.open(
                    "campaigns",
                    os.O_RDONLY
                    | os.O_DIRECTORY
                    | os.O_NOFOLLOW
                    | os.O_CLOEXEC,
                    dir_fd=self._runtime_lock_fd,
                )
                opened_campaigns = os.fstat(self._campaigns_fd)
                if not stat.S_ISDIR(opened_campaigns.st_mode):
                    raise ResearchConsoleError(
                        "runtime campaigns path is unsafe"
                    )
                os.fchmod(self._campaigns_fd, 0o700)
            except OSError as exc:
                raise ResearchConsoleError(
                    f"runtime campaigns path cannot be prepared: {exc}"
                ) from exc
            resolved_codex = _resolve_executable(codex_binary, "codex")
            self.config = ResearchConsoleConfig(
                database_path=database_path,
                runtime_root=runtime,
                pilot_root=pilot,
                runtime_identity=runtime_identity,
                campaigns_identity=(
                    opened_campaigns.st_dev,
                    opened_campaigns.st_ino,
                ),
                pilot_identity=pilot_identity,
                codex_binary=resolved_codex,
                codex_identity=_executable_identity(resolved_codex),
                codex_model=selected_codex_model,
                check_data_python=resolved_python,
                freqtrade_python=(
                    None
                    if freqtrade_python is None
                    else Path(freqtrade_python).expanduser()
                ),
                freqtrade_source=(
                    None
                    if freqtrade_source is None
                    else Path(freqtrade_source).expanduser()
                ),
                task_timeout_seconds=float(task_timeout_seconds),
            )
            self.webserver_probe_config = FreqUIConfig(
                normalized_webserver, None, None
            )
            self._artifact_root = (
                None if artifact_root is None else Path(artifact_root)
            )
            self._release_root = freeze_release_root(
                runtime / "releases" if release_root is None else release_root,
                PROJECT_ROOT,
                create=release_root is None,
            )
            self._frequi_config = frequi_config or FreqUIConfig(None, None, None)
            self.campaigns_root = campaigns
            self.check_data_argv = (
                build_check_data_argv(
                    pilot,
                    resolved_python,
                    profile_development=True,
                )
                if self._search_mode_configured
                else build_check_data_argv(pilot, resolved_python)
            )
            self._frozen_codex_capability = self._codex_preflight()
            self._search_capability = freeze_search_capability(
                self.config.database_path,
                search_root,
                freqtrade_python,
                freqtrade_source,
            )
            # Reconcile a complete Round 1 or terminal receipt and fail closed
            # on an interrupted partial ledger. Search recovery remains
            # independent of Console/Codex; only the explicit Search root keeps
            # this controller on the finalist-gated Development path.
            try:
                self._finalize_search_terminal(recover=True)
            except SearchCampaignError:
                # A damaged Search receipt must not prevent Console or Codex
                # generation; an explicitly configured Search path still keeps
                # Development closed until its finalist can be verified.
                self._search_capability.close()
                self._search_capability = FrozenSearchCapability(
                    status="BLOCKED_DATA",
                    reason="Search state is incomplete or invalid",
                )
            development_profile_contract = None
            if search_root is not None:
                search_capability = self._search_capability
                if (
                    search_capability.status == "READY"
                    and search_capability.profile_snapshot is not None
                    and search_capability.search_timerange is not None
                    and search_capability.development_timerange is not None
                    and search_capability.pre_roll_candles is not None
                ):
                    from lab import bounded_research as bounded_pilot

                    try:
                        development_profile_contract = bounded_pilot.profile_search_contract(
                            search_capability.profile_snapshot,
                            search_capability.search_timerange,
                            search_capability.development_timerange,
                            search_capability.pre_roll_candles,
                            search_capability.economic_gate,
                        )
                    except bounded_pilot.PilotError:
                        development_profile_contract = None
                if development_profile_contract is None:
                    self._development_capability = FrozenDevelopmentCapability(
                        status=search_capability.status,
                        reason=(
                            "Development requires one frozen valid Search Profile contract"
                        ),
                    )
                else:
                    self._development_capability = freeze_development_capability(
                        pilot,
                        freqtrade_python,
                        freqtrade_source,
                        profile_contract=development_profile_contract,
                    )
                    if (
                        self._development_capability.status == "READY"
                        and (
                            search_capability.source_acquisition_sha256 is None
                            or self._development_capability.source_acquisition_sha256
                            != search_capability.source_acquisition_sha256
                        )
                    ):
                        self._development_capability = FrozenDevelopmentCapability(
                            status="BLOCKED_DATA",
                            reason=(
                                "Search and Development source acquisitions do not match"
                            ),
                            profile_contract=development_profile_contract,
                        )
            else:
                self._development_capability = freeze_development_capability(
                    pilot,
                    freqtrade_python,
                    freqtrade_source,
                )
            self._holdout_capability = (
                FrozenHoldoutCapability(
                    status="SEALED_UNREAD",
                    reason=EXPLICIT_SEARCH_SEALED_REASON,
                )
                if self._search_mode_configured
                else freeze_holdout_capability(
                    pilot,
                    freqtrade_python,
                    freqtrade_source,
                )
            )
            self._restart_confirmation_required = (
                self._recover_interrupted_campaigns()
            )
        except Exception:
            if self._release_root is not None:
                self._release_root.close()
                self._release_root = None
            if self._search_capability is not None:
                self._search_capability.close()
            if self._campaigns_fd >= 0:
                os.close(self._campaigns_fd)
                self._campaigns_fd = -1
            fcntl.flock(self._runtime_lock_fd, fcntl.LOCK_UN)
            os.close(self._runtime_lock_fd)
            raise

    def _directory_unchanged(
        self, path: Path, identity: Optional[Tuple[int, int]]
    ) -> bool:
        if identity is None:
            return False
        try:
            inspected = os.stat(path)
        except OSError:
            return False
        return (
            stat.S_ISDIR(inspected.st_mode)
            and (inspected.st_dev, inspected.st_ino) == identity
        )

    def _campaign_directory(self, campaign_id: str, *, must_exist: bool) -> Path:
        try:
            canonical = str(UUID(campaign_id))
        except (ValueError, AttributeError) as exc:
            raise ControlRequestError(
                404, "campaign_not_found", "Campaign 不存在"
            ) from exc
        if canonical != campaign_id or CAMPAIGN_ID.fullmatch(campaign_id) is None:
            raise ControlRequestError(404, "campaign_not_found", "Campaign 不存在")
        path = self.campaigns_root / campaign_id
        if must_exist:
            try:
                if path.is_symlink() or not path.is_dir():
                    raise FileNotFoundError
                resolved = path.resolve(strict=True)
            except (OSError, RuntimeError):
                raise ControlRequestError(
                    404, "campaign_not_found", "Campaign 不存在"
                ) from None
            if resolved.parent != self.campaigns_root:
                raise ControlRequestError(
                    404, "campaign_not_found", "Campaign 不存在"
                )
            return resolved
        return path

    def _open_campaign_fd(self, campaign_id: str) -> int:
        self._campaign_directory(campaign_id, must_exist=False)
        descriptor = os.open(
            campaign_id,
            os.O_RDONLY
            | os.O_DIRECTORY
            | os.O_NOFOLLOW
            | os.O_CLOEXEC,
            dir_fd=self._campaigns_fd,
        )
        try:
            if stat.S_ISDIR(os.fstat(descriptor).st_mode):
                return descriptor
        except Exception:
            os.close(descriptor)
            raise
        os.close(descriptor)
        raise ControlRequestError(
            409, "campaign_state_unavailable", "Campaign 状态无法安全读取"
        )

    def _read_campaign_json(self, campaign_id: str, name: str) -> Dict[str, Any]:
        descriptor: Optional[int] = None
        try:
            descriptor = self._open_campaign_fd(campaign_id)
            return _read_json_object_at(descriptor, name)
        except (
            OSError,
            UnicodeDecodeError,
            json.JSONDecodeError,
            RecursionError,
            ValueError,
        ) as exc:
            raise ControlRequestError(
                409, "campaign_state_unavailable", "Campaign 状态无法安全读取"
            ) from exc
        finally:
            if descriptor is not None:
                os.close(descriptor)

    @staticmethod
    def _load_events_at(
        campaign_fd: int, campaign_id: str
    ) -> Dict[str, Any]:
        try:
            value = _read_json_object_at(campaign_fd, "events.json")
        except FileNotFoundError:
            return {
                "schema": EVENTS_SCHEMA,
                "campaign_id": campaign_id,
                "events": [],
            }
        events = value.get("events")
        if (
            value.get("schema") != EVENTS_SCHEMA
            or value.get("campaign_id") != campaign_id
            or not isinstance(events, list)
        ):
            raise ControlRequestError(
                409, "campaign_state_unavailable", "Campaign 事件无法安全读取"
            )
        previous = 0
        for event in events:
            sequence = event.get("sequence") if isinstance(event, dict) else None
            if (
                isinstance(sequence, bool)
                or not isinstance(sequence, int)
                or sequence <= previous
            ):
                raise ControlRequestError(
                    409, "campaign_state_unavailable", "Campaign 事件无法安全读取"
                )
            previous = sequence
        return value

    def _load_events(self, campaign_dir: Path) -> Dict[str, Any]:
        descriptor: Optional[int] = None
        try:
            descriptor = self._open_campaign_fd(campaign_dir.name)
            return self._load_events_at(descriptor, campaign_dir.name)
        except ControlRequestError:
            raise
        except Exception as exc:
            raise ControlRequestError(
                409, "campaign_state_unavailable", "Campaign 事件无法安全读取"
            ) from exc
        finally:
            if descriptor is not None:
                os.close(descriptor)

    def _append_event_at(
        self,
        campaign_fd: int,
        campaign_id: str,
        event_type: str,
        status_value: str,
        message: str,
    ) -> None:
        document = self._load_events_at(campaign_fd, campaign_id)
        events = list(document["events"])
        next_sequence = events[-1]["sequence"] + 1 if events else 1
        if len(events) >= MAX_EVENTS:
            events = events[-(MAX_EVENTS - 1) :]
        events.append(
            {
                "sequence": next_sequence,
                "at_utc": _utc_now(),
                "type": event_type,
                "status": status_value,
                "message": message,
            }
        )
        _atomic_write_json_at(
            campaign_fd,
            "events.json",
            {
                "schema": EVENTS_SCHEMA,
                "campaign_id": campaign_id,
                "events": events,
            },
        )

    def _append_event(
        self, campaign_dir: Path, event_type: str, status_value: str, message: str
    ) -> None:
        descriptor: Optional[int] = None
        try:
            descriptor = self._open_campaign_fd(campaign_dir.name)
            self._append_event_at(
                descriptor,
                campaign_dir.name,
                event_type,
                status_value,
                message,
            )
        finally:
            if descriptor is not None:
                os.close(descriptor)

    def _reconcile_codex_generation_at(
        self,
        campaign_fd: int,
        campaign_id: str,
        current: Optional[Dict[str, Any]],
    ) -> Optional[str]:
        """Reconcile one local campaign against the atomic Codex DB state."""
        finished = _utc_now()
        try:
            database_state = fail_generation(
                self.config.database_path,
                campaign_id,
                error_code="RESTART_INTERRUPTED",
                error_message="Service restarted before generation closed",
                finished_at=finished,
            )
        except GenerationContractError as exc:
            if exc.code == "generation_not_found":
                return None
            self._state_unavailable.add(campaign_id)
            return "UNKNOWN"

        try:
            payload = load_generation(self.config.database_path, campaign_id)
        except GenerationContractError:
            self._state_unavailable.add(campaign_id)
            return "UNKNOWN"
        started_at = payload.get("started_at")
        finished_at = payload.get("finished_at") or finished
        if database_state == "COMPLETED":
            recovered = self._status_document(
                campaign_id,
                "SUCCEEDED",
                action="CODEX_GENERATION",
                created_at=str(started_at or finished_at),
                started_at=(str(started_at) if started_at is not None else None),
                finished_at=str(finished_at),
                return_code=0,
                message="数据库已原子完成 Candidate；未重跑 Codex",
            )
            recovered["requires_confirmation"] = False
            _atomic_write_json_at(campaign_fd, "status.json", recovered)
            self._append_event_at(
                campaign_fd,
                campaign_id,
                "RECOVERED_COMPLETED",
                "SUCCEEDED",
                "已按数据库原子终态恢复显示；未重跑 Codex",
            )
            return "COMPLETED"

        interrupted = self._status_document(
            campaign_id,
            "INTERRUPTED_NEEDS_CONFIRMATION",
            action="CODEX_GENERATION",
            created_at=str(
                (current or {}).get("created_at_utc") or started_at or finished_at
            ),
            started_at=(str(started_at) if started_at is not None else None),
            finished_at=str(finished_at),
            return_code=None,
            message="服务重启，Codex Generation 已原子记为 FAILED；旧进程终态仍需确认",
        )
        interrupted["requires_confirmation"] = True
        _atomic_write_json_at(campaign_fd, "status.json", interrupted)
        self._append_event_at(
            campaign_fd,
            campaign_id,
            "INTERRUPTED",
            "INTERRUPTED_NEEDS_CONFIRMATION",
            "服务重启，Generation 已失败且旧进程终态需要人工确认",
        )
        return "FAILED"

    def _reconcile_development_at(
        self,
        campaign_fd: int,
        campaign_id: str,
        current: Optional[Dict[str, Any]],
    ) -> Optional[str]:
        """Reconcile a Development campaign from its six-table DB contract."""
        try:
            loader = (
                load_public_development_run
                if self._search_mode_configured
                else load_public_holdout_run
            )
            payload = loader(self.config.database_path, campaign_id)
        except (DevelopmentRunError, HoldoutRunError) as exc:
            if exc.code == "run_not_found":
                return None
            self._state_unavailable.add(campaign_id)
            return "UNKNOWN"
        if payload.get("pipeline_version") != "BOUNDED_DEVELOPMENT_V1":
            return None
        if payload["status"] == "RUNNING":
            try:
                payload = fail_development_run(
                    self.config.database_path,
                    campaign_id,
                    "INTERRUPTED",
                    "RESTART_INTERRUPTED",
                )
            except DevelopmentRunError:
                self._state_unavailable.add(campaign_id)
                return "UNKNOWN"
        finished = _utc_now()
        if payload["status"] in {"PENDING", "COMPLETED"}:
            recovered = self._status_document(
                campaign_id,
                "SUCCEEDED",
                action="DEVELOPMENT",
                created_at=str(
                    (current or {}).get("created_at_utc")
                    or payload.get("created_at")
                    or finished
                ),
                started_at=payload.get("started_at"),
                finished_at=payload.get("finished_at") or finished,
                return_code=0,
                message="已按数据库 Development Gate 终态恢复；未重跑",
            )
            recovered["requires_confirmation"] = False
            _atomic_write_json_at(campaign_fd, "status.json", recovered)
            self._append_event_at(
                campaign_fd,
                campaign_id,
                "RECOVERED_COMPLETED",
                "SUCCEEDED",
                "已按数据库终态恢复 Development；未重跑",
            )
            return "COMPLETED"
        interrupted = self._status_document(
            campaign_id,
            "INTERRUPTED_NEEDS_CONFIRMATION",
            action="DEVELOPMENT",
            created_at=str(
                (current or {}).get("created_at_utc")
                or payload.get("created_at")
                or finished
            ),
            started_at=payload.get("started_at"),
            finished_at=payload.get("finished_at") or finished,
            return_code=None,
            message="Development 已按数据库记为中断；旧进程终态需确认",
        )
        interrupted["requires_confirmation"] = True
        _atomic_write_json_at(campaign_fd, "status.json", interrupted)
        self._append_event_at(
            campaign_fd,
            campaign_id,
            "INTERRUPTED",
            "INTERRUPTED_NEEDS_CONFIRMATION",
            "Development 未自动恢复或重跑",
        )
        return "FAILED"

    def _reconcile_holdout_at(
        self,
        campaign_fd: int,
        campaign_id: str,
        current: Optional[Dict[str, Any]],
    ) -> Optional[str]:
        """Reconcile an authorized Holdout continuation without rerunning it."""
        try:
            payload = load_public_holdout_run(
                self.config.database_path, campaign_id
            )
        except HoldoutRunError as exc:
            if exc.code == "run_not_found":
                return None
            self._state_unavailable.add(campaign_id)
            return "UNKNOWN"
        if payload.get("pipeline_version") != "BOUNDED_DEVELOPMENT_V1":
            return None
        executions = payload.get("executions")
        authorization = payload.get("authorization")
        file_database_gap = (
            isinstance(authorization, dict)
            and authorization.get("status") == "CONSUMED_OR_INTERRUPTED"
        )
        continuation_in_database = (
            (isinstance(executions, list) and len(executions) == 3)
            or payload.get("status") == "RUNNING"
            or file_database_gap
        )
        continuation_in_receipt = (
            isinstance(current, dict)
            and current.get("action") == "HOLDOUT_CONTINUATION"
        )
        database_terminal = payload.get("status") in {
            "FAILED",
            "CANCELLED",
            "INTERRUPTED",
        }
        if not continuation_in_database and not continuation_in_receipt:
            return None
        finished = _utc_now()
        if payload.get("status") == "COMPLETED":
            self._copy_frequi_best_effort(campaign_id)
            recovered = self._status_document(
                campaign_id,
                "SUCCEEDED",
                action="HOLDOUT_CONTINUATION",
                created_at=str(
                    (current or {}).get("created_at_utc")
                    or payload.get("created_at")
                    or finished
                ),
                started_at=payload.get("started_at"),
                finished_at=payload.get("finished_at") or finished,
                return_code=0,
                message="已按数据库原子终态恢复 Holdout/Stress；未重跑",
            )
            recovered["requires_confirmation"] = False
            _atomic_write_json_at(
                campaign_fd, "holdout-status.json", recovered
            )
            self._append_event_at(
                campaign_fd,
                campaign_id,
                "RECOVERED_COMPLETED",
                "SUCCEEDED",
                "已按同一 ResearchRun 的三场景终态恢复；未重跑",
            )
            return "COMPLETED"
        if database_terminal:
            terminal_status = str(payload["status"])
            recovered = self._status_document(
                campaign_id,
                terminal_status,
                action="HOLDOUT_CONTINUATION",
                created_at=str(
                    (current or {}).get("created_at_utc")
                    or payload.get("created_at")
                    or finished
                ),
                started_at=payload.get("started_at"),
                finished_at=payload.get("finished_at") or finished,
                return_code=None,
                message=(
                    "已按数据库权威失败终态恢复 Holdout/Stress；"
                    "未补写 Artifact、未恢复或重跑"
                ),
            )
            recovered["requires_confirmation"] = False
            _atomic_write_json_at(
                campaign_fd, "holdout-status.json", recovered
            )
            self._append_event_at(
                campaign_fd,
                campaign_id,
                "RECOVERED_TERMINAL",
                terminal_status,
                "已按数据库权威终态恢复；未重跑",
            )
            return "UNCHANGED"
        if (
            continuation_in_receipt
            and current.get("status") in TERMINAL_STATUSES
            and payload.get("status") != "RUNNING"
        ):
            return (
                "FAILED"
                if current.get("status") == "INTERRUPTED_NEEDS_CONFIRMATION"
                or current.get("requires_confirmation") is True
                else "UNCHANGED"
            )
        if payload.get("status") == "RUNNING" or (
            not file_database_gap
            and continuation_in_receipt
            and current.get("status") in NONTERMINAL_STATUSES
        ):
            try:
                payload = fail_holdout_continuation(
                    self.config.database_path,
                    self.campaigns_root / campaign_id,
                    campaign_id,
                    "INTERRUPTED",
                    "RESTART_INTERRUPTED",
                )
            except HoldoutRunError:
                self._state_unavailable.add(campaign_id)
                return "UNKNOWN"
        interrupted = self._status_document(
            campaign_id,
            "INTERRUPTED_NEEDS_CONFIRMATION",
            action="HOLDOUT_CONTINUATION",
            created_at=str(
                (current or {}).get("created_at_utc")
                or payload.get("created_at")
                or finished
            ),
            started_at=payload.get("started_at"),
            finished_at=payload.get("finished_at") or finished,
            return_code=None,
            message="Holdout continuation 已按数据库记为中断；不会重跑或重试",
        )
        interrupted["requires_confirmation"] = True
        _atomic_write_json_at(
            campaign_fd, "holdout-status.json", interrupted
        )
        self._append_event_at(
            campaign_fd,
            campaign_id,
            "INTERRUPTED",
            "INTERRUPTED_NEEDS_CONFIRMATION",
            "Holdout continuation 已关闭且不会重跑",
        )
        return "FAILED"

    def _recover_interrupted_campaigns(self) -> bool:
        confirmation_required = False
        try:
            entries = tuple(os.listdir(self._campaigns_fd))
        except OSError as exc:
            raise ResearchConsoleError(
                f"runtime campaigns cannot be inspected: {exc}"
            ) from exc
        for campaign_id in entries:
            if not CAMPAIGN_ID.fullmatch(campaign_id):
                continue
            campaign_fd: Optional[int] = None
            try:
                campaign_fd = self._open_campaign_fd(campaign_id)
                if not self._search_mode_configured:
                    try:
                        holdout_current = _read_json_object_at(
                            campaign_fd, "holdout-status.json"
                        )
                    except (
                        FileNotFoundError,
                        OSError,
                        RecursionError,
                        ValueError,
                    ):
                        holdout_current = None
                    holdout_state = self._reconcile_holdout_at(
                        campaign_fd, campaign_id, holdout_current
                    )
                    if holdout_state is not None:
                        if holdout_state in {"FAILED", "UNKNOWN"}:
                            confirmation_required = True
                        os.close(campaign_fd)
                        campaign_fd = None
                        continue
                current = _read_json_object_at(campaign_fd, "status.json")
            except (ControlRequestError, OSError, RecursionError, ValueError):
                if campaign_fd is not None:
                    try:
                        database_state = None
                        if not self._search_mode_configured:
                            database_state = self._reconcile_holdout_at(
                                campaign_fd, campaign_id, None
                            )
                        if database_state is None:
                            database_state = self._reconcile_development_at(
                                campaign_fd, campaign_id, None
                            )
                        if database_state is None:
                            database_state = self._reconcile_codex_generation_at(
                                campaign_fd, campaign_id, None
                            )
                    except Exception:
                        self._state_unavailable.add(campaign_id)
                        database_state = "UNKNOWN"
                    if database_state in {"FAILED", "UNKNOWN"}:
                        confirmation_required = True
                    os.close(campaign_fd)
                continue
            try:
                if (
                    current.get("schema") != STATUS_SCHEMA
                    or current.get("campaign_id") != campaign_id
                ):
                    try:
                        database_state = None
                        if not self._search_mode_configured:
                            database_state = self._reconcile_holdout_at(
                                campaign_fd, campaign_id, current
                            )
                        if database_state is None:
                            database_state = self._reconcile_development_at(
                                campaign_fd, campaign_id, current
                            )
                        if database_state is None:
                            database_state = self._reconcile_codex_generation_at(
                                campaign_fd, campaign_id, current
                            )
                    except Exception:
                        self._state_unavailable.add(campaign_id)
                        database_state = "UNKNOWN"
                    if database_state in {"FAILED", "UNKNOWN"}:
                        confirmation_required = True
                    continue
                if current.get("action") == "CODEX_GENERATION" and (
                    current.get("status") in NONTERMINAL_STATUSES
                    or current.get("status") == "INTERRUPTED_NEEDS_CONFIRMATION"
                ):
                    try:
                        database_state = self._reconcile_codex_generation_at(
                            campaign_fd, campaign_id, current
                        )
                    except Exception:
                        self._state_unavailable.add(campaign_id)
                        database_state = "UNKNOWN"
                    if database_state in {"FAILED", "UNKNOWN", None}:
                        confirmation_required = True
                    continue
                if current.get("action") == "DEVELOPMENT" and (
                    current.get("status") in NONTERMINAL_STATUSES
                    or current.get("status") == "INTERRUPTED_NEEDS_CONFIRMATION"
                ):
                    finished = _utc_now()
                    try:
                        recovered = fail_development_run(
                            self.config.database_path,
                            campaign_id,
                            "INTERRUPTED",
                            "RESTART_INTERRUPTED",
                        )
                    except DevelopmentRunError:
                        self._state_unavailable.add(campaign_id)
                        confirmation_required = True
                        continue
                    if recovered["status"] in {"PENDING", "COMPLETED"}:
                        current.update(
                            {
                                "status": "SUCCEEDED",
                                "finished_at_utc": finished,
                                "return_code": 0,
                                "requires_confirmation": False,
                                "message": (
                                    "已按数据库中 SUCCEEDED execution 幂等完成 Development Gate；未重跑"
                                ),
                            }
                        )
                        self._append_event_at(
                            campaign_fd,
                            campaign_id,
                            "RECOVERED_COMPLETED",
                            "SUCCEEDED",
                            "已按数据库终态恢复 Development；未重跑",
                        )
                    else:
                        current.update(
                            {
                                "status": "INTERRUPTED_NEEDS_CONFIRMATION",
                                "finished_at_utc": finished,
                                "return_code": None,
                                "requires_confirmation": True,
                                "message": "服务重启，Development 已记为 INTERRUPTED；旧进程终态需确认",
                            }
                        )
                        self._append_event_at(
                            campaign_fd,
                            campaign_id,
                            "INTERRUPTED",
                            "INTERRUPTED_NEEDS_CONFIRMATION",
                            "Development 未自动恢复或重跑",
                        )
                        confirmation_required = True
                    _atomic_write_json_at(campaign_fd, "status.json", current)
                    continue
                if current.get("status") == "INTERRUPTED_NEEDS_CONFIRMATION":
                    if current.get("requires_confirmation") is False:
                        current.update(
                            {
                                "status": "INTERRUPTED",
                                "requires_confirmation": False,
                                "message": "旧版受控中断收据已归一；无需人工确认",
                            }
                        )
                        _atomic_write_json_at(
                            campaign_fd, "status.json", current
                        )
                    else:
                        if current.get("requires_confirmation") is not True:
                            current["requires_confirmation"] = True
                            _atomic_write_json_at(
                                campaign_fd, "status.json", current
                            )
                        confirmation_required = True
                    continue
                if current.get("status") not in NONTERMINAL_STATUSES:
                    continue
                finished = _utc_now()
                current.update(
                    {
                        "status": "INTERRUPTED_NEEDS_CONFIRMATION",
                        "finished_at_utc": finished,
                        "return_code": None,
                        "requires_confirmation": True,
                        "message": "服务重启后无法确认原任务终态；未自动恢复或重跑",
                    }
                )
                _atomic_write_json_at(campaign_fd, "status.json", current)
                self._append_event_at(
                    campaign_fd,
                    campaign_id,
                    "INTERRUPTED",
                    "INTERRUPTED_NEEDS_CONFIRMATION",
                    "服务重启，任务终态需要人工确认",
                )
                confirmation_required = True
            finally:
                os.close(campaign_fd)
        return confirmation_required

    def _runtime_paths_unchanged(self) -> bool:
        try:
            runtime_fd_stat = os.fstat(self._runtime_lock_fd)
            campaigns_fd_stat = os.fstat(self._campaigns_fd)
        except OSError:
            return False
        return (
            (runtime_fd_stat.st_dev, runtime_fd_stat.st_ino)
            == self.config.runtime_identity
            and (campaigns_fd_stat.st_dev, campaigns_fd_stat.st_ino)
            == self.config.campaigns_identity
            and self._directory_unchanged(
                self.config.runtime_root, self.config.runtime_identity
            )
            and self._directory_unchanged(
                self.campaigns_root, self.config.campaigns_identity
            )
        )

    def _codex_binary_unchanged(self) -> bool:
        binary = self.config.codex_binary
        expected = self.config.codex_identity
        if binary is None or expected is None:
            return False
        return _executable_identity(binary) == expected

    def _latest_status(self) -> Optional[Dict[str, Any]]:
        latest: Optional[Dict[str, Any]] = None
        try:
            entries = tuple(os.listdir(self._campaigns_fd))
        except OSError:
            return None
        for campaign_id in entries:
            if not CAMPAIGN_ID.fullmatch(campaign_id):
                continue
            try:
                value = self.get_status(campaign_id)
            except ControlRequestError:
                continue
            if latest is None or (
                str(value.get("created_at_utc")), str(value.get("campaign_id"))
            ) > (
                str(latest.get("created_at_utc")), str(latest.get("campaign_id"))
            ):
                latest = value
        return latest

    def _codex_preflight(self) -> Dict[str, Any]:
        binary = self.config.codex_binary
        unknown_features = {feature: None for feature in CODEX_DISABLED_FEATURES}
        if binary is None:
            return {
                "status": "UNAVAILABLE",
                "binary_available": False,
                "version": None,
                "exec_available": False,
                "required_exec_flags": {
                    flag: False for flag in CODEX_REQUIRED_FLAGS
                },
                "sensitive_feature_states": unknown_features,
                "shell_gate_disabled": False,
                "model_invoked": False,
                "message": "Codex CLI 不可用",
            }
        version_code, version_output, version_timeout = _bounded_capability(
            (str(binary), "--version")
        )
        help_code, help_output, help_timeout = _bounded_capability(
            (str(binary), "exec", "--help")
        )
        feature_code, feature_output, feature_timeout = _bounded_capability(
            build_codex_feature_probe_argv(binary)
        )
        if version_timeout or help_timeout or feature_timeout:
            return {
                "status": "UNKNOWN",
                "binary_available": True,
                "version": None,
                "exec_available": False,
                "required_exec_flags": {
                    flag: False for flag in CODEX_REQUIRED_FLAGS
                },
                "sensitive_feature_states": unknown_features,
                "shell_gate_disabled": False,
                "model_invoked": False,
                "message": "Codex CLI capability check 超时",
            }
        try:
            help_text = help_output.decode("utf-8", "strict")
        except UnicodeDecodeError:
            help_text = ""
        feature_states: Dict[str, Optional[bool]] = dict(unknown_features)
        try:
            feature_text = feature_output.decode("utf-8", "strict")
        except UnicodeDecodeError:
            feature_text = ""
        if feature_code == 0:
            for line in feature_text.splitlines():
                parts = line.split()
                if len(parts) >= 3 and parts[-1] in {"true", "false"}:
                    name = parts[0]
                    if name in feature_states:
                        feature_states[name] = parts[-1] == "true"
        version = _safe_version_line(version_output) if version_code == 0 else None
        flags = {
            flag: help_code == 0 and flag in help_text
            for flag in CODEX_REQUIRED_FLAGS
        }
        has_flags = all(flags.values())
        shell_gate_disabled = feature_states.get("shell_tool") is False
        sensitive_features_disabled = all(
            feature_states.get(feature) is False
            for feature in CODEX_REQUIRED_FALSE_FEATURES
        ) and feature_states.get("unified_exec") is not None
        ready = (
            version is not None
            and has_flags
            and feature_code == 0
            and shell_gate_disabled
            and sensitive_features_disabled
        )
        return {
            "status": "READY" if ready else "UNAVAILABLE",
            "binary_available": True,
            "version": version,
            "exec_available": help_code == 0,
            "required_exec_flags": flags,
            "sensitive_feature_states": feature_states,
            "shell_gate_disabled": shell_gate_disabled,
            "model_invoked": False,
            "message": (
                "Codex CLI 固定参数与敏感工具禁用门可用"
                if ready
                else "Codex CLI 缺少受控生成所需参数或敏感工具禁用门"
            ),
        }

    def preflight(self) -> Dict[str, Any]:
        codex = json.loads(json.dumps(self._frozen_codex_capability))
        codex_identity_unchanged = self._codex_binary_unchanged()
        codex["binary_identity_unchanged"] = codex_identity_unchanged
        if codex.get("binary_available") and not codex_identity_unchanged:
            codex["status"] = "UNAVAILABLE"
            codex["message"] = "启动时冻结的 Codex executable 身份已变化"
        try:
            database = validate_strategy_library_database(self.config.database_path)
            with closing(_open_read_only_database(database)) as connection:
                tables = sorted(
                    str(row[0])
                    for row in connection.execute(
                        """
                        SELECT name FROM sqlite_schema
                        WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
                        ORDER BY name
                        """
                    ).fetchall()
                )
                schema_version = int(
                    connection.execute("PRAGMA user_version").fetchone()[0]
                )
                query_only = (
                    int(connection.execute("PRAGMA query_only").fetchone()[0]) == 1
                )
            exact_tables = tables == sorted(BUSINESS_TABLES)
            sqlite_state = {
                "status": (
                    "READY"
                    if schema_version == 1 and query_only and exact_tables
                    else "UNAVAILABLE"
                ),
                "schema_version": schema_version,
                "business_table_count": len(tables),
                "exact_six_tables": exact_tables,
                "query_only": query_only,
                "message": "SQLite schema v1 可只读查询且恰好六张业务表",
            }
        except (OSError, RuntimeError, StrategyLibraryError):
            sqlite_state = {
                "status": "UNAVAILABLE",
                "schema_version": None,
                "business_table_count": None,
                "exact_six_tables": False,
                "query_only": None,
                "message": "SQLite 无法按 schema v1 只读查询",
            }
        runtime_ok = self._runtime_paths_unchanged()
        pilot_ok = self._directory_unchanged(
            self.config.pilot_root, self.config.pilot_identity
        )
        frequi = probe_frequi(self.webserver_probe_config)
        verified_after_ping_reasons = {
            "FREQUI_NOT_INSTALLED",
            "FREQUI_VERSION_MISMATCH",
            "BACKTEST_PAGE_UNAVAILABLE",
        }
        if (
            frequi.get("reachable") is True
            and (
                (frequi.get("available") is True and frequi.get("reason") is None)
                or frequi.get("reason") in verified_after_ping_reasons
            )
        ):
            freqtrade_status = "READY"
        elif frequi.get("reachable") is False:
            freqtrade_status = "UNAVAILABLE"
        else:
            freqtrade_status = "UNKNOWN"
        if frequi.get("available") is True:
            frequi_status = "READY"
        elif frequi.get("reachable") is False or frequi.get("ui_installed") is False:
            frequi_status = "UNAVAILABLE"
        else:
            frequi_status = "UNKNOWN"
        holdout_capability = self._public_holdout_capability()
        checks = {
            "codex": codex,
            "freqtrade": {
                "status": freqtrade_status,
                "webserver_mode": frequi.get("webserver_mode"),
                "message": (
                    "Freqtrade 公共 loopback ping 可达；交易模式仍为 UNKNOWN"
                    if freqtrade_status == "READY"
                    else (
                        "Freqtrade 公共 loopback 服务不可达"
                        if freqtrade_status == "UNAVAILABLE"
                        else "公共 HTTP 可达，但 Freqtrade ping 合同未验证"
                    )
                ),
            },
            "frequi": {
                "status": frequi_status,
                "version": frequi.get("version"),
                "reason": frequi.get("reason"),
                "message": frequi.get("message"),
            },
            "sqlite": sqlite_state,
            "runtime_root": {
                "status": (
                    "READY"
                    if runtime_ok and not self._restart_confirmation_required
                    else "UNAVAILABLE"
                ),
                "outside_git": runtime_ok,
                "atomic_state": True,
                "single_owner_lock": True,
                "restart_confirmation_required": (
                    self._restart_confirmation_required
                ),
                "message": (
                    "检测到崩溃前未闭合任务；本 Slice 不提供确认或自动重跑"
                    if self._restart_confirmation_required
                    else (
                        "Git 外运行目录已冻结"
                        if runtime_ok
                        else "运行目录身份已变化"
                    )
                ),
            },
            "pilot_root": {
                "status": "READY" if pilot_ok else "UNAVAILABLE",
                "outside_git": pilot_ok,
                "message": "Git 外 Pilot 目录已冻结" if pilot_ok else "Pilot 目录身份已变化",
            },
            "development_research": {
                **self._development_capability.public(),
                "message": self._development_capability.reason,
            },
            "holdout_continuation": {
                **holdout_capability,
                "message": holdout_capability["reason"],
            },
        }
        search_capability = self._search_capability
        assert search_capability is not None
        checks["search_research"] = {
            **search_capability.public(),
            "message": search_capability.reason,
        }
        with self._lock:
            latest = self._latest_status()
        ignored_checks = (
            {"holdout_continuation"}
            if self._search_mode_configured
            else {"search_research"}
        )
        return {
            "overall_status": (
                "READY"
                if all(
                    item.get("status") == "READY"
                    for name, item in checks.items()
                    if name not in ignored_checks
                )
                else "NOT_READY"
            ),
            "checks": checks,
            "capability_only": True,
            "latest_campaign": latest,
        }

    def _status_document(
        self,
        campaign_id: str,
        status_value: str,
        *,
        action: str = "CHECK_DATA",
        created_at: str,
        started_at: Optional[str],
        finished_at: Optional[str],
        return_code: Optional[int],
        message: str,
    ) -> Dict[str, Any]:
        return {
            "schema": STATUS_SCHEMA,
            "campaign_id": campaign_id,
            "action": action,
            "status": status_value,
            "created_at_utc": created_at,
            "started_at_utc": started_at,
            "finished_at_utc": finished_at,
            "return_code": return_code,
            "message": message,
        }

    @staticmethod
    def _write_status_at(
        campaign_fd: int,
        status_value: str,
        message: str,
        *,
        status_filename: str = "status.json",
        **updates: Any,
    ) -> Dict[str, Any]:
        try:
            current = _read_json_object_at(campaign_fd, status_filename)
        except FileNotFoundError:
            current = {}
        current.update({"status": status_value, "message": message, **updates})
        _atomic_write_json_at(campaign_fd, status_filename, current)
        return current

    def _write_status(
        self,
        campaign_dir: Path,
        status_value: str,
        message: str,
        *,
        status_filename: str = "status.json",
        **updates: Any,
    ) -> Dict[str, Any]:
        descriptor: Optional[int] = None
        try:
            descriptor = self._open_campaign_fd(campaign_dir.name)
            return self._write_status_at(
                descriptor,
                status_value,
                message,
                status_filename=status_filename,
                **updates,
            )
        finally:
            if descriptor is not None:
                os.close(descriptor)

    def _record_transition(
        self,
        campaign_dir: Path,
        status_value: str,
        message: str,
        event_type: str,
        *,
        status_filename: str = "status.json",
        **updates: Any,
    ) -> Optional[Dict[str, Any]]:
        """Best-effort receipts must never control process termination."""
        current: Optional[Dict[str, Any]] = None
        descriptor: Optional[int] = None
        try:
            descriptor = self._open_campaign_fd(campaign_dir.name)
        except Exception:
            return None
        try:
            current = self._write_status_at(
                descriptor,
                status_value,
                message,
                status_filename=status_filename,
                **updates,
            )
        except Exception:
            pass
        try:
            self._append_event_at(
                descriptor,
                campaign_dir.name,
                event_type,
                status_value,
                message,
            )
        except Exception:
            pass
        finally:
            os.close(descriptor)
        return current

    @staticmethod
    def _process_group_state(job: _ActiveJob) -> Optional[bool]:
        if job.process_group_id <= 1:
            return None
        try:
            os.killpg(job.process_group_id, 0)
        except ProcessLookupError:
            return False
        except OSError:
            return None
        return True

    @classmethod
    def _wait_for_process_group(cls, job: _ActiveJob, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if cls._process_group_state(job) is False:
                return True
            time.sleep(0.02)
        return cls._process_group_state(job) is False

    @staticmethod
    def _poll_leader(job: _ActiveJob) -> Optional[int]:
        with job.lifecycle_lock:
            return job.process.poll()

    @staticmethod
    def _leader_return_code(job: _ActiveJob) -> Optional[int]:
        with job.lifecycle_lock:
            return job.process.returncode

    def _terminate_owned_job(self, job: _ActiveJob) -> bool:
        with job.lifecycle_lock:
            if job.process.returncode is None:
                if not job.termination_identity_verified:
                    if not self._signal_process_group(job, signal.SIGTERM):
                        job.process.poll()
                        if job.process.returncode is None:
                            return False
                    elif job.signal_sent_at is None:
                        job.signal_sent_at = time.monotonic()
                if (
                    job.process.returncode is None
                    and job.termination_identity_verified
                ):
                    remaining_grace = max(
                        0.0,
                        GROUP_TERMINATION_CONFIRM_SECONDS
                        - (time.monotonic() - (job.signal_sent_at or 0.0)),
                    )
                    if remaining_grace:
                        time.sleep(remaining_grace)
                    self._signal_process_group(job, signal.SIGKILL)
                try:
                    job.process.wait(timeout=GROUP_TERMINATION_CONFIRM_SECONDS)
                except subprocess.TimeoutExpired:
                    return False
        return self._wait_for_process_group(
            job, GROUP_TERMINATION_CONFIRM_SECONDS
        )

    def create_campaign(self) -> Dict[str, Any]:
        with self._lock:
            if self._closed or self._shutting_down:
                raise ControlRequestError(
                    409, "console_shutting_down", "Research Console 正在关闭"
                )
            if self._restart_confirmation_required:
                raise ControlRequestError(
                    409,
                    "restart_confirmation_required",
                    "检测到崩溃前未闭合任务；请人工确认后换用新的运行目录",
                )
            if self._active is not None:
                raise ControlRequestError(
                    409, "active_campaign", "已有一个受控任务正在运行"
                )
            if not self._runtime_paths_unchanged():
                raise ControlRequestError(
                    409, "frozen_path_changed", "启动时冻结的运行目录身份已变化"
                )
            if self.config.pilot_identity is None:
                raise ControlRequestError(
                    503, "pilot_unavailable", "Pilot root 在启动时不可用"
                )
            if not self._directory_unchanged(
                self.config.pilot_root, self.config.pilot_identity
            ):
                raise ControlRequestError(
                    409, "frozen_path_changed", "启动时冻结的 Pilot 目录身份已变化"
                )
            campaign_id = str(uuid4())
            campaign_dir = self._campaign_directory(campaign_id, must_exist=False)
            try:
                os.mkdir(campaign_id, 0o700, dir_fd=self._campaigns_fd)
            except OSError as exc:
                raise ControlRequestError(
                    500, "campaign_create_failed", "Campaign 运行目录无法创建"
                ) from exc
            created = _utc_now()
            starting = self._status_document(
                campaign_id,
                "STARTING",
                created_at=created,
                started_at=None,
                finished_at=None,
                return_code=None,
                message="正在启动固定 CHECK_DATA",
            )
            stdout_handle = None
            stderr_handle = None
            campaign_fd: Optional[int] = None
            try:
                campaign_fd = self._open_campaign_fd(campaign_id)
                _atomic_write_json_at(
                    campaign_fd,
                    "request.json",
                    {
                        "schema": REQUEST_SCHEMA,
                        "campaign_id": campaign_id,
                        "action": "CHECK_DATA",
                        "created_at_utc": created,
                    },
                )
                _atomic_write_json_at(campaign_fd, "status.json", starting)
                self._append_event_at(
                    campaign_fd,
                    campaign_id,
                    "CREATED",
                    "STARTING",
                    "已创建固定 CHECK_DATA 任务",
                )
                stdout_handle = _open_private_output_at(campaign_fd, "stdout.log")
                stderr_handle = _open_private_output_at(campaign_fd, "stderr.log")
            except (OSError, ControlRequestError) as exc:
                if stdout_handle is not None:
                    stdout_handle.close()
                self._record_transition(
                    campaign_dir,
                    "FAILED",
                    "固定 CHECK_DATA 私有输出文件无法创建",
                    "OUTPUT_CREATE_FAILED",
                    finished_at_utc=_utc_now(),
                    return_code=None,
                )
                raise ControlRequestError(
                    500, "output_create_failed", "固定 CHECK_DATA 无法安全启动"
                ) from exc
            finally:
                if campaign_fd is not None:
                    os.close(campaign_fd)
            try:
                process = subprocess.Popen(
                    self.check_data_argv,
                    cwd=str(PROJECT_ROOT),
                    stdin=subprocess.DEVNULL,
                    stdout=stdout_handle,
                    stderr=stderr_handle,
                    env=_minimal_environment(),
                    shell=False,
                    start_new_session=True,
                    close_fds=True,
                )
            except OSError as exc:
                stdout_handle.close()
                stderr_handle.close()
                failed = self._write_status(
                    campaign_dir,
                    "FAILED",
                    "固定 CHECK_DATA 无法启动",
                    finished_at_utc=_utc_now(),
                    return_code=None,
                )
                self._append_event(
                    campaign_dir, "START_FAILED", "FAILED", "固定 CHECK_DATA 无法启动"
                )
                raise ControlRequestError(
                    500, "start_failed", failed["message"]
                ) from exc
            job = _ActiveJob(
                campaign_id=campaign_id,
                action="CHECK_DATA",
                process=process,
                process_group_id=process.pid,
                deadline=time.monotonic() + self.config.task_timeout_seconds,
            )
            self._active = job
            try:
                if not stdout_handle.closed:
                    stdout_handle.close()
                if not stderr_handle.closed:
                    stderr_handle.close()
                started = _utc_now()
                campaign_fd = self._open_campaign_fd(campaign_id)
                try:
                    _atomic_write_json_at(
                        campaign_fd,
                        "owner.json",
                        {
                            "schema": OWNER_SCHEMA,
                            "campaign_id": campaign_id,
                            "server_pid": os.getpid(),
                            "child_pid": process.pid,
                            "process_group_id": job.process_group_id,
                            "started_at_utc": started,
                        },
                    )
                finally:
                    os.close(campaign_fd)
                    campaign_fd = None
                running = self._write_status(
                    campaign_dir,
                    "RUNNING",
                    "固定 CHECK_DATA 正在运行",
                    started_at_utc=started,
                )
                self._append_event(
                    campaign_dir, "STARTED", "RUNNING", "固定 CHECK_DATA 已启动"
                )
                monitor = threading.Thread(
                    target=self._monitor_job,
                    args=(job,),
                    name=f"research-console-{campaign_id[:8]}",
                    daemon=True,
                )
                job.monitor = monitor
                monitor.start()
                return _public_status(running)
            except Exception as exc:
                terminated = self._terminate_owned_job(job)
                receipt = self._record_transition(
                    campaign_dir,
                    "FAILED" if terminated else "INTERRUPTED_NEEDS_CONFIRMATION",
                    (
                        "CHECK_DATA 启动收据失败，受控进程已终止"
                        if terminated
                        else "CHECK_DATA 启动收据失败，无法确认进程终态"
                    ),
                    "START_RECEIPT_FAILED",
                    finished_at_utc=_utc_now(),
                    return_code=self._leader_return_code(job),
                    requires_confirmation=not terminated,
                )
                if receipt is None and not self._has_legal_terminal_receipt(job):
                    self._state_unavailable.add(campaign_id)
                    self._restart_confirmation_required = True
                if self._active is job:
                    self._active = None
                if not terminated:
                    self._restart_confirmation_required = True
                raise ControlRequestError(
                    500,
                    "start_receipt_failed",
                    "固定 CHECK_DATA 无法安全完成启动",
                ) from exc

    def _persist_generation_failure(
        self,
        generation_id: str,
        *,
        error_code: str,
        error_message: str,
        finished_at: str,
        details: Optional[Mapping[str, Any]] = None,
    ) -> bool:
        try:
            state = fail_generation(
                self.config.database_path,
                generation_id,
                error_code=error_code,
                error_message=error_message,
                finished_at=finished_at,
                details=details,
            )
        except GenerationContractError:
            with self._lock:
                self._state_unavailable.add(generation_id)
                self._restart_confirmation_required = True
            return False
        return state == "FAILED"

    def create_generation(self, request: GenerationRequest) -> Dict[str, Any]:
        """Start one fixed Codex generation in the existing single process slot."""
        with self._lock:
            if self._closed or self._shutting_down:
                raise ControlRequestError(
                    409, "console_shutting_down", "Research Console 正在关闭"
                )
            if self._restart_confirmation_required:
                raise ControlRequestError(
                    409,
                    "restart_confirmation_required",
                    "检测到崩溃前未闭合任务；请人工确认后换用新的运行目录",
                )
            if self._active is not None:
                raise ControlRequestError(
                    409, "active_campaign", "已有一个受控任务正在运行"
                )
            if not self._runtime_paths_unchanged():
                raise ControlRequestError(
                    409, "frozen_path_changed", "启动时冻结的运行目录身份已变化"
                )
            search_capability = self._search_capability
            assert search_capability is not None
            try:
                parent_lock = load_search_context(
                    self.config.database_path, search_capability
                ).get("codex_parent_lock")
            except SearchCampaignError:
                # Only a valid completed Round 1 may lock generation fields.
                # Search corruption is local and cannot block ordinary Codex.
                parent_lock = None
            if isinstance(parent_lock, Mapping) and (
                request.parent_candidate_id
                != parent_lock.get("parent_candidate_id")
                or request.profile_id != parent_lock.get("profile_id")
                or request.strategy_family != parent_lock.get("strategy_family")
            ):
                raise ControlRequestError(
                    409,
                    "search_parent_locked",
                    "Search Round 1 已锁定 Codex parent、Profile 与 mechanism",
                )
            binary = self.config.codex_binary
            if (
                binary is None
                or self._frozen_codex_capability.get("status") != "READY"
            ):
                raise ControlRequestError(
                    503,
                    "codex_capability_unavailable",
                    "Codex CLI 固定参数或敏感工具禁用门不可用",
                )
            if not self._codex_binary_unchanged():
                raise ControlRequestError(
                    409,
                    "codex_binary_changed",
                    "启动时冻结的 Codex executable 身份已变化",
                )

            generation_id = str(uuid4())
            campaign_dir = self._campaign_directory(
                generation_id, must_exist=False
            )
            try:
                os.mkdir(generation_id, 0o700, dir_fd=self._campaigns_fd)
            except OSError as exc:
                raise ControlRequestError(
                    500, "generation_create_failed", "生成运行目录无法创建"
                ) from exc
            created = _utc_now()
            starting = self._status_document(
                generation_id,
                "STARTING",
                action="CODEX_GENERATION",
                created_at=created,
                started_at=None,
                finished_at=None,
                return_code=None,
                message="正在启动固定 Codex Candidate 生成",
            )
            stdout_handle = None
            stderr_handle = None
            stdin_handle = None
            campaign_fd: Optional[int] = None
            workspace_fd: Optional[int] = None
            try:
                campaign_fd = self._open_campaign_fd(generation_id)
                os.mkdir("workspace", 0o700, dir_fd=campaign_fd)
                workspace_fd = os.open(
                    "workspace",
                    os.O_RDONLY
                    | os.O_DIRECTORY
                    | os.O_NOFOLLOW
                    | os.O_CLOEXEC,
                    dir_fd=campaign_fd,
                )
                workspace_stat = os.fstat(workspace_fd)
                if not stat.S_ISDIR(workspace_stat.st_mode):
                    raise OSError("isolated workspace is unsafe")
                os.fchmod(workspace_fd, 0o700)
                _atomic_write_json_at(
                    campaign_fd, "output-schema.json", codex_output_schema()
                )
                _atomic_write_json_at(
                    campaign_fd,
                    "request.json",
                    {
                        "schema": REQUEST_SCHEMA,
                        "campaign_id": generation_id,
                        "action": "CODEX_GENERATION",
                        "created_at_utc": created,
                        "input": request.public_fields(),
                    },
                )
                _atomic_write_json_at(campaign_fd, "status.json", starting)
                self._append_event_at(
                    campaign_fd,
                    generation_id,
                    "CREATED",
                    "STARTING",
                    "已创建固定 Codex Candidate 生成任务",
                )
                stdout_handle = _open_private_output_at(campaign_fd, "stdout.log")
                stderr_handle = _open_private_output_at(campaign_fd, "stderr.log")
            except (OSError, ControlRequestError, ValueError) as exc:
                if stdout_handle is not None:
                    stdout_handle.close()
                if stderr_handle is not None:
                    stderr_handle.close()
                self._record_transition(
                    campaign_dir,
                    "FAILED",
                    "固定 Codex 生成私有运行文件无法创建",
                    "OUTPUT_CREATE_FAILED",
                    finished_at_utc=_utc_now(),
                    return_code=None,
                )
                raise ControlRequestError(
                    500, "output_create_failed", "固定 Codex 生成无法安全启动"
                ) from exc
            finally:
                if workspace_fd is not None:
                    os.close(workspace_fd)
                if campaign_fd is not None:
                    os.close(campaign_fd)

            prepared: Optional[PreparedGeneration] = None
            process: Optional[subprocess.Popen[bytes]] = None
            job: Optional[_ActiveJob] = None
            try:
                prepared = start_generation(
                    self.config.database_path,
                    generation_id,
                    request,
                    model=self.config.codex_model,
                    started_at=created,
                )
                workspace = campaign_dir / "workspace"
                prompt = build_prompt(request, prepared.profile, prepared.parent)
                stdin_handle = tempfile.TemporaryFile(mode="w+b", dir=campaign_dir)
                os.fchmod(stdin_handle.fileno(), 0o600)
                stdin_handle.write(prompt)
                stdin_handle.flush()
                stdin_handle.seek(0)
                argv = build_codex_argv(
                    binary,
                    workspace,
                    campaign_dir / "output-schema.json",
                    campaign_dir / "codex-output.json",
                    model=self.config.codex_model,
                )
                process = subprocess.Popen(
                    argv,
                    cwd=str(workspace),
                    stdin=stdin_handle,
                    stdout=stdout_handle,
                    stderr=stderr_handle,
                    env=_codex_environment(),
                    shell=False,
                    start_new_session=True,
                    close_fds=True,
                    umask=0o077,
                )
                stdin_handle.close()
                stdin_handle = None
                job = _ActiveJob(
                    campaign_id=generation_id,
                    action="CODEX_GENERATION",
                    process=process,
                    process_group_id=process.pid,
                    deadline=time.monotonic() + self.config.task_timeout_seconds,
                    prepared_generation=prepared,
                )
                self._active = job
            except (GenerationContractError, OSError, BrokenPipeError) as exc:
                if stdin_handle is not None:
                    stdin_handle.close()
                if stdout_handle is not None and not stdout_handle.closed:
                    stdout_handle.close()
                if stderr_handle is not None and not stderr_handle.closed:
                    stderr_handle.close()
                terminated = True
                if job is not None:
                    terminated = self._terminate_owned_job(job)
                    if self._active is job:
                        self._active = None
                finished = _utc_now()
                persisted = (
                    True
                    if prepared is None
                    else self._persist_generation_failure(
                        generation_id,
                        error_code="START_FAILED",
                        error_message="Codex generation could not start safely",
                        finished_at=finished,
                    )
                )
                self._record_transition(
                    campaign_dir,
                    "FAILED" if terminated and persisted else "INTERRUPTED_NEEDS_CONFIRMATION",
                    (
                        "固定 Codex 生成无法启动"
                        if terminated and persisted
                        else "固定 Codex 生成启动失败且终态无法确认"
                    ),
                    "START_FAILED",
                    finished_at_utc=finished,
                    return_code=(None if process is None else process.returncode),
                    requires_confirmation=not (terminated and persisted),
                )
                if not terminated or not persisted:
                    self._restart_confirmation_required = True
                status = exc.status if isinstance(exc, GenerationContractError) else 500
                code = exc.code if isinstance(exc, GenerationContractError) else "start_failed"
                raise ControlRequestError(
                    status, code, "固定 Codex 生成无法安全启动"
                ) from exc

            if stdout_handle is not None and not stdout_handle.closed:
                stdout_handle.close()
            if stderr_handle is not None and not stderr_handle.closed:
                stderr_handle.close()
            assert process is not None and job is not None
            try:
                started = _utc_now()
                campaign_fd = self._open_campaign_fd(generation_id)
                try:
                    _atomic_write_json_at(
                        campaign_fd,
                        "owner.json",
                        {
                            "schema": OWNER_SCHEMA,
                            "campaign_id": generation_id,
                            "server_pid": os.getpid(),
                            "child_pid": process.pid,
                            "process_group_id": job.process_group_id,
                            "started_at_utc": started,
                        },
                    )
                finally:
                    os.close(campaign_fd)
                    campaign_fd = None
                self._write_status(
                    campaign_dir,
                    "RUNNING",
                    "固定 Codex Candidate 生成正在运行",
                    started_at_utc=started,
                )
                self._append_event(
                    campaign_dir,
                    "STARTED",
                    "RUNNING",
                    "固定 Codex Candidate 生成已启动",
                )
                monitor = threading.Thread(
                    target=self._monitor_job,
                    args=(job,),
                    name=f"research-console-generation-{generation_id[:8]}",
                    daemon=True,
                )
                job.monitor = monitor
                monitor.start()
                return self.get_generation(generation_id)
            except Exception as exc:
                terminated = self._terminate_owned_job(job)
                finished = _utc_now()
                persisted = self._persist_generation_failure(
                    generation_id,
                    error_code="START_RECEIPT_FAILED",
                    error_message="Codex generation start receipt failed",
                    finished_at=finished,
                )
                self._record_transition(
                    campaign_dir,
                    "FAILED" if terminated and persisted else "INTERRUPTED_NEEDS_CONFIRMATION",
                    "Codex 生成启动收据失败",
                    "START_RECEIPT_FAILED",
                    finished_at_utc=finished,
                    return_code=self._leader_return_code(job),
                    requires_confirmation=not (terminated and persisted),
                )
                if self._active is job:
                    self._active = None
                if not terminated or not persisted:
                    self._restart_confirmation_required = True
                raise ControlRequestError(
                    500,
                    "start_receipt_failed",
                    "固定 Codex 生成无法安全完成启动",
                ) from exc

    def _signal_process_group(
        self, job: _ActiveJob, selected: signal.Signals
    ) -> bool:
        with job.lifecycle_lock:
            if self._active is not job or job.process.returncode is not None:
                return False
            if selected == signal.SIGKILL and job.termination_identity_verified:
                identity_confirmed = True
            else:
                try:
                    identity_confirmed = (
                        job.process.pid > 1
                        and os.getpgid(job.process.pid)
                        == job.process_group_id
                    )
                except OSError:
                    identity_confirmed = False
            if not identity_confirmed:
                return False
            try:
                os.killpg(job.process_group_id, selected)
            except OSError:
                return False
            if selected == signal.SIGTERM:
                job.termination_identity_verified = True
            return True

    def _begin_cancel_locked(self, job: _ActiveJob) -> bool:
        """Request SIGTERM under ``self._lock`` and leave receipt_lock owned."""
        if job.shutdown_requested or job.timed_out:
            raise ControlRequestError(
                409, "termination_in_progress", "任务已进入不可覆盖的终止流程"
            )
        if job.cancel_requested:
            return False
        if not job.receipt_lock.acquire(blocking=False):
            raise ControlRequestError(
                409, "termination_in_progress", "任务状态正在完成，不接受新的取消转换"
            )
        if not self._signal_process_group(job, signal.SIGTERM):
            job.receipt_lock.release()
            raise ControlRequestError(
                409,
                "process_group_unconfirmed",
                "无法安全确认受控 leader 身份；未发送取消信号",
            )
        job.cancel_requested = True
        job.signal_sent_at = time.monotonic()
        return True

    def _has_data_ready_output(self, campaign_dir: Path) -> bool:
        try:
            value = self._read_campaign_json(campaign_dir.name, "stdout.log")
        except (
            ControlRequestError,
            OSError,
            UnicodeDecodeError,
            json.JSONDecodeError,
            RecursionError,
            ValueError,
        ):
            return False
        return value.get("status") == "DATA_READY"

    def _codex_private_outputs_within_limits(self, campaign_id: str) -> bool:
        campaign_fd: Optional[int] = None
        try:
            campaign_fd = self._open_campaign_fd(campaign_id)
            for name, maximum, optional in (
                ("stdout.log", MAX_JSONL_BYTES, False),
                ("stderr.log", MAX_CODEX_STDERR_BYTES, False),
                ("codex-output.json", MAX_CODE_BYTES * 2, True),
            ):
                try:
                    inspected = os.stat(
                        name, dir_fd=campaign_fd, follow_symlinks=False
                    )
                except FileNotFoundError:
                    if optional:
                        continue
                    return False
                if (
                    not stat.S_ISREG(inspected.st_mode)
                    or inspected.st_nlink != 1
                    or inspected.st_size > maximum
                ):
                    return False
            return True
        except (ControlRequestError, OSError, ValueError):
            return False
        finally:
            if campaign_fd is not None:
                os.close(campaign_fd)

    def _finalize_codex_generation(
        self,
        job: _ActiveJob,
        campaign_dir: Path,
        finished_at: str,
    ) -> Tuple[str, str, str]:
        prepared = job.prepared_generation
        if prepared is None:
            raise GenerationContractError(
                "generation_state_conflict", "Generation context is unavailable"
            )
        campaign_fd: Optional[int] = None
        try:
            campaign_fd = self._open_campaign_fd(job.campaign_id)
            jsonl = _read_bounded_private_file_at(
                campaign_fd, "stdout.log", MAX_JSONL_BYTES
            )
            output = _read_bounded_private_file_at(
                campaign_fd, "codex-output.json", MAX_CODE_BYTES * 2
            )
            stderr = _read_bounded_private_file_at(
                campaign_fd, "stderr.log", MAX_CODEX_STDERR_BYTES
            )
            if stderr:
                raise GenerationContractError(
                    "codex_stderr_nonempty",
                    "Codex emitted private diagnostics; generation failed closed",
                )
            summary = validate_codex_jsonl(jsonl)
            candidate = parse_candidate_output(
                output,
                timeframe=str(prepared.profile["timeframe"]),
            )
            _atomic_publish_bytes_at(
                campaign_fd,
                "candidate.py",
                candidate.code_text.encode("utf-8", "strict"),
            )
        except GenerationContractError:
            raise
        except (OSError, UnicodeError, ValueError) as exc:
            raise GenerationContractError(
                "private_output_invalid",
                "Codex private output could not be read or published safely",
            ) from exc
        finally:
            if campaign_fd is not None:
                os.close(campaign_fd)
        complete_generation(
            self.config.database_path,
            prepared,
            candidate,
            raw_output=output,
            jsonl_summary=summary,
            finished_at=finished_at,
        )
        return (
            "SUCCEEDED",
            "Codex Candidate 已生成并以 PENDING 等待人工审核；尚未证明安全、有效、盈利或可交易",
            "SUCCEEDED",
        )

    def _finalize_search_terminal(
        self,
        *,
        campaign_id: Optional[str] = None,
        recover: bool = False,
        return_code: Optional[int] = None,
        failure_code: Optional[str] = None,
        process_group_finalized: bool = True,
        database_digest_before: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Use one entry point for every authoritative Search transition."""
        capability = self._search_capability
        assert capability is not None
        if recover:
            if (
                campaign_id is not None
                or return_code is not None
                or failure_code is not None
            ):
                raise ResearchConsoleError("Search recovery transition is ambiguous")
            return recover_interrupted_search(capability, self.config.database_path)
        if campaign_id is None or failure_code is None:
            raise ResearchConsoleError("Search terminal transition is incomplete")
        if not process_group_finalized:
            with self._lock:
                self._restart_confirmation_required = True
            return None
        if return_code in {0, 3}:
            return complete_search_round(
                capability,
                campaign_id,
                int(return_code),
                self.config.database_path,
                database_digest_before,
            )
        state = fail_search_campaign(
            self.config.database_path,
            capability,
            campaign_id,
            failure_code,
            database_digest_before=database_digest_before,
        )
        if state.get("status") == "RUNNING":
            with self._lock:
                self._restart_confirmation_required = True
        return state

    def _record_job_transition(
        self,
        job: _ActiveJob,
        campaign_dir: Path,
        status_value: str,
        message: str,
        event_type: str,
        **updates: Any,
    ) -> Optional[Dict[str, Any]]:
        """Persist lifecycle state at the job's one frozen state target."""
        if job.prepared_search_round is not None:
            return {}
        return self._record_transition(
            campaign_dir,
            status_value,
            message,
            event_type,
            status_filename=job.status_filename,
            **updates,
        )

    def _has_legal_terminal_receipt(self, job: _ActiveJob) -> bool:
        """Confirm a failed write still left one readable terminal receipt."""
        if job.prepared_search_round is not None:
            return False
        try:
            current = self._read_campaign_json(
                job.campaign_id, job.status_filename
            )
        except ControlRequestError:
            return False
        return (
            current.get("schema") == STATUS_SCHEMA
            and current.get("campaign_id") == job.campaign_id
            and current.get("action") == job.action
            and current.get("status") in TERMINAL_STATUSES
        )

    def _monitor_job(self, job: _ActiveJob) -> None:
        campaign_dir: Optional[Path] = None
        process_group_finalized = False
        try:
            if job.prepared_search_round is None:
                campaign_dir = self._campaign_directory(
                    job.campaign_id, must_exist=True
                )
            else:
                capability = self._search_capability
                if capability is None or capability.search_root is None:
                    raise SearchCampaignError(
                        "BLOCKED_DATA", "Search root is unavailable", status=503
                    )
                campaign_dir = capability.search_root
            while True:
                timeout_started = False
                output_limit_started = False
                if (
                    job.action == "CODEX_GENERATION"
                    and not job.cancel_requested
                    and not job.timed_out
                    and not job.shutdown_requested
                    and not job.output_limit_exceeded
                    and not self._codex_private_outputs_within_limits(
                        job.campaign_id
                    )
                ):
                    with self._lock:
                        if (
                            not job.cancel_requested
                            and not job.timed_out
                            and not job.shutdown_requested
                            and not job.output_limit_exceeded
                        ):
                            job.output_limit_exceeded = True
                            output_limit_started = True
                with self._lock:
                    current = time.monotonic()
                    if (
                        not job.cancel_requested
                        and not job.timed_out
                        and not job.shutdown_requested
                        and current >= job.deadline
                    ):
                        job.timed_out = True
                        timeout_started = True
                    terminating = (
                        job.cancel_requested
                        or job.timed_out
                        or job.shutdown_requested
                        or job.output_limit_exceeded
                    )
                    return_code = (
                        None if terminating else self._poll_leader(job)
                    )
                if return_code is not None:
                    break
                if timeout_started:
                    if self._signal_process_group(job, signal.SIGTERM):
                        with self._lock:
                            if job.signal_sent_at is None:
                                job.signal_sent_at = time.monotonic()
                    with job.receipt_lock:
                        self._record_job_transition(
                            job,
                            campaign_dir,
                            "TIMEOUT_TERMINATING",
                            "任务超时，正在终止受控进程组",
                            "TIMEOUT",
                        )
                if output_limit_started:
                    if self._signal_process_group(job, signal.SIGTERM):
                        with self._lock:
                            if job.signal_sent_at is None:
                                job.signal_sent_at = time.monotonic()
                    with job.receipt_lock:
                        self._record_job_transition(
                            job,
                            campaign_dir,
                            "OUTPUT_LIMIT_TERMINATING",
                            "Codex 私有输出超过固定上限，正在终止受控进程组",
                            "OUTPUT_LIMIT_EXCEEDED",
                        )
                if terminating:
                    process_group_finalized = self._terminate_owned_job(job)
                    break
                time.sleep(0.05)
            return_code = self._leader_return_code(job)
            confirmation_timeout = (
                GROUP_TERMINATION_CONFIRM_SECONDS
                if (
                    job.cancel_requested
                    or job.timed_out
                    or job.shutdown_requested
                    or job.output_limit_exceeded
                )
                else GROUP_EXIT_CONFIRM_SECONDS
            )
            if not process_group_finalized:
                process_group_finalized = self._wait_for_process_group(
                    job, confirmation_timeout
                )
            if not process_group_finalized:
                if job.action == "CODEX_GENERATION":
                    self._persist_generation_failure(
                        job.campaign_id,
                        error_code="PROCESS_GROUP_UNCONFIRMED",
                        error_message="Codex process group could not be confirmed gone",
                        finished_at=_utc_now(),
                    )
                elif job.action == "HOLDOUT_CONTINUATION":
                    try:
                        fail_holdout_continuation(
                            self.config.database_path,
                            campaign_dir,
                            job.campaign_id,
                            "INTERRUPTED",
                            "PROCESS_GROUP_UNCONFIRMED",
                        )
                    except HoldoutRunError:
                        with self._lock:
                            self._state_unavailable.add(job.campaign_id)
                with job.receipt_lock:
                    receipt = self._record_job_transition(
                        job,
                        campaign_dir,
                        "INTERRUPTED_NEEDS_CONFIRMATION",
                        f"{job.action} 进程组仍存在或无法确认消失；未继续发送未经确认的信号",
                        "PROCESS_GROUP_UNCONFIRMED",
                        finished_at_utc=_utc_now(),
                        return_code=return_code,
                        requires_confirmation=True,
                    )
                    receipt_unavailable = (
                        receipt is None
                        and not self._has_legal_terminal_receipt(job)
                    )
                with self._lock:
                    self._restart_confirmation_required = True
                    if receipt_unavailable:
                        self._state_unavailable.add(job.campaign_id)
                return
            finished = _utc_now()
            search_completion: Optional[Dict[str, Any]] = None
            if job.shutdown_requested:
                status_value = "INTERRUPTED"
                message = "服务关闭，受控进程组已确认终止；未自动恢复或重跑"
                event_type = "INTERRUPTED"
            elif job.timed_out:
                status_value = "TIMED_OUT"
                message = "任务超过启动时冻结的超时上限"
                event_type = "TIMED_OUT"
            elif job.cancel_requested:
                status_value = "CANCELLED"
                message = "任务已由页面请求取消"
                event_type = "CANCELLED"
            elif job.output_limit_exceeded:
                status_value = "FAILED"
                message = "Codex 私有输出超过固定上限；未读取、展示或入库"
                event_type = "FAILED"
            elif job.prepared_search_round is not None:
                status_value = "FAILED"
                message = "Search 执行输出正在按冻结合同闭合"
                event_type = "SEARCH_FINALIZING"
            elif job.action == "CODEX_GENERATION" and return_code == 0:
                try:
                    status_value, message, event_type = (
                        self._finalize_codex_generation(job, campaign_dir, finished)
                    )
                except GenerationContractError as exc:
                    persisted = self._persist_generation_failure(
                        job.campaign_id,
                        error_code=(
                            "DUPLICATE_CODE_SHA256"
                            if exc.code == "duplicate_candidate"
                            else exc.code.upper()
                        ),
                        error_message=exc.message,
                        finished_at=finished,
                        details=(
                            {"existing_candidate_id": exc.existing_candidate_id}
                            if exc.existing_candidate_id is not None
                            else None
                        ),
                    )
                    if not persisted:
                        raise
                    status_value = "FAILED"
                    message = (
                        "生成源码与既有 Candidate 重复；未覆盖，既有 Candidate 标识可在规范化状态中查看"
                        if exc.code == "duplicate_candidate"
                        else "Codex 生成输出未通过固定合同；私有日志不会显示在页面"
                    )
                    event_type = "FAILED"
            elif job.action == "DEVELOPMENT" and return_code == 0:
                try:
                    finalized = finalize_development_gate(
                        self.config.database_path, job.campaign_id
                    )
                    status_value = "SUCCEEDED"
                    message = (
                        "DEVELOPMENT Gate 通过；ResearchRun 以 PENDING 等待未来 Holdout 授权"
                        if finalized["status"] == "PENDING"
                        else "DEVELOPMENT Gate 未通过；ResearchRun 已 REJECTED"
                    )
                    event_type = "SUCCEEDED"
                except DevelopmentRunError:
                    status_value = "FAILED"
                    message = "DEVELOPMENT 结果无法按固定 Gate 完成"
                    event_type = "FAILED"
            elif job.action == "HOLDOUT_CONTINUATION" and return_code == 0:
                try:
                    finalized = finalize_holdout_continuation(
                        self.config.database_path,
                        campaign_dir,
                        job.campaign_id,
                    )
                    if finalized.get("status") != "COMPLETED":
                        raise HoldoutRunError(
                            "run_state_conflict",
                            "Holdout continuation did not reach COMPLETED",
                        )
                    status_value = "SUCCEEDED"
                    message = (
                        "同一 ResearchRun 的 DEVELOPMENT、HOLDOUT、"
                        "HOLDOUT_STRESS 已原子完成；verdict 仍为未评审"
                    )
                    event_type = "SUCCEEDED"
                    if not self._copy_frequi_best_effort(job.campaign_id):
                        message += "；可选 FreqUI copy 不可用，数据库终态不回滚"
                except HoldoutRunError:
                    status_value = "FAILED"
                    message = "Holdout/Stress 无法按同一 ResearchRun 原子完成"
                    event_type = "FAILED"
            elif job.action == "CHECK_DATA" and return_code == 0 and self._has_data_ready_output(campaign_dir):
                status_value = "SUCCEEDED"
                message = "CHECK_DATA 已完成；此状态不代表策略有效或盈利"
                event_type = "SUCCEEDED"
            else:
                status_value = "FAILED"
                message = (
                    f"{job.action} 输出合同无效；原始输出仅保存在 Git 外运行目录"
                    if return_code == 0
                    else f"{job.action} 执行失败；原始输出仅保存在 Git 外运行目录"
                )
                event_type = "FAILED"
            if (
                job.prepared_search_round is not None
                and search_completion is None
            ):
                failure_code = {
                    "INTERRUPTED": "SERVER_INTERRUPTED",
                    "TIMED_OUT": "TIMED_OUT",
                    "CANCELLED": "CANCELLED",
                    "FAILED": (
                        "OUTPUT_LIMIT_EXCEEDED"
                        if job.output_limit_exceeded
                        else "SEARCH_NONZERO_OR_INVALID"
                    ),
                }.get(status_value, "SEARCH_CONTROLLER_FAILED")
                accepted_return_code = (
                    int(return_code)
                    if not (
                        job.shutdown_requested
                        or job.timed_out
                        or job.cancel_requested
                        or job.output_limit_exceeded
                    )
                    and return_code in {0, 3}
                    else None
                )
                try:
                    search_completion = self._finalize_search_terminal(
                        campaign_id=job.campaign_id,
                        return_code=accepted_return_code,
                        failure_code=failure_code,
                        process_group_finalized=process_group_finalized,
                        database_digest_before=(
                            job.prepared_search_round.database_digest_before
                        ),
                    )
                    if search_completion is not None:
                        status_value = str(search_completion["status"])
                        if status_value == "FAILED":
                            message = "Search 已失败关闭；未自动重跑或打开后续阶段"
                            event_type = "SEARCH_FAILED_CLOSED"
                        else:
                            message = str(
                                search_completion.get("message")
                                or "Search round 已按固定 receipt 完成"
                            )
                            event_type = "SEARCH_COMPLETED"
                except SearchCampaignError:
                    with self._lock:
                        self._state_unavailable.add(job.campaign_id)
                        self._restart_confirmation_required = True
            if job.action == "DEVELOPMENT" and status_value != "SUCCEEDED":
                development_terminal = (
                    "INTERRUPTED"
                    if status_value == "INTERRUPTED"
                    else "CANCELLED"
                    if status_value == "CANCELLED"
                    else "TIMED_OUT"
                    if status_value == "TIMED_OUT"
                    else "FAILED"
                )
                failure_code = {
                    "INTERRUPTED": "SERVER_INTERRUPTED",
                    "CANCELLED": "CANCELLED",
                    "TIMED_OUT": "TIMED_OUT",
                    "FAILED": "DEVELOPMENT_NONZERO_OR_INVALID",
                }[development_terminal]
                try:
                    authoritative = fail_development_run(
                        self.config.database_path,
                        job.campaign_id,
                        development_terminal,
                        failure_code,
                    )
                    if authoritative["status"] in {"PENDING", "COMPLETED"}:
                        status_value = "SUCCEEDED"
                        event_type = "SUCCEEDED"
                        message = (
                            "取消/终止与已导入结果并发；以数据库 Development Gate 终态为准"
                        )
                except DevelopmentRunError:
                    with self._lock:
                        self._state_unavailable.add(job.campaign_id)
                        self._restart_confirmation_required = True
            if (
                job.action == "HOLDOUT_CONTINUATION"
                and status_value != "SUCCEEDED"
            ):
                holdout_terminal = (
                    "INTERRUPTED"
                    if status_value == "INTERRUPTED"
                    else "CANCELLED"
                    if status_value == "CANCELLED"
                    else "TIMED_OUT"
                    if status_value == "TIMED_OUT"
                    else "FAILED"
                )
                failure_code = {
                    "INTERRUPTED": "SERVER_INTERRUPTED",
                    "CANCELLED": "CANCELLED",
                    "TIMED_OUT": "TIMED_OUT",
                    "FAILED": "HOLDOUT_NONZERO_OR_INVALID",
                }[holdout_terminal]
                try:
                    authoritative = fail_holdout_continuation(
                        self.config.database_path,
                        campaign_dir,
                        job.campaign_id,
                        holdout_terminal,
                        failure_code,
                    )
                    if authoritative.get("status") == "COMPLETED":
                        status_value = "SUCCEEDED"
                        event_type = "SUCCEEDED"
                        message = (
                            "取消/终止与原子提交并发；以数据库三场景 COMPLETED 终态为准"
                        )
                        if not self._copy_frequi_best_effort(job.campaign_id):
                            message += "；可选 FreqUI copy 不可用"
                except HoldoutRunError:
                    with self._lock:
                        self._state_unavailable.add(job.campaign_id)
                        self._restart_confirmation_required = True
            if job.action == "CODEX_GENERATION" and status_value != "SUCCEEDED":
                reason_codes = {
                    "INTERRUPTED": "SERVER_INTERRUPTED",
                    "TIMED_OUT": "TIMED_OUT",
                    "CANCELLED": "CANCELLED",
                    "FAILED": (
                        "OUTPUT_LIMIT_EXCEEDED"
                        if job.output_limit_exceeded
                        else "CODEX_NONZERO" if return_code else "OUTPUT_INVALID"
                    ),
                }
                persisted = self._persist_generation_failure(
                    job.campaign_id,
                    error_code=reason_codes.get(status_value, "GENERATION_FAILED"),
                    error_message=message,
                    finished_at=finished,
                )
                if not persisted:
                    raise GenerationContractError(
                        "generation_state_conflict",
                        "Generation terminal state could not be persisted",
                    )
            with job.receipt_lock:
                receipt = search_completion
                if receipt is None:
                    receipt = self._record_job_transition(
                        job,
                        campaign_dir,
                        status_value,
                        message,
                        event_type,
                        finished_at_utc=finished,
                        return_code=return_code,
                        requires_confirmation=False,
                    )
                receipt_unavailable = (
                    receipt is None
                    and not self._has_legal_terminal_receipt(job)
                )
            if receipt_unavailable:
                with self._lock:
                    self._state_unavailable.add(job.campaign_id)
                    if job.prepared_search_round is None:
                        self._restart_confirmation_required = True
        except Exception:
            process_group_finalized = self._terminate_owned_job(job)
            if job.prepared_search_round is not None:
                try:
                    self._finalize_search_terminal(
                        campaign_id=job.campaign_id,
                        failure_code="CONTROLLER_FAILED",
                        process_group_finalized=process_group_finalized,
                    )
                except SearchCampaignError:
                    with self._lock:
                        self._state_unavailable.add(job.campaign_id)
                        self._restart_confirmation_required = True
            elif job.action == "CODEX_GENERATION":
                self._persist_generation_failure(
                    job.campaign_id,
                    error_code="CONTROLLER_FAILED",
                    error_message="Generation controller failed",
                    finished_at=_utc_now(),
                )
            elif job.action == "DEVELOPMENT" and process_group_finalized:
                try:
                    fail_development_run(
                        self.config.database_path,
                        job.campaign_id,
                        "INTERRUPTED",
                        "CONTROLLER_FAILED",
                    )
                except DevelopmentRunError:
                    pass
            elif job.action == "HOLDOUT_CONTINUATION" and process_group_finalized:
                try:
                    fail_holdout_continuation(
                        self.config.database_path,
                        campaign_dir,
                        job.campaign_id,
                        "INTERRUPTED",
                        "CONTROLLER_FAILED",
                    )
                except HoldoutRunError:
                    pass
            if campaign_dir is not None and job.prepared_search_round is None:
                with job.receipt_lock:
                    receipt = self._record_job_transition(
                        job,
                        campaign_dir,
                        "INTERRUPTED_NEEDS_CONFIRMATION",
                        "控制器内部故障；任务终态需要人工确认",
                        "CONTROLLER_FAILED",
                        finished_at_utc=_utc_now(),
                        return_code=self._leader_return_code(job),
                        requires_confirmation=True,
                    )
                    receipt_unavailable = (
                        receipt is None
                        and not self._has_legal_terminal_receipt(job)
                    )
                if receipt_unavailable:
                    with self._lock:
                        self._state_unavailable.add(job.campaign_id)
            with self._lock:
                if job.prepared_search_round is None or not process_group_finalized:
                    self._restart_confirmation_required = True
        finally:
            if (
                not process_group_finalized
                and self._leader_return_code(job) is None
            ):
                process_group_finalized = self._terminate_owned_job(job)
            with self._lock:
                if not process_group_finalized:
                    self._restart_confirmation_required = True
                if self._active is job:
                    self._active = None

    def _read_public_campaign_status(self, campaign_id: str) -> Dict[str, Any]:
        self._campaign_directory(campaign_id, must_exist=True)
        status_value = self._read_campaign_json(campaign_id, "status.json")
        if (
            status_value.get("schema") != STATUS_SCHEMA
            or status_value.get("campaign_id") != campaign_id
        ):
            raise ControlRequestError(
                409, "campaign_state_unavailable", "Campaign 状态无法安全读取"
            )
        if (
            self._search_mode_configured
            and status_value.get("action") == "HOLDOUT_CONTINUATION"
        ):
            raise ControlRequestError(
                404,
                "SEALED_UNREAD",
                EXPLICIT_SEARCH_SEALED_REASON,
            )
        return _public_status(status_value)

    def get_status(self, campaign_id: str) -> Dict[str, Any]:
        with self._lock:
            if campaign_id in self._state_unavailable:
                raise ControlRequestError(
                    409,
                    "campaign_state_unavailable",
                    "Campaign 终态收据无法安全确认",
                )
            job = self._active
            if job is None or job.campaign_id != campaign_id:
                job = None
        if job is None:
            return self._read_public_campaign_status(campaign_id)
        with job.receipt_lock:
            if campaign_id in self._state_unavailable:
                raise ControlRequestError(
                    409,
                    "campaign_state_unavailable",
                    "Campaign 终态收据无法安全确认",
                )
            return self._read_public_campaign_status(campaign_id)

    @staticmethod
    def _search_error(exc: SearchCampaignError) -> ControlRequestError:
        return ControlRequestError(exc.status, exc.code, exc.message)

    def search_context(self) -> Dict[str, Any]:
        capability = self._search_capability
        assert capability is not None
        with self._lock:
            active = (
                self._active is not None
                and self._active.prepared_search_round is not None
            )
        try:
            context = load_search_context(
                self.config.database_path, capability, active=active
            )
        except SearchCampaignError as exc:
            raise self._search_error(exc) from exc
        campaign_id = context.get("state", {}).get("campaign_id")
        with self._lock:
            if campaign_id in self._state_unavailable:
                raise ControlRequestError(409, "search_state_unavailable", "Search 终态无法安全确认")
        return context

    def get_search_campaign(self, campaign_id: str) -> Dict[str, Any]:
        capability = self._search_capability
        assert capability is not None
        with self._lock:
            active = (
                self._active is not None
                and self._active.prepared_search_round is not None
                and self._active.campaign_id == campaign_id
            )
        try:
            state = load_public_search_state(capability, active=active)
        except SearchCampaignError as exc:
            raise self._search_error(exc) from exc
        if state.get("campaign_id") != campaign_id:
            raise ControlRequestError(
                404, "search_campaign_not_found", "Search campaign 不存在"
            )
        with self._lock:
            if campaign_id in self._state_unavailable:
                raise ControlRequestError(409, "search_state_unavailable", "Search 终态无法安全确认")
        return state

    def _start_prepared_search(
        self, prepared: PreparedSearchRound
    ) -> Dict[str, Any]:
        capability = self._search_capability
        assert capability is not None
        stdout_handle: Optional[BinaryIO] = None
        stderr_handle: Optional[BinaryIO] = None
        process: Optional[subprocess.Popen[bytes]] = None
        job: Optional[_ActiveJob] = None
        try:
            stdout_handle = capability.open_private_output(
                f"round-{prepared.round_number}.stdout.log"
            )
            stderr_handle = capability.open_private_output(
                f"round-{prepared.round_number}.stderr.log"
            )
            process = subprocess.Popen(
                prepared.argv,
                cwd=str(PROJECT_ROOT),
                stdin=subprocess.DEVNULL,
                stdout=stdout_handle,
                stderr=stderr_handle,
                env=_minimal_environment(),
                shell=False,
                start_new_session=True,
                close_fds=True,
                umask=0o077,
            )
            job = _ActiveJob(
                campaign_id=prepared.campaign_id,
                action="SEARCH",
                process=process,
                process_group_id=process.pid,
                deadline=time.monotonic() + self.config.task_timeout_seconds,
                prepared_search_round=prepared,
            )
            self._active = job
            running_state = load_public_search_state(capability, active=True)
            monitor = threading.Thread(
                target=self._monitor_job,
                args=(job,),
                name=f"research-console-search-{prepared.campaign_id[:8]}",
                daemon=True,
            )
            job.monitor = monitor
            monitor.start()
            return running_state
        except (SearchCampaignError, OSError, RuntimeError) as exc:
            error_code = (
                "START_RECEIPT_FAILED"
                if isinstance(exc, SearchCampaignError)
                else "START_FAILED"
            )
            terminated = True if job is None else self._terminate_owned_job(job)
            if job is not None and self._active is job:
                self._active = None
            if terminated:
                try:
                    self._finalize_search_terminal(
                        campaign_id=prepared.campaign_id,
                        failure_code=error_code,
                        process_group_finalized=True,
                    )
                except SearchCampaignError:
                    self._state_unavailable.add(prepared.campaign_id)
                    self._restart_confirmation_required = True
            else:
                self._finalize_search_terminal(
                    campaign_id=prepared.campaign_id,
                    failure_code=error_code,
                    process_group_finalized=False,
                )
            if isinstance(exc, SearchCampaignError):
                raise
            raise ControlRequestError(
                500, "start_failed", "Search 无法安全启动"
            ) from exc
        finally:
            if stdout_handle is not None and not stdout_handle.closed:
                stdout_handle.close()
            if stderr_handle is not None and not stderr_handle.closed:
                stderr_handle.close()

    def _search_start_capability(self) -> FrozenSearchCapability:
        if self._closed or self._shutting_down:
            raise ControlRequestError(
                409, "console_shutting_down", "Research Console 正在关闭"
            )
        if self._restart_confirmation_required:
            raise ControlRequestError(
                409,
                "restart_confirmation_required",
                "检测到未闭合进程组；请人工确认后换用新的运行目录",
            )
        if self._active is not None:
            raise ControlRequestError(
                409, "active_campaign", "已有一个受控任务正在运行"
            )
        assert self._search_capability is not None
        return self._search_capability

    def create_search_campaign(
        self, candidate_ids: Sequence[str], profile_id: str
    ) -> Dict[str, Any]:
        with self._lock:
            capability = self._search_start_capability()
            try:
                prepared = prepare_round_one(
                    self.config.database_path,
                    capability,
                    candidate_ids,
                    profile_id=profile_id,
                )
                return self._start_prepared_search(prepared)
            except SearchCampaignError as exc:
                raise self._search_error(exc) from exc

    def start_search_round_two(
        self,
        campaign_id: str,
        candidates: Sequence[Mapping[str, Any]],
    ) -> Dict[str, Any]:
        with self._lock:
            capability = self._search_start_capability()
            try:
                prepared = prepare_round_two(
                    self.config.database_path,
                    capability,
                    campaign_id,
                    candidates,
                )
                return self._start_prepared_search(prepared)
            except SearchCampaignError as exc:
                raise self._search_error(exc) from exc

    def cancel_search_campaign(self, campaign_id: str) -> Dict[str, Any]:
        with self._lock:
            job = self._active
            if (
                job is None
                or job.campaign_id != campaign_id
                or job.prepared_search_round is None
            ):
                current = self.get_search_campaign(campaign_id)
                if current.get("status") in {
                    "SEARCH_FINALIST_FROZEN",
                    "SEARCH_TERMINATED_NO_PARENT",
                    "SEARCH_TERMINATED_NO_FINALIST",
                    "CANCELLED",
                    "FAILED",
                    "INTERRUPTED",
                }:
                    return current
                raise ControlRequestError(
                    409, "search_campaign_not_active", "Search 当前没有运行任务"
                )
            if self._leader_return_code(job) is not None:
                raise ControlRequestError(
                    409,
                    "process_group_unconfirmed",
                    "Search leader 已结束；请轮询 receipt 终态",
                )
            if not self._begin_cancel_locked(job):
                return self.get_search_campaign(campaign_id)
        try:
            return self.get_search_campaign(campaign_id)
        finally:
            job.receipt_lock.release()

    @staticmethod
    def _development_error(exc: DevelopmentRunError) -> ControlRequestError:
        status = 503 if exc.code == "BLOCKED_DATA" else 409
        return ControlRequestError(status, exc.code, exc.message)

    @staticmethod
    def _holdout_error(exc: HoldoutRunError) -> ControlRequestError:
        status = getattr(exc, "status", None)
        if not isinstance(status, int):
            status = (
                404
                if exc.code == "run_not_found"
                else 503
                if exc.code == "BLOCKED_DATA"
                else 409
            )
        return ControlRequestError(status, exc.code, exc.message)

    def _public_holdout_capability(self) -> Dict[str, Any]:
        if not self._search_mode_configured:
            return self._holdout_capability.public()
        return {
            "status": "SEALED_UNREAD",
            "reason": EXPLICIT_SEARCH_SEALED_REASON,
            "pipeline_version": DEVELOPMENT_PIPELINE_VERSION,
            "action": None,
            "holdout": "SEALED_UNREAD",
            "holdout_stress": "SEALED_UNREAD",
            "holdout_timerange": None,
            "stress_fee_multiplier": None,
            "one_shot": True,
        }

    def _decorate_research_run(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Combine DB eligibility with the controller's one live process slot."""
        if self._search_mode_configured:
            pick = lambda source, fields: {key: source[key] for key in fields if key in source}
            execution_fields = ("scenario", "sequence", "status", "scenario_opened",
                                "total_trades", "profit_pct", "total_profit_pct",
                                "max_drawdown_pct", "win_rate", "profit_factor",
                                "artifact_sha256", "net_profit_after_base_fees_pct",
                                "average_holding_period_minutes", "roi_exit_count",
                                "scenario_passed", "started_at", "finished_at")
            executions = payload.get("executions", [])
            development_execution = next((item for item in executions
                                          if isinstance(item, dict)
                                          and item.get("scenario") == "DEVELOPMENT"), None)
            development = payload.get("development")
            development = development if isinstance(development, dict) else development_execution or {}
            development_public = pick(development, execution_fields[1:])
            development_public["execution_rows"] = 1 if development else 0
            result = pick(payload, ("research_run_id", "candidate_id", "research_profile_id",
                                    "trigger_type", "pipeline_version", "freqtrade_version",
                                    "created_at", "started_at", "finished_at"))
            result.update(
                status=payload.get("status"),
                stage=payload.get("stage"),
                verdict=payload.get("verdict"),
                checks=pick(payload.get("checks", {}), (
                    "candidate_binding", "security_gate", "development_data",
                    "development_gate", "next_phase", "holdout", "holdout_stress",
                )),
                gate_results=[
                    pick(item, ("criterion", "threshold", "actual", "passed"))
                    for item in payload.get("gate_results", [])
                    if isinstance(item, dict)
                ],
                rejection_reasons=list(payload.get("rejection_reasons", [])),
                error_stage=payload.get("error_stage"),
                error_message=payload.get("error_message"),
                development=development_public,
                holdout={"status": "SEALED_UNREAD", "execution_rows": 0},
                holdout_stress={"status": "SEALED_UNREAD", "execution_rows": 0},
                authorization={"status": "SEALED_UNREAD", "can_authorize": False,
                               "reason": "Explicit Search mode keeps Holdout and Holdout Stress sealed"},
                boundaries=dict.fromkeys(("holdout", "holdout_stress", "judge", "release"),
                                          "SEALED_UNREAD"),
            )
            result["executions"] = [
                {
                    "scenario": "DEVELOPMENT",
                    **pick(development_public, execution_fields[1:]),
                }
            ] if development else []
            return result
        authorization = payload.get("authorization")
        normalized = dict(authorization) if isinstance(authorization, dict) else {}
        database_allows = normalized.get("can_authorize") is True
        run_id = payload.get("research_run_id")
        campaign_available = False
        if isinstance(run_id, str):
            try:
                self._campaign_directory(run_id, must_exist=True)
                campaign_available = True
            except ControlRequestError:
                pass
        with self._lock:
            capability_ready = self._holdout_capability.status == "READY"
            slot_available = self._active is None
            restart_clear = not self._restart_confirmation_required
            controller_allows = (
                capability_ready
                and slot_available
                and restart_clear
                and not self._closed
                and not self._shutting_down
                and self._runtime_paths_unchanged()
                and campaign_available
            )
        normalized["can_authorize"] = database_allows and controller_allows
        if database_allows and not controller_allows:
            if not capability_ready:
                normalized["reason"] = self._holdout_capability.reason
            elif not restart_clear:
                normalized["reason"] = "存在需要人工确认的重启中断任务"
            elif not slot_available:
                normalized["reason"] = "唯一受控任务槽当前被占用"
            elif not campaign_available:
                normalized["reason"] = "ResearchRun 不属于当前冻结的运行目录"
            else:
                normalized["reason"] = "Research Console 当前不可授权"
        result = dict(payload)
        result["authorization"] = normalized
        release_root = self._release_root
        executions = payload.get("executions")
        review_candidate = (
            payload.get("status") == "COMPLETED"
            and isinstance(executions, list)
            and len(executions) == 3
        )
        if not review_candidate:
            result["manual_review"] = {
                "status": "UNAVAILABLE",
                "can_reject": False,
                "can_pass_and_create_release": False,
                "reason": "ResearchRun 尚未形成同一 Run 的三场景人工评审资格",
                "release": None,
            }
        elif release_root is None:
            result["manual_review"] = {
                "status": "UNKNOWN",
                "can_reject": False,
                "can_pass_and_create_release": False,
                "reason": "Release root is unavailable",
                "release": None,
            }
        else:
            result["manual_review"] = inspect_manual_review(
                self.config.database_path,
                release_root,
                str(payload.get("research_run_id")),
            )
        return result

    def _copy_frequi_best_effort(self, research_run_id: str) -> bool:
        """Keep optional disposable FreqUI publication outside DB success."""
        try:
            result = copy_frequi_results(
                self.config.database_path,
                research_run_id,
                self._artifact_root,
                self._frequi_config,
            )
            return result.get("status") == "COPIED"
        except Exception:
            return False

    def research_context(self) -> Dict[str, Any]:
        payload = research_context(
            self.config.database_path, self._development_capability
        )
        holdout_capability = self._public_holdout_capability()
        if self._search_mode_configured:
            payload["boundaries"] = {
                "holdout": "SEALED_UNREAD",
                "holdout_stress": "SEALED_UNREAD",
                "judge": "SEALED_UNREAD",
                "release": "SEALED_UNREAD",
            }
        payload["holdout_capability"] = holdout_capability
        return payload

    def _require_later_phases_open(self) -> None:
        if self._search_mode_configured:
            raise ControlRequestError(
                409,
                "SEALED_UNREAD",
                "Explicit Search mode keeps Holdout, Stress, Judge, and Release sealed",
            )

    def get_research_run(self, research_run_id: str) -> Dict[str, Any]:
        try:
            loader = (
                load_public_development_run
                if self._search_mode_configured
                else load_public_holdout_run
            )
            return self._decorate_research_run(
                loader(self.config.database_path, research_run_id)
            )
        except (DevelopmentRunError, HoldoutRunError) as exc:
            raise self._holdout_error(exc) from exc

    def create_research_run(self, candidate_id: str) -> Dict[str, Any]:
        """Consume one approved Candidate and start one Development child."""
        with self._lock:
            if self._closed or self._shutting_down:
                raise ControlRequestError(
                    409, "console_shutting_down", "Research Console 正在关闭"
                )
            if self._restart_confirmation_required:
                raise ControlRequestError(
                    409,
                    "restart_confirmation_required",
                    "检测到崩溃前未闭合任务；请人工确认后换用新的运行目录",
                )
            if self._active is not None:
                raise ControlRequestError(
                    409, "active_campaign", "已有一个受控任务正在运行"
                )
            if not self._runtime_paths_unchanged():
                raise ControlRequestError(
                    409, "frozen_path_changed", "启动时冻结的运行目录身份已变化"
                )
            if not isinstance(candidate_id, str) or not candidate_id:
                raise ControlRequestError(
                    400, "invalid_candidate_id", "candidate_id 必须是非空字符串"
                )
            search_capability = self._search_capability
            search_finalist_binding: Optional[Mapping[str, Any]] = None
            if self._search_mode_configured:
                if search_capability is None:
                    raise ControlRequestError(
                        503,
                        "BLOCKED_DATA",
                        "显式 Search capability 不可用，finalist 绑定无法验证；未创建 ResearchRun，未启动 Development",
                    )
                if search_capability.status != "READY":
                    code = search_capability.status
                    raise ControlRequestError(
                        409
                        if code == "BLOCKED_INSUFFICIENT_CAPACITY"
                        else 503,
                        code,
                        search_capability.reason,
                    )
                if search_capability.profile_snapshot is None:
                    raise ControlRequestError(
                        503,
                        "BLOCKED_DATA",
                        "显式 Search Profile 绑定不可用；未创建 ResearchRun，未启动 Development",
                    )
                try:
                    search_finalist_binding = verified_finalist_binding(
                        self.config.database_path,
                        search_capability,
                        candidate_id,
                    )
                except SearchCampaignError as exc:
                    raise self._search_error(exc) from exc
                if search_finalist_binding is None:
                    raise ControlRequestError(
                        409,
                        "search_finalist_required",
                        "Candidate 不是已验证的 Profile Search finalist",
                    )
            if self._development_capability.status != "READY":
                raise ControlRequestError(
                    503, "BLOCKED_DATA", self._development_capability.reason
                )

            run_id = str(uuid4())
            campaign_dir = self._campaign_directory(run_id, must_exist=False)
            try:
                os.mkdir(run_id, 0o700, dir_fd=self._campaigns_fd)
                prepared = prepare_development_run(
                    self.config.database_path,
                    campaign_dir,
                    candidate_id,
                    self._development_capability,
                    research_run_id=run_id,
                    now=_utc_now(),
                    search_finalist_binding=search_finalist_binding,
                )
            except DevelopmentRunError as exc:
                shutil.rmtree(campaign_dir, ignore_errors=True)
                raise self._development_error(exc) from exc
            except OSError as exc:
                shutil.rmtree(campaign_dir, ignore_errors=True)
                raise ControlRequestError(
                    500, "research_run_create_failed", "ResearchRun 运行目录无法创建"
                ) from exc

            created = _utc_now()
            starting = self._status_document(
                run_id,
                "STARTING",
                action="DEVELOPMENT",
                created_at=created,
                started_at=None,
                finished_at=None,
                return_code=None,
                message="正在启动唯一 DEVELOPMENT 回测",
            )
            stdout_handle = None
            stderr_handle = None
            campaign_fd: Optional[int] = None
            try:
                campaign_fd = self._open_campaign_fd(run_id)
                _atomic_write_json_at(
                    campaign_fd,
                    "request.json",
                    {
                        "schema": REQUEST_SCHEMA,
                        "campaign_id": run_id,
                        "action": "DEVELOPMENT",
                        "created_at_utc": created,
                        "candidate_id": candidate_id,
                    },
                )
                _atomic_write_json_at(campaign_fd, "status.json", starting)
                self._append_event_at(
                    campaign_fd,
                    run_id,
                    "CREATED",
                    "STARTING",
                    "已创建唯一 DEVELOPMENT 任务；Holdout/Stress 保持 SEALED_UNREAD",
                )
                stdout_handle = _open_private_output_at(campaign_fd, "stdout.log")
                stderr_handle = _open_private_output_at(campaign_fd, "stderr.log")
            except (OSError, ControlRequestError, ValueError) as exc:
                fail_development_run(
                    self.config.database_path,
                    run_id,
                    "FAILED",
                    "OUTPUT_CREATE_FAILED",
                )
                raise ControlRequestError(
                    500, "output_create_failed", "DEVELOPMENT 私有运行文件无法创建"
                ) from exc
            finally:
                if campaign_fd is not None:
                    os.close(campaign_fd)

            try:
                argv = development_worker_argv(
                    self.config.database_path,
                    prepared,
                    self._development_capability,
                    Path(sys.executable).resolve(strict=True),
                )
                process = subprocess.Popen(
                    argv,
                    cwd=str(PROJECT_ROOT),
                    stdin=subprocess.DEVNULL,
                    stdout=stdout_handle,
                    stderr=stderr_handle,
                    env=_minimal_environment(),
                    shell=False,
                    start_new_session=True,
                    close_fds=True,
                    umask=0o077,
                )
            except OSError as exc:
                if stdout_handle is not None:
                    stdout_handle.close()
                if stderr_handle is not None:
                    stderr_handle.close()
                fail_development_run(
                    self.config.database_path, run_id, "FAILED", "START_FAILED"
                )
                self._record_transition(
                    campaign_dir,
                    "FAILED",
                    "唯一 DEVELOPMENT 无法启动",
                    "START_FAILED",
                    finished_at_utc=_utc_now(),
                    return_code=None,
                )
                raise ControlRequestError(
                    500, "start_failed", "唯一 DEVELOPMENT 无法启动"
                ) from exc

            job = _ActiveJob(
                campaign_id=run_id,
                action="DEVELOPMENT",
                process=process,
                process_group_id=process.pid,
                deadline=time.monotonic() + self.config.task_timeout_seconds,
            )
            self._active = job
            try:
                if stdout_handle is not None and not stdout_handle.closed:
                    stdout_handle.close()
                if stderr_handle is not None and not stderr_handle.closed:
                    stderr_handle.close()
                started = _utc_now()
                campaign_fd = self._open_campaign_fd(run_id)
                try:
                    _atomic_write_json_at(
                        campaign_fd,
                        "owner.json",
                        {
                            "schema": OWNER_SCHEMA,
                            "campaign_id": run_id,
                            "server_pid": os.getpid(),
                            "child_pid": process.pid,
                            "process_group_id": job.process_group_id,
                            "started_at_utc": started,
                        },
                    )
                finally:
                    os.close(campaign_fd)
                self._write_status(
                    campaign_dir,
                    "RUNNING",
                    "唯一 DEVELOPMENT 正在运行；Holdout/Stress 未打开",
                    started_at_utc=started,
                )
                self._append_event(
                    campaign_dir, "STARTED", "RUNNING", "唯一 DEVELOPMENT 已启动"
                )
                monitor = threading.Thread(
                    target=self._monitor_job,
                    args=(job,),
                    name=f"research-console-development-{run_id[:8]}",
                    daemon=True,
                )
                job.monitor = monitor
                monitor.start()
            except Exception as exc:
                terminated = self._terminate_owned_job(job)
                if terminated:
                    try:
                        fail_development_run(
                            self.config.database_path,
                            run_id,
                            "FAILED",
                            "START_RECEIPT_FAILED",
                        )
                    except DevelopmentRunError:
                        terminated = False
                receipt = self._record_transition(
                    campaign_dir,
                    "FAILED" if terminated else "INTERRUPTED_NEEDS_CONFIRMATION",
                    (
                        "DEVELOPMENT 启动收据失败，受控进程已终止"
                        if terminated
                        else "DEVELOPMENT 启动收据失败，无法确认进程终态"
                    ),
                    "START_RECEIPT_FAILED",
                    finished_at_utc=_utc_now(),
                    return_code=self._leader_return_code(job),
                    requires_confirmation=not terminated,
                )
                if receipt is None or not terminated:
                    self._restart_confirmation_required = True
                if self._active is job:
                    self._active = None
                raise ControlRequestError(
                    500,
                    "start_receipt_failed",
                    "唯一 DEVELOPMENT 无法安全完成启动",
                ) from exc
        return self.get_research_run(run_id)

    def authorize_holdout(self, research_run_id: str) -> Dict[str, Any]:
        """Consume the one-shot authorization and start the fixed continuation."""
        with self._lock:
            self._require_later_phases_open()
            if self._closed or self._shutting_down:
                raise ControlRequestError(
                    409, "console_shutting_down", "Research Console 正在关闭"
                )
            if self._restart_confirmation_required:
                raise ControlRequestError(
                    409,
                    "restart_confirmation_required",
                    "检测到崩溃前未闭合任务；Holdout 不会自动重试",
                )
            if self._active is not None:
                raise ControlRequestError(
                    409, "active_campaign", "已有一个受控任务正在运行"
                )
            if not self._runtime_paths_unchanged():
                raise ControlRequestError(
                    409, "frozen_path_changed", "启动时冻结的运行目录身份已变化"
                )
            if self._holdout_capability.status != "READY":
                raise ControlRequestError(
                    503, "BLOCKED_DATA", self._holdout_capability.reason
                )
            campaign_dir = self._campaign_directory(
                research_run_id, must_exist=True
            )
            try:
                prepared = prepare_holdout_continuation(
                    self.config.database_path,
                    campaign_dir,
                    research_run_id,
                    self._holdout_capability,
                    now=_utc_now(),
                )
            except HoldoutRunError as exc:
                raise self._holdout_error(exc) from exc

            created = _utc_now()
            starting = self._status_document(
                research_run_id,
                "STARTING",
                action="HOLDOUT_CONTINUATION",
                created_at=created,
                started_at=None,
                finished_at=None,
                return_code=None,
                message="正在启动一次性 HOLDOUT / HOLDOUT_STRESS continuation",
            )
            stdout_handle: Optional[BinaryIO] = None
            stderr_handle: Optional[BinaryIO] = None
            campaign_fd: Optional[int] = None
            try:
                campaign_fd = self._open_campaign_fd(research_run_id)
                request_body = (
                    json.dumps(
                        {
                            "schema": REQUEST_SCHEMA,
                            "campaign_id": research_run_id,
                            "action": "AUTHORIZE_HOLDOUT",
                            "created_at_utc": created,
                        },
                        ensure_ascii=False,
                        separators=(",", ":"),
                        sort_keys=True,
                    )
                    + "\n"
                ).encode("utf-8")
                _atomic_publish_bytes_at(
                    campaign_fd, "holdout-request.json", request_body
                )
                _atomic_write_json_at(
                    campaign_fd, "holdout-status.json", starting
                )
                self._append_event_at(
                    campaign_fd,
                    research_run_id,
                    "HOLDOUT_AUTHORIZED",
                    "STARTING",
                    "一次性 Holdout 授权已消费；不会自动重试",
                )
                stdout_handle = _open_private_output_at(
                    campaign_fd, "holdout.stdout.log"
                )
                stderr_handle = _open_private_output_at(
                    campaign_fd, "holdout.stderr.log"
                )
            except (OSError, ControlRequestError, ValueError) as exc:
                if stdout_handle is not None:
                    stdout_handle.close()
                if stderr_handle is not None:
                    stderr_handle.close()
                try:
                    fail_holdout_continuation(
                        self.config.database_path,
                        campaign_dir,
                        research_run_id,
                        "FAILED",
                        "OUTPUT_CREATE_FAILED",
                    )
                except HoldoutRunError:
                    self._state_unavailable.add(research_run_id)
                    self._restart_confirmation_required = True
                raise ControlRequestError(
                    500,
                    "output_create_failed",
                    "Holdout continuation 私有运行文件无法创建",
                ) from exc
            finally:
                if campaign_fd is not None:
                    os.close(campaign_fd)

            try:
                argv = holdout_worker_argv(
                    self.config.database_path,
                    prepared,
                    self._holdout_capability,
                    Path(sys.executable).resolve(strict=True),
                )
                process = subprocess.Popen(
                    argv,
                    cwd=str(PROJECT_ROOT),
                    stdin=subprocess.DEVNULL,
                    stdout=stdout_handle,
                    stderr=stderr_handle,
                    env=_minimal_environment(),
                    shell=False,
                    start_new_session=True,
                    close_fds=True,
                    umask=0o077,
                )
            except (OSError, HoldoutRunError) as exc:
                if stdout_handle is not None:
                    stdout_handle.close()
                if stderr_handle is not None:
                    stderr_handle.close()
                try:
                    fail_holdout_continuation(
                        self.config.database_path,
                        campaign_dir,
                        research_run_id,
                        "FAILED",
                        "START_FAILED",
                    )
                except HoldoutRunError:
                    self._state_unavailable.add(research_run_id)
                    self._restart_confirmation_required = True
                self._record_transition(
                    campaign_dir,
                    "FAILED",
                    "Holdout continuation 无法启动",
                    "START_FAILED",
                    status_filename="holdout-status.json",
                    finished_at_utc=_utc_now(),
                    return_code=None,
                )
                raise ControlRequestError(
                    500, "start_failed", "Holdout continuation 无法启动"
                ) from exc

            job = _ActiveJob(
                campaign_id=research_run_id,
                action="HOLDOUT_CONTINUATION",
                process=process,
                process_group_id=process.pid,
                deadline=time.monotonic() + self.config.task_timeout_seconds,
                status_filename="holdout-status.json",
            )
            self._active = job
            try:
                if stdout_handle is not None and not stdout_handle.closed:
                    stdout_handle.close()
                if stderr_handle is not None and not stderr_handle.closed:
                    stderr_handle.close()
                started = _utc_now()
                campaign_fd = self._open_campaign_fd(research_run_id)
                try:
                    _atomic_write_json_at(
                        campaign_fd,
                        "holdout-owner.json",
                        {
                            "schema": OWNER_SCHEMA,
                            "campaign_id": research_run_id,
                            "action": "HOLDOUT_CONTINUATION",
                            "server_pid": os.getpid(),
                            "child_pid": process.pid,
                            "process_group_id": job.process_group_id,
                            "started_at_utc": started,
                        },
                    )
                finally:
                    os.close(campaign_fd)
                self._write_status(
                    campaign_dir,
                    "RUNNING",
                    "正在依次运行 HOLDOUT 与 HOLDOUT_STRESS；Development 不会重跑",
                    status_filename="holdout-status.json",
                    started_at_utc=started,
                )
                self._append_event(
                    campaign_dir,
                    "STARTED",
                    "RUNNING",
                    "Holdout continuation 已启动",
                )
                monitor = threading.Thread(
                    target=self._monitor_job,
                    args=(job,),
                    name=f"research-console-holdout-{research_run_id[:8]}",
                    daemon=True,
                )
                job.monitor = monitor
                monitor.start()
            except Exception as exc:
                terminated = self._terminate_owned_job(job)
                if terminated:
                    try:
                        fail_holdout_continuation(
                            self.config.database_path,
                            campaign_dir,
                            research_run_id,
                            "FAILED",
                            "START_RECEIPT_FAILED",
                        )
                    except HoldoutRunError:
                        terminated = False
                receipt = self._record_transition(
                    campaign_dir,
                    "FAILED" if terminated else "INTERRUPTED_NEEDS_CONFIRMATION",
                    (
                        "Holdout 启动收据失败，受控进程已终止"
                        if terminated
                        else "Holdout 启动收据失败，无法确认进程终态"
                    ),
                    "START_RECEIPT_FAILED",
                    status_filename="holdout-status.json",
                    finished_at_utc=_utc_now(),
                    return_code=self._leader_return_code(job),
                    requires_confirmation=not terminated,
                )
                if receipt is None or not terminated:
                    self._restart_confirmation_required = True
                if self._active is job:
                    self._active = None
                raise ControlRequestError(
                    500,
                    "start_receipt_failed",
                    "Holdout continuation 无法安全完成启动",
                ) from exc
        return self.get_research_run(research_run_id)

    def review_research_run(
        self, research_run_id: str, action: str, reason: str
    ) -> Dict[str, Any]:
        """Apply one exact human terminal action; never execute the handoff."""
        with self._lock:
            self._require_later_phases_open()
            if self._closed or self._shutting_down:
                raise ControlRequestError(
                    409, "console_shutting_down", "Research Console 正在关闭"
                )
            release_root = self._release_root
            if release_root is None:
                raise ControlRequestError(
                    503, "release_root_unavailable", "Release root 不可用"
                )
            try:
                if action == "REJECT":
                    reject_research_run(
                        self.config.database_path,
                        release_root,
                        research_run_id,
                        reason,
                        now=_utc_now(),
                    )
                elif action == "PASS_AND_CREATE_RELEASE":
                    pass_and_create_release(
                        self.config.database_path,
                        release_root,
                        research_run_id,
                        reason,
                        now=_utc_now(),
                    )
                else:
                    raise ControlRequestError(
                        400, "invalid_action", "人工终态 action 无效"
                    )
            except ManualReleaseError as exc:
                raise ControlRequestError(
                    exc.status, exc.code, exc.message
                ) from exc
        return self.get_research_run(research_run_id)

    def cancel_research_run(self, research_run_id: str) -> Dict[str, Any]:
        with self._lock:
            job = self._active
            if (
                job is not None
                and job.campaign_id == research_run_id
                and job.action in {"DEVELOPMENT", "HOLDOUT_CONTINUATION"}
            ):
                self.cancel_campaign(
                    research_run_id, expected_action=job.action
                )
                return self.get_research_run(research_run_id)
        current = self.get_research_run(research_run_id)
        if current["status"] in {
            "PENDING",
            "COMPLETED",
            "REJECTED",
            "FAILED",
            "INTERRUPTED",
            "CANCELLED",
            "TIMED_OUT",
        }:
            return current
        raise ControlRequestError(
            409, "research_run_not_active", "ResearchRun 不由当前服务持有"
        )

    def generation_context(self) -> Dict[str, Any]:
        try:
            return load_generation_context(self.config.database_path)
        except GenerationContractError as exc:
            raise ControlRequestError(exc.status, exc.code, exc.message) from exc

    def get_generation(self, generation_id: str) -> Dict[str, Any]:
        try:
            payload = load_generation(self.config.database_path, generation_id)
        except GenerationContractError as exc:
            raise ControlRequestError(exc.status, exc.code, exc.message) from exc
        try:
            runtime = self.get_status(generation_id)
        except ControlRequestError:
            runtime = None
        if runtime is not None and runtime.get("action") != "CODEX_GENERATION":
            raise ControlRequestError(
                404, "generation_not_found", "Generation 不存在"
            )
        payload["runtime_status"] = (
            None if runtime is None else runtime.get("status")
        )
        payload["message"] = None if runtime is None else runtime.get("message")
        candidate = payload.get("candidate")
        review_status = (
            candidate.get("review_status") if isinstance(candidate, dict) else None
        )
        if payload["runtime_status"] == "SUCCEEDED" and review_status == "APPROVED":
            payload["message"] = (
                "Candidate 已人工批准进入后续研究；仍未证明安全、有效、盈利或可交易"
            )
        elif payload["runtime_status"] == "SUCCEEDED" and review_status == "REJECTED":
            payload["message"] = "Candidate 已人工拒绝；GenerationRun 仍保持真实完成状态"
        return payload

    def cancel_generation(self, generation_id: str) -> Dict[str, Any]:
        with self._lock:
            job = self._active
            if job is not None and job.campaign_id == generation_id:
                if job.action != "CODEX_GENERATION":
                    raise ControlRequestError(
                        404, "generation_not_found", "Generation 不存在"
                    )
                self.cancel_campaign(
                    generation_id, expected_action="CODEX_GENERATION"
                )
                return self.get_generation(generation_id)
            current = self.get_generation(generation_id)
            if current["status"] in {"COMPLETED", "FAILED"}:
                return current
            raise ControlRequestError(
                409, "generation_not_active", "Generation 不由当前服务持有"
            )

    def review_generation(
        self, generation_id: str, decision: str
    ) -> Dict[str, Any]:
        try:
            review_candidate_generation(
                self.config.database_path,
                generation_id,
                decision,
                decided_at=_utc_now(),
            )
            return self.get_generation(generation_id)
        except GenerationContractError as exc:
            raise ControlRequestError(exc.status, exc.code, exc.message) from exc

    def get_events(self, campaign_id: str, after: int = 0) -> Dict[str, Any]:
        if self._search_mode_configured:
            status = self.get_status(campaign_id)
            if status.get("action") == "DEVELOPMENT":
                raise ControlRequestError(
                    404,
                    "SEALED_UNREAD",
                    EXPLICIT_SEARCH_SEALED_REASON,
                )
        with self._lock:
            if campaign_id in self._state_unavailable:
                raise ControlRequestError(
                    409,
                    "campaign_state_unavailable",
                    "Campaign 终态收据无法安全确认",
                )
            job = self._active
            if job is None or job.campaign_id != campaign_id:
                job = None
        if job is None:
            campaign_dir = self._campaign_directory(
                campaign_id, must_exist=True
            )
            document = self._load_events(campaign_dir)
        else:
            with job.receipt_lock:
                if campaign_id in self._state_unavailable:
                    raise ControlRequestError(
                        409,
                        "campaign_state_unavailable",
                        "Campaign 终态收据无法安全确认",
                    )
                campaign_dir = self._campaign_directory(
                    campaign_id, must_exist=True
                )
                document = self._load_events(campaign_dir)
        selected = []
        for event in document["events"]:
            if not isinstance(event, dict) or not isinstance(event.get("sequence"), int):
                raise ControlRequestError(
                    409, "campaign_state_unavailable", "Campaign 事件无法安全读取"
                )
            if event["sequence"] > after:
                selected.append(
                    {
                        key: event.get(key)
                        for key in ("sequence", "at_utc", "type", "status", "message")
                    }
                )
        next_after = after if not selected else selected[-1]["sequence"]
        return {
            "campaign_id": campaign_id,
            "events": selected,
            "next_after": next_after,
        }

    def cancel_campaign(
        self, campaign_id: str, *, expected_action: str = "CHECK_DATA"
    ) -> Dict[str, Any]:
        with self._lock:
            job = self._active
            if (
                job is None
                or job.campaign_id != campaign_id
                or job.action != expected_action
            ):
                current = self.get_status(campaign_id)
                if current.get("action") != expected_action:
                    raise ControlRequestError(
                        404, "campaign_not_found", "Campaign 不存在"
                    )
                if current["status"] in TERMINAL_STATUSES:
                    return current
                raise ControlRequestError(
                    409, "campaign_not_active", "Campaign 不由当前服务持有"
                )
            if self._leader_return_code(job) is not None:
                current = _public_status(
                    self._read_campaign_json(
                        campaign_id, job.status_filename
                    )
                )
                if current["status"] in TERMINAL_STATUSES:
                    return current
                raise ControlRequestError(
                    409,
                    "process_group_unconfirmed",
                    "leader 已回收，不能向旧 PGID 发送信号；请轮询确认状态",
                )
            campaign_dir = self._campaign_directory(
                campaign_id, must_exist=True
            )
            if not self._begin_cancel_locked(job):
                return _public_status(
                    self._read_campaign_json(
                        campaign_id, job.status_filename
                    )
                )
        try:
            current = self._record_transition(
                campaign_dir,
                "CANCEL_REQUESTED",
                "已请求取消受控进程组",
                "CANCEL_REQUESTED",
                status_filename=job.status_filename,
            )
        finally:
            job.receipt_lock.release()
        if current is None:
            raise ControlRequestError(
                500,
                "cancel_receipt_failed",
                "取消已发送，但状态收据无法安全写入",
            )
        return _public_status(current)

    def shutdown(self) -> None:
        monitor: Optional[threading.Thread] = None
        job: Optional[_ActiveJob] = None
        campaign_dir: Optional[Path] = None
        shutdown_receipt_owned = False
        with self._lock:
            if self._closed:
                return
            self._shutting_down = True
            job = self._active
            if job is not None:
                monitor = job.monitor
                if self._leader_return_code(job) is None:
                    job.shutdown_requested = True
                    if job.prepared_search_round is not None:
                        capability = self._search_capability
                        campaign_dir = (
                            None if capability is None else capability.search_root
                        )
                    else:
                        try:
                            campaign_dir = self._campaign_directory(
                                job.campaign_id, must_exist=True
                            )
                        except ControlRequestError:
                            campaign_dir = None
                    if campaign_dir is not None:
                        shutdown_receipt_owned = job.receipt_lock.acquire(
                            blocking=False
                        )
                    if self._signal_process_group(job, signal.SIGTERM):
                        if job.signal_sent_at is None:
                            job.signal_sent_at = time.monotonic()
        if shutdown_receipt_owned and campaign_dir is not None:
            try:
                self._record_job_transition(
                    job,
                    campaign_dir,
                    "INTERRUPTING",
                    "服务正在关闭受控进程组",
                    "SERVER_SHUTDOWN",
                )
            finally:
                job.receipt_lock.release()
        if monitor is not None:
            monitor.join(timeout=3.0)
        if job is not None and self._leader_return_code(job) is None:
            self._terminate_owned_job(job)
            if monitor is not None:
                monitor.join(timeout=1.0)
        with self._lock:
            if monitor is not None and monitor.is_alive():
                raise ResearchConsoleError(
                    "owned task monitor did not finalize"
                )
            if (
                job is not None
                and self._process_group_state(job) is not False
                and not self._restart_confirmation_required
            ):
                raise ResearchConsoleError(
                    "owned task process group did not finalize"
                )
            if self._active is job:
                self._active = None
            campaigns_descriptor = self._campaigns_fd
            self._campaigns_fd = -1
            descriptor = self._runtime_lock_fd
            self._runtime_lock_fd = -1
            search_capability = self._search_capability
            self._search_capability = None
            release_root = self._release_root
            self._release_root = None
            self._closed = True
        try:
            os.close(campaigns_descriptor)
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            try:
                os.close(descriptor)
            finally:
                if search_capability is not None:
                    search_capability.close()
                if release_root is not None:
                    release_root.close()


CONSOLE_HTML = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="csrf-token" content="{csrf_token}">
<title>Research Console</title>
<style>
:root{{color-scheme:light;font:14px/1.5 system-ui,sans-serif;color:#172033;background:#f6f7f9}}
body{{margin:0}}main{{max-width:1040px;margin:auto;padding:24px}}
header{{display:flex;align-items:center;justify-content:space-between;margin-bottom:18px}}
h1,h2,h3{{margin:0 0 10px}}a{{color:#3157d5}}section{{background:#fff;border:1px solid #dde2ea;border-radius:10px;padding:16px;margin:12px 0}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px}}.field{{display:flex;flex-direction:column;gap:4px}}
.wide{{grid-column:1/-1}}label,.name{{font-weight:650}}select,input,textarea{{font:inherit;border:1px solid #cbd2dd;border-radius:7px;padding:8px;background:#fff}}textarea{{min-height:86px;resize:vertical}}
.check{{border:1px solid #e6e9ef;border-radius:8px;padding:10px}}.status{{font-family:ui-monospace,monospace}}
.candidate-row{{display:grid;grid-template-columns:minmax(220px,1fr) minmax(180px,.7fr);gap:8px;align-items:center;margin:6px 0}}.candidate-row label{{font-weight:500}}
button{{border:1px solid #3157d5;border-radius:7px;background:#3157d5;color:#fff;padding:8px 12px;margin:8px 8px 0 0}}button.secondary{{background:#fff;color:#3157d5}}button.danger{{background:#fff;color:#a32929;border-color:#a32929}}button:disabled{{opacity:.45}}
pre{{white-space:pre-wrap;word-break:break-word;background:#f6f7f9;padding:10px;border-radius:7px;min-height:42px;max-height:440px;overflow:auto}}
.note{{color:#5d687a}}ul{{padding-left:20px}}
</style><script src="/console.js" defer></script></head>
<body><main><header><div><h1>Research Console</h1><div class="note">本地单进程 · 固定动作 · 无任意命令入口</div></div><a href="/">策略库</a></header>
<section><h2>Preflight</h2><div id="overall" class="status">CHECKING</div><div id="checks" class="grid"></div></section>
<section><h2>Search-only 两轮 Gate</h2><p class="note">Round 1 选择同 Profile 的 APPROVED mechanism seed（Profile 模式最多 2 个）；Round 2 只接受一个 selected-parent child。Profile 主动预算 3 次、协议硬上限 6 次，不做阈值救援或第三轮。</p>
<div class="field"><label for="search-seeds">Round 1 seeds（从下方 ResearchProfile 筛选）</label><select id="search-seeds" multiple size="5"></select></div>
<div id="search-seed-note" class="note">只能选择同 Profile、不同 mechanism 的 root Candidate</div>
<button id="search-round-1" disabled>运行 Round 1</button><button id="search-cancel" class="secondary" disabled>取消当前 Search</button>
<h3>Round 2 children 与 changed_factor</h3><div id="search-parent-lock" class="note">selected parent 由 Round 1 receipt 锁定</div><div id="search-children" class="check"><span class="note">等待 Round 1 selected parent</span></div>
<button id="search-round-2" disabled>运行 Round 2</button>
<h3>规范化 Search 状态与 finalist 绑定凭据</h3><pre id="search-status">正在读取 Search context</pre>
<div class="grid"><div class="check"><div class="name">Holdout</div><div class="status">SEALED_UNREAD</div></div><div class="check"><div class="name">Holdout Stress</div><div class="status">SEALED_UNREAD</div></div><div class="check"><div class="name">数据库副作用</div><div class="status">Search 不创建 ResearchRun / Execution / Release</div></div></div>
</section>
<section><h2>Codex 生成 Candidate</h2><p class="note">每次只生成 1 个草稿。批准仅表示允许进入后续研究，不代表安全、有效、盈利或可交易。</p>
<div class="grid">
<div class="field"><label for="profile">ResearchProfile</label><select id="profile"></select></div>
<div class="field"><label for="parent">已批准父 Candidate（可选）</label><select id="parent"><option value="">无父 Candidate</option></select></div>
<div class="field wide"><label for="idea">研究假设</label><textarea id="idea" required></textarea></div>
<div class="field"><label for="family">策略族（可选）</label><input id="family"></div>
<div class="field"><label for="failure">预期失败模式（可选）</label><input id="failure"></div>
</div>
<button id="generate">Codex 生成</button><button id="generation-cancel" class="secondary" disabled>取消生成</button><button id="approve" disabled>批准进入研究</button><button id="reject" class="danger" disabled>拒绝</button>
<h3>规范化状态</h3><pre id="generation-status">尚未生成</pre><h3>源码预览</h3><pre id="candidate-code">暂无源码</pre>
</section>
<section id="development-section"><h2>Development 研究</h2><p class="note">仅允许已批准且通过窄安全门的 Candidate。每次只运行一个真实 DEVELOPMENT；浏览器不能提交路径、参数、场景或阈值。</p>
<div class="field"><label for="research-candidate">APPROVED Candidate</label><select id="research-candidate"></select></div>
<button id="research-run" disabled>运行唯一 DEVELOPMENT</button><button id="research-cancel" class="secondary" disabled>取消</button>
<button id="research-holdout" class="danger" disabled>授权并运行 Holdout / Stress</button>
<p class="note">永久警告：授权只执行一次，不能撤销、重试或重跑 Development；完成也不代表策略盈利、安全或可交易。</p>
<div id="research-scenarios" class="grid"><div class="check"><div class="name">DEVELOPMENT</div><div class="status">暂无数据</div></div><div class="check"><div class="name">HOLDOUT</div><div class="status">SEALED_UNREAD</div></div><div class="check"><div class="name">HOLDOUT_STRESS</div><div class="status">SEALED_UNREAD</div></div></div>
<p><span class="name">Verdict：</span><span id="research-verdict">未评审</span> · <a id="research-detail" hidden>打开同一 ResearchRun 的 Strategy Library 明细</a></p>
<div class="check"><h3>人工终态</h3><div id="manual-review-status" class="note">等待同一 ResearchRun 三场景完成并复验</div>
<div class="field"><label for="manual-review-reason">人工理由（必填）</label><textarea id="manual-review-reason" maxlength="1000"></textarea></div>
<button id="manual-reject" class="danger" disabled>REJECT</button><button id="manual-pass" disabled>PASS_AND_CREATE_RELEASE</button>
<pre id="manual-release-command">尚无 dry-run 交接命令</pre>
<p class="note">只生成并展示 handoff；Lab 不执行 dry-run、不管理部署。PASSED / Release 仍不证明未来盈利、稳健、可交易或资金安全。</p></div>
<h3>规范化研究状态</h3><pre id="research-status">尚未运行</pre>
</section>
<section><h2>数据检查</h2><p class="note">只运行已冻结 Pilot 目录的 CHECK_DATA；成功不代表策略有效、盈利或可交易。</p>
<button id="run">运行 CHECK_DATA</button><button id="cancel" class="secondary" disabled>取消当前任务</button><pre id="job">尚未启动</pre></section>
<section><h2>CHECK_DATA 规范化事件</h2><ul id="events"><li>暂无事件</li></ul></section>
</main></body></html>"""


CONSOLE_JS = r"""'use strict';
const token = document.querySelector('meta[name="csrf-token"]').content;
const postHeaders = {'Content-Type':'application/json','X-CSRF-Token':token};
const runButton = document.getElementById('run');
const cancelButton = document.getElementById('cancel');
const jobBox = document.getElementById('job');
const eventList = document.getElementById('events');
const profileSelect = document.getElementById('profile');
const parentSelect = document.getElementById('parent');
const generateButton = document.getElementById('generate');
const generationCancel = document.getElementById('generation-cancel');
const approveButton = document.getElementById('approve');
const rejectButton = document.getElementById('reject');
const generationStatus = document.getElementById('generation-status');
const candidateCode = document.getElementById('candidate-code');
const researchCandidate = document.getElementById('research-candidate');
const researchRunButton = document.getElementById('research-run');
const researchCancelButton = document.getElementById('research-cancel');
const researchHoldoutButton = document.getElementById('research-holdout');
const researchStatus = document.getElementById('research-status');
const researchScenarios = document.getElementById('research-scenarios');
const researchVerdict = document.getElementById('research-verdict');
const researchDetail = document.getElementById('research-detail');
const manualReviewStatus = document.getElementById('manual-review-status');
const manualReviewReason = document.getElementById('manual-review-reason');
const manualRejectButton = document.getElementById('manual-reject');
const manualPassButton = document.getElementById('manual-pass');
const manualReleaseCommand = document.getElementById('manual-release-command');
const searchSeeds = document.getElementById('search-seeds');
const searchChildren = document.getElementById('search-children');
const searchParentLock = document.getElementById('search-parent-lock');
const searchRoundOne = document.getElementById('search-round-1');
const searchRoundTwo = document.getElementById('search-round-2');
const searchCancel = document.getElementById('search-cancel');
const searchStatus = document.getElementById('search-status');
let campaignId = null;
let timer = null;
let generationId = null;
let generationTimer = null;
let generationContext = null;
let researchRunId = null;
let researchTimer = null;
let searchContext = null;
let searchTimer = null;
let searchLoadPromise = null;
function showJob(value) { jobBox.textContent = JSON.stringify(value, null, 2); }
function terminal(status) { return ['SUCCEEDED','FAILED','CANCELLED','TIMED_OUT','INTERRUPTED','INTERRUPTED_NEEDS_CONFIRMATION'].includes(status); }
function searchIsTerminal(status) { return ['SEARCH_FINALIST_FROZEN','SEARCH_TERMINATED_NO_PARENT','SEARCH_TERMINATED_NO_FINALIST','CANCELLED','FAILED','INTERRUPTED','BLOCKED_DATA'].includes(status); }
async function request(path, options = {}) {
  const response = await fetch(path, options);
  const value = await response.json();
  if (!response.ok && !(response.status === 409 && value.status === 'FAILED')) {
    const error = new Error(value.message || value.error || `HTTP ${response.status}`); error.payload = value; throw error;
  }
  return value;
}
function renderGeneration(value) {
  const safe = JSON.parse(JSON.stringify(value));
  const code = safe.candidate ? safe.candidate.code_text : null;
  if (safe.candidate) delete safe.candidate.code_text;
  generationStatus.textContent = JSON.stringify(safe, null, 2);
  candidateCode.textContent = code || '暂无源码';
  const runtimeActive = value.runtime_status !== null && !terminal(value.runtime_status);
  const running = value.status === 'RUNNING' || runtimeActive;
  const pending = value.status === 'COMPLETED' && value.runtime_status === 'SUCCEEDED' && value.candidate && value.candidate.review_status === 'PENDING';
  generationCancel.disabled = !running;
  generateButton.disabled = running;
  approveButton.disabled = !pending;
  rejectButton.disabled = !pending;
}
function refreshParents() {
  const lock = searchContext && searchContext.codex_parent_lock;
  const selected = lock ? lock.parent_candidate_id : parentSelect.value;
  if (lock && [...profileSelect.options].some(option => option.value === lock.profile_id)) profileSelect.value = lock.profile_id;
  parentSelect.replaceChildren();
  const empty = document.createElement('option'); empty.value = ''; empty.textContent = '无父 Candidate'; parentSelect.append(empty);
  if (!generationContext) return;
  generationContext.approved_parents.filter(item => item.profile_id === profileSelect.value).forEach(item => {
    const option = document.createElement('option'); option.value = item.id; option.textContent = `${item.display_name} · ${item.class_name}`; parentSelect.append(option);
  });
  if (lock && ![...parentSelect.options].some(option => option.value === selected)) {
    const option = document.createElement('option'); option.value = selected; option.textContent = `Search selected parent · ${selected}`; parentSelect.append(option);
  }
  if ([...parentSelect.options].some(option => option.value === selected)) parentSelect.value = selected;
  if (lock) document.getElementById('family').value = lock.strategy_family || '';
  profileSelect.disabled = Boolean(lock);
  parentSelect.disabled = Boolean(lock);
  document.getElementById('family').disabled = Boolean(lock);
}
async function loadGenerationContext() {
  generationContext = await request('/api/generation/context'); profileSelect.replaceChildren();
  generationContext.profiles.forEach(profile => { const option = document.createElement('option'); option.value = profile.id; option.textContent = `${profile.name} · ${profile.timeframe}`; profileSelect.append(option); });
  document.getElementById('idea').maxLength = generationContext.limits.idea_chars;
  document.getElementById('family').maxLength = generationContext.limits.strategy_family_chars;
  document.getElementById('failure').maxLength = generationContext.limits.expected_failure_mode_chars;
  refreshParents();
  if (searchContext) { renderSearchSeeds(searchContext); updateSearchControls(); }
  if (generationContext.latest_generation_id) { generationId = generationContext.latest_generation_id; await pollGeneration(); }
}
function renderResearch(value) {
  researchStatus.textContent = JSON.stringify(value, null, 2);
  const active = value && value.status === 'RUNNING';
  researchRunButton.disabled = active || ![...researchCandidate.options].some(option => option.dataset.ready === 'true');
  researchCancelButton.disabled = !active;
  researchHoldoutButton.disabled = !(value && value.authorization && value.authorization.can_authorize === true);
  researchVerdict.textContent = value && value.verdict !== null && value.verdict !== undefined ? String(value.verdict) : '未评审';
  researchDetail.hidden = !(value && typeof value.strategy_detail_url === 'string');
  if (!researchDetail.hidden) researchDetail.href = value.strategy_detail_url;
  const review = value && value.manual_review ? value.manual_review : null;
  manualReviewStatus.textContent = review ? `${review.status} · ${review.reason || '无理由'}` : '人工终态状态 UNKNOWN';
  manualReviewReason.maxLength = review && Number.isInteger(review.reason_max_chars) ? review.reason_max_chars : 1000;
  manualRejectButton.disabled = !(review && review.can_reject === true);
  manualPassButton.disabled = !(review && review.can_pass_and_create_release === true);
  const release = review && review.release;
  const handoff = release && release.dry_run_handoff;
  manualReleaseCommand.textContent = handoff && typeof handoff.command === 'string'
    ? `Release ${release.id}\nmanifest_sha256: ${release.manifest_sha256}\nstatus: ${handoff.status}\n\n${handoff.command}`
    : '尚无 dry-run 交接命令';
  researchScenarios.replaceChildren();
  const executions = value && Array.isArray(value.executions) ? value.executions : [];
  ['DEVELOPMENT','HOLDOUT','HOLDOUT_STRESS'].forEach(scenario => {
    const execution = executions.find(item => item && item.scenario === scenario);
    const box = document.createElement('div'); box.className = 'check';
    const title = document.createElement('div'); title.className = 'name'; title.textContent = scenario;
    const status = document.createElement('div'); status.className = 'status'; status.textContent = execution ? execution.status : 'SEALED_UNREAD';
    const opened = document.createElement('div'); opened.className = 'note';
    const openedValue = execution ? execution.scenario_opened : null;
    opened.textContent = `scenario_opened: ${openedValue === true ? 'OPENED' : openedValue === false ? 'NOT_OPENED' : openedValue || 'NOT_OPENED'}`;
    const metrics = document.createElement('div'); metrics.className = 'note';
    const metricKeys = ['total_trades','profit_pct','net_profit_after_base_fees_pct',
      'profit_factor','max_drawdown_pct','average_holding_period_minutes','roi_exit_count'];
    metrics.textContent = execution ? metricKeys.filter(key => execution[key] !== null && execution[key] !== undefined).map(key => `${key}: ${execution[key]}`).join(' · ') || 'metrics: UNKNOWN' : 'metrics: UNKNOWN';
    box.append(title, status, opened, metrics); researchScenarios.append(box);
  });
}
async function loadResearchContext() {
  const value = await request('/api/research/context'); researchCandidate.replaceChildren();
  value.candidates.forEach(candidate => {
    const option = document.createElement('option'); option.value = candidate.candidate_id;
    option.dataset.ready = candidate.status === 'READY' ? 'true' : 'false';
    option.disabled = candidate.status !== 'READY';
    option.textContent = `${candidate.display_name} · ${candidate.status}`; researchCandidate.append(option);
  });
  const ready = [...researchCandidate.options].find(option => option.dataset.ready === 'true');
  if (ready) researchCandidate.value = ready.value;
  researchRunButton.disabled = !ready || value.capability.status !== 'READY';
  if (!researchRunId && value.latest_research_run_id) { researchRunId = value.latest_research_run_id; await pollResearch(); }
  else if (!ready && !researchRunId) researchStatus.textContent = JSON.stringify(value, null, 2);
  updateSearchControls();
}
function selectedSearchSeeds() { return [...searchSeeds.selectedOptions]; }
function validRoundOneSelection() {
  const selected = selectedSearchSeeds();
  const maximum = 2;
  return selected.length >= 1 && selected.length <= maximum
    && selected.every(option => option.dataset.profileId === profileSelect.value)
    && new Set(selected.map(option => option.dataset.profileId)).size === 1
    && new Set(selected.map(option => option.dataset.family)).size === selected.length;
}
function selectedRoundTwoCandidates() {
  return [...searchChildren.querySelectorAll('input[data-candidate-id][type="checkbox"]:checked')].map(checkbox => {
    const factor = searchChildren.querySelector(`input[data-factor-for="${checkbox.dataset.candidateId}"]`);
    return {candidate_id:checkbox.dataset.candidateId,changed_factor:factor ? factor.value.trim() : ''};
  });
}
function validRoundTwoSelection() {
  const selected = selectedRoundTwoCandidates();
  const factors = selected.map(item => item.changed_factor);
  const maximum = 1;
  return selected.length >= 1 && selected.length <= maximum
    && factors.every(value => /^[a-z][a-z0-9_.-]{0,62}$/.test(value))
    && new Set(factors).size === factors.length;
}
function updateSearchControls() {
  const state = searchContext && searchContext.state;
  const status = state ? state.status : 'BLOCKED_DATA';
  const capabilityReady = Boolean(searchContext && searchContext.capability && searchContext.capability.status === 'READY');
  searchSeeds.disabled = status !== 'SEARCH_READY';
  searchChildren.querySelectorAll('input').forEach(input => {
    if (input.type === 'checkbox') input.disabled = status !== 'SEARCH_ROUND_READY_FOR_CHILDREN';
    else if (status !== 'SEARCH_ROUND_READY_FOR_CHILDREN') input.disabled = true;
  });
  searchRoundOne.disabled = !capabilityReady || status !== 'SEARCH_READY' || !validRoundOneSelection();
  searchRoundTwo.disabled = !capabilityReady || status !== 'SEARCH_ROUND_READY_FOR_CHILDREN' || !validRoundTwoSelection();
  searchCancel.disabled = status !== 'RUNNING' || !state.campaign_id;
}
function renderSearchSeeds(context) {
  const selected = new Set(selectedSearchSeeds().map(option => option.value));
  searchSeeds.replaceChildren();
  if (!context || context.state.status !== 'SEARCH_READY') {
    const option = document.createElement('option'); option.disabled = true; option.textContent = '当前状态不接受 Round 1 seeds'; searchSeeds.append(option); return;
  }
  context.candidates.filter(candidate => candidate.role === 'MECHANISM_SEED' && candidate.status === 'READY' && candidate.profile_id === profileSelect.value).forEach(candidate => {
    const option = document.createElement('option'); option.value = candidate.candidate_id;
    option.dataset.profileId = candidate.profile_id; option.dataset.family = candidate.strategy_family || '';
    option.textContent = `${candidate.display_name} · ${candidate.strategy_family || 'UNKNOWN'} · ${candidate.class_name}`;
    option.selected = selected.has(option.value); searchSeeds.append(option);
  });
}
function renderSearchChildren(context) {
  searchChildren.replaceChildren();
  const state = context && context.state;
  const selectedParent = state && state.selected_parent;
  if (!state || state.status !== 'SEARCH_ROUND_READY_FOR_CHILDREN' || !selectedParent) {
    searchParentLock.textContent = 'selected parent 由 Round 1 receipt 锁定';
    const note = document.createElement('span'); note.className = 'note';
    note.textContent = searchIsTerminal(state && state.status) ? 'Search 已终止，不再接受 Round 2' : '等待 Round 1 selected parent';
    searchChildren.append(note); return;
  }
  searchParentLock.textContent = `唯一 selected parent（receipt 锁定）: ${selectedParent.display_name || selectedParent.candidate_id} · ${selectedParent.mechanism || 'UNKNOWN'}`;
  const children = context.candidates.filter(candidate => candidate.role === 'SINGLE_FACTOR_CHILD' && candidate.status === 'READY');
  if (!children.length) {
    const note = document.createElement('span'); note.className = 'note'; note.textContent = '暂无符合 parent/Profile/mechanism 绑定的 APPROVED child；可在下方 Codex 表单生成并人工批准。'; searchChildren.append(note); return;
  }
  children.forEach(candidate => {
    const row = document.createElement('div'); row.className = 'candidate-row';
    const label = document.createElement('label');
    const checkbox = document.createElement('input'); checkbox.type = 'checkbox'; checkbox.dataset.candidateId = candidate.candidate_id;
    label.append(checkbox, document.createTextNode(` ${candidate.display_name} · ${candidate.class_name}`));
    const factor = document.createElement('input'); factor.placeholder = 'changed_factor slug'; factor.maxLength = 63; factor.disabled = true; factor.dataset.factorFor = candidate.candidate_id;
    checkbox.addEventListener('change', () => { factor.disabled = !checkbox.checked; if (!checkbox.checked) factor.value = ''; updateSearchControls(); });
    factor.addEventListener('input', updateSearchControls); row.append(label, factor); searchChildren.append(row);
  });
}
async function loadSearchContext() {
  if (searchLoadPromise) return searchLoadPromise;
  searchLoadPromise = (async () => { try {
      searchContext = await request('/api/search/context');
      renderSearchSeeds(searchContext); renderSearchChildren(searchContext); refreshParents();
      searchStatus.textContent = JSON.stringify({capability:searchContext.capability,state:searchContext.state,generation_run:searchContext.generation_run || null}, null, 2); updateSearchControls();
      if (searchContext.state.status === 'RUNNING' && !searchTimer) searchTimer = setTimeout(pollSearch, 750);
      if (searchContext.state.status !== 'RUNNING' && searchTimer) { clearTimeout(searchTimer); searchTimer = null; }
    } catch (error) { searchContext = null;
      if (searchTimer) clearTimeout(searchTimer); searchTimer = null; searchStatus.textContent = JSON.stringify(error.payload || {error:error.message}, null, 2); searchRoundOne.disabled = true; searchRoundTwo.disabled = true; searchCancel.disabled = true;
    } })();
  try { return await searchLoadPromise; } finally { searchLoadPromise = null; } }
async function refreshSearchContext() { if (searchLoadPromise) await searchLoadPromise; return loadSearchContext(); }
async function pollSearch() { searchTimer = null; await loadSearchContext(); }
async function pollResearch() {
  if (!researchRunId) return;
  try {
    const value = await request(`/api/research-runs/${researchRunId}`); renderResearch(value);
    if (value.status === 'RUNNING') { if (!researchTimer) researchTimer = setInterval(pollResearch, 750); }
    else { clearInterval(researchTimer); researchTimer = null; await loadResearchContext(); }
  } catch (error) { researchStatus.textContent = JSON.stringify(error.payload || {error:error.message}, null, 2); }
}
async function loadPreflight() {
  try {
    const value = await request('/api/control/preflight');
    document.getElementById('overall').textContent = value.overall_status;
    const root = document.getElementById('checks'); root.replaceChildren();
    Object.entries(value.checks).forEach(([name, check]) => {
      const box = document.createElement('div'); box.className = 'check';
      const title = document.createElement('div'); title.className = 'name'; title.textContent = name;
      const status = document.createElement('div'); status.className = 'status'; status.textContent = check.status;
      const message = document.createElement('div'); message.className = 'note'; message.textContent = Object.entries(check)
        .filter(([key]) => key !== 'status').map(([key, item]) => `${key}: ${item === null ? 'UNKNOWN' : (typeof item === 'object' ? JSON.stringify(item) : String(item))}`).join(' · ');
      box.append(title, status, message); root.append(box);
    });
    if (value.latest_campaign && value.latest_campaign.action === 'CHECK_DATA') {
      campaignId = value.latest_campaign.campaign_id; showJob(value.latest_campaign); await poll();
      if (!terminal(value.latest_campaign.status) && !timer) timer = setInterval(poll, 750);
    }
  } catch (error) { document.getElementById('overall').textContent = `ERROR: ${error.message}`; }
}
async function pollGeneration() {
  if (!generationId) return;
  try {
    const value = await request(`/api/generations/${generationId}`); renderGeneration(value);
    if (value.status === 'RUNNING' || (value.runtime_status !== null && !terminal(value.runtime_status))) { if (!generationTimer) generationTimer = setInterval(pollGeneration, 750); }
    else { clearInterval(generationTimer); generationTimer = null; }
  } catch (error) { generationStatus.textContent = JSON.stringify(error.payload || {error:error.message}, null, 2); }
}
async function generationAction(action) {
  if (!generationId) return;
  try {
    const value = await request(`/api/generations/${generationId}/actions`, {method:'POST',headers:postHeaders,body:JSON.stringify({action})});
    renderGeneration(value); if (action !== 'CANCEL') { await loadGenerationContext(); await loadResearchContext(); await refreshSearchContext(); }
  } catch (error) { generationStatus.textContent = JSON.stringify(error.payload || {error:error.message}, null, 2); }
}
generateButton.addEventListener('click', async () => {
  const payload = {profile_id:profileSelect.value,idea:document.getElementById('idea').value};
  const parent = parentSelect.value, family = document.getElementById('family').value.trim(), failure = document.getElementById('failure').value.trim();
  const lock = searchContext && searchContext.codex_parent_lock;
  if (lock) {
    payload.profile_id = lock.profile_id;
    payload.parent_candidate_id = lock.parent_candidate_id;
    payload.strategy_family = lock.strategy_family;
  } else {
    if (parent) payload.parent_candidate_id = parent;
    if (family) payload.strategy_family = family;
  }
  if (failure) payload.expected_failure_mode = failure;
  generateButton.disabled = true;
  try { const value = await request('/api/generations', {method:'POST',headers:postHeaders,body:JSON.stringify(payload)}); generationId = value.id; renderGeneration(value); await pollGeneration(); }
  catch (error) { generationStatus.textContent = JSON.stringify(error.payload || {error:error.message}, null, 2); generateButton.disabled = false; }
});
generationCancel.addEventListener('click', () => generationAction('CANCEL'));
approveButton.addEventListener('click', () => generationAction('APPROVE'));
rejectButton.addEventListener('click', () => generationAction('REJECT'));
profileSelect.addEventListener('change', () => { refreshParents(); renderSearchSeeds(searchContext); updateSearchControls(); });
searchSeeds.addEventListener('change', updateSearchControls);
searchRoundOne.addEventListener('click', async () => {
  if (!validRoundOneSelection()) return;
  searchRoundOne.disabled = true;
  try {
    const payload = {profile_id:profileSelect.value,candidate_ids:selectedSearchSeeds().map(option => option.value)};
    await request('/api/search-campaigns', {method:'POST',headers:postHeaders,body:JSON.stringify(payload)});
    await refreshSearchContext();
  } catch (error) { searchStatus.textContent = JSON.stringify(error.payload || {error:error.message}, null, 2); await refreshSearchContext(); }
});
searchRoundTwo.addEventListener('click', async () => {
  const campaignId = searchContext && searchContext.state.campaign_id;
  if (!campaignId || !validRoundTwoSelection()) return;
  searchRoundTwo.disabled = true;
  try {
    await request(`/api/search-campaigns/${encodeURIComponent(campaignId)}/actions`, {method:'POST',headers:postHeaders,body:JSON.stringify({action:'START_ROUND_2',candidates:selectedRoundTwoCandidates()})});
    await refreshSearchContext();
  } catch (error) { searchStatus.textContent = JSON.stringify(error.payload || {error:error.message}, null, 2); await refreshSearchContext(); }
});
searchCancel.addEventListener('click', async () => {
  const campaignId = searchContext && searchContext.state.campaign_id;
  if (!campaignId) return; searchCancel.disabled = true;
  try {
    await request(`/api/search-campaigns/${encodeURIComponent(campaignId)}/actions`, {method:'POST',headers:postHeaders,body:JSON.stringify({action:'CANCEL'})});
    await refreshSearchContext();
  } catch (error) { searchStatus.textContent = JSON.stringify(error.payload || {error:error.message}, null, 2); await refreshSearchContext(); }
});
researchRunButton.addEventListener('click', async () => {
  const selected = researchCandidate.selectedOptions[0];
  if (!selected || selected.dataset.ready !== 'true') return;
  researchRunButton.disabled = true;
  try {
    const value = await request('/api/research-runs', {method:'POST',headers:postHeaders,body:JSON.stringify({candidate_id:selected.value})});
    researchRunId = value.research_run_id; renderResearch(value); await pollResearch();
    if (!researchTimer) researchTimer = setInterval(pollResearch,750);
  } catch (error) { researchStatus.textContent = JSON.stringify(error.payload || {error:error.message}, null, 2); await loadResearchContext(); }
});
researchCancelButton.addEventListener('click', async () => {
  if (!researchRunId) return; researchCancelButton.disabled = true;
  try { renderResearch(await request(`/api/research-runs/${researchRunId}/actions`, {method:'POST',headers:postHeaders,body:JSON.stringify({action:'CANCEL'})})); }
  catch (error) { researchStatus.textContent = JSON.stringify(error.payload || {error:error.message}, null, 2); }
});
researchHoldoutButton.addEventListener('click', async () => {
  if (!researchRunId || researchHoldoutButton.disabled) return;
  researchHoldoutButton.disabled = true;
  try {
    const value = await request(`/api/research-runs/${researchRunId}/actions`, {method:'POST',headers:postHeaders,body:JSON.stringify({action:'AUTHORIZE_HOLDOUT'})});
    renderResearch(value); await pollResearch();
    if (!researchTimer) researchTimer = setInterval(pollResearch,750);
  } catch (error) { researchStatus.textContent = JSON.stringify(error.payload || {error:error.message}, null, 2); await loadResearchContext(); }
});
async function manualReviewAction(action) {
  if (!researchRunId) return;
  const reason = manualReviewReason.value;
  manualRejectButton.disabled = true; manualPassButton.disabled = true;
  try {
    const value = await request(`/api/research-runs/${researchRunId}/actions`, {method:'POST',headers:postHeaders,body:JSON.stringify({action,reason})});
    renderResearch(value);
  } catch (error) {
    researchStatus.textContent = JSON.stringify(error.payload || {error:error.message}, null, 2);
    await pollResearch();
  }
}
manualRejectButton.addEventListener('click', () => manualReviewAction('REJECT'));
manualPassButton.addEventListener('click', () => manualReviewAction('PASS_AND_CREATE_RELEASE'));
async function poll() {
  if (!campaignId) return;
  try {
    const [status, events] = await Promise.all([request(`/api/campaigns/${campaignId}`),request(`/api/campaigns/${campaignId}/events`)]);
    showJob(status); eventList.replaceChildren(); events.events.forEach(event => { const item = document.createElement('li'); item.textContent = `${event.at_utc} · ${event.status} · ${event.message}`; eventList.append(item); });
    cancelButton.disabled = terminal(status.status); runButton.disabled = !terminal(status.status); if (terminal(status.status)) { clearInterval(timer); timer = null; }
  } catch (error) { showJob({error:error.message}); }
}
runButton.addEventListener('click', async () => {
  runButton.disabled = true;
  try { const value = await request('/api/campaigns', {method:'POST',headers:postHeaders,body:JSON.stringify({action:'CHECK_DATA'})}); campaignId = value.campaign_id; cancelButton.disabled = false; showJob(value); await poll(); if (!timer) timer = setInterval(poll,750); }
  catch (error) { showJob({error:error.message}); runButton.disabled = false; }
});
cancelButton.addEventListener('click', async () => {
  if (!campaignId) return; cancelButton.disabled = true;
  try { showJob(await request(`/api/campaigns/${campaignId}/actions`, {method:'POST',headers:postHeaders,body:JSON.stringify({action:'CANCEL'})})); }
  catch (error) { showJob({error:error.message}); }
});
Promise.all([loadPreflight(), loadGenerationContext(), loadResearchContext(), loadSearchContext()]).catch(error => { generationStatus.textContent = `ERROR: ${error.message}`; });
"""


def _strict_json_object(raw: bytes) -> Dict[str, Any]:
    def no_duplicates(pairs: Sequence[Tuple[str, Any]]) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result

    def reject_constant(value: str) -> Any:
        raise ValueError(value)

    value = json.loads(
        raw.decode("utf-8", "strict"),
        object_pairs_hook=no_duplicates,
        parse_constant=reject_constant,
    )
    if not isinstance(value, dict):
        raise ValueError("JSON root must be an object")
    return value


class ResearchConsoleRequestHandler(StrategyLibraryRequestHandler):
    """Add fixed control routes while preserving Strategy Library routes."""

    content_security_policy = (
        "default-src 'none'; style-src 'unsafe-inline'; script-src 'self'; "
        "connect-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"
    )

    @property
    def controller(self) -> ResearchConsoleController:
        return getattr(self.server, "research_console_controller")

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(2.0)

    def parse_request(self) -> bool:
        """Retain the wire target before stdlib normalizes leading ``//``."""
        self._raw_request_target: Optional[str] = None
        self._raw_request_line_valid = False
        raw = self.raw_requestline
        if raw.endswith(b"\r\n"):
            line = raw[:-2]
            words = line.split(b" ")
            if (
                len(words) == 3
                and all(words)
                and all(0x21 <= byte <= 0x7E for byte in line if byte != 0x20)
            ):
                try:
                    self._raw_request_target = words[1].decode("ascii")
                except UnicodeDecodeError:
                    pass
                else:
                    self._raw_request_line_valid = True
        return super().parse_request()

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _control_error(
        self, status: int, code: str, message: str, *, head_only: bool = False
    ) -> None:
        self._error(status, code, message, api=True, head_only=head_only)

    def _request_target(self):
        if not self._raw_request_line_valid:
            raise ControlRequestError(400, "bad_target", "请求目标无效")
        target = self._raw_request_target or self.path
        if (
            not target.startswith("/")
            or target.startswith("//")
            or any(
                ord(character) < 0x21 or ord(character) > 0x7E
                for character in target
            )
        ):
            raise ControlRequestError(400, "bad_target", "请求目标无效")
        try:
            request = urlsplit(target)
        except ValueError as exc:
            raise ControlRequestError(
                400, "bad_target", "请求目标无效"
            ) from exc
        if (
            request.scheme
            or request.netloc
            or request.fragment
            or not request.path.startswith("/")
        ):
            raise ControlRequestError(400, "bad_target", "请求目标无效")
        return request

    def _dispatch(self, *, head_only: bool) -> None:
        try:
            request = self._request_target()
        except ControlRequestError as exc:
            self._control_error(
                exc.status, exc.code, exc.message, head_only=head_only
            )
            return
        path = request.path
        sealed_library = self.controller._search_mode_configured and path in {
            "/", "/api/strategies", "/strategy", "/api/strategy", "/download"
        }
        is_control = sealed_library or path in (
            "/console",
            "/console.js",
            "/api/control/preflight",
            "/api/campaigns",
            "/api/generation/context",
            "/api/generations",
            "/api/research/context",
            "/api/research-runs",
            "/api/search/context",
            "/api/search-campaigns",
        ) or path.startswith("/api/campaigns/") or path.startswith(
            "/api/generations/"
        ) or path.startswith(
            "/api/research-runs/"
        ) or path.startswith(
            "/api/search-campaigns/"
        )
        if not is_control:
            super()._dispatch(head_only=head_only)
            return
        if not self._has_expected_host():
            self._control_error(
                400,
                "bad_host",
                "Host 必须使用服务启动时打印的 loopback 地址",
                head_only=head_only,
            )
            return
        try:
            if sealed_library:
                raise ControlRequestError(
                    404,
                    "SEALED_UNREAD",
                    "Explicit Search mode does not expose Strategy Library evidence",
                )
            if path == "/console":
                if request.query:
                    raise ControlRequestError(400, "bad_request", "页面不接受查询参数")
                token = html.escape(
                    str(getattr(self.server, "research_console_csrf_token")), quote=True
                )
                self._send(
                    200,
                    CONSOLE_HTML.format(csrf_token=token).encode("utf-8"),
                    "text/html; charset=utf-8",
                    head_only=head_only,
                )
                return
            if path == "/console.js":
                if request.query:
                    raise ControlRequestError(400, "bad_request", "脚本不接受查询参数")
                self._send(
                    200,
                    CONSOLE_JS.encode("utf-8"),
                    "text/javascript; charset=utf-8",
                    head_only=head_only,
                )
                return
            if path == "/api/control/preflight":
                if request.query:
                    raise ControlRequestError(400, "bad_request", "API 不接受查询参数")
                self._send(
                    200,
                    json.dumps(
                        self.controller.preflight(),
                        ensure_ascii=False,
                        separators=(",", ":"),
                        sort_keys=True,
                    ).encode("utf-8"),
                    "application/json; charset=utf-8",
                    head_only=head_only,
                )
                return
            if path == "/api/generation/context":
                if request.query:
                    raise ControlRequestError(400, "bad_request", "API 不接受查询参数")
                payload = self.controller.generation_context()
                self._send(
                    200,
                    json.dumps(
                        payload,
                        ensure_ascii=False,
                        separators=(",", ":"),
                        sort_keys=True,
                    ).encode("utf-8"),
                    "application/json; charset=utf-8",
                    head_only=head_only,
                )
                return
            if path == "/api/generations":
                if request.query:
                    raise ControlRequestError(400, "bad_request", "API 不接受查询参数")
                self._send_control_method_not_allowed(path, head_only=head_only)
                return
            if path == "/api/research/context":
                if request.query:
                    raise ControlRequestError(400, "bad_request", "API 不接受查询参数")
                payload = self.controller.research_context()
                self._send(
                    200,
                    json.dumps(
                        payload,
                        ensure_ascii=False,
                        separators=(",", ":"),
                        sort_keys=True,
                    ).encode("utf-8"),
                    "application/json; charset=utf-8",
                    head_only=head_only,
                )
                return
            if path == "/api/search/context":
                if request.query:
                    raise ControlRequestError(400, "bad_request", "API 不接受查询参数")
                payload = self.controller.search_context()
                self._send(
                    200,
                    json.dumps(
                        payload,
                        ensure_ascii=False,
                        separators=(",", ":"),
                        sort_keys=True,
                    ).encode("utf-8"),
                    "application/json; charset=utf-8",
                    head_only=head_only,
                )
                return
            if path == "/api/research-runs":
                if request.query:
                    raise ControlRequestError(400, "bad_request", "API 不接受查询参数")
                self._send_control_method_not_allowed(path, head_only=head_only)
                return
            research_match = re.fullmatch(r"/api/research-runs/([^/]+)", path)
            if research_match is not None:
                if request.query:
                    raise ControlRequestError(400, "bad_request", "API 不接受查询参数")
                payload = self.controller.get_research_run(research_match.group(1))
                self._send(
                    200,
                    json.dumps(
                        payload,
                        ensure_ascii=False,
                        separators=(",", ":"),
                        sort_keys=True,
                    ).encode("utf-8"),
                    "application/json; charset=utf-8",
                    head_only=head_only,
                )
                return
            generation_match = re.fullmatch(r"/api/generations/([^/]+)", path)
            if generation_match is not None:
                if request.query:
                    raise ControlRequestError(400, "bad_request", "API 不接受查询参数")
                payload = self.controller.get_generation(generation_match.group(1))
                response_status = (
                    409
                    if payload.get("error_code") == "DUPLICATE_CODE_SHA256"
                    else 200
                )
                if response_status == 409:
                    payload = {
                        **payload,
                        "error": "duplicate_candidate",
                        "message": payload.get("message")
                        or "生成源码与既有 Candidate 重复",
                    }
                self._send(
                    response_status,
                    json.dumps(
                        payload,
                        ensure_ascii=False,
                        separators=(",", ":"),
                        sort_keys=True,
                    ).encode("utf-8"),
                    "application/json; charset=utf-8",
                    head_only=head_only,
                )
                return
            search_match = re.fullmatch(r"/api/search-campaigns/([^/]+)", path)
            if search_match is not None:
                if request.query:
                    raise ControlRequestError(400, "bad_request", "API 不接受查询参数")
                payload = self.controller.get_search_campaign(search_match.group(1))
                self._send(
                    200,
                    json.dumps(
                        payload,
                        ensure_ascii=False,
                        separators=(",", ":"),
                        sort_keys=True,
                    ).encode("utf-8"),
                    "application/json; charset=utf-8",
                    head_only=head_only,
                )
                return
            if path == "/api/search-campaigns":
                if request.query:
                    raise ControlRequestError(400, "bad_request", "API 不接受查询参数")
                self._send_control_method_not_allowed(path, head_only=head_only)
                return
            if path == "/api/campaigns":
                if request.query:
                    raise ControlRequestError(
                        400, "bad_request", "API 不接受查询参数"
                    )
                self._send_control_method_not_allowed(path, head_only=head_only)
                return
            match = re.fullmatch(
                r"/api/campaigns/([^/]+)(/events)?", path
            )
            if match is None:
                raise ControlRequestError(404, "not_found", "API 不存在")
            campaign_id, event_suffix = match.groups()
            if event_suffix:
                if request.query:
                    raise ControlRequestError(400, "bad_request", "API 不接受查询参数")
                payload = self.controller.get_events(campaign_id)
            else:
                if request.query:
                    raise ControlRequestError(400, "bad_request", "API 不接受查询参数")
                payload = self.controller.get_status(campaign_id)
            self._send(
                200,
                json.dumps(
                    payload,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode("utf-8"),
                "application/json; charset=utf-8",
                head_only=head_only,
            )
        except ControlRequestError as exc:
            self._control_error(
                exc.status, exc.code, exc.message, head_only=head_only
            )
        except (OSError, RuntimeError):
            self._control_error(
                500,
                "control_unavailable",
                "Research Console 暂时无法读取状态",
                head_only=head_only,
            )

    def _single_header(self, name: str) -> Optional[str]:
        values = self.headers.get_all(name, failobj=[])
        return values[0] if len(values) == 1 else None

    def _read_post_object(self) -> Dict[str, Any]:
        if self.headers.get_all("Transfer-Encoding", failobj=[]):
            raise ControlRequestError(400, "bad_request", "不接受流式请求体")
        content_type = self._single_header("Content-Type")
        if content_type != "application/json":
            raise ControlRequestError(415, "unsupported_media_type", "POST 必须使用 application/json")
        length_value = self._single_header("Content-Length")
        if length_value is None or re.fullmatch(r"0|[1-9][0-9]*", length_value) is None:
            raise ControlRequestError(400, "bad_request", "请求体长度无效")
        try:
            length = int(length_value)
        except ValueError:
            length = -1
        if length > MAX_REQUEST_BYTES:
            raise ControlRequestError(413, "body_too_large", "请求体超过允许大小")
        if length < 0:
            raise ControlRequestError(400, "bad_request", "请求体长度无效")
        raw = self.rfile.read(length)
        try:
            return _strict_json_object(raw)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            raise ControlRequestError(400, "bad_request", "请求体必须是严格 JSON object") from None

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
        try:
            request = self._request_target()
        except ControlRequestError as exc:
            self._control_error(exc.status, exc.code, exc.message)
            return
        create_route = request.path == "/api/campaigns"
        create_generation_route = request.path == "/api/generations"
        create_research_route = request.path == "/api/research-runs"
        create_search_route = request.path == "/api/search-campaigns"
        action_match = re.fullmatch(r"/api/campaigns/([^/]+)/actions", request.path)
        generation_action_match = re.fullmatch(
            r"/api/generations/([^/]+)/actions", request.path
        )
        research_action_match = re.fullmatch(
            r"/api/research-runs/([^/]+)/actions", request.path
        )
        search_action_match = re.fullmatch(
            r"/api/search-campaigns/([^/]+)/actions", request.path
        )
        if (
            not create_route
            and not create_generation_route
            and not create_research_route
            and not create_search_route
            and action_match is None
            and generation_action_match is None
            and research_action_match is None
            and search_action_match is None
        ):
            self._method_not_allowed()
            return
        if not self._has_expected_host():
            self._control_error(
                400, "bad_host", "Host 必须使用服务启动时打印的 loopback 地址"
            )
            return
        expected_origin = f"http://{LOOPBACK_HOST}:{self.server.server_port}"
        if self._single_header("Origin") != expected_origin:
            self._control_error(403, "bad_origin", "POST 必须来自同源页面")
            return
        supplied_token = self._single_header("X-CSRF-Token")
        expected_token = str(getattr(self.server, "research_console_csrf_token"))
        if supplied_token is None or not hmac.compare_digest(
            supplied_token, expected_token
        ):
            self._control_error(403, "bad_csrf", "CSRF token 无效")
            return
        try:
            if request.query:
                raise ControlRequestError(400, "bad_request", "POST 不接受查询参数")
            body = self._read_post_object()
            if create_route:
                if body != {"action": "CHECK_DATA"}:
                    raise ControlRequestError(
                        400, "invalid_action", "只允许固定 CHECK_DATA action"
                    )
                payload = self.controller.create_campaign()
                response_status = 202
            elif create_generation_route:
                try:
                    generation_request = validate_generation_request(body)
                except GenerationContractError as exc:
                    raise ControlRequestError(
                        exc.status, exc.code, exc.message
                    ) from exc
                payload = self.controller.create_generation(generation_request)
                response_status = 202
            elif create_research_route:
                if set(body) != {"candidate_id"} or not isinstance(
                    body.get("candidate_id"), str
                ):
                    raise ControlRequestError(
                        400,
                        "invalid_research_request",
                        "只允许 exact candidate_id 请求",
                    )
                payload = self.controller.create_research_run(body["candidate_id"])
                response_status = 202
            elif create_search_route:
                candidate_ids = body.get("candidate_ids")
                if (
                    set(body) != {"profile_id", "candidate_ids"}
                    or not isinstance(candidate_ids, list)
                    or not isinstance(body.get("profile_id"), str)
                ):
                    raise ControlRequestError(
                        400,
                        "invalid_search_request",
                        "Round 1 只接受 exact profile_id 和一至两个唯一 candidate_id",
                    )
                payload = self.controller.create_search_campaign(
                    candidate_ids, body["profile_id"]
                )
                response_status = 202
            elif action_match is not None:
                if body != {"action": "CANCEL"}:
                    raise ControlRequestError(
                        400, "invalid_action", "只允许固定 CANCEL action"
                    )
                payload = self.controller.cancel_campaign(action_match.group(1))
                response_status = 202
            elif generation_action_match is not None:
                if set(body) != {"action"} or body.get("action") not in {
                    "CANCEL",
                    "APPROVE",
                    "REJECT",
                }:
                    raise ControlRequestError(
                        400,
                        "invalid_action",
                        "Generation action 只允许 CANCEL、APPROVE 或 REJECT",
                    )
                selected_action = str(body["action"])
                if selected_action == "CANCEL":
                    payload = self.controller.cancel_generation(
                        generation_action_match.group(1)
                    )
                    response_status = 202
                else:
                    payload = self.controller.review_generation(
                        generation_action_match.group(1),
                        "APPROVED" if selected_action == "APPROVE" else "REJECTED",
                    )
                    response_status = 200
            elif research_action_match is not None:
                if body == {"action": "CANCEL"}:
                    payload = self.controller.cancel_research_run(
                        research_action_match.group(1)
                    )
                    response_status = 202
                elif body == {"action": "AUTHORIZE_HOLDOUT"}:
                    payload = self.controller.authorize_holdout(
                        research_action_match.group(1)
                    )
                    response_status = 202
                elif (
                    set(body) == {"action", "reason"}
                    and body.get("action")
                    in {"REJECT", "PASS_AND_CREATE_RELEASE"}
                    and isinstance(body.get("reason"), str)
                ):
                    payload = self.controller.review_research_run(
                        research_action_match.group(1),
                        str(body["action"]),
                        str(body["reason"]),
                    )
                    response_status = 200
                else:
                    raise ControlRequestError(
                        400,
                        "invalid_action",
                        "ResearchRun action 只允许固定 CANCEL、AUTHORIZE_HOLDOUT、REJECT 或 PASS_AND_CREATE_RELEASE",
                    )
            else:
                campaign_id = search_action_match.group(1)
                if body == {"action": "CANCEL"}:
                    payload = self.controller.cancel_search_campaign(campaign_id)
                    response_status = 202
                elif set(body) == {"action", "candidates"} and body.get(
                    "action"
                ) == "START_ROUND_2":
                    candidates = body.get("candidates")
                    if not isinstance(candidates, list):
                        raise ControlRequestError(
                            400,
                            "invalid_search_request",
                            "Round 2 只接受一个 candidate_id 与 changed_factor",
                        )
                    payload = self.controller.start_search_round_two(
                        campaign_id, candidates
                    )
                    response_status = 202
                else:
                    raise ControlRequestError(
                        400,
                        "invalid_action",
                        "Search action 只允许 CANCEL 或 START_ROUND_2",
                    )
            self._send(
                response_status,
                json.dumps(
                    payload,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode("utf-8"),
                "application/json; charset=utf-8",
            )
        except ControlRequestError as exc:
            self._control_error(exc.status, exc.code, exc.message)
        except (OSError, RuntimeError):
            self._control_error(
                500, "control_unavailable", "Research Console 暂时无法执行固定动作"
            )

    def _send_control_method_not_allowed(
        self, path: str, *, head_only: bool = False
    ) -> None:
        allow = (
            "POST"
            if path in (
                "/api/campaigns",
                "/api/generations",
                "/api/research-runs",
                "/api/search-campaigns",
            )
            or path.endswith("/actions")
            else "GET, HEAD"
        )
        self._send(
            405,
            json.dumps(
                {"error": "method_not_allowed", "message": "method not allowed"},
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8"),
            "application/json; charset=utf-8",
            head_only=head_only,
            extra_headers={"Allow": allow},
        )

    def _method_not_allowed(self) -> None:
        try:
            path = self._request_target().path
        except ControlRequestError as exc:
            self._control_error(exc.status, exc.code, exc.message)
            return
        if (
            path in (
                "/console",
                "/console.js",
                "/api/control/preflight",
                "/api/generation/context",
                "/api/research/context",
                "/api/search/context",
            )
            or path == "/api/campaigns"
            or path.startswith("/api/campaigns/")
            or path == "/api/generations"
            or path.startswith("/api/generations/")
            or path == "/api/research-runs"
            or path.startswith("/api/research-runs/")
            or path == "/api/search-campaigns"
            or path.startswith("/api/search-campaigns/")
        ):
            if not self._has_expected_host():
                self._control_error(
                    400, "bad_host", "Host 必须使用服务启动时打印的 loopback 地址"
                )
                return
            self._send_control_method_not_allowed(path)
            return
        super()._method_not_allowed()

    def send_error(
        self,
        code: int,
        message: Optional[str] = None,
        explain: Optional[str] = None,
    ) -> None:
        """Replace stdlib HTML/parser errors with sanitized security headers."""
        if code == 501:
            self._method_not_allowed()
            return
        self._control_error(
            413 if code == 413 else 400,
            "bad_request",
            "请求无法安全解析",
        )

    do_PUT = _method_not_allowed
    do_PATCH = _method_not_allowed
    do_DELETE = _method_not_allowed
    do_OPTIONS = _method_not_allowed
    do_TRACE = _method_not_allowed
    do_CONNECT = _method_not_allowed


def create_research_console_server(
    database: PathLike,
    runtime_root: PathLike,
    pilot_root: PathLike,
    port: int = DEFAULT_PORT,
    artifact_root: Optional[PathLike] = None,
    *,
    search_root: Optional[PathLike] = None,
    release_root: Optional[PathLike] = None,
    frequi_base_url: Optional[str] = None,
    frequi_results_root: Optional[PathLike] = None,
    codex_binary: Optional[PathLike] = None,
    codex_model: Optional[str] = None,
    check_data_python: PathLike = sys.executable,
    freqtrade_python: Optional[PathLike] = None,
    freqtrade_source: Optional[PathLike] = None,
    webserver_base_url: str = "http://127.0.0.1:8080",
    task_timeout_seconds: float = 300.0,
):
    """Create one loopback server containing both Console and Library routes."""
    server = create_strategy_library_server(
        database,
        port,
        artifact_root=artifact_root,
        frequi_base_url=frequi_base_url,
        frequi_results_root=frequi_results_root,
        request_handler_class=ResearchConsoleRequestHandler,
        validate_database=False,
    )
    controller: Optional[ResearchConsoleController] = None
    try:
        handler = server.RequestHandlerClass
        controller = ResearchConsoleController(
            handler.database_path,
            runtime_root,
            pilot_root,
            search_root=search_root,
            codex_binary=codex_binary,
            codex_model=codex_model,
            check_data_python=check_data_python,
            freqtrade_python=freqtrade_python,
            freqtrade_source=freqtrade_source,
            webserver_base_url=webserver_base_url,
            artifact_root=handler.artifact_root,
            release_root=release_root,
            frequi_config=handler.frequi_config,
            task_timeout_seconds=task_timeout_seconds,
        )
        setattr(server, "research_console_controller", controller)
        setattr(server, "manual_release_root", controller._release_root)
        setattr(server, "research_console_csrf_token", secrets.token_urlsafe(32))
        return server
    except Exception:
        if controller is not None:
            controller.shutdown()
        server.server_close()
        raise
