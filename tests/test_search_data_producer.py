import json
import stat
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from lab import search_campaign
from lab.database import get_connection
from lab import bounded_research as pilot
from scripts import run_freqtrade_backtest as offline_runner
from tests.test_development_run import _approved_candidate_database


PROFILE_SEARCH_TIMERANGE = "20260601-20260701"
PROFILE_DEVELOPMENT_TIMERANGE = "20260701-20260731"
PROFILE_TIMEFRAME = "5m"
PROFILE_PRE_ROLL_CANDLES = 24
PROFILE_SEARCH_STEPS, PROFILE_SEARCH_SUFFIXES = pilot._search_series_contract(
    PROFILE_TIMEFRAME
)
PROFILE_SEARCH_WINDOW = pilot._search_window_contract(
    PROFILE_SEARCH_TIMERANGE,
    timeframe=PROFILE_TIMEFRAME,
    pre_roll_candles=PROFILE_PRE_ROLL_CANDLES,
)
PROFILE_SEARCH_ROWS = PROFILE_SEARCH_WINDOW["rows"]
PROFILE_DEVELOPMENT_WINDOW = pilot._development_window_contract(
    PROFILE_DEVELOPMENT_TIMERANGE,
    timeframe=PROFILE_TIMEFRAME,
    pre_roll_candles=PROFILE_PRE_ROLL_CANDLES,
)


def _arrow_modules():
    return pytest.importorskip("pyarrow"), pytest.importorskip("pyarrow.feather")


