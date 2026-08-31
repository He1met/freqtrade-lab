"""Single-process local Research Console for fixed, bounded actions.

The console deliberately exposes no generic command runner.  Its first slice
can only run the existing ``check-data`` command with paths frozen at startup.
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
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple, Union
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from lab.frequi import (
    FreqUIConfig,
    FreqUIConfigurationError,
    _loopback_base_url,
    probe_frequi,
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
REQUEST_SCHEMA = "freqtrade-lab-research-console-request-v1"
OWNER_SCHEMA = "freqtrade-lab-research-console-owner-v1"
MAX_REQUEST_BYTES = 4096
MAX_STATE_BYTES = 256 * 1024
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
        "INTERRUPTING",
    }
)
CODEX_REQUIRED_FLAGS = (
    "--cd",
    "--ephemeral",
    "--ignore-user-config",
    "--json",
    "--output-last-message",
    "--sandbox",
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
    pilot_identity: Tuple[int, int]
    codex_binary: Optional[Path]
    check_data_python: Path
    task_timeout_seconds: float


@dataclass
class _ActiveJob:
    campaign_id: str
    process: subprocess.Popen[bytes]
    process_group_id: int
    deadline: float
    monitor: Optional[threading.Thread] = None
    cancel_requested: bool = False
    timed_out: bool = False
    signal_sent_at: Optional[float] = None
    shutdown_requested: bool = False
    termination_identity_verified: bool = False
    lifecycle_lock: threading.RLock = field(default_factory=threading.RLock)
    receipt_lock: threading.Lock = field(default_factory=threading.Lock)


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


def _minimal_environment() -> Dict[str, str]:
    return {
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": os.environ.get("PATH", "/usr/bin:/bin:/usr/sbin:/sbin"),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUNBUFFERED": "1",
    }


def build_check_data_argv(
    pilot_root: Path,
    python_executable: PathLike = sys.executable,
) -> Tuple[str, ...]:
    """Return the only child argv exposed by this console slice."""
    script = PILOT_SCRIPT.resolve(strict=True)
    return (
        str(python_executable),
        str(script),
        "check-data",
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
        codex_binary: Optional[PathLike] = None,
        check_data_python: PathLike = sys.executable,
        webserver_base_url: str = "http://127.0.0.1:8080",
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
        pilot, pilot_identity = _resolve_external_directory(pilot_root, "pilot root")
        resolved_python = _resolve_executable(check_data_python, None)
        if resolved_python is None:
            raise ResearchConsoleError("CHECK_DATA Python is unavailable")
        try:
            normalized_webserver = _loopback_base_url(webserver_base_url)
        except FreqUIConfigurationError as exc:
            raise ResearchConsoleError("webserver probe URL is unsafe") from exc
        self._runtime_lock_fd = _acquire_runtime_lock(runtime, runtime_identity)
        self._campaigns_fd = -1
        self._lock = threading.RLock()
        self._active: Optional[_ActiveJob] = None
        self._state_unavailable: set[str] = set()
        self._restart_confirmation_required = False
        self._shutting_down = False
        self._closed = False
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
                codex_binary=_resolve_executable(codex_binary, "codex"),
                check_data_python=resolved_python,
                task_timeout_seconds=float(task_timeout_seconds),
            )
            self.webserver_probe_config = FreqUIConfig(
                normalized_webserver, None, None
            )
            self.campaigns_root = campaigns
            self.check_data_argv = build_check_data_argv(pilot, resolved_python)
            self._restart_confirmation_required = (
                self._recover_interrupted_campaigns()
            )
        except Exception:
            if self._campaigns_fd >= 0:
                os.close(self._campaigns_fd)
                self._campaigns_fd = -1
            fcntl.flock(self._runtime_lock_fd, fcntl.LOCK_UN)
            os.close(self._runtime_lock_fd)
            raise

    def _directory_unchanged(self, path: Path, identity: Tuple[int, int]) -> bool:
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
                current = _read_json_object_at(campaign_fd, "status.json")
            except (ControlRequestError, OSError, RecursionError, ValueError):
                if campaign_fd is not None:
                    os.close(campaign_fd)
                continue
            try:
                if (
                    current.get("schema") != STATUS_SCHEMA
                    or current.get("campaign_id") != campaign_id
                ):
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
        if binary is None:
            return {
                "status": "UNAVAILABLE",
                "binary_available": False,
                "version": None,
                "exec_available": False,
                "required_exec_flags": {
                    flag: False for flag in CODEX_REQUIRED_FLAGS
                },
                "model_invoked": False,
                "message": "Codex CLI 不可用",
            }
        version_code, version_output, version_timeout = _bounded_capability(
            (str(binary), "--version")
        )
        help_code, help_output, help_timeout = _bounded_capability(
            (str(binary), "exec", "--help")
        )
        if version_timeout or help_timeout:
            return {
                "status": "UNKNOWN",
                "binary_available": True,
                "version": None,
                "exec_available": False,
                "required_exec_flags": {
                    flag: False for flag in CODEX_REQUIRED_FLAGS
                },
                "model_invoked": False,
                "message": "Codex CLI capability check 超时",
            }
        try:
            help_text = help_output.decode("utf-8", "strict")
        except UnicodeDecodeError:
            help_text = ""
        version = _safe_version_line(version_output) if version_code == 0 else None
        flags = {
            flag: help_code == 0 and flag in help_text
            for flag in CODEX_REQUIRED_FLAGS
        }
        has_flags = all(flags.values())
        ready = version is not None and has_flags
        return {
            "status": "READY" if ready else "UNAVAILABLE",
            "binary_available": True,
            "version": version,
            "exec_available": help_code == 0,
            "required_exec_flags": flags,
            "model_invoked": False,
            "message": (
                "Codex CLI capability 可用"
                if ready
                else "Codex CLI 缺少后续受控生成所需参数"
            ),
        }

    def preflight(self) -> Dict[str, Any]:
        codex = self._codex_preflight()
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
        }
        with self._lock:
            latest = self._latest_status()
        return {
            "overall_status": (
                "READY"
                if all(item.get("status") == "READY" for item in checks.values())
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
        created_at: str,
        started_at: Optional[str],
        finished_at: Optional[str],
        return_code: Optional[int],
        message: str,
    ) -> Dict[str, Any]:
        return {
            "schema": STATUS_SCHEMA,
            "campaign_id": campaign_id,
            "action": "CHECK_DATA",
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
        **updates: Any,
    ) -> Dict[str, Any]:
        try:
            current = _read_json_object_at(campaign_fd, "status.json")
        except FileNotFoundError:
            current = {}
        current.update({"status": status_value, "message": message, **updates})
        _atomic_write_json_at(campaign_fd, "status.json", current)
        return current

    def _write_status(
        self,
        campaign_dir: Path,
        status_value: str,
        message: str,
        **updates: Any,
    ) -> Dict[str, Any]:
        descriptor: Optional[int] = None
        try:
            descriptor = self._open_campaign_fd(campaign_dir.name)
            return self._write_status_at(
                descriptor, status_value, message, **updates
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
                descriptor, status_value, message, **updates
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
            if not self._runtime_paths_unchanged() or not self._directory_unchanged(
                self.config.pilot_root, self.config.pilot_identity
            ):
                raise ControlRequestError(
                    409, "frozen_path_changed", "启动时冻结的运行目录身份已变化"
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
                if receipt is None:
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

    def _monitor_job(self, job: _ActiveJob) -> None:
        campaign_dir: Optional[Path] = None
        process_group_finalized = False
        try:
            campaign_dir = self._campaign_directory(
                job.campaign_id, must_exist=True
            )
            while True:
                timeout_started = False
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
                        self._record_transition(
                            campaign_dir,
                            "TIMEOUT_TERMINATING",
                            "任务超时，正在终止受控进程组",
                            "TIMEOUT",
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
                )
                else GROUP_EXIT_CONFIRM_SECONDS
            )
            if not process_group_finalized:
                process_group_finalized = self._wait_for_process_group(
                    job, confirmation_timeout
                )
            if not process_group_finalized:
                with job.receipt_lock:
                    receipt = self._record_transition(
                        campaign_dir,
                        "INTERRUPTED_NEEDS_CONFIRMATION",
                        "CHECK_DATA 进程组仍存在或无法确认消失；未继续发送未经确认的信号",
                        "PROCESS_GROUP_UNCONFIRMED",
                        finished_at_utc=_utc_now(),
                        return_code=return_code,
                        requires_confirmation=True,
                    )
                with self._lock:
                    self._restart_confirmation_required = True
                    if receipt is None:
                        self._state_unavailable.add(job.campaign_id)
                return
            finished = _utc_now()
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
            elif return_code == 0 and self._has_data_ready_output(campaign_dir):
                status_value = "SUCCEEDED"
                message = "CHECK_DATA 已完成；此状态不代表策略有效或盈利"
                event_type = "SUCCEEDED"
            else:
                status_value = "FAILED"
                message = (
                    "CHECK_DATA 输出合同无效；原始输出仅保存在 Git 外运行目录"
                    if return_code == 0
                    else "CHECK_DATA 执行失败；原始输出仅保存在 Git 外运行目录"
                )
                event_type = "FAILED"
            with job.receipt_lock:
                receipt = self._record_transition(
                    campaign_dir,
                    status_value,
                    message,
                    event_type,
                    finished_at_utc=finished,
                    return_code=return_code,
                    requires_confirmation=False,
                )
            if receipt is None:
                with self._lock:
                    self._state_unavailable.add(job.campaign_id)
                    self._restart_confirmation_required = True
        except Exception:
            process_group_finalized = self._terminate_owned_job(job)
            if campaign_dir is not None:
                with job.receipt_lock:
                    receipt = self._record_transition(
                        campaign_dir,
                        "INTERRUPTED_NEEDS_CONFIRMATION",
                        "控制器内部故障；任务终态需要人工确认",
                        "CONTROLLER_FAILED",
                        finished_at_utc=_utc_now(),
                        return_code=self._leader_return_code(job),
                        requires_confirmation=True,
                    )
                if receipt is None:
                    with self._lock:
                        self._state_unavailable.add(job.campaign_id)
            with self._lock:
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

    def get_status(self, campaign_id: str) -> Dict[str, Any]:
        with self._lock:
            if campaign_id in self._state_unavailable:
                raise ControlRequestError(
                    409,
                    "campaign_state_unavailable",
                    "Campaign 终态收据无法安全确认",
                )
        self._campaign_directory(campaign_id, must_exist=True)
        status_value = self._read_campaign_json(campaign_id, "status.json")
        if (
            status_value.get("schema") != STATUS_SCHEMA
            or status_value.get("campaign_id") != campaign_id
        ):
            raise ControlRequestError(
                409, "campaign_state_unavailable", "Campaign 状态无法安全读取"
            )
        return _public_status(status_value)

    def get_events(self, campaign_id: str, after: int = 0) -> Dict[str, Any]:
        with self._lock:
            if campaign_id in self._state_unavailable:
                raise ControlRequestError(
                    409,
                    "campaign_state_unavailable",
                    "Campaign 终态收据无法安全确认",
                )
        campaign_dir = self._campaign_directory(campaign_id, must_exist=True)
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

    def cancel_campaign(self, campaign_id: str) -> Dict[str, Any]:
        with self._lock:
            job = self._active
            if (
                job is None
                or job.campaign_id != campaign_id
            ):
                current = self.get_status(campaign_id)
                if current["status"] in TERMINAL_STATUSES:
                    return current
                raise ControlRequestError(
                    409, "campaign_not_active", "Campaign 不由当前服务持有"
                )
            if self._leader_return_code(job) is not None:
                current = self.get_status(campaign_id)
                if current["status"] in TERMINAL_STATUSES:
                    return current
                raise ControlRequestError(
                    409,
                    "process_group_unconfirmed",
                    "leader 已回收，不能向旧 PGID 发送信号；请轮询确认状态",
                )
            if job.shutdown_requested or job.timed_out:
                raise ControlRequestError(
                    409,
                    "termination_in_progress",
                    "任务已进入不可覆盖的终止流程",
                )
            if job.cancel_requested:
                return self.get_status(campaign_id)
            campaign_dir = self._campaign_directory(
                campaign_id, must_exist=True
            )
            if not job.receipt_lock.acquire(blocking=False):
                raise ControlRequestError(
                    409,
                    "termination_in_progress",
                    "任务状态正在完成，不接受新的取消转换",
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
        try:
            current = self._record_transition(
                campaign_dir,
                "CANCEL_REQUESTED",
                "已请求取消受控进程组",
                "CANCEL_REQUESTED",
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
                self._record_transition(
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
                    "owned CHECK_DATA monitor did not finalize"
                )
            if (
                job is not None
                and self._process_group_state(job) is not False
                and not self._restart_confirmation_required
            ):
                raise ResearchConsoleError(
                    "owned CHECK_DATA process group did not finalize"
                )
            if self._active is job:
                self._active = None
            campaigns_descriptor = self._campaigns_fd
            self._campaigns_fd = -1
            descriptor = self._runtime_lock_fd
            self._runtime_lock_fd = -1
            self._closed = True
        try:
            os.close(campaigns_descriptor)
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


CONSOLE_HTML = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="csrf-token" content="{csrf_token}">
<title>Research Console</title>
<style>
:root{{color-scheme:light;font:14px/1.5 system-ui,sans-serif;color:#172033;background:#f6f7f9}}
body{{margin:0}}main{{max-width:1000px;margin:auto;padding:24px}}
header{{display:flex;align-items:center;justify-content:space-between;margin-bottom:18px}}
h1,h2{{margin:0 0 10px}}a{{color:#3157d5}}section{{background:#fff;border:1px solid #dde2ea;border-radius:10px;padding:16px;margin:12px 0}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:8px}}
.check{{border:1px solid #e6e9ef;border-radius:8px;padding:10px}}.name{{font-weight:650}}.status{{font-family:ui-monospace,monospace}}
button{{border:1px solid #3157d5;border-radius:7px;background:#3157d5;color:#fff;padding:8px 12px;margin-right:8px}}button.secondary{{background:#fff;color:#3157d5}}button:disabled{{opacity:.45}}
pre{{white-space:pre-wrap;word-break:break-word;background:#f6f7f9;padding:10px;border-radius:7px;min-height:42px}}
.note{{color:#5d687a}}ul{{padding-left:20px}}
</style><script src="/console.js" defer></script></head>
<body><main><header><div><h1>Research Console</h1><div class="note">本地单进程 · 固定动作 · 无任意命令入口</div></div><a href="/">策略库</a></header>
<section><h2>Preflight</h2><div id="overall" class="status">CHECKING</div><div id="checks" class="grid"></div></section>
<section><h2>受控任务</h2><p class="note">本 Slice 只运行已冻结 Pilot 目录的 CHECK_DATA；成功不代表策略有效、盈利或可交易。</p>
<button id="run">运行 CHECK_DATA</button><button id="cancel" class="secondary" disabled>取消当前任务</button><pre id="job">尚未启动</pre></section>
<section><h2>规范化事件</h2><ul id="events"><li>暂无事件</li></ul></section>
</main></body></html>"""


