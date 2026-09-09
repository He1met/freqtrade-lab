import importlib.util
import json
import shutil
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from lab import development_run, search_campaign
from scripts import run_freqtrade_backtest as offline_runner


ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "run_bounded_research_pilot.py"
SPEC = importlib.util.spec_from_file_location("bounded_pilot", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
pilot = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pilot)


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(pilot.canonical(value))


def _candidate_source(class_name: str, body: str = "return dataframe") -> bytes:
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
        f"        {body}\n\n"
        "    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:\n"
        "        return dataframe\n\n"
        "    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:\n"
        "        return dataframe\n"
    ).encode()


def test_t0_check_development_root_uses_staged_read_only_capability(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = tmp_path / "development"
    source = tmp_path / "freqtrade-source"
    root.mkdir()
    source.mkdir()
    captured: dict[str, object] = {}

    class ReadyCapability:
        status = "READY"

        @staticmethod
        def public() -> dict[str, object]:
            return {"status": "READY", "holdout": "SEALED_UNREAD"}

    def freeze(
        development_root: Path,
        freqtrade_python: Path,
        freqtrade_source: Path,
    ) -> ReadyCapability:
        captured.update(
            root=development_root,
            python=freqtrade_python,
            source=freqtrade_source,
        )
        return ReadyCapability()

    monkeypatch.setattr(pilot, "freeze_development_capability", freeze)
    assert (
        pilot.main(
            [
                "check-development-root",
                "--development-root",
                str(root),
                "--freqtrade-python",
                sys.executable,
                "--freqtrade-source",
                str(source),
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "DATA_READY"
    assert result["capability_status"] == "READY"
    assert result["holdout"] == "SEALED_UNREAD"
    assert captured == {
        "root": root,
        "python": Path(sys.executable),
        "source": source,
    }


def _plan_root(tmp_path: Path) -> Path:
    root = tmp_path / "pilot"
    candidates = root / "candidates"
    candidates.mkdir(parents=True)
    window = {
        "schema": "freqtrade-lab-okx-window-v1",
        "data_start_utc": "2026-05-31T22:00:00Z",
        "development_start_utc": "2026-06-01T00:00:00Z",
        "holdout_start_utc": "2026-07-31T00:00:00Z",
        "end_exclusive_utc": "2026-08-30T00:00:00Z",
    }
    _write_json(root / pilot.WINDOW, window)
    source = _candidate_source("CandidateOne")
    strategy = candidates / "CandidateOne.py"
    strategy.write_bytes(source)
    research_spec = {
        "schema": "freqtrade-lab-research-spec-v1",
        "profile": {
            "history_start_date": "2026-06-01",
            "holdout_days": 30,
            "stress_fee_multiplier": 2.0,
        },
        "candidate": {
            "class_name": "CandidateOne",
            "metadata": {
                "pilot_id": "test-pilot",
                "economic_evidence": "NOT_EVALUATED",
                "generation": {
                    "source": "CODEX",
                    "model": None,
                    "returned_strategy_count": 1,
                    "source_item_index": 0,
                },
            },
        },
    }
    spec_path = candidates / "CandidateOne-spec.json"
    _write_json(spec_path, research_spec)
    plan = {
        "schema": pilot.SCHEMA,
        "pilot_id": "test-pilot",
        "freqtrade_version": "2026.7",
        "window_spec_sha256": pilot.digest((root / pilot.WINDOW).read_bytes()),
        "development_timerange": "20260601-20260731",
        "holdout_timerange": "20260731-20260830",
        "stress_fee_multiplier": 2.0,
        "selection": {
            "minimum_trades": 20,
            "max_selected": 1,
            "no_eligible": "STOP",
            "missing_metric_policy": "STOP",
            "visibility": "DEVELOPMENT_ONLY_BLIND",
            "candidate_execution_failure": "STOP",
            "ranking": list(pilot.RANKING),
            "economic_gate": "NONE_TECHNICAL_PILOT",
        },
        "holdout_policy": {
            "max_open_count": 1,
            "retry_after_open": False,
            "tune_after_result": False,
        },
        "candidates": [
            {
                "candidate_id": "candidate-one",
                "class_name": "CandidateOne",
                "strategy_file": "candidates/CandidateOne.py",
                "research_spec_file": "candidates/CandidateOne-spec.json",
                "strategy_sha256": pilot.digest(source),
                "research_spec_sha256": pilot.digest(spec_path.read_bytes()),
            }
        ],
    }
    _write_json(root / pilot.PLAN, plan)
    return root


def _enable_positive_development_gate(
    root: Path,
    *,
    minimum_profit_pct: float = 0.5,
    minimum_profit_factor: float = 1.1,
    maximum_drawdown_pct: float = 10.0,
) -> None:
    plan = json.loads((root / pilot.PLAN).read_bytes())
    plan["selection"].update(
        {
            "economic_gate": "POSITIVE_DEVELOPMENT_V1",
            "minimum_profit_pct": minimum_profit_pct,
            "minimum_profit_factor": minimum_profit_factor,
            "maximum_drawdown_pct": maximum_drawdown_pct,
        }
    )
    _write_json(root / pilot.PLAN, plan)


def _rewrite_rolling_window(
    root: Path,
    *,
    development: str = "20260701-20260830",
    holdout: str = "20260830-20260929",
    schema: str = pilot.STRICT_WINDOW_SCHEMA,
) -> None:
    development_start, _ = pilot.timerange(development, "Development")
    holdout_start, holdout_stop = pilot.timerange(holdout, "Holdout")
    _write_json(
        root / pilot.WINDOW,
        {
            "schema": schema,
            "data_start_utc": "2026-06-30T22:00:00Z",
            "development_start_utc": development_start.isoformat().replace(
                "+00:00", "Z"
            ),
            "holdout_start_utc": holdout_start.isoformat().replace("+00:00", "Z"),
            "end_exclusive_utc": holdout_stop.isoformat().replace("+00:00", "Z"),
        },
    )
    plan = json.loads((root / pilot.PLAN).read_bytes())
    plan["development_timerange"] = development
    plan["holdout_timerange"] = holdout
    plan["window_spec_sha256"] = pilot.digest((root / pilot.WINDOW).read_bytes())
    spec_path = root / plan["candidates"][0]["research_spec_file"]
    spec = json.loads(spec_path.read_bytes())
    spec["profile"]["history_start_date"] = development_start.strftime("%Y-%m-%d")
    spec["profile"]["holdout_days"] = (holdout_stop - holdout_start).days
    _write_json(spec_path, spec)
    plan["candidates"][0]["research_spec_sha256"] = pilot.digest(spec_path.read_bytes())
    _write_json(root / pilot.PLAN, plan)


def _development_result(
    candidate_id: str,
    **overrides: object,
) -> dict[str, object]:
    return {
        "candidate_id": candidate_id,
        "total_trades": 20,
        "profit_pct": 0.5,
        "max_drawdown_pct": 5.0,
        "profit_factor": 1.1,
        **overrides,
    }


def _write_open_receipts(root: Path, plan: dict[str, object]) -> None:
    candidate = plan["candidates"][0]
    provenance = root / "selected-input" / "retained-data-provenance.json"
    stop = pilot.timerange(plan["holdout_timerange"], "Holdout")[1]
    for scenario, relative in (
        ("HOLDOUT", pilot.HOLDOUT_SEAL),
        ("HOLDOUT_STRESS", pilot.STRESS_SEAL),
    ):
        _write_json(
            root / relative,
            {
                "schema": "freqtrade-lab-scenario-open-v1",
                "scenario": scenario,
                "timerange": plan["holdout_timerange"],
                "strategy": candidate["class_name"],
                "strategy_sha256": candidate["strategy_sha256"],
                "data_provenance_sha256": pilot.digest(provenance.read_bytes()),
                "exclusive_stop_utc": stop.isoformat().replace("+00:00", "Z"),
                "meaning": "one-shot scenario execution budget was consumed before retained market data validation began",
                "opened_at_utc": "2026-08-31T00:00:00.000Z",
            },
        )


def _mock_pilot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, display_failure: str | None = None, research_failure: str | None = None) -> tuple[Path, Path]:
    root = _plan_root(tmp_path)
    plan = pilot.load_plan(root)
    candidate = plan["candidates"][0]
    source = tmp_path / "freqtrade-source"
    source.mkdir()
    input_root = root / "selected-input"
    input_root.mkdir()
    _write_json(input_root / "retained-data-provenance.json", {"frozen": True})
    produced = SimpleNamespace(imported=SimpleNamespace(research_run_id="research-run-1"), manifest_sha256="a" * 64, bundle_root=root / "mock-bundle", artifacts=[])

    def select(*args: object) -> str:
        pilot.write_once(root / pilot.SELECTION, {"selected_candidate_id": candidate["candidate_id"]})
        return candidate["candidate_id"]

    def producer(**kwargs: object) -> object:
        if research_failure is not None:
            _write_open_receipts(root, plan)
        return produced

    def evidence(database: Path, run_id: str) -> dict[str, object]:
        assert run_id == produced.imported.research_run_id
        if research_failure == "database":
            raise sqlite3.DatabaseError("database evidence unavailable")
        return {
            "research_run_id": run_id,
            "verdict": None,
            "release_count": 0,
            "scenarios": [{"scenario": scenario, "scenario_passed": None} for scenario in ("DEVELOPMENT", "HOLDOUT", "HOLDOUT_STRESS")],
        }

    def replay(*args: object) -> dict[str, str]:
        return {"status": "EXACT_REPORT_SEMANTICS_AND_DATA_VIEW_MATCH"}

    def library(database: Path) -> None:
        if display_failure == "library":
            raise pilot.StrategyLibraryError("display unavailable")

    def frequi(*args: object) -> dict[str, object]:
        if display_failure == "frequi":
            raise pilot.PresentationUnavailableError("target unavailable")
        if research_failure == "unexpected":
            raise AttributeError("source provenance shape is invalid")
        return {"root": str(root / "frequi-results"), "files": []}

    monkeypatch.setattr(pilot, "verify_data", lambda *args: {"status": "DATA_READY"})
    monkeypatch.setattr(pilot, "materialize_inputs", lambda *args: {candidate["candidate_id"]: input_root})
    monkeypatch.setattr(pilot, "materialize_development_isolation", lambda *args: {"receipt": {}})
    monkeypatch.setattr(pilot, "screen", lambda *args: [])
    monkeypatch.setattr(pilot, "select", select)
    monkeypatch.setattr(pilot, "init_database", lambda *args: None)
    monkeypatch.setattr(pilot, "materialize_selected_input", lambda *args: input_root)
    monkeypatch.setattr(pilot, "verify_candidate_copy", lambda *args: None)
    monkeypatch.setattr(pilot, "run_research_candidate", producer)
    monkeypatch.setattr(pilot, "scenario_open_evidence", lambda *args: {"holdout_open_count": 1, "stress_open_count": 1, "receipts": {}})
    monkeypatch.setattr(pilot, "database_evidence", evidence)
    monkeypatch.setattr(pilot, "development_replay_evidence", replay)
    monkeypatch.setattr(pilot, "validate_strategy_library_database", library)
    monkeypatch.setattr(pilot, "copy_frequi_results", frequi)
    monkeypatch.setattr(pilot, "now", lambda: "2026-08-31T00:00:00.000Z")
    return root, source


def _main_args(root: Path, source: Path) -> list[str]:
    return [
        "run", "--pilot-root", str(root), "--freqtrade-python", sys.executable,
        "--freqtrade-source", str(source), "--frequi-base-url", "http://127.0.0.1:18766",
    ]


def _search_root(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "search-campaign"
    data_root = root / "acquisition" / "data" / "okx" / "futures"
    data_root.mkdir(parents=True)
    data_names = {
        "futures_5m": "TEST_USDT_USDT-5m-futures.feather",
        "mark_1h": "TEST_USDT_USDT-1h-mark.feather",
        "funding_history": "TEST_USDT_USDT-1h-funding_rate.feather",
    }
    rows = dict(pilot.FROZEN_SEARCH_ROWS)
    local: dict[str, object] = {}
    source_data_sha256: dict[str, str] = {}
    for series, name in data_names.items():
        data = f"unit-only-{series}\n".encode()
        path = data_root / name
        path.write_bytes(data)
        relative = f"futures/{name}"
        source_data_sha256[relative] = pilot.digest(data)
        local[f"data/okx/{relative}"] = {
            "bytes": len(data),
            "sha256": pilot.digest(data),
            "rows": rows[series],
        }
    config = json.loads(
        (
            Path(__file__).parent
            / "fixtures"
            / "freqtrade_2026_7"
            / "producer"
            / "config.json"
        ).read_bytes()
    )
    config["exchange"]["pair_whitelist"] = ["TEST/USDT:USDT"]
    _write_json(root / "acquisition" / "config.json", config)
    _write_json(
        root / "acquisition" / "market_snapshot.json",
        {
            "id": "TEST-USDT-SWAP",
            "symbol": "TEST/USDT:USDT",
            "active": True,
            "contract": True,
            "swap": True,
            "linear": True,
            "inverse": False,
            "type": "swap",
        },
    )
    _write_json(
        root / "acquisition" / "isolated_tiers_snapshot.json",
        [{"symbol": "TEST/USDT:USDT"}],
    )
    config = (root / "acquisition" / "config.json").read_bytes()
    market = (root / "acquisition" / "market_snapshot.json").read_bytes()
    tiers = (root / "acquisition" / "isolated_tiers_snapshot.json").read_bytes()
    local.update(
        {
            "market_snapshot.json": {
                "bytes": len(market),
                "sha256": pilot.digest(market),
            },
            "isolated_tiers_snapshot.json": {
                "bytes": len(tiers),
                "sha256": pilot.digest(tiers),
            },
        }
    )
    provenance = {
        "schema": "freqtrade-lab-retained-search-data-v2",
        "source": {
            "host": "www.okx.com",
            "authentication": "none",
            "pair": "TEST/USDT:USDT",
            "instrument_id": "TEST-USDT-SWAP",
        },
        "freqtrade": {
            "version": "2026.7",
            "tag": "2026.7",
            "commit": "52bc96f4480b1a0da6a9b455bd00b17fbb6786a5",
            "dependencies": dict(offline_runner.SUPPORTED_DEPENDENCIES),
        },
        "contract": {
            "timeframe": "5m",
            "search_timerange": "20260101-20260131",
            "data_dir": "data/okx",
            "market_snapshot": "market_snapshot.json",
            "leverage_tiers": "isolated_tiers_snapshot.json",
            "config": "config.json",
        },
        "source_acquisition": {
            "provenance_sha256": "a" * 64,
            "retrieval_receipt_sha256": "b" * 64,
            "data_sha256": source_data_sha256,
        },
        "search_retention": {
            "startup_start_utc": "2025-12-31T22:00:00Z",
            "search_start_utc": "2026-01-01T00:00:00Z",
            "end_exclusive_utc": "2026-01-31T00:00:00Z",
            "later_rows_exposed_to_search": False,
            "rows": rows,
        },
        "local_only_files": local,
        "files": {
            "config.json": {
                "bytes": len(config),
                "sha256": pilot.digest(config),
            }
        },
    }
    _write_json(root / "acquisition" / "retained-data-provenance.json", provenance)
    source = tmp_path / "freqtrade-source"
    source.mkdir()
    return root, source


def _unit_search_rows(path: Path | str) -> int:
    name = str(path)
    return next(
        pilot.FROZEN_SEARCH_ROWS[series]
        for series, suffix in pilot.SEARCH_SERIES_SUFFIXES.items()
        if name.endswith(suffix)
    )


def _future_holdout_root_fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    fully_closed: bool = True,
) -> SimpleNamespace:
    """Build a local future-acquisition envelope around one passed Dev run."""
    pair = "TEST/USDT:USDT"
    instrument_id = "TEST-USDT-SWAP"
    research_run_id = "future-holdout-run"
    candidate_id = "future-candidate"
    generation_run_id = "future-generation"
    profile_id = "future-profile"
    candidate_sha256 = "c" * 64
    profile_sha256 = "f" * 64
    development_manifest_sha256 = "d" * 64
    holdout_timerange = "20260903-20261003"

    source_root = tmp_path / "future-source"
    acquisition = source_root / pilot.ACQUISITION
    source_data_root = acquisition / "data" / "okx"
    source_data_root.mkdir(parents=True)
    data_names = pilot._search_data_names(pair)
    source_rows = {
        "futures_5m": [
            "2026-09-02T21:55:00Z",
            "2026-09-02T22:00:00Z",
            "2026-09-03T00:00:00Z",
            "2026-10-02T23:55:00Z",
            "2026-10-03T00:00:00Z",
        ],
        "mark_1h": [
            "2026-09-02T21:00:00Z",
            "2026-09-02T22:00:00Z",
            "2026-09-03T00:00:00Z",
            "2026-10-02T23:00:00Z",
            "2026-10-03T00:00:00Z",
        ],
        "funding_history": [
            "2026-09-02T16:00:00Z",
            "2026-09-03T00:00:00Z",
            "2026-10-02T16:00:00Z",
            "2026-10-03T00:00:00Z",
        ],
    }
    source_data_sha256: dict[str, str] = {}
    for series, relative in data_names.items():
        data = pilot.canonical(source_rows[series])
        path = source_data_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        source_data_sha256[relative] = pilot.digest(data)

    config = json.loads(
        (
            Path(__file__).parent
            / "fixtures"
            / "freqtrade_2026_7"
            / "producer"
            / "config.json"
        ).read_bytes()
    )
    config["exchange"]["pair_whitelist"] = [pair]
    _write_json(acquisition / "config.json", config)
    _write_json(
        acquisition / "market_snapshot.json",
        {
            "id": instrument_id,
            "symbol": pair,
            "active": True,
            "contract": True,
            "swap": True,
            "linear": True,
            "inverse": False,
            "type": "swap",
        },
    )
    _write_json(
        acquisition / "isolated_tiers_snapshot.json",
        [{"symbol": pair}],
    )
    receipt = {
        "host": "www.okx.com",
        "authentication": "none",
        "pair": pair,
        "instrument_id": instrument_id,
        "finished_at_utc": "2026-10-03T00:01:00Z",
        "data_window": {
            "start_utc": "2026-09-02T22:00:00Z",
            "end_exclusive_utc": "2026-10-03T00:00:00Z",
            "fully_closed_at_fetch": fully_closed,
        },
    }
    _write_json(acquisition / "retrieval_receipt.json", receipt)
    provenance = {
        "schema": "freqtrade-lab-retained-okx-data-v1",
        "source": {
            "host": "www.okx.com",
            "authentication": "none",
            "pair": pair,
            "instrument_id": instrument_id,
            "retrieval_receipt": "retrieval_receipt.json",
        },
        "freqtrade": {
            "version": "2026.7",
            "tag": "2026.7",
            "commit": pilot.SUPPORTED_FREQTRADE_COMMIT,
            "dependencies": dict(pilot.RUNNER_DEPENDENCIES),
        },
        "contract": {
            "timeframe": "5m",
            "config": "config.json",
            "data_dir": "data/okx",
            "market_snapshot": "market_snapshot.json",
            "leverage_tiers": "isolated_tiers_snapshot.json",
            "holdout_timerange": holdout_timerange,
        },
    }
    _write_json(acquisition / "retained-data-provenance.json", provenance)
    _write_json(
        source_root / pilot.PLAN,
        {
            "holdout_timerange": holdout_timerange,
            "stress_fee_multiplier": 2.0,
        },
    )
    provenance_path = acquisition / "retained-data-provenance.json"
    receipt_path = acquisition / "retrieval_receipt.json"

    development_root = tmp_path / "development-root"
    development_root.mkdir()
    run_dir = tmp_path / "runtime" / research_run_id
    development_input = run_dir / "development-input"
    development_input.mkdir(parents=True)
    _write_json(
        development_input / "manifest.json",
        {"schema": "freqtrade-lab-development-input-v1", "research_run_id": research_run_id},
    )
    freqtrade_source = tmp_path / "freqtrade-source"
    freqtrade_source.mkdir()
    output_parent = tmp_path / "published"
    output_parent.mkdir()
    output_root = output_parent / "holdout-root"
    database = tmp_path / "lab.sqlite"

    capability = SimpleNamespace(
        status="READY",
        root_schema=pilot.DEVELOPMENT_ROOT_SCHEMA,
        pilot_root=development_root.resolve(),
        bound_research_run_id=research_run_id,
        bound_candidate_id=candidate_id,
        bound_generation_run_id=generation_run_id,
        bound_candidate_sha256=candidate_sha256,
        bound_profile_id=profile_id,
        bound_profile_sha256=profile_sha256,
        plan_sha256=development_manifest_sha256,
        pair=pair,
        instrument_id=instrument_id,
        config_sha256=pilot.digest((acquisition / "config.json").read_bytes()),
        runner_sha256=pilot.digest(pilot.DEFAULT_RUNNER.read_bytes()),
        development_timerange="20260803-20260902",
        freqtrade_python=Path(sys.executable),
        freqtrade_source=freqtrade_source,
    )
    row = {
        "candidate_id": candidate_id,
        "generation_run_id": generation_run_id,
        "code_sha256": candidate_sha256,
        "research_profile_id": profile_id,
        "stress_fee_multiplier": 2.0,
        "run_dir": str(run_dir),
    }
    parsed = SimpleNamespace(
        archive_sha256="a" * 64,
        metadata_sha256="b" * 64,
        provenance_sha256="e" * 64,
    )
    snapshot = {
        "future_holdout": {"timerange": holdout_timerange},
        "development_root_manifest_sha256": development_manifest_sha256,
    }

    monkeypatch.setattr(pilot, "freeze_development_capability", lambda *args: capability)
    monkeypatch.setattr(pilot, "get_connection", lambda *args, **kwargs: sqlite3.connect(":memory:"))
    monkeypatch.setattr(
        pilot,
        "_eligible_holdout_row",
        lambda *args, **kwargs: (row, parsed, snapshot),
    )
    monkeypatch.setattr(
        pilot,
        "_holdout_profile_binding_sha256",
        lambda *args: profile_sha256,
    )
    monkeypatch.setattr(
        pilot,
        "load_plan",
        lambda *args, **kwargs: {
            "holdout_timerange": holdout_timerange,
            "stress_fee_multiplier": 2.0,
        },
    )
    monkeypatch.setattr(
        pilot,
        "verify_data",
        lambda *args: {
            "provenance_sha256": pilot.digest(provenance_path.read_bytes()),
            "retrieval_receipt_sha256": pilot.digest(receipt_path.read_bytes()),
        },
    )
    monkeypatch.setattr(pilot, "_verify_dependency_versions", lambda *args: None)

    def verified_source(*args: object, **kwargs: object) -> dict[str, object]:
        assert kwargs["scenario"] == "HOLDOUT"
        assert kwargs["timerange"] == holdout_timerange
        assert kwargs["pair"] == pair
        return {"data_sha256": dict(source_data_sha256)}

    def copy_source_view(
        source: Path,
        destination: Path,
        timerange: str,
        expected: dict[str, str],
    ) -> dict[str, object]:
        assert timerange == holdout_timerange
        for relative, expected_sha256 in expected.items():
            data = (source / relative).read_bytes()
            assert pilot.digest(data) == expected_sha256
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        return {"exclusive_stop_utc": "2026-10-03T00:00:00Z", "files": {}}

    def trim_phase_only(
        data_root: Path,
        names: dict[str, str],
        timerange: str,
    ) -> dict[str, dict[str, object]]:
        window = pilot._search_window_contract(timerange)
        records: dict[str, dict[str, object]] = {}
        for series, relative in names.items():
            path = data_root / relative
            values = json.loads(path.read_bytes())
            start = window["starts"][series].isoformat().replace("+00:00", "Z")
            stop = window["search_stop"].isoformat().replace("+00:00", "Z")
            retained = [value for value in values if start <= value < stop]
            data = pilot.canonical(retained)
            path.write_bytes(data)
            records[relative] = {
                "bytes": len(data),
                "sha256": pilot.digest(data),
                "rows": len(retained),
            }
        return records

    monkeypatch.setattr(pilot, "_verify_data_provenance", verified_source)
    monkeypatch.setattr(pilot, "_create_scenario_data_view", copy_source_view)
    monkeypatch.setattr(pilot, "_trim_holdout_view", trim_phase_only)
    return SimpleNamespace(
        source_root=source_root,
        development_root=development_root,
        freqtrade_source=freqtrade_source,
        database=database,
        output_root=output_root,
        research_run_id=research_run_id,
        candidate_id=candidate_id,
        profile_id=profile_id,
        holdout_timerange=holdout_timerange,
        data_names=data_names,
        source_rows=source_rows,
        provenance_path=provenance_path,
        receipt_path=receipt_path,
    )


def _direct_development_source_fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    source_state: str = "closed",
) -> SimpleNamespace:
    """Reuse the public-acquisition envelope without a legacy Pilot plan."""
    fixture = _future_holdout_root_fixture(tmp_path, monkeypatch)
    development_timerange = "20260704-20260902"
    acquisition = fixture.source_root / pilot.ACQUISITION
    (fixture.source_root / pilot.PLAN).unlink()
    data_root = acquisition / "data" / "okx"
    for relative in fixture.data_names.values():
        (data_root / relative).unlink()
    data_names = pilot._search_data_names("XRP/USDT:USDT")
    rows = {
        "futures_5m": [
            "2026-07-03T22:00:00Z",
            "2026-07-04T00:00:00Z",
            "2026-09-01T23:55:00Z",
        ],
        "mark_1h": [
            "2026-07-03T22:00:00Z",
            "2026-07-04T00:00:00Z",
            "2026-09-01T23:00:00Z",
        ],
        "funding_history": [
            "2026-07-04T00:00:00Z",
            "2026-09-01T16:00:00Z",
        ],
    }
    data_sha256: dict[str, str] = {}
    local_files: dict[str, dict[str, object]] = {}
    for series, relative in data_names.items():
        data = pilot.canonical(rows[series])
        (data_root / relative).write_bytes(data)
        data_sha256[relative] = pilot.digest(data)
        local_files[f"data/okx/{relative}"] = {
            "bytes": len(data),
            "sha256": pilot.digest(data),
        }
    for name in ("market_snapshot.json", "isolated_tiers_snapshot.json"):
        data = (acquisition / name).read_bytes()
        local_files[name] = {"bytes": len(data), "sha256": pilot.digest(data)}

    config = json.loads((acquisition / "config.json").read_bytes())
    config["exchange"]["pair_whitelist"] = ["XRP/USDT:USDT"]
    _write_json(acquisition / "config.json", config)
    _write_json(
        acquisition / "market_snapshot.json",
        {"id": "XRP-USDT-SWAP", "symbol": "XRP/USDT:USDT"},
    )
    _write_json(
        acquisition / "isolated_tiers_snapshot.json",
        [{"symbol": "XRP/USDT:USDT"}],
    )
    for name in ("market_snapshot.json", "isolated_tiers_snapshot.json"):
        data = (acquisition / name).read_bytes()
        local_files[name] = {"bytes": len(data), "sha256": pilot.digest(data)}

    provenance = json.loads(fixture.provenance_path.read_bytes())
    provenance["portable_retained_fixture"] = "BLOCKED_LICENSE"
    provenance["source"].update(
        pair="XRP/USDT:USDT",
        instrument_id="XRP-USDT-SWAP",
        pair_family="XRP-USDT",
    )
    provenance["contract"].pop("holdout_timerange")
    provenance["contract"]["development_timerange"] = development_timerange
    provenance["contract"]["strategy"] = "strategies/DevelopmentCandidate.py"
    provenance["local_only_files"] = local_files
    config_data = (acquisition / "config.json").read_bytes()
    provenance["files"] = {
        "config.json": {
            "bytes": len(config_data),
            "sha256": pilot.digest(config_data),
        }
    }
    _write_json(fixture.provenance_path, provenance)
    source_stop = (
        "2026-09-01T23:55:00Z"
        if source_state == "short"
        else "2026-09-02T00:00:00Z"
    )
    _write_json(
        fixture.receipt_path,
        {
            "gate": "freqtrade-lab-development-window-v1",
            "host": "www.okx.com",
            "authentication": "none",
            "pair": "XRP/USDT:USDT",
            "instrument_id": "XRP-USDT-SWAP",
            "pair_family": "XRP-USDT",
            "requests": [],
            "snapshots": {
                name: local_files[name]["sha256"]
                for name in (
                    "market_snapshot.json",
                    "isolated_tiers_snapshot.json",
                )
            },
            "landed_files": {
                f"data/okx/{relative}": local_files[f"data/okx/{relative}"]
                for relative in data_names.values()
            },
            "runtime": {},
            "started_at_utc": "2026-09-01T23:54:00Z",
            "finished_at_utc": source_stop,
            "data_window": {
                "schema": "freqtrade-lab-okx-development-window-v1",
                "start_utc": "2026-07-03T22:00:00Z",
                "development_start_utc": "2026-07-04T00:00:00Z",
                "end_exclusive_utc": source_stop,
                "fully_closed_at_fetch": source_state != "unclosed",
                "startup_candles_required": 20,
            },
            "series": {
                "futures_5m": {
                    "rows": 17304,
                    "start_utc": "2026-07-03T22:00:00Z",
                    "end_utc": "2026-09-01T23:55:00Z",
                    "duplicates": 0,
                    "missing_intervals": 0,
                    "unclosed_candles": 0,
                },
                "mark_1h": {
                    "rows": 1442,
                    "start_utc": "2026-07-03T22:00:00Z",
                    "end_utc": "2026-09-01T23:00:00Z",
                    "duplicates": 0,
                    "missing_intervals": 0,
                    "unclosed_candles": 0,
                },
                "funding_history": {
                    "rows": 180,
                    "start_utc": "2026-07-04T00:00:00Z",
                    "end_utc": "2026-09-01T16:00:00Z",
                    "duplicates": 0,
                    "outside_window": 0,
                },
            },
        },
    )
    receipt_data = fixture.receipt_path.read_bytes()
    provenance = json.loads(fixture.provenance_path.read_bytes())
    provenance["files"]["retrieval_receipt.json"] = {
        "bytes": len(receipt_data),
        "sha256": pilot.digest(receipt_data),
    }
    _write_json(fixture.provenance_path, provenance)

    candidate = {
        "id": fixture.candidate_id,
        "generation_run_id": "future-generation",
        "class_name": "DevelopmentCandidate",
        "code_sha256": "c" * 64,
        "research_profile_id": fixture.profile_id,
    }
    for module in (pilot, development_run):
        monkeypatch.setattr(
            module,
            "get_connection",
            lambda *args, **kwargs: sqlite3.connect(":memory:"),
        )
        monkeypatch.setattr(module, "_schema_v1", lambda *args: None, raising=False)
        monkeypatch.setattr(
            module, "_bound_candidate", lambda *args: candidate, raising=False
        )
        monkeypatch.setattr(module, "_profile_gate", lambda *args: None, raising=False)
        monkeypatch.setattr(
            module,
            "_profile_binding_sha256",
            lambda *args: "f" * 64,
            raising=False,
        )
    monkeypatch.setattr(pilot, "_development_schema_v1", lambda *args: None)
    monkeypatch.setattr(
        pilot, "_bound_development_candidate", lambda *args: candidate
    )
    monkeypatch.setattr(pilot, "_development_profile_gate", lambda *args: None)
    monkeypatch.setattr(
        pilot,
        "_development_profile_binding_sha256",
        lambda *args: "f" * 64,
    )
    monkeypatch.setattr(
        pilot,
        "load_plan",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("direct Development source must not load a Pilot plan")
        ),
    )
    monkeypatch.setattr(
        pilot,
        "_verify_data_provenance",
        lambda *args, **kwargs: {
            "data_sha256": dict(data_sha256),
            "market_snapshot_sha256": local_files["market_snapshot.json"]["sha256"],
            "leverage_tiers_sha256": local_files[
                "isolated_tiers_snapshot.json"
            ]["sha256"],
        },
    )

    def reject_reslicing(*args: object, **kwargs: object) -> object:
        raise AssertionError("exact Development source must be copied without slicing")

    monkeypatch.setattr(pilot, "_create_scenario_data_view", reject_reslicing)
    monkeypatch.setattr(
        pilot,
        "_verify_search_output_dates",
        lambda *args: (_ for _ in ()).throw(
            AssertionError("60-day Development must not use the 30-day Search verifier")
        ),
    )
    def verify_development_output(
        output: Path,
        names: dict[str, str],
        timerange: str,
        expected_rows: dict[str, int],
    ) -> dict[str, int]:
        assert output.is_dir()
        assert names == data_names
        assert timerange == development_timerange
        assert expected_rows == {
            "futures_5m": 17304,
            "mark_1h": 1442,
            "funding_history": 180,
        }
        return dict(expected_rows)

    monkeypatch.setattr(
        pilot,
        "_verify_development_output_dates",
        verify_development_output,
    )
    monkeypatch.setattr(pilot, "_trim_holdout_view", reject_reslicing)
    monkeypatch.setattr(
        pilot, "_trim_development_view", reject_reslicing, raising=False
    )
    values = vars(fixture).copy()
    values.update(
        source_root=acquisition,
        output_root=fixture.output_root.parent / "development-root",
        development_timerange=development_timerange,
        data_names=data_names,
        rows=rows,
        source_state=source_state,
        research_run_id="00000000-0000-4000-8000-000000000001",
    )
    return SimpleNamespace(**values)


def test_t0_prepare_holdout_root_publishes_only_closed_future_phase(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fixture = _future_holdout_root_fixture(tmp_path, monkeypatch)
    provenance_sha256 = pilot.digest(fixture.provenance_path.read_bytes())
    receipt_sha256 = pilot.digest(fixture.receipt_path.read_bytes())
    arguments = [
        "prepare-holdout-root",
        "--source-pilot-root",
        str(fixture.source_root),
        "--source-provenance-sha256",
        provenance_sha256,
        "--source-receipt-sha256",
        receipt_sha256,
        "--output-root",
        str(fixture.output_root),
        "--development-root",
        str(fixture.development_root),
        "--freqtrade-python",
        sys.executable,
        "--freqtrade-source",
        str(fixture.freqtrade_source),
        "--database",
        str(fixture.database),
        "--research-run-id",
        fixture.research_run_id,
    ]

    assert pilot.main(arguments) == 0
    result = json.loads(capsys.readouterr().out)
    manifest_path = fixture.output_root / pilot.HOLDOUT_ROOT_MANIFEST
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    assert result == {
        "candidate_id": fixture.candidate_id,
        "files": 6,
        "holdout_timerange": fixture.holdout_timerange,
        "manifest_sha256": pilot.digest(manifest_bytes),
        "research_profile_id": fixture.profile_id,
        "research_run_id": fixture.research_run_id,
        "retrieval_receipt_sha256": receipt_sha256,
        "source_provenance_sha256": provenance_sha256,
        "status": "HOLDOUT_ROOT_READY_SEALED",
    }
    assert manifest["source_receipts"] == {
        "fully_closed_at_fetch": True,
        "retrieval_finished_at_utc": "2026-10-03T00:01:00Z",
        "retrieval_receipt_sha256": receipt_sha256,
        "source_end_exclusive_utc": "2026-10-03T00:00:00Z",
        "source_provenance_sha256": provenance_sha256,
        "source_start_utc": "2026-09-02T22:00:00Z",
    }
    assert manifest["binding"]["research_run_id"] == fixture.research_run_id
    assert manifest["binding"]["candidate_id"] == fixture.candidate_id
    assert manifest["binding"]["research_profile_id"] == fixture.profile_id
    assert set(manifest["files"]) == {
        "config.json",
        "market_snapshot.json",
        "isolated_tiers_snapshot.json",
        *(f"data/okx/{name}" for name in fixture.data_names.values()),
    }
    assert {
        path.relative_to(fixture.output_root).as_posix()
        for path in fixture.output_root.rglob("*")
        if path.is_file()
    } == {pilot.HOLDOUT_ROOT_MANIFEST, *manifest["files"]}
    assert not (fixture.output_root / pilot.ACQUISITION).exists()
    window = pilot._search_window_contract(fixture.holdout_timerange)
    for series, relative in fixture.data_names.items():
        path = fixture.output_root / "data" / "okx" / relative
        retained = json.loads(path.read_bytes())
        start = window["starts"][series].isoformat().replace("+00:00", "Z")
        stop = window["search_stop"].isoformat().replace("+00:00", "Z")
        assert retained == [
            value
            for value in fixture.source_rows[series]
            if start <= value < stop
        ]
        record = manifest["files"][f"data/okx/{relative}"]
        assert record["bytes"] == path.stat().st_size
        assert record["sha256"] == pilot.digest(path.read_bytes())
        assert record["role"] == "market_data"
    assert fixture.output_root.stat().st_mode & 0o777 == 0o500
    assert all(
        path.stat().st_mode & 0o777 == (0o500 if path.is_dir() else 0o400)
        for path in fixture.output_root.rglob("*")
    )

    with pytest.raises(pilot.PilotError, match="replay is forbidden"):
        pilot.main(arguments)
    assert manifest_path.read_bytes() == manifest_bytes
    assert not list(fixture.output_root.parent.glob(".holdout-root-*"))


@pytest.mark.parametrize("failure", ["untrusted", "unclosed"])
def test_t0_prepare_holdout_root_rejects_untrusted_or_unclosed_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    fixture = _future_holdout_root_fixture(
        tmp_path,
        monkeypatch,
        fully_closed=failure != "unclosed",
    )
    provenance_sha256 = pilot.digest(fixture.provenance_path.read_bytes())
    if failure == "untrusted":
        provenance_sha256 = "0" * 64

    with pytest.raises(
        pilot.PilotError,
        match=(
            "trusted source SHA-256 values do not match"
            if failure == "untrusted"
            else "identity/completeness receipt mismatch"
        ),
    ):
        pilot.prepare_holdout_root(
            fixture.source_root,
            fixture.output_root,
            fixture.development_root,
            Path(sys.executable),
            fixture.freqtrade_source,
            fixture.database,
            fixture.research_run_id,
            provenance_sha256,
            pilot.digest(fixture.receipt_path.read_bytes()),
        )
    assert not fixture.output_root.exists()
    assert not list(fixture.output_root.parent.glob(".holdout-root-*"))


def test_t0_prepare_holdout_root_exclusive_publish_preserves_concurrent_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _future_holdout_root_fixture(tmp_path, monkeypatch)
    original_freeze = pilot._freeze_staged_holdout_root

    def freeze_then_race(root: Path, capability: SimpleNamespace) -> object:
        frozen = original_freeze(root, capability)
        fixture.output_root.mkdir()
        (fixture.output_root / "owner.txt").write_text("concurrent owner\n")
        return frozen

    monkeypatch.setattr(pilot, "_freeze_staged_holdout_root", freeze_then_race)
    with pytest.raises(pilot.PilotError, match="created concurrently"):
        pilot.prepare_holdout_root(
            fixture.source_root,
            fixture.output_root,
            fixture.development_root,
            Path(sys.executable),
            fixture.freqtrade_source,
            fixture.database,
            fixture.research_run_id,
            pilot.digest(fixture.provenance_path.read_bytes()),
            pilot.digest(fixture.receipt_path.read_bytes()),
        )
    assert (fixture.output_root / "owner.txt").read_text() == "concurrent owner\n"
    assert not (fixture.output_root / pilot.HOLDOUT_ROOT_MANIFEST).exists()
    assert not list(fixture.output_root.parent.glob(".holdout-root-*"))


def _direct_development_args(fixture: SimpleNamespace) -> list[str]:
    return [
        "prepare-development-root",
        "--source-root",
        str(fixture.source_root),
        "--source-provenance-sha256",
        pilot.digest(fixture.provenance_path.read_bytes()),
        "--source-receipt-sha256",
        pilot.digest(fixture.receipt_path.read_bytes()),
        "--output-root",
        str(fixture.output_root),
        "--freqtrade-python",
        sys.executable,
        "--freqtrade-source",
        str(fixture.freqtrade_source),
        "--database",
        str(fixture.database),
        "--candidate-id",
        fixture.candidate_id,
        "--research-run-id",
        fixture.research_run_id,
    ]


def test_t0_prepare_development_root_accepts_closed_direct_acquisition_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fixture = _direct_development_source_fixture(tmp_path, monkeypatch)
    source_provenance = json.loads(fixture.provenance_path.read_bytes())
    source_receipt = json.loads(fixture.receipt_path.read_bytes())
    assert set(source_provenance["contract"]) == {
        "config",
        "data_dir",
        "development_timerange",
        "leverage_tiers",
        "market_snapshot",
        "strategy",
        "timeframe",
    }
    assert set(source_receipt["data_window"]) == {
        "schema",
        "start_utc",
        "development_start_utc",
        "end_exclusive_utc",
        "fully_closed_at_fetch",
        "startup_candles_required",
    }
    assert "holdout_timerange" not in source_provenance["contract"]
    assert "holdout_start_utc" not in source_receipt["data_window"]
    assert {
        series: record["rows"]
        for series, record in source_receipt["series"].items()
    } == {"futures_5m": 17304, "mark_1h": 1442, "funding_history": 180}
    assert not (fixture.source_root / pilot.PLAN).exists()
    assert not (fixture.source_root / "development-isolation").exists()

    assert pilot.main(_direct_development_args(fixture)) == 0
    result = json.loads(capsys.readouterr().out)
    manifest_path = fixture.output_root / development_run.DEVELOPMENT_ROOT_MANIFEST
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    provenance_sha256 = pilot.digest(fixture.provenance_path.read_bytes())
    receipt_sha256 = pilot.digest(fixture.receipt_path.read_bytes())
    assert result["status"] == "DEVELOPMENT_ROOT_READY"
    assert result["development_timerange"] == fixture.development_timerange
    assert result["rows"] == {
        "funding_history": 180,
        "futures_5m": 17304,
        "mark_1h": 1442,
    }
    assert result["manifest_sha256"] == pilot.digest(manifest_bytes)
    assert manifest["development_timerange"] == fixture.development_timerange
    assert manifest["source_receipts"] == {
        "fully_closed_at_fetch": True,
        "retrieval_finished_at_utc": "2026-09-02T00:00:00Z",
        "retrieval_receipt_sha256": receipt_sha256,
        "source_end_exclusive_utc": "2026-09-02T00:00:00Z",
        "source_provenance_sha256": provenance_sha256,
        "source_start_utc": "2026-07-03T22:00:00Z",
    }
    assert manifest["binding"]["research_run_id"] == fixture.research_run_id
    assert manifest["binding"]["candidate_id"] == fixture.candidate_id
    assert set(manifest["files"]) == {
        "config.json",
        "market_snapshot.json",
        "isolated_tiers_snapshot.json",
        *(f"data/okx/{name}" for name in fixture.data_names.values()),
    }
    assert {
        path.relative_to(fixture.output_root).as_posix()
        for path in fixture.output_root.rglob("*")
        if path.is_file()
    } == {development_run.DEVELOPMENT_ROOT_MANIFEST, *manifest["files"]}
    assert b"holdout" not in manifest_bytes.lower()
    assert not (fixture.output_root / pilot.ACQUISITION).exists()
    for series, relative in fixture.data_names.items():
        path = fixture.output_root / "data" / "okx" / relative
        retained = json.loads(path.read_bytes())
        assert retained == fixture.rows[series]
        record = manifest["files"][f"data/okx/{relative}"]
        assert record == {
            "bytes": path.stat().st_size,
            "role": "market_data",
            "sha256": pilot.digest(path.read_bytes()),
        }
    assert fixture.output_root.stat().st_mode & 0o777 == 0o500
    assert all(
        path.stat().st_mode & 0o777 == (0o500 if path.is_dir() else 0o400)
        for path in fixture.output_root.rglob("*")
    )


@pytest.mark.parametrize("source_state", ["unclosed", "short"])
def test_t0_prepare_development_root_requires_closed_complete_development_window(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source_state: str,
) -> None:
    fixture = _direct_development_source_fixture(
        tmp_path,
        monkeypatch,
        source_state=source_state,
    )

    with pytest.raises(
        pilot.PilotError,
        match="closed|cover|coverage|completeness",
    ):
        pilot.main(_direct_development_args(fixture))
    assert not fixture.output_root.exists()
    assert not list(fixture.output_root.parent.glob(".development-root.preparing-*"))


@pytest.mark.parametrize("location", ["contract", "data_window"])
def test_t0_prepare_development_root_rejects_any_holdout_source_field(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    location: str,
) -> None:
    fixture = _direct_development_source_fixture(tmp_path, monkeypatch)
    if location == "contract":
        provenance = json.loads(fixture.provenance_path.read_bytes())
        provenance["contract"]["holdout_timerange"] = "20260902-20261002"
        _write_json(fixture.provenance_path, provenance)
    else:
        receipt = json.loads(fixture.receipt_path.read_bytes())
        receipt["data_window"]["holdout_start_utc"] = "2026-09-02T00:00:00Z"
        _write_json(fixture.receipt_path, receipt)
        receipt_data = fixture.receipt_path.read_bytes()
        provenance = json.loads(fixture.provenance_path.read_bytes())
        provenance["files"]["retrieval_receipt.json"] = {
            "bytes": len(receipt_data),
            "sha256": pilot.digest(receipt_data),
        }
        _write_json(fixture.provenance_path, provenance)

    with pytest.raises(pilot.PilotError, match="Holdout|holdout"):
        pilot.main(_direct_development_args(fixture))
    assert not fixture.output_root.exists()
    assert not list(fixture.output_root.parent.glob(".development-root.preparing-*"))


def test_t0_prepare_development_root_does_not_replace_concurrent_direct_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _direct_development_source_fixture(tmp_path, monkeypatch)
    original_publish = pilot._publish_directory_exclusive

    def publish_after_claim(source: Path, destination: Path) -> None:
        destination.mkdir()
        (destination / "owner.txt").write_text("concurrent owner\n")
        original_publish(source, destination)

    monkeypatch.setattr(pilot, "_publish_directory_exclusive", publish_after_claim)
    monkeypatch.setattr(
        development_run,
        "_publish_directory_exclusive",
        publish_after_claim,
    )
    with pytest.raises(pilot.PilotError, match="concurrent|claimed"):
        pilot.main(_direct_development_args(fixture))
    assert (fixture.output_root / "owner.txt").read_text() == "concurrent owner\n"
    assert not (
        fixture.output_root / development_run.DEVELOPMENT_ROOT_MANIFEST
    ).exists()
    assert not list(fixture.output_root.parent.glob(".development-root.preparing-*"))


def test_t0_search_capability_requires_exact_pyarrow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _ = _search_root(tmp_path)
    root.chmod(0o700)
    provenance = root / pilot.ACQUISITION / "retained-data-provenance.json"
    plan = {
        "schema": pilot.SEARCH_SCHEMA,
        "search_timerange": "20260101-20260131",
        "data_provenance_sha256": pilot.digest(provenance.read_bytes()),
    }
    monkeypatch.setitem(sys.modules, "pyarrow", None)
    monkeypatch.setitem(sys.modules, "pyarrow.feather", None)

    with pytest.raises(pilot.PilotError, match="exact PyArrow 25.0.0"):
        pilot.verify_data(root, plan)
    capability = search_campaign.freeze_search_capability(root, None, None)
    try:
        assert capability.status == "BLOCKED_DATA"
        assert not (root / pilot.SEARCH_CAMPAIGN).exists()
        assert not (root / pilot.SEARCH_TRIALS).exists()
    finally:
        capability.close()


def _search_candidate(
    root: Path,
    candidate_id: str,
    class_name: str,
    mechanism: str,
    *,
    relationship: str = "MECHANISM_SEED",
    changed_factor: str | None = None,
    parent_sha256: str | None = None,
    body: str = "return dataframe",
) -> dict[str, object]:
    path = root / "candidates" / f"{class_name}.py"
    path.parent.mkdir(exist_ok=True)
    source = _candidate_source(class_name, body)
    path.write_bytes(source)
    return {
        "candidate_id": candidate_id,
        "class_name": class_name,
        "mechanism": mechanism,
        "relationship": relationship,
        "changed_factor": changed_factor,
        "parent_strategy_sha256": parent_sha256,
        "strategy_file": f"candidates/{path.name}",
        "strategy_sha256": pilot.digest(source),
    }


def _write_search_campaign(
    root: Path,
    candidates: list[dict[str, object]],
    *,
    round_number: int = 1,
    parent: dict[str, object] | None = None,
    previous_receipt_sha256: str | None = None,
) -> None:
    _write_json(
        root / pilot.SEARCH_CAMPAIGN,
        {
            "schema": pilot.SEARCH_SCHEMA,
            "campaign_id": "bounded-evolution-test",
            "freqtrade_version": "2026.7",
            "round": round_number,
            "previous_round_receipt_sha256": previous_receipt_sha256,
            "search_timerange": "20260101-20260131",
            "data_provenance_sha256": pilot.digest(
                (root / "acquisition" / "retained-data-provenance.json").read_bytes()
            ),
            "budget": {"maximum_attempts": 6},
            "ranking": list(pilot.SEARCH_RANKING),
            "finalist_gate": pilot.SEARCH_GATE_CONTRACT,
            "parent": parent,
            "candidates": candidates,
        },
    )


def _patch_search_screen(
    monkeypatch: pytest.MonkeyPatch,
    metrics: dict[str, dict[str, object]],
) -> None:
    monkeypatch.setattr(pilot, "verify_data", lambda *args: {"status": "DATA_READY"})
    monkeypatch.setattr(
        pilot,
        "materialize_screening_isolation",
        lambda *args, **kwargs: {"receipt": {}, "provenance": Path("unused"), "data_dir": Path("unused")},
    )
    monkeypatch.setattr(
        pilot,
        "materialize_inputs",
        lambda root, plan, **kwargs: {
            item["candidate_id"]: root for item in plan["candidates"]
        },
    )

    def fake_screen(
        root: Path, plan: dict[str, object], *args: object, **kwargs: object
    ) -> list[dict[str, object]]:
        return [
            {
                "candidate_id": item["candidate_id"],
                "class_name": item["class_name"],
                "strategy_sha256": item["strategy_sha256"],
                "technical_status": "VALID",
                "failure_reason": None,
                **metrics[item["candidate_id"]],
            }
            for item in plan["candidates"]
        ]

    monkeypatch.setattr(pilot, "screen", fake_screen)


def _parent_contract(outcome: dict[str, object]) -> dict[str, object]:
    selected = outcome["brief"]["selected_parent"]
    return {
        key: selected[key]
        for key in ("candidate_id", "class_name", "mechanism", "strategy_sha256")
    }


def _search_records(root: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in (root / pilot.SEARCH_TRIALS).read_text(encoding="utf-8").splitlines()
    ]


def test_t0_plan_freezes_candidate_hash_and_codex_lineage(tmp_path: Path) -> None:
    root = _plan_root(tmp_path)

    plan = pilot.load_plan(root)

    assert plan["pilot_id"] == "test-pilot"
    assert plan["selection"]["visibility"] == "DEVELOPMENT_ONLY_BLIND"
    assert plan["selection"]["max_selected"] == 1
    assert plan["selection"]["economic_gate"] == "NONE_TECHNICAL_PILOT"
    assert "minimum_profit_pct" not in plan["selection"]
    assert plan["candidates"][0]["_strategy"].name == "CandidateOne.py"
    (root / "candidates" / "CandidateOne.py").write_text("changed\n")
    with pytest.raises(pilot.PilotError, match="hash mismatch"):
        pilot.load_plan(root)


def test_t0_strict_window_v2_accepts_exact_rolling_60_30(tmp_path: Path) -> None:
    root = _plan_root(tmp_path)
    _rewrite_rolling_window(root)

    plan = pilot.load_plan(root)

    assert plan["development_timerange"] == "20260701-20260830"
    assert plan["holdout_timerange"] == "20260830-20260929"


@pytest.mark.parametrize(
    ("development", "holdout"),
    (
        ("20260701-20260829", "20260829-20260928"),
        ("20260701-20260831", "20260831-20260930"),
        ("20260701-20260830", "20260830-20260928"),
        ("20260701-20260830", "20260830-20260930"),
        ("20260701-20260830", "20260831-20260930"),
        ("20260701-20260830", "20260829-20260928"),
    ),
)
def test_t0_strict_window_v2_rejects_duration_and_adjacency_drift(
    tmp_path: Path, development: str, holdout: str
) -> None:
    root = _plan_root(tmp_path)
    _rewrite_rolling_window(root, development=development, holdout=holdout)

    with pytest.raises(pilot.PilotError, match="strict window"):
        pilot.load_plan(root)


def test_t0_window_schema_is_explicit_and_legacy_v1_still_loads(
    tmp_path: Path,
) -> None:
    legacy = _plan_root(tmp_path / "legacy")
    assert pilot.load_plan(legacy)["development_timerange"] == "20260601-20260731"

    unknown = _plan_root(tmp_path / "unknown")
    _rewrite_rolling_window(unknown, schema="freqtrade-lab-okx-window-v3")
    with pytest.raises(pilot.PilotError, match="shape/version"):
        pilot.load_plan(unknown)


def test_t0_positive_development_gate_thresholds_are_frozen(
    tmp_path: Path,
) -> None:
    root = _plan_root(tmp_path)
    _enable_positive_development_gate(
        root,
        minimum_profit_pct=0.01,
        minimum_profit_factor=1.01,
        maximum_drawdown_pct=100,
    )

    selection = pilot.load_plan(root)["selection"]

    assert selection["economic_gate"] == "POSITIVE_DEVELOPMENT_V1"
    assert selection["minimum_profit_pct"] == 0.01
    assert selection["minimum_profit_factor"] == 1.01
    assert selection["maximum_drawdown_pct"] == 100


@pytest.mark.parametrize(
    "field,value,missing,message",
    [
        (None, None, False, "selection rule shape"),
        ("minimum_profit_pct", None, True, "selection rule shape"),
        ("minimum_profit_pct", True, False, "minimum_profit_pct must be a finite number"),
        ("minimum_profit_pct", float("nan"), False, "minimum_profit_pct must be a finite number"),
        ("minimum_profit_factor", float("inf"), False, "minimum_profit_factor must be a finite number"),
        ("minimum_profit_pct", 0.0, False, "minimum_profit_pct must exceed 0"),
        ("minimum_profit_factor", 1.0, False, "minimum_profit_factor must exceed 1"),
        ("maximum_drawdown_pct", -0.01, False, "maximum_drawdown_pct must be a finite number"),
        ("maximum_drawdown_pct", 100.01, False, "maximum_drawdown_pct must not exceed 100"),
    ],
)
def test_t0_positive_development_gate_invalid_thresholds_fail_closed(
    tmp_path: Path,
    field: str | None,
    value: object,
    missing: bool,
    message: str,
) -> None:
    root = _plan_root(tmp_path)
    _enable_positive_development_gate(root)
    plan = json.loads((root / pilot.PLAN).read_bytes())
    if field is None:
        plan["selection"].clear()
    elif missing:
        plan["selection"].pop(field)
    else:
        plan["selection"][field] = value
    (root / pilot.PLAN).write_text(
        json.dumps(plan, allow_nan=True), encoding="utf-8"
    )

    with pytest.raises(pilot.PilotError, match=message):
        pilot.load_plan(root)


@pytest.mark.parametrize(
    "body, message",
    [
        ("dataframe['x'] = dataframe['close'].shift(-1); return dataframe", "shift"),
        ("dataframe['x'] = dataframe['close'].rolling(3, None, True).max(); return dataframe", "rolling"),
        ("dataframe['x'] = dataframe.iloc[-1]; return dataframe", "positional"),
        ("dataframe['x'] = dataframe['close'].max(); return dataframe", "full-sample"),
        ("open('holdout.feather'); return dataframe", "forbidden call"),
    ],
)
def test_t0_causal_gate_rejects_future_ambiguous_source(
    tmp_path: Path, body: str, message: str
) -> None:
    path = tmp_path / "BadCandidate.py"
    path.write_bytes(_candidate_source("BadCandidate", body))

    with pytest.raises(pilot.PilotError, match=message):
        pilot.causal_source(path, "BadCandidate")


def test_t0_selection_is_development_only_and_one_shot(tmp_path: Path) -> None:
    plan = {
        "pilot_id": "test-pilot",
        "_sha256": "a" * 64,
        "development_timerange": "20260601-20260731",
        "selection": {
            "minimum_trades": 20,
            "economic_gate": "NONE_TECHNICAL_PILOT",
        },
    }
    results = [
        {
            "candidate_id": "higher-drawdown",
            "total_trades": 30,
            "profit_pct": 1.0,
            "max_drawdown_pct": 4.0,
            "profit_factor": 2.0,
        },
        {
            "candidate_id": "winner",
            "total_trades": 25,
            "profit_pct": 1.0,
            "max_drawdown_pct": 3.0,
            "profit_factor": 1.2,
        },
        {
            "candidate_id": "too-few-trades",
            "total_trades": 19,
            "profit_pct": 99.0,
            "max_drawdown_pct": 0.1,
            "profit_factor": 99.0,
        },
    ]

    assert pilot.select(tmp_path, plan, results) == "winner"
    receipt = json.loads((tmp_path / pilot.SELECTION).read_bytes())
    assert receipt["holdout_read"] is False
    assert receipt["selected_candidate_id"] == "winner"
    assert receipt["economic_gate"] == "NONE_TECHNICAL_PILOT"
    assert not {
        "minimum_profit_pct",
        "minimum_profit_factor",
        "maximum_drawdown_pct",
    }.intersection(receipt)
    assert not (tmp_path / pilot.HOLDOUT_SEAL).exists()
    with pytest.raises(pilot.PilotError, match="replay"):
        pilot.select(tmp_path, plan, results)


def test_t0_positive_development_gate_requires_every_threshold_and_ranks(
    tmp_path: Path,
) -> None:
    plan = {
        "pilot_id": "test-pilot",
        "_sha256": "a" * 64,
        "development_timerange": "20260601-20260731",
        "selection": {
            "minimum_trades": 20,
            "economic_gate": "POSITIVE_DEVELOPMENT_V1",
            "minimum_profit_pct": 0.5,
            "minimum_profit_factor": 1.1,
            "maximum_drawdown_pct": 5.0,
        },
    }
    results = [
        _development_result("negative-profit", profit_pct=-0.01),
        _development_result("low-profit-factor", profit_factor=1.09),
        _development_result("high-drawdown", max_drawdown_pct=5.01),
        _development_result("too-few-trades", total_trades=19),
        _development_result("exact-thresholds"),
        _development_result(
            "ranked-winner",
            total_trades=21,
            profit_pct=0.75,
            max_drawdown_pct=4.0,
            profit_factor=1.2,
        ),
    ]

    assert pilot.select(tmp_path, plan, results) == "ranked-winner"
    receipt = json.loads((tmp_path / pilot.SELECTION).read_bytes())
    assert receipt["eligible_candidate_ids"] == ["ranked-winner", "exact-thresholds"]
    assert receipt["selected_candidate_id"] == "ranked-winner"
    assert receipt["economic_gate"] == "POSITIVE_DEVELOPMENT_V1"
    assert receipt["minimum_profit_pct"] == 0.5
    assert receipt["minimum_profit_factor"] == 1.1
    assert receipt["maximum_drawdown_pct"] == 5.0


def test_t0_no_development_finalist_stops_before_holdout_side_effects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _plan_root(tmp_path)
    _enable_positive_development_gate(root)
    source = tmp_path / "freqtrade-source"
    source.mkdir()

    def must_not_run(*args: object, **kwargs: object) -> None:
        raise AssertionError("post-selection work must not run without a finalist")

    monkeypatch.setattr(pilot, "verify_data", lambda *args: {"status": "DATA_READY"})
    monkeypatch.setattr(pilot, "materialize_inputs", lambda *args: {})
    monkeypatch.setattr(pilot, "materialize_development_isolation", lambda *args: {"receipt": {}})
    monkeypatch.setattr(pilot, "screen", lambda *args: [_development_result("candidate-one", profit_pct=-0.01)])
    for name in ("init_database", "materialize_selected_input", "run_research_candidate"):
        monkeypatch.setattr(pilot, name, must_not_run)
    monkeypatch.setattr(pilot, "now", lambda: "2026-08-31T00:00:00.000Z")

    assert pilot.main(_main_args(root, source)) == 3

    terminal = json.loads((root / pilot.TERMINAL).read_bytes())
    selection = json.loads((root / pilot.SELECTION).read_bytes())
    assert terminal["status"] == "NO_DEVELOPMENT_FINALIST"
    assert terminal["holdout_opened"] is False
    assert terminal["holdout_open_count"] == terminal["stress_open_count"] == 0
    assert selection["selected_candidate_id"] is None
    assert not (root / pilot.HOLDOUT_AUTHORIZATION).exists()
    assert not (root / "scenario-opens").exists()
    assert not (root / "workspace").exists()


def test_t0_selected_development_replay_must_match_exact_semantics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    view = {"exclusive_stop_utc": "2026-07-31T00:00:00Z", "files": {}}
    screened = [
        {
            "candidate_id": "winner",
            "archive_sha256": "a" * 64,
            "report_semantic_sha256": "b" * 64,
            "scenario_data_view": view,
            "total_trades": 25,
            "profit_pct": 1.25,
            "max_drawdown_pct": 3.5,
            "profit_factor": 1.2,
        }
    ]
    evidence = {
        "candidate_class_name": "CandidateOne",
        "scenarios": [
            {
                "scenario": "DEVELOPMENT",
                "total_trades": 25,
                "profit_pct": 1.25,
                "max_drawdown_pct": 3.5,
                "profit_factor": 1.2,
            }
        ]
    }
    produced = SimpleNamespace(
        bundle_root=tmp_path,
        artifacts=[
            SimpleNamespace(scenario="DEVELOPMENT", archive="development.zip")
        ],
    )
    monkeypatch.setattr(
        pilot,
        "report_metrics",
        lambda *args: {
            "total_trades": 25,
            "profit_pct": 1.25,
            "max_drawdown_pct": 3.5,
            "profit_factor": 1.2,
            "report_semantic_sha256": "b" * 64,
        },
    )
    monkeypatch.setattr(
        pilot,
        "load_json",
        lambda *args: ({"generation": {"scenario_data_view": view}}, b"{}"),
    )

    assert (
        pilot.development_replay_evidence(
            screened, "winner", evidence, produced
        )["status"]
        == "EXACT_REPORT_SEMANTICS_AND_DATA_VIEW_MATCH"
    )
    evidence["scenarios"][0]["profit_pct"] = 1.2501
    with pytest.raises(pilot.PilotError, match="database disagree"):
        pilot.development_replay_evidence(screened, "winner", evidence, produced)


def test_t0_daily_ui_command_binds_exact_isolated_roots(tmp_path: Path) -> None:
    terminal = {
        "database": tmp_path / "workspace with spaces" / "lab.sqlite",
        "bundle_root": tmp_path / "bundle with spaces",
        "frequi_base_url": "http://127.0.0.1:18766",
        "frequi_results_root": tmp_path / "FreqUI results" / "backtest_results",
    }

    command = pilot.shlex.split(pilot.strategy_library_command(terminal))

    assert command[command.index("--artifact-root") + 1] == str(terminal["bundle_root"])
    assert command[command.index("--frequi-base-url") + 1] == terminal["frequi_base_url"]
    assert command[command.index("--frequi-results-root") + 1] == str(
        terminal["frequi_results_root"]
    )


def test_t0_invalid_open_receipt_is_unknown_not_counted(tmp_path: Path) -> None:
    invalid = tmp_path / pilot.HOLDOUT_SEAL
    invalid.mkdir(parents=True)

    state = pilot.failure_open_state(tmp_path, None)

    assert state["holdout_opened"] is None
    assert state["holdout_open_count"] is None
    assert state["stress_open_count"] == 0
    assert state["open_receipt_integrity"] == "UNKNOWN_INVALID_OR_PARTIAL_RECEIPT"


def test_t0_materialized_candidate_hashes_are_rechecked(tmp_path: Path) -> None:
    root = _plan_root(tmp_path)
    plan = pilot.load_plan(root)
    candidate = plan["candidates"][0]
    controls = tmp_path / "controls"
    (controls / "strategies").mkdir(parents=True)
    (controls / "strategies" / "CandidateOne.py").write_bytes(
        candidate["_strategy"].read_bytes()
    )
    (controls / "research-spec.json").write_bytes(candidate["_spec"].read_bytes())

    pilot.verify_candidate_copy(candidate, controls, "test")
    (controls / "research-spec.json").write_text("changed\n", encoding="utf-8")

    with pytest.raises(pilot.PilotError, match="research spec changed"):
        pilot.verify_candidate_copy(candidate, controls, "test")


@pytest.mark.parametrize(
    "display_failure",
    [None, "library", "frequi"],
    ids=["success", "library-unknown", "frequi-unknown"],
)
def test_t0_completed_research_survives_classified_display_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    display_failure: str | None,
) -> None:
    root, source = _mock_pilot(tmp_path, monkeypatch, display_failure=display_failure)

    assert pilot.main(_main_args(root, source)) == 0
    captured = capsys.readouterr()
    terminal = json.loads((root / pilot.TERMINAL).read_bytes())
    assert terminal["status"] == "PILOT_COMPLETED_NO_VERDICT"
    assert terminal["research_claim"] == "NOT_EVALUATED"
    assert terminal["trading_claim"] == "NONE"
    if display_failure is None:
        assert terminal["frequi_results_root"] == str(root / "frequi-results")
    else:
        assert terminal["frequi_results_root"] is None
        assert terminal["frequi_history_visibility"] == "UNKNOWN"
        assert "optional presentation is UNKNOWN" in captured.err


def test_t0_happy_path_order_producer_once_and_complete_terminal_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, source = _mock_pilot(tmp_path, monkeypatch)
    plan = pilot.load_plan(root)
    candidate = plan["candidates"][0]
    scenario_data_view = {
        "exclusive_stop_utc": "2026-07-31T00:00:00Z",
        "files": {"market.feather": {"sha256": "b" * 64}},
    }
    development_results = [
        {
            "candidate_id": "candidate-one",
            "class_name": "CandidateOne",
            "strategy_sha256": candidate["strategy_sha256"],
            "exit_code": 0,
            "scenario_data_view": scenario_data_view,
            "archive": "screened-development.zip",
            "archive_sha256": "c" * 64,
            "report_semantic_sha256": "d" * 64,
            "total_trades": 20,
            "profit_pct": 0.5,
            "max_drawdown_pct": 5.0,
            "profit_factor": 1.1,
        }
    ]
    open_evidence = {
        "holdout_open_count": 1,
        "stress_open_count": 1,
        "receipts": {
            "HOLDOUT": {
                "sha256": "e" * 64,
                "opened_at_utc": "2026-08-31T00:00:00.000Z",
            },
            "HOLDOUT_STRESS": {
                "sha256": "f" * 64,
                "opened_at_utc": "2026-08-31T00:00:00.000Z",
            },
        },
    }
    scenarios = [
        {
            "scenario": scenario,
            "status": "SUCCEEDED",
            "total_trades": 20,
            "profit_pct": 0.5,
            "max_drawdown_pct": 5.0,
            "profit_factor": 1.1,
            "scenario_passed": None,
        }
        for scenario in ("DEVELOPMENT", "HOLDOUT", "HOLDOUT_STRESS")
    ]
    evidence = {
        "research_run_id": "research-run-1",
        "candidate_class_name": "CandidateOne",
        "generation_source": "CODEX",
        "generation_model": None,
        "returned_strategy_count": 1,
        "source_item_index": 0,
        "status": "COMPLETED",
        "verdict": None,
        "release_count": 0,
        "scenarios": scenarios,
    }
    replay = {
        "status": "EXACT_REPORT_SEMANTICS_AND_DATA_VIEW_MATCH",
        "screened_archive_sha256": "c" * 64,
        "screened_report_semantic_sha256": "d" * 64,
        "producer_report_semantic_sha256": "d" * 64,
        "scenario_data_view": scenario_data_view,
        "metrics": {
            label: {"screened": value, "producer_replay": value}
            for label, value in (
                ("total_trades", 20),
                ("profit_pct", 0.5),
                ("max_drawdown_pct", 5.0),
                ("profit_factor", 1.1),
            )
        },
    }
    frequi_receipts = [
        {
            "scenario": scenario,
            "archive": f"{stem}.zip",
            "archive_sha256": archive_sha,
            "metadata": f"{stem}.meta.json",
            "metadata_sha256": metadata_sha,
        }
        for scenario, stem, archive_sha, metadata_sha in (
            (
                "DEVELOPMENT",
                "backtest-result-development-01",
                "1" * 64,
                "2" * 64,
            ),
            (
                "HOLDOUT",
                "backtest-result-holdout-02",
                "3" * 64,
                "4" * 64,
            ),
            (
                "HOLDOUT_STRESS",
                "backtest-result-holdout-stress-03",
                "5" * 64,
                "6" * 64,
            ),
        )
    ]
    original_producer = pilot.run_research_candidate

    def producer(**kwargs: object) -> object:
        assert (root / pilot.HOLDOUT_AUTHORIZATION).is_file()
        assert (root / "scenario-opens").is_dir()
        assert kwargs["scenario_open_receipts"] == {
            "HOLDOUT": root / pilot.HOLDOUT_SEAL,
            "HOLDOUT_STRESS": root / pilot.STRESS_SEAL,
        }
        return original_producer(**kwargs)

    monkeypatch.setattr(pilot, "screen", lambda *args: development_results)
    monkeypatch.setattr(pilot, "run_research_candidate", producer)
    monkeypatch.setattr(pilot, "scenario_open_evidence", lambda *args: open_evidence)
    monkeypatch.setattr(pilot, "database_evidence", lambda *args: evidence)
    monkeypatch.setattr(pilot, "development_replay_evidence", lambda *args: replay)
    monkeypatch.setattr(
        pilot,
        "copy_frequi_results",
        lambda *args: {
            "root": str(root / "frequi-results"),
            "files": frequi_receipts,
        },
    )
    events: list[str] = []
    stages = (
        "verify_data",
        "materialize_inputs",
        "materialize_development_isolation",
        "screen",
        "select",
        "init_database",
        "materialize_selected_input",
        "verify_candidate_copy",
        "run_research_candidate",
        "scenario_open_evidence",
        "database_evidence",
        "development_replay_evidence",
        "validate_strategy_library_database",
        "copy_frequi_results",
    )
    for stage in stages:
        original = getattr(pilot, stage)

        def record(
            *args: object,
            _stage: str = stage,
            _original: object = original,
            **kwargs: object,
        ) -> object:
            events.append(_stage)
            return _original(*args, **kwargs)

        monkeypatch.setattr(pilot, stage, record)

    assert pilot.main(_main_args(root, source)) == 0

    terminal = json.loads((root / pilot.TERMINAL).read_bytes())
    assert events == list(stages)
    assert events.count("run_research_candidate") == 1
    assert terminal == {
        "schema": pilot.SCHEMA,
        "pilot_id": "test-pilot",
        "plan_sha256": plan["_sha256"],
        "status": "PILOT_COMPLETED_NO_VERDICT",
        "data": {"status": "DATA_READY"},
        "development_isolation": {},
        "development_results": development_results,
        "development_replay": replay,
        "selected_candidate_id": "candidate-one",
        "selection_basis": plan["selection"],
        **open_evidence,
        "retry_allowed": False,
        "tuning_after_result": False,
        "manifest_sha256": "a" * 64,
        "bundle_root": str(root / "mock-bundle"),
        "database": str(root / "workspace" / "lab.sqlite"),
        "database_evidence": evidence,
        "frequi_base_url": "http://127.0.0.1:18766",
        "frequi_results_root": str(root / "frequi-results"),
        "frequi_copy_receipts": frequi_receipts,
        "frequi_history_visibility": None,
        "research_claim": "NOT_EVALUATED",
        "trading_claim": "NONE",
        "created_at_utc": "2026-08-31T00:00:00.000Z",
    }


@pytest.mark.parametrize("research_failure", ["database", "unexpected"])
def test_t0_opened_research_failure_remains_blocked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    research_failure: str,
) -> None:
    root, source = _mock_pilot(tmp_path, monkeypatch, research_failure=research_failure)

    with pytest.raises(pilot.PilotError):
        pilot.main(_main_args(root, source))

    terminal = json.loads((root / pilot.TERMINAL).read_bytes())
    assert terminal["status"] == "BLOCKED"
    assert terminal["holdout_open_count"] == terminal["stress_open_count"] == 1


