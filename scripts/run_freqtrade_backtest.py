#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Freqtrade 2026.7 offline adapter for one research scenario.

This adapter calls Freqtrade's GPL-3.0-only internal backtesting APIs directly.
It is intentionally limited to a single, local OKX futures backtest and must be
executed by the pinned Freqtrade 2026.7 Python environment with its source tree
on ``PYTHONPATH``.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import hmac
import importlib.metadata
import io
import json
import logging
import math
import platform
import re
import shutil
import stat
import sys
import tempfile
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence


SUPPORTED_FREQTRADE_VERSION = "2026.7"
SUPPORTED_FREQTRADE_COMMIT = "52bc96f4480b1a0da6a9b455bd00b17fbb6786a5"
SUPPORTED_DEPENDENCIES = {
    "ccxt": "4.5.68",
    "pandas": "3.0.3",
    "pyarrow": "25.0.0",
    "python": "3.13.13",
}
RETAINED_DATA_SCHEMA = "freqtrade-lab-retained-okx-data-v1"
SUPPORTED_SCENARIOS = ("DEVELOPMENT", "HOLDOUT", "HOLDOUT_STRESS")
MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_RECEIPT_FILE_BYTES = 64 * 1024 * 1024
MAX_SOURCE_TREE_BYTES = 64 * 1024 * 1024
MAX_NATIVE_ARCHIVE_BYTES = 16 * 1024 * 1024
MAX_NATIVE_ZIP_MEMBER_BYTES = 16 * 1024 * 1024
MAX_NATIVE_ZIP_TOTAL_BYTES = 32 * 1024 * 1024
MAX_NATIVE_ZIP_MEMBERS = 16
MAX_NATIVE_ZIP_COMPRESSION_RATIO = 200
MAX_SUPPRESSED_TEXT_BYTES = 1024 * 1024
MAX_RUNNER_BYTES = 2 * 1024 * 1024
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CLASS_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_TIMERANGE = re.compile(r"^\d{8}-\d{8}$")
_SENSITIVE_KEYS = {
    "account_id",
    "accountid",
    "api_key",
    "apikey",
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
_RUNTIME_CONFIG_KEYS = _BASE_CONFIG_KEYS | {
    "config_files",
    "datadir",
    "export",
    "exportdirectory",
    "strategy_path",
    "timerange",
    "user_data_dir",
}
_EXCHANGE_CONFIG_KEYS = {"enable_ws", "name", "pair_blacklist", "pair_whitelist"}
_PRICING_CONFIG_KEYS = {"order_book_top", "price_side", "use_order_book"}
_TIMEOUT_CONFIG_KEYS = {"entry", "exit", "exit_timeout_count", "unit"}


class OfflineBacktestError(ValueError):
    """Raised when the offline adapter cannot prove its complete contract."""


class FailClosedArgumentParser(argparse.ArgumentParser):
    """Turn argparse failures into the adapter's one-line error contract."""

    def error(self, message: str) -> None:
        raise OfflineBacktestError(f"invalid arguments: {message}")


class _BoundedTextSink(io.TextIOBase):
    """Discard normal engine chatter while bounding Candidate-controlled text."""

    def __init__(self, limit: int = MAX_SUPPRESSED_TEXT_BYTES):
        super().__init__()
        self._limit = limit
        self._bytes = 0

    def writable(self) -> bool:
        return True

    def write(self, value: str) -> int:
        if not isinstance(value, str):
            raise TypeError("bounded text sink accepts text only")
        self._bytes += len(value.encode("utf-8", "replace"))
        if self._bytes > self._limit:
            raise OfflineBacktestError("engine text output exceeds the fixed limit")
        return len(value)

    def flush(self) -> None:
        return None


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = FailClosedArgumentParser(description=__doc__)
    parser.add_argument("--runner-sha256", required=True)
    parser.add_argument("--freqtrade-source", required=True, type=Path)
    parser.add_argument("--source-tree-sha256", required=True)
    parser.add_argument("--scenario", required=True, choices=SUPPORTED_SCENARIOS)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--user-data-dir", required=True, type=Path)
    parser.add_argument("--strategy-path", required=True, type=Path)
    parser.add_argument("--strategy-file", required=True, type=Path)
    parser.add_argument("--strategy-sha256", required=True)
    parser.add_argument("--strategy", required=True)
    parser.add_argument("--timerange", required=True)
    parser.add_argument("--fee", required=True, type=float)
    parser.add_argument("--export-dir", required=True, type=Path)
    parser.add_argument("--market-snapshot", required=True, type=Path)
    parser.add_argument("--leverage-tiers", required=True, type=Path)
    parser.add_argument("--data-provenance", required=True, type=Path)
    return parser.parse_args(argv)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_regular_file(path: Path, label: str, limit: int) -> bytes:
    try:
        info = path.stat(follow_symlinks=False)
    except OSError as exc:
        raise OfflineBacktestError(f"{label} cannot be inspected: {exc}") from exc
    if path.is_symlink() or not stat.S_ISREG(info.st_mode):
        raise OfflineBacktestError(f"{label} must be a regular non-symlink file")
    if info.st_size > limit:
        raise OfflineBacktestError(f"{label} exceeds the {limit}-byte limit")
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise OfflineBacktestError(f"{label} cannot be read: {exc}") from exc
    if len(data) != info.st_size or len(data) > limit:
        raise OfflineBacktestError(f"{label} changed while it was being read")
    return data


def _resolve_file(value: Path, label: str, limit: int = MAX_JSON_BYTES) -> tuple[Path, bytes]:
    if value.is_symlink():
        raise OfflineBacktestError(f"{label} must not be a symlink")
    try:
        path = value.resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as exc:
        raise OfflineBacktestError(f"{label} cannot be resolved: {exc}") from exc
    return path, _read_regular_file(path, label, limit)


def _resolve_directory(value: Path, label: str) -> Path:
    if value.is_symlink():
        raise OfflineBacktestError(f"{label} must not be a symlink")
    try:
        path = value.resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as exc:
        raise OfflineBacktestError(f"{label} cannot be resolved: {exc}") from exc
    if not path.is_dir():
        raise OfflineBacktestError(f"{label} must be a directory")
    return path


def _strict_json(data: bytes, label: str) -> Any:
    def no_duplicates(pairs: Iterable[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise OfflineBacktestError(f"{label} contains duplicate key {key!r}")
            result[key] = value
        return result

    def reject_constant(value: str) -> Any:
        raise OfflineBacktestError(f"{label} contains non-finite number {value}")

    try:
        return json.loads(
            data.decode("utf-8", "strict"),
            object_pairs_hook=no_duplicates,
            parse_constant=reject_constant,
        )
    except OfflineBacktestError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise OfflineBacktestError(f"{label} is not strict UTF-8 JSON: {exc}") from exc


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise OfflineBacktestError(f"{label} must be a JSON object")
    return value


def _exact_keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    missing = sorted(expected - set(value))
    unknown = sorted(set(value) - expected)
    if missing:
        raise OfflineBacktestError(f"{label} is missing fields: {', '.join(missing)}")
    if unknown:
        raise OfflineBacktestError(f"{label} contains unknown fields: {', '.join(unknown)}")


def _relative_posix(value: Any, label: str) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise OfflineBacktestError(f"{label} must be a safe relative POSIX path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise OfflineBacktestError(f"{label} must be a safe relative POSIX path")
    return path


def _receipt_record(value: Any, label: str) -> tuple[int, str]:
    record = _mapping(value, label)
    size = record.get("bytes")
    digest = record.get("sha256")
    if isinstance(size, bool) or not isinstance(size, int) or size < 0:
        raise OfflineBacktestError(f"{label}.bytes must be a non-negative integer")
    if size > MAX_RECEIPT_FILE_BYTES:
        raise OfflineBacktestError(f"{label}.bytes exceeds the offline adapter limit")
    if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
        raise OfflineBacktestError(f"{label}.sha256 must be a lowercase SHA-256")
    return size, digest


def _verify_file_receipt(path: Path, value: Any, label: str) -> str:
    expected_size, expected_sha = _receipt_record(value, label)
    data = _read_regular_file(path, label, max(MAX_JSON_BYTES, expected_size))
    actual_sha = _sha256(data)
    if len(data) != expected_size or actual_sha != expected_sha:
        raise OfflineBacktestError(f"{label} does not match data provenance")
    return actual_sha


def _verify_data_provenance(
    provenance: Mapping[str, Any],
    *,
    scenario: str,
    timerange: str,
    pair: str,
    data_dir: Path,
    market_snapshot: Path,
    leverage_tiers: Path,
) -> dict[str, Any]:
    if provenance.get("schema") != RETAINED_DATA_SCHEMA:
        raise OfflineBacktestError("data provenance schema is not supported")

    source = _mapping(provenance.get("source"), "data provenance source")
    if source.get("host") != "www.okx.com" or source.get("authentication") != "none":
        raise OfflineBacktestError(
            "data provenance must attest unauthenticated public www.okx.com data"
        )
    if source.get("pair") != pair:
        raise OfflineBacktestError("data provenance pair disagrees with loaded config")

    freqtrade = _mapping(provenance.get("freqtrade"), "data provenance freqtrade")
    if (
        freqtrade.get("version") != SUPPORTED_FREQTRADE_VERSION
        or freqtrade.get("tag") != SUPPORTED_FREQTRADE_VERSION
        or freqtrade.get("commit") != SUPPORTED_FREQTRADE_COMMIT
    ):
        raise OfflineBacktestError("data provenance does not bind Freqtrade 2026.7")

    contract = _mapping(provenance.get("contract"), "data provenance contract")
    if contract.get("timeframe") != "5m":
        raise OfflineBacktestError("data provenance timeframe must be 5m")
    expected_timerange_key = (
        "development_timerange" if scenario == "DEVELOPMENT" else "holdout_timerange"
    )
    if contract.get(expected_timerange_key) != timerange:
        raise OfflineBacktestError("scenario timerange disagrees with data provenance")

    local_only = _mapping(
        provenance.get("local_only_files"), "data provenance local_only_files"
    )
    data_prefix = _relative_posix(contract.get("data_dir"), "contract data_dir")
    market_name = _relative_posix(contract.get("market_snapshot"), "contract market_snapshot")
    tiers_name = _relative_posix(contract.get("leverage_tiers"), "contract leverage_tiers")

    expected_data: dict[Path, Any] = {}
    market_record: Any = None
    tiers_record: Any = None
    for name, record in local_only.items():
        relative = _relative_posix(name, f"local_only_files path {name!r}")
        _receipt_record(record, f"local_only_files receipt {name!r}")
        if relative == market_name:
            if market_record is not None:
                raise OfflineBacktestError("data provenance repeats the market snapshot")
            market_record = record
            continue
        if relative == tiers_name:
            if tiers_record is not None:
                raise OfflineBacktestError("data provenance repeats the leverage tiers snapshot")
            tiers_record = record
            continue
        try:
            under_data = relative.relative_to(data_prefix)
        except ValueError as exc:
            raise OfflineBacktestError(
                f"local_only_files path {name!r} is not a recognized runner input"
            ) from exc
        expected_data[Path(*under_data.parts)] = record

    if market_record is None or tiers_record is None or not expected_data:
        raise OfflineBacktestError(
            "data provenance must bind market, leverage tiers, and local market data"
        )

    market_sha = _verify_file_receipt(
        market_snapshot, market_record, "market snapshot"
    )
    tiers_sha = _verify_file_receipt(
        leverage_tiers, tiers_record, "leverage tiers snapshot"
    )

    actual_data: set[Path] = set()
    try:
        for path in data_dir.rglob("*"):
            if path.is_symlink():
                raise OfflineBacktestError("data directory must not contain symlinks")
            if path.is_file():
                actual_data.add(path.relative_to(data_dir))
    except OSError as exc:
        raise OfflineBacktestError(f"data directory cannot be inspected: {exc}") from exc
    if actual_data != set(expected_data):
        raise OfflineBacktestError("data directory file set does not match data provenance")
    data_hashes: dict[str, str] = {}
    for relative in sorted(expected_data, key=lambda item: item.as_posix()):
        digest = _verify_file_receipt(
            data_dir / relative,
            expected_data[relative],
            f"market data {relative.as_posix()}",
        )
        data_hashes[relative.as_posix()] = digest

    return {
        "market_snapshot_sha256": market_sha,
        "leverage_tiers_sha256": tiers_sha,
        "data_sha256": data_hashes,
    }


def _create_scenario_data_view(
    source: Path,
    destination: Path,
    timerange: str,
    expected_sha256: Mapping[str, str],
) -> dict[str, Any]:
    """Create a local view whose stop bound is exclusive for scenario isolation."""
    match = _TIMERANGE.fullmatch(timerange)
    if match is None:
        raise OfflineBacktestError("timerange must use YYYYMMDD-YYYYMMDD")
    stop = datetime.strptime(match.group(0).split("-", 1)[1], "%Y%m%d").replace(
        tzinfo=timezone.utc
    )
    if destination.is_symlink() or not destination.is_dir() or any(destination.iterdir()):
        raise OfflineBacktestError("owned scenario data view must start as an empty directory")
    try:
        import pyarrow as pa
        import pyarrow.compute as pc
        import pyarrow.feather as feather
    except (ImportError, ModuleNotFoundError) as exc:
        raise OfflineBacktestError(f"PyArrow is unavailable for scenario isolation: {exc}") from exc

    expected_paths = set(expected_sha256)
    actual_paths: set[str] = set()
    try:
        for input_path in source.rglob("*"):
            if input_path.is_symlink():
                raise OfflineBacktestError(
                    "scenario data source must not contain symlinks"
                )
            if input_path.is_file():
                actual_paths.add(input_path.relative_to(source).as_posix())
    except OSError as exc:
        raise OfflineBacktestError(
            f"scenario data source cannot be inspected: {exc}"
        ) from exc
    if actual_paths != expected_paths:
        raise OfflineBacktestError(
            "scenario data source changed after provenance validation"
        )

    receipt: dict[str, Any] = {}
    base_end_seen = False
    for relative_name in sorted(expected_paths):
        if not relative_name.endswith(".feather"):
            raise OfflineBacktestError(
                "scenario data source contains an unsupported file type"
            )
        relative = Path(*PurePosixPath(relative_name).parts)
        input_path = source / relative
        output_path = destination / relative
        output_path.parent.mkdir(parents=True, exist_ok=True)
        input_bytes = _read_regular_file(
            input_path,
            f"scenario data source {relative_name}",
            MAX_RECEIPT_FILE_BYTES,
        )
        if _sha256(input_bytes) != expected_sha256[relative_name]:
            raise OfflineBacktestError(
                "scenario data source changed after provenance validation"
            )
        try:
            table = feather.read_table(pa.BufferReader(input_bytes))
        except Exception as exc:
            raise OfflineBacktestError(
                f"scenario data view cannot read {relative.as_posix()}: {exc}"
            ) from exc
        if "date" not in table.column_names:
            raise OfflineBacktestError(
                f"scenario data view lacks date column in {relative.as_posix()}"
            )
        dates = table.column("date")
        if not pa.types.is_timestamp(dates.type) or dates.null_count:
            raise OfflineBacktestError(
                f"scenario data view has an invalid date column in {relative.as_posix()}"
            )
        stop_value = pa.scalar(stop, type=dates.type)
        filtered = table.filter(pc.less(dates, stop_value))
        if filtered.num_rows == 0:
            raise OfflineBacktestError(
                f"scenario data view is empty for {relative.as_posix()}"
            )
        filtered_dates = filtered.column("date")
        if pc.any(pc.greater_equal(filtered_dates, stop_value)).as_py():
            raise OfflineBacktestError("scenario data view crossed its exclusive stop")
        if relative.name.endswith("-5m-futures.feather"):
            expected_last = pa.scalar(stop - timedelta(minutes=5), type=dates.type)
            if pc.max(filtered_dates).as_py() != expected_last.as_py():
                raise OfflineBacktestError(
                    "scenario 5m data does not end one candle before its exclusive stop"
                )
            base_end_seen = True
        try:
            feather.write_feather(filtered, output_path, compression="uncompressed")
        except Exception as exc:
            raise OfflineBacktestError(
                f"scenario data view cannot write {relative.as_posix()}: {exc}"
            ) from exc
        output_bytes = _read_regular_file(
            output_path,
            f"scenario data view {relative.as_posix()}",
            MAX_RECEIPT_FILE_BYTES,
        )
        receipt[relative.as_posix()] = {
            "rows": filtered.num_rows,
            "sha256": _sha256(output_bytes),
        }
    if not base_end_seen:
        raise OfflineBacktestError("scenario data view lacks the selected 5m futures series")
    return {
        "exclusive_stop_utc": stop.isoformat().replace("+00:00", "Z"),
        "files": receipt,
    }


@contextlib.contextmanager
def _owned_scenario_data_directory(parent: Path):
    """Yield and remove only the unique directory created by this invocation."""
    try:
        path = Path(tempfile.mkdtemp(prefix=".scenario-data-", dir=str(parent)))
    except OSError as exc:
        raise OfflineBacktestError(f"scenario data view cannot be created: {exc}") from exc
    try:
        yield path
    finally:
        try:
            if path.is_symlink():
                path.unlink()
                raise OfflineBacktestError("owned scenario data view was replaced by a symlink")
            shutil.rmtree(path)
        except OfflineBacktestError:
            raise
        except OSError as exc:
            raise OfflineBacktestError(f"scenario data view cleanup failed: {exc}") from exc


def _inside(path: Path, root: Path, label: str) -> None:
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise OfflineBacktestError(f"{label} is not loaded from the Freqtrade source tree") from exc


def _verify_source_snapshot(source_root: Path, expected_sha256: str) -> str:
    if not isinstance(expected_sha256, str) or _SHA256.fullmatch(expected_sha256) is None:
        raise OfflineBacktestError("source tree SHA-256 is invalid")
    try:
        top_level = list(source_root.iterdir())
    except OSError as exc:
        raise OfflineBacktestError(f"source snapshot cannot be inspected: {exc}") from exc
    if len(top_level) != 1 or top_level[0].name != "freqtrade" or not top_level[0].is_dir():
        raise OfflineBacktestError("source snapshot must contain only the freqtrade package")
    files: list[Path] = []
    try:
        for path in source_root.rglob("*"):
            if path.is_symlink():
                raise OfflineBacktestError("source snapshot must not contain symlinks")
            if path.is_file():
                files.append(path)
    except OSError as exc:
        raise OfflineBacktestError(f"source snapshot cannot be inspected: {exc}") from exc
    if not files or not (source_root / "freqtrade" / "__init__.py").is_file():
        raise OfflineBacktestError("source snapshot is incomplete")
    digest = hashlib.sha256(b"freqtrade-lab-source-tree-v1\0")
    total = 0
    for path in sorted(files, key=lambda item: item.relative_to(source_root).as_posix()):
        relative = path.relative_to(source_root).as_posix()
        data = _read_regular_file(
            path,
            f"source snapshot {relative}",
            MAX_SOURCE_TREE_BYTES,
        )
        total += len(data)
        if total > MAX_SOURCE_TREE_BYTES:
            raise OfflineBacktestError("source snapshot exceeds the size limit")
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(len(data)).encode("ascii"))
        digest.update(b"\0")
        digest.update(data)
        digest.update(b"\0")
    actual = digest.hexdigest()
    if actual != expected_sha256:
        raise OfflineBacktestError("source snapshot does not match its producer receipt")
    return actual


def _verify_dependency_versions(
    provenance: Mapping[str, Any], runtime_dependencies: Mapping[str, Any]
) -> None:
    freqtrade = _mapping(provenance.get("freqtrade"), "data provenance freqtrade")
    recorded = _mapping(
        freqtrade.get("dependencies"), "data provenance freqtrade dependencies"
    )
    _exact_keys(
        recorded,
        set(SUPPORTED_DEPENDENCIES),
        "data provenance freqtrade dependencies",
    )
    normalized: dict[str, str] = {}
    for name in SUPPORTED_DEPENDENCIES:
        value = recorded[name]
        if not isinstance(value, str) or not value:
            raise OfflineBacktestError(
                f"data provenance dependency {name} must be a non-empty string"
            )
        if name == "python" and value.startswith("Python "):
            value = value.removeprefix("Python ")
        normalized[name] = value
    actual = {name: runtime_dependencies.get(name) for name in SUPPORTED_DEPENDENCIES}
    if normalized != SUPPORTED_DEPENDENCIES or actual != SUPPORTED_DEPENDENCIES:
        raise OfflineBacktestError(
            "recorded and runtime dependency versions must match the supported build"
        )


def _load_official_freqtrade(
    expected_source_root: Path, expected_source_tree_sha256: str
) -> dict[str, Any]:
    try:
        import ccxt
        import freqtrade
        import freqtrade.optimize.backtesting as backtesting_module
        import freqtrade.optimize.optimize_reports.optimize_reports as reports_module
        from freqtrade.commands.optimize_commands import setup_optimize_configuration
        from freqtrade.enums import RunMode
        from freqtrade.exchange.okx import Okx
        from freqtrade.optimize.backtesting import Backtesting
        from freqtrade.optimize.optimize_reports import generate_backtest_stats
        from freqtrade.optimize.optimize_reports.bt_storage import store_backtest_results
    except (ImportError, ModuleNotFoundError) as exc:
        raise OfflineBacktestError(f"Freqtrade 2026.7 imports are unavailable: {exc}") from exc

    try:
        installed_version = importlib.metadata.version("freqtrade")
    except importlib.metadata.PackageNotFoundError as exc:
        raise OfflineBacktestError("Freqtrade distribution metadata is unavailable") from exc
    if installed_version != SUPPORTED_FREQTRADE_VERSION:
        raise OfflineBacktestError(
            f"Freqtrade distribution must be exactly {SUPPORTED_FREQTRADE_VERSION}"
        )
    if getattr(freqtrade, "__version__", None) != SUPPORTED_FREQTRADE_VERSION:
        raise OfflineBacktestError("Freqtrade package version disagrees with distribution metadata")

    package_file = Path(freqtrade.__file__).resolve(strict=True)
    package_root = package_file.parent
    source_root = package_root.parent
    if source_root != expected_source_root:
        raise OfflineBacktestError("loaded Freqtrade package disagrees with --freqtrade-source")
    source_tree_sha256 = _verify_source_snapshot(
        source_root, expected_source_tree_sha256
    )

    official_core = {
        "setup_optimize_configuration": setup_optimize_configuration.__module__,
        "Okx": Okx.__module__,
        "Backtesting.start": Backtesting.start.__module__,
        "Backtesting.backtest_one_strategy": Backtesting.backtest_one_strategy.__module__,
        "Backtesting.backtest": Backtesting.backtest.__module__,
        "generate_backtest_stats": generate_backtest_stats.__module__,
        "store_backtest_results": store_backtest_results.__module__,
    }
    expected_core = {
        "setup_optimize_configuration": "freqtrade.commands.optimize_commands",
        "Okx": "freqtrade.exchange.okx",
        "Backtesting.start": "freqtrade.optimize.backtesting",
        "Backtesting.backtest_one_strategy": "freqtrade.optimize.backtesting",
        "Backtesting.backtest": "freqtrade.optimize.backtesting",
        "generate_backtest_stats": "freqtrade.optimize.optimize_reports.optimize_reports",
        "store_backtest_results": "freqtrade.optimize.optimize_reports.bt_storage",
    }
    if official_core != expected_core:
        raise OfflineBacktestError("Freqtrade core method identities are not official 2026.7 APIs")
    if (
        backtesting_module.generate_backtest_stats is not generate_backtest_stats
        or backtesting_module.store_backtest_results is not store_backtest_results
        or reports_module.generate_backtest_stats is not generate_backtest_stats
    ):
        raise OfflineBacktestError("Freqtrade backtesting/exporter functions were replaced")

    modules = (
        backtesting_module,
        reports_module,
        sys.modules[setup_optimize_configuration.__module__],
        sys.modules[Okx.__module__],
        sys.modules[store_backtest_results.__module__],
    )
    for module in modules:
        module_file = getattr(module, "__file__", None)
        if not isinstance(module_file, str):
            raise OfflineBacktestError(f"official module {module.__name__} has no source file")
        _inside(Path(module_file).resolve(strict=True), package_root, module.__name__)

    dependencies = {
        "python": platform.python_version(),
        "freqtrade": installed_version,
        "ccxt": getattr(ccxt, "__version__", importlib.metadata.version("ccxt")),
        "pandas": importlib.metadata.version("pandas"),
        "pyarrow": importlib.metadata.version("pyarrow"),
    }
    return {
        "Backtesting": Backtesting,
        "Okx": Okx,
        "RunMode": RunMode,
        "setup_optimize_configuration": setup_optimize_configuration,
        "official_core": official_core,
        "dependencies": dependencies,
        "source_commit": SUPPORTED_FREQTRADE_COMMIT,
        "source_tree_sha256": source_tree_sha256,
    }


def _enum_value(value: Any) -> Any:
    return getattr(value, "value", value)


def _walk_sensitive(value: Any, label: str) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).lower().replace("-", "_")
            if normalized in _SENSITIVE_KEYS and child not in (None, "", [], {}):
                raise OfflineBacktestError(f"{label} contains non-empty credential field {key!r}")
            _walk_sensitive(child, label)
    elif isinstance(value, list):
        for child in value:
            _walk_sensitive(child, label)


def _validate_raw_config_boundary(config: Mapping[str, Any]) -> None:
    _walk_sensitive(config, "raw Freqtrade config")
    if "add_config_files" in config:
        raise OfflineBacktestError("raw config add_config_files is outside the single-file boundary")
    _exact_keys(config, _RUNTIME_CONFIG_KEYS, "raw Freqtrade config")
    if config.get("pairlists") != [{"method": "StaticPairList"}]:
        raise OfflineBacktestError("raw config must use exactly one StaticPairList")
    exchange = _mapping(config.get("exchange"), "raw config exchange")
    entry_pricing = _mapping(config.get("entry_pricing"), "raw config entry_pricing")
    exit_pricing = _mapping(config.get("exit_pricing"), "raw config exit_pricing")
    unfilledtimeout = _mapping(config.get("unfilledtimeout"), "raw config unfilledtimeout")
    _exact_keys(exchange, _EXCHANGE_CONFIG_KEYS, "raw config exchange")
    _exact_keys(entry_pricing, _PRICING_CONFIG_KEYS, "raw config entry_pricing")
    _exact_keys(exit_pricing, _PRICING_CONFIG_KEYS, "raw config exit_pricing")
    _exact_keys(unfilledtimeout, _TIMEOUT_CONFIG_KEYS, "raw config unfilledtimeout")


def _verify_strategy_input(
    strategy_path: Path,
    strategy_file: Path,
    expected_sha256: str,
    provenance: Mapping[str, Any],
) -> str:
    if _SHA256.fullmatch(expected_sha256) is None:
        raise OfflineBacktestError("strategy SHA-256 must be lowercase hexadecimal")
    _inside(strategy_file, strategy_path, "strategy file")
    files: set[Path] = set()
    for path in strategy_path.rglob("*"):
        if path.is_symlink():
            raise OfflineBacktestError("strategy path must not contain symlinks")
        if path.is_file():
            files.add(path.resolve(strict=True))
    if files != {strategy_file}:
        raise OfflineBacktestError("strategy path must contain exactly the selected strategy file")
    strategy_bytes = _read_regular_file(strategy_file, "strategy file", 256 * 1024)
    actual_sha256 = _sha256(strategy_bytes)
    if actual_sha256 != expected_sha256:
        raise OfflineBacktestError("strategy file SHA-256 disagrees with the CLI")

    contract = _mapping(provenance.get("contract"), "data provenance contract")
    contract_strategy = _relative_posix(contract.get("strategy"), "contract strategy")
    relative_strategy = strategy_file.relative_to(strategy_path)
    expected_contract_strategy = PurePosixPath("strategies", *relative_strategy.parts)
    if contract_strategy != expected_contract_strategy:
        raise OfflineBacktestError("strategy path disagrees with data provenance")
    tracked = _mapping(provenance.get("files"), "data provenance files")
    record = tracked.get(contract_strategy.as_posix())
    expected_size, receipt_sha256 = _receipt_record(record, "strategy provenance receipt")
    if len(strategy_bytes) != expected_size or actual_sha256 != receipt_sha256:
        raise OfflineBacktestError("strategy file disagrees with data provenance")
    return actual_sha256


def _same_path(value: Any, expected: Path, label: str) -> None:
    try:
        actual = Path(value).resolve(strict=True)
    except (TypeError, OSError, RuntimeError, ValueError) as exc:
        raise OfflineBacktestError(f"loaded {label} is not a valid existing path") from exc
    if actual != expected:
        raise OfflineBacktestError(f"loaded {label} disagrees with the CLI")


def _validate_loaded_config(
    config: Mapping[str, Any],
    *,
    args: argparse.Namespace,
    config_path: Path,
    data_dir: Path,
    user_data_dir: Path,
    strategy_path: Path,
    export_dir: Path,
) -> str:
    _walk_sensitive(config, "loaded Freqtrade config")
    exchange = _mapping(config.get("exchange"), "loaded config exchange")
    pairs = exchange.get("pair_whitelist")
    if not isinstance(pairs, list) or len(pairs) != 1 or not isinstance(pairs[0], str):
        raise OfflineBacktestError("loaded config must select exactly one pair")
    actual = {
        "dry_run": config.get("dry_run"),
        "exchange": exchange.get("name"),
        "trading_mode": _enum_value(config.get("trading_mode")),
        "margin_mode": _enum_value(config.get("margin_mode")),
        "timeframe": config.get("timeframe"),
        "pairs": pairs,
        "strategy": config.get("strategy"),
        "timerange": config.get("timerange"),
        "fee": config.get("fee"),
        "export": config.get("export"),
        "dataformat_ohlcv": config.get("dataformat_ohlcv"),
        "disableparamexport": config.get("disableparamexport"),
        "backtest_cache": config.get("backtest_cache"),
        "enable_ws": exchange.get("enable_ws"),
    }
    if (
        actual["dry_run"] is not True
        or actual["exchange"] != "okx"
        or actual["trading_mode"] != "futures"
        or actual["margin_mode"] != "isolated"
        or actual["timeframe"] != "5m"
        or actual["strategy"] != args.strategy
        or actual["timerange"] != args.timerange
        or actual["export"] != "trades"
        or actual["dataformat_ohlcv"] != "feather"
        or actual["disableparamexport"] is not True
        or actual["backtest_cache"] != "none"
        or actual["enable_ws"] is not False
    ):
        raise OfflineBacktestError(
            f"loaded Freqtrade contract is unsafe or inconsistent: {actual!r}"
        )
    loaded_fee = config.get("fee")
    if (
        isinstance(loaded_fee, bool)
        or not isinstance(loaded_fee, (int, float))
        or not math.isfinite(float(loaded_fee))
        or not math.isclose(float(loaded_fee), args.fee, rel_tol=0.0, abs_tol=1e-15)
    ):
        raise OfflineBacktestError("loaded fee disagrees with the CLI")

    for section in ("api_server", "telegram", "webhook", "external_message_consumer"):
        section_value = config.get(section)
        if isinstance(section_value, dict) and section_value.get("enabled") is True:
            raise OfflineBacktestError(f"loaded config must not enable {section}")
    if config.get("db_url") not in (None, ""):
        raise OfflineBacktestError("loaded config must not select a trading database")

    config_files = config.get("config_files")
    if not isinstance(config_files, list) or len(config_files) != 1:
        raise OfflineBacktestError("loaded config must contain exactly one config file")
    _same_path(config_files[0], config_path, "config")
    _same_path(config.get("datadir"), data_dir, "data directory")
    _same_path(config.get("user_data_dir"), user_data_dir, "user-data directory")
    _same_path(config.get("strategy_path"), strategy_path, "strategy path")
    _same_path(config.get("exportdirectory"), export_dir, "export directory")
    return pairs[0]


def _verify_market_inputs(
    market_value: Any,
    tiers_value: Any,
    *,
    pair: str,
    provenance: Mapping[str, Any],
) -> tuple[Mapping[str, Any], list[Mapping[str, Any]]]:
    market = _mapping(market_value, "market snapshot")
    source = _mapping(provenance.get("source"), "data provenance source")
    if (
        market.get("symbol") != pair
        or market.get("id") != source.get("instrument_id")
        or market.get("active") is not True
        or market.get("contract") is not True
        or market.get("swap") is not True
        or market.get("linear") is not True
        or market.get("inverse") is not False
        or market.get("type") != "swap"
    ):
        raise OfflineBacktestError("market snapshot is not the selected live OKX linear swap")
    if not isinstance(tiers_value, list) or not tiers_value:
        raise OfflineBacktestError("isolated leverage tiers snapshot must be a non-empty array")
    tiers: list[Mapping[str, Any]] = []
    for index, value in enumerate(tiers_value):
        tier = _mapping(value, f"leverage tier {index}")
        if tier.get("symbol") != pair:
            raise OfflineBacktestError(f"leverage tier {index} pair disagrees with config")
        tiers.append(tier)
    return market, tiers


def _finite_trade_number(value: Any, label: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise OfflineBacktestError(f"{label} must be a finite number")
    number = float(value)
    if not math.isfinite(number) or (positive and number <= 0.0):
        raise OfflineBacktestError(f"{label} must be a valid finite number")
    return number


def _validate_results(results: Any, strategy: str, pair: str, fee: float) -> int:
    root = _mapping(results, "backtest results")
    strategies = _mapping(root.get("strategy"), "backtest result strategies")
    if set(strategies) != {strategy}:
        raise OfflineBacktestError("backtest did not produce exactly the selected strategy")
    result = _mapping(strategies[strategy], "selected strategy result")
    trades = result.get("trades")
    if not isinstance(trades, list) or not trades:
        raise OfflineBacktestError("backtest produced zero trades")
    total_trades = result.get("total_trades")
    if isinstance(total_trades, bool) or not isinstance(total_trades, int):
        raise OfflineBacktestError("backtest total_trades is invalid")
    if total_trades != len(trades):
        raise OfflineBacktestError("backtest total_trades disagrees with trade records")
    for index, value in enumerate(trades):
        trade = _mapping(value, f"trade {index}")
        if trade.get("pair") != pair:
            raise OfflineBacktestError(f"trade {index} pair disagrees with config")
        for field in ("fee_open", "fee_close"):
            actual_fee = _finite_trade_number(trade.get(field), f"trade {index} {field}")
            if not math.isclose(actual_fee, fee, rel_tol=0.0, abs_tol=1e-15):
                raise OfflineBacktestError(f"trade {index} {field} disagrees with config")
        _finite_trade_number(trade.get("leverage"), f"trade {index} leverage", positive=True)
        if "funding_fees" not in trade:
            raise OfflineBacktestError(f"trade {index} lacks funding_fees")
        _finite_trade_number(trade.get("funding_fees"), f"trade {index} funding_fees")
    return total_trades


def _cleanup_export_directory(export_dir: Path) -> None:
    for child in export_dir.iterdir():
        if child.is_symlink() or child.is_file():
            child.unlink()
        elif child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


def _validate_native_zip_infos(infos: Sequence[zipfile.ZipInfo]) -> None:
    if not infos or len(infos) > MAX_NATIVE_ZIP_MEMBERS:
        raise OfflineBacktestError("native archive member count is unsafe")
    names: set[str] = set()
    total = 0
    for info in infos:
        try:
            relative = PurePosixPath(info.filename)
        except (TypeError, ValueError) as exc:
            raise OfflineBacktestError("native archive member path is invalid") from exc
        if (
            relative.is_absolute()
            or not relative.parts
            or any(part in ("", ".", "..") for part in relative.parts)
            or "\\" in info.filename
            or "\x00" in info.filename
            or info.filename in names
            or info.is_dir()
            or info.filename.endswith("/")
        ):
            raise OfflineBacktestError("native archive contains an unsafe member")
        names.add(info.filename)
        if info.flag_bits & 0x1:
            raise OfflineBacktestError("native archive must not be encrypted")
        mode = info.external_attr >> 16
        file_type = stat.S_IFMT(mode)
        if file_type not in (0, stat.S_IFREG):
            raise OfflineBacktestError("native archive contains a non-regular member")
        if info.file_size < 0 or info.file_size > MAX_NATIVE_ZIP_MEMBER_BYTES:
            raise OfflineBacktestError("native archive member exceeds the expansion limit")
        total += info.file_size
        if total > MAX_NATIVE_ZIP_TOTAL_BYTES:
            raise OfflineBacktestError("native archive exceeds the total expansion limit")
        if info.file_size > max(
            1024, info.compress_size * MAX_NATIVE_ZIP_COMPRESSION_RATIO
        ):
            raise OfflineBacktestError("native archive compression ratio is unsafe")


def _verify_native_exports(export_dir: Path, strategy: str) -> tuple[str, str]:
    pointer = export_dir / ".last_result.json"
    if pointer.exists() or pointer.is_symlink():
        if pointer.is_symlink() or not pointer.is_file():
            raise OfflineBacktestError("official exporter pointer is not a regular file")
        pointer.unlink()

    entries = sorted(export_dir.iterdir(), key=lambda item: item.name)
    if any(path.is_symlink() or not path.is_file() for path in entries):
        raise OfflineBacktestError("export directory contains a non-file result")
    archives = [
        path
        for path in entries
        if path.name.startswith("backtest-result-") and path.suffix == ".zip"
    ]
    metadata = [
        path
        for path in entries
        if path.name.startswith("backtest-result-") and path.name.endswith(".meta.json")
    ]
    if len(entries) != 2 or len(archives) != 1 or len(metadata) != 1:
        raise OfflineBacktestError("official exporter did not leave exactly one ZIP/meta pair")
    archive = archives[0]
    meta = metadata[0]
    if f"{archive.stem}.meta.json" != meta.name:
        raise OfflineBacktestError("official ZIP and metadata stems do not match")

    metadata_value = _mapping(
        _strict_json(
            _read_regular_file(meta, "native metadata", MAX_JSON_BYTES), "native metadata"
        ),
        "native metadata",
    )
    if set(metadata_value) != {strategy}:
        raise OfflineBacktestError("native metadata does not select exactly the requested strategy")
    strategy_metadata = _mapping(metadata_value[strategy], "native strategy metadata")
    if strategy_metadata.get("timeframe") != "5m":
        raise OfflineBacktestError("native metadata timeframe is not 5m")

    archive_bytes = _read_regular_file(
        archive, "native archive", MAX_NATIVE_ARCHIVE_BYTES
    )
    try:
        with zipfile.ZipFile(io.BytesIO(archive_bytes), "r") as unit:
            _validate_native_zip_infos(unit.infolist())
            if unit.testzip() is not None:
                raise OfflineBacktestError("native archive failed CRC validation")
            names = unit.namelist()
    except OfflineBacktestError:
        raise
    except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
        raise OfflineBacktestError(f"native archive cannot be read safely: {exc}") from exc
    reports = [
        name
        for name in names
        if name.endswith(".json") and not name.endswith("_config.json")
    ]
    configs = [name for name in names if name.endswith("_config.json")]
    strategies = [name for name in names if name.endswith(f"_{strategy}.py")]
    if len(reports) != 1 or len(configs) != 1 or len(strategies) != 1:
        raise OfflineBacktestError("native archive lacks one report/config/strategy unit")
    return archive.name, meta.name


def _execute(args: argparse.Namespace) -> dict[str, Any]:
    runner_path = Path(__file__).resolve(strict=True)
    runner_bytes = _read_regular_file(runner_path, "runner implementation", MAX_RUNNER_BYTES)
    if _SHA256.fullmatch(args.runner_sha256) is None or not hmac.compare_digest(
        _sha256(runner_bytes), args.runner_sha256
    ):
        raise OfflineBacktestError("runner implementation SHA-256 disagrees with the producer")
    if _CLASS_NAME.fullmatch(args.strategy) is None:
        raise OfflineBacktestError("strategy must be a simple Python class name")
    if _TIMERANGE.fullmatch(args.timerange) is None:
        raise OfflineBacktestError("timerange must use YYYYMMDD-YYYYMMDD")
    if isinstance(args.fee, bool) or not math.isfinite(args.fee) or args.fee <= 0.0:
        raise OfflineBacktestError("fee must be a positive finite number")

    source_root = _resolve_directory(args.freqtrade_source, "Freqtrade source")
    config_path, config_bytes = _resolve_file(args.config, "Freqtrade config")
    data_dir = _resolve_directory(args.data_dir, "data directory")
    user_data_dir = _resolve_directory(args.user_data_dir, "user-data directory")
    if any(user_data_dir.iterdir()):
        raise OfflineBacktestError("user-data directory must start empty")
    strategy_path = _resolve_directory(args.strategy_path, "strategy path")
    strategy_file, _ = _resolve_file(args.strategy_file, "strategy file", 256 * 1024)
    export_dir = _resolve_directory(args.export_dir, "export directory")
    market_path, market_bytes = _resolve_file(args.market_snapshot, "market snapshot")
    tiers_path, tiers_bytes = _resolve_file(args.leverage_tiers, "leverage tiers snapshot")
    _, provenance_bytes = _resolve_file(
        args.data_provenance, "data provenance"
    )
    if any(export_dir.iterdir()):
        raise OfflineBacktestError("export directory must start empty")

    raw_config = _mapping(
        _strict_json(config_bytes, "raw Freqtrade config"), "raw Freqtrade config"
    )
    _validate_raw_config_boundary(raw_config)
    provenance = _mapping(
        _strict_json(provenance_bytes, "data provenance"), "data provenance"
    )
    _verify_strategy_input(
        strategy_path,
        strategy_file,
        args.strategy_sha256,
        provenance,
    )
    _verify_source_snapshot(source_root, args.source_tree_sha256)

    cleanup_enabled = True
    try:
        official = _load_official_freqtrade(source_root, args.source_tree_sha256)
        _verify_dependency_versions(provenance, official["dependencies"])
        setup_optimize_configuration = official["setup_optimize_configuration"]
        RunMode = official["RunMode"]
        cli_config = {
            "command": "backtesting",
            "config": [str(config_path)],
            "datadir": str(data_dir),
            "user_data_dir": str(user_data_dir),
            "strategy_path": str(strategy_path),
            "strategy": args.strategy,
            "timerange": args.timerange,
            "fee": args.fee,
            "export": "trades",
            "exportdirectory": str(export_dir),
            "dataformat_ohlcv": "feather",
            "disableparamexport": True,
            "backtest_cache": "none",
        }
        config = setup_optimize_configuration(cli_config, RunMode.BACKTEST)
        pair = _validate_loaded_config(
            config,
            args=args,
            config_path=config_path,
            data_dir=data_dir,
            user_data_dir=user_data_dir,
            strategy_path=strategy_path,
            export_dir=export_dir,
        )

        receipt_summary = _verify_data_provenance(
            provenance,
            scenario=args.scenario,
            timerange=args.timerange,
            pair=pair,
            data_dir=data_dir,
            market_snapshot=market_path,
            leverage_tiers=tiers_path,
        )
        market, tiers = _verify_market_inputs(
            _strict_json(market_bytes, "market snapshot"),
            _strict_json(tiers_bytes, "leverage tiers snapshot"),
            pair=pair,
            provenance=provenance,
        )
        with _owned_scenario_data_directory(export_dir.parent) as scenario_data_dir:
            scenario_data_view = _create_scenario_data_view(
                data_dir,
                scenario_data_dir,
                args.timerange,
                receipt_summary["data_sha256"],
            )
            config["datadir"] = scenario_data_dir

            Okx = official["Okx"]
            exchange = Okx(config, validate=False, load_leverage_tiers=False)
            exchange._api.set_markets([market], {})
            exchange._api_async.set_markets([market], {})
            exchange._markets = exchange._api.markets
            exchange._leverage_tiers = {
                pair: [exchange.parse_leverage_tier(tier) for tier in tiers]
            }
            if set(exchange._markets) != {pair} or set(exchange._leverage_tiers) != {pair}:
                raise OfflineBacktestError(
                    "rehydrated exchange is not limited to the selected pair"
                )

            Backtesting = official["Backtesting"]
            backtesting = Backtesting(config, exchange=exchange)
            if len(backtesting.strategylist) != 1:
                raise OfflineBacktestError("Freqtrade resolved more than one strategy")
            selected = backtesting.strategylist[0]
            if (
                selected.get_strategy_name() != args.strategy
                or selected.__class__.__name__ != args.strategy
            ):
                raise OfflineBacktestError(
                    "Freqtrade did not resolve the exact selected strategy"
                )
            selected_strategy_file = Path(selected.__file__).resolve(strict=True)
            if selected_strategy_file != strategy_file:
                raise OfflineBacktestError(
                    "Freqtrade did not load the exact SHA-bound strategy file"
                )

            backtesting.start()
            _verify_source_snapshot(source_root, args.source_tree_sha256)
            if not hmac.compare_digest(
                _sha256(
                    _read_regular_file(
                        runner_path, "runner implementation", MAX_RUNNER_BYTES
                    )
                ),
                args.runner_sha256,
            ):
                raise OfflineBacktestError("runner implementation changed during execution")
            total_trades = _validate_results(
                backtesting.results, args.strategy, pair, args.fee
            )
            archive_name, metadata_name = _verify_native_exports(
                export_dir, args.strategy
            )
            summary = {
                "scenario": args.scenario,
                "archive": archive_name,
                "metadata": metadata_name,
                "total_trades": total_trades,
                "dependencies": official["dependencies"],
                "official_core": official["official_core"],
                "freqtrade_commit": official["source_commit"],
                "source_tree_sha256": official["source_tree_sha256"],
                "runner_sha256": args.runner_sha256,
                "data_provenance_sha256": _sha256(provenance_bytes),
                "input_receipts": receipt_summary,
                "scenario_data_view": scenario_data_view,
            }
        cleanup_enabled = False
        return summary
    finally:
        if cleanup_enabled:
            _cleanup_export_directory(export_dir)


def _one_line_error(exc: BaseException) -> str:
    message = " ".join(str(exc).split())
    if not message:
        message = type(exc).__name__
    return f"offline backtest failed: {message}"


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = _parse_args(argv)
        # Freqtrade is normally verbose on stderr.  The producer records the
        # native stdout, while failures use this adapter's single-line stderr.
        logging.disable(logging.CRITICAL)
        suppressed_stdout = _BoundedTextSink()
        suppressed_stderr = _BoundedTextSink()
        with contextlib.redirect_stdout(suppressed_stdout), contextlib.redirect_stderr(
            suppressed_stderr
        ):
            summary = _execute(args)
        print(json.dumps(summary, allow_nan=False, separators=(",", ":"), sort_keys=True))
        return 0
    except OfflineBacktestError as exc:
        print(_one_line_error(exc), file=sys.stderr)
        return 2
    except Exception as exc:  # Fail closed without exposing an internal traceback.
        print(_one_line_error(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