CONSOLE_JS = r"""'use strict';
const token = document.querySelector('meta[name="csrf-token"]').content;
const runButton = document.getElementById('run');
const cancelButton = document.getElementById('cancel');
const jobBox = document.getElementById('job');
const eventList = document.getElementById('events');
let campaignId = null;
let timer = null;
function showJob(value) { jobBox.textContent = JSON.stringify(value, null, 2); }
function terminal(status) { return ['SUCCEEDED','FAILED','CANCELLED','TIMED_OUT','INTERRUPTED','INTERRUPTED_NEEDS_CONFIRMATION'].includes(status); }
async function request(path, options = {}) {
  const response = await fetch(path, options);
  const value = await response.json();
  if (!response.ok) throw new Error(value.message || value.error || `HTTP ${response.status}`);
  return value;
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
    if (value.latest_campaign) {
      campaignId = value.latest_campaign.campaign_id;
      showJob(value.latest_campaign);
      await poll();
      if (!terminal(value.latest_campaign.status) && !timer) timer = setInterval(poll, 750);
    }
  } catch (error) { document.getElementById('overall').textContent = `ERROR: ${error.message}`; }
}
async function poll() {
  if (!campaignId) return;
  try {
    const [status, events] = await Promise.all([
      request(`/api/campaigns/${campaignId}`),
      request(`/api/campaigns/${campaignId}/events`)
    ]);
    showJob(status); eventList.replaceChildren();
    events.events.forEach(event => { const item = document.createElement('li'); item.textContent = `${event.at_utc} · ${event.status} · ${event.message}`; eventList.append(item); });
    cancelButton.disabled = terminal(status.status);
    runButton.disabled = !terminal(status.status);
    if (terminal(status.status)) { clearInterval(timer); timer = null; }
  } catch (error) { showJob({error: error.message}); }
}
runButton.addEventListener('click', async () => {
  runButton.disabled = true;
  try {
    const value = await request('/api/campaigns', {
      method: 'POST', headers: {'Content-Type':'application/json','X-CSRF-Token':token},
      body: JSON.stringify({action:'CHECK_DATA'})
    });
    campaignId = value.campaign_id; cancelButton.disabled = false; showJob(value);
    await poll(); if (!timer) timer = setInterval(poll, 750);
  } catch (error) { showJob({error:error.message}); runButton.disabled = false; }
});
cancelButton.addEventListener('click', async () => {
  if (!campaignId) return;
  cancelButton.disabled = true;
  try {
    showJob(await request(`/api/campaigns/${campaignId}/actions`, {
      method:'POST', headers:{'Content-Type':'application/json','X-CSRF-Token':token},
      body:JSON.stringify({action:'CANCEL'})
    }));
  } catch (error) { showJob({error:error.message}); }
});
loadPreflight();
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
        is_control = path in (
            "/console",
            "/console.js",
            "/api/control/preflight",
            "/api/campaigns",
        ) or path.startswith("/api/campaigns/")
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
        action_match = re.fullmatch(r"/api/campaigns/([^/]+)/actions", request.path)
        if not create_route and action_match is None:
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
            else:
                if body != {"action": "CANCEL"}:
                    raise ControlRequestError(
                        400, "invalid_action", "只允许固定 CANCEL action"
                    )
                payload = self.controller.cancel_campaign(action_match.group(1))
            self._send(
                202,
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
            if path == "/api/campaigns" or path.endswith("/actions")
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
            path in ("/console", "/console.js", "/api/control/preflight")
            or path == "/api/campaigns"
            or path.startswith("/api/campaigns/")
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
    frequi_base_url: Optional[str] = None,
    frequi_results_root: Optional[PathLike] = None,
    codex_binary: Optional[PathLike] = None,
    check_data_python: PathLike = sys.executable,
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
            codex_binary=codex_binary,
            check_data_python=check_data_python,
            webserver_base_url=webserver_base_url,
            task_timeout_seconds=task_timeout_seconds,
        )
        setattr(server, "research_console_controller", controller)
        setattr(server, "research_console_csrf_token", secrets.token_urlsafe(32))
        return server
    except Exception:
        if controller is not None:
            controller.shutdown()
        server.server_close()
        raise
