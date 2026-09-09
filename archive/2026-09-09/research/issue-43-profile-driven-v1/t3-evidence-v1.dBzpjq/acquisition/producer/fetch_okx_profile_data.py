#!/usr/bin/env python3
"""Fetch one Profile-bound, public OKX Search/Development source dataset."""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import shutil
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any


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
MAX_FUNDING_BATCH = 100


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
    if set(value) != {"schema", *WINDOW_FIELDS} or value.get("schema") != PROFILE_WINDOW_SCHEMA:
        raise RuntimeError("Profile source window shape/version is not supported")
    data_start, search_start, development_start, end_exclusive = (
        _utc_z(value[field], f"Profile source {field}") for field in WINDOW_FIELDS
    )
    if not data_start < search_start < development_start < end_exclusive:
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
) -> dict[str, Any]:
    data_start, search_start, development_start, end_exclusive = load_window_spec(
        window_spec
    )
    contract = bounded_research.profile_acquisition_contract(
        database,
        profile_id,
        f"{search_start:%Y%m%d}-{development_start:%Y%m%d}",
        f"{development_start:%Y%m%d}-{end_exclusive:%Y%m%d}",
        pre_roll_candles,
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
    if (
        PROFILE_ACQUISITION is None
        or None in (
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


def fetch_funding_history(exchange: Any, requests: list[dict[str, object]]) -> list[dict]:
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
        rows = exchange.fetch_funding_rate_history(
            SYMBOL,
            since=batch_start,
            limit=len(timestamps),
            params={"after": batch_end},
        )
        number = offset // MAX_FUNDING_BATCH + 1
        requests.append(
            request_receipt(
                exchange,
                "funding-history" if batches == 1 else f"funding-history-{number}",
            )
        )
        if not isinstance(rows, list) or len(rows) != len(timestamps):
            raise RuntimeError(f"funding history batch {number} is incomplete")
        output.extend(rows)
    return output


def validate_funding_history(funding: list[dict]) -> dict[str, object]:
    _configured()
    assert SEARCH_START is not None and DATA_END_MS is not None
    expected = list(
        range(int(SEARCH_START.timestamp() * 1000), DATA_END_MS, FUNDING_INTERVAL_MS)
    )
    timestamps = [item.get("timestamp") for item in funding]
    if timestamps != expected:
        raise RuntimeError("funding history must cover every fixed eight-hour timestamp")
    rates = [item.get("fundingRate") for item in funding]
    if any(isinstance(rate, bool) or not isinstance(rate, (int, float)) for rate in rates):
        raise RuntimeError("funding history contains an invalid funding rate")
    return {
        "rows": len(funding),
        "first_timestamp": timestamps[0],
        "last_timestamp": timestamps[-1],
    }


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
        tiers = exchange.fetch_market_leverage_tiers(
            SYMBOL, {"marginMode": "isolated"}
        )
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
        funding = fetch_funding_history(exchange, requests)
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
    handler.ohlcv_store(
        SYMBOL, "1h", funding_df, transport.CandleType.FUNDING_RATE
    )
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
    acquisition_fields = bounded_research.PROFILE_ACQUISITION_FIELDS
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
            "profile_acquisition": {
                key: contract[key] for key in acquisition_fields
            },
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
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    configure_profile_acquisition(
        args.profile_database,
        args.profile_id,
        args.window_spec,
        args.pre_roll_candles,
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
        provenance = write_profile_provenance(
            output, receipt, runtime, implementations
        )
    except BaseException:
        shutil.rmtree(output)
        raise
    print(f"Retrieval receipt: {receipt}")
    print(f"Retrieval receipt SHA-256: {sha256(receipt.read_bytes())}")
    print(f"Provenance: {provenance}")
    print(f"Provenance SHA-256: {sha256(provenance.read_bytes())}")


if __name__ == "__main__":
    main()
