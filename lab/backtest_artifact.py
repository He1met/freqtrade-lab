"""Import one frozen Freqtrade 2026.7 artifact into an existing execution.

This module deliberately supports only the three-member, provenance-bound format
frozen for GitHub Issue #2.  It does not run Freqtrade and it never creates rows.
"""

from __future__ import annotations

import hashlib
import hmac
import io
import json
import math
import os
import re
import sqlite3
import stat
import zipfile
import zlib
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple, Union

from lab.database import get_connection


SUPPORTED_FREQTRADE_VERSION = "2026.7"
SUPPORTED_FREQTRADE_COMMIT = "52bc96f4480b1a0da6a9b455bd00b17fbb6786a5"
SUPPORTED_PROVENANCE_SCHEMA = "freqtrade-lab-fixture-provenance-v1"
SUPPORTED_SCENARIOS = ("SMOKE", "DEVELOPMENT", "HOLDOUT", "HOLDOUT_STRESS")
SCENARIO_STAGES = {
    "SMOKE": "SMOKE_BACKTEST",
    "DEVELOPMENT": "DEVELOPMENT_BACKTEST",
    "HOLDOUT": "HOLDOUT_BACKTEST",
    "HOLDOUT_STRESS": "HOLDOUT_STRESS_BACKTEST",
}
SUPPORTED_EXCHANGE = "okx"
SUPPORTED_TRADING_MODE = "futures"
SUPPORTED_MARGIN_MODE = "isolated"
SUPPORTED_PROFILE_DOMAIN = "OKX_CRYPTO_PERP"

MAX_ARCHIVE_BYTES = 4 * 1024 * 1024
MAX_METADATA_BYTES = 1024 * 1024
MAX_PROVENANCE_BYTES = 1024 * 1024
MAX_REPORT_BYTES = 2 * 1024 * 1024
MAX_CONFIG_BYTES = 128 * 1024
MAX_STRATEGY_BYTES = 256 * 1024
MAX_COMPRESSION_RATIO = 100
SQLITE_INTEGER_MAX = 2**63 - 1
FEE_TOLERANCE = 1e-15
VALUE_TOLERANCE = 1e-12

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_NAIVE_ISO_TIMESTAMP = re.compile(
    r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?$"
)
_ZONED_ISO_TIMESTAMP = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?"
    r"(?:Z|[+-]\d{2}:\d{2})$"
)
_CONFIG_TIMERANGE = re.compile(r"^(\d{8})-(\d{8})$")
PathLike = Union[str, Path]


class ArtifactImportError(ValueError):
    """Raised when artifact validation or its atomic import fails closed."""


@dataclass(frozen=True)
class ParsedBacktestArtifact:
    """Validated values from the single supported frozen artifact format."""

    archive_path: Path
    strategy: str
    freqtrade_version: str
    freqtrade_commit: str
    report_member: str
    config_member: str
    strategy_member: str
    archive_sha256: str
    metadata_sha256: str
    provenance_sha256: str
    report_sha256: str
    config_sha256: str
    strategy_sha256: str
    exchange: str
    trading_mode: str
    margin_mode: str
    pairs: Tuple[str, ...]
    timeframe: str
    detail_timeframe: Optional[str]
    backtest_start: str
    backtest_end: str
    starting_balance: float
    stake_amount: float
    max_open_trades: int
    configured_fee: float
    total_trades: int
    profit_pct: float
    max_drawdown_pct: float
    win_rate: float
    profit_factor: float
    sharpe: Optional[float]
    sortino: Optional[float]
    calmar: Optional[float]
    long_profit_pct: float
    short_profit_pct: float
    wins: int
    draws: int
    losses: int

    def metrics_json(self) -> str:
        """Return the deliberately small, deterministic database payload."""
        artifact_fields = (
            "archive_sha256", "config_member", "config_sha256",
            "freqtrade_commit", "freqtrade_version", "metadata_sha256",
            "provenance_sha256", "report_member", "report_sha256", "strategy",
            "strategy_member", "strategy_sha256",
        )
        payload = {
            "artifact": {name: getattr(self, name) for name in artifact_fields},
            "contract": {
                "configured_fee": self.configured_fee,
                "exchange": self.exchange,
                "margin_mode": self.margin_mode,
                "pairs": list(self.pairs),
                "trading_mode": self.trading_mode,
            },
            "draws": self.draws,
            "losses": self.losses,
            "wins": self.wins,
        }
        return json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _strict_json(data: bytes, label: str) -> Any:
    def no_duplicate_keys(pairs: Iterable[Tuple[str, Any]]) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ArtifactImportError(f"{label}: duplicate JSON key {key!r}")
            result[key] = value
        return result

    def reject_constant(value: str) -> Any:
        raise ArtifactImportError(f"{label}: non-finite JSON value {value}")

    try:
        text = data.decode("utf-8", "strict")
        return json.loads(
            text,
            object_pairs_hook=no_duplicate_keys,
            parse_constant=reject_constant,
        )
    except ArtifactImportError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ArtifactImportError(f"{label}: invalid UTF-8 JSON: {exc}") from exc


def _required_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ArtifactImportError(f"{label} must be a JSON object")
    return value


def _required_string(mapping: Mapping[str, Any], key: str, label: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value:
        raise ArtifactImportError(f"{label} field {key!r} must be a non-empty string")
    return value


def _required_sha256(mapping: Mapping[str, Any], key: str, label: str) -> str:
    value = _required_string(mapping, key, label)
    if not _SHA256.fullmatch(value):
        raise ArtifactImportError(f"{label} field {key!r} must be a lowercase SHA-256")
    return value


def _required_int(mapping: Mapping[str, Any], key: str, label: str = "strategy") -> int:
    if key not in mapping:
        raise ArtifactImportError(f"{label} is missing required field {key!r}")
    value = mapping[key]
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 0
        or value > SQLITE_INTEGER_MAX
    ):
        raise ArtifactImportError(
            f"{label} field {key!r} must be a non-negative SQLite integer"
        )
    return value


