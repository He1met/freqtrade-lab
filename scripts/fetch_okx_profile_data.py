#!/usr/bin/env python3
"""Fetch one Profile-bound, public OKX Search/Development source dataset."""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import http.client
import importlib.util
import io
import json
import math
import os
import shutil
import sys
import time
import zipfile
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from email.utils import parsedate_to_datetime
from pathlib import Path
from types import ModuleType
from typing import Any
from urllib.parse import urlparse

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from lab import bounded_research

HISTORICAL_PRODUCER = (
    REPOSITORY_ROOT
    / "tests"
    / "fixtures"
    / "freqtrade_2026_7"
    / "producer"
    / "fetch_okx_public_data.py"
)
PROFILE_WINDOW_SCHEMA = "freqtrade-lab-profile-source-window-v1"
WINDOW_FIELDS = (
    "data_start_utc",
    "search_start_utc",
    "development_start_utc",
    "end_exclusive_utc",
)
FUNDING_INTERVAL_MS = 8 * 60 * 60 * 1000
FUNDING_ARCHIVE_TIMESTAMP_NORMALIZATION = "FLOOR_TO_8H_GRID_V1"
MAX_FUNDING_ARCHIVE_TIMESTAMP_DRIFT_MS = 2_000
MAX_FUNDING_BATCH = 100
FUNDING_REST_RETENTION = timedelta(days=90)
ARCHIVE_CATALOG_HOST = "www.okx.com"
ARCHIVE_CATALOG_PATH = "/priapi/v5/broker/public/trade-data/download-link"
ARCHIVE_CATALOG_URL = f"https://{ARCHIVE_CATALOG_HOST}{ARCHIVE_CATALOG_PATH}"
ARCHIVE_ASSET_HOST = "static.okx.com"
ARCHIVE_ASSET_PREFIX = "/cdn/okex/traderecords/swaprates/monthly/"
ARCHIVE_QUERY = "v=999"
ARCHIVE_TIMEZONE = timezone(timedelta(hours=8))
ARCHIVE_CSV_HEADER = ["instrument_name", "funding_rate", "funding_time"]
MAX_ARCHIVE_CATALOG_BYTES = 1_000_000
MAX_ARCHIVE_ZIP_BYTES = 10_000_000
MAX_ARCHIVE_CSV_BYTES = 20_000_000
MAX_ARCHIVE_CATALOG_MONTHS = 6
ARCHIVE_CATALOG_THROTTLE_SECONDS = 1.0
ARCHIVE_CATALOG_RETRY_FALLBACK_SECONDS = 2.0
ARCHIVE_CATALOG_RETRY_MAX_SECONDS = 5.0
RECEIPT_HEADERS = (
    "content-type",
    "content-length",
    "etag",
    "last-modified",
    "content-md5",
    "retry-after",
    "x-oss-hash-crc64ecma",
)


class ArchiveCatalogRateLimited(RuntimeError):
    def __init__(self, body: bytes, headers: dict[str, str]) -> None:
        super().__init__("funding archive catalog rate limited")
        self.body = body
        self.headers = headers