def test_t0_opened_research_failure_with_invalid_receipt_is_unknown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, source = _mock_pilot(
        tmp_path, monkeypatch, research_failure="database"
    )
    original = pilot.run_research_candidate

    def producer_with_invalid_receipt(**kwargs: object) -> object:
        produced = original(**kwargs)
        (root / pilot.HOLDOUT_SEAL).write_text("{}\n", encoding="utf-8")
        return produced

    monkeypatch.setattr(
        pilot, "run_research_candidate", producer_with_invalid_receipt
    )

    with pytest.raises(pilot.PilotError):
        pilot.main(_main_args(root, source))

    terminal = json.loads((root / pilot.TERMINAL).read_bytes())
    assert terminal["status"] == "BLOCKED"
    assert terminal["holdout_opened"] is None
    assert terminal["holdout_open_count"] is None
    assert terminal["stress_open_count"] is None
    assert terminal["open_receipt_integrity"] == "UNKNOWN_INVALID_OR_PARTIAL_RECEIPT"


def test_t0_search_negative_candidate_can_be_parent_but_not_finalist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, source = _search_root(tmp_path)
    candidates = [
        _search_candidate(root, "seed-a", "SeedA", "ema"),
        _search_candidate(root, "seed-b", "SeedB", "rsi"),
        _search_candidate(root, "seed-c", "SeedC", "channel"),
    ]
    _write_search_campaign(root, candidates)
    _patch_search_screen(
        monkeypatch,
        {
            "seed-a": {"total_trades": 40, "profit_pct": -2.0, "max_drawdown_pct": 3.0, "profit_factor": 0.7},
            "seed-b": {"total_trades": 5, "profit_pct": -0.5, "max_drawdown_pct": 2.0, "profit_factor": 0.2},
            "seed-c": {"total_trades": 80, "profit_pct": -4.0, "max_drawdown_pct": 1.0, "profit_factor": 0.9},
        },
    )

    outcome = pilot.screen_search(
        root,
        pilot.load_plan(root, pilot.SEARCH_CAMPAIGN),
        Path(sys.executable),
        source,
    )

    assert outcome["status"] == "SEARCH_ROUND_READY_FOR_CHILDREN"
    assert outcome["brief"]["selected_parent"]["candidate_id"] == "seed-b"
    assert outcome["brief"]["selected_parent"]["search_metrics"][
        "net_profit_after_base_fees_pct"
    ] < 0
    assert "search_finalist" not in outcome["brief"]
    assert not (root / pilot.SEARCH_TERMINAL).exists()
    round_receipt = _search_records(root)[-1]
    assert round_receipt["record_type"] == "ROUND_RECEIPT"
    assert set(round_receipt["brief"]) == {
        "campaign",
        "candidates",
        "frozen_ranking",
        "selected_parent",
    }


