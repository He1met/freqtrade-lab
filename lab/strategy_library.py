"""Read-only strategy library query and local HTTP presentation.

The module deliberately stays inside one process and Python's standard library.
It never initializes the database or writes business records.
"""

from __future__ import annotations

import html
import hashlib
import hmac
import io
import json
import math
import os
import sqlite3
import stat
import zipfile
from contextlib import closing
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple, Union
from urllib.parse import parse_qs, urlencode, urlsplit

from lab.frequi import (
    FreqUIConfig,
    FreqUIConfigurationError,
    configure_frequi,
    no_execution_frequi,
    probe_frequi,
    scenario_frequi_status,
    unconfigured_frequi,
)


SCHEMA_VERSION = 1
LOOPBACK_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
PathLike = Union[str, Path]


class StrategyLibraryError(RuntimeError):
    """Base error for read-only database and presentation failures."""


class ProfileNotFoundError(StrategyLibraryError):
    """Raised when a requested Research Profile does not exist."""


class ProfileRequiredError(StrategyLibraryError):
    """Raised when an API request cannot select one profile honestly."""


class BadRequestError(StrategyLibraryError):
    """Raised when an HTTP query is malformed or unsupported."""


class ResearchRunNotFoundError(StrategyLibraryError):
    """Raised when an exact profile/candidate/run tuple does not exist."""


class ExecutionNotFoundError(StrategyLibraryError):
    """Raised when a requested execution does not exist in a valid scope."""


class ArtifactUnavailableError(StrategyLibraryError):
    """Raised when an execution archive fails the download boundary."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


REQUIRED_SCENARIOS = ("DEVELOPMENT", "HOLDOUT", "HOLDOUT_STRESS")
MAX_DOWNLOAD_BYTES = 4 * 1024 * 1024


STRATEGY_LIBRARY_SQL = """
WITH
scoped_candidates AS (
    SELECT
        c.id,
        c.display_name,
        c.class_name,
        c.timeframe,
        c.strategy_family,
        c.created_at
    FROM candidates AS c
    JOIN generation_runs AS g ON g.id = c.generation_run_id
    WHERE g.research_profile_id = :profile_id
),
scoped_runs AS (
    SELECT r.*
    FROM research_runs AS r
    JOIN scoped_candidates AS c ON c.id = r.candidate_id
    WHERE r.research_profile_id = :profile_id
),
status_ranked AS (
    SELECT
        r.*,
        ROW_NUMBER() OVER (
            PARTITION BY r.candidate_id
            ORDER BY r.created_at DESC, r.id DESC
        ) AS candidate_rank
    FROM scoped_runs AS r
),
run_counts AS (
    SELECT
        candidate_id,
        SUM(CASE WHEN status = 'COMPLETED' THEN 1 ELSE 0 END)
            AS completed_count,
        SUM(
            CASE
                WHEN status = 'COMPLETED' AND verdict = 'PASSED' THEN 1
                ELSE 0
            END
        ) AS passed_count
    FROM scoped_runs
    GROUP BY candidate_id
),
eligible_summaries AS (
    SELECT
        r.id AS research_run_id,
        r.candidate_id,
        r.verdict,
        r.created_at,
        r.finished_at,
        development.profit_pct AS development_profit_pct,
        holdout.profit_pct AS holdout_profit_pct,
        holdout.max_drawdown_pct AS holdout_max_drawdown_pct,
        holdout.profit_factor AS holdout_profit_factor,
        holdout.total_trades AS holdout_total_trades,
        CAST(json_extract(holdout.metrics_json, '$.losses') AS INTEGER)
            AS holdout_losses,
        stress.profit_pct AS stress_profit_pct
    FROM scoped_runs AS r
    JOIN backtest_executions AS development
      ON development.research_run_id = r.id
     AND development.scenario = 'DEVELOPMENT'
    JOIN backtest_executions AS holdout
      ON holdout.research_run_id = r.id
     AND holdout.scenario = 'HOLDOUT'
    JOIN backtest_executions AS stress
      ON stress.research_run_id = r.id
     AND stress.scenario = 'HOLDOUT_STRESS'
    WHERE r.status = 'COMPLETED'
      AND r.finished_at IS NOT NULL
      AND development.status = 'SUCCEEDED'
      AND holdout.status = 'SUCCEEDED'
      AND stress.status = 'SUCCEEDED'
      AND typeof(development.profit_pct) IN ('integer', 'real')
      AND typeof(holdout.profit_pct) IN ('integer', 'real')
      AND typeof(holdout.max_drawdown_pct) IN ('integer', 'real')
      AND typeof(holdout.profit_factor) IN ('integer', 'real')
      AND typeof(holdout.total_trades) = 'integer'
      AND typeof(stress.profit_pct) IN ('integer', 'real')
      AND development.profit_pct BETWEEN -1.7976931348623157e308
                                         AND 1.7976931348623157e308
      AND holdout.profit_pct BETWEEN -1.7976931348623157e308
                                     AND 1.7976931348623157e308
      AND stress.profit_pct BETWEEN -1.7976931348623157e308
                                    AND 1.7976931348623157e308
      AND holdout.max_drawdown_pct BETWEEN 0 AND 1.7976931348623157e308
      AND holdout.profit_factor BETWEEN 0 AND 1.7976931348623157e308
      AND holdout.total_trades >= 0
      AND json_type(holdout.metrics_json, '$.losses') = 'integer'
      AND json_extract(holdout.metrics_json, '$.losses') >= 0
),
summary_ranked AS (
    SELECT
        s.*,
        ROW_NUMBER() OVER (
            PARTITION BY s.candidate_id
            ORDER BY
                s.finished_at DESC,
                s.created_at DESC,
                s.research_run_id DESC
        ) AS candidate_rank
    FROM eligible_summaries AS s
)
SELECT
    c.id AS candidate_id,
    c.display_name,
    c.class_name,
    c.timeframe,
    c.strategy_family,
    status_run.id AS latest_status_run_id,
    status_run.status AS latest_status,
    status_run.stage AS latest_status_stage,
    status_run.verdict AS latest_status_verdict,
    status_run.created_at AS latest_status_created_at,
    status_run.started_at AS latest_status_started_at,
    status_run.finished_at AS latest_status_finished_at,
    summary.research_run_id AS latest_summary_run_id,
    summary.verdict AS latest_summary_verdict,
    summary.finished_at AS latest_summary_finished_at,
    summary.development_profit_pct,
    summary.holdout_profit_pct,
    summary.holdout_max_drawdown_pct,
    summary.holdout_profit_factor,
    summary.holdout_total_trades,
    summary.holdout_losses,
    summary.stress_profit_pct,
    COALESCE(counts.completed_count, 0) AS completed_count,
    COALESCE(counts.passed_count, 0) AS passed_count,
    CASE
        WHEN summary.research_run_id IS NOT NULL AND EXISTS (
            SELECT 1
            FROM releases AS release
            WHERE release.research_run_id = summary.research_run_id
              AND release.archived_at IS NULL
        ) THEN 1
        ELSE 0
    END AS has_release
FROM scoped_candidates AS c
LEFT JOIN status_ranked AS status_run
  ON status_run.candidate_id = c.id
 AND status_run.candidate_rank = 1
LEFT JOIN summary_ranked AS summary
  ON summary.candidate_id = c.id
 AND summary.candidate_rank = 1
