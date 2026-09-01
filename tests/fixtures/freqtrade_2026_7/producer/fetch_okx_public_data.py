#!/usr/bin/env python3
"""Fetch a bounded OKX public dataset into an untracked local path.

This is a manual acquisition helper, not a test that may silently use the
network.  It deliberately has no credential inputs and permits only the five
public OKX GET endpoints listed below.  OKX market data produced by this script
must not be added to this repository.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

import ccxt
import pandas
import pyarrow

import freqtrade
from freqtrade.data.converter import ohlcv_to_dataframe
from freqtrade.data.history import get_datahandler
from freqtrade.enums import CandleType


REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
FIXTURE_ROOT = Path(__file__).resolve().parent
HOST = "www.okx.com"
SYMBOL = "XRP/USDT:USDT"
INSTRUMENT_ID = "XRP-USDT-SWAP"
PAIR_FAMILY = "XRP-USDT"
DATA_START = datetime(2026, 7, 31, 22, 0, tzinfo=UTC)
DEVELOPMENT_START = datetime(2026, 8, 1, 0, 0, tzinfo=UTC)
HOLDOUT_START = datetime(2026, 8, 4, 0, 0, tzinfo=UTC)
DATA_END = datetime(2026, 8, 7, 0, 0, tzinfo=UTC)
DATA_START_MS = int(DATA_START.timestamp() * 1000)
DATA_END_MS = int(DATA_END.timestamp() * 1000)
EXPECTED_VERSIONS = {
    "python": "3.13.13",
    "freqtrade": "2026.7",
    "ccxt": "4.5.68",
    "pandas": "3.0.3",
    "pyarrow": "25.0.0",
}
EXPECTED_FREQTRADE_COMMIT = "52bc96f4480b1a0da6a9b455bd00b17fbb6786a5"
GIT_EXECUTABLE = Path("/Library/Developer/CommandLineTools/usr/bin/git")
WINDOW_SPEC_SCHEMA = "freqtrade-lab-okx-window-v1"
STRICT_WINDOW_SPEC_SCHEMA = "freqtrade-lab-okx-window-v2"
WINDOW_SCHEMA_USED: str | None = None
WINDOW_SPEC_FIELDS = (
    "data_start_utc",
    "development_start_utc",
    "holdout_start_utc",
    "end_exclusive_utc",
)
FUNDING_INTERVAL_MS = 8 * 60 * 60 * 1000
MAX_FUNDING_BATCH = 100

ALLOWED_PATHS = {
    "/api/v5/public/instruments",
    "/api/v5/public/position-tiers",
    "/api/v5/market/history-candles",
    "/api/v5/market/history-mark-price-candles",
    "/api/v5/public/funding-rate-history",
}


LocalCandidateInputs = tuple[str, bytes, bytes, str]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _strict_json_object(path: Path, label: str) -> dict:
    def no_duplicates(pairs: list[tuple[str, object]]) -> dict:
        value = {}
        for key, child in pairs:
            if key in value:
                raise RuntimeError(f"{label} contains duplicate key {key!r}")
            value[key] = child
        return value

    def reject_constant(value: str) -> object:
        raise RuntimeError(f"{label} contains non-finite number {value}")

    try:
        raw = path.expanduser().read_bytes()
        value = json.loads(
            raw.decode("utf-8", "strict"),
            object_pairs_hook=no_duplicates,
            parse_constant=reject_constant,
        )
    except RuntimeError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise RuntimeError(f"{label} cannot be read as strict JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"{label} must be a JSON object")
    return value


def _utc_z_datetime(value: object, label: str) -> datetime:
    if not isinstance(value, str) or len(value) != 20 or not value.endswith("Z"):
        raise RuntimeError(f"{label} must use YYYY-MM-DDTHH:MM:SSZ")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError as exc:
        raise RuntimeError(f"{label} must use YYYY-MM-DDTHH:MM:SSZ") from exc
    if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != value:
        raise RuntimeError(f"{label} must use YYYY-MM-DDTHH:MM:SSZ")
    return parsed


def load_window_spec(
    path: Path,
) -> tuple[str, datetime, datetime, datetime, datetime]:
    value = _strict_json_object(path, "window spec")
    expected = {"schema", *WINDOW_SPEC_FIELDS}
    missing = sorted(expected - set(value))
    unknown = sorted(set(value) - expected)
    if missing:
        raise RuntimeError(f"window spec is missing fields: {', '.join(missing)}")
    if unknown:
        raise RuntimeError(f"window spec contains unknown fields: {', '.join(unknown)}")
    schema = value["schema"]
    if schema not in {WINDOW_SPEC_SCHEMA, STRICT_WINDOW_SPEC_SCHEMA}:
        raise RuntimeError("window spec schema is not supported")

    data_start, development_start, holdout_start, end_exclusive = (
        _utc_z_datetime(value[field], f"window spec {field}")
        for field in WINDOW_SPEC_FIELDS
    )
    if not data_start < development_start < holdout_start < end_exclusive:
        raise RuntimeError(
            "window spec must satisfy data_start < development_start < "
            "holdout_start < end_exclusive"
        )

    for label, boundary in (
        ("development_start_utc", development_start),
        ("holdout_start_utc", holdout_start),
        ("end_exclusive_utc", end_exclusive),
    ):
        if any((boundary.hour, boundary.minute, boundary.second, boundary.microsecond)):
            raise RuntimeError(f"window spec {label} must be UTC midnight")
    if any((data_start.minute, data_start.second, data_start.microsecond)):
        raise RuntimeError("window spec data_start_utc must be aligned to an UTC hour")

    day_seconds = 24 * 60 * 60
    development_seconds = int((holdout_start - development_start).total_seconds())
    holdout_seconds = int((end_exclusive - holdout_start).total_seconds())
    if development_seconds % day_seconds or holdout_seconds % day_seconds:
        raise RuntimeError("window spec Development and Holdout must be whole days")
    development_days = development_seconds // day_seconds
    holdout_days = holdout_seconds // day_seconds
    if schema == STRICT_WINDOW_SPEC_SCHEMA:
        if development_days != 60 or holdout_days != 30:
            raise RuntimeError(
                "window spec v2 requires exactly 60 Development days and 30 Holdout days"
            )
    elif not 60 <= development_days + holdout_days <= 90:
        raise RuntimeError("window spec research window must be from 60 to 90 whole days")

    warmup_seconds = int((development_start - data_start).total_seconds())
    if not 0 < warmup_seconds <= day_seconds:
        raise RuntimeError("window spec warmup must be greater than zero and at most one day")
    if end_exclusive >= datetime.now(UTC):
        raise RuntimeError("window spec end_exclusive_utc must be fully closed")
    return schema, data_start, development_start, holdout_start, end_exclusive


def configure_window(path: Path | None) -> None:
    """Apply an optional frozen window while preserving the six-day default."""
    if path is None:
        return
    global DATA_START, DEVELOPMENT_START, HOLDOUT_START, DATA_END
    global DATA_START_MS, DATA_END_MS
    global WINDOW_SCHEMA_USED
    (
        WINDOW_SCHEMA_USED,
        DATA_START,
        DEVELOPMENT_START,
        HOLDOUT_START,
        DATA_END,
    ) = load_window_spec(path)
    DATA_START_MS = int(DATA_START.timestamp() * 1000)
    DATA_END_MS = int(DATA_END.timestamp() * 1000)


def scenario_timerange(start: datetime, end: datetime) -> str:
    return f"{start:%Y%m%d}-{end:%Y%m%d}"


def load_local_candidate_inputs(
    strategy_file: Path | None, research_spec: Path | None
) -> LocalCandidateInputs | None:
    if strategy_file is None and research_spec is None:
        return None
    if strategy_file is None or research_spec is None:
        raise RuntimeError(
            "--strategy-file and --research-spec must be provided together"
        )

    try:
        strategy_path = strategy_file.expanduser()
        strategy_bytes = strategy_path.read_bytes()
        spec_bytes = research_spec.expanduser().read_bytes()
        spec_value = json.loads(spec_bytes)
        candidate = spec_value["candidate"]
        class_name = candidate["class_name"]
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise RuntimeError(f"local Candidate inputs cannot be read: {exc}") from exc
    if not isinstance(class_name, str) or not class_name:
        raise RuntimeError("research spec candidate.class_name must be a non-empty string")

    return strategy_path.name, strategy_bytes, spec_bytes, class_name


def request_receipt(exchange: ccxt.okx, label: str) -> dict[str, object]:
    url = exchange.last_request_url
    raw_text = exchange.last_http_response
    if not isinstance(url, str) or not isinstance(raw_text, str):
        raise RuntimeError(f"{label}: CCXT did not expose request/response evidence")
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != HOST or parsed.path not in ALLOWED_PATHS:
        raise RuntimeError(f"{label}: forbidden endpoint {url!r}")
    raw_bytes = raw_text.encode("utf-8")
    return {
        "label": label,
        "method": "GET",
        "url": url,
        "fetched_at_utc": datetime.now(UTC).isoformat(),
        "response_bytes": len(raw_bytes),
        "response_sha256": sha256(raw_bytes),
    }


def install_request_guard(exchange: ccxt.okx) -> None:
    """Reject any request outside the public allowlist before network I/O."""
    original_fetch = exchange.fetch
    exchange.session.trust_env = False
    original_request = exchange.session.request

    def validate_endpoint(method: str, url: str) -> None:
        parsed = urlparse(url)
        if (
            method.upper() != "GET"
            or parsed.scheme != "https"
            or parsed.hostname != HOST
            or parsed.port not in (None, 443)
            or parsed.path not in ALLOWED_PATHS
        ):
            raise RuntimeError(f"forbidden pre-request endpoint: {method} {url!r}")

    def guarded_request(method: str, url: str, *args, **kwargs):
        validate_endpoint(method, url)
        if kwargs.get("allow_redirects") not in (None, False):
            raise RuntimeError("redirect-following is forbidden for acquisition requests")
        kwargs["allow_redirects"] = False
        response = original_request(method, url, *args, **kwargs)
        if 300 <= response.status_code < 400:
            response.close()
            raise RuntimeError("redirect response rejected before any follow-up request")
        return response

    def guarded_fetch(
        url: str,
        method: str = "GET",
        headers: dict | None = None,
        body: str | None = None,
    ):
        validate_endpoint(method, url)
        return original_fetch(url, method, headers, body)

    exchange.session.request = guarded_request
    exchange.fetch = guarded_fetch


def assert_okx_response(response: object, label: str) -> dict:
    if not isinstance(response, dict):
        raise RuntimeError(f"{label}: response is not an object")
    if response.get("code") != "0" or response.get("msg") not in ("", None):
        raise RuntimeError(f"{label}: OKX returned an error: {response!r}")
    if not isinstance(response.get("data"), list):
        raise RuntimeError(f"{label}: response data is not an array")
    return response


def assert_regular_series(
    rows: list[list],
    *,
    label: str,
    start_ms: int,
    end_ms: int,
    step_ms: int,
) -> dict[str, object]:
    timestamps = [int(row[0]) for row in rows]
    expected = list(range(start_ms, end_ms, step_ms))
    if timestamps != expected:
        duplicates = len(timestamps) - len(set(timestamps))
        missing = sorted(set(expected) - set(timestamps))
        extras = sorted(set(timestamps) - set(expected))
        raise RuntimeError(
            f"{label}: non-contiguous data; duplicates={duplicates}, "
            f"missing={missing[:5]}, extras={extras[:5]}"
        )
    if timestamps[-1] + step_ms > end_ms:
        raise RuntimeError(f"{label}: contains an unclosed candle")
    return {
        "rows": len(rows),
        "start_utc": datetime.fromtimestamp(timestamps[0] / 1000, UTC).isoformat(),
        "end_utc": datetime.fromtimestamp(timestamps[-1] / 1000, UTC).isoformat(),
        "duplicates": 0,
        "missing_intervals": 0,
        "unclosed_candles": 0,
    }


def validate_funding_history(funding: list[dict]) -> dict[str, object]:
    if not funding:
        raise RuntimeError("funding history is empty")
    funding_timestamps = [int(item["timestamp"]) for item in funding]
    if funding_timestamps != sorted(funding_timestamps):
        raise RuntimeError("funding history is not sorted")
    if len(funding_timestamps) != len(set(funding_timestamps)):
        raise RuntimeError("funding history contains duplicate timestamps")
    if any(ts < DATA_START_MS or ts >= DATA_END_MS for ts in funding_timestamps):
        raise RuntimeError("funding history escaped the fixed window")
    if any(
        not isinstance(item.get("fundingRate"), (int, float))
        or not math.isfinite(float(item["fundingRate"]))
        for item in funding
    ):
        raise RuntimeError("funding history contains invalid rates")
    expected_funding = list(
        range(
            int(DEVELOPMENT_START.timestamp() * 1000),
            DATA_END_MS,
            FUNDING_INTERVAL_MS,
        )
    )
    if funding_timestamps != expected_funding:
        raise RuntimeError(
            "funding history must cover every fixed eight-hour timestamp "
            "from Development start through Holdout end"
        )
    return {
        "rows": len(funding),
        "start_utc": datetime.fromtimestamp(funding_timestamps[0] / 1000, UTC).isoformat(),
        "end_utc": datetime.fromtimestamp(funding_timestamps[-1] / 1000, UTC).isoformat(),
        "duplicates": 0,
        "outside_window": 0,
    }


def fetch_funding_history(
    exchange: ccxt.okx,
    requests: list[dict[str, object]],
) -> list[dict]:
    expected_timestamps = list(
        range(
            int(DEVELOPMENT_START.timestamp() * 1000),
            DATA_END_MS,
            FUNDING_INTERVAL_MS,
        )
    )
    batches = math.ceil(len(expected_timestamps) / MAX_FUNDING_BATCH)
    output: list[dict] = []
    for offset in range(0, len(expected_timestamps), MAX_FUNDING_BATCH):
        batch_number = offset // MAX_FUNDING_BATCH + 1
        batch_timestamps = expected_timestamps[offset : offset + MAX_FUNDING_BATCH]
        batch_start = batch_timestamps[0]
        count = len(batch_timestamps)
        batch_end = batch_start + count * FUNDING_INTERVAL_MS
        rows = exchange.fetch_funding_rate_history(
            SYMBOL,
            since=batch_start,
            limit=count,
            params={"after": batch_end},
        )
        label = (
            "funding-history"
            if batches == 1
            else f"funding-history-{batch_number}"
        )
        requests.append(request_receipt(exchange, label))
        if not isinstance(rows, list) or len(rows) != count:
            received = len(rows) if isinstance(rows, list) else "non-list"
            raise RuntimeError(
                f"funding history batch {batch_number}: expected {count} rows, "
                f"received {received}"
            )
        output.extend(rows)
    return output


def validate_ohlcv_values(
    rows: list[list], *, label: str, volume_required: bool
) -> None:
    for index, row in enumerate(rows):
        if not isinstance(row, list) or len(row) != 6:
            raise RuntimeError(f"{label} row {index}: invalid CCXT OHLCV shape")
        prices = row[1:5]
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or float(value) <= 0
            for value in prices
        ):
            raise RuntimeError(f"{label} row {index}: invalid OHLC price")
        open_price, high, low, close = (float(value) for value in prices)
        if high < max(open_price, low, close) or low > min(open_price, high, close):
            raise RuntimeError(f"{label} row {index}: inconsistent OHLC bounds")
        volume = row[5]
        if volume is None and not volume_required:
            continue
        if (
            isinstance(volume, bool)
            or not isinstance(volume, (int, float))
            or not math.isfinite(float(volume))
            or float(volume) < 0
        ):
            raise RuntimeError(f"{label} row {index}: invalid volume")


def fetch_candles(
    exchange: ccxt.okx,
    *,
    timeframe: str,
    start_ms: int,
    end_ms: int,
    page_limit: int,
    price: str | None,
    label: str,
    requests: list[dict[str, object]],
) -> list[list]:
    step_ms = exchange.parse_timeframe(timeframe) * 1000
    cursor = start_ms
    output: list[list] = []
    page = 0
    while cursor < end_ms:
        count = min(page_limit, math.ceil((end_ms - cursor) / step_ms))
        until = cursor + count * step_ms
        params: dict[str, object] = {
            "until": until,
            "type": "HistoryCandles",
        }
        if price is not None:
            params["price"] = price
        rows = exchange.fetch_ohlcv(
            SYMBOL,
            timeframe=timeframe,
            since=cursor,
            limit=count,
            params=params,
        )
        page += 1
        requests.append(request_receipt(exchange, f"{label}-{page}"))
        if len(rows) != count:
            raise RuntimeError(
                f"{label} page {page}: expected {count} rows, received {len(rows)}"
            )
        validate_ohlcv_values(
            rows,
            label=f"{label} page {page}",
            volume_required=price is None,
        )
        output.extend(rows)
        cursor = until
    return output


def run_git(source: Path, *arguments: str) -> str:
    if (
        GIT_EXECUTABLE.is_symlink()
        or not GIT_EXECUTABLE.is_file()
        or not os.access(GIT_EXECUTABLE, os.X_OK)
    ):
        raise RuntimeError("exact CommandLineTools git executable is unavailable")
    completed = subprocess.run(
        [
            str(GIT_EXECUTABLE),
            "-c",
            "core.fsmonitor=false",
            "-c",
            "core.hooksPath=/dev/null",
            *arguments,
        ],
        cwd=source,
        env={
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_TERMINAL_PROMPT": "0",
            "LC_ALL": "C",
            "PATH": "/usr/bin:/bin",
            "TZ": "UTC",
        },
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"Freqtrade source check failed: git {' '.join(arguments)}")
    return completed.stdout.strip()


def validate_runtime() -> dict[str, object]:
    actual = {
        "python": platform.python_version(),
        "freqtrade": freqtrade.__version__,
        "ccxt": ccxt.__version__,
        "pandas": pandas.__version__,
        "pyarrow": pyarrow.__version__,
    }
    if actual != EXPECTED_VERSIONS:
        raise RuntimeError(
            f"exact acquisition runtime required: expected {EXPECTED_VERSIONS!r}, "
            f"received {actual!r}"
        )
    source = Path(freqtrade.__file__).resolve(strict=True).parent.parent
    commit = run_git(source, "rev-parse", "HEAD")
    tag = run_git(source, "describe", "--exact-match", "--tags", "HEAD")
    dirty = run_git(source, "status", "--porcelain=v1", "--untracked-files=all")
    if commit != EXPECTED_FREQTRADE_COMMIT or tag != EXPECTED_VERSIONS["freqtrade"]:
        raise RuntimeError("Freqtrade source is not the exact 2026.7 checkout")
    if dirty:
        raise RuntimeError("Freqtrade source checkout must be completely clean")
    return {"versions": actual, "freqtrade_commit": commit, "freqtrade_tag": tag}


def acquire(root: Path, runtime: dict[str, object]) -> Path:
    data_dir = root / "data" / "okx"
    data_dir.mkdir(parents=True, exist_ok=False)
    started = datetime.now(UTC)
    if DATA_END >= started:
        raise RuntimeError("fixed data window is not fully closed")

    exchange = ccxt.okx(
        {
            "enableRateLimit": True,
            "timeout": 30000,
            "options": {"defaultType": "swap"},
        }
    )
    install_request_guard(exchange)
    requests: list[dict[str, object]] = []
    try:
        instrument_response = assert_okx_response(
            exchange.public_get_public_instruments(
                {"instType": "SWAP", "instId": INSTRUMENT_ID}
            ),
            "instrument",
        )
        requests.append(request_receipt(exchange, "instrument"))
        if len(instrument_response["data"]) != 1:
            raise RuntimeError("instrument response must contain exactly one market")
        instrument = instrument_response["data"][0]
        if (
            instrument.get("instId") != INSTRUMENT_ID
            or instrument.get("instType") != "SWAP"
            or instrument.get("settleCcy") != "USDT"
            or instrument.get("state") != "live"
        ):
            raise RuntimeError("instrument response does not prove live OKX USDT swap")

        market = exchange.parse_market(instrument)
        if (
            market.get("symbol") != SYMBOL
            or market.get("id") != INSTRUMENT_ID
            or market.get("swap") is not True
            or market.get("linear") is not True
            or market.get("settle") != "USDT"
        ):
            raise RuntimeError("parsed market does not match the target linear perpetual")
        exchange.set_markets([market], {})

        tiers = exchange.fetch_market_leverage_tiers(
            SYMBOL, {"marginMode": "isolated"}
        )
        requests.append(request_receipt(exchange, "isolated-position-tiers"))
        if not tiers or any(tier.get("symbol") != SYMBOL for tier in tiers):
            raise RuntimeError("OKX isolated leverage tiers are missing or mismatched")

        futures = fetch_candles(
            exchange,
            timeframe="5m",
            start_ms=DATA_START_MS,
            end_ms=DATA_END_MS,
            page_limit=300,
            price=None,
            label="futures-5m",
            requests=requests,
        )
        mark = fetch_candles(
            exchange,
            timeframe="1h",
            start_ms=DATA_START_MS,
            end_ms=DATA_END_MS,
            page_limit=100,
            price="mark",
            label="mark-1h",
            requests=requests,
        )
        funding = fetch_funding_history(exchange, requests)
    finally:
        exchange.close()

    futures_stats = assert_regular_series(
        futures,
        label="futures-5m",
        start_ms=DATA_START_MS,
        end_ms=DATA_END_MS,
        step_ms=5 * 60 * 1000,
    )
    mark_stats = assert_regular_series(
        mark,
        label="mark-1h",
        start_ms=DATA_START_MS,
        end_ms=DATA_END_MS,
        step_ms=60 * 60 * 1000,
    )

    funding_stats = validate_funding_history(funding)

    handler = get_datahandler(data_dir, "feather")
    futures_df = ohlcv_to_dataframe(
        futures, "5m", SYMBOL, fill_missing=False, drop_incomplete=False
    )
    mark_df = ohlcv_to_dataframe(
        mark, "1h", SYMBOL, fill_missing=False, drop_incomplete=False
    )
    funding_rows = [
        [item["timestamp"], item["fundingRate"], 0, 0, 0, 0] for item in funding
    ]
    funding_df = ohlcv_to_dataframe(
        funding_rows, "1h", SYMBOL, fill_missing=False, drop_incomplete=False
    )
    handler.ohlcv_store(SYMBOL, "5m", futures_df, CandleType.FUTURES)
    handler.ohlcv_store(SYMBOL, "1h", mark_df, CandleType.MARK)
    handler.ohlcv_store(SYMBOL, "1h", funding_df, CandleType.FUNDING_RATE)

    market_path = root / "market_snapshot.json"
    tiers_path = root / "isolated_tiers_snapshot.json"
    market_path.write_bytes(canonical_bytes(market))
    tiers_path.write_bytes(canonical_bytes(tiers))

    landed = {}
    feather_files = sorted((data_dir / "futures").glob("*.feather"))
    if len(feather_files) != 3:
        raise RuntimeError(f"expected three landed Feather files, found {feather_files!r}")
    for path in feather_files:
        data = path.read_bytes()
        landed[str(path.relative_to(root))] = {
            "bytes": len(data),
            "sha256": sha256(data),
        }

    receipt = {
        "gate": "freqtrade-lab-issue-9-local-only-public-data",
        "host": HOST,
        "authentication": "none",
        "pair": SYMBOL,
        "instrument_id": INSTRUMENT_ID,
        "pair_family": PAIR_FAMILY,
        "data_window": {
            "start_utc": DATA_START.isoformat(),
            "end_exclusive_utc": DATA_END.isoformat(),
            "fully_closed_at_fetch": True,
            "development_start_utc": DEVELOPMENT_START.isoformat(),
            "holdout_start_utc": HOLDOUT_START.isoformat(),
            "startup_candles_required": 20,
        },
        "requests": requests,
        "series": {
            "futures_5m": futures_stats,
            "mark_1h": mark_stats,
            "funding_history": funding_stats,
        },
        "snapshots": {
            str(market_path.relative_to(root)): sha256(market_path.read_bytes()),
            str(tiers_path.relative_to(root)): sha256(tiers_path.read_bytes()),
        },
        "landed_files": landed,
        "runtime": runtime,
        "started_at_utc": started.isoformat(),
        "finished_at_utc": datetime.now(UTC).isoformat(),
    }
    if WINDOW_SCHEMA_USED == STRICT_WINDOW_SPEC_SCHEMA:
        receipt["data_window"]["schema"] = STRICT_WINDOW_SPEC_SCHEMA
    receipt_path = root / "retrieval_receipt.json"
    receipt_path.write_bytes(canonical_bytes(receipt))
    return receipt_path


def file_record(path: Path, role: str, *, status: str | None = None) -> dict[str, object]:
    data = path.read_bytes()
    record: dict[str, object] = {
        "role": role,
        "bytes": len(data),
        "sha256": sha256(data),
    }
    if status is not None:
        record["status"] = status
    return record


def write_local_producer_inputs(
    root: Path,
    receipt_path: Path,
    runtime: dict[str, object],
    local_candidate: LocalCandidateInputs | None = None,
) -> Path:
    """Create a self-contained local producer root without redistributing it."""
    if local_candidate is None:
        strategy_relative = "strategies/StrategyTestV3Futures.py"
        tracked_sources: dict[str, tuple[Path | bytes, str]] = {
            "config.json": (
                FIXTURE_ROOT / "config.json",
                "sanitized_freqtrade_config",
            ),
            "research-spec.json": (
                FIXTURE_ROOT / "research-spec.json",
                "fixed_research_profile_and_candidate",
            ),
            strategy_relative: (
                FIXTURE_ROOT / strategy_relative,
                "gpl_upstream_test_strategy",
            ),
            "UPSTREAM_LICENSE.txt": (
                FIXTURE_ROOT.parent / "UPSTREAM_LICENSE.txt",
                "upstream_gpl_license",
            ),
        }
    else:
        strategy_name, strategy_bytes, research_spec_bytes, class_name = local_candidate
        fixed_config = json.loads((FIXTURE_ROOT / "config.json").read_bytes())
        fixed_config["strategy"] = class_name
        strategy_relative = f"strategies/{strategy_name}"
        tracked_sources = {
            "config.json": (
                canonical_bytes(fixed_config),
                "fixed_okx_config_with_user_selected_candidate",
            ),
            "research-spec.json": (
                research_spec_bytes,
                "user_selected_local_research_spec",
            ),
            strategy_relative: (
                strategy_bytes,
                "user_selected_local_candidate_strategy",
            ),
        }
    tracked_sources["fetch_okx_public_data.py"] = (
        Path(__file__).resolve(strict=True),
        "manual_public_data_acquisition_and_validation",
    )
    files: dict[str, object] = {}
    for relative, (source, role) in tracked_sources.items():
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(source, bytes):
            destination.write_bytes(source)
        else:
            shutil.copyfile(source, destination)
        files[relative] = file_record(destination, role)
    files[receipt_path.name] = file_record(receipt_path, "local_public_retrieval_receipt")

    local_only: dict[str, object] = {}
    for path in sorted((root / "data" / "okx").rglob("*.feather")):
        relative = path.relative_to(root).as_posix()
        if relative.endswith("-5m-futures.feather"):
            role = "merged_futures_ohlcv"
        elif relative.endswith("-1h-mark.feather"):
            role = "merged_mark_ohlcv"
        elif relative.endswith("-1h-funding_rate.feather"):
            role = "merged_funding_rate_series"
        else:
            raise RuntimeError(f"unrecognized generated data file: {relative}")
        local_only[relative] = file_record(
            path, role, status="LOCAL_ONLY_NOT_DISTRIBUTED"
        )
    for name, role in (
        ("market_snapshot.json", "market_snapshot"),
        ("isolated_tiers_snapshot.json", "leverage_tiers"),
    ):
        local_only[name] = file_record(
            root / name, role, status="LOCAL_ONLY_NOT_DISTRIBUTED"
        )

    provenance = {
        "schema": "freqtrade-lab-retained-okx-data-v1",
        "portable_retained_fixture": "BLOCKED_LICENSE",
        "source": {
            "host": HOST,
            "authentication": "none",
            "instrument_id": INSTRUMENT_ID,
            "pair": SYMBOL,
            "pair_family": PAIR_FAMILY,
            "retrieval_receipt": receipt_path.name,
        },
        "freqtrade": {
            "version": EXPECTED_VERSIONS["freqtrade"],
            "tag": runtime["freqtrade_tag"],
            "commit": runtime["freqtrade_commit"],
            "dependencies": {
                name: runtime["versions"][name]
                for name in ("ccxt", "pandas", "pyarrow", "python")
            },
        },
        "contract": {
            "data_dir": "data/okx",
            "market_snapshot": "market_snapshot.json",
            "leverage_tiers": "isolated_tiers_snapshot.json",
            "config": "config.json",
            "strategy": strategy_relative,
            "development_timerange": scenario_timerange(
                DEVELOPMENT_START, HOLDOUT_START
            ),
            "holdout_timerange": scenario_timerange(HOLDOUT_START, DATA_END),
            "timeframe": "5m",
        },
        "files": files,
        "local_only_files": local_only,
    }
    provenance_path = root / "retained-data-provenance.json"
    provenance_path.write_bytes(canonical_bytes(provenance))
    return provenance_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch bounded, public OKX XRP-USDT-SWAP research inputs. "
            "The output is local-only and must stay outside Git."
        )
    )
    parser.add_argument(
        "--output-root",
        required=True,
        type=Path,
        help="new output directory outside this repository",
    )
    parser.add_argument(
        "--strategy-file",
        type=Path,
        help="reviewed local Candidate strategy source; requires --research-spec",
    )
    parser.add_argument(
        "--research-spec",
        type=Path,
        help="local ResearchProfile/Candidate JSON; requires --strategy-file",
    )
    parser.add_argument(
        "--window-spec",
        type=Path,
        help=(
            "optional freqtrade-lab-okx-window-v1/v2 JSON; v2 freezes exact "
            "60-day Development and 30-day Holdout while XRP/5m/OKX stay fixed"
        ),
    )
    args = parser.parse_args()
    if (args.strategy_file is None) != (args.research_spec is None):
        parser.error("--strategy-file and --research-spec must be provided together")
    return args


def is_same_or_below_existing_directory(candidate_parent: Path, boundary: Path) -> bool:
    """Compare existing ancestors by inode so case aliases cannot bypass the boundary."""
    current = candidate_parent.resolve(strict=True)
    boundary = boundary.resolve(strict=True)
    while True:
        if current.samefile(boundary):
            return True
        parent = current.parent
        if parent == current:
            return False
        current = parent


def main() -> None:
    args = parse_args()
    configure_window(getattr(args, "window_spec", None))
    local_candidate = load_local_candidate_inputs(
        args.strategy_file,
        args.research_spec,
    )
    runtime = validate_runtime()
    root = args.output_root.expanduser().resolve()
    if is_same_or_below_existing_directory(root.parent, REPOSITORY_ROOT):
        raise RuntimeError("OKX market data output must stay outside this repository")
    if root.exists():
        raise RuntimeError(f"output root already exists: {root}")
    root.mkdir(parents=False, exist_ok=False)
    try:
        receipt_path = acquire(root, runtime)
        provenance_path = write_local_producer_inputs(
            root, receipt_path, runtime, local_candidate
        )
    except BaseException:
        shutil.rmtree(root)
        raise
    print(receipt_path)
    print(sha256(receipt_path.read_bytes()))
    print(provenance_path)
    print(sha256(provenance_path.read_bytes()))


if __name__ == "__main__":
    main()