def test_t0_search_finalist_gate_is_positive_without_pf_threshold(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, source = _search_root(tmp_path)
    seeds = [
        _search_candidate(root, "seed-a", "SeedA", "ema"),
        _search_candidate(root, "seed-b", "SeedB", "rsi"),
        _search_candidate(root, "seed-c", "SeedC", "channel"),
    ]
    _write_search_campaign(root, seeds)
    metrics = {
        "seed-a": {"total_trades": 40, "profit_pct": -0.2, "max_drawdown_pct": 3.0, "profit_factor": 0.8},
        "seed-b": {"total_trades": 40, "profit_pct": -0.5, "max_drawdown_pct": 2.0, "profit_factor": 0.9},
        "seed-c": {"total_trades": 40, "profit_pct": -1.0, "max_drawdown_pct": 1.0, "profit_factor": 0.95},
    }
    _patch_search_screen(monkeypatch, metrics)
    first = pilot.screen_search(
        root,
        pilot.load_plan(root, pilot.SEARCH_CAMPAIGN),
        Path(sys.executable),
        source,
    )
    parent = _parent_contract(first)
    children = [
        _search_candidate(
            root,
            "child-high-dd",
            "ChildHighDd",
            parent["mechanism"],
            relationship="SINGLE_FACTOR_CHILD",
            changed_factor="ema-period",
            parent_sha256=parent["strategy_sha256"],
        ),
        _search_candidate(
            root,
            "child-finalist",
            "ChildFinalist",
            parent["mechanism"],
            relationship="SINGLE_FACTOR_CHILD",
            changed_factor="adx-period",
            parent_sha256=parent["strategy_sha256"],
        ),
        _search_candidate(
            root,
            "child-zero",
            "ChildZero",
            parent["mechanism"],
            relationship="SINGLE_FACTOR_CHILD",
            changed_factor="entry-cross",
            parent_sha256=parent["strategy_sha256"],
        ),
    ]
    _write_search_campaign(
        root,
        children,
        round_number=2,
        parent=parent,
        previous_receipt_sha256=first["round_receipt_sha256"],
    )
    metrics.update(
        {
            "child-high-dd": {"total_trades": 50, "profit_pct": 5.0, "max_drawdown_pct": 10.01, "profit_factor": 9.0},
            "child-finalist": {"total_trades": 30, "profit_pct": 0.01, "max_drawdown_pct": 10.0, "profit_factor": 0.2},
            "child-zero": {"total_trades": 100, "profit_pct": 0.0, "max_drawdown_pct": 0.1, "profit_factor": 99.0},
        }
    )
    _patch_search_screen(monkeypatch, metrics)

    second = pilot.screen_search(
        root,
        pilot.load_plan(root, pilot.SEARCH_CAMPAIGN),
        Path(sys.executable),
        source,
    )

    terminal = json.loads((root / pilot.SEARCH_TERMINAL).read_bytes())
    assert second["status"] == terminal["status"] == "SEARCH_FINALIST_FROZEN"
    terminal_before = (root / pilot.SEARCH_TERMINAL).read_bytes()
    assert terminal["brief"]["selected_parent"]["candidate_id"] == "child-high-dd"
    assert terminal["search_finalist"]["candidate_id"] == "child-finalist"
    assert terminal["search_finalist"]["search_metrics"]["profit_factor"] == 0.2
    assert terminal["brief"]["campaign"]["budget"]["consumed_total"] == 6
    assert terminal["finalist_gate"] == pilot.SEARCH_GATE_CONTRACT
    assert "minimum_profit_factor" not in terminal["finalist_gate"]
    with pytest.raises(pilot.PilotError, match="terminal receipt already exists"):
        pilot.screen_search(
            root,
            pilot.load_plan(root, pilot.SEARCH_CAMPAIGN),
            Path(sys.executable),
            source,
        )
    assert (root / pilot.SEARCH_TERMINAL).read_bytes() == terminal_before


def test_t0_search_duplicates_and_invalid_source_consume_budget_without_leakage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, source = _search_root(tmp_path)
    valid = _search_candidate(root, "valid", "ValidSeed", "ema")
    duplicate = _search_candidate(root, "duplicate", "DuplicateSeed", "rsi")
    duplicate["strategy_file"] = valid["strategy_file"]
    duplicate["strategy_sha256"] = valid["strategy_sha256"]
    invalid = _search_candidate(
        root, "invalid", "InvalidSeed", "channel", body="dataframe["
    )
    _write_search_campaign(root, [valid, duplicate, invalid])
    _patch_search_screen(
        monkeypatch,
        {
            "valid": {"total_trades": 10, "profit_pct": -1.0, "max_drawdown_pct": 2.0, "profit_factor": 0.5}
        },
    )

    outcome = pilot.screen_search(
        root,
        pilot.load_plan(root, pilot.SEARCH_CAMPAIGN),
        Path(sys.executable),
        source,
    )

    statuses = {
        item["candidate_id"]: item["technical_status"]
        for item in outcome["brief"]["candidates"]
    }
    assert statuses == {"valid": "VALID", "duplicate": "INVALID", "invalid": "INVALID"}
    assert outcome["brief"]["campaign"]["budget"] == {
        "maximum_attempts": 6,
        "consumed_before_round": 0,
        "consumed_this_round": 3,
        "consumed_total": 3,
        "remaining": 3,
    }
    assert len(
        [item for item in _search_records(root) if item["record_type"] == "TRIAL"]
    ) == 3
    serialized = json.dumps(outcome["brief"], sort_keys=True).lower()
    for forbidden in ("acquisition", "validation", "development", "holdout", "stress"):
        assert forbidden not in serialized
    with pytest.raises(pilot.PilotError, match="round 1 already consumed"):
        pilot.screen_search(
            root,
            pilot.load_plan(root, pilot.SEARCH_CAMPAIGN),
            Path(sys.executable),
            source,
        )


@pytest.mark.parametrize(
    "relative",
    (
        "config.json",
        "market_snapshot.json",
        "isolated_tiers_snapshot.json",
        "data/okx/futures/TEST_USDT_USDT-5m-futures.feather",
        "data/okx/futures/TEST_USDT_USDT-1h-mark.feather",
        "data/okx/futures/TEST_USDT_USDT-1h-funding_rate.feather",
    ),
)
def test_t0_search_runner_inputs_are_sha_bound_before_screen(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    relative: str,
) -> None:
    root, source = _search_root(tmp_path)
    _write_search_campaign(
        root, [_search_candidate(root, "seed-a", "SeedA", "ema")]
    )
    target = root / pilot.ACQUISITION / relative
    target.write_bytes(target.read_bytes() + b"changed")

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("a changed Search input must fail before screening")

    monkeypatch.setattr(pilot, "materialize_screening_isolation", forbidden)
    with pytest.raises(pilot.PilotError, match="receipt mismatch"):
        pilot.screen_search(
            root,
            pilot.load_plan(root, pilot.SEARCH_CAMPAIGN),
            Path(sys.executable),
            source,
        )


@pytest.mark.parametrize(
    "mismatch",
    (
        "missing-instrument",
        "empty-instrument",
        "missing-pair",
        "empty-pair",
        "market-id",
        "market-symbol",
    ),
)
def test_t0_search_market_identity_fails_before_attempt_reservation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mismatch: str,
) -> None:
    root, source = _search_root(tmp_path)
    provenance_path = root / pilot.ACQUISITION / "retained-data-provenance.json"
    market_path = root / pilot.ACQUISITION / "market_snapshot.json"
    provenance = json.loads(provenance_path.read_bytes())
    market = json.loads(market_path.read_bytes())
    if mismatch == "missing-instrument":
        provenance["source"].pop("instrument_id")
    elif mismatch == "empty-instrument":
        provenance["source"]["instrument_id"] = ""
    elif mismatch == "missing-pair":
        provenance["source"].pop("pair")
    elif mismatch == "empty-pair":
        provenance["source"]["pair"] = ""
    else:
        market["id" if mismatch == "market-id" else "symbol"] = "MISMATCH"
        _write_json(market_path, market)
        market_bytes = market_path.read_bytes()
        provenance["local_only_files"]["market_snapshot.json"] = {
            "bytes": len(market_bytes),
            "sha256": pilot.digest(market_bytes),
        }
    _write_json(provenance_path, provenance)
    _write_search_campaign(
        root, [_search_candidate(root, "seed-a", "SeedA", "ema")]
    )

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("invalid market identity must fail before screening")

    monkeypatch.setattr(pilot, "materialize_screening_isolation", forbidden)
    with pytest.raises(pilot.PilotError, match="identity|source pair"):
        pilot.screen_search(
            root,
            pilot.load_plan(root, pilot.SEARCH_CAMPAIGN),
            Path(sys.executable),
            source,
        )
    assert not (root / pilot.SEARCH_TRIALS).exists()
    assert not (root / "search-isolation-round-1").exists()


