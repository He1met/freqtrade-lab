"""Optional, credential-free FreqUI readiness and artifact discovery checks.

The strategy library never authenticates to Freqtrade and never copies files.
It only exposes the generic ``/backtest`` page after a public loopback probe and
an exact, disposable ZIP/metadata copy can be verified locally.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple, Union
from urllib.parse import urlsplit


PathLike = Union[str, Path]
MAX_PROBE_BYTES = 256 * 1024
MAX_ARCHIVE_BYTES = 4 * 1024 * 1024
MAX_META_BYTES = 1024 * 1024
MAX_COMPLETION_RECEIPT_BYTES = 16 * 1024
SUPPORTED_FREQUI_VERSION = "3.1.1"
FREQUI_COMPLETION_RECEIPT_NAME = ".freqtrade-lab-frequi-complete.json"
FREQUI_COMPLETION_RECEIPT_SCHEMA = "freqtrade-lab-frequi-completion-v1"
FREQUI_COMPLETION_SCENARIOS = ("DEVELOPMENT", "HOLDOUT", "HOLDOUT_STRESS")
_ARCHIVE_NAME = re.compile(r"^backtest-result-.+-[0-9][0-9].*\.zip$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class FreqUIConfigurationError(ValueError):
    """Raised when the optional local FreqUI boundary is unsafe or ambiguous."""


@dataclass(frozen=True)
class FreqUIConfig:
    base_url: Optional[str]
    results_root: Optional[Path]
    results_root_identity: Optional[Tuple[int, int]]


def unconfigured_frequi() -> FreqUIConfig:
    return FreqUIConfig(
        base_url=None,
        results_root=None,
        results_root_identity=None,
    )


def _regular_directory(path: PathLike, label: str) -> Tuple[Path, os.stat_result]:
    try:
        value = Path(path).expanduser()
        if value.is_symlink():
            raise FreqUIConfigurationError(f"{label} must not be a symlink")
        resolved = value.resolve(strict=True)
        inspected = os.lstat(resolved)
    except FreqUIConfigurationError:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise FreqUIConfigurationError(
            f"{label} cannot be resolved safely: {exc}"
        ) from exc
    if not stat.S_ISDIR(inspected.st_mode):
        raise FreqUIConfigurationError(f"{label} must be a directory")
    return resolved, inspected


def _loopback_base_url(value: str) -> str:
    if not isinstance(value, str) or not value or any(
        character.isspace() or ord(character) < 32 for character in value
    ):
        raise FreqUIConfigurationError("FreqUI base URL is invalid")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise FreqUIConfigurationError("FreqUI base URL has an invalid port") from exc
    if (
        parsed.scheme != "http"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.hostname != "127.0.0.1"
        or port is None
        or parsed.netloc != f"127.0.0.1:{port}"
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
        or not 1 <= port <= 65535
    ):
        raise FreqUIConfigurationError(
            "FreqUI base URL must be origin-only http://127.0.0.1:<port>"
        )
    return f"http://127.0.0.1:{port}"


def _identity_is_ancestor(
    identity: Tuple[int, int],
    path: Path,
) -> bool:
    """Compare filesystem identities so case aliases cannot hide containment."""
    current = path
    while True:
        inspected = os.stat(current)
        if (inspected.st_dev, inspected.st_ino) == identity:
            return True
        parent = current.parent
        if parent == current:
            return False
        current = parent


def configure_frequi(
    base_url: Optional[str],
    results_root: Optional[PathLike],
    *,
    artifact_root: Optional[Path],
) -> FreqUIConfig:
    """Freeze a loopback origin and a separate, disposable scan directory."""
    if base_url is None and results_root is None:
        return unconfigured_frequi()
    if base_url is None or results_root is None:
        raise FreqUIConfigurationError(
            "FreqUI base URL and results root must be configured together"
        )
    if artifact_root is None:
        raise FreqUIConfigurationError(
            "FreqUI integration requires the controlled artifact root"
        )
    normalized = _loopback_base_url(base_url)
    resolved_artifact, artifact_inspected = _regular_directory(
        artifact_root, "controlled artifact root"
    )
    resolved_results, inspected = _regular_directory(
        results_root, "FreqUI results root"
    )
    artifact_identity = (artifact_inspected.st_dev, artifact_inspected.st_ino)
    results_identity = (inspected.st_dev, inspected.st_ino)
    try:
        overlaps = _identity_is_ancestor(
            artifact_identity, resolved_results
        ) or _identity_is_ancestor(results_identity, resolved_artifact)
    except OSError as exc:
        raise FreqUIConfigurationError(
            f"FreqUI roots cannot be compared safely: {exc}"
        ) from exc
    if overlaps:
        raise FreqUIConfigurationError(
            "FreqUI results root must be separate from the frozen artifact root"
        )
    return FreqUIConfig(
        base_url=normalized,
        results_root=resolved_results,
        results_root_identity=(inspected.st_dev, inspected.st_ino),
    )


def _strict_object(data: bytes) -> Mapping[str, Any]:
    def no_duplicates(pairs: Iterable[Tuple[str, Any]]) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def reject_constant(value: str) -> Any:
        raise ValueError(f"non-finite JSON value: {value}")

    parsed = json.loads(
        data.decode("utf-8", "strict"),
        object_pairs_hook=no_duplicates,
        parse_constant=reject_constant,
    )
    if not isinstance(parsed, dict):
        raise ValueError("JSON root must be an object")
    return parsed


def _read_http_response(
    connection: http.client.HTTPConnection,
    path: str,
    *,
    accept: str,
) -> Tuple[bytes, str]:
    connection.request(
        "GET",
        path,
        headers={"Accept": accept, "User-Agent": "freqtrade-lab"},
    )
    response = connection.getresponse()
    if response.status != 200:
        raise ValueError("unexpected HTTP status")
    declared = response.getheader("Content-Length")
    if declared is not None and int(declared) > MAX_PROBE_BYTES:
        raise ValueError("response is too large")
    data = response.read(MAX_PROBE_BYTES + 1)
    if len(data) > MAX_PROBE_BYTES:
        raise ValueError("response is too large")
    return data, response.getheader("Content-Type", "")


def _media_type(value: str) -> str:
    return value.split(";", 1)[0].strip().lower()


def _probe_failure(
    reason: str,
    message: str,
    *,
    reachable: Optional[bool],
    ui_installed: Optional[bool],
    version: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "configured": reason != "NOT_CONFIGURED",
        "reachable": reachable,
        "ui_installed": ui_installed,
        "available": False,
        "reason": reason,
        "message": message,
        "version": version,
        "url": None,
        "webserver_mode": None,
    }


def probe_frequi(config: FreqUIConfig, *, timeout: float = 0.5) -> Dict[str, Any]:
    """Probe fixed public endpoints without proxies, redirects, or credentials."""
    if config.base_url is None:
        return _probe_failure(
            "NOT_CONFIGURED",
            "未配置本机 FreqUI",
            reachable=None,
            ui_installed=None,
        )
    try:
        normalized_base_url = _loopback_base_url(config.base_url)
    except FreqUIConfigurationError:
        return _probe_failure(
            "WEBSERVER_RESPONSE_INVALID",
            "FreqUI 配置无法识别",
            reachable=None,
            ui_installed=None,
        )
    port = urlsplit(normalized_base_url).port
    if port is None:  # Defensive: configured values always contain a port.
        return _probe_failure(
            "WEBSERVER_RESPONSE_INVALID",
            "FreqUI 配置无法识别",
            reachable=None,
            ui_installed=None,
        )
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        ping_bytes, ping_type = _read_http_response(
            connection, "/api/v1/ping", accept="application/json"
        )
        if _media_type(ping_type) != "application/json":
            raise ValueError("ping is not JSON")
        if _strict_object(ping_bytes) != {"status": "pong"}:
            raise ValueError("unexpected ping")

        version_bytes, version_type = _read_http_response(
            connection, "/ui_version", accept="application/json"
        )
        if _media_type(version_type) != "application/json":
            raise ValueError("ui_version is not JSON")
        version_payload = _strict_object(version_bytes)
        version = version_payload.get("version")
        if not isinstance(version, str) or not version or len(version) > 32:
            raise ValueError("invalid FreqUI version")
        if version == "not_installed":
            return _probe_failure(
                "FREQUI_NOT_INSTALLED",
                "FreqUI 未安装或版本不可识别",
                reachable=True,
                ui_installed=False,
            )
        if version != SUPPORTED_FREQUI_VERSION:
            return _probe_failure(
                "FREQUI_VERSION_MISMATCH",
                f"FreqUI 版本必须为 {SUPPORTED_FREQUI_VERSION}",
                reachable=True,
                ui_installed=True,
                version=version,
            )

        page_bytes, page_type = _read_http_response(
            connection, "/backtest", accept="text/html"
        )
        if _media_type(page_type) != "text/html" or not page_bytes:
            return _probe_failure(
                "BACKTEST_PAGE_UNAVAILABLE",
                "FreqUI /backtest 未返回 HTML",
                reachable=True,
                ui_installed=True,
                version=version,
            )
    except (OSError, TimeoutError, http.client.HTTPException):
        return _probe_failure(
            "WEBSERVER_UNREACHABLE",
            "本机 FreqUI Webserver 不可达",
            reachable=False,
            ui_installed=None,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError):
        return _probe_failure(
            "WEBSERVER_RESPONSE_INVALID",
            "FreqUI Webserver 的公共响应不符合预期",
            reachable=True,
            ui_installed=None,
        )
    finally:
        connection.close()
    return {
        "configured": True,
        "reachable": True,
        "ui_installed": True,
        "available": True,
        "reason": None,
        "message": "FreqUI 通用 Backtest 入口可达",
        "version": version,
        "url": normalized_base_url + "/backtest",
        "webserver_mode": None,
    }


def _scenario_failure(
    reason: str,
    message: str,
    *,
    artifact_filename: Optional[str],
    strategy: Optional[str],
    version: Optional[str],
    local_copy_ready: Optional[bool] = False,
) -> Dict[str, Any]:
    return {
        "available": False,
        "local_copy_ready": local_copy_ready,
        "history_visibility": None,
        "reason": reason,
        "message": message,
        "url": None,
        "artifact_filename": artifact_filename,
        "filename": Path(artifact_filename).stem if artifact_filename else None,
        "strategy": strategy,
        "version": version,
        "selection": "MANUAL",
    }


def no_execution_frequi(probe: Mapping[str, Any]) -> Dict[str, Any]:
    version = probe.get("version")
    return _scenario_failure(
        "NO_EXECUTION",
        "此 Run 没有该场景 execution",
        artifact_filename=None,
        strategy=None,
        version=version if isinstance(version, str) else None,
    )


def _artifact_evidence(
    raw_archive_path: Any,
    raw_metrics: Any,
) -> Tuple[str, str, str, str, str]:
    if not isinstance(raw_archive_path, str) or not raw_archive_path:
        raise ValueError("archive path is missing")
    supplied = Path(raw_archive_path)
    if not supplied.is_absolute() or ".." in supplied.parts:
        raise ValueError("archive path is unsafe")
    archive_name = supplied.name
    if not _ARCHIVE_NAME.fullmatch(archive_name):
        raise ValueError("archive filename is unsupported")
    if not isinstance(raw_metrics, str):
        raise ValueError("metrics are missing")
    metrics = _strict_object(raw_metrics.encode("utf-8", "strict"))
    artifact = metrics.get("artifact")
    if not isinstance(artifact, dict):
        raise ValueError("artifact evidence is missing")
    strategy = artifact.get("strategy")
    archive_sha256 = artifact.get("archive_sha256")
    metadata_sha256 = artifact.get("metadata_sha256")
    report_member = artifact.get("report_member")
    expected_report = Path(archive_name).with_suffix(".json").name
    if (
        not isinstance(strategy, str)
        or not strategy
        or not isinstance(archive_sha256, str)
        or _SHA256.fullmatch(archive_sha256) is None
        or not isinstance(metadata_sha256, str)
        or _SHA256.fullmatch(metadata_sha256) is None
        or report_member != expected_report
    ):
        raise ValueError("artifact identity is incomplete")
    metadata_name = Path(archive_name).with_suffix(".meta.json").name
    return archive_name, metadata_name, strategy, archive_sha256, metadata_sha256


def _open_results_root(config: FreqUIConfig) -> int:
    if config.results_root is None or config.results_root_identity is None:
        raise ValueError("results root is not configured")
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(config.results_root, flags)
    try:
        inspected = os.fstat(descriptor)
    except OSError:
        os.close(descriptor)
        raise
    if (
        not stat.S_ISDIR(inspected.st_mode)
        or (inspected.st_dev, inspected.st_ino) != config.results_root_identity
    ):
        os.close(descriptor)
        raise ValueError("results root identity changed")
    return descriptor


def _read_regular_at(
    directory_fd: int,
    name: str,
    *,
    maximum: int,
) -> Tuple[bytes, os.stat_result]:
    if Path(name).name != name or not name:
        raise ValueError("unsafe filename")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    descriptor = os.open(name, flags, dir_fd=directory_fd)
    try:
        inspected = os.fstat(descriptor)
        if (
            not stat.S_ISREG(inspected.st_mode)
            or inspected.st_nlink != 1
            or inspected.st_size > maximum
        ):
            raise ValueError("file is not an independent bounded regular file")
        chunks = []
        total = 0
        while True:
            chunk = os.read(descriptor, min(64 * 1024, maximum + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > maximum:
                raise ValueError("file is too large")
        after = os.fstat(descriptor)
        if (
            after.st_dev != inspected.st_dev
            or after.st_ino != inspected.st_ino
            or after.st_size != inspected.st_size
            or after.st_mtime_ns != inspected.st_mtime_ns
        ):
            raise ValueError("file changed while reading")
        return b"".join(chunks), inspected
    finally:
        os.close(descriptor)


def _validate_completion_receipt(
    receipt: Mapping[str, Any],
) -> Dict[str, Tuple[str, str, str, str]]:
    if (
        set(receipt) != {"schema", "research_run_id", "scenarios"}
        or receipt.get("schema") != FREQUI_COMPLETION_RECEIPT_SCHEMA
        or not isinstance(receipt.get("research_run_id"), str)
        or _SAFE_RUN_ID.fullmatch(str(receipt.get("research_run_id"))) is None
    ):
        raise ValueError("completion receipt identity is invalid")
    raw_scenarios = receipt.get("scenarios")
    if not isinstance(raw_scenarios, list) or len(raw_scenarios) != 3:
        raise ValueError("completion receipt scenario set is invalid")
    validated: Dict[str, Tuple[str, str, str, str]] = {}
    filenames: set[str] = set()
    for expected_scenario, raw in zip(FREQUI_COMPLETION_SCENARIOS, raw_scenarios):
        if (
            not isinstance(raw, dict)
            or set(raw)
            != {
                "scenario",
                "archive",
                "archive_sha256",
                "metadata",
                "metadata_sha256",
            }
            or raw.get("scenario") != expected_scenario
        ):
            raise ValueError("completion receipt scenario binding is invalid")
        archive = raw.get("archive")
        metadata = raw.get("metadata")
        archive_sha256 = raw.get("archive_sha256")
        metadata_sha256 = raw.get("metadata_sha256")
        if (
            not isinstance(archive, str)
            or Path(archive).name != archive
            or _ARCHIVE_NAME.fullmatch(archive) is None
            or not isinstance(metadata, str)
            or Path(metadata).name != metadata
            or metadata != Path(archive).with_suffix(".meta.json").name
            or not isinstance(archive_sha256, str)
            or _SHA256.fullmatch(archive_sha256) is None
            or not isinstance(metadata_sha256, str)
            or _SHA256.fullmatch(metadata_sha256) is None
            or archive in filenames
            or metadata in filenames
        ):
            raise ValueError("completion receipt file binding is invalid")
        filenames.update((archive, metadata))
        validated[expected_scenario] = (
            archive,
            archive_sha256,
            metadata,
            metadata_sha256,
        )
    if len(validated) != 3 or len(filenames) != 6:
        raise ValueError("completion receipt is incomplete")
    return validated


def build_frequi_completion_receipt(
    research_run_id: str,
    scenarios: Sequence[Mapping[str, Any]],
) -> bytes:
    """Build the final one-shot visibility receipt for one exact three-scenario set."""
    receipt = {
        "schema": FREQUI_COMPLETION_RECEIPT_SCHEMA,
        "research_run_id": research_run_id,
        "scenarios": [dict(item) for item in scenarios],
    }
    _validate_completion_receipt(receipt)
    return (
        json.dumps(receipt, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("ascii")


def _validate_completed_result_set(
    root_fd: int,
    research_run_id: str,
    expected: Tuple[str, str, str, str],
) -> None:
    receipt_bytes, _ = _read_regular_at(
        root_fd,
        FREQUI_COMPLETION_RECEIPT_NAME,
        maximum=MAX_COMPLETION_RECEIPT_BYTES,
    )
    receipt = _strict_object(receipt_bytes)
    scenarios = _validate_completion_receipt(receipt)
    if receipt["research_run_id"] != research_run_id:
        raise ValueError("completion receipt belongs to a different ResearchRun")
    expected_names = {FREQUI_COMPLETION_RECEIPT_NAME}
    matched = False
    for archive, archive_sha256, metadata, metadata_sha256 in scenarios.values():
        expected_names.update((archive, metadata))
        archive_bytes, _ = _read_regular_at(
            root_fd, archive, maximum=MAX_ARCHIVE_BYTES
        )
        metadata_bytes, _ = _read_regular_at(
            root_fd, metadata, maximum=MAX_META_BYTES
        )
        if (
            hashlib.sha256(archive_bytes).hexdigest() != archive_sha256
            or hashlib.sha256(metadata_bytes).hexdigest() != metadata_sha256
        ):
            raise ValueError("completion receipt file hash drifted")
        matched = matched or expected == (
            archive,
            archive_sha256,
            metadata,
            metadata_sha256,
        )
    if not matched or set(os.listdir(root_fd)) != expected_names:
        raise ValueError("completion receipt does not bind the visible result set")


def scenario_frequi_status(
    config: FreqUIConfig,
    probe: Mapping[str, Any],
    *,
    research_run_id: str,
    raw_archive_path: Any,
    raw_metrics: Any,
    candidate_class_name: str,
    canonical_artifact_available: bool,
) -> Dict[str, Any]:
    """Verify one exact, disposable ZIP/meta copy in FreqUI's scan directory."""
    version = probe.get("version")
    safe_version = version if isinstance(version, str) else None
    try:
        (
            archive_name,
            metadata_name,
            strategy,
            expected_archive_hash,
            expected_metadata_hash,
        ) = _artifact_evidence(raw_archive_path, raw_metrics)
    except (UnicodeEncodeError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return _scenario_failure(
            "INVALID_ARTIFACT_IDENTITY",
            "Artifact 身份证据不完整",
            artifact_filename=None,
            strategy=None,
            version=safe_version,
        )
    if not probe.get("available"):
        return _scenario_failure(
            str(probe.get("reason") or "WEBSERVER_UNREACHABLE"),
            str(probe.get("message") or "FreqUI 不可用"),
            artifact_filename=archive_name,
            strategy=strategy,
            version=safe_version,
            local_copy_ready=None,
        )
    if not canonical_artifact_available:
        return _scenario_failure(
            "ARTIFACT_UNAVAILABLE",
            "冻结 Artifact 未通过下载边界校验",
            artifact_filename=archive_name,
            strategy=strategy,
            version=safe_version,
        )
    if config.results_root is None:
        return _scenario_failure(
            "NOT_CONFIGURED",
            "未配置 FreqUI backtest_results 目录",
            artifact_filename=archive_name,
            strategy=strategy,
            version=safe_version,
        )
    if strategy != candidate_class_name:
        return _scenario_failure(
            "INVALID_ARTIFACT_IDENTITY",
            "Artifact strategy 与 Candidate 不一致",
            artifact_filename=archive_name,
            strategy=strategy,
            version=safe_version,
        )
    try:
        root_fd = _open_results_root(config)
        try:
            archive_bytes, _ = _read_regular_at(
                root_fd, archive_name, maximum=MAX_ARCHIVE_BYTES
            )
            metadata_bytes, _ = _read_regular_at(
                root_fd, metadata_name, maximum=MAX_META_BYTES
            )
        finally:
            os.close(root_fd)
    except FileNotFoundError:
        return _scenario_failure(
            "RESULT_COPY_MISSING",
            "FreqUI 副本目录缺少同名 ZIP 或 .meta.json",
            artifact_filename=archive_name,
            strategy=strategy,
            version=safe_version,
        )
    except (OSError, ValueError):
        return _scenario_failure(
            "RESULT_COPY_INVALID",
            "FreqUI 副本不是独立、安全的普通文件",
            artifact_filename=archive_name,
            strategy=strategy,
            version=safe_version,
        )
    if hashlib.sha256(archive_bytes).hexdigest() != expected_archive_hash:
        return _scenario_failure(
            "RESULT_COPY_INVALID",
            "FreqUI ZIP 副本与冻结 Artifact 不一致",
            artifact_filename=archive_name,
            strategy=strategy,
            version=safe_version,
        )
    if hashlib.sha256(metadata_bytes).hexdigest() != expected_metadata_hash:
        return _scenario_failure(
            "METADATA_INVALID",
            "FreqUI metadata 副本与冻结证据不一致",
            artifact_filename=archive_name,
            strategy=strategy,
            version=safe_version,
        )
    try:
        metadata = _strict_object(metadata_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError):
        return _scenario_failure(
            "METADATA_INVALID",
            "FreqUI metadata 无法被安全识别",
            artifact_filename=archive_name,
            strategy=strategy,
            version=safe_version,
        )
    strategy_metadata = metadata.get(strategy)
    start_time = (
        strategy_metadata.get("backtest_start_time")
        if isinstance(strategy_metadata, dict)
        else None
    )
    if (
        set(metadata) != {strategy}
        or not isinstance(strategy_metadata, dict)
        or not isinstance(strategy_metadata.get("run_id"), str)
        or not strategy_metadata["run_id"]
        or isinstance(start_time, bool)
        or not isinstance(start_time, int)
    ):
        return _scenario_failure(
            "METADATA_INVALID",
            "FreqUI metadata 中找不到该 strategy 的有效历史条目",
            artifact_filename=archive_name,
            strategy=strategy,
            version=safe_version,
        )
    try:
        root_fd = _open_results_root(config)
        try:
            _validate_completed_result_set(
                root_fd,
                research_run_id,
                (
                    archive_name,
                    expected_archive_hash,
                    metadata_name,
                    expected_metadata_hash,
                ),
            )
        finally:
            os.close(root_fd)
    except FileNotFoundError:
        return _scenario_failure(
            "RESULT_SET_INCOMPLETE",
            "FreqUI 三场景副本尚未完整发布",
            artifact_filename=archive_name,
            strategy=strategy,
            version=safe_version,
        )
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        RecursionError,
        ValueError,
    ):
        return _scenario_failure(
            "RESULT_SET_INVALID",
            "FreqUI 三场景副本未通过 completion receipt 校验",
            artifact_filename=archive_name,
            strategy=strategy,
            version=safe_version,
        )
    return {
        "available": True,
        "local_copy_ready": True,
        "history_visibility": None,
        "reason": None,
        "message": "本地文件前提满足；请在 FreqUI 的 Load Results 中手动确认",
        "url": probe["url"],
        "artifact_filename": archive_name,
        "filename": Path(archive_name).stem,
        "strategy": strategy,
        "version": safe_version,
        "selection": "MANUAL",
    }
