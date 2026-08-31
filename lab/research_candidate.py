"""Run one real three-scenario Freqtrade candidate and publish a strict bundle.

The producer is deliberately synchronous and single-use.  It validates one
Candidate/Profile contract, runs exactly three offline Freqtrade backtests,
sanitizes the native exports, reuses the existing artifact/bundle validators,
and optionally imports the published bundle into an explicitly selected
schema-v1 database.
"""

from __future__ import annotations

import copy
import ctypes
import errno
import hashlib
import io
import json
import math
import os
import re
import shutil
import sqlite3
import stat
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

from lab.backtest_artifact import (
    SUPPORTED_FREQTRADE_COMMIT,
    SUPPORTED_FREQTRADE_VERSION,
    parse_backtest_artifact,
)
from lab.research_bundle import (
    BUNDLE_SCHEMA,
    ImportedResearchBundle,
    ResearchBundleImportError,
    import_research_bundle,
    validate_research_bundle,
)


RESEARCH_SPEC_SCHEMA = "freqtrade-lab-research-spec-v1"
RETAINED_DATA_SCHEMA = "freqtrade-lab-retained-okx-data-v1"
SUPPORTED_DEPENDENCIES = {
    "ccxt": "4.5.68",
    "pandas": "3.0.3",
    "pyarrow": "25.0.0",
    "python": "3.13.13",
}
SUPPORTED_OFFICIAL_CORE = {
    "setup_optimize_configuration": "freqtrade.commands.optimize_commands",
    "Okx": "freqtrade.exchange.okx",
    "Backtesting.start": "freqtrade.optimize.backtesting",
    "Backtesting.backtest_one_strategy": "freqtrade.optimize.backtesting",
    "Backtesting.backtest": "freqtrade.optimize.backtesting",
    "generate_backtest_stats": "freqtrade.optimize.optimize_reports.optimize_reports",
    "store_backtest_results": "freqtrade.optimize.optimize_reports.bt_storage",
}
MANIFEST_NAME = "research-bundle-v1.json"
SCENARIOS = (
    ("DEVELOPMENT", "development-01"),
    ("HOLDOUT", "holdout-02"),
    ("HOLDOUT_STRESS", "holdout-stress-03"),
)
DEFAULT_RUNNER = Path(__file__).resolve().parent.parent / "scripts" / "run_freqtrade_backtest.py"
DEFAULT_SANDBOX_EXEC = Path("/usr/bin/sandbox-exec")
DEFAULT_GIT_EXECUTABLE = Path("/Library/Developer/CommandLineTools/usr/bin/git")
SUPPORTED_FREQTRADE_TREE = "167618402c6e278b7dc9dd72a3f69003fad04983"

MAX_JSON_BYTES = 1024 * 1024
MAX_RAW_ARCHIVE_BYTES = 16 * 1024 * 1024
MAX_SOURCE_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_RAW_ZIP_MEMBER_BYTES = 16 * 1024 * 1024
MAX_RAW_ZIP_TOTAL_BYTES = 32 * 1024 * 1024
MAX_RAW_ZIP_MEMBERS = 16
MAX_RAW_ZIP_COMPRESSION_RATIO = 200
SCENARIO_TIMEOUT_SECONDS = 60 * 60
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_TIMERANGE = re.compile(r"^(\d{8})-(\d{8})$")
_CLASS_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_WINDOWS_ABSOLUTE = re.compile(r"^[A-Za-z]:[\\/]")
_SENSITIVE_KEYS = {
    "account_id",
    "accountid",
    "apikey",
    "api_key",
    "apikeysecret",
    "api_secret",
    "bearer_token",
    "chat_id",
    "key",
    "password",
    "passphrase",
    "private_key",
    "privatekey",
    "secret",
    "token",
    "uid",
    "wallet_address",
    "walletaddress",
    "webhook_url",
}
_BASE_CONFIG_KEYS = {
    "backtest_cache",
    "cancel_open_orders_on_exit",
    "dataformat_ohlcv",
    "disableparamexport",
    "dry_run",
    "dry_run_wallet",
    "entry_pricing",
    "exchange",
    "exit_pricing",
    "fee",
    "fiat_display_currency",
    "margin_mode",
    "max_open_trades",
    "pairlists",
    "stake_amount",
    "stake_currency",
    "strategy",
    "timeframe",
    "tradable_balance_ratio",
    "trading_mode",
    "unfilledtimeout",
}
_EXCHANGE_CONFIG_KEYS = {"enable_ws", "name", "pair_blacklist", "pair_whitelist"}
_PRICING_CONFIG_KEYS = {"order_book_top", "price_side", "use_order_book"}
_TIMEOUT_CONFIG_KEYS = {"entry", "exit", "exit_timeout_count", "unit"}

PathLike = Union[str, Path]
CommandRunner = Callable[..., subprocess.CompletedProcess]


class ResearchCandidateError(ValueError):
    """Raised when the producer fails closed before completing the full slice."""


@dataclass(frozen=True)
class ProducedArtifact:
    scenario: str
    archive: str
    archive_sha256: str
    provenance_sha256: str
    total_trades: int


@dataclass(frozen=True)
class ResearchCandidateResult:
    bundle_root: Path
    manifest_path: Path
    manifest_sha256: str
    artifacts: Tuple[ProducedArtifact, ...]
    imported: Optional[ImportedResearchBundle]


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_bytes(value: Any) -> bytes:
    try:
        text = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError, OverflowError) as exc:
        raise ResearchCandidateError(f"value cannot be encoded as strict JSON: {exc}") from exc
    return (text + "\n").encode("utf-8")


def _strict_json(data: bytes, label: str) -> Any:
    def no_duplicates(pairs: Iterable[Tuple[str, Any]]) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ResearchCandidateError(f"{label}: duplicate JSON key {key!r}")
            result[key] = value
        return result

    def reject_constant(value: str) -> Any:
        raise ResearchCandidateError(f"{label}: non-finite JSON value {value}")

    try:
        return json.loads(
            data.decode("utf-8", "strict"),
            object_pairs_hook=no_duplicates,
            parse_constant=reject_constant,
        )
    except ResearchCandidateError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ResearchCandidateError(f"{label}: invalid UTF-8 JSON: {exc}") from exc


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ResearchCandidateError(f"{label} must be a JSON object")
    return value


def _exact_keys(value: Mapping[str, Any], keys: Sequence[str], label: str) -> None:
    expected = set(keys)
    actual = set(value)
    missing = sorted(expected - actual)
    unknown = sorted(actual - expected)
    if missing:
        raise ResearchCandidateError(f"{label} is missing fields: {', '.join(missing)}")
    if unknown:
        raise ResearchCandidateError(f"{label} contains unknown fields: {', '.join(unknown)}")


def _read_file(path: Path, label: str, limit: int = MAX_JSON_BYTES) -> bytes:
    try:
        info = path.stat()
        if not stat.S_ISREG(info.st_mode):
            raise ResearchCandidateError(f"{label} must be a regular file")
        if info.st_size > limit:
            raise ResearchCandidateError(f"{label} exceeds the {limit}-byte limit")
        data = path.read_bytes()
    except ResearchCandidateError:
        raise
    except OSError as exc:
        raise ResearchCandidateError(f"{label} cannot be read safely: {exc}") from exc
    if len(data) > limit:
        raise ResearchCandidateError(f"{label} exceeds the {limit}-byte limit")
    return data


def _resolve_file(path_value: PathLike, label: str, *, executable: bool = False) -> Path:
    try:
        value = Path(path_value).expanduser()
        if value.is_symlink():
            raise ResearchCandidateError(f"{label} must not be a symlink")
        path = value.resolve(strict=True)
    except ResearchCandidateError:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise ResearchCandidateError(f"{label} cannot be resolved safely: {exc}") from exc
    if not path.is_file():
        raise ResearchCandidateError(f"{label} must be a regular file")
    if executable and not os.access(str(path), os.X_OK):
        raise ResearchCandidateError(f"{label} must be executable")
    return path


def _resolve_executable(path_value: PathLike, label: str) -> Path:
    """Validate an executable while preserving a final virtualenv symlink."""
    try:
        value = Path(path_value).expanduser()
        path = Path(os.path.abspath(str(value)))
        target = path.resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as exc:
        raise ResearchCandidateError(f"{label} cannot be resolved safely: {exc}") from exc
    if not target.is_file():
        raise ResearchCandidateError(f"{label} must resolve to a regular file")
    if not os.access(str(path), os.X_OK):
        raise ResearchCandidateError(f"{label} must be executable")
    return path


def _resolve_directory(path_value: PathLike, label: str) -> Path:
    try:
        value = Path(path_value).expanduser()
        if value.is_symlink():
            raise ResearchCandidateError(f"{label} must not be a symlink")
        path = value.resolve(strict=True)
    except ResearchCandidateError:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise ResearchCandidateError(f"{label} cannot be resolved safely: {exc}") from exc
    if not path.is_dir():
        raise ResearchCandidateError(f"{label} must be a directory")
    return path


def _resolve_output(path_value: PathLike) -> Path:
    value = Path(path_value).expanduser()
    if value.name in ("", ".", ".."):
        raise ResearchCandidateError("output directory must name one new bundle directory")
    parent = _resolve_directory(value.parent, "output parent")
    output = parent / value.name
    if output.exists() or output.is_symlink():
        raise ResearchCandidateError("output directory already exists")
    return output


def _resolve_new_receipt(path_value: PathLike, label: str) -> Path:
    value = Path(path_value).expanduser()
    if not value.is_absolute() or value.name in ("", ".", ".."):
        raise ResearchCandidateError(f"{label} must name one absolute new file")
    parent = _resolve_directory(value.parent, f"{label} parent")
    path = parent / value.name
    if path.exists() or path.is_symlink():
        raise ResearchCandidateError(f"{label} already exists")
    return path