def test_t0_search_isolation_preserves_sha_bound_instrument_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _ = _search_root(tmp_path)
    _write_search_campaign(
        root, [_search_candidate(root, "seed-a", "SeedA", "ema")]
    )

    def create_view(
        source_root: Path,
        destination_root: Path,
        timerange: str,
        expected: dict[str, str],
    ) -> dict[str, object]:
        files = {}
        for relative, sha256 in expected.items():
            destination = destination_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_root / relative, destination)
            files[relative] = {
                "rows": _unit_search_rows(relative),
                "sha256": sha256,
            }
        return {
            "exclusive_stop_utc": "2026-01-31T00:00:00Z",
            "files": files,
        }

    monkeypatch.setattr(pilot, "_create_scenario_data_view", create_view)
    monkeypatch.setattr(pilot, "_search_feather_rows", _unit_search_rows)
    isolation = pilot.materialize_screening_isolation(
        root, pilot.load_plan(root, pilot.SEARCH_CAMPAIGN)
    )
    converted = json.loads(Path(isolation["provenance"]).read_bytes())
    market = json.loads((root / pilot.ACQUISITION / "market_snapshot.json").read_bytes())
    tiers = json.loads(
        (root / pilot.ACQUISITION / "isolated_tiers_snapshot.json").read_bytes()
    )

    assert converted["schema"] == offline_runner.RETAINED_DATA_SCHEMA
    assert converted["source"]["instrument_id"] == "TEST-USDT-SWAP"
    assert converted["source"]["pair"] == "TEST/USDT:USDT"
    assert converted["contract"]["development_timerange"] == "20260101-20260131"
    assert "search_timerange" not in converted["contract"]
    offline_runner._verify_market_inputs(
        market, tiers, pair="TEST/USDT:USDT", provenance=converted
    )