LEFT JOIN run_counts AS counts ON counts.candidate_id = c.id
ORDER BY c.created_at DESC, c.id DESC
"""


def _resolve_database_path(database: PathLike) -> Path:
    try:
        value = Path(database).expanduser()
        if value.is_symlink():
            raise StrategyLibraryError("database path must not be a symlink")
        path = value.resolve(strict=True)
    except StrategyLibraryError:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise StrategyLibraryError(
            f"database path cannot be resolved safely: {exc}"
        ) from exc
    try:
        mode = os.lstat(path).st_mode
    except OSError as exc:
        raise StrategyLibraryError(f"database cannot be inspected safely: {exc}") from exc
    if not stat.S_ISREG(mode):
        raise StrategyLibraryError("database path must be a regular file")
    return path


def _open_read_only_database(database: PathLike) -> sqlite3.Connection:
    path = _resolve_database_path(database)
    uri = f"{path.as_uri()}?mode=ro"
    try:
        connection = sqlite3.connect(uri, uri=True)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA query_only = ON")
        query_only = connection.execute("PRAGMA query_only").fetchone()
        if query_only is None or int(query_only[0]) != 1:
            raise StrategyLibraryError("SQLite query_only mode could not be enabled")
        schema_row = connection.execute("PRAGMA user_version").fetchone()
        if schema_row is None or int(schema_row[0]) != SCHEMA_VERSION:
            raise StrategyLibraryError(
                f"database schema version must be {SCHEMA_VERSION}"
            )
        return connection
    except StrategyLibraryError:
        try:
            connection.close()
        except (NameError, sqlite3.Error):
            pass
        raise
    except sqlite3.Error as exc:
        try:
            connection.close()
        except (NameError, sqlite3.Error):
            pass
        raise StrategyLibraryError(f"database cannot be opened read-only: {exc}") from exc


def _resolve_artifact_root(artifact_root: Optional[PathLike]) -> Optional[Path]:
    if artifact_root is None:
        return None
    try:
        value = Path(artifact_root).expanduser()
        if value.is_symlink():
            raise StrategyLibraryError("artifact root must not be a symlink")
        root = value.resolve(strict=True)
        mode = os.lstat(root).st_mode
    except StrategyLibraryError:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise StrategyLibraryError(
            f"artifact root cannot be resolved safely: {exc}"
        ) from exc
    if not stat.S_ISDIR(mode):
        raise StrategyLibraryError("artifact root must be a directory")
    return root


def _open_artifact_root_fd(artifact_root: Path) -> int:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(artifact_root, flags)
        if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
            os.close(descriptor)
            raise StrategyLibraryError("artifact root must be a directory")
        return descriptor
    except StrategyLibraryError:
        raise
    except OSError as exc:
        raise StrategyLibraryError(f"artifact root cannot be opened safely: {exc}") from exc


def _artifact_error(reason: str) -> ArtifactUnavailableError:
    messages = {
        "ROOT_NOT_CONFIGURED": "服务未配置 artifact root",
        "NO_ARCHIVE": "该场景没有证据 ZIP",
        "INVALID_PATH": "证据路径无效",
        "PATH_TRAVERSAL": "证据路径包含目录穿越",
        "OUTSIDE_ARTIFACT_ROOT": "证据文件不在允许目录内",
        "SYMLINK_NOT_ALLOWED": "证据路径包含不允许的符号链接",
        "MISSING": "证据文件不存在",
        "NOT_REGULAR_FILE": "证据目标不是普通文件",
        "NOT_ZIP": "证据目标不是有效 ZIP 文件",
        "UNREADABLE": "证据文件不可读取",
        "TOO_LARGE": "证据 ZIP 超出允许大小",
        "HASH_UNAVAILABLE": "数据库没有可验证的证据哈希",
        "HASH_MISMATCH": "证据 ZIP 与数据库哈希不一致",
    }
    return ArtifactUnavailableError(reason, messages[reason])


def _archive_sha256(raw_metrics: Any) -> str:
    try:
        parsed = json.loads(raw_metrics)
    except (TypeError, json.JSONDecodeError, RecursionError):
        raise _artifact_error("HASH_UNAVAILABLE")
    artifact = parsed.get("artifact") if isinstance(parsed, dict) else None
    expected = artifact.get("archive_sha256") if isinstance(artifact, dict) else None
    if (
        not isinstance(expected, str)
        or len(expected) != 64
        or any(character not in "0123456789abcdef" for character in expected)
    ):
        raise _artifact_error("HASH_UNAVAILABLE")
    return expected


def _relative_archive_parts(artifact_root: Optional[Path], raw_path: Any) -> Tuple[str, ...]:
    if artifact_root is None:
        raise _artifact_error("ROOT_NOT_CONFIGURED")
    if not isinstance(raw_path, str) or not raw_path:
        raise _artifact_error("NO_ARCHIVE")
    if "\x00" in raw_path:
        raise _artifact_error("INVALID_PATH")
    try:
        supplied = Path(raw_path)
    except (TypeError, ValueError):
        raise _artifact_error("INVALID_PATH")
    if not supplied.is_absolute():
        raise _artifact_error("INVALID_PATH")
    if ".." in supplied.parts:
        raise _artifact_error("PATH_TRAVERSAL")
    try:
        relative = supplied.relative_to(artifact_root)
    except ValueError:
        raise _artifact_error("OUTSIDE_ARTIFACT_ROOT")
    if not relative.parts:
        raise _artifact_error("NOT_REGULAR_FILE")
    if Path(relative.parts[-1]).suffix.lower() != ".zip":
        raise _artifact_error("NOT_ZIP")
    return relative.parts


def _read_artifact_zip(
    artifact_root: Optional[Path],
    artifact_root_fd: Optional[int],
    raw_path: Any,
    raw_metrics: Any,
) -> bytes:
    parts = _relative_archive_parts(artifact_root, raw_path)
    if artifact_root_fd is None:
        raise _artifact_error("ROOT_NOT_CONFIGURED")
    expected_sha256 = _archive_sha256(raw_metrics)
    try:
        directory_fd = os.dup(artifact_root_fd)
    except OSError:
        raise _artifact_error("UNREADABLE")
    file_fd: Optional[int] = None
    try:
        directory_flags = os.O_RDONLY
        if hasattr(os, "O_DIRECTORY"):
            directory_flags |= os.O_DIRECTORY
        if hasattr(os, "O_NOFOLLOW"):
            directory_flags |= os.O_NOFOLLOW
        for part in parts[:-1]:
            try:
                inspected = os.stat(part, dir_fd=directory_fd, follow_symlinks=False)
            except FileNotFoundError:
                raise _artifact_error("MISSING")
            except OSError:
                raise _artifact_error("UNREADABLE")
            if stat.S_ISLNK(inspected.st_mode):
                raise _artifact_error("SYMLINK_NOT_ALLOWED")
            if not stat.S_ISDIR(inspected.st_mode):
                raise _artifact_error("NOT_REGULAR_FILE")
            try:
                next_fd = os.open(part, directory_flags, dir_fd=directory_fd)
            except FileNotFoundError:
                raise _artifact_error("MISSING")
            except OSError:
                raise _artifact_error("UNREADABLE")
            previous_fd = directory_fd
            directory_fd = next_fd
            os.close(previous_fd)

        leaf = parts[-1]
        try:
            inspected = os.stat(leaf, dir_fd=directory_fd, follow_symlinks=False)
        except FileNotFoundError:
            raise _artifact_error("MISSING")
        except OSError:
            raise _artifact_error("UNREADABLE")
        if stat.S_ISLNK(inspected.st_mode):
            raise _artifact_error("SYMLINK_NOT_ALLOWED")
        if not stat.S_ISREG(inspected.st_mode):
            raise _artifact_error("NOT_REGULAR_FILE")
        file_flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            file_flags |= os.O_NOFOLLOW
        if hasattr(os, "O_NONBLOCK"):
            file_flags |= os.O_NONBLOCK
        try:
            file_fd = os.open(leaf, file_flags, dir_fd=directory_fd)
        except FileNotFoundError:
            raise _artifact_error("MISSING")
        except OSError:
            raise _artifact_error("UNREADABLE")
        actual = os.fstat(file_fd)
        if not stat.S_ISREG(actual.st_mode):
            raise _artifact_error("NOT_REGULAR_FILE")
        if actual.st_size > MAX_DOWNLOAD_BYTES:
            raise _artifact_error("TOO_LARGE")
        with os.fdopen(file_fd, "rb") as stream:
            file_fd = None
            data = stream.read(MAX_DOWNLOAD_BYTES + 1)
        if len(data) > MAX_DOWNLOAD_BYTES:
            raise _artifact_error("TOO_LARGE")
        if not zipfile.is_zipfile(io.BytesIO(data)):
            raise _artifact_error("NOT_ZIP")
        if not hmac.compare_digest(hashlib.sha256(data).hexdigest(), expected_sha256):
            raise _artifact_error("HASH_MISMATCH")
        return data
    except ArtifactUnavailableError:
        raise
    except OSError:
        raise _artifact_error("UNREADABLE")
    finally:
        if file_fd is not None:
            try:
                os.close(file_fd)
            except OSError:
                pass
        try:
            os.close(directory_fd)
        except OSError:
            pass


def _profile_rows(connection: sqlite3.Connection) -> List[Dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT id, name, is_default
        FROM research_profiles
        ORDER BY is_default DESC, name COLLATE NOCASE, id
        """
    ).fetchall()
    return [
        {"id": row["id"], "name": row["name"], "is_default": bool(row["is_default"])}
        for row in rows
    ]


def _select_profile(
    profiles: List[Dict[str, Any]],
    requested_profile_id: Optional[str],
    *,
    require_unambiguous: bool,
) -> Optional[Dict[str, Any]]:
    if requested_profile_id is not None:
        for profile in profiles:
            if profile["id"] == requested_profile_id:
                return profile
        raise ProfileNotFoundError(
            f"research profile {requested_profile_id!r} was not found"
        )
    if not profiles:
        return None
    default_profiles = [profile for profile in profiles if profile["is_default"]]
    if len(default_profiles) == 1:
        return default_profiles[0]
    if len(profiles) == 1:
        return profiles[0]
    if require_unambiguous:
        raise ProfileRequiredError(
            "profile_id is required when multiple profiles have no default"
        )
    return None


