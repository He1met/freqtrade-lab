import json
import stat
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from lab import search_campaign
from scripts import run_bounded_research_pilot as pilot
from scripts import run_freqtrade_backtest as offline_runner


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


def _source_acquisition(
    tmp_path: Path,
    *,
    missing_search_candle: bool = False,
    prefixed_python_dependency: bool = False,
) -> tuple[Path, str, str]:
    pa, feather = _arrow_modules()
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
            pa.table({"date": pa.array(dates, type=pa.timestamp("ms", tz="UTC"))}),
            path,
            compression="uncompressed",
        )
        local[f"data/okx/futures/{name}"] = _record(path, role)

    config = json.loads(
        (
            Path(__file__).parent
            / "fixtures"
            / "freqtrade_2026_7"
            / "producer"
            / "config.json"
        ).read_bytes()
    )
    _write_json(root / "config.json", config)
    _write_json(
        root / "market_snapshot.json",
        {"id": "XRP-USDT-SWAP", "symbol": "XRP/USDT:USDT"},
    )
    _write_json(root / "isolated_tiers_snapshot.json", {"tiers": []})
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
            },
        },
    )
    files = {
        "config.json": _record(root / "config.json", "sanitized_freqtrade_config"),
        "retrieval_receipt.json": _record(
            root / "retrieval_receipt.json", "local_public_retrieval_receipt"
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
            },
            "files": files,
            "local_only_files": local,
        },
    )
    return root, pilot.digest(provenance_bytes), pilot.digest(receipt_bytes)


def _produce(tmp_path: Path, **source_kwargs: object) -> tuple[Path, dict[str, object]]:
    source, provenance_sha, receipt_sha = _source_acquisition(
        tmp_path, **source_kwargs
    )
    output = tmp_path / "search-campaign"
    result = pilot.prepare_search_data(source, output, provenance_sha, receipt_sha)
    return output, result


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
        "-5m-futures.feather": pilot.FROZEN_SEARCH_STARTUP,
        "-1h-mark.feather": pilot.FROZEN_SEARCH_STARTUP,
        "-1h-funding_rate.feather": pilot.FROZEN_SEARCH_START,
    }
    _, feather = _arrow_modules()
    for path in (output / "acquisition" / "data" / "okx").rglob("*.feather"):
        dates = feather.read_table(path, columns=["date"]).column("date").to_pylist()
        assert dates[0].astimezone(timezone.utc) == next(
            start for suffix, start in starts.items() if path.name.endswith(suffix)
        )
        assert all(item < pilot.FROZEN_SEARCH_STOP for item in dates)
    plan = {
        "schema": pilot.SEARCH_SCHEMA,
        "search_timerange": pilot.FROZEN_SEARCH_TIMERANGE,
        "data_provenance_sha256": pilot.digest(provenance_path.read_bytes()),
    }
    assert pilot.verify_data(output, plan)["status"] == "DATA_READY"
    assert search_campaign._acquisition_snapshot(output) == {
        "search_timerange": pilot.FROZEN_SEARCH_TIMERANGE,
        "data_provenance_sha256": pilot.digest(provenance_path.read_bytes()),
        "pair": "XRP/USDT:USDT",
        "timeframe": "5m",
        "base_fee": 0.0005,
    }


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
        pilot.prepare_search_data(source, output, provenance_sha, receipt_sha)

    assert not output.exists()
    assert not list(tmp_path.glob(".search-data-*"))


def test_t0_producer_rejects_a_search_gap_without_partial_output(tmp_path: Path) -> None:
    source, provenance_sha, receipt_sha = _source_acquisition(
        tmp_path, missing_search_candle=True
    )
    output = tmp_path / "search-campaign"

    with pytest.raises(pilot.PilotError, match="not contiguous"):
        pilot.prepare_search_data(source, output, provenance_sha, receipt_sha)

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
        pilot.prepare_search_data(source, output, "0" * 64, "0" * 64)

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

    with pytest.raises(pilot.PilotError, match="db_url|single-file boundary"):
        pilot.prepare_search_data(
            source, output, pilot.digest(provenance_bytes), receipt_sha
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
        pilot.prepare_search_data(source, output, provenance_sha, receipt_sha)

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
    candidates = []
    for index, mechanism in enumerate(("ema", "rsi", "channel"), start=1):
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
            }
        )
    provenance = output / "acquisition" / "retained-data-provenance.json"
    _write_json(
        output / pilot.SEARCH_CAMPAIGN,
        {
            "schema": pilot.SEARCH_SCHEMA,
            "campaign_id": "producer-consumer-test",
            "freqtrade_version": "2026.7",
            "round": 1,
            "previous_round_receipt_sha256": None,
            "search_timerange": pilot.FROZEN_SEARCH_TIMERANGE,
            "data_provenance_sha256": pilot.digest(provenance.read_bytes()),
            "budget": {"maximum_attempts": 6},
            "ranking": list(pilot.SEARCH_RANKING),
            "finalist_gate": pilot.SEARCH_GATE_CONTRACT,
            "parent": None,
            "candidates": candidates,
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
            scenario="DEVELOPMENT",
            timerange=pilot.FROZEN_SEARCH_TIMERANGE,
            pair="XRP/USDT:USDT",
            data_dir=Path(isolation["data_dir"]),
            market_snapshot=first_input / "market_snapshot.json",
            leverage_tiers=first_input / "isolated_tiers_snapshot.json",
        )
        return [
            {
                "candidate_id": item["candidate_id"],
                "class_name": item["class_name"],
                "strategy_sha256": item["strategy_sha256"],
                "technical_status": "VALID",
                "failure_reason": None,
                "total_trades": 35,
                "profit_pct": 0.2,
                "max_drawdown_pct": 4.0,
                "profit_factor": 1.1,
            }
            for item in search_plan["candidates"]
        ]

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