def test_t0_search_batch_is_reserved_before_candidate_processing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, source = _search_root(tmp_path)
    candidates = [
        _search_candidate(root, "seed-a", "SeedA", "ema"),
        _search_candidate(root, "seed-b", "SeedB", "rsi"),
        _search_candidate(root, "seed-c", "SeedC", "channel"),
    ]
    _write_search_campaign(root, candidates)
    monkeypatch.setattr(pilot, "verify_data", lambda *args: {"status": "DATA_READY"})

    def interrupted(*args: object, **kwargs: object) -> None:
        raise pilot.PilotError("injected interruption")

    monkeypatch.setattr(pilot, "_validate_search_candidates", interrupted)
    plan = pilot.load_plan(root, pilot.SEARCH_CAMPAIGN)
    with pytest.raises(pilot.PilotError, match="injected interruption"):
        pilot.screen_search(root, plan, Path(sys.executable), source)

    records = _search_records(root)
    assert [item["record_type"] for item in records] == ["ROUND_STARTED"]
    assert records[0]["attempt_numbers"] == [1, 2, 3]
    with pytest.raises(pilot.PilotError, match="round 1 already consumed"):
        pilot.screen_search(root, plan, Path(sys.executable), source)


def test_t0_completed_round_one_cli_retry_does_not_poison_round_two(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, source = _search_root(tmp_path)
    candidate = _search_candidate(root, "seed-a", "SeedA", "ema")
    _write_search_campaign(root, [candidate])
    _patch_search_screen(
        monkeypatch,
        {
            "seed-a": {
                "total_trades": 30,
                "profit_pct": -0.1,
                "max_drawdown_pct": 1.0,
                "profit_factor": 0.9,
            }
        },
    )
    assert (
        pilot.main(
            [
                "screen-search",
                "--campaign-root",
                str(root),
                "--freqtrade-python",
                sys.executable,
                "--freqtrade-source",
                str(source),
            ]
        )
        == 0
    )

    with pytest.raises(pilot.PilotError, match="round 1 already consumed"):
        pilot.main(
            [
                "screen-search",
                "--campaign-root",
                str(root),
                "--freqtrade-python",
                sys.executable,
                "--freqtrade-source",
                str(source),
            ]
        )
    assert not (root / pilot.SEARCH_TERMINAL).exists()


def test_t0_search_failure_text_cannot_leak_paths_or_later_phase_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, source = _search_root(tmp_path)
    candidate = _search_candidate(root, "seed-a", "SeedA", "ema")
    _write_search_campaign(root, [candidate])
    _patch_search_screen(monkeypatch, {"seed-a": {}})

    def failed_screen(
        unused_root: Path,
        plan: dict[str, object],
        *args: object,
        **kwargs: object,
    ) -> list[dict[str, object]]:
        item = plan["candidates"][0]
        return [
            {
                "candidate_id": item["candidate_id"],
                "class_name": item["class_name"],
                "strategy_sha256": item["strategy_sha256"],
                "technical_status": "FAILED",
                "failure_reason": (
                    f"DEVELOPMENT failed at {root}/acquisition/HOLDOUT/secret; "
                    "Validation and Stress are unavailable"
                ),
            }
        ]

    monkeypatch.setattr(pilot, "screen", failed_screen)
    outcome = pilot.screen_search(
        root,
        pilot.load_plan(root, pilot.SEARCH_CAMPAIGN),
        Path(sys.executable),
        source,
    )

    serialized = (
        json.dumps(outcome["brief"], sort_keys=True)
        + (root / pilot.SEARCH_TRIALS).read_text(encoding="utf-8")
        + (root / pilot.SEARCH_TERMINAL).read_text(encoding="utf-8")
    ).lower()
    assert str(root).lower() not in serialized
    for forbidden in ("acquisition", "validation", "development", "holdout", "stress"):
        assert forbidden not in serialized


def test_t0_search_rejects_source_rows_filtered_at_the_search_stop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, source = _search_root(tmp_path)
    provenance_path = root / pilot.ACQUISITION / "retained-data-provenance.json"
    provenance = json.loads(provenance_path.read_bytes())
    changed_name = "data/okx/futures/TEST_USDT_USDT-5m-futures.feather"
    provenance["local_only_files"][changed_name]["rows"] += 1
    _write_json(provenance_path, provenance)
    _write_search_campaign(
        root, [_search_candidate(root, "seed-a", "SeedA", "ema")]
    )

    def filtered_view(
        source_root: Path,
        destination_root: Path,
        timerange: str,
        expected: dict[str, str],
    ) -> dict[str, object]:
        files = {}
        for relative, sha256 in expected.items():
            destination = destination_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_root / relative, destination)
            source_rows = _unit_search_rows(relative)
            files[relative] = {
                "rows": source_rows - 1 if relative.endswith("-5m-futures.feather") else source_rows,
                "sha256": sha256,
            }
        return {
            "exclusive_stop_utc": "2026-01-31T00:00:00Z",
            "files": files,
        }

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("post-window data must fail before Candidate screening")

    monkeypatch.setattr(pilot, "verify_data", lambda *args: {"status": "DATA_READY"})
    monkeypatch.setattr(pilot, "_create_scenario_data_view", filtered_view)
    monkeypatch.setattr(
        pilot,
        "_search_feather_rows",
        lambda path: _unit_search_rows(path)
        + (1 if str(path).endswith("-5m-futures.feather") else 0),
    )
    monkeypatch.setattr(pilot, "screen", forbidden)
    with pytest.raises(pilot.PilotError, match="post-window data"):
        pilot.screen_search(
            root,
            pilot.load_plan(root, pilot.SEARCH_CAMPAIGN),
            Path(sys.executable),
            source,
        )
    assert not (root / "search-isolation-round-1").exists()