def _load_historical_transport() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "_freqtrade_lab_historical_okx_transport", HISTORICAL_PRODUCER
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("historical OKX transport helper is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


transport = _load_historical_transport()
EXPECTED_VERSIONS = transport.EXPECTED_VERSIONS
EXPECTED_FREQTRADE_COMMIT = transport.EXPECTED_FREQTRADE_COMMIT
canonical_bytes = transport.canonical_bytes
sha256 = transport.sha256
file_record = transport.file_record
install_request_guard = transport.install_request_guard
request_receipt = transport.request_receipt
assert_okx_response = transport.assert_okx_response
assert_regular_series = transport.assert_regular_series
validate_ohlcv_values = transport.validate_ohlcv_values
validate_runtime = transport.validate_runtime
is_same_or_below_existing_directory = transport.is_same_or_below_existing_directory

PROFILE_ACQUISITION: dict[str, Any] | None = None
DATA_START: datetime | None = None
SEARCH_START: datetime | None = None
DEVELOPMENT_START: datetime | None = None
DATA_END: datetime | None = None
DATA_START_MS: int | None = None
DATA_END_MS: int | None = None
MARK_START_MS: int | None = None
SYMBOL: str | None = None
INSTRUMENT_ID: str | None = None
PAIR_FAMILY: str | None = None
FUTURES_TIMEFRAME: str | None = None


def _strict_json_object(path: Path, label: str) -> dict[str, Any]:
    def no_duplicates(pairs: list[tuple[str, object]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, child in pairs:
            if key in value:
                raise RuntimeError(f"{label} contains duplicate key {key!r}")
            value[key] = child
        return value

    try:
        raw = path.expanduser().read_bytes()
        value = json.loads(
            raw.decode("utf-8", "strict"),
            object_pairs_hook=no_duplicates,
            parse_constant=lambda item: (_ for _ in ()).throw(
                RuntimeError(f"{label} contains non-finite number {item}")
            ),
        )
    except RuntimeError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise RuntimeError(f"{label} cannot be read as strict JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"{label} must be a JSON object")
    return value


def _utc_z(value: object, label: str) -> datetime:
    if not isinstance(value, str) or len(value) != 20 or not value.endswith("Z"):
        raise RuntimeError(f"{label} must use YYYY-MM-DDTHH:MM:SSZ")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError as exc:
        raise RuntimeError(f"{label} must use YYYY-MM-DDTHH:MM:SSZ") from exc
    return parsed


def load_window_spec(path: Path) -> tuple[datetime, datetime, datetime, datetime]:
    value = _strict_json_object(path, "Profile source window")
    exploratory = value.get("schema") == "freqtrade-lab-exploratory-source-window-v1"
    if exploratory:
        bounded_research.validate_exploration(value.get("exploration"))
    if (
        set(value) != {"schema", *WINDOW_FIELDS} | ({"exploration"} if exploratory else set())
        or value.get("schema") not in {PROFILE_WINDOW_SCHEMA, "freqtrade-lab-exploratory-source-window-v1"}
    ):
        raise RuntimeError("Profile source window shape/version is not supported")
    data_start, search_start, development_start, end_exclusive = (
        _utc_z(value[field], f"Profile source {field}") for field in WINDOW_FIELDS
    )
    if not (data_start < search_start < development_start
            and (development_start == end_exclusive if exploratory else development_start < end_exclusive)):
        raise RuntimeError(
            "Profile source window must satisfy data < Search < Development < stop"
        )
    if any(
        (item.hour, item.minute, item.second, item.microsecond) != (0, 0, 0, 0)
        for item in (search_start, development_start, end_exclusive)
    ):
        raise RuntimeError("Profile Search/Development boundaries must be UTC midnight")
    if end_exclusive >= datetime.now(UTC):
        raise RuntimeError("Profile source window must be fully closed")
    return data_start, search_start, development_start, end_exclusive


def configure_profile_acquisition(
    database: Path,
    profile_id: str,
    window_spec: Path,
    pre_roll_candles: int,
    economic_gate: Any = None,
    single_baseline: Any = None,
) -> dict[str, Any]:
    data_start, search_start, development_start, end_exclusive = load_window_spec(
        window_spec
    )
    exploration = _strict_json_object(window_spec, "Profile source window").get("exploration")
    contract = bounded_research.profile_acquisition_contract(
        database,
        profile_id,
        f"{search_start:%Y%m%d}-{development_start:%Y%m%d}",
        None if exploration is not None else f"{development_start:%Y%m%d}-{end_exclusive:%Y%m%d}",
        pre_roll_candles,
        economic_gate,
        exploration,
        single_baseline,
    )
    step = bounded_research.PROFILE_TIMEFRAME_STEPS[str(contract["timeframe"])]
    if data_start != search_start - step * pre_roll_candles:
        raise RuntimeError(
            "Profile source data_start must equal timeframe times pre-roll candles"
        )
    pair = str(contract["pair"])
    base, quote_settle = pair.split("/", 1)
    quote, settle = quote_settle.split(":", 1)
    if quote != settle:
        raise RuntimeError("Profile pair is not an OKX linear perpetual")
    global PROFILE_ACQUISITION, DATA_START, SEARCH_START, DEVELOPMENT_START
    global DATA_END, DATA_START_MS, DATA_END_MS, MARK_START_MS, SYMBOL, INSTRUMENT_ID
    global PAIR_FAMILY, FUTURES_TIMEFRAME
    PROFILE_ACQUISITION = contract
    DATA_START, SEARCH_START = data_start, search_start
    DEVELOPMENT_START, DATA_END = development_start, end_exclusive
    DATA_START_MS = int(data_start.timestamp() * 1000)
    DATA_END_MS = int(end_exclusive.timestamp() * 1000)
    MARK_START_MS = int(
        data_start.replace(minute=0, second=0, microsecond=0).timestamp() * 1000
    )
    SYMBOL = pair
    INSTRUMENT_ID = f"{base}-{quote}-SWAP"
    PAIR_FAMILY = f"{base}-{quote}"
    FUTURES_TIMEFRAME = str(contract["timeframe"])
    return contract


def _configured() -> dict[str, Any]:
    if PROFILE_ACQUISITION is None or None in (
        DATA_START,
        SEARCH_START,
        DEVELOPMENT_START,
        DATA_END,
        DATA_START_MS,
        DATA_END_MS,
        MARK_START_MS,
        SYMBOL,
        INSTRUMENT_ID,
        PAIR_FAMILY,
        FUTURES_TIMEFRAME,
    ):
        raise RuntimeError("Profile acquisition is not configured")
    return PROFILE_ACQUISITION


def fetch_profile_candles(
    exchange: Any,
    *,
    timeframe: str,
    start_ms: int,
    end_ms: int,
    page_limit: int,
    price: str | None,
    label: str,
    requests: list[dict[str, object]],
) -> list[list]:
    """Fetch candles for the Profile pair, never the historical XRP global."""
    _configured()
    assert SYMBOL is not None
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


def _archive_months() -> list[tuple[int, int]]:
    _configured()
    assert SEARCH_START is not None and DATA_END_MS is not None
    first = int(SEARCH_START.timestamp() * 1000)
    expected = list(range(first, DATA_END_MS, FUNDING_INTERVAL_MS))
    if not expected:
        raise RuntimeError("funding archive window is empty")
    start = datetime.fromtimestamp(expected[0] / 1000, UTC).astimezone(ARCHIVE_TIMEZONE)
    stop = datetime.fromtimestamp(expected[-1] / 1000, UTC).astimezone(ARCHIVE_TIMEZONE)
    result: list[tuple[int, int]] = []
    year, month = start.year, start.month
    while (year, month) <= (stop.year, stop.month):
        result.append((year, month))
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return result


def _archive_month_groups() -> list[list[tuple[int, int]]]:
    months = _archive_months()
    return [
        months[offset : offset + MAX_ARCHIVE_CATALOG_MONTHS]
        for offset in range(0, len(months), MAX_ARCHIVE_CATALOG_MONTHS)
    ]


def _archive_names(year: int, month: int) -> tuple[str, str, str]:
    assert INSTRUMENT_ID is not None
    label = f"{year:04d}-{month:02d}"
    stem = f"{INSTRUMENT_ID}-fundingrates-{label}"
    return label, f"{stem}.zip", f"{stem}.csv"


def _archive_month_bounds(year: int, month: int) -> tuple[int, int]:
    start = datetime(year, month, 1, tzinfo=ARCHIVE_TIMEZONE)
    next_start = (
        datetime(year + 1, 1, 1, tzinfo=ARCHIVE_TIMEZONE)
        if month == 12
        else datetime(year, month + 1, 1, tzinfo=ARCHIVE_TIMEZONE)
    )
    last_day = next_start - timedelta(days=1)
    return int(start.timestamp() * 1000), int(last_day.timestamp() * 1000)


def _validate_archive_endpoint(method: str, url: str) -> tuple[str, str]:
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
        or parsed.fragment
    ):
        raise RuntimeError(f"forbidden funding archive endpoint {url!r}")
    if method == "POST":
        if (
            parsed.hostname != ARCHIVE_CATALOG_HOST
            or parsed.path != ARCHIVE_CATALOG_PATH
            or parsed.query
        ):
            raise RuntimeError(f"forbidden funding archive endpoint {url!r}")
        return ARCHIVE_CATALOG_HOST, parsed.path
    if method == "GET":
        relative = parsed.path.removeprefix(ARCHIVE_ASSET_PREFIX)
        parts = relative.split("/")
        month_key = parts[0] if len(parts) == 2 else ""
        archive_name = parts[1] if len(parts) == 2 else ""
        suffix = (
            f"-fundingrates-{month_key[:4]}-{month_key[4:]}.zip"
            if len(month_key) == 6
            else ""
        )
        instrument = (
            archive_name[: -len(suffix)]
            if suffix and archive_name.endswith(suffix)
            else ""
        )
        if (
            parsed.hostname != ARCHIVE_ASSET_HOST
            or not parsed.path.startswith(ARCHIVE_ASSET_PREFIX)
            or len(parts) != 2
            or not month_key.isascii()
            or not month_key.isdigit()
            or len(month_key) != 6
            or not instrument.endswith("-SWAP")
            or not instrument.isascii()
            or instrument.upper() != instrument
            or not instrument.replace("-", "").isalnum()
            or (INSTRUMENT_ID is not None and instrument != INSTRUMENT_ID)
            or parsed.query != ARCHIVE_QUERY
        ):
            raise RuntimeError(f"forbidden funding archive endpoint {url!r}")
        return ARCHIVE_ASSET_HOST, f"{parsed.path}?{parsed.query}"
    raise RuntimeError(f"forbidden funding archive method {method!r}")


def _receipt_headers(headers: list[tuple[str, str]]) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw_name, value in headers:
        name = raw_name.lower()
        if name in result:
            raise RuntimeError(f"funding archive response repeats header {name!r}")
        if name in RECEIPT_HEADERS:
            result[name] = value
    return result


def archive_http_request(
    method: str, url: str, *, body: bytes | None = None
) -> tuple[bytes, dict[str, str]]:
    """Perform one pinned, unauthenticated HTTPS request without redirects."""
    host, target = _validate_archive_endpoint(method, url)
    if (method == "POST") != (body is not None):
        raise RuntimeError("funding archive request body disagrees with method")
    maximum = MAX_ARCHIVE_CATALOG_BYTES if method == "POST" else MAX_ARCHIVE_ZIP_BYTES
    headers = {
        "Accept": "application/json" if method == "POST" else "application/zip",
        "Accept-Encoding": "identity",
        "User-Agent": "freqtrade-lab-profile-source-v1",
    }
    if body is not None:
        headers["Content-Type"] = "application/json"
    connection = http.client.HTTPSConnection(host, timeout=30)
    response: http.client.HTTPResponse | None = None
    try:
        connection.request(method, target, body=body, headers=headers)
        response = connection.getresponse()
        if 300 <= response.status < 400:
            raise RuntimeError("funding archive redirect response rejected")
        rate_limited = method == "POST" and response.status == 429
        if response.status != 200 and not rate_limited:
            raise RuntimeError(
                f"funding archive HTTP status {response.status} is not successful"
            )
        selected = _receipt_headers(response.getheaders())
        content_encoding = response.getheader("Content-Encoding")
        if content_encoding not in (None, "", "identity"):
            raise RuntimeError("funding archive response encoding is not identity")
        raw_length = selected.get("content-length")
        if raw_length is not None:
            try:
                length = int(raw_length)
            except ValueError as exc:
                raise RuntimeError("funding archive Content-Length is invalid") from exc
            if length < 0 or length > maximum:
                raise RuntimeError("funding archive response is too large")
        data = response.read(maximum + 1)
        if len(data) > maximum:
            raise RuntimeError("funding archive response is too large")
        if raw_length is not None and len(data) != int(raw_length):
            raise RuntimeError("funding archive Content-Length disagrees with body")
        content_md5 = selected.get("content-md5")
        if content_md5 is not None:
            try:
                expected_md5 = base64.b64decode(content_md5, validate=True)
            except ValueError as exc:
                raise RuntimeError("funding archive Content-MD5 is invalid") from exc
            if len(expected_md5) != 16 or hashlib.md5(data).digest() != expected_md5:
                raise RuntimeError("funding archive Content-MD5 mismatch")
        if rate_limited:
            raise ArchiveCatalogRateLimited(data, selected)
        return data, selected
    finally:
        if response is not None:
            response.close()
        connection.close()


def _strict_catalog_response(raw: bytes) -> dict[str, Any]:
    def no_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise RuntimeError(
                    f"funding archive catalog contains duplicate key {key!r}"
                )
            result[key] = value
        return result

    try:
        value = json.loads(
            raw.decode("utf-8", "strict"),
            object_pairs_hook=no_duplicates,
            parse_constant=lambda item: (_ for _ in ()).throw(
                RuntimeError(
                    f"funding archive catalog contains non-finite number {item}"
                )
            ),
        )
    except RuntimeError:
        raise
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise RuntimeError(
            f"funding archive catalog is not strict JSON: {exc}"
        ) from exc
    if not isinstance(value, dict):
        raise RuntimeError("funding archive catalog must be a JSON object")
    return value


def _month_after(month: tuple[int, int]) -> tuple[int, int]:
    year, number = month
    return (year + 1, 1) if number == 12 else (year, number + 1)


def _catalog_group_label(months: list[tuple[int, int]]) -> str:
    first = f"{months[0][0]:04d}-{months[0][1]:02d}"
    last = f"{months[-1][0]:04d}-{months[-1][1]:02d}"
    return first if first == last else f"{first}-through-{last}"


def _catalog_retry_delay(value: str | None, *, now: datetime | None = None) -> float:
    fallback = max(
        ARCHIVE_CATALOG_THROTTLE_SECONDS,
        ARCHIVE_CATALOG_RETRY_FALLBACK_SECONDS,
    )
    if value is None:
        return fallback
    delay: float | None = None
    if value.isascii() and value.isdigit():
        delay = float(int(value))
    else:
        try:
            parsed = parsedate_to_datetime(value)
            if parsed.tzinfo is None or parsed.utcoffset() is None:
                raise ValueError("Retry-After date must be timezone-aware")
            current = datetime.now(UTC) if now is None else now.astimezone(UTC)
            delay = (parsed.astimezone(UTC) - current).total_seconds()
        except (TypeError, ValueError, OverflowError):
            return fallback
    if delay < 0 or delay > ARCHIVE_CATALOG_RETRY_MAX_SECONDS:
        return fallback
    return max(ARCHIVE_CATALOG_THROTTLE_SECONDS, delay)


def _catalog_attempt_receipt(
    *,
    label: str,
    attempt: int,
    body: bytes,
    raw: bytes,
    headers: dict[str, str],
    status: int,
) -> dict[str, object]:
    return {
        "label": f"funding-archive-catalog-{label}-attempt-{attempt}",
        "method": "POST",
        "url": ARCHIVE_CATALOG_URL,
        "attempt": attempt,
        "http_status": status,
        "fetched_at_utc": datetime.now(UTC).isoformat(),
        "request_bytes": len(body),
        "request_sha256": sha256(body),
        "response_bytes": len(raw),
        "response_sha256": sha256(raw),
        "response_headers": headers,
    }


def _request_archive_catalog(
    body: bytes,
    *,
    label: str,
    requests: list[dict[str, object]],
) -> tuple[bytes, dict[str, str]]:
    time.sleep(ARCHIVE_CATALOG_THROTTLE_SECONDS)
    for attempt in (1, 2):
        try:
            raw, headers = archive_http_request("POST", ARCHIVE_CATALOG_URL, body=body)
        except ArchiveCatalogRateLimited as exc:
            receipt = _catalog_attempt_receipt(
                label=label,
                attempt=attempt,
                body=body,
                raw=exc.body,
                headers=exc.headers,
                status=429,
            )
            requests.append(receipt)
            if attempt == 2:
                raise RuntimeError(
                    f"funding archive catalog group {label} remained rate limited"
                ) from exc
            delay = _catalog_retry_delay(exc.headers.get("retry-after"))
            receipt["retry_wait_seconds"] = delay
            time.sleep(delay)
            continue
        requests.append(
            _catalog_attempt_receipt(
                label=label,
                attempt=attempt,
                body=body,
                raw=raw,
                headers=headers,
                status=200,
            )
        )
        return raw, headers
    raise AssertionError("catalog retry loop did not terminate")


def _archive_catalog_group(
    months: list[tuple[int, int]], requests: list[dict[str, object]]
) -> list[tuple[int, int, str, str, str]]:
    _configured()
    assert PAIR_FAMILY is not None and INSTRUMENT_ID is not None
    if not 1 <= len(months) <= MAX_ARCHIVE_CATALOG_MONTHS or any(
        current != _month_after(previous)
        for previous, current in zip(months, months[1:], strict=False)
    ):
        raise RuntimeError(
            "funding archive catalog months must be consecutive and bounded"
        )
    label = _catalog_group_label(months)
    begin = _archive_month_bounds(*months[0])[0]
    end = _archive_month_bounds(*months[-1])[1]
    payload = {
        "dateQuery": {
            "begin": str(begin),
            "dateAggrType": "monthly",
            "end": str(end),
        },
        "instQueryParam": {"instFamilyList": [PAIR_FAMILY]},
        "instType": "SWAP",
        "module": "3",
    }
    body = canonical_bytes(payload)
    raw, headers = _request_archive_catalog(body, label=label, requests=requests)
    content_type = headers.get("content-type", "")
    if not content_type.lower().startswith("application/json"):
        raise RuntimeError("funding archive catalog Content-Type is not JSON")
    value = _strict_catalog_response(raw)
    if set(value) != {"code", "data", "msg"} or value.get("code") != "0":
        raise RuntimeError("funding archive catalog response is unsuccessful")
    data = value.get("data")
    expected_data_fields = {
        "begin",
        "ccyList",
        "dateAggrType",
        "details",
        "end",
        "exportTime",
        "instrumentList",
        "totalSizeMB",
    }
    if not isinstance(data, dict) or set(data) != expected_data_fields:
        raise RuntimeError("funding archive catalog data shape changed")
    if (
        data.get("begin") != str(begin)
        or data.get("end") != str(end)
        or data.get("dateAggrType") != "monthly"
        or data.get("ccyList") != []
        or data.get("instrumentList") != [PAIR_FAMILY]
        or not isinstance(data.get("exportTime"), str)
        or not str(data.get("exportTime")).isdigit()
        or not isinstance(data.get("totalSizeMB"), str)
    ):
        raise RuntimeError("funding archive catalog contract changed")
    details = data.get("details")
    if not isinstance(details, list) or len(details) != 1:
        raise RuntimeError(
            f"funding archive catalog group {label} has missing, duplicate, or extra months"
        )
    detail = details[0]
    expected_detail_fields = {
        "ccy",
        "dateRangeEnd",
        "dateRangeStart",
        "groupDetails",
        "groupSizeMB",
        "instFamily",
        "instId",
        "instType",
    }
    if not isinstance(detail, dict) or set(detail) != expected_detail_fields:
        raise RuntimeError("funding archive catalog detail shape changed")
    groups = detail.get("groupDetails")
    first_month_start = str(_archive_month_bounds(*months[0])[0])
    last_month_start = str(_archive_month_bounds(*months[-1])[0])
    if (
        detail.get("ccy") != ""
        or detail.get("dateRangeStart") != first_month_start
        or detail.get("dateRangeEnd") != last_month_start
        or detail.get("instFamily") != PAIR_FAMILY
        or detail.get("instId") != ""
        or detail.get("instType") != "SWAP"
        or not isinstance(detail.get("groupSizeMB"), str)
        or not isinstance(groups, list)
        or len(groups) != len(months)
    ):
        raise RuntimeError(f"funding archive catalog group {label} drifted")
    expected: dict[str, tuple[int, int, str, str]] = {}
    for year, month in months:
        _, archive_name, csv_name = _archive_names(year, month)
        expected[str(_archive_month_bounds(year, month)[0])] = (
            year,
            month,
            archive_name,
            csv_name,
        )
    found: dict[str, tuple[int, int, str, str, str]] = {}
    for group in groups:
        if not isinstance(group, dict) or set(group) != {
            "dateTs",
            "filename",
            "sizeMB",
            "url",
        }:
            raise RuntimeError("funding archive catalog group shape changed")
        date_ts = group.get("dateTs")
        if not isinstance(date_ts, str) or date_ts not in expected or date_ts in found:
            raise RuntimeError(
                f"funding archive catalog group {label} has missing, duplicate, or extra months"
            )
        year, month, archive_name, csv_name = expected[date_ts]
        url = group.get("url")
        if (
            group.get("filename") != archive_name
            or not isinstance(group.get("sizeMB"), str)
            or not isinstance(url, str)
        ):
            raise RuntimeError(
                f"funding archive catalog month {year:04d}-{month:02d} drifted"
            )
        expected_path = f"{ARCHIVE_ASSET_PREFIX}{year:04d}{month:02d}/{archive_name}"
        parsed = urlparse(url)
        _validate_archive_endpoint("GET", url)
        if parsed.path != expected_path:
            raise RuntimeError(
                f"funding archive catalog month {year:04d}-{month:02d} path drifted"
            )
        found[date_ts] = (year, month, url, archive_name, csv_name)
    if set(found) != set(expected):
        raise RuntimeError(
            f"funding archive catalog group {label} has missing, duplicate, or extra months"
        )
    return [found[str(_archive_month_bounds(*month)[0])] for month in months]


def _parse_funding_archive(
    raw: bytes,
    *,
    archive_name: str,
    csv_name: str,
    year: int,
    month: int,
    start_ms: int,
    end_exclusive_ms: int,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    """Interpret rates only when raw AND floored times belong to [start, end).

    Raw time is checked first: flooring never admits a rate at/after the cutoff,
    even when the cutoff is a grid point plus a legal drift. Profile callers use
    UTC-midnight boundaries. Hashes cover all bytes; csv_rows counts all records
    excluding the header, while csv_physical_lines includes the header and any
    embedded newlines. Unselected rates have no semantic validation.
    """
    assert INSTRUMENT_ID is not None
    if start_ms >= end_exclusive_ms:
        raise RuntimeError("funding archive window is empty")
    label = f"{year:04d}-{month:02d}"
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            members = archive.infolist()
            if len(members) != 1 or members[0].filename != csv_name:
                raise RuntimeError(
                    f"funding archive {archive_name} must contain exactly {csv_name}"
                )
            member = members[0]
            if member.is_dir() or member.flag_bits & 1:
                raise RuntimeError(f"funding archive {archive_name} member is invalid")
            if member.file_size < 1 or member.file_size > MAX_ARCHIVE_CSV_BYTES:
                raise RuntimeError(f"funding archive {archive_name} CSV is too large")
            with archive.open(member) as stream:
                csv_raw = stream.read(MAX_ARCHIVE_CSV_BYTES + 1)
            if len(csv_raw) != member.file_size or len(csv_raw) > MAX_ARCHIVE_CSV_BYTES:
                raise RuntimeError(f"funding archive {archive_name} CSV size mismatch")
    except zipfile.BadZipFile as exc:
        raise RuntimeError(
            f"funding archive {archive_name} is not a valid ZIP"
        ) from exc
    try:
        reader = csv.reader(io.StringIO(csv_raw.decode("utf-8", "strict")), strict=True)
        header = next(reader)
        if header != ARCHIVE_CSV_HEADER:
            raise RuntimeError(f"funding archive {archive_name} header changed")
        rows: list[dict[str, object]] = []
        csv_rows = 0
        timestamp_drifts: list[int] = []
        for number, fields in enumerate(reader, start=2):
            csv_rows += 1
            if len(fields) != 3:
                raise RuntimeError(
                    f"funding archive {archive_name} row {number} shape changed"
                )
            if fields[0] != INSTRUMENT_ID:
                raise RuntimeError(
                    f"funding archive {archive_name} row {number} instrument mismatch"
                )
            raw_timestamp = fields[2]
            if (
                len(raw_timestamp) != 13
                or not raw_timestamp.isascii()
                or not raw_timestamp.isdigit()
            ):
                raise RuntimeError(
                    f"funding archive {archive_name} row {number} timestamp is invalid"
                )
            timestamp = int(raw_timestamp)
            if not start_ms <= timestamp < end_exclusive_ms:
                continue
            drift = timestamp % FUNDING_INTERVAL_MS
            normalized_timestamp = timestamp - drift
            if not start_ms <= normalized_timestamp < end_exclusive_ms:
                continue
            local = datetime.fromtimestamp(timestamp / 1000, UTC).astimezone(
                ARCHIVE_TIMEZONE
            )
            if (local.year, local.month) != (year, month) or not (
                0 <= drift <= MAX_FUNDING_ARCHIVE_TIMESTAMP_DRIFT_MS
            ):
                reasons = []
                if (local.year, local.month) != (year, month):
                    reasons.append("MONTH_MISMATCH")
                if not 0 <= drift <= MAX_FUNDING_ARCHIVE_TIMESTAMP_DRIFT_MS:
                    reasons.append("DRIFT_EXCEEDS_LIMIT")
                # Only validated clock values and byte identity belong in stderr.
                # Keep the legacy prefix and RuntimeError for existing callers.
                raise RuntimeError(
                    f"funding archive month {label} timestamp drifted: "
                    f"reasons={','.join(reasons)}; row={number}; "
                    f"expected_month={label}; actual_month={local:%Y-%m}; "
                    f"month_timezone=UTC+08:00; raw_timestamp_ms={timestamp}; "
                    f"normalized_timestamp_ms={normalized_timestamp}; "
                    f"drift_ms={drift}; "
                    f"maximum_drift_ms={MAX_FUNDING_ARCHIVE_TIMESTAMP_DRIFT_MS}; "
                    f"archive_sha256={sha256(raw)}"
                )
            try:
                rate = float(fields[1])
            except ValueError:
                raise RuntimeError(
                    f"funding archive {archive_name} row {number} rate is invalid"
                ) from None
            if not math.isfinite(rate):
                raise RuntimeError(
                    f"funding archive {archive_name} row {number} rate is not finite"
                )
            rows.append({"timestamp": normalized_timestamp, "fundingRate": rate})
            timestamp_drifts.append(drift)
    except (UnicodeError, csv.Error, StopIteration):
        raise RuntimeError(f"funding archive {archive_name} CSV is invalid") from None
    if not csv_rows:
        raise RuntimeError(f"funding archive {archive_name} CSV is empty")
    return rows, {
        "archive_filename": archive_name,
        "archive_bytes": len(raw),
        "archive_sha256": sha256(raw),
        "csv_filename": csv_name,
        "csv_bytes": len(csv_raw),
        "csv_sha256": sha256(csv_raw),
        "csv_rows": csv_rows,
        "csv_physical_lines": reader.line_num,
        "rate_selection": {
            "method": "RAW_AND_NORMALIZED_IN_HALF_OPEN_V1",
            "start_ms": start_ms,
            "end_exclusive_ms": end_exclusive_ms,
            "selected_rows": len(rows),
            "uninterpreted_rate_rows": csv_rows - len(rows),
            "uninterpreted_rate_validation": "NOT_PERFORMED",
        },
        "timestamp_normalization": {
            "method": FUNDING_ARCHIVE_TIMESTAMP_NORMALIZATION,
            "scope": "SELECTED_ROWS",
            "maximum_allowed_drift_ms": MAX_FUNDING_ARCHIVE_TIMESTAMP_DRIFT_MS,
            "maximum_observed_drift_ms": max(timestamp_drifts, default=None),
            "normalized_rows": sum(drift > 0 for drift in timestamp_drifts),
        },
    }


def fetch_archive_funding_history(
    requests: list[dict[str, object]],
) -> list[dict[str, object]]:
    _configured()
    assert SEARCH_START is not None and DATA_END_MS is not None
    first = int(SEARCH_START.timestamp() * 1000)
    output: list[dict[str, object]] = []
    seen_archives: set[str] = set()
    catalog_entries = [
        entry
        for months in _archive_month_groups()
        for entry in _archive_catalog_group(months, requests)
    ]
    for year, month, url, archive_name, csv_name in catalog_entries:
        label = f"{year:04d}-{month:02d}"
        if archive_name in seen_archives:
            raise RuntimeError(f"funding archive month {label} is repeated")
        seen_archives.add(archive_name)
        raw, headers = archive_http_request("GET", url)
        content_type = headers.get("content-type", "")
        if not content_type.lower().startswith("application/zip"):
            raise RuntimeError(f"funding archive month {label} Content-Type is not ZIP")
        rows, archive_receipt = _parse_funding_archive(
            raw,
            archive_name=archive_name,
            csv_name=csv_name,
            year=year,
            month=month,
            start_ms=first,
            end_exclusive_ms=DATA_END_MS,
        )
        requests.append(
            {
                "label": f"funding-archive-{label}",
                "method": "GET",
                "url": url,
                "fetched_at_utc": datetime.now(UTC).isoformat(),
                "response_bytes": len(raw),
                "response_sha256": sha256(raw),
                "response_headers": headers,
                **archive_receipt,
            }
        )
        output.extend(rows)
    all_timestamps = [int(row["timestamp"]) for row in output]
    if len(all_timestamps) != len(set(all_timestamps)):
        raise RuntimeError("funding archive contains duplicate UTC timestamps")
    output.sort(key=lambda row: int(row["timestamp"]))
    validate_funding_history(output)
    return output


class _RestFundingValidationError(RuntimeError):
    """A funding validation message that contains no response values."""


def _validate_rest_funding_response(
    raw_text: object, response: object, timestamps: list[int], label: str
) -> dict[int, float]:
    """Validate the unfiltered response before CCXT can drop any funding events."""
    def strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        value: dict[str, object] = {}
        for key, child in pairs:
            if key in value:
                raise ValueError("duplicate JSON key")
            value[key] = child
        return value

    def reject_constant(value: str) -> None:
        raise ValueError("non-finite JSON constant")

    if not isinstance(raw_text, str):
        raise _RestFundingValidationError(f"{label}: raw response evidence is unavailable")
    try:
        raw = json.loads(
            raw_text, object_pairs_hook=strict_object, parse_constant=reject_constant
        )
    except (ValueError, RecursionError):
        raise _RestFundingValidationError(f"{label}: raw response is not strict JSON") from None
    if (
        not isinstance(raw, dict)
        or raw.get("code") != "0"
        or raw.get("msg") not in ("", None)
        or not isinstance(raw.get("data"), list)
        or raw != response
    ):
        raise _RestFundingValidationError(f"{label}: raw response contract changed")
    rows = raw["data"]
    if len(rows) != len(timestamps):
        raise _RestFundingValidationError(f"{label}: raw event count differs from the complete eight-hour grid")
    expected = set(timestamps)
    seen: set[int] = set()
    # Validate every clock and identity before interpreting any actual rate.
    for row in rows:
        if not isinstance(row, dict) or row.get("instId") != INSTRUMENT_ID:
            raise _RestFundingValidationError(f"{label}: raw instrument identity is invalid")
        timestamp = row.get("fundingTime")
        if (
            not isinstance(timestamp, str)
            or not timestamp.isascii()
            or not timestamp.isdecimal()
            or len(timestamp) > 16
            or str(int(timestamp)) != timestamp
        ):
            raise _RestFundingValidationError(f"{label}: raw funding timestamp is invalid")
        timestamp_ms = int(timestamp)
        if timestamp_ms not in expected or timestamp_ms in seen:
            raise _RestFundingValidationError(f"{label}: raw timestamps differ from the complete eight-hour grid")
        seen.add(timestamp_ms)
    rates: dict[int, float] = {}
    for row in rows:
        value = row.get("realizedRate")
        if not isinstance(value, str) or not value or value != value.strip():
            raise _RestFundingValidationError(f"{label}: actual funding rate is invalid")
        try:
            actual = Decimal(value)
            rate = float(actual)
        except (InvalidOperation, ValueError, OverflowError):
            raise _RestFundingValidationError(f"{label}: actual funding rate is invalid") from None
        if not actual.is_finite() or not math.isfinite(rate) or (rate == 0 and actual != 0):
            raise _RestFundingValidationError(f"{label}: actual funding rate is not representable and finite")
        rates[int(row["fundingTime"])] = rate
    return rates


def fetch_rest_funding_history(
    exchange: Any, requests: list[dict[str, object]]
) -> list[dict]:
    _configured()
    assert SEARCH_START is not None and DATA_END_MS is not None and SYMBOL is not None
    first = int(SEARCH_START.timestamp() * 1000)
    expected = list(range(first, DATA_END_MS, FUNDING_INTERVAL_MS))
    output: list[dict] = []
    batches = math.ceil(len(expected) / MAX_FUNDING_BATCH)
    for offset in range(0, len(expected), MAX_FUNDING_BATCH):
        timestamps = expected[offset : offset + MAX_FUNDING_BATCH]
        batch_start = timestamps[0]
        batch_end = batch_start + len(timestamps) * FUNDING_INTERVAL_MS
        number = offset // MAX_FUNDING_BATCH + 1
        label = f"funding history batch {number}"
        # N+1 reveals overflow regardless of API ordering; do not widen the window.
        limit = len(timestamps) + 1
        raw_rates: dict[int, float] | None = None
        endpoint = exchange.publicGetPublicFundingRateHistory

        def checked_endpoint(params: dict) -> object:
            nonlocal raw_rates
            if raw_rates is not None or params != {
                "instId": INSTRUMENT_ID,
                "before": batch_start - 1,
                "after": batch_end,
                "limit": limit,
            }:
                raise _RestFundingValidationError(f"{label}: CCXT request contract changed")
            exchange.last_http_response = None
            try:
                response = endpoint(params)
            except Exception:
                # CCXT errors may embed an entire response, including protected rates.
                raise _RestFundingValidationError(f"{label}: public funding request failed") from None
            raw_rates = _validate_rest_funding_response(
                exchange.last_http_response, response, timestamps, label
            )
            return response

        exchange.publicGetPublicFundingRateHistory = checked_endpoint
        try:
            rows = exchange.fetch_funding_rate_history(
                SYMBOL, since=batch_start, limit=limit, params={"after": batch_end}
            )
        except _RestFundingValidationError:
            raise
        except Exception:
            raise RuntimeError(f"{label}: CCXT funding parsing failed") from None
        finally:
            exchange.publicGetPublicFundingRateHistory = endpoint
        requests.append(
            request_receipt(
                exchange,
                "funding-history" if batches == 1 else f"funding-history-{number}",
            )
        )
        if raw_rates is None or not isinstance(rows, list) or len(rows) != len(timestamps):
            raise RuntimeError(f"{label}: CCXT parsed event count differs from raw evidence")
        for row, timestamp in zip(rows, timestamps):
            if (
                not isinstance(row, dict)
                or type(row.get("timestamp")) is not int
                or row["timestamp"] != timestamp
                or row.get("symbol") != SYMBOL
                or type(row.get("fundingRate")) not in (int, float)
                or not math.isfinite(row["fundingRate"])
                or row["fundingRate"] != raw_rates[timestamp]
            ):
                raise RuntimeError(f"{label}: CCXT parsed event differs from raw evidence")
        output.extend(rows)
    return output


def fetch_funding_history(
    exchange: Any,
    requests: list[dict[str, object]],
    *,
    fetched_at: datetime | None = None,
) -> list[dict]:
    _configured()
    assert SEARCH_START is not None
    current = datetime.now(UTC) if fetched_at is None else fetched_at
    if current.tzinfo is None or current.utcoffset() is None:
        raise RuntimeError("funding retrieval timestamp must be timezone-aware")
    if SEARCH_START < current.astimezone(UTC) - FUNDING_REST_RETENTION:
        return fetch_archive_funding_history(requests)
    return fetch_rest_funding_history(exchange, requests)


def validate_funding_history(funding: list[dict]) -> dict[str, object]:
    _configured()
    assert SEARCH_START is not None and DATA_END_MS is not None
    expected = list(
        range(int(SEARCH_START.timestamp() * 1000), DATA_END_MS, FUNDING_INTERVAL_MS)
    )
    timestamps = [item.get("timestamp") for item in funding]
    if timestamps != expected:
        raise RuntimeError(
            "funding history must cover every fixed eight-hour timestamp"
        )
    rates = [item.get("fundingRate") for item in funding]
    if any(
        isinstance(rate, bool) or not isinstance(rate, (int, float)) for rate in rates
    ):
        raise RuntimeError("funding history contains an invalid funding rate")
    return {
        "rows": len(funding),
        "first_timestamp": timestamps[0],
        "last_timestamp": timestamps[-1],
    }


def store_profile_market_data(
    data_dir: Path,
    futures: list[list],
    mark: list[list],
    funding: list[dict],
) -> None:
    """Write only Freqtrade 2026.7's standard futures data representation."""
    _configured()
    assert SYMBOL is not None and FUTURES_TIMEFRAME is not None
    handler = transport.get_datahandler(data_dir, "feather")
    futures_df = transport.ohlcv_to_dataframe(
        futures,
        FUTURES_TIMEFRAME,
        SYMBOL,
        fill_missing=False,
        drop_incomplete=False,
    )
    mark_df = transport.ohlcv_to_dataframe(
        mark, "1h", SYMBOL, fill_missing=False, drop_incomplete=False
    )
    funding_df = transport.ohlcv_to_dataframe(
        [[item["timestamp"], item["fundingRate"], 0, 0, 0, 0] for item in funding],
        "1h",
        SYMBOL,
        fill_missing=False,
        drop_incomplete=False,
    )
    handler.ohlcv_store(
        SYMBOL, FUTURES_TIMEFRAME, futures_df, transport.CandleType.FUTURES
    )
    handler.ohlcv_store(SYMBOL, "1h", mark_df, transport.CandleType.MARK)
    handler.ohlcv_store(SYMBOL, "1h", funding_df, transport.CandleType.FUNDING_RATE)


def acquire(root: Path, runtime: dict[str, object]) -> Path:
    contract = _configured()
    assert all(
        item is not None
        for item in (
            DATA_START,
            SEARCH_START,
            DEVELOPMENT_START,
            DATA_END,
            DATA_START_MS,
            DATA_END_MS,
            MARK_START_MS,
            SYMBOL,
            INSTRUMENT_ID,
            PAIR_FAMILY,
            FUTURES_TIMEFRAME,
        )
    )
    data_dir = root / "data" / "okx"
    data_dir.mkdir(parents=True, exist_ok=False)
    started = datetime.now(UTC)
    if DATA_END >= started:
        raise RuntimeError("Profile source window is not fully closed")
    exchange = transport.ccxt.okx(
        {
            "enableRateLimit": True,
            "timeout": 30000,
            "options": {"defaultType": "swap"},
        }
    )
    install_request_guard(exchange)
    requests: list[dict[str, object]] = []
    try:
        response = assert_okx_response(
            exchange.public_get_public_instruments(
                {"instType": "SWAP", "instId": INSTRUMENT_ID}
            ),
            "instrument",
        )
        requests.append(request_receipt(exchange, "instrument"))
        if len(response["data"]) != 1:
            raise RuntimeError("instrument response must contain exactly one market")
        instrument = response["data"][0]
        if (
            instrument.get("instId") != INSTRUMENT_ID
            or instrument.get("instType") != "SWAP"
            or instrument.get("settleCcy") != SYMBOL.split("/", 1)[1].split(":", 1)[0]
            or instrument.get("state") != "live"
        ):
            raise RuntimeError("instrument response does not match the Profile")
        market = exchange.parse_market(instrument)
        if (
            market.get("symbol") != SYMBOL
            or market.get("id") != INSTRUMENT_ID
            or market.get("swap") is not True
            or market.get("linear") is not True
        ):
            raise RuntimeError("parsed market does not match the Profile")
        exchange.set_markets([market], {})
        tiers = exchange.fetch_market_leverage_tiers(SYMBOL, {"marginMode": "isolated"})
        requests.append(request_receipt(exchange, "isolated-position-tiers"))
        if not tiers or any(tier.get("symbol") != SYMBOL for tier in tiers):
            raise RuntimeError("OKX isolated leverage tiers are missing or mismatched")
        futures = fetch_profile_candles(
            exchange,
            timeframe=FUTURES_TIMEFRAME,
            start_ms=DATA_START_MS,
            end_ms=DATA_END_MS,
            page_limit=300 if FUTURES_TIMEFRAME == "5m" else 100,
            price=None,
            label=f"futures-{FUTURES_TIMEFRAME}",
            requests=requests,
        )
        mark = fetch_profile_candles(
            exchange,
            timeframe="1h",
            start_ms=MARK_START_MS,
            end_ms=DATA_END_MS,
            page_limit=100,
            price="mark",
            label="mark-1h",
            requests=requests,
        )
        funding = fetch_funding_history(exchange, requests, fetched_at=started)
    finally:
        exchange.close()
    step_ms = int(
        bounded_research.PROFILE_TIMEFRAME_STEPS[FUTURES_TIMEFRAME].total_seconds()
        * 1000
    )
    futures_stats = assert_regular_series(
        futures,
        label=f"futures-{FUTURES_TIMEFRAME}",
        start_ms=DATA_START_MS,
        end_ms=DATA_END_MS,
        step_ms=step_ms,
    )
    mark_stats = assert_regular_series(
        mark,
        label="mark-1h",
        start_ms=MARK_START_MS,
        end_ms=DATA_END_MS,
        step_ms=60 * 60 * 1000,
    )
    funding_stats = validate_funding_history(funding)
    store_profile_market_data(data_dir, futures, mark, funding)
    market_path = root / "market_snapshot.json"
    tiers_path = root / "isolated_tiers_snapshot.json"
    market_path.write_bytes(canonical_bytes(market))
    tiers_path.write_bytes(canonical_bytes(tiers))
    landed: dict[str, dict[str, object]] = {}
    feathers = sorted((data_dir / "futures").glob("*.feather"))
    if len(feathers) != 3:
        raise RuntimeError("Profile acquisition must land exactly three Feather files")
    for path in feathers:
        data = path.read_bytes()
        landed[path.relative_to(root).as_posix()] = {
            "bytes": len(data),
            "sha256": sha256(data),
        }
    receipt = {
        "gate": "freqtrade-lab-profile-source-v1",
        "host": "www.okx.com",
        "authentication": "none",
        "pair": SYMBOL,
        "instrument_id": INSTRUMENT_ID,
        "pair_family": PAIR_FAMILY,
        "data_window": {
            "start_utc": DATA_START.isoformat(),
            "end_exclusive_utc": DATA_END.isoformat(),
            "fully_closed_at_fetch": True,
            "development_start_utc": SEARCH_START.isoformat(),
            "holdout_start_utc": DEVELOPMENT_START.isoformat(),
            "startup_candles_required": contract["pre_roll_candles"],
        },
        "requests": requests,
        "series": {
            f"futures_{FUTURES_TIMEFRAME}": futures_stats,
            "mark_1h": mark_stats,
            "funding_history": funding_stats,
        },
        "snapshots": {
            "market_snapshot.json": sha256(market_path.read_bytes()),
            "isolated_tiers_snapshot.json": sha256(tiers_path.read_bytes()),
        },
        "landed_files": landed,
        "runtime": runtime,
        "started_at_utc": started.isoformat(),
        "finished_at_utc": datetime.now(UTC).isoformat(),
    }
    path = root / "retrieval_receipt.json"
    path.write_bytes(canonical_bytes(receipt))
    return path


def implementation_snapshot() -> dict[str, bytes]:
    paths = {
        "producer/fetch_okx_profile_data.py": Path(__file__).resolve(strict=True),
        "producer/historical_fetch_okx_public_data.py": (
            HISTORICAL_PRODUCER.resolve(strict=True)
        ),
    }
    result: dict[str, bytes] = {}
    for name, path in paths.items():
        if path.is_symlink() or not path.is_file():
            raise RuntimeError("Profile producer implementation is unavailable")
        result[name] = path.read_bytes()
    return result


def write_profile_provenance(
    root: Path,
    receipt_path: Path,
    runtime: dict[str, object],
    implementations: dict[str, bytes] | None = None,
) -> Path:
    contract = _configured()
    assert all(
        item is not None
        for item in (SYMBOL, INSTRUMENT_ID, PAIR_FAMILY, FUTURES_TIMEFRAME)
    )
    config = canonical_bytes(contract["runtime_config"])
    (root / "config.json").write_bytes(config)
    frozen_implementations = (
        implementation_snapshot() if implementations is None else implementations
    )
    if frozen_implementations != implementation_snapshot():
        raise RuntimeError("Profile producer implementation changed during acquisition")
    producer_dir = root / "producer"
    producer_dir.mkdir()
    current_copy = producer_dir / "fetch_okx_profile_data.py"
    historical_copy = producer_dir / "historical_fetch_okx_public_data.py"
    current_copy.write_bytes(
        frozen_implementations["producer/fetch_okx_profile_data.py"]
    )
    historical_copy.write_bytes(
        frozen_implementations["producer/historical_fetch_okx_public_data.py"]
    )
    files = {
        "config.json": file_record(root / "config.json", "profile_bound_search_config"),
        receipt_path.name: file_record(receipt_path, "local_public_retrieval_receipt"),
        "producer/fetch_okx_profile_data.py": file_record(
            current_copy, "profile_acquisition_and_validation"
        ),
        "producer/historical_fetch_okx_public_data.py": file_record(
            historical_copy, "historical_transport_dependency"
        ),
    }
    local_only: dict[str, object] = {}
    for path in sorted((root / "data" / "okx").rglob("*.feather")):
        relative = path.relative_to(root).as_posix()
        if relative.endswith(f"-{FUTURES_TIMEFRAME}-futures.feather"):
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
    acquisition_fields = bounded_research._profile_acquisition_contract_fields(
        contract
    )
    provenance = {
        "schema": "freqtrade-lab-retained-okx-data-v1",
        "portable_retained_fixture": False,
        "source": {
            "host": "www.okx.com",
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
            "development_timerange": contract["search_timerange"],
            "holdout_timerange": contract["development_timerange"],
            "timeframe": FUTURES_TIMEFRAME,
            "profile_acquisition": {key: contract[key] for key in acquisition_fields},
        },
        "files": files,
        "local_only_files": local_only,
    }
    path = root / "retained-data-provenance.json"
    path.write_bytes(canonical_bytes(provenance))
    return path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--window-spec", required=True, type=Path)
    parser.add_argument("--profile-database", required=True, type=Path)
    parser.add_argument("--profile-id", required=True)
    parser.add_argument("--pre-roll-candles", required=True, type=int)
    parser.add_argument(
        "--economic-gate",
        type=Path,
        help="pre-result PROFILE_DRIVEN_ECONOMIC_GATE_V1 JSON",
    )
    parser.add_argument("--single-baseline", type=Path,
                        help="pre-source SINGLE_BASELINE_V1 JSON")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    economic_gate_path = getattr(args, "economic_gate", None)
    economic_gate = (
        None
        if economic_gate_path is None
        else bounded_research.load_profile_economic_gate(economic_gate_path)
    )
    configure_profile_acquisition(
        args.profile_database,
        args.profile_id,
        args.window_spec,
        args.pre_roll_candles,
        economic_gate,
        (None if getattr(args, "single_baseline", None) is None else
         bounded_research.validate_single_baseline(
             _strict_json_object(args.single_baseline, "Single baseline"))),
    )
    runtime = validate_runtime()
    implementations = implementation_snapshot()
    requested = args.output_root.expanduser()
    parent = requested.parent.resolve(strict=True)
    if is_same_or_below_existing_directory(parent, REPOSITORY_ROOT):
        raise RuntimeError("output root must stay outside the repository")
    output = parent / requested.name
    if output.exists() or output.is_symlink():
        raise RuntimeError("output root already exists")
    os.mkdir(output, 0o700)
    try:
        receipt = acquire(output, runtime)
        provenance = write_profile_provenance(output, receipt, runtime, implementations)
    except BaseException as exc:
        if PROFILE_ACQUISITION is not None and "exploration" in PROFILE_ACQUISITION:
            (output / "acquisition-failure.json").write_bytes(canonical_bytes({
                "status": "BLOCKED_DATA", "error_type": type(exc).__name__,
                "message": str(exc)[:1000], "exploration": PROFILE_ACQUISITION["exploration"],
                "retry_allowed": False,
            }))
        else:
            shutil.rmtree(output)
        raise
    print(f"Retrieval receipt: {receipt}")
    print(f"Retrieval receipt SHA-256: {sha256(receipt.read_bytes())}")
    print(f"Provenance: {provenance}")
    print(f"Provenance SHA-256: {sha256(provenance.read_bytes())}")


if __name__ == "__main__":
    main()