def _number(
    value: Any,
    label: str,
    *,
    allow_none: bool = False,
    minimum: Optional[float] = None,
    maximum: Optional[float] = None,
) -> Optional[float]:
    if value is None and allow_none:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        expected = "a finite number or null" if allow_none else "a finite number"
        raise ArtifactImportError(f"{label} must be {expected}")
    try:
        result = float(value)
    except (OverflowError, ValueError) as exc:
        raise ArtifactImportError(f"{label} cannot be represented as a number") from exc
    if not math.isfinite(result):
        raise ArtifactImportError(f"{label} must be finite")
    if minimum is not None and result < minimum:
        raise ArtifactImportError(f"{label} is below {minimum}")
    if maximum is not None and result > maximum:
        raise ArtifactImportError(f"{label} is above {maximum}")
    return result


def _required_number(
    mapping: Mapping[str, Any],
    key: str,
    *,
    label: str = "strategy",
    allow_none: bool = False,
    minimum: Optional[float] = None,
    maximum: Optional[float] = None,
) -> Optional[float]:
    if key not in mapping:
        raise ArtifactImportError(f"{label} is missing required field {key!r}")
    return _number(
        mapping[key],
        f"{label} field {key!r}",
        allow_none=allow_none,
        minimum=minimum,
        maximum=maximum,
    )


def _string_list(value: Any, label: str) -> Tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise ArtifactImportError(f"{label} must be a non-empty JSON array")
    result: List[str] = []
    for item in value:
        if not isinstance(item, str) or not item:
            raise ArtifactImportError(f"{label} entries must be non-empty strings")
        result.append(item)
    if len(set(result)) != len(result):
        raise ArtifactImportError(f"{label} must not contain duplicates")
    return tuple(result)


def _same_number(left: float, right: float, *, fee: bool = False) -> bool:
    return math.isclose(
        left,
        right,
        rel_tol=0.0,
        abs_tol=FEE_TOLERANCE if fee else VALUE_TOLERANCE,
    )


def _normalize_detail_timeframe(value: Any, label: str) -> Optional[str]:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise ArtifactImportError(f"{label} timeframe_detail must be a string or null")
    return value


def _utc_from_epoch(value: int, label: str) -> datetime:
    try:
        return datetime.fromtimestamp(value, tz=timezone.utc)
    except (OverflowError, OSError, ValueError) as exc:
        raise ArtifactImportError(f"{label} is outside the supported epoch range") from exc


def _utc_from_epoch_millis(value: int, label: str) -> datetime:
    seconds, milliseconds = divmod(value, 1000)
    try:
        return _utc_from_epoch(seconds, label) + timedelta(milliseconds=milliseconds)
    except (OverflowError, ValueError) as exc:
        raise ArtifactImportError(f"{label} is outside the supported epoch range") from exc


def _parse_execution_timestamp(value: Any, label: str) -> datetime:
    if not isinstance(value, str):
        raise ArtifactImportError(f"{label} must be an ISO timestamp string")
    try:
        if _NAIVE_ISO_TIMESTAMP.fullmatch(value):
            return datetime.fromisoformat(value.replace(" ", "T")).replace(
                tzinfo=timezone.utc
            )
        if _ZONED_ISO_TIMESTAMP.fullmatch(value):
            normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
            return datetime.fromisoformat(normalized).astimezone(timezone.utc)
    except (OverflowError, ValueError) as exc:
        raise ArtifactImportError(f"{label} is not a valid ISO timestamp") from exc
    raise ArtifactImportError(
        f"{label} must use YYYY-MM-DD HH:MM:SS or timezone-aware ISO 8601"
    )


def _iso_z(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _percentage(value: float, source_field: str) -> float:
    percentage = value * 100.0
    if not math.isfinite(percentage):
        raise ArtifactImportError(
            f"strategy field {source_field!r} overflows percentage storage"
        )
    return percentage


def _reject_symlinks(root: Path, relative_path: Path, label: str) -> None:
    current = root
    for part in relative_path.parts:
        current = current / part
        if current.is_symlink():
            raise ArtifactImportError(f"{label} must not contain symlinks")


def _resolve_artifact_file(root: Path, relative_path: Path, label: str) -> Path:
    if relative_path.is_absolute():
        raise ArtifactImportError(f"{label} must be relative to artifact root")
    if not relative_path.parts or any(part in ("", ".", "..") for part in relative_path.parts):
        raise ArtifactImportError(f"{label} contains an unsafe path component")
    if "\\" in str(relative_path) or "\x00" in str(relative_path):
        raise ArtifactImportError(f"{label} contains an unsafe path character")

    _reject_symlinks(root, relative_path, label)
    unresolved = root / relative_path
    try:
        resolved = unresolved.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, RuntimeError, ValueError) as exc:
        raise ArtifactImportError(f"{label} is outside artifact root or missing") from exc
    try:
        mode = os.lstat(resolved).st_mode
    except OSError as exc:
        raise ArtifactImportError(f"{label} cannot be inspected safely: {exc}") from exc
    if not stat.S_ISREG(mode):
        raise ArtifactImportError(f"{label} must be a regular file")
    return resolved