def test_t0_search_ledger_symlink_is_rejected_without_touching_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, source = _search_root(tmp_path)
    _write_search_campaign(
        root, [_search_candidate(root, "seed-a", "SeedA", "ema")]
    )
    _patch_search_screen(monkeypatch, {"seed-a": {}})
    target = tmp_path / "outside-ledger"
    target.write_bytes(b"unchanged\n")
    (root / pilot.SEARCH_TRIALS).symlink_to(target)

    with pytest.raises(pilot.PilotError, match="cannot be opened safely"):
        pilot.screen_search(
            root,
            pilot.load_plan(root, pilot.SEARCH_CAMPAIGN),
            Path(sys.executable),
            source,
        )
    assert target.read_bytes() == b"unchanged\n"


def test_t0_search_config_toctou_fails_before_candidate_screen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, source = _search_root(tmp_path)
    _write_search_campaign(
        root, [_search_candidate(root, "seed-a", "SeedA", "ema")]
    )

    def mutate_after_preflight(
        campaign_root: Path,
        plan: dict[str, object],
        **kwargs: object,
    ) -> dict[str, object]:
        config = campaign_root / pilot.ACQUISITION / "config.json"
        config.write_bytes(config.read_bytes() + b"changed")
        isolation_root = campaign_root / f"search-isolation-round-{plan['round']}"
        isolation_root.mkdir()
        return {
            "receipt": {},
            "provenance": isolation_root / "retained-data-provenance.json",
            "data_dir": isolation_root,
        }

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("changed config must fail before Candidate screening")

    monkeypatch.setattr(
        pilot, "materialize_screening_isolation", mutate_after_preflight
    )
    monkeypatch.setattr(
        pilot,
        "_verify_search_output_dates",
        lambda *args: dict(pilot.FROZEN_SEARCH_ROWS),
    )
    monkeypatch.setattr(pilot, "screen", forbidden)
    with pytest.raises(pilot.PilotError, match="config changed after preflight"):
        pilot.screen_search(
            root,
            pilot.load_plan(root, pilot.SEARCH_CAMPAIGN),
            Path(sys.executable),
            source,
        )
    assert not (root / "search-isolation-round-1").exists()
    assert not (root / "search-inputs-round-1").exists()