def _write_json(path: Path, value: object) -> bytes:
    data = pilot.canonical(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return data


def _record(path: Path, role: str) -> dict[str, object]:
    data = path.read_bytes()
    return {"role": role, "bytes": len(data), "sha256": pilot.digest(data)}


def _timestamps(start: datetime, stop: datetime, step: timedelta) -> list[datetime]:
    return [start + index * step for index in range(int((stop - start) / step))]


def _ohlcv_table(pa, dates: list[datetime], *, missing_volume: bool = False):
    rows = len(dates)
    return pa.table(
        {
            "date": pa.array(dates, type=pa.timestamp("ms", tz="UTC")),
            "open": pa.array([100.0] * rows, type=pa.float64()),
            "high": pa.array([101.0] * rows, type=pa.float64()),
            "low": pa.array([99.0] * rows, type=pa.float64()),
            "close": pa.array([100.0] * rows, type=pa.float64()),
            "volume": pa.array(
                [None] * rows if missing_volume else [1.0] * rows,
                type=pa.float64(),
            ),
        }
    )


def _source_acquisition(
    tmp_path: Path,
    *,
    missing_search_candle: bool = False,
    prefixed_python_dependency: bool = False,
) -> tuple[Path, str, str]:
    pa, feather = _arrow_modules()
    profile_contract = pilot.profile_acquisition_contract(
        **_profile_prepare_kwargs(tmp_path)
    )
    root = tmp_path / "complete-source-acquisition"
    data_root = root / "data" / "okx" / "futures"
    data_root.mkdir(parents=True)
    source_start = datetime(2026, 5, 31, 22, tzinfo=timezone.utc)
    research_start = datetime(2026, 6, 1, tzinfo=timezone.utc)
    source_stop = datetime(2026, 7, 31, tzinfo=timezone.utc)
    series = {
        "XRP_USDT_USDT-5m-futures.feather": (
            _timestamps(source_start, source_stop, timedelta(minutes=5)),
            "merged_futures_ohlcv",
        ),
        "XRP_USDT_USDT-1h-mark.feather": (
            _timestamps(source_start, source_stop, timedelta(hours=1)),
            "merged_mark_ohlcv",
        ),
        "XRP_USDT_USDT-1h-funding_rate.feather": (
            _timestamps(research_start, source_stop, timedelta(hours=8)),
            "merged_funding_rate_series",
        ),
    }
    if missing_search_candle:
        series["XRP_USDT_USDT-5m-futures.feather"][0].pop(100)
    local: dict[str, object] = {}
    for name, (dates, role) in series.items():
        path = data_root / name
        feather.write_feather(
            _ohlcv_table(
                pa,
                dates,
                missing_volume=name.endswith("-1h-mark.feather"),
            ),
            path,
            compression="uncompressed",
        )
        local[f"data/okx/futures/{name}"] = _record(path, role)

    config = pilot.profile_search_config(profile_contract["profile_snapshot"])
    _write_json(root / "config.json", config)
    _write_json(
        root / "market_snapshot.json",
        {
            "id": "XRP-USDT-SWAP",
            "symbol": "XRP/USDT:USDT",
            "active": True,
            "contract": True,
            "swap": True,
            "linear": True,
            "inverse": False,
            "type": "swap",
        },
    )
    _write_json(
        root / "isolated_tiers_snapshot.json", [{"symbol": "XRP/USDT:USDT"}]
    )
    local["market_snapshot.json"] = _record(
        root / "market_snapshot.json", "market_snapshot"
    )
    local["isolated_tiers_snapshot.json"] = _record(
        root / "isolated_tiers_snapshot.json", "leverage_tiers"
    )
    receipt_bytes = _write_json(
        root / "retrieval_receipt.json",
        {
            "host": "www.okx.com",
            "authentication": "none",
            "pair": "XRP/USDT:USDT",
            "instrument_id": "XRP-USDT-SWAP",
            "data_window": {
                "start_utc": source_start.isoformat(),
                "end_exclusive_utc": source_stop.isoformat(),
                "fully_closed_at_fetch": True,
                "development_start_utc": research_start.isoformat(),
                "holdout_start_utc": datetime(
                    2026, 7, 1, tzinfo=timezone.utc
                ).isoformat(),
                "startup_candles_required": PROFILE_PRE_ROLL_CANDLES,
            },
        },
    )
    producer_root = root / "producer"
    producer_root.mkdir()
    profile_helper = Path(__file__).resolve().parent.parent / "scripts" / (
        "fetch_okx_profile_data.py"
    )
    historical_helper = Path(__file__).resolve().parent / "fixtures" / (
        "freqtrade_2026_7/producer/fetch_okx_public_data.py"
    )
    (producer_root / "fetch_okx_profile_data.py").write_bytes(
        profile_helper.read_bytes()
    )
    (producer_root / "historical_fetch_okx_public_data.py").write_bytes(
        historical_helper.read_bytes()
    )
    files = {
        "config.json": _record(root / "config.json", "profile_bound_search_config"),
        "retrieval_receipt.json": _record(
            root / "retrieval_receipt.json", "local_public_retrieval_receipt"
        ),
        "producer/fetch_okx_profile_data.py": _record(
            producer_root / "fetch_okx_profile_data.py",
            "profile_acquisition_and_validation",
        ),
        "producer/historical_fetch_okx_public_data.py": _record(
            producer_root / "historical_fetch_okx_public_data.py",
            "historical_transport_dependency",
        ),
    }
    dependencies = dict(offline_runner.SUPPORTED_DEPENDENCIES)
    if prefixed_python_dependency:
        dependencies["python"] = f"Python {dependencies['python']}"
    provenance_bytes = _write_json(
        root / "retained-data-provenance.json",
        {
            "schema": "freqtrade-lab-retained-okx-data-v1",
            "portable_retained_fixture": "BLOCKED_LICENSE",
            "source": {
                "host": "www.okx.com",
                "authentication": "none",
                "pair": "XRP/USDT:USDT",
                "instrument_id": "XRP-USDT-SWAP",
                "pair_family": "XRP-USDT",
                "retrieval_receipt": "retrieval_receipt.json",
            },
            "freqtrade": {
                "version": "2026.7",
                "tag": "2026.7",
                "commit": offline_runner.SUPPORTED_FREQTRADE_COMMIT,
                "dependencies": dependencies,
            },
            "contract": {
                "data_dir": "data/okx",
                "market_snapshot": "market_snapshot.json",
                "leverage_tiers": "isolated_tiers_snapshot.json",
                "config": "config.json",
                "development_timerange": "20260601-20260701",
                "holdout_timerange": "20260701-20260731",
                "timeframe": "5m",
                "profile_acquisition": {
                    key: profile_contract[key]
                    for key in pilot.PROFILE_ACQUISITION_FIELDS
                },
            },
            "files": files,
            "local_only_files": local,
        },
    )
    return root, pilot.digest(provenance_bytes), pilot.digest(receipt_bytes)


def _profile_search_database(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    profile_root = tmp_path / "profile"
    existing = list(profile_root.glob("approved-*.sqlite"))
    if existing:
        assert len(existing) == 1
        database = existing[0]
        candidate_id = _profile_candidate_id(database)
    else:
        database, candidate_id = _approved_candidate_database(
            profile_root, pair="XRP/USDT:USDT", timeframe=PROFILE_TIMEFRAME
        )
    with get_connection(database, read_only=True) as connection:
        connection.execute("BEGIN")
        profile = search_campaign.load_approved_candidate_snapshot(
            connection, candidate_id
        ).profile
    return database, dict(profile)


def _profile_prepare_kwargs(tmp_path: Path) -> dict[str, object]:
    database, profile = _profile_search_database(tmp_path)
    return {
        "database_path": database,
        "profile_id": str(profile["id"]),
        "search_timerange": PROFILE_SEARCH_TIMERANGE,
        "development_timerange": PROFILE_DEVELOPMENT_TIMERANGE,
        "pre_roll_candles": PROFILE_PRE_ROLL_CANDLES,
    }


def _profile_database_path(tmp_path: Path) -> Path:
    paths = list((tmp_path / "profile").glob("approved-*.sqlite"))
    assert len(paths) == 1
    return paths[0]


def _profile_candidate_id(database: Path) -> str:
    with get_connection(database, read_only=True) as connection:
        row = connection.execute("SELECT id FROM candidates").fetchone()
    assert row is not None
    return str(row[0])


def _produce(tmp_path: Path, **source_kwargs: object) -> tuple[Path, dict[str, object]]:
    source, provenance_sha, receipt_sha = _source_acquisition(
        tmp_path, **source_kwargs
    )
    output = tmp_path / "search-campaign"
    result = pilot.prepare_search_data(
        source,
        output,
        provenance_sha,
        receipt_sha,
        **_profile_prepare_kwargs(tmp_path),
    )
    return output, result


def _produce_development(
    tmp_path: Path, **source_kwargs: object
) -> tuple[Path, Path, dict[str, object]]:
    source, provenance_sha, receipt_sha = _source_acquisition(
        tmp_path, **source_kwargs
    )
    output = tmp_path / "development-pilot"
    result = pilot.prepare_development_data(
        source,
        output,
        provenance_sha,
        receipt_sha,
        **_profile_prepare_kwargs(tmp_path),
    )
    return source, output, result


def _search_plan(root: Path) -> dict[str, object]:
    provenance_path = root / pilot.ACQUISITION / "retained-data-provenance.json"
    provenance = json.loads(provenance_path.read_bytes())
    contract = provenance["contract"]
    return {
        "schema": pilot.SEARCH_SCHEMA,
        "search_timerange": contract["search_timerange"],
        "data_provenance_sha256": pilot.digest(provenance_path.read_bytes()),
        **{
            key: contract[key]
            for key in (
                "profile_snapshot",
                "profile_snapshot_sha256",
                "development_timerange",
                "pre_roll_candles",
                "capacity",
                "finalist_gate",
                "holdout",
                "holdout_stress",
            )
        },
    }


def _save_search_provenance(root: Path, provenance: dict[str, object]) -> dict[str, object]:
    _write_json(
        root / pilot.ACQUISITION / "retained-data-provenance.json", provenance
    )
    return _search_plan(root)


def _series_local_name(provenance: dict[str, object], series: str) -> str:
    _, suffixes = pilot._search_series_contract(provenance["contract"]["timeframe"])
    suffix = suffixes[series]
    return next(
        name
        for name in provenance["local_only_files"]
        if name.startswith("data/okx/") and name.endswith(suffix)
    )


def _resign_local_file(
    root: Path, provenance: dict[str, object], local_name: str
) -> None:
    path = root / pilot.ACQUISITION / local_name
    data = path.read_bytes()
    receipt = provenance["local_only_files"][local_name]
    receipt["bytes"] = len(data)
    receipt["sha256"] = pilot.digest(data)


def _rewrite_search_window(root: Path, timerange_value: str) -> dict[str, object]:
    pa, feather = _arrow_modules()
    provenance_path = root / pilot.ACQUISITION / "retained-data-provenance.json"
    provenance = json.loads(provenance_path.read_bytes())
    timeframe = provenance["contract"]["timeframe"]
    pre_roll = provenance["contract"]["pre_roll_candles"]
    window = pilot._search_window_contract(
        timerange_value,
        timeframe=timeframe,
        pre_roll_candles=pre_roll,
    )
    steps, _ = pilot._search_series_contract(timeframe)
    for series, step in steps.items():
        local_name = _series_local_name(provenance, series)
        path = root / pilot.ACQUISITION / local_name
        path.chmod(0o600)
        values = _timestamps(window["starts"][series], window["search_stop"], step)
        feather.write_feather(
            _ohlcv_table(pa, values, missing_volume=series == "mark_1h"),
            path,
            compression="uncompressed",
        )
        provenance["local_only_files"][local_name]["rows"] = window["rows"][series]
        _resign_local_file(root, provenance, local_name)
    provenance["contract"]["search_timerange"] = timerange_value
    provenance["contract"]["capacity"] = pilot.profile_search_capacity(
        provenance["contract"]["profile_snapshot"], timerange_value
    )
    provenance["search_retention"] = {
        "startup_start_utc": window["startup_start"].isoformat().replace("+00:00", "Z"),
        "search_start_utc": window["search_start"].isoformat().replace("+00:00", "Z"),
        "end_exclusive_utc": window["search_stop"].isoformat().replace("+00:00", "Z"),
        "later_rows_exposed_to_search": False,
        "rows": window["rows"],
    }
    return _save_search_provenance(root, provenance)


@pytest.mark.parametrize(
    "case",
    (
        "missing-source-acquisition",
        "extra-source-acquisition-field",
        "uppercase-source-sha",
        "missing-search-retention",
        "extra-search-retention-field",
        "later-rows-true",
        "wrong-retention-rows",
        "missing-source-series",
        "extra-source-series",
        "missing-local-series",
        "extra-local-series",
        "wrong-local-rows",
        "extra-actual-data-file",
    ),
)
def test_t0_search_consumer_rejects_inexact_v2_contract(
    tmp_path: Path, case: str
) -> None:
    root, _ = _produce(tmp_path)
    provenance_path = root / pilot.ACQUISITION / "retained-data-provenance.json"
    provenance = json.loads(provenance_path.read_bytes())
    if case == "missing-source-acquisition":
        provenance.pop("source_acquisition")
    elif case == "extra-source-acquisition-field":
        provenance["source_acquisition"]["extra"] = "x"
    elif case == "uppercase-source-sha":
        provenance["source_acquisition"]["provenance_sha256"] = "A" * 64
    elif case == "missing-search-retention":
        provenance.pop("search_retention")
    elif case == "extra-search-retention-field":
        provenance["search_retention"]["extra"] = "x"
    elif case == "later-rows-true":
        provenance["search_retention"]["later_rows_exposed_to_search"] = True
    elif case == "wrong-retention-rows":
        provenance["search_retention"]["rows"]["futures_5m"] += 1
    elif case == "missing-source-series":
        provenance["source_acquisition"]["data_sha256"].pop(
            next(iter(provenance["source_acquisition"]["data_sha256"]))
        )
    elif case == "extra-source-series":
        provenance["source_acquisition"]["data_sha256"]["futures/extra.feather"] = "c" * 64
    elif case == "missing-local-series":
        provenance["local_only_files"].pop(
            _series_local_name(provenance, "futures_5m")
        )
    elif case == "extra-local-series":
        provenance["local_only_files"]["data/okx/futures/extra.feather"] = {
            "bytes": 1,
            "sha256": "c" * 64,
            "rows": 1,
        }
    elif case == "wrong-local-rows":
        provenance["local_only_files"][
            _series_local_name(provenance, "futures_5m")
        ]["rows"] += 1
    elif case == "extra-actual-data-file":
        extra = root / pilot.ACQUISITION / "data" / "okx" / "futures" / "extra.feather"
        extra.write_bytes(b"extra")
    plan = _save_search_provenance(root, provenance)

    with pytest.raises(pilot.PilotError):
        pilot.verify_data(root, plan)


@pytest.mark.parametrize(
    "case", ("credential", "db-url", "external-channel", "pair", "market")
)
def test_t0_search_consumer_reuses_safe_config_and_identity_validation(
    tmp_path: Path, case: str
) -> None:
    root, _ = _produce(tmp_path)
    acquisition = root / pilot.ACQUISITION
    provenance_path = acquisition / "retained-data-provenance.json"
    provenance = json.loads(provenance_path.read_bytes())
    if case == "market":
        path = acquisition / "market_snapshot.json"
        market = json.loads(path.read_bytes())
        market["symbol"] = "BTC/USDT:USDT"
        _write_json(path, market)
        _resign_local_file(root, provenance, "market_snapshot.json")
    else:
        path = acquisition / "config.json"
        config = json.loads(path.read_bytes())
        if case == "credential":
            config["exchange"]["key"] = "secret"
        elif case == "db-url":
            config["db_url"] = "sqlite:///private.sqlite"
        elif case == "external-channel":
            config["telegram"] = {"enabled": True}
        elif case == "pair":
            config["exchange"]["pair_whitelist"] = ["BTC/USDT:USDT"]
        _write_json(path, config)
        data = path.read_bytes()
        provenance["files"]["config.json"] = {
            "bytes": len(data),
            "sha256": pilot.digest(data),
        }
    plan = _save_search_provenance(root, provenance)

    with pytest.raises(pilot.PilotError):
        pilot.verify_data(root, plan)


def test_t0_search_consumer_rejects_self_signed_non_feather(tmp_path: Path) -> None:
    root, _ = _produce(tmp_path)
    provenance_path = root / pilot.ACQUISITION / "retained-data-provenance.json"
    provenance = json.loads(provenance_path.read_bytes())
    local_name = _series_local_name(provenance, "futures_5m")
    path = root / pilot.ACQUISITION / local_name
    path.chmod(0o600)
    path.write_bytes(b"not a feather file")
    _resign_local_file(root, provenance, local_name)
    plan = _save_search_provenance(root, provenance)

    with pytest.raises(pilot.PilotError, match="readable Feather"):
        pilot.verify_data(root, plan)


def test_t0_search_consumer_requires_exact_pyarrow_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pyarrow, _ = _arrow_modules()
    root, _ = _produce(tmp_path)
    monkeypatch.setattr(pyarrow, "__version__", "25.0.1")

    with pytest.raises(pilot.PilotError, match="exact PyArrow 25.0.0"):
        pilot.verify_data(root, _search_plan(root))
    capability = search_campaign.freeze_search_capability(
        _profile_database_path(tmp_path), root, None, None
    )
    try:
        assert capability.status == "BLOCKED_DATA"
    finally:
        capability.close()


@pytest.mark.parametrize(
    "case", ("gap", "duplicate", "wrong-start", "early-end", "post-stop", "null", "non-utc")
)
def test_t1_exact_pyarrow_rejects_invalid_search_timestamps(
    tmp_path: Path, case: str
) -> None:
    pa, feather = _arrow_modules()
    root, _ = _produce(tmp_path)
    provenance_path = root / pilot.ACQUISITION / "retained-data-provenance.json"
    provenance = json.loads(provenance_path.read_bytes())
    local_name = _series_local_name(provenance, "futures_5m")
    path = root / pilot.ACQUISITION / local_name
    table = feather.read_table(path)
    values = table.column("date").to_pylist()
    step = PROFILE_SEARCH_STEPS["futures_5m"]
    if case == "gap":
        values[100] = values[99] + 2 * step
    elif case == "duplicate":
        values[100] = values[99]
    elif case == "wrong-start":
        values[0] += step
    elif case == "early-end":
        values[-1] -= step
    elif case == "post-stop":
        values[-1] = PROFILE_SEARCH_WINDOW["search_stop"] + step
    elif case == "null":
        values[100] = None
    elif case == "non-utc":
        values = [item.replace(tzinfo=None) for item in values]
    timestamp_type = pa.timestamp("ms") if case == "non-utc" else pa.timestamp("ms", tz="UTC")
    path.chmod(0o600)
    feather.write_feather(
        table.set_column(0, "date", pa.array(values, type=timestamp_type)),
        path,
        compression="uncompressed",
    )
    _resign_local_file(root, provenance, local_name)
    plan = _save_search_provenance(root, provenance)

    with pytest.raises(pilot.PilotError):
        pilot.verify_data(root, plan)


@pytest.mark.parametrize(
    "case",
    (
        "missing-volume",
        "extra-column",
        "null-close",
        "infinite-open",
        "integer-volume",
        "infinite-mark-volume",
        "null-futures-volume",
        "null-funding-volume",
    ),
)
def test_t1_exact_pyarrow_rejects_invalid_search_ohlcv_schema_or_values(
    tmp_path: Path, case: str
) -> None:
    pa, feather = _arrow_modules()
    root, _ = _produce(tmp_path)
    provenance_path = root / pilot.ACQUISITION / "retained-data-provenance.json"
    provenance = json.loads(provenance_path.read_bytes())
    if case == "infinite-mark-volume":
        series = "mark_1h"
    elif case == "null-funding-volume":
        series = "funding_history"
    else:
        series = "futures_5m"
    local_name = _series_local_name(provenance, series)
    path = root / pilot.ACQUISITION / local_name
    table = feather.read_table(path)
    if case == "missing-volume":
        table = table.remove_column(table.schema.get_field_index("volume"))
    elif case == "extra-column":
        table = table.append_column("forged", pa.array([1.0] * table.num_rows))
    elif case == "null-close":
        values = table.column("close").to_pylist()
        values[100] = None
        index = table.schema.get_field_index("close")
        table = table.set_column(index, "close", pa.array(values, type=pa.float64()))
    elif case == "infinite-open":
        values = table.column("open").to_pylist()
        values[100] = float("inf")
        index = table.schema.get_field_index("open")
        table = table.set_column(index, "open", pa.array(values, type=pa.float64()))
    elif case == "integer-volume":
        index = table.schema.get_field_index("volume")
        table = table.set_column(
            index, "volume", pa.array([1] * table.num_rows, type=pa.int64())
        )
    elif case == "infinite-mark-volume":
        values = table.column("volume").to_pylist()
        values[100] = float("inf")
        index = table.schema.get_field_index("volume")
        table = table.set_column(index, "volume", pa.array(values, type=pa.float64()))
    elif case in {"null-futures-volume", "null-funding-volume"}:
        values = table.column("volume").to_pylist()
        values[10] = None
        index = table.schema.get_field_index("volume")
        table = table.set_column(index, "volume", pa.array(values, type=pa.float64()))
    path.chmod(0o600)
    feather.write_feather(table, path, compression="uncompressed")
    _resign_local_file(root, provenance, local_name)
    plan = _save_search_provenance(root, provenance)

    with pytest.raises(pilot.PilotError):
        pilot.verify_data(root, plan)


def test_t1_exact_pyarrow_accepts_dynamic_non_june_30_day_window(
    tmp_path: Path,
) -> None:
    root, _ = _produce(tmp_path)
    plan = _rewrite_search_window(root, "20260501-20260531")

    verified = pilot.verify_data(root, plan)
    snapshot = search_campaign._acquisition_snapshot(
        root, _profile_database_path(tmp_path)
    )

    assert verified["status"] == "DATA_READY"
    assert verified["search_timerange"] == "20260501-20260531"
    assert verified["rows"] == PROFILE_SEARCH_ROWS
    assert snapshot["search_timerange"] == "20260501-20260531"


def test_t2_full_length_date_only_feathers_block_before_any_mutation(
    tmp_path: Path,
) -> None:
    pa, feather = _arrow_modules()
    root, _ = _produce(tmp_path)
    provenance_path = root / pilot.ACQUISITION / "retained-data-provenance.json"
    provenance = json.loads(provenance_path.read_bytes())
    for series in PROFILE_SEARCH_STEPS:
        local_name = _series_local_name(provenance, series)
        path = root / pilot.ACQUISITION / local_name
        dates = feather.read_table(path, columns=["date"]).column("date")
        path.chmod(0o600)
        feather.write_feather(
            pa.table({"date": dates}), path, compression="uncompressed"
        )
        _resign_local_file(root, provenance, local_name)
    _save_search_provenance(root, provenance)
    with pytest.raises(pilot.PilotError, match="exact Freqtrade OHLCV schema"):
        pilot.verify_data(root, _search_plan(root))
    database = _profile_database_path(tmp_path)
    candidate_id = _profile_candidate_id(database)
    before = search_campaign.business_table_digest(database)

    capability = search_campaign.freeze_search_capability(
        database, root, None, None
    )
    try:
        assert capability.status == "BLOCKED_DATA"
        assert capability.reason == "Profile Search data contract could not be verified"
        with pytest.raises(search_campaign.SearchCampaignError) as raised:
            search_campaign.prepare_round_one(
                database,
                capability,
                [candidate_id],
                profile_id=str(_search_plan(root)["profile_snapshot"]["id"]),
            )
        assert raised.value.code == "BLOCKED_DATA"
        assert search_campaign.business_table_digest(database) == before
        assert not (root / pilot.SEARCH_CAMPAIGN).exists()
        assert not (root / pilot.SEARCH_TRIALS).exists()
        assert not (root / search_campaign.STRATEGIES).exists()
    finally:
        capability.close()


def test_t2_three_one_row_feathers_block_before_campaign_or_database_mutation(
    tmp_path: Path,
) -> None:
    pa, feather = _arrow_modules()
    root, _ = _produce(tmp_path)
    provenance_path = root / pilot.ACQUISITION / "retained-data-provenance.json"
    provenance = json.loads(provenance_path.read_bytes())
    window = PROFILE_SEARCH_WINDOW
    for series in PROFILE_SEARCH_STEPS:
        local_name = _series_local_name(provenance, series)
        path = root / pilot.ACQUISITION / local_name
        path.chmod(0o600)
        feather.write_feather(
            _ohlcv_table(
                pa,
                [window["starts"][series]],
                missing_volume=series == "mark_1h",
            ),
            path,
            compression="uncompressed",
        )
        _resign_local_file(root, provenance, local_name)
    _save_search_provenance(root, provenance)
    with pytest.raises(pilot.PilotError, match="output is not contiguous"):
        pilot.verify_data(root, _search_plan(root))
    database = _profile_database_path(tmp_path)
    candidate_id = _profile_candidate_id(database)
    before = search_campaign.business_table_digest(database)

    capability = search_campaign.freeze_search_capability(
        database, root, None, None
    )
    try:
        assert capability.status == "BLOCKED_DATA"
        assert capability.reason == "Profile Search data contract could not be verified"
        with pytest.raises(search_campaign.SearchCampaignError) as raised:
            search_campaign.prepare_round_one(
                database,
                capability,
                [candidate_id],
                profile_id=str(_search_plan(root)["profile_snapshot"]["id"]),
            )
        assert raised.value.code == "BLOCKED_DATA"
        assert search_campaign.business_table_digest(database) == before
        assert not (root / pilot.SEARCH_CAMPAIGN).exists()
        assert not (root / pilot.SEARCH_TRIALS).exists()
        assert not (root / search_campaign.STRATEGIES).exists()
    finally:
        capability.close()


def test_t1_producer_publishes_only_exact_search_values_and_real_check_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("init_database", "run_research_candidate"):
        monkeypatch.setattr(
            pilot,
            name,
            lambda *args, **kwargs: (_ for _ in ()).throw(
                AssertionError("Search producer must have no database/research side effect")
            ),
        )
    output, result = _produce(tmp_path)

    assert result["status"] == "SEARCH_DATA_READY"
    assert stat.S_IMODE(output.stat().st_mode) == 0o700
    assert {path.name for path in output.iterdir()} == {"acquisition"}
    assert not list(output.rglob("*.sqlite*"))
    provenance_path = output / "acquisition" / "retained-data-provenance.json"
    provenance = json.loads(provenance_path.read_bytes())
    assert "retrieval_receipt" not in provenance["source"]
    assert provenance["search_retention"]["later_rows_exposed_to_search"] is False
    assert set(provenance["source_acquisition"]) == {
        "provenance_sha256",
        "retrieval_receipt_sha256",
        "data_sha256",
    }
    starts = {
        "-5m-futures.feather": PROFILE_SEARCH_WINDOW["startup_start"],
        "-1h-mark.feather": PROFILE_SEARCH_WINDOW["starts"]["mark_1h"],
        "-1h-funding_rate.feather": PROFILE_SEARCH_WINDOW["search_start"],
    }
    _, feather = _arrow_modules()
    for path in (output / "acquisition" / "data" / "okx").rglob("*.feather"):
        table = feather.read_table(path)
        dates = table.column("date").to_pylist()
        assert dates[0].astimezone(timezone.utc) == next(
            start for suffix, start in starts.items() if path.name.endswith(suffix)
        )
        assert all(item < PROFILE_SEARCH_WINDOW["search_stop"] for item in dates)
        if path.name.endswith("-1h-mark.feather"):
            assert table.column("volume").null_count == table.num_rows
    plan = _search_plan(output)
    assert pilot.verify_data(output, plan)["status"] == "DATA_READY"
    assert search_campaign._acquisition_snapshot(
        output, _profile_database_path(tmp_path)
    ) == {
        "search_timerange": PROFILE_SEARCH_TIMERANGE,
        "data_provenance_sha256": pilot.digest(provenance_path.read_bytes()),
        "source_acquisition_sha256": pilot.digest(
            pilot.canonical(provenance["source_acquisition"])
        ),
        "pair": "XRP/USDT:USDT",
        "timeframe": "5m",
        "base_fee": 0.0005,
        "profile_snapshot": provenance["contract"]["profile_snapshot"],
        "profile_snapshot_sha256": provenance["contract"][
            "profile_snapshot_sha256"
        ],
        "development_timerange": PROFILE_DEVELOPMENT_TIMERANGE,
        "pre_roll_candles": PROFILE_PRE_ROLL_CANDLES,
    }


def test_t1_development_producer_publishes_one_isolated_profile_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    for name in ("init_database", "run_research_candidate"):
        monkeypatch.setattr(
            pilot,
            name,
            lambda *args, **kwargs: (_ for _ in ()).throw(
                AssertionError(
                    "Development materializer must not create a ResearchRun"
                )
            ),
        )
    source, output, result = _produce_development(tmp_path)

    assert result["status"] == "DEVELOPMENT_DATA_READY"
    assert stat.S_IMODE(output.stat().st_mode) == 0o700
    assert {path.name for path in output.iterdir()} == {
        pilot.PLAN,
        pilot.WINDOW,
        pilot.ACQUISITION,
        pilot.DEVELOPMENT_ISOLATION,
    }
    assert not list(output.rglob("*.sqlite*"))
    assert not (output / "candidates").exists()
    assert not (output / "workspace").exists()
    assert not (output / "holdout-isolation").exists()

    plan = json.loads((output / pilot.PLAN).read_bytes())
    acquisition = output / pilot.ACQUISITION
    acquisition_provenance = json.loads(
        (acquisition / "retained-data-provenance.json").read_bytes()
    )
    isolation = output / pilot.DEVELOPMENT_ISOLATION
    development_provenance = json.loads(
        (isolation / "retained-data-provenance.json").read_bytes()
    )
    assert plan["schema"] == pilot.PROFILE_DEVELOPMENT_SCHEMA
    assert plan["candidates"] == []
    assert {path.name for path in acquisition.iterdir()} == {
        "config.json",
        "market_snapshot.json",
        "isolated_tiers_snapshot.json",
        "retained-data-provenance.json",
    }
    assert not (acquisition / "data").exists()

    source_provenance = json.loads(
        (source / "retained-data-provenance.json").read_bytes()
    )
    expected_source_acquisition = {
        "provenance_sha256": pilot.digest(
            (source / "retained-data-provenance.json").read_bytes()
        ),
        "retrieval_receipt_sha256": pilot.digest(
            (source / "retrieval_receipt.json").read_bytes()
        ),
        "data_sha256": {
            name.removeprefix("data/okx/"): receipt["sha256"]
            for name, receipt in source_provenance["local_only_files"].items()
            if name.startswith("data/okx/")
        },
    }
    assert plan["source_acquisition"] == expected_source_acquisition
    assert (
        acquisition_provenance["source_acquisition"]
        == expected_source_acquisition
        == development_provenance["source_acquisition"]
    )
    assert development_provenance["development_isolation"][
        "holdout_values_present"
    ] is False

    starts = {
        "-5m-futures.feather": PROFILE_DEVELOPMENT_WINDOW["startup_start"],
        "-1h-mark.feather": PROFILE_DEVELOPMENT_WINDOW["starts"]["mark_1h"],
        "-1h-funding_rate.feather": PROFILE_DEVELOPMENT_WINDOW[
            "development_start"
        ],
    }
    _, feather = _arrow_modules()
    for path in (isolation / "data" / "okx").rglob("*.feather"):
        dates = feather.read_table(path, columns=["date"]).column("date").to_pylist()
        assert dates[0].astimezone(timezone.utc) == next(
            start for suffix, start in starts.items() if path.name.endswith(suffix)
        )
        assert all(
            item < PROFILE_DEVELOPMENT_WINDOW["development_stop"]
            for item in dates
        )

    verified = offline_runner._verify_data_provenance(
        development_provenance,
        scenario="DEVELOPMENT",
        timerange=PROFILE_DEVELOPMENT_TIMERANGE,
        pair="XRP/USDT:USDT",
        data_dir=isolation / "data" / "okx",
        market_snapshot=acquisition / "market_snapshot.json",
        leverage_tiers=acquisition / "isolated_tiers_snapshot.json",
        timeframe=PROFILE_TIMEFRAME,
    )
    assert set(verified["data_sha256"]) == set(
        expected_source_acquisition["data_sha256"]
    )
    assert pilot.check_development_data(output) == result
    assert (
        pilot.main(
            ["check-development-data", "--pilot-root", str(output)]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["status"] == "DEVELOPMENT_DATA_READY"


def test_t0_development_check_rejects_extra_candidate_file(tmp_path: Path) -> None:
    _, output, _ = _produce_development(tmp_path)
    marker = output / "candidate.py"
    marker.write_text("user-owned", encoding="utf-8")

    with pytest.raises(pilot.PilotError, match="file set is not exact"):
        pilot.check_development_data(output)

    assert marker.read_text(encoding="utf-8") == "user-owned"


def test_t0_development_publish_failure_leaves_no_partial_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, provenance_sha, receipt_sha = _source_acquisition(tmp_path)
    output = tmp_path / "development-pilot"

    def fail_publish(*args: object, **kwargs: object) -> None:
        raise pilot.ResearchCandidateError("injected publication failure")

    monkeypatch.setattr(pilot, "_publish_directory_exclusive", fail_publish)
    with pytest.raises(pilot.PilotError, match="injected publication failure"):
        pilot.prepare_development_data(
            source,
            output,
            provenance_sha,
            receipt_sha,
            **_profile_prepare_kwargs(tmp_path),
        )

    assert not output.exists()
    assert not list(tmp_path.glob(".development-data-*"))


def test_t1_legacy_python_dependency_is_published_canonically(tmp_path: Path) -> None:
    output, _ = _produce(tmp_path, prefixed_python_dependency=True)

    provenance = json.loads(
        (output / "acquisition" / "retained-data-provenance.json").read_bytes()
    )
    assert provenance["freqtrade"]["dependencies"] == pilot.RUNNER_DEPENDENCIES


@pytest.mark.parametrize("bad_binding", ("provenance", "receipt"))
def test_t0_producer_rejects_untrusted_source_without_partial_output(
    tmp_path: Path, bad_binding: str
) -> None:
    if bad_binding == "provenance":
        source = tmp_path / "complete-source-acquisition"
        source.mkdir()
        _write_json(source / "retained-data-provenance.json", {})
        provenance_sha = "0" * 64
        receipt_sha = "0" * 64
    else:
        source, provenance_sha, receipt_sha = _source_acquisition(tmp_path)
        receipt_sha = "0" * 64
    output = tmp_path / "search-campaign"

    with pytest.raises(pilot.PilotError, match="trusted SHA|tracked receipt"):
        pilot.prepare_search_data(
            source,
            output,
            provenance_sha,
            receipt_sha,
            **_profile_prepare_kwargs(tmp_path),
        )

    assert not output.exists()
    assert not list(tmp_path.glob(".search-data-*"))


@pytest.mark.parametrize(
    "case",
    (
        "development-window",
        "pre-roll",
        "profile-gate",
        "receipt-development",
        "receipt-holdout",
        "receipt-startup",
    ),
)
def test_t0_producer_rejects_profile_contract_drift_without_partial_output(
    tmp_path: Path, case: str
) -> None:
    source, provenance_sha, receipt_sha = _source_acquisition(tmp_path)
    kwargs = _profile_prepare_kwargs(tmp_path)
    if case == "development-window":
        kwargs["development_timerange"] = "20260701-20260801"
    elif case == "pre-roll":
        kwargs["pre_roll_candles"] = PROFILE_PRE_ROLL_CANDLES - 1
    else:
        if case == "profile-gate":
            with get_connection(kwargs["database_path"]) as connection:
                connection.execute(
                    "UPDATE research_profiles SET max_drawdown_pct = 4.0 WHERE id = ?",
                    (kwargs["profile_id"],),
                )
                connection.commit()
        else:
            receipt_path = source / "retrieval_receipt.json"
            receipt = json.loads(receipt_path.read_bytes())
            field, value = {
                "receipt-development": (
                    "development_start_utc",
                    "2026-06-02T00:00:00+00:00",
                ),
                "receipt-holdout": (
                    "holdout_start_utc",
                    "2026-07-02T00:00:00+00:00",
                ),
                "receipt-startup": (
                    "startup_candles_required",
                    PROFILE_PRE_ROLL_CANDLES - 1,
                ),
            }[case]
            receipt["data_window"][field] = value
            receipt_bytes = _write_json(receipt_path, receipt)
            provenance_path = source / "retained-data-provenance.json"
            provenance = json.loads(provenance_path.read_bytes())
            provenance["files"]["retrieval_receipt.json"] = _record(
                receipt_path, "local_public_retrieval_receipt"
            )
            provenance_bytes = _write_json(provenance_path, provenance)
            receipt_sha = pilot.digest(receipt_bytes)
            provenance_sha = pilot.digest(provenance_bytes)
    output = tmp_path / "search-campaign"

    with pytest.raises(pilot.PilotError):
        pilot.prepare_search_data(
            source,
            output,
            provenance_sha,
            receipt_sha,
            **kwargs,
        )

    assert not output.exists()
    assert not list(tmp_path.glob(".search-data-*"))


def test_t0_producer_rejects_a_search_gap_without_partial_output(tmp_path: Path) -> None:
    source, provenance_sha, receipt_sha = _source_acquisition(
        tmp_path, missing_search_candle=True
    )
    output = tmp_path / "search-campaign"

    with pytest.raises(pilot.PilotError, match="not contiguous"):
        pilot.prepare_search_data(
            source,
            output,
            provenance_sha,
            receipt_sha,
            **_profile_prepare_kwargs(tmp_path),
        )

    assert not output.exists()
    assert not list(tmp_path.glob(".search-data-*"))


def test_t0_producer_never_overwrites_an_existing_root(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    output = tmp_path / "search-campaign"
    output.mkdir()
    marker = output / "user-owned.txt"
    marker.write_text("preserve", encoding="utf-8")

    with pytest.raises(pilot.PilotError, match="already exists"):
        pilot.prepare_search_data(
            source,
            output,
            "0" * 64,
            "0" * 64,
            **_profile_prepare_kwargs(tmp_path),
        )

    assert marker.read_text(encoding="utf-8") == "preserve"


def test_t0_producer_rejects_sensitive_config(tmp_path: Path) -> None:
    source, _, receipt_sha = _source_acquisition(tmp_path)
    config_path = source / "config.json"
    config = json.loads(config_path.read_bytes())
    config["db_url"] = "sqlite:///private.sqlite"
    config_bytes = _write_json(config_path, config)
    provenance_path = source / "retained-data-provenance.json"
    provenance = json.loads(provenance_path.read_bytes())
    provenance["files"]["config.json"].update(
        {"bytes": len(config_bytes), "sha256": pilot.digest(config_bytes)}
    )
    provenance_bytes = _write_json(provenance_path, provenance)
    output = tmp_path / "search-campaign"

    with pytest.raises(pilot.PilotError, match="frozen Search Profile"):
        pilot.prepare_search_data(
            source,
            output,
            pilot.digest(provenance_bytes),
            receipt_sha,
            **_profile_prepare_kwargs(tmp_path),
        )

    assert not output.exists()


def test_t0_control_drift_after_validation_fails_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, provenance_sha, receipt_sha = _source_acquisition(tmp_path)
    original = pilot._verify_data_provenance

    def mutate_after_validation(*args: object, **kwargs: object) -> dict[str, object]:
        result = original(*args, **kwargs)
        _write_json(
            source / "market_snapshot.json",
            {"id": "DRIFT-USDT-SWAP", "symbol": "DRIFT/USDT:USDT"},
        )
        return result

    monkeypatch.setattr(pilot, "_verify_data_provenance", mutate_after_validation)
    output = tmp_path / "search-campaign"

    with pytest.raises(pilot.PilotError, match="changed after provenance validation"):
        pilot.prepare_search_data(
            source,
            output,
            provenance_sha,
            receipt_sha,
            **_profile_prepare_kwargs(tmp_path),
        )

    assert not output.exists()
    assert not list(tmp_path.glob(".search-data-*"))


def _candidate_source(class_name: str) -> bytes:
    return (
        "import talib.abstract as ta\n"
        "from pandas import DataFrame\n"
        "from technical import qtpylib\n\n"
        "from freqtrade.strategy import IStrategy\n\n\n"
        f"class {class_name}(IStrategy):\n"
        "    INTERFACE_VERSION = 3\n"
        '    timeframe = "5m"\n'
        "    can_short = True\n"
        "    startup_candle_count = 20\n"
        "    process_only_new_candles = True\n"
        '    minimal_roi = {"0": 0.0}\n'
        "    stoploss = -0.02\n\n"
        "    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:\n"
        "        return dataframe\n\n"
        "    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:\n"
        "        return dataframe\n\n"
        "    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:\n"
        "        return dataframe\n"
    ).encode()


def test_t2_generated_root_runs_real_search_preflight_and_isolation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output, _ = _produce(tmp_path)
    profile_contract = _search_plan(output)
    profile_id = profile_contract["profile_snapshot"]["id"]
    candidates = []
    analyses = {}
    for index, mechanism in enumerate(("ema", "rsi"), start=1):
        class_name = f"SearchSeed{index}"
        data = _candidate_source(class_name)
        path = output / "candidates" / f"{class_name}.py"
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(data)
        candidates.append(
            {
                "candidate_id": f"seed-{index}",
                "class_name": class_name,
                "mechanism": mechanism,
                "relationship": "MECHANISM_SEED",
                "changed_factor": None,
                "parent_strategy_sha256": None,
                "strategy_file": f"candidates/{class_name}.py",
                "strategy_sha256": pilot.digest(data),
                "generation_run_id": f"generation-{index}",
                "profile_id": profile_id,
            }
        )
        analysis = pilot.analyze_bounded_causal_strategy_file(
            path, class_name, expected_timeframe=PROFILE_TIMEFRAME
        )
        analyses[f"seed-{index}"] = {
            "timeframe": analysis.timeframe,
            "startup_candle_count": analysis.startup_candle_count,
            "maximum_lookback": analysis.max_lookback,
        }
    provenance = output / "acquisition" / "retained-data-provenance.json"
    _write_json(
        output / pilot.SEARCH_CAMPAIGN,
        {
            **profile_contract,
            "schema": pilot.SEARCH_SCHEMA,
            "campaign_id": "producer-consumer-test",
            "freqtrade_version": "2026.7",
            "round": 1,
            "previous_round_receipt_sha256": None,
            "data_provenance_sha256": pilot.digest(provenance.read_bytes()),
            "budget": {"maximum_attempts": 6},
            "ranking": list(pilot.SEARCH_RANKING),
            "active_attempt_limit": pilot.PROFILE_ACTIVE_ATTEMPTS,
            "parent": None,
            "candidates": candidates,
            "strategy_analyses": analyses,
        },
    )
    plan = pilot.load_plan(output, pilot.SEARCH_CAMPAIGN)

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("Search must not open database or ResearchRun paths")

    for name in ("init_database", "run_research_candidate", "materialize_selected_input"):
        monkeypatch.setattr(pilot, name, forbidden)

    def outer_freqtrade_fake(
        root: Path,
        search_plan: dict[str, object],
        inputs: dict[str, Path],
        python: Path,
        source: Path,
        isolation: dict[str, object],
    ) -> list[dict[str, object]]:
        isolated_provenance = json.loads(Path(isolation["provenance"]).read_bytes())
        first_input = next(iter(inputs.values()))
        offline_runner._verify_dependency_versions(
            isolated_provenance, offline_runner.SUPPORTED_DEPENDENCIES
        )
        offline_runner._verify_data_provenance(
            isolated_provenance,
            scenario="SEARCH",
            timerange=PROFILE_SEARCH_TIMERANGE,
            pair="XRP/USDT:USDT",
            data_dir=Path(isolation["data_dir"]),
            market_snapshot=first_input / "market_snapshot.json",
            leverage_tiers=first_input / "isolated_tiers_snapshot.json",
        )
        results = []
        for item in search_plan["candidates"]:
            result = {
                "candidate_id": item["candidate_id"],
                "class_name": item["class_name"],
                "strategy_sha256": item["strategy_sha256"],
                "technical_status": "VALID",
                "failure_reason": None,
                "total_trades": 35,
                "profit_pct": 0.2,
                "gross_profit_before_fees_pct": 0.3,
                "configured_fee_cost_pct": 0.1,
                "max_drawdown_pct": 4.0,
                "profit_factor": 1.1,
                "average_holding_period_minutes": 45.0,
                "direction_concentration": 0.6,
                "market_state_concentration": 0.5,
                "market_state_definition": pilot.MARKET_STATE_DEFINITION,
                "market_state_lookback_candles": search_plan["pre_roll_candles"],
            }
            result_root = (
                root
                / f"search-results-round-{search_plan['round']}"
                / str(item["candidate_id"])
            )
            raw_root = result_root / "raw"
            raw_root.mkdir(parents=True)
            archive_name = "backtest-result.zip"
            archive_bytes = pilot.canonical(
                {"candidate_id": item["candidate_id"], "kind": "test archive"}
            )
            (raw_root / archive_name).write_bytes(archive_bytes)
            result.update(
                archive=archive_name,
                archive_sha256=pilot.digest(archive_bytes),
                report_semantic_sha256=pilot.digest(
                    pilot.canonical({"candidate_id": item["candidate_id"]})
                ),
            )
            (result_root / "result.json").write_bytes(pilot.canonical(result))
            results.append(result)
        return results

    monkeypatch.setattr(pilot, "screen", outer_freqtrade_fake)
    source = tmp_path / "freqtrade-source"
    source.mkdir()

    outcome = pilot.screen_search(
        output, plan, Path(sys.executable), source
    )

    assert outcome["status"] == "SEARCH_ROUND_READY_FOR_CHILDREN"
    assert not (output / "search-isolation-round-1").exists()
    assert not (output / "search-inputs-round-1").exists()
    assert not list(output.rglob("*.sqlite*"))