def _publish_directory_exclusive(source: Path, destination: Path) -> None:
    """Atomically publish without replacing a concurrently created target."""
    if sys.platform == "darwin":
        libc = ctypes.CDLL(None, use_errno=True)
        rename_exclusive = getattr(libc, "renameatx_np", None)
        if rename_exclusive is None:
            raise ResearchCandidateError("exclusive directory publication is unavailable")
        rename_exclusive.argtypes = (
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        )
        rename_exclusive.restype = ctypes.c_int
        at_fdcwd = -2
        rename_excl = 0x00000004
        result = rename_exclusive(
            at_fdcwd,
            os.fsencode(source),
            at_fdcwd,
            os.fsencode(destination),
            rename_excl,
        )
        if result == 0:
            return
        error_number = ctypes.get_errno()
        if error_number in (errno.EEXIST, errno.ENOTEMPTY):
            raise ResearchCandidateError(
                "output directory was created concurrently; nothing was published"
            )
        raise ResearchCandidateError(
            f"exclusive directory publication failed: {os.strerror(error_number)}"
        )

    # Real execution is macOS-only.  Keep fake/unit execution portable while
    # retaining fail-closed behavior on an already-visible target.
    if destination.exists() or destination.is_symlink():
        raise ResearchCandidateError(
            "output directory was created concurrently; nothing was published"
        )
    try:
        os.rename(source, destination)
    except FileExistsError as exc:
        raise ResearchCandidateError(
            "output directory was created concurrently; nothing was published"
        ) from exc


def _relative_member(value: str, label: str) -> Path:
    path = Path(value)
    if path.is_absolute() or not path.parts or any(part in ("", ".", "..") for part in path.parts):
        raise ResearchCandidateError(f"{label} must be a safe relative path")
    if "\\" in value or "\x00" in value:
        raise ResearchCandidateError(f"{label} contains an unsafe path character")
    return path


def _parse_timerange(value: str, label: str) -> Tuple[datetime, datetime]:
    match = _TIMERANGE.fullmatch(value)
    if match is None:
        raise ResearchCandidateError(f"{label} must use YYYYMMDD-YYYYMMDD")
    try:
        start = datetime.strptime(match.group(1), "%Y%m%d").replace(tzinfo=timezone.utc)
        end = datetime.strptime(match.group(2), "%Y%m%d").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise ResearchCandidateError(f"{label} contains an invalid calendar date") from exc
    if end <= start:
        raise ResearchCandidateError(f"{label} must have a positive duration")
    return start, end