def _read_regular_file(path: Path, limit: int, label: str) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(str(path), flags)
    except OSError as exc:
        raise ArtifactImportError(f"{label} cannot be opened safely: {exc}") from exc
    try:
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode):
                raise ArtifactImportError(f"{label} must be a regular file")
            if info.st_size > limit:
                raise ArtifactImportError(f"{label} exceeds the supported size limit")
            chunks: List[bytes] = []
            remaining = limit + 1
            while remaining:
                chunk = os.read(descriptor, min(64 * 1024, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            data = b"".join(chunks)
            if len(data) > limit:
                raise ArtifactImportError(f"{label} exceeds the supported size limit")
            return data
        except OSError as exc:
            raise ArtifactImportError(f"{label} cannot be read safely: {exc}") from exc
    finally:
        os.close(descriptor)


def _validate_zip_info(info: zipfile.ZipInfo, limit: int) -> None:
    if info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
        raise ArtifactImportError(f"ZIP member {info.filename!r} uses unsupported compression")
    if info.file_size > limit:
        raise ArtifactImportError(f"ZIP member {info.filename!r} exceeds its size limit")
    if info.file_size / max(info.compress_size, 1) > MAX_COMPRESSION_RATIO:
        raise ArtifactImportError(
            f"ZIP member {info.filename!r} has an unsafe compression ratio"
        )


def _load_archive(
    archive_bytes: bytes,
    archive_stem: str,
    strategy: str,
) -> Tuple[Mapping[str, bytes], str, str, str]:
    report_member = f"{archive_stem}.json"
    config_member = f"{archive_stem}_config.json"
    strategy_member = f"{archive_stem}_{strategy}.py"
    limits = {
        report_member: MAX_REPORT_BYTES,
        config_member: MAX_CONFIG_BYTES,
        strategy_member: MAX_STRATEGY_BYTES,
    }
    try:
        archive = zipfile.ZipFile(io.BytesIO(archive_bytes))
    except zipfile.BadZipFile as exc:
        raise ArtifactImportError(f"invalid ZIP archive: {exc}") from exc

    with archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        if set(names) != set(limits) or len(names) != 3:
            raise ArtifactImportError(
                "supported Freqtrade 2026.7 ZIP must contain exactly report, config, "
                "and selected strategy source"
            )
        for info in infos:
            _validate_zip_info(info, limits[info.filename])
        try:
            members = {info.filename: archive.read(info) for info in infos}
        except (EOFError, OSError, RuntimeError, zipfile.BadZipFile, zlib.error) as exc:
            raise ArtifactImportError(f"ZIP cannot be read safely: {exc}") from exc
    return members, report_member, config_member, strategy_member


def _contract_equal(contract: Mapping[str, Any], key: str, expected: Any) -> None:
    if key not in contract:
        raise ArtifactImportError(f"provenance contract is missing field {key!r}")
    actual = contract[key]
    if isinstance(expected, float):
        number = _number(actual, f"provenance contract field {key!r}")
        assert number is not None
        if not _same_number(number, expected, fee=(key == "fee")):
            raise ArtifactImportError(f"provenance contract field {key!r} disagrees")
    elif actual != expected:
        raise ArtifactImportError(f"provenance contract field {key!r} disagrees")


def _parse_config_timerange(value: str) -> Tuple[datetime, datetime]:
    match = _CONFIG_TIMERANGE.fullmatch(value)
    if match is None:
        raise ArtifactImportError("config timerange must use YYYYMMDD-YYYYMMDD")
    try:
        start = datetime.strptime(match.group(1), "%Y%m%d").replace(tzinfo=timezone.utc)
        end = datetime.strptime(match.group(2), "%Y%m%d").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise ArtifactImportError("config timerange contains an invalid date") from exc
    if end <= start:
        raise ArtifactImportError("config timerange must have a positive duration")
    return start, end


def _validate_provenance_boundary(provenance: Mapping[str, Any]) -> None:
    acquisition = _required_mapping(
        provenance.get("acquisition"), "provenance acquisition"
    )
    if (
        acquisition.get("host") != "www.okx.com"
        or acquisition.get("authentication") != "none"
    ):
        raise ArtifactImportError(
            "provenance acquisition must attest unauthenticated www.okx.com data"
        )


def parse_backtest_artifact(
    artifact_root: PathLike,
    archive: PathLike,
    strategy: str,
    freqtrade_version: str,
    expected_provenance_sha256: str,
) -> ParsedBacktestArtifact:
    """Parse and cross-check the frozen, provenance-bound Freqtrade format."""
    if freqtrade_version != SUPPORTED_FREQTRADE_VERSION:
        raise ArtifactImportError(
            f"unsupported Freqtrade version {freqtrade_version!r}; "
            f"expected {SUPPORTED_FREQTRADE_VERSION!r}"
        )
    if not isinstance(strategy, str) or not strategy:
        raise ArtifactImportError("strategy must be a non-empty string")
    if not isinstance(expected_provenance_sha256, str) or not _SHA256.fullmatch(
        expected_provenance_sha256
    ):
        raise ArtifactImportError(
            "expected provenance SHA-256 must be 64 lowercase hexadecimal characters"
        )

    try:
        root_input = Path(artifact_root).expanduser()
        if root_input.is_symlink():
            raise ArtifactImportError("artifact root must not be a symlink")
        root = root_input.resolve(strict=True)
    except ArtifactImportError:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise ArtifactImportError(f"artifact root cannot be resolved safely: {exc}") from exc
    if not root.is_dir():
        raise ArtifactImportError("artifact root must be a directory")

    archive_relative = Path(archive)
    if archive_relative.suffix != ".zip" or not archive_relative.name.startswith(
        "backtest-result-"
    ):
        raise ArtifactImportError("archive must be a relative backtest-result-*.zip path")
    archive_path = _resolve_artifact_file(root, archive_relative, "archive")
    metadata_relative = archive_relative.with_name(f"{archive_relative.stem}.meta.json")
    provenance_relative = archive_relative.with_name(
        f"{archive_relative.stem}.provenance.json"
    )
    metadata_path = _resolve_artifact_file(root, metadata_relative, "metadata")
    provenance_path = _resolve_artifact_file(root, provenance_relative, "provenance")

    archive_bytes = _read_regular_file(archive_path, MAX_ARCHIVE_BYTES, "archive")
    metadata_bytes = _read_regular_file(metadata_path, MAX_METADATA_BYTES, "metadata")
    provenance_bytes = _read_regular_file(
        provenance_path, MAX_PROVENANCE_BYTES, "provenance"
    )
    actual_provenance_sha256 = _sha256(provenance_bytes)
    if not hmac.compare_digest(actual_provenance_sha256, expected_provenance_sha256):
        raise ArtifactImportError("provenance SHA-256 does not match the trusted receipt")
    members, report_member, config_member, strategy_member = _load_archive(
        archive_bytes, archive_relative.stem, strategy
    )
    report_bytes = members[report_member]
    config_bytes = members[config_member]
    strategy_bytes = members[strategy_member]
    report = _required_mapping(_strict_json(report_bytes, report_member), "report root")
    config = _required_mapping(_strict_json(config_bytes, config_member), "config root")
    _strict_json(metadata_bytes, metadata_relative.name)
    provenance = _required_mapping(
        _strict_json(provenance_bytes, provenance_relative.name), "provenance root"
    )

    if provenance.get("schema") != SUPPORTED_PROVENANCE_SCHEMA:
        raise ArtifactImportError("unsupported or missing provenance schema")
    _validate_provenance_boundary(provenance)
    provenance_freqtrade = _required_mapping(
        provenance.get("freqtrade"), "provenance freqtrade"
    )
    if (
        provenance_freqtrade.get("version") != SUPPORTED_FREQTRADE_VERSION
        or provenance_freqtrade.get("tag") != SUPPORTED_FREQTRADE_VERSION
        or provenance_freqtrade.get("commit") != SUPPORTED_FREQTRADE_COMMIT
    ):
        raise ArtifactImportError("provenance does not attest the supported Freqtrade build")
    artifact_receipt = _required_mapping(
        provenance.get("artifact"), "provenance artifact"
    )
    if artifact_receipt.get("archive") != archive_relative.name:
        raise ArtifactImportError("provenance archive name does not match input")
    if _required_sha256(
        artifact_receipt, "archive_sha256", "provenance artifact"
    ) != _sha256(archive_bytes):
        raise ArtifactImportError("provenance archive SHA-256 does not match input")
    if artifact_receipt.get("metadata") != metadata_relative.name:
        raise ArtifactImportError("provenance metadata name does not match input")
    if _required_sha256(
        artifact_receipt, "metadata_sha256", "provenance artifact"
    ) != _sha256(metadata_bytes):
        raise ArtifactImportError("provenance metadata SHA-256 does not match input")
    receipt_members = _required_mapping(
        artifact_receipt.get("members"), "provenance artifact members"
    )
    if set(receipt_members) != set(members):
        raise ArtifactImportError("provenance member set does not match ZIP")
    for name, data in members.items():
        value = receipt_members.get(name)
        if not isinstance(value, str) or not _SHA256.fullmatch(value):
            raise ArtifactImportError(f"provenance member hash for {name!r} is invalid")
        if value != _sha256(data):
            raise ArtifactImportError(f"provenance member hash for {name!r} disagrees")
    try:
        strategy_text = strategy_bytes.decode("utf-8", "strict")
    except UnicodeDecodeError as exc:
        raise ArtifactImportError("strategy source must be UTF-8") from exc
    class_pattern = re.compile(rf"(?m)^class\s+{re.escape(strategy)}\s*\(")
    if class_pattern.search(strategy_text) is None:
        raise ArtifactImportError("strategy source does not declare the selected class")

    if _required_string(config, "strategy", "config") != strategy:
        raise ArtifactImportError("config strategy does not match selection")
    exchange_config = _required_mapping(config.get("exchange"), "config exchange")
    exchange = _required_string(exchange_config, "name", "config exchange")
    pairs = _string_list(
        exchange_config.get("pair_whitelist"), "config exchange pair_whitelist"
    )
    trading_mode = _required_string(config, "trading_mode", "config")
    margin_mode = _required_string(config, "margin_mode", "config")
    if (
        exchange != SUPPORTED_EXCHANGE
        or trading_mode != SUPPORTED_TRADING_MODE
        or margin_mode != SUPPORTED_MARGIN_MODE
    ):
        raise ArtifactImportError(
            "the frozen format boundary requires okx/futures/isolated"
        )
    timeframe = _required_string(config, "timeframe", "config")
    if timeframe != "5m":
        raise ArtifactImportError("the frozen format boundary supports only 5m")
    detail_timeframe = _normalize_detail_timeframe(
        config.get("timeframe_detail"), "config"
    )
    config_timerange = _required_string(config, "timerange", "config")
    timerange_start, timerange_end_exclusive = _parse_config_timerange(config_timerange)
    configured_fee = _required_number(config, "fee", label="config", minimum=0.0)
    starting_balance = _required_number(
        config, "dry_run_wallet", label="config", minimum=0.0
    )
    stake_amount = _required_number(config, "stake_amount", label="config", minimum=0.0)
    max_open_trades = _required_int(config, "max_open_trades", "config")
    assert configured_fee is not None
    assert starting_balance is not None
    assert stake_amount is not None
    if (
        configured_fee <= 0
        or starting_balance <= 0
        or stake_amount <= 0
        or max_open_trades <= 0
    ):
        raise ArtifactImportError(
            "config fee, balance, stake, and max_open_trades must be positive"
        )

    strategies = _required_mapping(report.get("strategy"), "report strategy")
    if set(strategies) != {strategy}:
        raise ArtifactImportError("report strategy set does not exactly match selection")
    result = _required_mapping(strategies[strategy], "strategy result")
    if _required_string(result, "strategy_name", "strategy result") != strategy:
        raise ArtifactImportError("strategy_name does not match selected strategy")

    report_timeframe = _required_string(result, "timeframe", "strategy result")
    if report_timeframe != timeframe:
        raise ArtifactImportError("report and config timeframe disagree")
    if "timeframe_detail" not in result:
        raise ArtifactImportError("strategy result is missing timeframe_detail")
    report_detail = _normalize_detail_timeframe(
        result.get("timeframe_detail"), "strategy result"
    )
    if report_detail != detail_timeframe:
        raise ArtifactImportError("report and config detail timeframe disagree")
    if _required_string(result, "timerange", "strategy result") != config_timerange:
        raise ArtifactImportError("report and config timerange disagree")

    report_start_text = _required_string(result, "backtest_start", "strategy result")
    report_end_text = _required_string(result, "backtest_end", "strategy result")
    report_start = _parse_execution_timestamp(report_start_text, "artifact backtest_start")
    report_end = _parse_execution_timestamp(report_end_text, "artifact backtest_end")
    report_start_millis = _required_int(
        result, "backtest_start_ts", "strategy result"
    )
    report_end_millis = _required_int(result, "backtest_end_ts", "strategy result")
    report_epoch_start = _utc_from_epoch_millis(
        report_start_millis, "strategy result backtest_start_ts"
    )
    report_epoch_end = _utc_from_epoch_millis(
        report_end_millis, "strategy result backtest_end_ts"
    )
    if report_epoch_start != report_start or report_epoch_end != report_end:
        raise ArtifactImportError(
            "report text and millisecond timeranges disagree"
        )
    if report_start != timerange_start or report_end != timerange_end_exclusive - timedelta(
        minutes=5
    ):
        raise ArtifactImportError("config timerange and report candle bounds disagree")
    backtest_start = _iso_z(report_start)
    backtest_end = _iso_z(report_end)

    if _required_string(result, "trading_mode", "strategy result") != trading_mode:
        raise ArtifactImportError("report and config trading_mode disagree")
    if _required_string(result, "margin_mode", "strategy result") != margin_mode:
        raise ArtifactImportError("report and config margin_mode disagree")
    report_pairs = _string_list(result.get("pairlist"), "strategy result pairlist")
    if report_pairs != pairs:
        raise ArtifactImportError("report and config pairlist disagree")
    report_balance = _required_number(
        result, "starting_balance", label="strategy result", minimum=0.0
    )
    report_stake = _required_number(
        result, "stake_amount", label="strategy result", minimum=0.0
    )
    report_max_open = _required_int(result, "max_open_trades", "strategy result")
    assert report_balance is not None
    assert report_stake is not None
    if not _same_number(report_balance, starting_balance):
        raise ArtifactImportError("report and config starting balance disagree")
    if not _same_number(report_stake, stake_amount):
        raise ArtifactImportError("report and config stake_amount disagree")
    if report_max_open != max_open_trades:
        raise ArtifactImportError("report and config max_open_trades disagree")

    total_trades = _required_int(result, "total_trades", "strategy result")
    wins = _required_int(result, "wins", "strategy result")
    draws = _required_int(result, "draws", "strategy result")
    losses = _required_int(result, "losses", "strategy result")
    if total_trades == 0:
        raise ArtifactImportError("zero-trade reports cannot prove pair or fee identity")
    if wins + draws + losses != total_trades:
        raise ArtifactImportError("wins + draws + losses must equal total_trades")
    trades = result.get("trades")
    if not isinstance(trades, list) or len(trades) != total_trades:
        raise ArtifactImportError("trade list length must equal total_trades")
    for index, trade_value in enumerate(trades):
        trade = _required_mapping(trade_value, f"trade {index}")
        pair = _required_string(trade, "pair", f"trade {index}")
        if pair not in pairs:
            raise ArtifactImportError(f"trade {index} pair is outside the configured pairlist")
        for fee_key in ("fee_open", "fee_close"):
            trade_fee = _required_number(trade, fee_key, label=f"trade {index}", minimum=0.0)
            assert trade_fee is not None
            if not _same_number(trade_fee, configured_fee, fee=True):
                raise ArtifactImportError(
                    f"trade {index} {fee_key} does not match configured fee"
                )
        leverage = _required_number(trade, "leverage", label=f"trade {index}", minimum=0.0)
        assert leverage is not None
        if leverage <= 0:
            raise ArtifactImportError(f"trade {index} leverage must be positive")
        is_short = trade.get("is_short")
        if not isinstance(is_short, bool):
            raise ArtifactImportError(f"trade {index} is_short must be boolean")
        _required_number(trade, "funding_fees", label=f"trade {index}")

    profit_total = _required_number(result, "profit_total", label="strategy result")
    max_drawdown = _required_number(
        result,
        "max_drawdown_account",
        label="strategy result",
        minimum=0.0,
        maximum=1.0,
    )
    winrate = _required_number(
        result, "winrate", label="strategy result", minimum=0.0, maximum=1.0
    )
    profit_factor = _required_number(
        result, "profit_factor", label="strategy result", minimum=0.0
    )
    sharpe = _required_number(result, "sharpe", label="strategy result", allow_none=True)
    sortino = _required_number(
        result, "sortino", label="strategy result", allow_none=True
    )
    calmar = _required_number(result, "calmar", label="strategy result", allow_none=True)
    profit_total_long = _required_number(
        result, "profit_total_long", label="strategy result"
    )
    profit_total_short = _required_number(
        result, "profit_total_short", label="strategy result"
    )
    assert profit_total is not None
    assert max_drawdown is not None
    assert winrate is not None
    assert profit_factor is not None
    assert profit_total_long is not None
    assert profit_total_short is not None
    if not _same_number(winrate, wins / total_trades):
        raise ArtifactImportError("winrate does not agree with wins and total_trades")

    contract = _required_mapping(provenance.get("contract"), "provenance contract")
    for key, expected in (
        ("strategy", strategy),
        ("exchange", exchange),
        ("trading_mode", trading_mode),
        ("margin_mode", margin_mode),
        ("pairs", list(pairs)),
        ("timeframe", timeframe),
        ("detail_timeframe", detail_timeframe),
        ("timerange", config_timerange),
        ("backtest_start_utc", backtest_start),
        ("backtest_end_utc", backtest_end),
        ("starting_balance", starting_balance),
        ("stake_amount", stake_amount),
        ("max_open_trades", max_open_trades),
        ("fee", configured_fee),
        ("report_total_trades", total_trades),
        ("wins", wins),
        ("draws", draws),
        ("losses", losses),
    ):
        _contract_equal(contract, key, expected)
    fee_evidence = _required_mapping(
        provenance.get("fee_evidence"), "provenance fee_evidence"
    )
    if fee_evidence.get("kind") != "configured parser-fixture assumption":
        raise ArtifactImportError("unsupported fee evidence kind")
    fee_evidence_rate = _required_number(
        fee_evidence, "rate", label="provenance fee_evidence", minimum=0.0
    )
    assert fee_evidence_rate is not None
    if not _same_number(fee_evidence_rate, configured_fee, fee=True):
        raise ArtifactImportError("provenance fee evidence rate disagrees")
    claim = _required_string(fee_evidence, "claim", "provenance fee_evidence")
    if claim != "not an observed or public OKX account fee rate":
        raise ArtifactImportError("provenance must preserve the configured-fee limitation")

    return ParsedBacktestArtifact(
        archive_path=archive_path,
        strategy=strategy,
        freqtrade_version=freqtrade_version,
        freqtrade_commit=SUPPORTED_FREQTRADE_COMMIT,
        report_member=report_member,
        config_member=config_member,
        strategy_member=strategy_member,
        archive_sha256=_sha256(archive_bytes),
        metadata_sha256=_sha256(metadata_bytes),
        provenance_sha256=actual_provenance_sha256,
        report_sha256=_sha256(report_bytes),
        config_sha256=_sha256(config_bytes),
        strategy_sha256=_sha256(strategy_bytes),
        exchange=exchange,
        trading_mode=trading_mode,
        margin_mode=margin_mode,
        pairs=pairs,
        timeframe=timeframe,
        detail_timeframe=detail_timeframe,
        backtest_start=backtest_start,
        backtest_end=backtest_end,
        starting_balance=starting_balance,
        stake_amount=stake_amount,
        max_open_trades=max_open_trades,
        configured_fee=configured_fee,
        total_trades=total_trades,
        profit_pct=_percentage(profit_total, "profit_total"),
        max_drawdown_pct=_percentage(max_drawdown, "max_drawdown_account"),
        win_rate=_percentage(winrate, "winrate"),
        profit_factor=profit_factor,
        sharpe=sharpe,
        sortino=sortino,
        calmar=calmar,
        long_profit_pct=_percentage(profit_total_long, "profit_total_long"),
        short_profit_pct=_percentage(profit_total_short, "profit_total_short"),
        wins=wins,
        draws=draws,
        losses=losses,
    )


def _resolve_database_path(db_path: PathLike) -> Path:
    try:
        path_input = Path(db_path).expanduser()
        if path_input.is_symlink():
            raise ArtifactImportError("database path must not be a symlink")
        path = path_input.resolve(strict=True)
    except ArtifactImportError:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise ArtifactImportError(f"database path cannot be resolved safely: {exc}") from exc
    if not path.is_file():
        raise ArtifactImportError("database path must be a regular file")
    return path


def _profile_pairs(value: Any) -> Tuple[str, ...]:
    if not isinstance(value, str):
        raise ArtifactImportError("research profile pairs_json must be text")
    parsed = _strict_json(value.encode("utf-8"), "research profile pairs_json")
    return _string_list(parsed, "research profile pairs_json")


def _empty_metrics(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return _strict_json(value.encode("utf-8"), "execution metrics_json") == {}
    except ArtifactImportError:
        return False


def _require_clean_execution(row: sqlite3.Row) -> None:
    if row["status"] != "PENDING":
        raise ArtifactImportError(
            f"execution status {row['status']!r} cannot be imported; "
            "only PENDING executions are eligible and terminal rows remain immutable"
        )
    nullable_result_fields = (
        "result_archive_path", "stdout_path", "stderr_path", "return_code",
        "total_trades", "profit_pct", "max_drawdown_pct", "win_rate",
        "profit_factor", "sharpe", "sortino", "calmar", "long_profit_pct",
        "short_profit_pct", "scenario_passed", "error_message", "finished_at",
    )
    dirty = [key for key in nullable_result_fields if row[key] is not None]
    if dirty or not _empty_metrics(row["metrics_json"]):
        fields = ", ".join(dirty or ["metrics_json"])
        raise ArtifactImportError(
            f"execution contains pre-existing result state ({fields}); refusing overwrite"
        )


def _db_float(value: Any, label: str, *, minimum: Optional[float] = None) -> float:
    number = _number(value, label, minimum=minimum)
    assert number is not None
    return number


def import_backtest_execution(
    db_path: PathLike,
    artifact_root: PathLike,
    archive: PathLike,
    research_run_id: str,
    scenario: str,
    strategy: str,
    freqtrade_version: str,
    expected_provenance_sha256: str,
) -> ParsedBacktestArtifact:
    """Atomically update one existing execution with a validated artifact."""
    if not isinstance(research_run_id, str) or not research_run_id:
        raise ArtifactImportError("research_run_id must be a non-empty string")
    if scenario not in SUPPORTED_SCENARIOS:
        raise ArtifactImportError(f"unsupported scenario {scenario!r}")

    parsed = parse_backtest_artifact(
        artifact_root,
        archive,
        strategy,
        freqtrade_version,
        expected_provenance_sha256,
    )
    database_path = _resolve_database_path(db_path)
    try:
        connection = get_connection(database_path)
    except (sqlite3.Error, OverflowError) as exc:
        raise ArtifactImportError(f"database cannot be opened safely: {exc}") from exc

    with closing(connection):
        try:
            connection.execute("BEGIN IMMEDIATE")
            schema_row = connection.execute("PRAGMA user_version").fetchone()
            if schema_row is None or int(schema_row[0]) != 1:
                raise ArtifactImportError("database schema version must be 1")
            rows = connection.execute(
                """
                SELECT be.*,
                    rr.status AS research_run_status,
                    rr.stage AS research_run_stage,
                    rr.verdict AS research_run_verdict,
                    rr.freqtrade_version,
                    c.class_name AS candidate_class_name,
                    c.timeframe AS candidate_timeframe,
                    c.code_text AS candidate_code_text,
                    c.code_sha256 AS candidate_code_sha256,
                    rp.domain AS profile_domain,
                    rp.exchange AS profile_exchange,
                    rp.trading_mode AS profile_trading_mode,
                    rp.margin_mode AS profile_margin_mode,
                    rp.pairs_json AS profile_pairs_json,
                    rp.timeframe AS profile_timeframe,
                    rp.detail_timeframe AS profile_detail_timeframe,
                    rp.starting_balance AS profile_starting_balance,
                    rp.stake_amount AS profile_stake_amount,
                    rp.max_open_trades AS profile_max_open_trades,
                    rp.taker_fee_rate AS profile_taker_fee_rate,
                    rp.stress_fee_multiplier AS profile_stress_fee_multiplier
                FROM backtest_executions AS be
                JOIN research_runs AS rr ON rr.id = be.research_run_id
                JOIN candidates AS c ON c.id = rr.candidate_id
                JOIN research_profiles AS rp ON rp.id = rr.research_profile_id
                WHERE be.research_run_id = ? AND be.scenario = ?
                """,
                (research_run_id, scenario),
            ).fetchall()
            if len(rows) != 1:
                raise ArtifactImportError(
                    "expected exactly one existing execution for research run and scenario"
                )
            row = rows[0]
            _require_clean_execution(row)
            expected_stage = SCENARIO_STAGES[scenario]
            if (
                row["research_run_status"] != "RUNNING"
                or row["research_run_stage"] != expected_stage
                or row["research_run_verdict"] is not None
            ):
                raise ArtifactImportError(
                    "research run must be RUNNING at the selected scenario stage "
                    "with no verdict"
                )

            if row["candidate_class_name"] != parsed.strategy:
                raise ArtifactImportError(
                    "research run candidate class does not match artifact strategy"
                )
            if row["candidate_timeframe"] != parsed.timeframe:
                raise ArtifactImportError("candidate timeframe does not match artifact")
            candidate_hash = row["candidate_code_sha256"]
            candidate_text = row["candidate_code_text"]
            if not isinstance(candidate_hash, str) or candidate_hash != parsed.strategy_sha256:
                raise ArtifactImportError("candidate code_sha256 does not match strategy source")
            if not isinstance(candidate_text, str) or _sha256(
                candidate_text.encode("utf-8")
            ) != candidate_hash:
                raise ArtifactImportError("candidate code_text does not match its code_sha256")

            if row["timeframe"] != parsed.timeframe:
                raise ArtifactImportError("execution timeframe does not match artifact")
            if _normalize_detail_timeframe(
                row["detail_timeframe"], "execution"
            ) != parsed.detail_timeframe:
                raise ArtifactImportError("execution detail timeframe does not match artifact")
            execution_start = _parse_execution_timestamp(
                row["timerange_start"], "execution timerange_start"
            )
            execution_end = _parse_execution_timestamp(
                row["timerange_end"], "execution timerange_end"
            )
            artifact_start = _parse_execution_timestamp(
                parsed.backtest_start, "artifact backtest_start"
            )
            artifact_end = _parse_execution_timestamp(
                parsed.backtest_end, "artifact backtest_end"
            )
            if execution_start != artifact_start or execution_end != artifact_end:
                raise ArtifactImportError("execution timerange does not match artifact")

            if row["profile_domain"] != SUPPORTED_PROFILE_DOMAIN:
                raise ArtifactImportError(
                    "research profile domain does not match the OKX crypto artifact"
                )
            if row["profile_exchange"] != parsed.exchange:
                raise ArtifactImportError("research profile exchange does not match artifact")
            if row["profile_trading_mode"] != parsed.trading_mode:
                raise ArtifactImportError("research profile trading_mode does not match artifact")
            if row["profile_margin_mode"] != parsed.margin_mode:
                raise ArtifactImportError("research profile margin_mode does not match artifact")
            profile_pairs = _profile_pairs(row["profile_pairs_json"])
            if set(profile_pairs) != set(parsed.pairs):
                raise ArtifactImportError("research profile pair set does not match artifact")
            if row["profile_timeframe"] != parsed.timeframe:
                raise ArtifactImportError("research profile timeframe does not match artifact")
            if _normalize_detail_timeframe(
                row["profile_detail_timeframe"], "research profile"
            ) != parsed.detail_timeframe:
                raise ArtifactImportError(
                    "research profile detail timeframe does not match artifact"
                )
            profile_balance = _db_float(
                row["profile_starting_balance"], "research profile starting_balance", minimum=0.0
            )
            profile_stake = _db_float(
                row["profile_stake_amount"], "research profile stake_amount", minimum=0.0
            )
            if not _same_number(profile_balance, parsed.starting_balance):
                raise ArtifactImportError("research profile starting_balance does not match artifact")
            if not _same_number(profile_stake, parsed.stake_amount):
                raise ArtifactImportError("research profile stake_amount does not match artifact")
            if row["profile_max_open_trades"] != parsed.max_open_trades:
                raise ArtifactImportError("research profile max_open_trades does not match artifact")

            execution_fee = _db_float(row["fee_rate"], "execution fee_rate", minimum=0.0)
            multiplier = _db_float(
                row["fee_multiplier"], "execution fee_multiplier", minimum=1.0
            )
            profile_fee = _db_float(
                row["profile_taker_fee_rate"], "research profile taker_fee_rate", minimum=0.0
            )
            stress_multiplier = _db_float(
                row["profile_stress_fee_multiplier"],
                "research profile stress_fee_multiplier",
                minimum=1.0,
            )
            if profile_fee <= 0:
                raise ArtifactImportError("profile fee must be positive")
            expected_multiplier = stress_multiplier if scenario == "HOLDOUT_STRESS" else 1.0
            if not _same_number(multiplier, expected_multiplier, fee=True):
                raise ArtifactImportError("execution fee_multiplier does not match scenario")
            if not _same_number(execution_fee, profile_fee * multiplier, fee=True):
                raise ArtifactImportError(
                    "execution fee_rate does not equal profile fee times multiplier"
                )
            if not _same_number(execution_fee, parsed.configured_fee, fee=True):
                raise ArtifactImportError("execution fee_rate does not match artifact trade fees")

            identity_rows = connection.execute(
                """
                SELECT scenario, timerange_start, timerange_end, timeframe,
                       detail_timeframe, fee_rate
                FROM backtest_executions
                WHERE research_run_id = ?
                """,
                (research_run_id,),
            ).fetchall()
            matching_scenarios: List[str] = []
            for identity in identity_rows:
                identity_start = _parse_execution_timestamp(
                    identity["timerange_start"], "scenario timerange_start"
                )
                identity_end = _parse_execution_timestamp(
                    identity["timerange_end"], "scenario timerange_end"
                )
                identity_fee = _db_float(
                    identity["fee_rate"], "scenario fee_rate", minimum=0.0
                )
                if (
                    identity_start == artifact_start
                    and identity_end == artifact_end
                    and identity["timeframe"] == parsed.timeframe
                    and _normalize_detail_timeframe(
                        identity["detail_timeframe"], "scenario"
                    )
                    == parsed.detail_timeframe
                    and _same_number(identity_fee, parsed.configured_fee, fee=True)
                ):
                    matching_scenarios.append(identity["scenario"])
            if matching_scenarios != [scenario]:
                raise ArtifactImportError(
                    "artifact timerange/timeframe/fee identity does not uniquely match scenario"
                )

            existing_version = row["freqtrade_version"]
            if existing_version not in (None, parsed.freqtrade_version):
                raise ArtifactImportError(
                    "research run Freqtrade version conflicts with artifact provenance"
                )
            if existing_version is None:
                version_update = connection.execute(
                    """
                    UPDATE research_runs
                    SET freqtrade_version = ?
                    WHERE id = ? AND freqtrade_version IS NULL
                      AND status = 'RUNNING' AND stage = ? AND verdict IS NULL
                    """,
                    (
                        parsed.freqtrade_version,
                        research_run_id,
                        expected_stage,
                    ),
                )
                if version_update.rowcount != 1:
                    raise ArtifactImportError("research run version changed during import")

            execution_update = connection.execute(
                """
                UPDATE backtest_executions
                SET status = 'SUCCEEDED',
                    result_archive_path = ?,
                    total_trades = ?,
                    profit_pct = ?,
                    max_drawdown_pct = ?,
                    win_rate = ?,
                    profit_factor = ?,
                    sharpe = ?,
                    sortino = ?,
                    calmar = ?,
                    long_profit_pct = ?,
                    short_profit_pct = ?,
                    metrics_json = ?,
                    error_message = NULL
                WHERE id = ? AND status = 'PENDING' AND result_archive_path IS NULL
                """,
                (
                    str(parsed.archive_path),
                    parsed.total_trades,
                    parsed.profit_pct,
                    parsed.max_drawdown_pct,
                    parsed.win_rate,
                    parsed.profit_factor,
                    parsed.sharpe,
                    parsed.sortino,
                    parsed.calmar,
                    parsed.long_profit_pct,
                    parsed.short_profit_pct,
                    parsed.metrics_json(),
                    row["id"],
                ),
            )
            if execution_update.rowcount != 1:
                raise ArtifactImportError("execution changed during import")
            connection.commit()
        except ArtifactImportError:
            if connection.in_transaction:
                connection.rollback()
            raise
        except (sqlite3.Error, OverflowError, UnicodeEncodeError) as exc:
            if connection.in_transaction:
                connection.rollback()
            raise ArtifactImportError(f"database import failed: {exc}") from exc
    return parsed