def test_t0_search_runtime_inputs_are_cleaned_after_screen_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, source = _search_root(tmp_path)
    _write_search_campaign(
        root, [_search_candidate(root, "seed-a", "SeedA", "ema")]
    )
    monkeypatch.setattr(pilot, "verify_data", lambda *args: {"status": "DATA_READY"})

    def isolation(
        campaign_root: Path,
        plan: dict[str, object],
        **kwargs: object,
    ) -> dict[str, object]:
        isolation_root = campaign_root / f"search-isolation-round-{plan['round']}"
        isolation_root.mkdir()
        return {
            "receipt": {},
            "provenance": isolation_root / "retained-data-provenance.json",
            "data_dir": isolation_root,
        }

    def failed_screen(*args: object, **kwargs: object) -> None:
        assert (root / "search-isolation-round-1").is_dir()
        assert (root / "search-inputs-round-1").is_dir()
        raise pilot.PilotError("injected screen failure")

    monkeypatch.setattr(pilot, "materialize_screening_isolation", isolation)
    monkeypatch.setattr(pilot, "screen", failed_screen)
    with pytest.raises(pilot.PilotError, match="injected screen failure"):
        pilot.screen_search(
            root,
            pilot.load_plan(root, pilot.SEARCH_CAMPAIGN),
            Path(sys.executable),
            source,
        )
    assert not (root / "search-isolation-round-1").exists()
    assert not (root / "search-inputs-round-1").exists()