def _finite_number(value: Any, label: str, *, minimum: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ResearchCandidateError(f"{label} must be a finite number")
    number = float(value)
    if not math.isfinite(number) or number < minimum:
        raise ResearchCandidateError(f"{label} must be a finite number >= {minimum}")
    return number


def _positive_integer(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ResearchCandidateError(f"{label} must be a positive integer")
    return value


def _nonempty_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ResearchCandidateError(f"{label} must be a non-empty string")
    return value


def _validate_research_spec(
    path: Path,
    strategy: str,
    development_timerange: str,
    holdout_timerange: str,
    stress_fee_multiplier: float,
) -> Mapping[str, Any]:
    value = _mapping(_strict_json(_read_file(path, "research spec"), "research spec"), "research spec")
    _exact_keys(value, ("schema", "profile", "candidate"), "research spec")
    if value["schema"] != RESEARCH_SPEC_SCHEMA:
        raise ResearchCandidateError("unsupported research spec schema")

    profile = _mapping(value["profile"], "research spec profile")
    profile_keys = (
        "name",
        "history_start_date",
        "smoke_days",
        "holdout_days",
        "stress_fee_multiplier",
        "max_drawdown_pct",
        "min_development_trades",
        "min_holdout_trades",
        "min_profit_factor",
    )
    _exact_keys(profile, profile_keys, "research spec profile")
    _nonempty_string(profile["name"], "profile name")
    _positive_integer(profile["smoke_days"], "profile smoke_days")
    holdout_days = _positive_integer(profile["holdout_days"], "profile holdout_days")
    profile_multiplier = _finite_number(
        profile["stress_fee_multiplier"], "profile stress_fee_multiplier", minimum=1.0
    )
    if profile_multiplier <= 1.0:
        raise ResearchCandidateError("profile stress_fee_multiplier must be greater than 1")
    if not math.isclose(profile_multiplier, stress_fee_multiplier, rel_tol=0.0, abs_tol=1e-15):
        raise ResearchCandidateError("CLI and profile stress_fee_multiplier disagree")
    max_drawdown = _finite_number(profile["max_drawdown_pct"], "profile max_drawdown_pct")
    if max_drawdown <= 0.0 or max_drawdown > 100.0:
        raise ResearchCandidateError("profile max_drawdown_pct must be in (0, 100]")
    for key in ("min_development_trades", "min_holdout_trades"):
        value_int = profile[key]
        if isinstance(value_int, bool) or not isinstance(value_int, int) or value_int < 0:
            raise ResearchCandidateError(f"profile {key} must be a non-negative integer")
    _finite_number(profile["min_profit_factor"], "profile min_profit_factor")

    development_start, _ = _parse_timerange(development_timerange, "development timerange")
    holdout_start, holdout_end = _parse_timerange(holdout_timerange, "holdout timerange")
    if (holdout_end - holdout_start).days != holdout_days:
        raise ResearchCandidateError("profile holdout_days does not match the holdout timerange")
    history_start_text = _nonempty_string(profile["history_start_date"], "profile history_start_date")
    try:
        history_start = datetime.strptime(history_start_text, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise ResearchCandidateError("profile history_start_date must use YYYY-MM-DD") from exc
    if history_start > development_start:
        raise ResearchCandidateError("profile history_start_date is after Development")

    candidate = _mapping(value["candidate"], "research spec candidate")
    candidate_keys = (
        "display_name",
        "class_name",
        "strategy_family",
        "idea",
        "expected_failure_mode",
        "metadata",
    )
    _exact_keys(candidate, candidate_keys, "research spec candidate")
    _nonempty_string(candidate["display_name"], "candidate display_name")
    if candidate["class_name"] != strategy:
        raise ResearchCandidateError("research spec Candidate class does not match --strategy")
    for key in ("strategy_family", "idea", "expected_failure_mode"):
        if candidate[key] is not None and (not isinstance(candidate[key], str) or not candidate[key]):
            raise ResearchCandidateError(f"candidate {key} must be null or a non-empty string")
    metadata = _mapping(candidate["metadata"], "candidate metadata")
    _walk_sensitive(metadata, "candidate metadata")
    return value


def _walk_sensitive(value: Any, label: str) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).lower().replace("-", "_")
            if normalized in _SENSITIVE_KEYS and child not in (None, "", [], {}):
                raise ResearchCandidateError(f"{label} contains non-empty credential field {key!r}")
            _walk_sensitive(child, label)
    elif isinstance(value, list):
        for child in value:
            _walk_sensitive(child, label)


def _validate_config(config: Mapping[str, Any], strategy: str) -> Tuple[float, Tuple[str, ...]]:
    _walk_sensitive(config, "Freqtrade config")
    if "add_config_files" in config:
        raise ResearchCandidateError("config add_config_files is outside the single-file boundary")
    _exact_keys(config, tuple(_BASE_CONFIG_KEYS), "Freqtrade config")
    if config.get("pairlists") != [{"method": "StaticPairList"}]:
        raise ResearchCandidateError("config must use exactly one StaticPairList")
    exchange = _mapping(config.get("exchange"), "config exchange")
    _exact_keys(exchange, tuple(_EXCHANGE_CONFIG_KEYS), "config exchange")
    entry_pricing = _mapping(config.get("entry_pricing"), "config entry_pricing")
    exit_pricing = _mapping(config.get("exit_pricing"), "config exit_pricing")
    unfilledtimeout = _mapping(config.get("unfilledtimeout"), "config unfilledtimeout")
    _exact_keys(entry_pricing, tuple(_PRICING_CONFIG_KEYS), "config entry_pricing")
    _exact_keys(exit_pricing, tuple(_PRICING_CONFIG_KEYS), "config exit_pricing")
    _exact_keys(unfilledtimeout, tuple(_TIMEOUT_CONFIG_KEYS), "config unfilledtimeout")
    pairs = exchange.get("pair_whitelist")
    if not isinstance(pairs, list) or len(pairs) != 1 or not isinstance(pairs[0], str) or not pairs[0]:
        raise ResearchCandidateError("config must select exactly one non-empty pair")
    if (
        exchange.get("name") != "okx"
        or config.get("trading_mode") != "futures"
        or config.get("margin_mode") != "isolated"
        or config.get("timeframe") != "5m"
    ):
        raise ResearchCandidateError("config must use okx/futures/isolated at 5m")
    if config.get("dry_run") is not True:
        raise ResearchCandidateError("config dry_run must be true")
    if exchange.get("enable_ws") not in (None, False):
        raise ResearchCandidateError("config exchange.enable_ws must be false")
    if config.get("strategy") not in (None, strategy):
        raise ResearchCandidateError("config strategy disagrees with --strategy")
    for section in ("api_server", "telegram", "webhook", "external_message_consumer"):
        section_value = config.get(section)
        if isinstance(section_value, dict) and section_value.get("enabled") is True:
            raise ResearchCandidateError(f"config {section} must not be enabled")
    if config.get("db_url") not in (None, ""):
        raise ResearchCandidateError("config db_url is outside the backtest-only boundary")
    fee = _finite_number(config.get("fee"), "config fee")
    if fee <= 0.0:
        raise ResearchCandidateError("config fee must be positive")
    if _finite_number(config.get("dry_run_wallet"), "config dry_run_wallet") <= 0.0:
        raise ResearchCandidateError("config dry_run_wallet must be positive")
    if _finite_number(config.get("stake_amount"), "config stake_amount") <= 0.0:
        raise ResearchCandidateError("config stake_amount must be positive")
    _positive_integer(config.get("max_open_trades"), "config max_open_trades")
    if config.get("dataformat_ohlcv", "feather") != "feather":
        raise ResearchCandidateError("the producer currently requires Feather OHLCV data")
    return fee, tuple(pairs)


def _validate_strategy(strategy_file: Path, strategy_path: Path, strategy: str) -> bytes:
    if _CLASS_NAME.fullmatch(strategy) is None:
        raise ResearchCandidateError("strategy must be a simple Python class name")
    try:
        strategy_file.relative_to(strategy_path)
    except ValueError as exc:
        raise ResearchCandidateError("strategy file must be contained by --strategy-path") from exc
    source = _read_file(strategy_file, "strategy source", limit=256 * 1024)
    try:
        text = source.decode("utf-8", "strict")
    except UnicodeDecodeError as exc:
        raise ResearchCandidateError("strategy source must be UTF-8") from exc
    if re.search(rf"(?m)^class\s+{re.escape(strategy)}\s*\(", text) is None:
        raise ResearchCandidateError("strategy source does not declare the selected class")
    return source


def _validate_hash_record(record: Any, label: str) -> Tuple[int, str, Optional[str]]:
    value = _mapping(record, label)
    allowed = {"bytes", "sha256", "role", "status"}
    unknown = set(value) - allowed
    if unknown:
        raise ResearchCandidateError(f"{label} contains unknown fields: {', '.join(sorted(unknown))}")
    size = value.get("bytes")
    digest = value.get("sha256")
    role = value.get("role")
    if isinstance(size, bool) or not isinstance(size, int) or size < 0:
        raise ResearchCandidateError(f"{label} bytes must be a non-negative integer")
    if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
        raise ResearchCandidateError(f"{label} sha256 is invalid")
    if role is not None and (not isinstance(role, str) or not role):
        raise ResearchCandidateError(f"{label} role must be a non-empty string")
    return size, digest, role


def _check_file_hash(path: Path, expected_size: int, expected_sha: str, label: str) -> None:
    data = _read_file(path, label, limit=max(MAX_RAW_ARCHIVE_BYTES, expected_size))
    if len(data) != expected_size or _sha256(data) != expected_sha:
        raise ResearchCandidateError(f"{label} does not match its retained receipt")


def _validate_data_provenance(
    provenance_path: Path,
    config_path: Path,
    research_spec_path: Path,
    strategy_file: Path,
    data_dir: Path,
    market_snapshot: Path,
    leverage_tiers: Path,
    pairs: Tuple[str, ...],
    development_timerange: str,
    holdout_timerange: str,
) -> Tuple[Mapping[str, Any], str, Mapping[str, Any]]:
    provenance_bytes = _read_file(provenance_path, "data provenance")
    value = _mapping(_strict_json(provenance_bytes, "data provenance"), "data provenance")
    _exact_keys(
        value,
        (
            "schema",
            "portable_retained_fixture",
            "source",
            "freqtrade",
            "contract",
            "files",
            "local_only_files",
        ),
        "data provenance",
    )
    if value["schema"] != RETAINED_DATA_SCHEMA:
        raise ResearchCandidateError("unsupported retained data provenance schema")
    if value["portable_retained_fixture"] not in ("RETAINED", "BLOCKED_LICENSE"):
        raise ResearchCandidateError("invalid portable_retained_fixture state")
    source = _mapping(value["source"], "data provenance source")
    if source.get("host") != "www.okx.com" or source.get("authentication") != "none":
        raise ResearchCandidateError("data provenance must attest public unauthenticated www.okx.com")
    if source.get("pair") != pairs[0]:
        raise ResearchCandidateError("data provenance pair disagrees with config")
    freqtrade = _mapping(value["freqtrade"], "data provenance freqtrade")
    _exact_keys(
        freqtrade,
        ("version", "tag", "commit", "dependencies"),
        "data provenance freqtrade",
    )
    if (
        freqtrade.get("version") != SUPPORTED_FREQTRADE_VERSION
        or freqtrade.get("tag") != SUPPORTED_FREQTRADE_VERSION
        or freqtrade.get("commit") != SUPPORTED_FREQTRADE_COMMIT
    ):
        raise ResearchCandidateError("data provenance does not bind the supported Freqtrade build")
    dependencies = _mapping(
        freqtrade["dependencies"], "data provenance freqtrade dependencies"
    )
    _exact_keys(
        dependencies,
        tuple(SUPPORTED_DEPENDENCIES),
        "data provenance freqtrade dependencies",
    )
    normalized_dependencies: Dict[str, str] = {}
    for name in SUPPORTED_DEPENDENCIES:
        version = dependencies[name]
        if not isinstance(version, str) or not version:
            raise ResearchCandidateError(
                f"data provenance dependency {name} must be a non-empty string"
            )
        if name == "python" and version.startswith("Python "):
            version = version.removeprefix("Python ")
        normalized_dependencies[name] = version
    if normalized_dependencies != SUPPORTED_DEPENDENCIES:
        raise ResearchCandidateError(
            "data provenance does not bind the supported dependency versions"
        )
    contract = _mapping(value["contract"], "data provenance contract")
    contract_keys = (
        "config",
        "strategy",
        "data_dir",
        "market_snapshot",
        "leverage_tiers",
        "development_timerange",
        "holdout_timerange",
        "timeframe",
    )
    _exact_keys(contract, contract_keys, "data provenance contract")
    if (
        contract["development_timerange"] != development_timerange
        or contract["holdout_timerange"] != holdout_timerange
        or contract["timeframe"] != "5m"
    ):
        raise ResearchCandidateError("data provenance scenario contract disagrees with CLI")

    root = provenance_path.parent
    tracked = _mapping(value["files"], "data provenance files")
    for name, record in tracked.items():
        relative = _relative_member(str(name), f"tracked receipt path {name!r}")
        expected_size, expected_sha, _ = _validate_hash_record(record, f"tracked receipt {name!r}")
        receipt_path = root / relative
        if receipt_path.is_symlink():
            raise ResearchCandidateError(f"tracked receipt path {name!r} must not be a symlink")
        resolved = receipt_path.resolve(strict=True)
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise ResearchCandidateError(f"tracked receipt path {name!r} escapes its root") from exc
        _check_file_hash(resolved, expected_size, expected_sha, f"tracked file {name!r}")

    config_relative = str(_relative_member(str(contract["config"]), "contract config"))
    strategy_relative = str(_relative_member(str(contract["strategy"]), "contract strategy"))
    expected_config = (root / config_relative).resolve(strict=True)
    expected_strategy = (root / strategy_relative).resolve(strict=True)
    if config_path != expected_config or strategy_file != expected_strategy:
        raise ResearchCandidateError("config/strategy paths do not match the retained receipt")
    try:
        research_spec_relative = str(research_spec_path.relative_to(root))
    except ValueError as exc:
        raise ResearchCandidateError("research spec must be contained by the retained receipt root") from exc
    missing_inputs = sorted(
        {config_relative, strategy_relative, research_spec_relative} - set(tracked)
    )
    if missing_inputs:
        raise ResearchCandidateError(
            "config, strategy, and research spec must all be bound by the retained receipt"
        )

    local_only = _mapping(value["local_only_files"], "data provenance local_only_files")
    data_prefix = _relative_member(str(contract["data_dir"]), "contract data_dir")
    expected_local_data: Dict[Path, Tuple[int, str]] = {}
    market_sha: Optional[str] = None
    tiers_sha: Optional[str] = None
    for name, record in local_only.items():
        relative = _relative_member(str(name), f"local-only receipt path {name!r}")
        expected_size, expected_sha, role = _validate_hash_record(
            record, f"local-only receipt {name!r}"
        )
        if role == "market_snapshot" or relative == _relative_member(
            str(contract["market_snapshot"]), "contract market_snapshot"
        ):
            if market_sha is not None:
                raise ResearchCandidateError("data provenance repeats the market snapshot")
            _check_file_hash(market_snapshot, expected_size, expected_sha, "market snapshot")
            market_sha = expected_sha
        elif role == "leverage_tiers" or relative == _relative_member(
            str(contract["leverage_tiers"]), "contract leverage_tiers"
        ):
            if tiers_sha is not None:
                raise ResearchCandidateError("data provenance repeats the leverage tiers snapshot")
            _check_file_hash(leverage_tiers, expected_size, expected_sha, "leverage tiers")
            tiers_sha = expected_sha
        else:
            try:
                under_data = relative.relative_to(data_prefix)
            except ValueError as exc:
                raise ResearchCandidateError(
                    f"local-only receipt {name!r} has no recognized input role"
                ) from exc
            expected_local_data[under_data] = (expected_size, expected_sha)
    if market_sha is None or tiers_sha is None:
        raise ResearchCandidateError("data provenance must bind market and leverage snapshots")
    if not expected_local_data:
        raise ResearchCandidateError("data provenance contains no local OHLCV inputs")
    actual_files: set[Path] = set()
    for path in data_dir.rglob("*"):
        if path.is_symlink():
            raise ResearchCandidateError("data directory must not contain symlinks")
        if path.is_file():
            actual_files.add(path.relative_to(data_dir))
    if actual_files != set(expected_local_data):
        raise ResearchCandidateError("data directory file set does not match the retained receipt")
    for relative, (expected_size, expected_sha) in expected_local_data.items():
        _check_file_hash(data_dir / relative, expected_size, expected_sha, f"market data {relative}")
    expected_runner_receipts = {
        "market_snapshot_sha256": market_sha,
        "leverage_tiers_sha256": tiers_sha,
        "data_sha256": {
            relative.as_posix(): expected_sha
            for relative, (_, expected_sha) in sorted(
                expected_local_data.items(), key=lambda item: item[0].as_posix()
            )
        },
    }
    return value, _sha256(provenance_bytes), expected_runner_receipts


def _minimal_environment(home: Path, python: Path, source: Path) -> Dict[str, str]:
    return {
        "HOME": str(home),
        "TMPDIR": str(home / "tmp"),
        "PATH": f"{python.parent}:/usr/bin:/bin",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONHASHSEED": "0",
        "PYTHONPATH": str(source),
        "TZ": "UTC",
    }


def _executable_symlink_chain(path: Path) -> Tuple[Path, ...]:
    """Return every literal pathname traversed before an executable target."""
    current = path
    chain: List[Path] = []
    seen: set[Path] = set()
    for _ in range(32):
        if current in seen:
            raise ResearchCandidateError("Freqtrade Python symlink chain contains a cycle")
        seen.add(current)
        chain.append(current)
        try:
            info = current.lstat()
        except OSError as exc:
            raise ResearchCandidateError(
                f"Freqtrade Python symlink chain cannot be inspected: {exc}"
            ) from exc
        if not stat.S_ISLNK(info.st_mode):
            if not stat.S_ISREG(info.st_mode):
                raise ResearchCandidateError(
                    "Freqtrade Python must resolve to a regular executable file"
                )
            return tuple(chain)
        try:
            target = Path(os.readlink(current))
        except OSError as exc:
            raise ResearchCandidateError(
                f"Freqtrade Python symlink cannot be read safely: {exc}"
            ) from exc
        if not target.is_absolute():
            target = current.parent / target
        current = Path(os.path.abspath(str(target)))
    raise ResearchCandidateError("Freqtrade Python symlink chain is too deep")


def _sandbox_policy(
    *,
    python: Path,
    source: Path,
    runner_script: Path,
    config_path: Path,
    data_dir: Path,
    user_data_dir: Path,
    strategy_path: Path,
    strategy_file: Path,
    export_dir: Path,
    market_snapshot: Path,
    leverage_tiers: Path,
    data_provenance: Path,
    home: Path,
    scenario_open_receipt: Optional[Path] = None,
) -> str:
    """Build a deny-by-default Seatbelt profile for one bounded scenario."""
    python_chain = _executable_symlink_chain(python)
    python_target = python.resolve(strict=True)
    if python.parent.name != "bin":
        raise ResearchCandidateError("Freqtrade Python must be the bin/python of a virtualenv")
    virtualenv_root = python.parent.parent.resolve(strict=True)
    pyvenv_config = virtualenv_root / "pyvenv.cfg"
    if pyvenv_config.is_symlink() or not pyvenv_config.is_file():
        raise ResearchCandidateError("Freqtrade Python virtualenv must contain regular pyvenv.cfg")
    site_candidates = list((virtualenv_root / "lib").glob("python*/site-packages"))
    if len(site_candidates) != 1 or site_candidates[0].is_symlink():
        raise ResearchCandidateError(
            "Freqtrade Python virtualenv must contain one regular site-packages directory"
        )
    site_packages = site_candidates[0].resolve(strict=True)
    try:
        site_packages.relative_to(virtualenv_root)
    except ValueError as exc:
        raise ResearchCandidateError("Freqtrade site-packages escapes its virtualenv") from exc
    if not site_packages.is_dir():
        raise ResearchCandidateError("Freqtrade site-packages must be a directory")
    python_runtime_root = python_target.parent.parent
    broad_roots = {
        Path("/"),
        Path("/Users"),
        Path("/private"),
        Path("/private/tmp"),
        Path("/Library"),
        Path("/opt"),
        Path("/opt/homebrew"),
        Path("/usr"),
        Path("/usr/local"),
        Path.home().resolve(),
    }
    sandbox_roots = {
        source,
        site_packages,
        python_runtime_root,
        data_dir,
        user_data_dir,
        strategy_path,
        export_dir.parent,
        home,
    }
    if sandbox_roots & broad_roots:
        raise ResearchCandidateError("sandbox read/write allowlist contains an unsafe broad root")
    read_subpaths = {
        source,
        site_packages,
        python_runtime_root,
        data_dir,
        user_data_dir,
        strategy_path,
        export_dir.parent,
        home,
    }
    read_literals = {
        *python_chain,
        python_target,
        runner_script,
        config_path,
        strategy_file,
        market_snapshot,
        leverage_tiers,
        data_provenance,
        pyvenv_config,
    }
    write_literals: set[Path] = set()
    if scenario_open_receipt is not None:
        write_literals.update((scenario_open_receipt, scenario_open_receipt.parent))
        read_literals.add(scenario_open_receipt.parent)
    process_executables = {*python_chain, python_target}
    metadata_paths: set[Path] = set()
    for allowed_path in read_subpaths | read_literals | write_literals | process_executables | {
        export_dir.parent,
        home,
    }:
        current = allowed_path
        while True:
            metadata_paths.add(current)
            if current.parent == current:
                break
            current = current.parent

    def allow_rules(operation: str, kind: str, paths: Iterable[Path]) -> List[str]:
        return [
            f"(allow {operation} ({kind} {json.dumps(str(path), ensure_ascii=True)}))"
            for path in sorted(paths, key=str)
        ]

    lines = [
        "(version 1)",
        "(deny default)",
        '(import "system.sb")',
    ]
    lines.extend(allow_rules("process-exec", "literal", process_executables))
    lines.extend(allow_rules("file-map-executable", "literal", process_executables))
    lines.extend(
        allow_rules(
            "file-map-executable",
            "subpath",
            {
                site_packages,
                python_runtime_root,
            },
        )
    )
    lines.extend(allow_rules("file-read*", "subpath", read_subpaths))
    lines.extend(allow_rules("file-read*", "literal", read_literals))
    lines.extend(
        allow_rules(
            "file-read-metadata file-test-existence",
            "literal",
            metadata_paths,
        )
    )
    lines.extend(allow_rules("file-write*", "subpath", {export_dir.parent, home}))
    lines.extend(allow_rules("file-write*", "literal", write_literals))
    lines.extend(("(deny network*)", ""))
    return "\n".join(lines)


def _run_command(
    runner: CommandRunner,
    command: Sequence[str],
    *,
    cwd: Path,
    env: Optional[Mapping[str, str]] = None,
) -> subprocess.CompletedProcess:
    try:
        return runner(
            list(command),
            cwd=str(cwd),
            env=None if env is None else dict(env),
            capture_output=True,
            text=True,
            check=False,
            timeout=SCENARIO_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise ResearchCandidateError(
            f"subprocess exceeded the fixed {SCENARIO_TIMEOUT_SECONDS}-second limit"
        ) from exc
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        raise ResearchCandidateError(f"subprocess could not start safely: {exc}") from exc


def _source_tree_sha256(root: Path) -> str:
    digest = hashlib.sha256(b"freqtrade-lab-source-tree-v1\0")
    files: List[Path] = []
    total = 0
    try:
        for path in root.rglob("*"):
            if path.is_symlink():
                raise ResearchCandidateError("Freqtrade source snapshot must not contain symlinks")
            if path.is_file():
                files.append(path)
    except OSError as exc:
        raise ResearchCandidateError(f"Freqtrade source snapshot cannot be inspected: {exc}") from exc
    if not files or not (root / "freqtrade" / "__init__.py").is_file():
        raise ResearchCandidateError("Freqtrade source snapshot is incomplete")
    for path in sorted(files, key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix()
        data = _read_file(path, f"Freqtrade source snapshot {relative}", MAX_SOURCE_ARCHIVE_BYTES)
        total += len(data)
        if total > MAX_SOURCE_ARCHIVE_BYTES:
            raise ResearchCandidateError("Freqtrade source snapshot exceeds the size limit")
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(len(data)).encode("ascii"))
        digest.update(b"\0")
        digest.update(data)
        digest.update(b"\0")
    return digest.hexdigest()


def _exact_git_command(arguments: Sequence[str]) -> List[str]:
    return [
        str(DEFAULT_GIT_EXECUTABLE),
        "--no-replace-objects",
        "-c",
        "core.fsmonitor=false",
        "-c",
        "core.hooksPath=/dev/null",
        "-c",
        "core.attributesFile=/dev/null",
        *arguments,
    ]


def _git_environment(git_home: Path) -> Dict[str, str]:
    return {
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_PAGER": "",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_TERMINAL_PROMPT": "0",
        "HOME": str(git_home),
        "LC_ALL": "C",
        "PATH": "/usr/bin:/bin",
        "TMPDIR": str(git_home / "tmp"),
        "TZ": "UTC",
    }


def _git_sandbox_policy(source: Path, git_home: Path) -> str:
    """Allow only the fixed Git binary to inspect one supplied checkout."""
    git_executable = DEFAULT_GIT_EXECUTABLE.resolve(strict=True)
    command_line_tools = Path("/Library/Developer/CommandLineTools")
    read_subpaths = {source, git_home, command_line_tools}
    metadata_paths: set[Path] = set()
    for allowed_path in read_subpaths | {git_executable}:
        current = allowed_path
        while True:
            metadata_paths.add(current)
            if current.parent == current:
                break
            current = current.parent

    def rules(operation: str, kind: str, paths: Iterable[Path]) -> List[str]:
        return [
            f"(allow {operation} ({kind} {json.dumps(str(path), ensure_ascii=True)}))"
            for path in sorted(paths, key=str)
        ]

    lines = [
        "(version 1)",
        "(deny default)",
        '(import "system.sb")',
    ]
    lines.extend(rules("process-exec", "literal", {git_executable}))
    lines.extend(rules("file-map-executable", "literal", {git_executable}))
    lines.extend(rules("file-read*", "subpath", read_subpaths))
    lines.extend(
        rules(
            "file-read-metadata file-test-existence",
            "literal",
            metadata_paths,
        )
    )
    lines.extend(rules("file-write*", "subpath", {git_home}))
    lines.extend(("(deny network*)", ""))
    return "\n".join(lines)


def _prepare_freqtrade_source_snapshot(
    source: Path, destination: Path, git_home: Path, sandbox_exec: Path
) -> str:
    """Export tracked package bytes without trusting supplied Git metadata."""
    git_home.mkdir()
    (git_home / "tmp").mkdir()
    environment = _git_environment(git_home)
    sandbox_policy = _git_sandbox_policy(source, git_home)

    def sandboxed_git(arguments: Sequence[str]) -> List[str]:
        return [
            str(sandbox_exec),
            "-p",
            sandbox_policy,
            *_exact_git_command(arguments),
        ]

    def git_text(arguments: Sequence[str], label: str) -> str:
        try:
            completed = subprocess.run(
                sandboxed_git(arguments),
                cwd=str(source),
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            raise ResearchCandidateError(f"{label} could not run safely: {exc}") from exc
        if completed.returncode != 0:
            raise ResearchCandidateError(f"{label} failed")
        return completed.stdout.strip()

    commit = git_text(("rev-parse", "HEAD"), "Freqtrade commit check")
    tree = git_text(("rev-parse", "HEAD^{tree}"), "Freqtrade tree check")
    tag = git_text(
        ("describe", "--exact-match", "--tags", "HEAD"),
        "Freqtrade tag check",
    )
    dirty = git_text(
        ("status", "--porcelain=v1", "--untracked-files=all"),
        "Freqtrade source cleanliness check",
    )
    if (
        commit != SUPPORTED_FREQTRADE_COMMIT
        or tree != SUPPORTED_FREQTRADE_TREE
        or tag != SUPPORTED_FREQTRADE_VERSION
    ):
        raise ResearchCandidateError(
            f"Freqtrade source must be tag {SUPPORTED_FREQTRADE_VERSION} at "
            f"{SUPPORTED_FREQTRADE_COMMIT} with tree {SUPPORTED_FREQTRADE_TREE}"
        )
    if dirty:
        raise ResearchCandidateError("Freqtrade source must be completely clean")

    try:
        archive = subprocess.run(
            sandboxed_git(("archive", "--format=tar", "HEAD", "freqtrade")),
            cwd=str(source),
            env=environment,
            capture_output=True,
            check=False,
        )
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        raise ResearchCandidateError(f"Freqtrade source archive could not run safely: {exc}") from exc
    if archive.returncode != 0 or not archive.stdout:
        raise ResearchCandidateError("Freqtrade source archive failed")
    if len(archive.stdout) > MAX_SOURCE_ARCHIVE_BYTES:
        raise ResearchCandidateError("Freqtrade source archive exceeds the size limit")

    destination.mkdir()
    seen: set[str] = set()
    total = 0
    try:
        with tarfile.open(fileobj=io.BytesIO(archive.stdout), mode="r:") as unit:
            for member in unit:
                name = member.name.rstrip("/")
                relative = _relative_member(name, "Freqtrade source archive member")
                if relative.parts[0] != "freqtrade" or name in seen:
                    raise ResearchCandidateError(
                        "Freqtrade source archive contains an unexpected member"
                    )
                seen.add(name)
                target = destination / relative
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                if not member.isfile():
                    raise ResearchCandidateError(
                        "Freqtrade source archive contains a non-regular member"
                    )
                extracted = unit.extractfile(member)
                if extracted is None:
                    raise ResearchCandidateError(
                        "Freqtrade source archive member cannot be read"
                    )
                data = extracted.read(MAX_SOURCE_ARCHIVE_BYTES + 1)
                if len(data) != member.size or len(data) > MAX_SOURCE_ARCHIVE_BYTES:
                    raise ResearchCandidateError(
                        "Freqtrade source archive member size is invalid"
                    )
                total += len(data)
                if total > MAX_SOURCE_ARCHIVE_BYTES:
                    raise ResearchCandidateError(
                        "Freqtrade source archive expands beyond the size limit"
                    )
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists() or target.is_symlink():
                    raise ResearchCandidateError(
                        "Freqtrade source archive repeats an output path"
                    )
                target.write_bytes(data)
                target.chmod(0o644)
    except ResearchCandidateError:
        raise
    except (OSError, tarfile.TarError) as exc:
        raise ResearchCandidateError(f"Freqtrade source archive is invalid: {exc}") from exc
    return _source_tree_sha256(destination)


def _runtime_config(
    base: Mapping[str, Any],
    *,
    config_source: Path,
    data_dir: Path,
    user_data_dir: Path,
    strategy_path: Path,
    strategy: str,
    timerange: str,
    fee: float,
    export_dir: Path,
) -> Mapping[str, Any]:
    config = copy.deepcopy(dict(base))
    config["config_files"] = [str(config_source)]
    config["datadir"] = str(data_dir)
    config["user_data_dir"] = str(user_data_dir)
    config["strategy_path"] = str(strategy_path)
    config["strategy"] = strategy
    config["timerange"] = timerange
    config["fee"] = fee
    config["export"] = "trades"
    config["exportdirectory"] = str(export_dir)
    config["dataformat_ohlcv"] = "feather"
    config["disableparamexport"] = True
    config["backtest_cache"] = "none"
    exchange = dict(_mapping(config.get("exchange"), "config exchange"))
    exchange["enable_ws"] = False
    config["exchange"] = exchange
    return config


def _last_json_line(stdout: str, label: str) -> Mapping[str, Any]:
    for line in reversed(stdout.splitlines()):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise ResearchCandidateError(f"{label} did not emit its final JSON receipt")


def _redact(text: str, replacements: Mapping[Path, str]) -> str:
    result = text
    for path, replacement in sorted(replacements.items(), key=lambda item: len(str(item[0])), reverse=True):
        result = result.replace(str(path), replacement)
    return result


def _run_scenario(
    *,
    scenario: str,
    timerange: str,
    fee: float,
    python: Path,
    source: Path,
    source_tree_sha256: str,
    runner_script: Path,
    runner_sha256: str,
    sandbox_exec: Path,
    config_path: Path,
    data_dir: Path,
    user_data_dir: Path,
    strategy_path: Path,
    strategy_file: Path,
    strategy_sha256: str,
    strategy: str,
    export_dir: Path,
    market_snapshot: Path,
    leverage_tiers: Path,
    data_provenance: Path,
    home: Path,
    command_runner: CommandRunner,
    allow_zero_trades: bool = False,
    scenario_open_receipt: Optional[Path] = None,
) -> Tuple[subprocess.CompletedProcess, Mapping[str, Any], Tuple[str, ...]]:
    sandbox_policy = _sandbox_policy(
        python=python,
        source=source,
        runner_script=runner_script,
        config_path=config_path,
        data_dir=data_dir,
        user_data_dir=user_data_dir,
        strategy_path=strategy_path,
        strategy_file=strategy_file,
        export_dir=export_dir,
        market_snapshot=market_snapshot,
        leverage_tiers=leverage_tiers,
        data_provenance=data_provenance,
        home=home,
        scenario_open_receipt=scenario_open_receipt,
    )
    command = (
        str(sandbox_exec),
        "-p",
        sandbox_policy,
        str(python),
        str(runner_script),
        "--runner-sha256",
        runner_sha256,
        "--freqtrade-source",
        str(source),
        "--source-tree-sha256",
        source_tree_sha256,
        "--scenario",
        scenario,
        "--config",
        str(config_path),
        "--data-dir",
        str(data_dir),
        "--user-data-dir",
        str(user_data_dir),
        "--strategy-path",
        str(strategy_path),
        "--strategy-file",
        str(strategy_file),
        "--strategy-sha256",
        strategy_sha256,
        "--strategy",
        strategy,
        "--timerange",
        timerange,
        "--fee",
        format(fee, ".17g"),
        "--export-dir",
        str(export_dir),
        "--market-snapshot",
        str(market_snapshot),
        "--leverage-tiers",
        str(leverage_tiers),
        "--data-provenance",
        str(data_provenance),
    )
    if allow_zero_trades:
        command += ("--allow-zero-trades",)
    if scenario_open_receipt is not None:
        command += ("--scenario-open-receipt", str(scenario_open_receipt))
    completed = _run_command(
        command_runner,
        command,
        cwd=source,
        env=_minimal_environment(home, python, source),
    )
    redacted_shape = tuple(
        "<deny-by-default-sandbox-profile>"
        if part == sandbox_policy
        else _redact(
            part,
            {
                python: "<freqtrade-python>",
                source: "<freqtrade-source>",
                runner_script: "<producer-runner>",
                config_path: "<scenario-config>",
                data_dir: "<data-dir>",
                user_data_dir: "<user-data-dir>",
                strategy_path: "<strategy-path>",
                strategy_file: "<strategy-file>",
                export_dir: "<raw-export-dir>",
                market_snapshot: "<market-snapshot>",
                leverage_tiers: "<leverage-tiers>",
                data_provenance: "<data-provenance>",
                sandbox_exec: "<sandbox-exec>",
                **(
                    {scenario_open_receipt: "<scenario-open-receipt>"}
                    if scenario_open_receipt is not None
                    else {}
                ),
            },
        )
        for part in command
    )
    if completed.returncode != 0:
        raise ResearchCandidateError(
            f"{scenario} backtesting failed with exit code {completed.returncode}"
        )
    summary = _last_json_line(completed.stdout, f"{scenario} backtesting")
    return completed, summary, redacted_shape


def _remove_sensitive_keys(value: Any) -> Any:
    if isinstance(value, dict):
        result = {}
        for key, child in value.items():
            normalized = str(key).lower().replace("-", "_")
            if normalized in _SENSITIVE_KEYS:
                continue
            result[key] = _remove_sensitive_keys(child)
        return result
    if isinstance(value, list):
        return [_remove_sensitive_keys(child) for child in value]
    return value


def _reject_absolute_strings(value: Any, label: str) -> None:
    if isinstance(value, dict):
        for child in value.values():
            _reject_absolute_strings(child, label)
    elif isinstance(value, list):
        for child in value:
            _reject_absolute_strings(child, label)
    elif isinstance(value, str):
        if value.startswith("/") or _WINDOWS_ABSOLUTE.match(value):
            raise ResearchCandidateError(f"{label} still contains an absolute path")


def _iso_z(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ResearchCandidateError(f"{label} must be a timestamp string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ResearchCandidateError(f"{label} is not an ISO timestamp") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    parsed = parsed.astimezone(timezone.utc)
    return parsed.isoformat(timespec="seconds").replace("+00:00", "Z")


def _validate_scenario_open_receipt(
    path: Path,
    *,
    scenario: str,
    timerange: str,
    strategy: str,
    strategy_sha256: str,
    data_provenance_sha256: str,
) -> str:
    data = _read_file(path, "scenario open receipt")
    value = _mapping(
        _strict_json(data, "scenario open receipt"), "scenario open receipt"
    )
    _exact_keys(
        value,
        (
            "schema",
            "scenario",
            "timerange",
            "strategy",
            "strategy_sha256",
            "data_provenance_sha256",
            "exclusive_stop_utc",
            "meaning",
            "opened_at_utc",
        ),
        "scenario open receipt",
    )
    _, stop = _parse_timerange(timerange, "scenario open receipt timerange")
    if (
        value["schema"] != "freqtrade-lab-scenario-open-v1"
        or value["scenario"] != scenario
        or value["timerange"] != timerange
        or value["strategy"] != strategy
        or value["strategy_sha256"] != strategy_sha256
        or value["data_provenance_sha256"] != data_provenance_sha256
        or value["exclusive_stop_utc"]
        != stop.isoformat().replace("+00:00", "Z")
        or value["meaning"]
        != (
            "one-shot scenario execution budget was consumed before retained market data "
            "validation began"
        )
    ):
        raise ResearchCandidateError("scenario open receipt disagrees with the invocation")
    _iso_z(value["opened_at_utc"], "scenario open receipt opened_at_utc")
    return _sha256(data)


def _zip_bytes(members: Sequence[Tuple[str, bytes]]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED, allowZip64=False) as archive:
        for name, data in members:
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            info.compress_type = zipfile.ZIP_STORED
            archive.writestr(info, data)
    return output.getvalue()


def _validate_runner_summary(
    summary: Mapping[str, Any],
    *,
    scenario: str,
    timerange: str,
    data_provenance_sha256: str,
    expected_input_receipts: Mapping[str, Any],
    expected_source_tree_sha256: str,
    expected_runner_sha256: str,
    allow_zero_trades: bool = False,
) -> Tuple[str, str, int]:
    if not isinstance(allow_zero_trades, bool):
        raise ResearchCandidateError("allow_zero_trades must be boolean")
    _exact_keys(
        summary,
        (
            "scenario",
            "archive",
            "metadata",
            "total_trades",
            "dependencies",
            "official_core",
            "freqtrade_commit",
            "source_tree_sha256",
            "runner_sha256",
            "data_provenance_sha256",
            "input_receipts",
            "scenario_data_view",
        ),
        "runner receipt",
    )
    _walk_sensitive(summary, "runner receipt")
    _reject_absolute_strings(summary, "runner receipt")
    if summary["scenario"] != scenario:
        raise ResearchCandidateError("runner receipt scenario disagrees with the invocation")
    if summary["freqtrade_commit"] != SUPPORTED_FREQTRADE_COMMIT:
        raise ResearchCandidateError("runner receipt does not bind the supported Freqtrade commit")
    if summary["source_tree_sha256"] != expected_source_tree_sha256:
        raise ResearchCandidateError("runner receipt does not bind the exported source snapshot")
    if summary["runner_sha256"] != expected_runner_sha256:
        raise ResearchCandidateError("runner receipt does not bind the producer runner bytes")
    if summary["data_provenance_sha256"] != data_provenance_sha256:
        raise ResearchCandidateError("runner receipt does not bind the retained data provenance")

    dependencies = _mapping(summary["dependencies"], "runner dependencies")
    expected_dependencies = {
        "freqtrade": SUPPORTED_FREQTRADE_VERSION,
        **SUPPORTED_DEPENDENCIES,
    }
    _exact_keys(dependencies, tuple(expected_dependencies), "runner dependencies")
    if dict(dependencies) != expected_dependencies:
        raise ResearchCandidateError("runner dependencies disagree with the supported build")
    official_core = _mapping(summary["official_core"], "runner official_core")
    if dict(official_core) != SUPPORTED_OFFICIAL_CORE:
        raise ResearchCandidateError("runner official_core receipt is incomplete or unexpected")
    input_receipts = _mapping(summary["input_receipts"], "runner input_receipts")
    if dict(input_receipts) != dict(expected_input_receipts):
        raise ResearchCandidateError("runner input receipts disagree with producer validation")

    scenario_view = _mapping(summary["scenario_data_view"], "runner scenario_data_view")
    _exact_keys(
        scenario_view,
        ("exclusive_stop_utc", "files"),
        "runner scenario_data_view",
    )
    _, expected_stop = _parse_timerange(timerange, "runner timerange")
    expected_stop_text = expected_stop.isoformat().replace("+00:00", "Z")
    if scenario_view["exclusive_stop_utc"] != expected_stop_text:
        raise ResearchCandidateError("runner scenario data view has the wrong exclusive stop")
    view_files = _mapping(scenario_view["files"], "runner scenario_data_view files")
    expected_data = _mapping(
        expected_input_receipts["data_sha256"], "expected input data receipts"
    )
    if set(view_files) != set(expected_data):
        raise ResearchCandidateError("runner scenario data view file set is incomplete")
    for name, record_value in view_files.items():
        _relative_member(str(name), f"runner scenario data view path {name!r}")
        record = _mapping(record_value, f"runner scenario data view receipt {name!r}")
        _exact_keys(
            record,
            ("rows", "sha256"),
            f"runner scenario data view receipt {name!r}",
        )
        _positive_integer(record["rows"], f"runner scenario data view rows {name!r}")
        if not isinstance(record["sha256"], str) or _SHA256.fullmatch(record["sha256"]) is None:
            raise ResearchCandidateError(
                f"runner scenario data view sha256 {name!r} is invalid"
            )

    total_trades_value = summary["total_trades"]
    if (
        isinstance(total_trades_value, bool)
        or not isinstance(total_trades_value, int)
        or total_trades_value < 0
    ):
        raise ResearchCandidateError("runner total_trades must be a non-negative integer")
    total_trades = total_trades_value
    if total_trades == 0 and not allow_zero_trades:
        raise ResearchCandidateError("runner total_trades must be a positive integer")
    archive_name = _nonempty_string(summary["archive"], "runner archive")
    metadata_name = _nonempty_string(summary["metadata"], "runner metadata")
    return archive_name, metadata_name, total_trades


def _database_signature(database: Path) -> Tuple[Tuple[str, Tuple[str, ...]], ...]:
    """Read a stable business-row signature without creating or mutating a database."""
    tables = (
        "research_profiles",
        "generation_runs",
        "candidates",
        "research_runs",
        "backtest_executions",
        "releases",
    )
    try:
        connection = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)
        try:
            return tuple(
                (
                    table,
                    tuple(
                        str(row[0])
                        for row in connection.execute(
                            f"SELECT id FROM {table} ORDER BY id"
                        ).fetchall()
                    ),
                )
                for table in tables
            )
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise ResearchCandidateError(
            f"database state cannot be inspected safely: {exc}"
        ) from exc


def _validate_raw_zip_infos(infos: Sequence[zipfile.ZipInfo]) -> None:
    if not infos or len(infos) > MAX_RAW_ZIP_MEMBERS:
        raise ResearchCandidateError("raw Freqtrade archive member count is unsafe")
    names: set[str] = set()
    total = 0
    for info in infos:
        name = info.filename
        _relative_member(name, "raw Freqtrade archive member")
        if name in names or info.is_dir() or name.endswith("/"):
            raise ResearchCandidateError(
                "raw Freqtrade archive contains duplicate or non-file members"
            )
        names.add(name)
        if info.flag_bits & 0x1:
            raise ResearchCandidateError("raw Freqtrade archive must not be encrypted")
        mode = info.external_attr >> 16
        file_type = stat.S_IFMT(mode)
        if file_type not in (0, stat.S_IFREG):
            raise ResearchCandidateError(
                "raw Freqtrade archive contains a non-regular member"
            )
        if info.file_size < 0 or info.file_size > MAX_RAW_ZIP_MEMBER_BYTES:
            raise ResearchCandidateError(
                "raw Freqtrade archive member exceeds the expansion limit"
            )
        total += info.file_size
        if total > MAX_RAW_ZIP_TOTAL_BYTES:
            raise ResearchCandidateError(
                "raw Freqtrade archive exceeds the total expansion limit"
            )
        if info.file_size > max(
            1024, info.compress_size * MAX_RAW_ZIP_COMPRESSION_RATIO
        ):
            raise ResearchCandidateError(
                "raw Freqtrade archive compression ratio is unsafe"
            )


def _sanitize_raw_artifact(
    *,
    scenario: str,
    slug: str,
    raw_dir: Path,
    runner_summary: Mapping[str, Any],
    completed: subprocess.CompletedProcess,
    command_shape: Tuple[str, ...],
    bundle_dir: Path,
    strategy: str,
    strategy_source: bytes,
    data_provenance: Mapping[str, Any],
    data_provenance_sha256: str,
    expected_input_receipts: Mapping[str, Any],
    source_tree_sha256: str,
    implementation_receipts: Mapping[str, Any],
    timerange: str,
    network_policy: str,
    allow_zero_trades: bool = False,
) -> ProducedArtifact:
    raw_archive_name, raw_metadata_name, runner_total_trades = _validate_runner_summary(
        runner_summary,
        scenario=scenario,
        timerange=timerange,
        data_provenance_sha256=data_provenance_sha256,
        expected_input_receipts=expected_input_receipts,
        expected_source_tree_sha256=source_tree_sha256,
        expected_runner_sha256=str(implementation_receipts["runner"]["sha256"]),
        allow_zero_trades=allow_zero_trades,
    )
    raw_archive = raw_dir / _relative_member(raw_archive_name, "runner archive")
    raw_metadata = raw_dir / _relative_member(raw_metadata_name, "runner metadata")
    raw_archive_bytes = _read_file(raw_archive, "raw Freqtrade archive", MAX_RAW_ARCHIVE_BYTES)
    raw_metadata_bytes = _read_file(raw_metadata, "raw Freqtrade metadata")
    metadata_value = _strict_json(raw_metadata_bytes, "raw Freqtrade metadata")
    _walk_sensitive(metadata_value, "raw Freqtrade metadata")
    _reject_absolute_strings(metadata_value, "raw Freqtrade metadata")

    try:
        with zipfile.ZipFile(io.BytesIO(raw_archive_bytes), "r") as archive:
            _validate_raw_zip_infos(archive.infolist())
            if archive.testzip() is not None:
                raise ResearchCandidateError("raw Freqtrade archive failed CRC validation")
            names = archive.namelist()
            report_names = [name for name in names if name.endswith(".json") and not name.endswith("_config.json")]
            config_names = [name for name in names if name.endswith("_config.json")]
            strategy_names = [name for name in names if name.endswith(f"_{strategy}.py")]
            if len(report_names) != 1 or len(config_names) != 1 or len(strategy_names) != 1:
                raise ResearchCandidateError("raw Freqtrade archive lacks one exact report/config/strategy unit")
            report_bytes = archive.read(report_names[0])
            raw_config_bytes = archive.read(config_names[0])
            exported_strategy = archive.read(strategy_names[0])
    except ResearchCandidateError:
        raise
    except (OSError, KeyError, RuntimeError, zipfile.BadZipFile) as exc:
        raise ResearchCandidateError(f"raw Freqtrade archive cannot be read safely: {exc}") from exc
    if exported_strategy != strategy_source:
        raise ResearchCandidateError("Freqtrade exported strategy source differs from Candidate input")

    report = _mapping(_strict_json(report_bytes, "Freqtrade report"), "Freqtrade report")
    raw_config = _mapping(_strict_json(raw_config_bytes, "Freqtrade config export"), "Freqtrade config export")
    sanitized_config = _mapping(_remove_sensitive_keys(raw_config), "sanitized config")
    sanitized_config = dict(sanitized_config)
    sanitized_config["config_files"] = ["config.json"]
    sanitized_config["datadir"] = "data/okx"
    sanitized_config["exportdirectory"] = "backtest_results"
    sanitized_config["strategy_path"] = "strategies"
    sanitized_config["user_data_dir"] = "user_data"
    _walk_sensitive(sanitized_config, "sanitized config")
    _reject_absolute_strings(sanitized_config, "sanitized config")
    config_bytes = _canonical_bytes(sanitized_config)

    stem = f"backtest-result-{slug}"
    report_member = f"{stem}.json"
    config_member = f"{stem}_config.json"
    strategy_member = f"{stem}_{strategy}.py"
    final_archive_bytes = _zip_bytes(
        (
            (report_member, report_bytes),
            (config_member, config_bytes),
            (strategy_member, strategy_source),
        )
    )
    archive_name = f"{stem}.zip"
    metadata_name = f"{stem}.meta.json"
    (bundle_dir / archive_name).write_bytes(final_archive_bytes)
    (bundle_dir / metadata_name).write_bytes(raw_metadata_bytes)

    strategies = _mapping(report.get("strategy"), "report strategy")
    if set(strategies) != {strategy}:
        raise ResearchCandidateError("report must contain exactly the selected strategy")
    result = _mapping(strategies[strategy], "strategy result")
    total_trades = result.get("total_trades")
    wins = result.get("wins")
    draws = result.get("draws")
    losses = result.get("losses")
    for value, label in (
        (total_trades, "total_trades"),
        (wins, "wins"),
        (draws, "draws"),
        (losses, "losses"),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ResearchCandidateError(f"strategy result {label} is invalid")
    if total_trades == 0 and not allow_zero_trades:
        raise ResearchCandidateError("each scenario must produce at least one trade")
    if total_trades != runner_total_trades:
        raise ResearchCandidateError("runner total_trades disagrees with the native report")
    exchange = _mapping(sanitized_config.get("exchange"), "sanitized config exchange")
    contract = {
        "strategy": strategy,
        "exchange": sanitized_config.get("exchange", {}).get("name"),
        "trading_mode": sanitized_config.get("trading_mode"),
        "margin_mode": sanitized_config.get("margin_mode"),
        "pairs": exchange.get("pair_whitelist"),
        "timeframe": sanitized_config.get("timeframe"),
        "detail_timeframe": sanitized_config.get("timeframe_detail"),
        "timerange": sanitized_config.get("timerange"),
        "backtest_start_utc": _iso_z(result.get("backtest_start"), "backtest_start"),
        "backtest_end_utc": _iso_z(result.get("backtest_end"), "backtest_end"),
        "starting_balance": sanitized_config.get("dry_run_wallet"),
        "stake_amount": sanitized_config.get("stake_amount"),
        "max_open_trades": sanitized_config.get("max_open_trades"),
        "fee": sanitized_config.get("fee"),
        "report_total_trades": total_trades,
        "wins": wins,
        "draws": draws,
        "losses": losses,
    }
    source = _mapping(data_provenance["source"], "data provenance source")
    provenance = {
        "schema": "freqtrade-lab-fixture-provenance-v1",
        "acquisition": {
            "host": "www.okx.com",
            "authentication": "none",
            "pair": source.get("pair"),
            "instrument_id": source.get("instrument_id"),
            "retained_data_provenance_sha256": data_provenance_sha256,
            "portable_retained_fixture": data_provenance["portable_retained_fixture"],
        },
        "freqtrade": {
            "version": SUPPORTED_FREQTRADE_VERSION,
            "tag": SUPPORTED_FREQTRADE_VERSION,
            "commit": SUPPORTED_FREQTRADE_COMMIT,
            "source_tree_sha256": source_tree_sha256,
            "dependencies": runner_summary.get("dependencies", {}),
        },
        "artifact": {
            "archive": archive_name,
            "archive_sha256": _sha256(final_archive_bytes),
            "metadata": metadata_name,
            "metadata_sha256": _sha256(raw_metadata_bytes),
            "members": {
                report_member: _sha256(report_bytes),
                config_member: _sha256(config_bytes),
                strategy_member: _sha256(strategy_source),
            },
            "raw_archive_sha256": _sha256(raw_archive_bytes),
            "raw_config_member_sha256": _sha256(raw_config_bytes),
            "removed_raw_members": sorted(
                name for name in names if name not in (report_names[0], config_names[0], strategy_names[0])
            ),
            "sanitized_config_member_sha256": _sha256(config_bytes),
        },
        "contract": contract,
        "fee_evidence": {
            "kind": "configured parser-fixture assumption",
            "rate": sanitized_config.get("fee"),
            "claim": "not an observed or public OKX account fee rate",
        },
        "generation": {
            "scenario": scenario,
            "command_shape": list(command_shape),
            "network_policy": network_policy,
            "candidate_code_trust": (
                "SHA-bound user-reviewed input; sandboxing contains filesystem and network "
                "effects but does not attest result integrity against adversarial strategy code"
            ),
            "implementation_receipts": implementation_receipts,
            "return_code": completed.returncode,
            "stdout_sha256": _sha256(completed.stdout.encode("utf-8")),
            "stderr_sha256": _sha256(completed.stderr.encode("utf-8")),
            "official_core": runner_summary.get("official_core"),
            "scenario_data_view": runner_summary.get("scenario_data_view"),
        },
        "sanitization": {
            "config_path_replacements": {
                "config_files": ["config.json"],
                "datadir": "data/okx",
                "exportdirectory": "backtest_results",
                "strategy_path": "strategies",
                "user_data_dir": "user_data",
            },
            "metadata_changed": False,
            "report_changed": False,
            "strategy_changed": False,
            "zip_compression": "stored",
            "zip_member_mode": "0100644",
            "zip_timestamp": "1980-01-01T00:00:00",
        },
        "license": {
            "upstream": "Freqtrade",
            "license": "GPL-3.0-only",
            "source_commit": SUPPORTED_FREQTRADE_COMMIT,
        },
    }
    provenance_bytes = _canonical_bytes(provenance)
    provenance_name = f"{stem}.provenance.json"
    (bundle_dir / provenance_name).write_bytes(provenance_bytes)
    provenance_sha = _sha256(provenance_bytes)

    parsed = parse_backtest_artifact(
        bundle_dir,
        Path(archive_name),
        strategy,
        SUPPORTED_FREQTRADE_VERSION,
        provenance_sha,
        allow_zero_trades=allow_zero_trades,
    )
    return ProducedArtifact(
        scenario=scenario,
        archive=archive_name,
        archive_sha256=parsed.archive_sha256,
        provenance_sha256=provenance_sha,
        total_trades=parsed.total_trades,
    )


def _scan_for_path_leaks(root: Path, sensitive_paths: Sequence[Path]) -> None:
    needles = [str(path).encode("utf-8") for path in sensitive_paths]
    needles.extend((b"/Users/", b"/private/tmp/", b"\\Users\\"))
    for path in sorted(root.iterdir()):
        if path.suffix == ".zip":
            with zipfile.ZipFile(path, "r") as archive:
                payloads = [(f"{path.name}!/{name}", archive.read(name)) for name in archive.namelist()]
        else:
            payloads = [(path.name, path.read_bytes())]
        for label, data in payloads:
            for needle in needles:
                if needle and needle in data:
                    raise ResearchCandidateError(f"published evidence leaks a private path in {label}")


def run_research_candidate(
    *,
    freqtrade_python: PathLike,
    freqtrade_source: PathLike,
    config: PathLike,
    data_dir: PathLike,
    strategy_path: PathLike,
    strategy_file: PathLike,
    strategy: str,
    research_spec: PathLike,
    data_provenance: PathLike,
    market_snapshot: PathLike,
    leverage_tiers: PathLike,
    development_timerange: str,
    holdout_timerange: str,
    stress_fee_multiplier: float,
    output_dir: PathLike,
    database: Optional[PathLike] = None,
    sandbox_exec: PathLike = DEFAULT_SANDBOX_EXEC,
    runner_script: PathLike = DEFAULT_RUNNER,
    command_runner: CommandRunner = subprocess.run,
    scenario_open_receipts: Optional[Mapping[str, PathLike]] = None,
) -> ResearchCandidateResult:
    """Run, validate, atomically publish, and optionally import one Candidate."""
    python_path = _resolve_executable(freqtrade_python, "Freqtrade Python")
    source_path = _resolve_directory(freqtrade_source, "Freqtrade source")
    config_path = _resolve_file(config, "Freqtrade config")
    data_path = _resolve_directory(data_dir, "Freqtrade data directory")
    strategy_root = _resolve_directory(strategy_path, "strategy path")
    strategy_source_path = _resolve_file(strategy_file, "strategy file")
    spec_path = _resolve_file(research_spec, "research spec")
    data_provenance_path = _resolve_file(data_provenance, "data provenance")
    market_path = _resolve_file(market_snapshot, "market snapshot")
    tiers_path = _resolve_file(leverage_tiers, "leverage tiers")
    sandbox_path = _resolve_file(sandbox_exec, "sandbox-exec", executable=True)
    runner_path = _resolve_file(runner_script, "Freqtrade backtest runner")
    open_receipt_paths: Dict[str, Path] = {}
    if scenario_open_receipts is not None:
        if set(scenario_open_receipts) != {"HOLDOUT", "HOLDOUT_STRESS"}:
            raise ResearchCandidateError(
                "scenario open receipts must name exactly HOLDOUT and HOLDOUT_STRESS"
            )
        for scenario in ("HOLDOUT", "HOLDOUT_STRESS"):
            open_receipt_paths[scenario] = _resolve_new_receipt(
                scenario_open_receipts[scenario], f"{scenario} open receipt"
            )
        if len(set(open_receipt_paths.values())) != 2:
            raise ResearchCandidateError("scenario open receipt paths must be distinct")
    producer_path = _resolve_file(Path(__file__), "research Candidate producer implementation")
    producer_bytes = _read_file(producer_path, "research Candidate producer implementation")
    runner_bytes = _read_file(runner_path, "Freqtrade backtest runner implementation")
    implementation_receipts = {
        "producer": {"bytes": len(producer_bytes), "sha256": _sha256(producer_bytes)},
        "runner": {"bytes": len(runner_bytes), "sha256": _sha256(runner_bytes)},
    }
    output_path = _resolve_output(output_dir)
    database_path = None if database is None else _resolve_file(database, "database")
    before_database = None
    if database_path is not None:
        try:
            before_database = _database_signature(database_path)
        except ResearchCandidateError as exc:
            raise ResearchCandidateError(f"database import failed preflight: {exc}") from exc

    real_execution = command_runner is subprocess.run
    if real_execution:
        expected_sandbox = _resolve_file(
            DEFAULT_SANDBOX_EXEC, "system sandbox-exec", executable=True
        )
        expected_git = _resolve_file(
            DEFAULT_GIT_EXECUTABLE,
            "CommandLineTools git",
            executable=True,
        )
        expected_runner = _resolve_file(DEFAULT_RUNNER, "default Freqtrade backtest runner")
        if sandbox_path != expected_sandbox:
            raise ResearchCandidateError("real execution requires /usr/bin/sandbox-exec")
        if runner_path != expected_runner:
            raise ResearchCandidateError("real execution requires the repository runner")
        if expected_git != DEFAULT_GIT_EXECUTABLE:
            raise ResearchCandidateError("real execution requires exact CommandLineTools git")
        network_policy = (
            "deny-by-default /usr/bin/sandbox-exec profile with explicit read/write/process "
            "allowlists and network denied"
        )
    else:
        network_policy = "test command runner; network isolation not attested"

    strategy_bytes = _validate_strategy(strategy_source_path, strategy_root, strategy)
    strategy_sha256 = _sha256(strategy_bytes)
    development_start, development_end = _parse_timerange(
        development_timerange, "development timerange"
    )
    holdout_start, _ = _parse_timerange(holdout_timerange, "holdout timerange")
    if development_end > holdout_start:
        raise ResearchCandidateError("Development must end no later than Holdout starts")
    multiplier = _finite_number(
        stress_fee_multiplier, "stress fee multiplier", minimum=1.0
    )
    if multiplier <= 1.0:
        raise ResearchCandidateError("stress fee multiplier must be greater than 1")
    spec = _validate_research_spec(
        spec_path,
        strategy,
        development_timerange,
        holdout_timerange,
        multiplier,
    )
    base_config = _mapping(
        _strict_json(_read_file(config_path, "Freqtrade config"), "Freqtrade config"),
        "Freqtrade config",
    )
    base_fee, pairs = _validate_config(base_config, strategy)
    data_receipt, data_receipt_sha, expected_input_receipts = _validate_data_provenance(
        data_provenance_path,
        config_path,
        spec_path,
        strategy_source_path,
        data_path,
        market_path,
        tiers_path,
        pairs,
        development_timerange,
        holdout_timerange,
    )

    work_root = Path(tempfile.mkdtemp(prefix=f".{output_path.name}.work-", dir=str(output_path.parent)))
    published = False
    try:
        bundle_staging = work_root / "bundle"
        runtime_root = work_root / "runtime"
        bundle_staging.mkdir()
        runtime_root.mkdir()
        execution_source = source_path
        source_tree_sha256 = "0" * 64
        ephemeral_roots = [runtime_root]
        if real_execution:
            execution_source = work_root / "freqtrade-source"
            git_home = work_root / "git-home"
            source_tree_sha256 = _prepare_freqtrade_source_snapshot(
                source_path,
                execution_source,
                git_home,
                sandbox_path,
            )
            ephemeral_roots.extend((execution_source, git_home))
        produced: List[ProducedArtifact] = []
        for scenario, slug in SCENARIOS:
            _check_file_hash(
                producer_path,
                len(producer_bytes),
                implementation_receipts["producer"]["sha256"],
                "research Candidate producer implementation",
            )
            _check_file_hash(
                runner_path,
                len(runner_bytes),
                implementation_receipts["runner"]["sha256"],
                "Freqtrade backtest runner implementation",
            )
            timerange = (
                development_timerange if scenario == "DEVELOPMENT" else holdout_timerange
            )
            fee = base_fee * multiplier if scenario == "HOLDOUT_STRESS" else base_fee
            scenario_root = runtime_root / slug
            raw_dir = scenario_root / "raw"
            scenario_user_data = scenario_root / "user_data"
            scenario_home = scenario_root / "home"
            raw_dir.mkdir(parents=True)
            scenario_user_data.mkdir()
            scenario_home.mkdir()
            (scenario_home / "tmp").mkdir()
            scenario_config_path = scenario_root / "config.json"
            scenario_config_path.write_bytes(
                _canonical_bytes(
                    _runtime_config(
                        base_config,
                        config_source=config_path,
                        data_dir=data_path,
                        user_data_dir=scenario_user_data,
                        strategy_path=strategy_root,
                        strategy=strategy,
                        timerange=timerange,
                        fee=fee,
                        export_dir=raw_dir,
                    )
                )
            )
            completed, runner_summary, command_shape = _run_scenario(
                scenario=scenario,
                timerange=timerange,
                fee=fee,
                python=python_path,
                source=execution_source,
                source_tree_sha256=source_tree_sha256,
                runner_script=runner_path,
                runner_sha256=implementation_receipts["runner"]["sha256"],
                sandbox_exec=sandbox_path,
                config_path=scenario_config_path,
                data_dir=data_path,
                user_data_dir=scenario_user_data,
                strategy_path=strategy_root,
                strategy_file=strategy_source_path,
                strategy_sha256=strategy_sha256,
                strategy=strategy,
                export_dir=raw_dir,
                market_snapshot=market_path,
                leverage_tiers=tiers_path,
                data_provenance=data_provenance_path,
                home=scenario_home,
                command_runner=command_runner,
                scenario_open_receipt=open_receipt_paths.get(scenario),
            )
            if scenario in open_receipt_paths:
                _validate_scenario_open_receipt(
                    open_receipt_paths[scenario],
                    scenario=scenario,
                    timerange=timerange,
                    strategy=strategy,
                    strategy_sha256=strategy_sha256,
                    data_provenance_sha256=data_receipt_sha,
                )
            _check_file_hash(
                producer_path,
                len(producer_bytes),
                implementation_receipts["producer"]["sha256"],
                "research Candidate producer implementation",
            )
            _check_file_hash(
                runner_path,
                len(runner_bytes),
                implementation_receipts["runner"]["sha256"],
                "Freqtrade backtest runner implementation",
            )
            produced.append(
                _sanitize_raw_artifact(
                    scenario=scenario,
                    slug=slug,
                    raw_dir=raw_dir,
                    runner_summary=runner_summary,
                    completed=completed,
                    command_shape=command_shape,
                    bundle_dir=bundle_staging,
                    strategy=strategy,
                    strategy_source=strategy_bytes,
                    data_provenance=data_receipt,
                    data_provenance_sha256=data_receipt_sha,
                    expected_input_receipts=expected_input_receipts,
                    source_tree_sha256=source_tree_sha256,
                    implementation_receipts=implementation_receipts,
                    timerange=timerange,
                    network_policy=network_policy,
                )
            )

        manifest = {
            "schema": BUNDLE_SCHEMA,
            "freqtrade_version": SUPPORTED_FREQTRADE_VERSION,
            "profile": spec["profile"],
            "candidate": spec["candidate"],
            "artifacts": [
                {
                    "scenario": artifact.scenario,
                    "archive": artifact.archive,
                    "provenance_sha256": artifact.provenance_sha256,
                }
                for artifact in produced
            ],
        }
        manifest_bytes = _canonical_bytes(manifest)
        (bundle_staging / MANIFEST_NAME).write_bytes(manifest_bytes)
        validated = validate_research_bundle(bundle_staging, Path(MANIFEST_NAME))
        _check_file_hash(
            producer_path,
            len(producer_bytes),
            implementation_receipts["producer"]["sha256"],
            "research Candidate producer implementation",
        )
        _check_file_hash(
            runner_path,
            len(runner_bytes),
            implementation_receipts["runner"]["sha256"],
            "Freqtrade backtest runner implementation",
        )
        _scan_for_path_leaks(
            bundle_staging,
            (
                work_root,
                config_path,
                data_path,
                strategy_root,
                source_path,
                python_path,
            ),
        )
        for ephemeral_root in ephemeral_roots:
            shutil.rmtree(ephemeral_root)
        remaining = list(work_root.iterdir())
        if remaining != [bundle_staging]:
            raise ResearchCandidateError(
                "temporary work root contains an unexpected pre-publication entry"
            )
        _publish_directory_exclusive(bundle_staging, output_path)
        published = True
        try:
            work_root.rmdir()
        except OSError as exc:
            try:
                shutil.rmtree(output_path)
                published = False
            except OSError as cleanup_exc:
                raise ResearchCandidateError(
                    "publication finalization failed and bundle rollback also failed: "
                    f"{cleanup_exc}"
                ) from exc
            raise ResearchCandidateError(
                f"publication finalization failed: {exc}"
            ) from exc

        imported = None
        if database_path is not None:
            if before_database is None:
                raise ResearchCandidateError("database import preflight state is unavailable")
            try:
                imported = import_research_bundle(
                    database_path,
                    output_path,
                    Path(MANIFEST_NAME),
                )
            except ResearchBundleImportError as exc:
                try:
                    shutil.rmtree(output_path)
                    published = False
                except OSError as cleanup_exc:
                    raise ResearchCandidateError(
                        f"database import failed and published bundle cleanup also failed: {cleanup_exc}"
                    ) from exc
                raise ResearchCandidateError(f"database import failed: {exc}") from exc
            except BaseException as exc:
                try:
                    after_database = _database_signature(database_path)
                except ResearchCandidateError:
                    after_database = None
                if after_database == before_database:
                    try:
                        shutil.rmtree(output_path)
                        published = False
                    except OSError as cleanup_exc:
                        raise ResearchCandidateError(
                            "database import was interrupted before a visible commit, and "
                            f"bundle rollback also failed: {cleanup_exc}"
                        ) from exc
                    raise ResearchCandidateError(
                        "database import was interrupted before a visible commit; "
                        "the published bundle was rolled back"
                    ) from exc
                raise ResearchCandidateError(
                    "database import was interrupted after the database changed or while its "
                    "outcome was unreadable; the validated bundle was retained so committed "
                    "artifact locators cannot be broken"
                ) from exc

        return ResearchCandidateResult(
            bundle_root=output_path,
            manifest_path=output_path / MANIFEST_NAME,
            manifest_sha256=validated.manifest_sha256,
            artifacts=tuple(produced),
            imported=imported,
        )
    except ResearchCandidateError:
        raise
    except ResearchBundleImportError as exc:
        raise ResearchCandidateError(f"research bundle validation failed: {exc}") from exc
    except (OSError, ValueError, RuntimeError, zipfile.BadZipFile) as exc:
        raise ResearchCandidateError(f"research candidate production failed: {exc}") from exc
    finally:
        if work_root.exists():
            try:
                shutil.rmtree(work_root)
            except OSError as exc:
                if not published:
                    raise ResearchCandidateError(
                        f"temporary work directory cleanup failed: {exc}"
                    ) from exc