def _finite_float(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise StrategyLibraryError(f"database returned a non-numeric {label}")
    number = float(value)
    if not math.isfinite(number):
        raise StrategyLibraryError(f"database returned a non-finite {label}")
    return number


def _optional_finite_float(value: Any, label: str) -> Optional[float]:
    return None if value is None else _finite_float(value, label)


def _optional_nonnegative_int(value: Any, label: str) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise StrategyLibraryError(f"database returned an invalid {label}")
    return value


def _metrics_counts(raw_metrics: Any) -> Dict[str, Optional[int]]:
    try:
        parsed = json.loads(raw_metrics)
    except (TypeError, json.JSONDecodeError, RecursionError) as exc:
        raise StrategyLibraryError("database returned invalid execution metrics") from exc
    if not isinstance(parsed, dict):
        return {"wins": None, "draws": None, "losses": None}
    return {
        key: _optional_nonnegative_int(parsed.get(key), f"{key} metric")
        for key in ("wins", "draws", "losses")
    }


def _card_from_row(row: sqlite3.Row) -> Dict[str, Any]:
    latest_status = None
    if row["latest_status_run_id"] is not None:
        latest_status = {
            "research_run_id": row["latest_status_run_id"],
            "status": row["latest_status"],
            "stage": row["latest_status_stage"],
            "verdict": row["latest_status_verdict"],
            "created_at": row["latest_status_created_at"],
            "started_at": row["latest_status_started_at"],
            "finished_at": row["latest_status_finished_at"],
        }

    latest_summary = None
    if row["latest_summary_run_id"] is not None:
        profit_factor = _finite_float(
            row["holdout_profit_factor"], "holdout profit_factor"
        )
        losses = int(row["holdout_losses"])
        latest_summary = {
            "research_run_id": row["latest_summary_run_id"],
            "verdict": row["latest_summary_verdict"],
            "finished_at": row["latest_summary_finished_at"],
            "development_profit_pct": _finite_float(
                row["development_profit_pct"], "development profit_pct"
            ),
            "holdout_profit_pct": _finite_float(
                row["holdout_profit_pct"], "holdout profit pct"
            ),
            "holdout_max_drawdown_pct": _finite_float(
                row["holdout_max_drawdown_pct"], "holdout max drawdown pct"
            ),
            "holdout_profit_factor": profit_factor,
            "holdout_total_trades": int(row["holdout_total_trades"]),
            "holdout_losses": losses,
            "stress_profit_pct": _finite_float(
                row["stress_profit_pct"], "stress profit pct"
            ),
            "profit_factor_interpretation": (
                "NO_LOSS_SAMPLE"
                if profit_factor == 0.0 and losses == 0
                else "NUMERIC"
            ),
            "has_release": bool(row["has_release"]),
        }

    if latest_summary is not None:
        summary_state = "COMPLETE"
    elif latest_status is None:
        summary_state = "NO_COMPLETE_RESULT"
    else:
        summary_state = "INCOMPLETE_DATA"
    return {
        "candidate": {
            "id": row["candidate_id"],
            "display_name": row["display_name"],
            "class_name": row["class_name"],
            "timeframe": row["timeframe"],
            "strategy_family": row["strategy_family"],
        },
        "latest_status": latest_status,
        "latest_summary": latest_summary,
        "completed_count": int(row["completed_count"]),
        "passed_count": int(row["passed_count"]),
        "summary_state": summary_state,
    }


def _query_cards(
    connection: sqlite3.Connection, profile_id: str
) -> List[Dict[str, Any]]:
    rows = connection.execute(
        STRATEGY_LIBRARY_SQL,
        {"profile_id": profile_id},
    ).fetchall()
    return [_card_from_row(row) for row in rows]


def validate_strategy_library_database(database: PathLike) -> Path:
    """Fail before listening if the database cannot serve the read model."""
    path = _resolve_database_path(database)
    with closing(_open_read_only_database(path)) as connection:
        try:
            connection.execute("BEGIN")
            _profile_rows(connection)
            _query_cards(connection, "__schema_validation__")
            connection.rollback()
        except (sqlite3.Error, StrategyLibraryError) as exc:
            if connection.in_transaction:
                connection.rollback()
            if isinstance(exc, StrategyLibraryError):
                raise
            raise StrategyLibraryError(
                f"database cannot serve the strategy library: {exc}"
            ) from exc
    return path


def load_strategy_library(
    database: PathLike,
    profile_id: Optional[str] = None,
    *,
    require_unambiguous_profile: bool = False,
) -> Dict[str, Any]:
    """Return one profile-scoped, JSON-safe strategy-library read model."""
    with closing(_open_read_only_database(database)) as connection:
        try:
            connection.execute("BEGIN")
            profiles = _profile_rows(connection)
            selected = _select_profile(
                profiles,
                profile_id,
                require_unambiguous=require_unambiguous_profile,
            )
            strategies = _query_cards(connection, selected["id"]) if selected else []
            connection.rollback()
        except (sqlite3.Error, StrategyLibraryError) as exc:
            if connection.in_transaction:
                connection.rollback()
            if isinstance(exc, StrategyLibraryError):
                raise
            raise StrategyLibraryError(f"strategy library query failed: {exc}") from exc
    return {
        "profile": selected,
        "profiles": profiles,
        "strategies": strategies,
    }


def _download_model(
    execution_id: str,
    raw_path: Any,
    raw_metrics: Any,
    artifact_root: Optional[Path],
    artifact_root_fd: Optional[int],
) -> Dict[str, Any]:
    try:
        _read_artifact_zip(
            artifact_root,
            artifact_root_fd,
            raw_path,
            raw_metrics,
        )
    except ArtifactUnavailableError as exc:
        return {
            "available": False,
            "reason": exc.reason,
            "message": str(exc),
            "url": None,
        }
    return {
        "available": True,
        "reason": None,
        "message": "证据 ZIP 可下载",
        "url": "/download?" + urlencode({"execution_id": execution_id}),
    }


def _scenario_model(
    row: Optional[sqlite3.Row],
    scenario: str,
    artifact_root: Optional[Path],
    artifact_root_fd: Optional[int],
    frequi_config: FreqUIConfig,
    frequi_probe: Mapping[str, Any],
    candidate_class_name: str,
) -> Dict[str, Any]:
    if row is None:
        return {
            "scenario": scenario,
            "execution_id": None,
            "status": "MISSING",
            "sequence": None,
            "timerange_start": None,
            "timerange_end": None,
            "timeframe": None,
            "detail_timeframe": None,
            "fee_rate": None,
            "fee_multiplier": None,
            "total_trades": None,
            "profit_pct": None,
            "max_drawdown_pct": None,
            "win_rate": None,
            "profit_factor": None,
            "profit_factor_interpretation": "UNKNOWN",
            "sharpe": None,
            "sortino": None,
            "calmar": None,
            "long_profit_pct": None,
            "short_profit_pct": None,
            "wins": None,
            "draws": None,
            "losses": None,
            "scenario_passed": None,
            "error_message": None,
            "download": {
                "available": False,
                "reason": "NO_EXECUTION",
                "message": "此 Run 没有该场景 execution",
                "url": None,
            },
            "frequi": no_execution_frequi(frequi_probe),
        }
    counts = _metrics_counts(row["metrics_json"])
    profit_factor = _optional_finite_float(
        row["profit_factor"], f"{scenario} profit factor"
    )
    if profit_factor is None:
        profit_factor_interpretation = "UNKNOWN"
    elif profit_factor == 0.0 and counts["losses"] == 0:
        profit_factor_interpretation = "NO_LOSS_SAMPLE"
    else:
        profit_factor_interpretation = "NUMERIC"
    scenario_passed = row["scenario_passed"]
    if scenario_passed not in (None, 0, 1):
        raise StrategyLibraryError("database returned invalid scenario_passed")
    download = _download_model(
        row["id"],
        row["result_archive_path"],
        row["metrics_json"],
        artifact_root,
        artifact_root_fd,
    )
    return {
        "scenario": scenario,
        "execution_id": row["id"],
        "status": row["status"],
        "sequence": int(row["sequence"]),
        "timerange_start": row["timerange_start"],
        "timerange_end": row["timerange_end"],
        "timeframe": row["timeframe"],
        "detail_timeframe": row["detail_timeframe"],
        "fee_rate": _finite_float(row["fee_rate"], f"{scenario} fee rate"),
        "fee_multiplier": _finite_float(
            row["fee_multiplier"], f"{scenario} fee multiplier"
        ),
        "total_trades": _optional_nonnegative_int(
            row["total_trades"], f"{scenario} total trades"
        ),
        "profit_pct": _optional_finite_float(
            row["profit_pct"], f"{scenario} profit pct"
        ),
        "max_drawdown_pct": _optional_finite_float(
            row["max_drawdown_pct"], f"{scenario} max drawdown pct"
        ),
        "win_rate": _optional_finite_float(
            row["win_rate"], f"{scenario} win rate"
        ),
        "profit_factor": profit_factor,
        "profit_factor_interpretation": profit_factor_interpretation,
        "sharpe": _optional_finite_float(row["sharpe"], f"{scenario} sharpe"),
        "sortino": _optional_finite_float(row["sortino"], f"{scenario} sortino"),
        "calmar": _optional_finite_float(row["calmar"], f"{scenario} calmar"),
        "long_profit_pct": _optional_finite_float(
            row["long_profit_pct"], f"{scenario} long profit pct"
        ),
        "short_profit_pct": _optional_finite_float(
            row["short_profit_pct"], f"{scenario} short profit pct"
        ),
        "wins": counts["wins"],
        "draws": counts["draws"],
        "losses": counts["losses"],
        "scenario_passed": scenario_passed,
        "error_message": row["error_message"],
        "download": download,
        "frequi": scenario_frequi_status(
            frequi_config,
            frequi_probe,
            raw_archive_path=row["result_archive_path"],
            raw_metrics=row["metrics_json"],
            candidate_class_name=candidate_class_name,
            canonical_artifact_available=bool(download["available"]),
        ),
    }


def _history_model(row: sqlite3.Row, selected_run_id: str) -> Dict[str, Any]:
    scenario_statuses = {
        scenario: row[f"{scenario.lower()}_status"]
        for scenario in REQUIRED_SCENARIOS
    }
    present = sum(status is not None for status in scenario_statuses.values())
    succeeded = sum(status == "SUCCEEDED" for status in scenario_statuses.values())
    if row["status"] == "COMPLETED" and succeeded == len(REQUIRED_SCENARIOS):
        evidence_state = "THREE_SCENARIOS_SUCCEEDED"
    elif present == 0:
        evidence_state = "NO_SCENARIOS"
    else:
        evidence_state = "INCOMPLETE"
    return {
        "research_run_id": row["id"],
        "selected": row["id"] == selected_run_id,
        "status": row["status"],
        "stage": row["stage"],
        "verdict": row["verdict"],
        "trigger_type": row["trigger_type"],
        "created_at": row["created_at"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "error_stage": row["error_stage"],
        "error_message": row["error_message"],
        "scenario_statuses": scenario_statuses,
        "scenario_count": present,
        "succeeded_count": succeeded,
        "evidence_state": evidence_state,
    }


def load_research_run_detail(
    database: PathLike,
    profile_id: str,
    candidate_id: str,
    research_run_id: str,
    *,
    artifact_root: Optional[Path] = None,
    artifact_root_fd: Optional[int] = None,
    frequi_config: Optional[FreqUIConfig] = None,
    frequi_probe: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Load one exact profile/candidate/run snapshot and its candidate history."""
    selected_frequi_config = frequi_config or unconfigured_frequi()
    selected_frequi_probe = dict(
        frequi_probe
        if frequi_probe is not None
        else probe_frequi(selected_frequi_config)
    )
    with closing(_open_read_only_database(database)) as connection:
        try:
            connection.execute("BEGIN")
            selected = connection.execute(
                """
                SELECT
                    p.id AS profile_id,
                    p.name AS profile_name,
                    c.id AS candidate_id,
                    c.display_name,
                    c.class_name,
                    c.timeframe AS candidate_timeframe,
                    c.strategy_family,
                    r.id AS research_run_id,
                    r.trigger_type,
                    r.status,
                    r.stage,
                    r.verdict,
                    r.pipeline_version,
                    r.freqtrade_version,
                    r.error_stage,
                    r.error_message,
                    r.created_at,
                    r.started_at,
                    r.finished_at
                FROM research_profiles AS p
                JOIN generation_runs AS g ON g.research_profile_id = p.id
                JOIN candidates AS c ON c.generation_run_id = g.id
                JOIN research_runs AS r
                  ON r.candidate_id = c.id
                 AND r.research_profile_id = p.id
                WHERE p.id = ? AND c.id = ? AND r.id = ?
                """,
                (profile_id, candidate_id, research_run_id),
            ).fetchone()
            if selected is None:
                raise ResearchRunNotFoundError(
                    "research profile, candidate, and run do not match"
                )
            execution_rows = connection.execute(
                """
                SELECT
                    id, scenario, status, sequence,
                    timerange_start, timerange_end, timeframe, detail_timeframe,
                    fee_rate, fee_multiplier, result_archive_path,
                    total_trades, profit_pct, max_drawdown_pct, win_rate,
                    profit_factor, sharpe, sortino, calmar,
                    long_profit_pct, short_profit_pct, metrics_json,
                    scenario_passed, error_message
                FROM backtest_executions
                WHERE research_run_id = ?
                  AND scenario IN ('DEVELOPMENT', 'HOLDOUT', 'HOLDOUT_STRESS')
                ORDER BY sequence, id
                """,
                (research_run_id,),
            ).fetchall()
            execution_by_scenario = {row["scenario"]: row for row in execution_rows}
            scenarios = [
                _scenario_model(
                    execution_by_scenario.get(scenario),
                    scenario,
                    artifact_root,
                    artifact_root_fd,
                    selected_frequi_config,
                    selected_frequi_probe,
                    selected["class_name"],
                )
                for scenario in REQUIRED_SCENARIOS
            ]
            history_rows = connection.execute(
                """
                SELECT
                    r.id, r.trigger_type, r.status, r.stage, r.verdict,
                    r.error_stage, r.error_message,
                    r.created_at, r.started_at, r.finished_at,
                    MAX(CASE WHEN e.scenario = 'DEVELOPMENT' THEN e.status END)
                        AS development_status,
                    MAX(CASE WHEN e.scenario = 'HOLDOUT' THEN e.status END)
                        AS holdout_status,
                    MAX(CASE WHEN e.scenario = 'HOLDOUT_STRESS' THEN e.status END)
                        AS holdout_stress_status
                FROM research_runs AS r
                LEFT JOIN backtest_executions AS e
                  ON e.research_run_id = r.id
                 AND e.scenario IN ('DEVELOPMENT', 'HOLDOUT', 'HOLDOUT_STRESS')
                WHERE r.candidate_id = ? AND r.research_profile_id = ?
                GROUP BY r.id
                ORDER BY r.created_at DESC, r.id DESC
                """,
                (candidate_id, profile_id),
            ).fetchall()
            connection.rollback()
        except (sqlite3.Error, StrategyLibraryError) as exc:
            if connection.in_transaction:
                connection.rollback()
            if isinstance(exc, StrategyLibraryError):
                raise
            raise StrategyLibraryError(f"strategy detail query failed: {exc}") from exc

    selected_run = {
        "research_run_id": selected["research_run_id"],
        "trigger_type": selected["trigger_type"],
        "status": selected["status"],
        "stage": selected["stage"],
        "verdict": selected["verdict"],
        "pipeline_version": selected["pipeline_version"],
        "freqtrade_version": selected["freqtrade_version"],
        "error_stage": selected["error_stage"],
        "error_message": selected["error_message"],
        "created_at": selected["created_at"],
        "started_at": selected["started_at"],
        "finished_at": selected["finished_at"],
        "scenario_count": sum(item["execution_id"] is not None for item in scenarios),
        "succeeded_count": sum(item["status"] == "SUCCEEDED" for item in scenarios),
    }
    return {
        "profile": {"id": selected["profile_id"], "name": selected["profile_name"]},
        "candidate": {
            "id": selected["candidate_id"],
            "display_name": selected["display_name"],
            "class_name": selected["class_name"],
            "timeframe": selected["candidate_timeframe"],
            "strategy_family": selected["strategy_family"],
        },
        "selected_run": selected_run,
        "frequi_service": selected_frequi_probe,
        "scenarios": scenarios,
        "history": [
            _history_model(row, research_run_id) for row in history_rows
        ],
    }


def load_execution_archive(
    database: PathLike,
    execution_id: str,
    *,
    artifact_root: Optional[Path],
    artifact_root_fd: Optional[int],
) -> Tuple[bytes, str]:
    """Read one validated execution ZIP without exposing its stored path."""
    with closing(_open_read_only_database(database)) as connection:
        try:
            row = connection.execute(
                """
                SELECT e.result_archive_path, e.metrics_json
                FROM backtest_executions AS e
                JOIN research_runs AS r ON r.id = e.research_run_id
                JOIN candidates AS c ON c.id = r.candidate_id
                JOIN generation_runs AS g ON g.id = c.generation_run_id
                WHERE e.id = ?
                  AND g.research_profile_id = r.research_profile_id
                """,
                (execution_id,),
            ).fetchone()
        except sqlite3.Error as exc:
            raise StrategyLibraryError(f"execution download query failed: {exc}") from exc
    if row is None:
        raise ExecutionNotFoundError("execution was not found")
    data = _read_artifact_zip(
        artifact_root,
        artifact_root_fd,
        row["result_archive_path"],
        row["metrics_json"],
    )
    safe_token = hashlib.sha256(execution_id.encode("utf-8")).hexdigest()[:12]
    return data, f"evidence-{safe_token}.zip"


def _escape(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _format_percentage(value: float) -> str:
    return f"{value:+.2f}%"


def _status_presentation(status: Optional[Mapping[str, Any]]) -> Tuple[str, str]:
    if status is None:
        return "未研究", "neutral"
    raw_status = status["status"]
    verdict = status["verdict"]
    if raw_status == "COMPLETED":
        if verdict == "PASSED":
            return "已完成 · 通过", "positive"
        if verdict == "REJECTED":
            return "已完成 · 拒绝", "negative"
        return "已完成 · 未评审", "neutral"
    labels = {
        "PENDING": ("等待研究", "neutral"),
        "RUNNING": ("研究中", "running"),
        "FAILED": ("失败", "negative"),
        "INTERRUPTED": ("中断待确认", "warning"),
        "CANCELLED": ("已取消", "neutral"),
    }
    return labels.get(str(raw_status), ("未知状态", "warning"))


def _metric(label: str, value: str, note: str = "") -> str:
    note_html = f'<span class="metric-note">{_escape(note)}</span>' if note else ""
    return (
        '<div class="metric">'
        f'<span class="metric-label">{_escape(label)}</span>'
        f'<strong>{_escape(value)}</strong>{note_html}'
        "</div>"
    )


def _render_card(card: Mapping[str, Any], profile_id: str) -> str:
    candidate = card["candidate"]
    summary = card["latest_summary"]
    status_label, tone = _status_presentation(card["latest_status"])
    release = (
        '<span class="release-badge">Release</span>'
        if summary is not None and summary["has_release"]
        else ""
    )
    summary_context = ""
    if (
        summary is not None
        and card["latest_status"] is not None
        and card["latest_status"]["research_run_id"]
        != summary["research_run_id"]
    ):
        summary_context = (
            '<div class="summary-context">'
            "最近完整摘要（非当前 Run） · 完成于 "
            f'{_escape(summary["finished_at"])}</div>'
        )
    if summary is None:
        state_message = (
            "尚未研究"
            if card["summary_state"] == "NO_COMPLETE_RESULT"
            else "无完整结果 / 数据不完整"
        )
        metrics_html = (
            '<div class="empty-result">'
            f"{_escape(state_message)}"
            '<span>需要同一 ResearchRun 的三场景完整结果</span>'
            "</div>"
        )
    else:
        if summary["profit_factor_interpretation"] == "NO_LOSS_SAMPLE":
            profit_factor = _metric(
                "Holdout PF",
                "无亏损样本",
                "不可直接解释",
            )
        else:
            profit_factor = _metric(
                "Holdout PF", f"{summary['holdout_profit_factor']:.2f}"
            )
        metrics_html = (
            '<div class="metrics">'
            + _metric(
                "Holdout 收益",
                _format_percentage(summary["holdout_profit_pct"]),
            )
            + _metric(
                "Holdout 回撤",
                f"{summary['holdout_max_drawdown_pct']:.2f}%",
            )
            + profit_factor
            + _metric("Holdout 交易", str(summary["holdout_total_trades"]))
            + _metric(
                "Development 收益",
                _format_percentage(summary["development_profit_pct"]),
            )
            + _metric(
                "Stress 收益",
                _format_percentage(summary["stress_profit_pct"]),
            )
            + "</div>"
        )
    family = (
        f'<span class="family">{_escape(candidate["strategy_family"])}</span>'
        if candidate["strategy_family"]
        else ""
    )
    detail_source = summary if summary is not None else card["latest_status"]
    detail_link = ""
    if detail_source is not None:
        detail_query = urlencode(
            {
                "profile_id": profile_id,
                "candidate_id": candidate["id"],
                "research_run_id": detail_source["research_run_id"],
            }
        )
        detail_link = (
            f'<a class="detail-link" href="/strategy?{_escape(detail_query)}">'
            "查看详情与历史</a>"
        )
    return (
        '<article class="strategy-card">'
        '<div class="card-heading">'
        '<div class="identity">'
        f'<h2>{_escape(candidate["display_name"])}</h2>'
        f'<p>{_escape(candidate["class_name"])} · {_escape(candidate["timeframe"])}</p>'
        "</div>"
        '<div class="badges">'
        f"{family}{release}"
        f'<span class="status {tone}">{_escape(status_label)}</span>'
        "</div></div>"
        f"{summary_context}"
        f"{metrics_html}"
        '<div class="counts">'
        f"{detail_link}"
        f'<span>完成 <strong>{int(card["completed_count"])}</strong></span>'
        f'<span>通过 <strong>{int(card["passed_count"])}</strong></span>'
        "</div>"
        "</article>"
    )


def render_strategy_library_page(model: Mapping[str, Any]) -> bytes:
    """Render the profile-scoped list without client-side state."""
    profiles = model["profiles"]
    selected = model["profile"]
    selected_id = selected["id"] if selected else None
    options = ['<option value="">请选择 Research Profile</option>']
    for profile in profiles:
        is_selected = " selected" if profile["id"] == selected_id else ""
        suffix = " · 默认" if profile["is_default"] else ""
        options.append(
            f'<option value="{_escape(profile["id"])}"{is_selected}>'
            f'{_escape(profile["name"] + suffix)}</option>'
        )
    if not profiles:
        content = (
            '<section class="page-empty"><h2>还没有 Research Profile</h2>'
            '<p>先初始化并导入研究数据；页面不会写入业务记录。</p></section>'
        )
    elif selected is None:
        content = (
            '<section class="page-empty"><h2>请选择 Research Profile</h2>'
            '<p>存在多个 Profile 且没有默认项，策略状态和计数不会跨 Profile 混合。</p></section>'
        )
    elif not model["strategies"]:
        content = (
            '<section class="page-empty"><h2>此 Profile 尚无 Candidate</h2>'
            '<p>这里只展示已经写入研究数据库的真实记录。</p></section>'
        )
    else:
        content = '<main class="card-list">' + "".join(
            _render_card(card, selected_id) for card in model["strategies"]
        ) + "</main>"
    profile_form = ""
    if profiles:
        profile_form = (
            '<form class="profile-form" method="get" action="/">'
            '<label for="profile_id">Research Profile</label>'
            '<select id="profile_id" name="profile_id">'
            + "".join(options)
            + '</select><button type="submit">查看</button></form>'
        )
    page = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>策略库 · freqtrade-lab</title>
  <style>
    :root {{ color-scheme: light; --ink:#17202a; --muted:#6b7280;
      --line:#e5e7eb; --soft:#f7f8fa; --blue:#2563eb; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; background:#fff; color:var(--ink); font:14px/1.45
      -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }}
    .shell {{ width:min(1180px,calc(100% - 32px)); margin:0 auto; padding:28px 0 48px; }}
    .topbar {{ display:flex; align-items:flex-end; justify-content:space-between;
      gap:20px; padding-bottom:18px; border-bottom:1px solid var(--line); }}
    h1 {{ margin:0; font-size:24px; letter-spacing:-.02em; }}
    .subtitle {{ margin:4px 0 0; color:var(--muted); }}
    .profile-form {{ display:flex; align-items:center; gap:8px; }}
    .profile-form label {{ color:var(--muted); font-size:12px; }}
    select,button {{ height:34px; border:1px solid #d1d5db; border-radius:7px;
      background:#fff; color:var(--ink); padding:0 10px; font:inherit; }}
    button {{ cursor:pointer; background:var(--ink); color:#fff; border-color:var(--ink); }}
    .boundary {{ margin:14px 0 18px; padding:9px 11px; border:1px solid #dbeafe;
      border-radius:7px; background:#f8fbff; color:#475569; font-size:12px; }}
    .card-list {{ display:grid; gap:10px; }}
    .strategy-card {{ border:1px solid var(--line); border-radius:10px;
      padding:16px 18px 12px; background:#fff; }}
    .card-heading {{ display:flex; justify-content:space-between; gap:16px; align-items:flex-start; }}
    .identity h2 {{ margin:0; font-size:16px; }}
    .identity p {{ margin:3px 0 0; color:var(--muted); font:12px ui-monospace,SFMono-Regular,monospace; }}
    .badges {{ display:flex; justify-content:flex-end; gap:6px; flex-wrap:wrap; }}
    .status,.family,.release-badge {{ border-radius:999px; padding:3px 8px; font-size:11px;
      white-space:nowrap; background:#f3f4f6; color:#4b5563; }}
    .status.positive {{ color:#047857; background:#ecfdf5; }}
    .status.negative {{ color:#b91c1c; background:#fef2f2; }}
    .status.running {{ color:#1d4ed8; background:#eff6ff; }}
    .status.warning {{ color:#a16207; background:#fefce8; }}
    .release-badge {{ color:#6d28d9; background:#f5f3ff; }}
    .summary-context {{ margin-top:11px; color:#92400e; font-size:11px; }}
    .metrics {{ display:grid; grid-template-columns:repeat(6,minmax(0,1fr));
      margin-top:14px; border:1px solid var(--line); border-radius:8px; overflow:hidden; }}
    .metric {{ min-height:66px; padding:10px 12px; border-right:1px solid var(--line); }}
    .metric:last-child {{ border-right:0; }}
    .metric-label,.metric-note {{ display:block; color:var(--muted); font-size:11px; }}
    .metric strong {{ display:block; margin-top:5px; font-size:15px; font-variant-numeric:tabular-nums; }}
    .metric-note {{ margin-top:1px; font-size:10px; }}
    .empty-result {{ margin-top:14px; padding:14px; border:1px dashed #d1d5db;
      border-radius:8px; color:#374151; }}
    .empty-result span {{ display:block; color:var(--muted); font-size:11px; margin-top:2px; }}
    .counts {{ display:flex; gap:18px; justify-content:flex-end; padding-top:10px;
      color:var(--muted); font-size:12px; }}
    .counts strong {{ color:var(--ink); font-variant-numeric:tabular-nums; }}
    .detail-link {{ margin-right:auto; color:var(--blue); text-decoration:none; font-weight:600; }}
    .page-empty {{ margin-top:44px; padding:42px; text-align:center; border:1px dashed #d1d5db;
      border-radius:10px; background:var(--soft); }}
    .page-empty h2 {{ margin:0; font-size:16px; }}
    .page-empty p {{ margin:7px 0 0; color:var(--muted); }}
    footer {{ margin-top:22px; color:var(--muted); font-size:11px; text-align:center; }}
    @media (max-width:900px) {{ .metrics {{ grid-template-columns:repeat(3,1fr); }}
      .metric:nth-child(3) {{ border-right:0; }} .metric {{ border-bottom:1px solid var(--line); }} }}
    @media (max-width:640px) {{ .shell {{ width:min(100% - 20px,1180px); padding-top:18px; }}
      .topbar,.card-heading {{ align-items:stretch; flex-direction:column; }}
      .profile-form {{ display:grid; grid-template-columns:1fr auto; }} .profile-form label {{ grid-column:1/-1; }}
      .metrics {{ grid-template-columns:repeat(2,1fr); }} .metric:nth-child(3) {{ border-right:1px solid var(--line); }}
      .metric:nth-child(even) {{ border-right:0; }} }}
  </style>
</head>
<body><div class="shell">
  <header class="topbar"><div><h1>策略库</h1>
    <p class="subtitle">最近可用的三场景研究摘要</p></div>{profile_form}</header>
  <div class="boundary">只读视图 · COMPLETED 只表示结果组装完整，未评审不等于通过。</div>
  {content}
  <footer>回测摘要仅为研究记录，不代表盈利、可交易性或资金安全。</footer>
</div></body></html>"""
    return page.encode("utf-8")


def _optional_number(value: Optional[float], *, digits: int = 2) -> str:
    return "UNKNOWN" if value is None else f"{value:.{digits}f}"


def _optional_percentage(value: Optional[float], *, signed: bool = True) -> str:
    if value is None:
        return "UNKNOWN"
    return f"{value:+.2f}%" if signed else f"{value:.2f}%"


def _optional_integer(value: Optional[int]) -> str:
    return "UNKNOWN" if value is None else str(value)


def _scenario_passed_label(value: Optional[int]) -> str:
    if value == 1:
        return "通过"
    if value == 0:
        return "未通过"
    return "UNKNOWN"


def _scenario_name(value: str) -> str:
    return {
        "DEVELOPMENT": "Development",
        "HOLDOUT": "Holdout",
        "HOLDOUT_STRESS": "Holdout Stress",
    }.get(value, value)


def _detail_query_string(
    profile_id: str, candidate_id: str, research_run_id: str
) -> str:
    return urlencode(
        {
            "profile_id": profile_id,
            "candidate_id": candidate_id,
            "research_run_id": research_run_id,
        }
    )


def _render_scenario_row(scenario: Mapping[str, Any]) -> str:
    if scenario["profit_factor_interpretation"] == "NO_LOSS_SAMPLE":
        profit_factor = "无亏损样本"
    else:
        profit_factor = _optional_number(scenario["profit_factor"])
    download = scenario["download"]
    if download["available"]:
        download_html = (
            f'<a href="{_escape(download["url"])}">下载 ZIP</a>'
        )
    else:
        download_html = f'<span class="unavailable">{_escape(download["message"])}</span>'
    frequi = scenario["frequi"]
    if frequi["available"]:
        frequi_html = (
            f'<a target="_blank" rel="noopener noreferrer" href="{_escape(frequi["url"])}">'
            "打开 FreqUI</a>"
        )
    else:
        frequi_html = (
            f'<span class="unavailable">FreqUI：{_escape(frequi["message"])}</span>'
        )
    return (
        "<tr>"
        f'<th scope="row">{_escape(_scenario_name(scenario["scenario"]))}</th>'
        f'<td><code>{_escape(scenario["status"])}</code></td>'
        f'<td>{_escape(_optional_percentage(scenario["profit_pct"]))}</td>'
        f'<td>{_escape(_optional_percentage(scenario["max_drawdown_pct"], signed=False))}</td>'
        f'<td>{_escape(profit_factor)}</td>'
        f'<td>{_escape(_optional_integer(scenario["total_trades"]))}</td>'
        f'<td>{_escape(_scenario_passed_label(scenario["scenario_passed"]))}</td>'
        f'<td>{download_html}<br>{frequi_html}</td>'
        "</tr>"
    )


def _evidence_item(label: str, value: Any) -> str:
    shown = "UNKNOWN" if value is None else str(value)
    return (
        '<div class="evidence-item">'
        f'<span>{_escape(label)}</span><strong>{_escape(shown)}</strong></div>'
    )


def _render_scenario_evidence(scenario: Mapping[str, Any]) -> str:
    if scenario["profit_factor_interpretation"] == "NO_LOSS_SAMPLE":
        pf_note = '<p class="caveat">PF：无亏损样本，不可直接解释。</p>'
    else:
        pf_note = ""
    timerange = (
        "UNKNOWN"
        if scenario["timerange_start"] is None or scenario["timerange_end"] is None
        else f'{scenario["timerange_start"]} → {scenario["timerange_end"]}'
    )
    if scenario["execution_id"] is None:
        configured_detail = "UNKNOWN"
    elif scenario["detail_timeframe"] is None:
        configured_detail = "未配置"
    else:
        configured_detail = scenario["detail_timeframe"]
    fee = (
        "UNKNOWN"
        if scenario["fee_rate"] is None
        else (
            f'{scenario["fee_rate"] * 100:.4f}%'
            f'（倍率 {scenario["fee_multiplier"]:.2f}x）'
        )
    )
    explicit_counts = "".join(
        _evidence_item(label, scenario[key])
        for label, key in (("Wins", "wins"), ("Draws", "draws"), ("Losses", "losses"))
        if scenario[key] is not None
    )
    items = (
        _evidence_item("Timerange", timerange)
        + _evidence_item("Timeframe", scenario["timeframe"])
        + _evidence_item("Detail timeframe", configured_detail)
        + _evidence_item("有效配置费率假设", fee)
        + _evidence_item("胜率", _optional_percentage(scenario["win_rate"], signed=False))
        + _evidence_item("Sharpe", _optional_number(scenario["sharpe"]))
        + _evidence_item("Sortino", _optional_number(scenario["sortino"]))
        + _evidence_item("Calmar", _optional_number(scenario["calmar"]))
        + _evidence_item("Long 收益", _optional_percentage(scenario["long_profit_pct"]))
        + _evidence_item("Short 收益", _optional_percentage(scenario["short_profit_pct"]))
        + explicit_counts
    )
    error = (
        f'<p class="error-note">Execution 错误：{_escape(scenario["error_message"])}</p>'
        if scenario["error_message"]
        else ""
    )
    frequi = scenario["frequi"]
    identity = ""
    if frequi["filename"] or frequi["strategy"]:
        identity = (
            '<span class="frequi-identity">'
            f'FreqUI filename：<code>{_escape(frequi["filename"] or "UNKNOWN")}</code>'
            f' · Strategy：<code>{_escape(frequi["strategy"] or "UNKNOWN")}</code>'
            "</span>"
        )
    if frequi["available"]:
        frequi_html = (
            '<div class="frequi-ready">'
            f'<a target="_blank" rel="noopener noreferrer" href="{_escape(frequi["url"])}">'
            "打开通用 FreqUI Backtest</a>"
            f'<span>{_escape(frequi["message"])}；不会自动选中当前结果；'
            "仅 ZIP/meta 可加载回测摘要；缺少本地 strategy 时 "
            "FreqUI 可能提示 Strategy not found。</span>"
            f"{identity}</div>"
        )
    else:
        frequi_html = (
            '<div class="frequi-unavailable">'
            f'FreqUI：{_escape(frequi["message"])}'
            f' <code>{_escape(frequi["reason"])}</code>{identity}</div>'
        )
    return (
        '<details class="scenario-evidence">'
        f'<summary>{_escape(_scenario_name(scenario["scenario"]))} 扩展指标</summary>'
        f'<div class="evidence-grid">{items}</div>{frequi_html}{pf_note}{error}</details>'
    )


def _render_history_row(
    item: Mapping[str, Any], profile_id: str, candidate_id: str
) -> str:
    query = _detail_query_string(profile_id, candidate_id, item["research_run_id"])
    selected = '<span class="selected">当前查看</span>' if item["selected"] else ""
    verdict = item["verdict"] if item["verdict"] is not None else "未评审"
    scenarios = " / ".join(
        f'{_scenario_name(name)}={status or "MISSING"}'
        for name, status in item["scenario_statuses"].items()
    )
    error = item["error_message"] or ""
    return (
        "<tr>"
        f'<td><a href="/strategy?{_escape(query)}">{_escape(item["created_at"])}</a>{selected}</td>'
        f'<td><code>{_escape(item["status"])}</code> · {_escape(item["stage"])}</td>'
        f'<td>{_escape(verdict)}</td>'
        f'<td>{item["succeeded_count"]}/3 成功<br><span class="small">{_escape(scenarios)}</span></td>'
        f'<td>{_escape(error)}</td>'
        "</tr>"
    )


def render_research_run_detail_page(model: Mapping[str, Any]) -> bytes:
    """Render one exact ResearchRun, fixed scenario slots, and scoped history."""
    profile = model["profile"]
    candidate = model["candidate"]
    selected_run = model["selected_run"]
    back_query = urlencode({"profile_id": profile["id"]})
    status_label, tone = _status_presentation(selected_run)
    scenario_rows = "".join(_render_scenario_row(item) for item in model["scenarios"])
    evidence = "".join(_render_scenario_evidence(item) for item in model["scenarios"])
    history = "".join(
        _render_history_row(item, profile["id"], candidate["id"])
        for item in model["history"]
    )
    run_error = ""
    if selected_run["error_stage"] or selected_run["error_message"]:
        run_error = (
            '<div class="run-error">'
            f'错误阶段：{_escape(selected_run["error_stage"] or "UNKNOWN")} · '
            f'{_escape(selected_run["error_message"] or "无错误详情")}</div>'
        )
    page = f"""<!doctype html>
<html lang="zh-CN"><head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_escape(candidate["display_name"])} · 策略详情</title>
  <style>
    :root {{ --ink:#17202a; --muted:#6b7280; --line:#e5e7eb; --soft:#f7f8fa; --blue:#2563eb; }}
    * {{ box-sizing:border-box; }} body {{ margin:0; color:var(--ink); background:#fff;
      font:14px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }}
    .shell {{ width:min(1180px,calc(100% - 32px)); margin:0 auto; padding:26px 0 48px; }}
    a {{ color:var(--blue); }} .back {{ display:inline-block; margin-bottom:16px; text-decoration:none; }}
    .heading {{ display:flex; justify-content:space-between; gap:20px; align-items:flex-start; }}
    h1 {{ margin:0; font-size:24px; overflow-wrap:anywhere; }} .subtitle {{ margin:4px 0 0; color:var(--muted); overflow-wrap:anywhere; }}
    .status {{ border-radius:999px; padding:4px 9px; font-size:11px; background:#f3f4f6; }}
    .status.positive {{ color:#047857;background:#ecfdf5; }} .status.negative {{ color:#b91c1c;background:#fef2f2; }}
    .status.running {{ color:#1d4ed8;background:#eff6ff; }} .status.warning {{ color:#a16207;background:#fefce8; }}
    .run-meta {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:8px;
      margin:18px 0; }} .meta {{ padding:10px 12px; border:1px solid var(--line); border-radius:8px; }}
    .meta span,.small {{ color:var(--muted); font-size:11px; }} .meta strong {{ display:block; margin-top:3px; overflow-wrap:anywhere; }}
    .boundary,.run-error {{ padding:10px 12px; border-radius:8px; margin:12px 0; font-size:12px; }}
    .boundary {{ color:#475569; border:1px solid #dbeafe; background:#f8fbff; }}
    .run-error {{ color:#991b1b; border:1px solid #fecaca; background:#fef2f2; }}
    h2 {{ margin:26px 0 10px; font-size:17px; }} .table-wrap {{ overflow-x:auto; border:1px solid var(--line); border-radius:9px; }}
    table {{ width:100%; border-collapse:collapse; min-width:820px; }} th,td {{ padding:10px 11px; text-align:left;
      border-bottom:1px solid var(--line); vertical-align:top; }} thead th {{ color:var(--muted); background:var(--soft); font-size:11px; }}
    tbody tr:last-child th,tbody tr:last-child td {{ border-bottom:0; }} code {{ font-size:11px; }}
    .unavailable {{ color:#92400e; font-size:11px; }} .scenario-evidence {{ border:1px solid var(--line);
      border-radius:8px; margin-top:8px; padding:10px 12px; }} summary {{ cursor:pointer; font-weight:600; }}
    .evidence-grid {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:8px; margin-top:10px; }}
    .evidence-item {{ padding:8px 9px; background:var(--soft); border-radius:6px; min-width:0; }}
    .evidence-item span {{ display:block; color:var(--muted); font-size:10px; }} .evidence-item strong {{ display:block;
      margin-top:3px; overflow-wrap:anywhere; }} .caveat,.error-note {{ margin:8px 0 0; color:#92400e; font-size:11px; }}
    .frequi-ready,.frequi-unavailable {{ display:flex; flex-wrap:wrap; gap:6px 10px; align-items:center;
      margin-top:10px; padding:9px 10px; border-radius:6px; font-size:11px; }}
    .frequi-ready {{ background:#eff6ff; color:#1e3a8a; }} .frequi-unavailable {{ background:#fffbeb; color:#92400e; }}
    .frequi-identity {{ overflow-wrap:anywhere; }}
    .selected {{ display:inline-block; margin-left:6px; padding:2px 6px; border-radius:999px; background:#eff6ff;
      color:#1d4ed8; font-size:10px; }} footer {{ margin-top:24px; color:var(--muted); font-size:11px; text-align:center; }}
    @media (max-width:700px) {{ .shell {{ width:calc(100% - 20px); padding-top:18px; }} .heading {{ flex-direction:column; }}
      .run-meta,.evidence-grid {{ grid-template-columns:repeat(2,minmax(0,1fr)); }} }}
  </style></head><body><div class="shell">
  <a class="back" href="/?{_escape(back_query)}">← 返回策略库</a>
  <div class="heading"><div><h1>{_escape(candidate["display_name"])}</h1>
    <p class="subtitle">{_escape(candidate["class_name"])} · {_escape(candidate["timeframe"])} · {_escape(profile["name"])}</p></div>
    <span class="status {tone}">{_escape(status_label)}</span></div>
  <div class="run-meta">
    <div class="meta"><span>ResearchRun</span><strong>{_escape(selected_run["research_run_id"])}</strong></div>
    <div class="meta"><span>Stage</span><strong>{_escape(selected_run["stage"])}</strong></div>
    <div class="meta"><span>三场景执行</span><strong>{selected_run["succeeded_count"]}/3 成功</strong></div>
    <div class="meta"><span>完成时间</span><strong>{_escape(selected_run["finished_at"] or "UNKNOWN")}</strong></div>
  </div>
  <div class="boundary">本页固定到链接中的同一个 ResearchRun；SUCCEEDED 只表示 Artifact 已验证落库，不代表 Judge 通过或策略盈利。FreqUI 仅打开通用 Backtest 页，需按页面提示手动选择；它读取的是独立可丢弃副本，不是冻结 Artifact 根目录。</div>
  {run_error}
  <h2>三场景结果</h2><div class="table-wrap"><table><thead><tr><th>场景</th><th>状态</th><th>收益</th>
    <th>最大回撤</th><th>PF</th><th>交易数</th><th>Scenario Judge</th><th>证据</th></tr></thead>
    <tbody>{scenario_rows}</tbody></table></div>{evidence}
  <h2>ResearchRun 历史</h2><div class="table-wrap"><table><thead><tr><th>创建时间</th><th>状态 / Stage</th>
    <th>Verdict</th><th>三场景证据</th><th>错误</th></tr></thead><tbody>{history}</tbody></table></div>
  <footer>空指标保持 UNKNOWN；回测结果不证明盈利、可交易性或资金安全。</footer>
</div></body></html>"""
    return page.encode("utf-8")


def _json_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise StrategyLibraryError(f"response cannot be encoded safely: {exc}") from exc


def _profile_query(query: str) -> Optional[str]:
    if not query:
        return None
    try:
        values = parse_qs(query, keep_blank_values=True, strict_parsing=True)
    except ValueError as exc:
        raise BadRequestError("query string is malformed") from exc
    if set(values) - {"profile_id"}:
        raise BadRequestError("only profile_id is supported")
    selected = values.get("profile_id")
    if selected is None:
        return None
    if len(selected) != 1 or not selected[0]:
        raise BadRequestError("profile_id must appear exactly once and be non-empty")
    return selected[0]


def _required_query(query: str, names: Tuple[str, ...]) -> Dict[str, str]:
    if not query:
        raise BadRequestError("required query parameters are missing")
    try:
        values = parse_qs(query, keep_blank_values=True, strict_parsing=True)
    except ValueError as exc:
        raise BadRequestError("query string is malformed") from exc
    if set(values) != set(names):
        raise BadRequestError("query parameters do not match the route contract")
    result: Dict[str, str] = {}
    for name in names:
        entries = values[name]
        if len(entries) != 1 or not entries[0]:
            raise BadRequestError(f"{name} must appear exactly once and be non-empty")
        if len(entries[0]) > 256 or "\x00" in entries[0]:
            raise BadRequestError(f"{name} is too long or invalid")
        result[name] = entries[0]
    return result


def _detail_query(query: str) -> Dict[str, str]:
    return _required_query(
        query,
        ("profile_id", "candidate_id", "research_run_id"),
    )


def _execution_query(query: str) -> str:
    return _required_query(query, ("execution_id",))["execution_id"]


class StrategyLibraryRequestHandler(BaseHTTPRequestHandler):
    """A fixed-route handler whose database is supplied by ``create_server``."""

    server_version = "freqtrade-lab"
    sys_version = ""
    database_path: Path
    artifact_root: Optional[Path]
    frequi_config: FreqUIConfig

    def _has_expected_host(self) -> bool:
        expected = f"{LOOPBACK_HOST}:{self.server.server_port}"
        return self.headers.get_all("Host", failobj=[]) == [expected]

    def _send(
        self,
        status: int,
        body: bytes,
        content_type: str,
        *,
        head_only: bool = False,
        extra_headers: Optional[Mapping[str, str]] = None,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; style-src 'unsafe-inline'; "
            "form-action 'self'; frame-ancestors 'none'",
        )
        for name, value in (extra_headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        if not head_only:
            self.wfile.write(body)

    def _error(
        self,
        status: int,
        code: str,
        message: str,
        *,
        api: bool,
        head_only: bool,
    ) -> None:
        if api:
            body = _json_bytes({"error": code, "message": message})
            content_type = "application/json; charset=utf-8"
        else:
            body = (
                "<!doctype html><html lang=\"zh-CN\"><meta charset=\"utf-8\">"
                f"<title>{status}</title><h1>{status}</h1><p>{_escape(message)}</p>"
                "</html>"
            ).encode("utf-8")
            content_type = "text/html; charset=utf-8"
        self._send(status, body, content_type, head_only=head_only)

    def _dispatch(self, *, head_only: bool) -> None:
        request = urlsplit(self.path)
        api = request.path in ("/api/strategies", "/api/strategy")
        if not self._has_expected_host():
            self._error(
                400,
                "bad_host",
                "Host 必须使用服务启动时打印的 loopback 地址",
                api=api,
                head_only=head_only,
            )
            return
        if request.path not in (
            "/",
            "/api/strategies",
            "/strategy",
            "/api/strategy",
            "/download",
        ):
            self._error(404, "not_found", "页面不存在", api=api, head_only=head_only)
            return
        try:
            if request.path in ("/", "/api/strategies"):
                profile_id = _profile_query(request.query)
                model = load_strategy_library(
                    self.database_path,
                    profile_id,
                    require_unambiguous_profile=api,
                )
                if api:
                    body = _json_bytes(model)
                    content_type = "application/json; charset=utf-8"
                else:
                    body = render_strategy_library_page(model)
                    content_type = "text/html; charset=utf-8"
                self._send(200, body, content_type, head_only=head_only)
                return
            if request.path in ("/strategy", "/api/strategy"):
                identifiers = _detail_query(request.query)
                frequi_probe = probe_frequi(self.frequi_config)
                model = load_research_run_detail(
                    self.database_path,
                    identifiers["profile_id"],
                    identifiers["candidate_id"],
                    identifiers["research_run_id"],
                    artifact_root=self.artifact_root,
                    artifact_root_fd=getattr(self.server, "artifact_root_fd", None),
                    frequi_config=self.frequi_config,
                    frequi_probe=frequi_probe,
                )
                if api:
                    body = _json_bytes(model)
                    content_type = "application/json; charset=utf-8"
                else:
                    body = render_research_run_detail_page(model)
                    content_type = "text/html; charset=utf-8"
                self._send(200, body, content_type, head_only=head_only)
                return
            execution_id = _execution_query(request.query)
            body, filename = load_execution_archive(
                self.database_path,
                execution_id,
                artifact_root=self.artifact_root,
                artifact_root_fd=getattr(self.server, "artifact_root_fd", None),
            )
            self._send(
                200,
                body,
                "application/zip",
                head_only=head_only,
                extra_headers={
                    "Content-Disposition": f'attachment; filename="{filename}"'
                },
            )
        except BadRequestError as exc:
            self._error(400, "bad_request", str(exc), api=api, head_only=head_only)
        except ProfileNotFoundError as exc:
            self._error(404, "profile_not_found", str(exc), api=api, head_only=head_only)
        except ProfileRequiredError as exc:
            self._error(409, "profile_required", str(exc), api=api, head_only=head_only)
        except ResearchRunNotFoundError:
            self._error(
                404,
                "research_run_not_found",
                "指定的 Profile、Candidate 与 ResearchRun 不匹配",
                api=api,
                head_only=head_only,
            )
        except ExecutionNotFoundError:
            self._error(
                404,
                "execution_not_found",
                "Execution 不存在",
                api=False,
                head_only=head_only,
            )
        except ArtifactUnavailableError as exc:
            self._error(
                404,
                "artifact_unavailable",
                str(exc),
                api=False,
                head_only=head_only,
            )
        except StrategyLibraryError:
            self._error(
                500,
                "read_failed",
                "策略库暂时无法读取数据库",
                api=api,
                head_only=head_only,
            )

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        self._dispatch(head_only=False)

    def do_HEAD(self) -> None:  # noqa: N802 - stdlib handler API
        self._dispatch(head_only=True)

    def _method_not_allowed(self) -> None:
        api = urlsplit(self.path).path in ("/api/strategies", "/api/strategy")
        if not self._has_expected_host():
            self._error(
                400,
                "bad_host",
                "Host 必须使用服务启动时打印的 loopback 地址",
                api=api,
                head_only=False,
            )
            return
        body = _json_bytes({"error": "method_not_allowed"}) if api else b"Method not allowed"
        self._send(
            405,
            body,
            "application/json; charset=utf-8" if api else "text/plain; charset=utf-8",
            extra_headers={"Allow": "GET, HEAD"},
        )

    do_POST = _method_not_allowed
    do_PUT = _method_not_allowed
    do_PATCH = _method_not_allowed
    do_DELETE = _method_not_allowed


class StrategyLibraryHTTPServer(HTTPServer):
    """HTTPServer that owns the configured artifact-root descriptor."""

    artifact_root_fd: Optional[int] = None

    def server_close(self) -> None:
        try:
            super().server_close()
        finally:
            if self.artifact_root_fd is not None:
                os.close(self.artifact_root_fd)
                self.artifact_root_fd = None


def create_strategy_library_server(
    database: PathLike,
    port: int = DEFAULT_PORT,
    artifact_root: Optional[PathLike] = None,
    *,
    frequi_base_url: Optional[str] = None,
    frequi_results_root: Optional[PathLike] = None,
) -> HTTPServer:
    """Validate first, then create one loopback-only single-process server."""
    if isinstance(port, bool) or not isinstance(port, int) or not 0 <= port <= 65535:
        raise StrategyLibraryError("port must be an integer from 0 to 65535")
    path = validate_strategy_library_database(database)
    resolved_artifact_root = _resolve_artifact_root(artifact_root)
    try:
        resolved_frequi_config = configure_frequi(
            frequi_base_url,
            frequi_results_root,
            artifact_root=resolved_artifact_root,
        )
    except FreqUIConfigurationError as exc:
        raise StrategyLibraryError(f"unsafe FreqUI configuration: {exc}") from exc
    artifact_root_fd = (
        _open_artifact_root_fd(resolved_artifact_root)
        if resolved_artifact_root is not None
        else None
    )

    class BoundHandler(StrategyLibraryRequestHandler):
        database_path = path
        artifact_root = resolved_artifact_root
        frequi_config = resolved_frequi_config

    try:
        server = StrategyLibraryHTTPServer((LOOPBACK_HOST, port), BoundHandler)
        server.artifact_root_fd = artifact_root_fd
        return server
    except OSError as exc:
        if artifact_root_fd is not None:
            os.close(artifact_root_fd)
        raise StrategyLibraryError(f"loopback server cannot start: {exc}") from exc