def test_t1_search_two_round_six_candidate_smoke_has_no_later_phase_side_effects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, source = _search_root(tmp_path)

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("Search must not enter database or producer paths")

    for name in ("init_database", "run_research_candidate", "materialize_selected_input"):
        monkeypatch.setattr(pilot, name, forbidden)

    def create_view(
        source_root: Path,
        destination_root: Path,
        timerange: str,
        expected: dict[str, str],
    ) -> dict[str, object]:
        files = {}
        for relative, sha256 in expected.items():
            destination = destination_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_root / relative, destination)
            files[relative] = {
                "sha256": sha256,
                "rows": _unit_search_rows(relative),
            }
        return {"exclusive_stop_utc": "2026-01-31T00:00:00Z", "files": files}

    def isolated_screen(
        campaign_root: Path,
        plan: dict[str, object],
        inputs: dict[str, Path],
        python: Path,
        source_root: Path,
        isolation: dict[str, object],
        **kwargs: object,
    ) -> list[dict[str, object]]:
        provenance = json.loads(Path(isolation["provenance"]).read_bytes())
        first_input = next(iter(inputs.values()))
        offline_runner._verify_dependency_versions(
            provenance, offline_runner.SUPPORTED_DEPENDENCIES
        )
        offline_runner._verify_data_provenance(
            provenance,
            scenario="DEVELOPMENT",
            timerange=plan["search_timerange"],
            pair="TEST/USDT:USDT",
            data_dir=Path(isolation["data_dir"]),
            market_snapshot=first_input / "market_snapshot.json",
            leverage_tiers=first_input / "isolated_tiers_snapshot.json",
        )
        (campaign_root / f"search-results-round-{plan['round']}").mkdir()
        return [
            {
                "candidate_id": candidate["candidate_id"],
                "class_name": candidate["class_name"],
                "strategy_sha256": candidate["strategy_sha256"],
                "technical_status": "VALID",
                "failure_reason": None,
                "total_trades": 35,
                "profit_pct": 0.25 if candidate["candidate_id"] == "child-a" else -0.25,
                "max_drawdown_pct": 5.0,
                "profit_factor": 0.8,
            }
            for candidate in plan["candidates"]
        ]

    monkeypatch.setattr(pilot, "_create_scenario_data_view", create_view)
    monkeypatch.setattr(pilot, "_search_feather_rows", _unit_search_rows)
    monkeypatch.setattr(
        pilot,
        "_verify_search_output_dates",
        lambda *args: dict(pilot.FROZEN_SEARCH_ROWS),
    )
    monkeypatch.setattr(pilot, "screen", isolated_screen)
    seeds = [
        _search_candidate(root, "seed-a", "SeedA", "ema"),
        _search_candidate(root, "seed-b", "SeedB", "rsi"),
        _search_candidate(root, "seed-c", "SeedC", "channel"),
    ]
    _write_search_campaign(root, seeds)
    first = pilot.screen_search(
        root,
        pilot.load_plan(root, pilot.SEARCH_CAMPAIGN),
        Path(sys.executable),
        source,
    )
    parent = _parent_contract(first)
    children = [
        _search_candidate(
            root,
            candidate_id,
            class_name,
            parent["mechanism"],
            relationship="SINGLE_FACTOR_CHILD",
            changed_factor=factor,
            parent_sha256=parent["strategy_sha256"],
        )
        for candidate_id, class_name, factor in (
            ("child-a", "ChildA", "period-a"),
            ("child-b", "ChildB", "period-b"),
            ("child-c", "ChildC", "period-c"),
        )
    ]
    _write_search_campaign(
        root,
        children,
        round_number=2,
        parent=parent,
        previous_receipt_sha256=first["round_receipt_sha256"],
    )

    second = pilot.screen_search(
        root,
        pilot.load_plan(root, pilot.SEARCH_CAMPAIGN),
        Path(sys.executable),
        source,
    )

    assert second["status"] == "SEARCH_FINALIST_FROZEN"
    records = _search_records(root)
    assert len([item for item in records if item["record_type"] == "TRIAL"]) == 6
    assert sum(
        len(item["attempt_numbers"])
        for item in records
        if item["record_type"] == "ROUND_STARTED"
    ) == 6
    for name in (
        "workspace",
        "selected-input",
        "scenario-opens",
        pilot.HOLDOUT_AUTHORIZATION,
        pilot.TERMINAL,
    ):
        assert not (root / name).exists()
    assert not list(root.rglob("*.sqlite"))
    assert not (root / "search-isolation-round-1").exists()
    assert not (root / "search-isolation-round-2").exists()
    assert not (root / "search-inputs-round-1").exists()
    assert not (root / "search-inputs-round-2").exists()
    assert (root / "search-results-round-1").is_dir()
    assert (root / "search-results-round-2").is_dir()
    assert (root / pilot.SEARCH_TERMINAL).is_file()
