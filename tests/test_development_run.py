"""T0/T1 contracts for the one-scenario DEVELOPMENT slice."""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from lab import codex_generation, development_run
from lab.database import get_connection, init_database
from lab import bounded_research as pilot
from scripts import run_freqtrade_backtest as runner_module


NOW = "2026-01-01T00:00:00.000Z"
ROLLING_DEVELOPMENT_TIMERANGE = "20260401-20260531"
ROLLING_HOLDOUT_TIMERANGE = "20260531-20260630"

BOUNDED_SOURCE = """import talib.abstract as ta
from pandas import DataFrame
from technical import qtpylib
from freqtrade.strategy import IStrategy

class BoundedCandidate(IStrategy):
    INTERFACE_VERSION = 3
    timeframe = "5m"
    can_short = True
    startup_candle_count = 20
    process_only_new_candles = True
    minimal_roi = {"0": 0.0}
    stoploss = -0.02

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        return dataframe
"""


def _seed_development_run(
    tmp_path: Path,
    *,
    status: str = "SUCCEEDED",
    total_trades: int | None = 30,
    profit_pct: float | None = 0.5,
    profit_factor: float | None = 1.1,
    max_drawdown_pct: float | None = 5.0,
) -> tuple[Path, str]:
    database = tmp_path / f"lab-{uuid4()}.sqlite"
    init_database(database)
    profile_id = str(uuid4())
    generation_id = str(uuid4())
    candidate_id = str(uuid4())
    research_run_id = str(uuid4())
    execution_id = str(uuid4())
    snapshot = {
        "schema": development_run.DEVELOPMENT_CONTRACT_SCHEMA,
        "pipeline_version": development_run.DEVELOPMENT_PIPELINE_VERSION,
        "freqtrade_version": "2026.7",
        "scenario": "DEVELOPMENT",
        "gate": {
            "version": development_run.DEVELOPMENT_GATE_VERSION,
            **development_run.EXPECTED_GATE,
        },
        "holdout": "SEALED_UNREAD",
        "holdout_stress": "SEALED_UNREAD",
    }
    checks = {
        "candidate_binding": "PASSED",
        "security_gate": "PASSED",
        "development_data": "PHYSICALLY_ISOLATED",
        "development_gate": "PENDING",
        "next_phase": "DEVELOPMENT_GATE",
        "holdout": "SEALED_UNREAD",
        "holdout_stress": "SEALED_UNREAD",
    }
    with get_connection(database) as connection:
        connection.execute(
            """
            INSERT INTO research_profiles (
                id, name, domain, exchange, trading_mode, margin_mode,
                pairs_json, timeframe, detail_timeframe, history_start_date,
                smoke_days, holdout_days, starting_balance, stake_amount,
                max_open_trades, taker_fee_rate, stress_fee_multiplier,
                max_drawdown_pct, min_development_trades, min_holdout_trades,
                min_profit_factor, created_at, updated_at
            ) VALUES (?, ?, 'OKX_CRYPTO_PERP', 'okx', 'futures', 'isolated',
                      '["ADA/USDT:USDT"]', '5m', NULL, '2026-01-01',
                      7, 30, 1000.0, 100.0, 1, 0.0005, 2.0,
                      5.0, 30, 30, 1.1, ?, ?)
            """,
            (profile_id, f"profile-{profile_id}", NOW, NOW),
        )
        connection.execute(
            """
            INSERT INTO generation_runs (
                id, research_profile_id, source, status, request_json,
                returned_strategy_count, started_at, finished_at,
                created_at, updated_at
            ) VALUES (?, ?, 'MANUAL', 'COMPLETED', '{}', 1, ?, ?, ?, ?)
            """,
            (generation_id, profile_id, NOW, NOW, NOW, NOW),
        )
        connection.execute(
            """
            INSERT INTO candidates (
                id, generation_run_id, source_item_index, display_name,
                class_name, timeframe, code_text, code_sha256,
                metadata_json, created_at, updated_at
            ) VALUES (?, ?, 0, 'Bounded Candidate', 'BoundedCandidate', '5m',
                      'class BoundedCandidate: pass', ?, '{}', ?, ?)
            """,
            (candidate_id, generation_id, uuid4().hex * 2, NOW, NOW),
        )
        connection.execute(
            """
            INSERT INTO research_runs (
                id, candidate_id, research_profile_id, trigger_type, status,
                stage, verdict, pipeline_version, freqtrade_version,
                input_snapshot_json, checks_json, run_dir,
                rejection_reasons_json, created_at, started_at
            ) VALUES (?, ?, ?, 'MANUAL', 'RUNNING', 'DEVELOPMENT_BACKTEST',
                      NULL, ?, '2026.7', ?, ?, '/private/run-dir', '[]', ?, ?)
            """,
            (
                research_run_id,
                candidate_id,
                profile_id,
                development_run.DEVELOPMENT_PIPELINE_VERSION,
                json.dumps(snapshot),
                json.dumps(checks),
                NOW,
                NOW,
            ),
        )
        connection.execute(
            """
            INSERT INTO backtest_executions (
                id, research_run_id, scenario, status, sequence,
                timerange_start, timerange_end, timeframe, detail_timeframe,
                fee_rate, fee_multiplier, command_json, config_path,
                strategy_path, result_archive_path, stdout_path, stderr_path,
                return_code, total_trades, profit_pct, max_drawdown_pct,
                win_rate, profit_factor, sharpe, sortino, calmar,
                long_profit_pct, short_profit_pct, metrics_json,
                scenario_passed, created_at, started_at
            ) VALUES (?, ?, 'DEVELOPMENT', ?, 1,
                      '2026-06-01T00:00:00Z', '2026-07-30T23:55:00Z',
                      '5m', NULL, 0.0005, 1.0, '{}',
                      '/private/config.json', '/private/strategy.py',
                      '/private/result.zip', '/private/stdout.log',
                      '/private/stderr.log', 0, ?, ?, ?, 0.55, ?,
                      0.2, 0.3, 0.4, 0.6, -0.1, '{"raw":"must-clear"}',
                      NULL, ?, ?)
            """,
            (
                execution_id,
                research_run_id,
                status,
                total_trades,
                profit_pct,
                max_drawdown_pct,
                profit_factor,
                NOW,
                NOW,
            ),
        )
        connection.commit()
    return database, research_run_id


def _approved_candidate_database(
    tmp_path: Path,
    *,
    min_development_trades: int = 30,
    holdout_days: int = 30,
    pair: str = "ADA/USDT:USDT",
    timeframe: str = "5m",
) -> tuple[Path, str]:
    database = tmp_path / f"approved-{uuid4()}.sqlite"
    init_database(database)
    profile_id = str(uuid4())
    generation_id = str(uuid4())
    with get_connection(database) as connection:
        connection.execute(
            """
            INSERT INTO research_profiles (
                id, name, domain, exchange, trading_mode, margin_mode,
                pairs_json, timeframe, detail_timeframe, history_start_date,
                smoke_days, holdout_days, starting_balance, stake_amount,
                max_open_trades, taker_fee_rate, stress_fee_multiplier,
                max_drawdown_pct, min_development_trades, min_holdout_trades,
                min_profit_factor, created_at, updated_at
            ) VALUES (?, ?, 'OKX_CRYPTO_PERP', 'okx', 'futures', 'isolated',
                      ?, ?, NULL, '2026-01-01',
                      7, ?, 1000.0, 100.0, 1, 0.0005, 2.0,
                      5.0, ?, 30, 1.1, ?, ?)
            """,
            (
                profile_id,
                f"approved-profile-{profile_id}",
                json.dumps([pair], separators=(",", ":")),
                timeframe,
                holdout_days,
                min_development_trades,
                NOW,
                NOW,
            ),
        )
        connection.commit()
    request = codex_generation.validate_generation_request(
        {
            "profile_id": profile_id,
            "idea": "Test one frozen bounded Candidate.",
            "strategy_family": "trend",
            "expected_failure_mode": "Sideways markets may whipsaw.",
        }
    )
    prepared = codex_generation.start_generation(
        database,
        generation_id,
        request,
        model="fixed-test-model",
        started_at=NOW,
    )
    source = BOUNDED_SOURCE.replace('timeframe = "5m"', f'timeframe = "{timeframe}"')
    output = json.dumps(
        {
            "display_name": "Bounded Candidate",
            "class_name": "BoundedCandidate",
            "code_text": source,
        },
        separators=(",", ":"),
    ).encode()
    candidate_id = codex_generation.complete_generation(
        database,
        prepared,
        codex_generation.parse_candidate_output(output, timeframe=timeframe),
        raw_output=output,
        jsonl_summary={"event_count": 4, "tool_event_count": 0},
        finished_at=NOW,
    )
    codex_generation.review_generation(
        database,
        generation_id,
        "APPROVED",
        decided_at=NOW,
    )
    return database, candidate_id


def _canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _timerange_datetimes(value: str) -> tuple[datetime, datetime]:
    start, stop = (
        datetime.strptime(part, "%Y%m%d").replace(tzinfo=timezone.utc)
        for part in value.split("-", 1)
    )
    return start, stop


def _frozen_capability_fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    pair: str = "ADA/USDT:USDT",
    instrument_id: str = "ADA-USDT-SWAP",
    timeframe: str = "5m",
    profile_contract: dict[str, object] | None = None,
) -> tuple[Path, Path, Path]:
    pilot = tmp_path / "pilot"
    acquisition = pilot / "acquisition"
    isolation = pilot / "development-isolation"
    data_stem = pair.split("/", 1)[0]
    data_file = isolation / "data" / "okx" / "futures" / f"{data_stem}-{timeframe}.feather"
    source = tmp_path / "freqtrade-source"
    python = tmp_path / "freqtrade-python"
    acquisition.mkdir(parents=True)
    data_file.parent.mkdir(parents=True)
    source.mkdir()
    python.write_text("#!/bin/sh\nexit 0\n")
    python.chmod(0o700)

    if profile_contract is None:
        profile = None
        development_timerange = "20260601-20260731"
        holdout_timerange = "20260731-20260830"
        data_start = datetime(2026, 5, 31, 22, tzinfo=timezone.utc)
        window_schema = "freqtrade-lab-okx-window-v1"
    else:
        profile = dict(profile_contract["profile_snapshot"])
        development_timerange = str(profile_contract["development_timerange"])
        development_start, development_stop = _timerange_datetimes(
            development_timerange
        )
        holdout_stop = development_stop + timedelta(days=int(profile["holdout_days"]))
        holdout_timerange = (
            f"{development_stop:%Y%m%d}-{holdout_stop:%Y%m%d}"
        )
        step = timedelta(days=1) if timeframe == "1d" else timedelta(minutes=5)
        data_start = development_start - step * int(profile_contract["pre_roll_candles"])
        window_schema = "freqtrade-lab-okx-window-v2"
    development_start, development_stop = _timerange_datetimes(development_timerange)
    _, holdout_stop = _timerange_datetimes(holdout_timerange)
    window_bytes = _canonical(
        {
            "schema": window_schema,
            "data_start_utc": data_start.isoformat().replace("+00:00", "Z"),
            "development_start_utc": development_start.isoformat().replace("+00:00", "Z"),
            "holdout_start_utc": development_stop.isoformat().replace("+00:00", "Z"),
            "end_exclusive_utc": holdout_stop.isoformat().replace("+00:00", "Z"),
        }
    )
    (pilot / "window-spec.json").write_bytes(window_bytes)
    plan = {
        "freqtrade_version": development_run.SUPPORTED_FREQTRADE_VERSION,
        "window_spec_sha256": hashlib.sha256(window_bytes).hexdigest(),
        "development_timerange": development_timerange,
        "holdout_timerange": holdout_timerange,
        "selection": {
            "economic_gate": development_run.DEVELOPMENT_GATE_VERSION,
            **development_run.EXPECTED_GATE,
            **(
                {}
                if profile_contract is None
                else {
                    key: profile_contract["finalist_gate"][key]
                    for key in (
                        "minimum_trades",
                        "minimum_profit_factor",
                        "maximum_drawdown_pct",
                    )
                }
            ),
            "max_selected": 1,
            "visibility": "DEVELOPMENT_ONLY_BLIND",
            "candidate_execution_failure": "STOP",
        },
    }
    (pilot / "pilot-spec.json").write_bytes(_canonical(plan))
    config = {
        "max_open_trades": 1 if profile is None else profile["max_open_trades"],
        "stake_currency": "USDT",
        "stake_amount": 100.0 if profile is None else profile["stake_amount"],
        "tradable_balance_ratio": 0.99,
        "fiat_display_currency": "USD",
        "dry_run": True,
        "dry_run_wallet": 1000.0 if profile is None else profile["starting_balance"],
        "cancel_open_orders_on_exit": False,
        "trading_mode": "futures",
        "margin_mode": "isolated",
        "timeframe": timeframe,
        "fee": 0.0005 if profile is None else profile["taker_fee_rate"],
        "unfilledtimeout": {
            "entry": 10,
            "exit": 30,
            "exit_timeout_count": 0,
            "unit": "minutes",
        },
        "entry_pricing": {
            "price_side": "same",
            "use_order_book": True,
            "order_book_top": 1,
        },
        "exit_pricing": {
            "price_side": "same",
            "use_order_book": True,
            "order_book_top": 1,
        },
        "exchange": {
            "name": "okx",
            "enable_ws": False,
            "pair_whitelist": [pair],
            "pair_blacklist": [],
        },
        "pairlists": [{"method": "StaticPairList"}],
        "strategy": "PilotPlaceholder",
        "dataformat_ohlcv": "feather",
        "disableparamexport": True,
        "backtest_cache": "none",
    }
    config_bytes = _canonical(config)
    (acquisition / "config.json").write_bytes(config_bytes)
    market = _canonical(
        {
            "id": instrument_id,
            "symbol": pair,
            "active": True,
            "contract": True,
            "swap": True,
            "linear": True,
            "inverse": False,
            "type": "swap",
        }
    )
    tiers = _canonical([{"symbol": pair}])
    candles = b"development-only\n"
    (acquisition / "market_snapshot.json").write_bytes(market)
    (acquisition / "isolated_tiers_snapshot.json").write_bytes(tiers)
    data_file.write_bytes(candles)
    source_provenance = {
        "source": {
            "host": "www.okx.com",
            "authentication": "none",
            "pair": pair,
            "instrument_id": instrument_id,
        },
        "contract": {"config": "config.json"},
        "files": {
            "config.json": {
                "bytes": len(config_bytes),
                "sha256": hashlib.sha256(config_bytes).hexdigest(),
            }
        },
    }
    if profile_contract is not None:
        from lab import bounded_research as bounded_pilot

        source_provenance["source_acquisition"] = {
            "provenance_sha256": "1" * 64,
            "retrieval_receipt_sha256": "2" * 64,
            "data_sha256": {
                name: str(index) * 64
                for index, name in enumerate(
                    bounded_pilot._search_data_names(pair, timeframe).values(),
                    start=3,
                )
            },
        }
    source_provenance_bytes = _canonical(source_provenance)
    (acquisition / "retained-data-provenance.json").write_bytes(
        source_provenance_bytes
    )
    isolation_provenance = {
        "schema": "freqtrade-lab-retained-okx-data-v1",
        "contract": {
            "timeframe": timeframe,
            "development_timerange": development_timerange,
            "market_snapshot": "market_snapshot.json",
            "leverage_tiers": "isolated_tiers_snapshot.json",
        },
        "source": {
            "host": "www.okx.com",
            "authentication": "none",
            "pair": pair,
            "instrument_id": instrument_id,
        },
        "freqtrade": {
            "version": development_run.SUPPORTED_FREQTRADE_VERSION,
            "tag": development_run.SUPPORTED_FREQTRADE_VERSION,
            "commit": development_run.SUPPORTED_FREQTRADE_COMMIT,
        },
        "local_only_files": {
            "market_snapshot.json": {
                "bytes": len(market),
                "sha256": hashlib.sha256(market).hexdigest(),
            },
            "isolated_tiers_snapshot.json": {
                "bytes": len(tiers),
                "sha256": hashlib.sha256(tiers).hexdigest(),
            },
            f"data/okx/futures/{data_stem}-{timeframe}.feather": {
                "bytes": len(candles),
                "sha256": hashlib.sha256(candles).hexdigest(),
            },
        },
        "development_isolation": {
            "holdout_values_present": False,
            "timerange": development_timerange,
            "exclusive_stop_utc": development_stop.isoformat().replace("+00:00", "Z"),
            "source_provenance_sha256": hashlib.sha256(
                source_provenance_bytes
            ).hexdigest(),
        },
    }
    (isolation / "retained-data-provenance.json").write_bytes(
        _canonical(isolation_provenance)
    )

    monkeypatch.setattr(development_run, "_verify_python", lambda _python: None)

    def git_value(_source: Path, *arguments: str) -> str:
        if arguments == ("rev-parse", "HEAD"):
            return development_run.SUPPORTED_FREQTRADE_COMMIT
        if arguments == ("rev-parse", "HEAD^{tree}"):
            return development_run.SUPPORTED_FREQTRADE_TREE
        if arguments == ("describe", "--exact-match", "--tags", "HEAD"):
            return development_run.SUPPORTED_FREQTRADE_VERSION
        if arguments == ("status", "--porcelain=v1", "--untracked-files=all"):
            return ""
        raise AssertionError(arguments)

    monkeypatch.setattr(development_run, "_git_value", git_value)
    return pilot, python, source


def _rewrite_source_provenance(
    pilot: Path, source_provenance: dict[str, object]
) -> None:
    source_bytes = _canonical(source_provenance)
    (pilot / "acquisition" / "retained-data-provenance.json").write_bytes(
        source_bytes
    )
    isolation_path = pilot / "development-isolation" / "retained-data-provenance.json"
    isolation = json.loads(isolation_path.read_text())
    isolation["development_isolation"]["source_provenance_sha256"] = hashlib.sha256(
        source_bytes
    ).hexdigest()
    isolation_path.write_bytes(_canonical(isolation))


def _configure_rolling_window_fixture(
    pilot: Path,
    *,
    development_timerange: str = ROLLING_DEVELOPMENT_TIMERANGE,
    holdout_timerange: str = ROLLING_HOLDOUT_TIMERANGE,
) -> None:
    """Upgrade the compact legacy fixture to one fully bound rolling v2 window."""
    development_start, development_stop = _timerange_datetimes(
        development_timerange
    )
    holdout_start, holdout_stop = _timerange_datetimes(holdout_timerange)
    window = {
        "schema": "freqtrade-lab-okx-window-v2",
        "data_start_utc": (
            development_start - timedelta(hours=2)
        ).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "development_start_utc": development_start.strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
        "holdout_start_utc": holdout_start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "end_exclusive_utc": holdout_stop.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    window_bytes = _canonical(window)
    (pilot / "window-spec.json").write_bytes(window_bytes)

    plan_path = pilot / "pilot-spec.json"
    plan = json.loads(plan_path.read_text())
    plan.update(
        {
            "development_timerange": development_timerange,
            "holdout_timerange": holdout_timerange,
            "window_spec_sha256": hashlib.sha256(window_bytes).hexdigest(),
            "stress_fee_multiplier": 2.0,
            "holdout_policy": {
                "max_open_count": 1,
                "retry_after_open": False,
                "tune_after_result": False,
            },
        }
    )
    plan_path.write_bytes(_canonical(plan))

    isolation_path = (
        pilot / "development-isolation" / "retained-data-provenance.json"
    )
    isolation = json.loads(isolation_path.read_text())
    isolation["contract"]["development_timerange"] = development_timerange
    isolation["development_isolation"].update(
        {
            "timerange": development_timerange,
            "exclusive_stop_utc": development_stop.isoformat().replace(
                "+00:00", "Z"
            ),
        }
    )
    isolation_path.write_bytes(_canonical(isolation))

    acquisition = pilot / "acquisition"
    isolated_data = next(
        (pilot / "development-isolation" / "data" / "okx").rglob("*.feather")
    )
    full_data = acquisition / "data" / "okx" / isolated_data.relative_to(
        pilot / "development-isolation" / "data" / "okx"
    )
    full_data.parent.mkdir(parents=True, exist_ok=True)
    full_data.write_bytes(isolated_data.read_bytes() + b"holdout-only\n")

    source_path = acquisition / "retained-data-provenance.json"
    source = json.loads(source_path.read_text())
    source["contract"].update(
        {
            "data_dir": "data/okx",
            "market_snapshot": "market_snapshot.json",
            "leverage_tiers": "isolated_tiers_snapshot.json",
            "development_timerange": development_timerange,
            "holdout_timerange": holdout_timerange,
            "timeframe": "5m",
        }
    )
    local_paths = (
        acquisition / "market_snapshot.json",
        acquisition / "isolated_tiers_snapshot.json",
        full_data,
    )
    source["local_only_files"] = {
        path.relative_to(acquisition).as_posix(): {
            "bytes": len(path.read_bytes()),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for path in local_paths
    }
    _rewrite_source_provenance(pilot, source)


def _configure_legacy_window_fixture(
    pilot: Path,
    *,
    holdout_timerange: str,
) -> None:
    """Bind a non-default legacy v1 Holdout span without upgrading to v2."""
    _configure_rolling_window_fixture(
        pilot,
        development_timerange="20260601-20260731",
        holdout_timerange=holdout_timerange,
    )
    window_path = pilot / "window-spec.json"
    window = json.loads(window_path.read_text())
    window["schema"] = "freqtrade-lab-okx-window-v1"
    window_bytes = _canonical(window)
    window_path.write_bytes(window_bytes)
    plan_path = pilot / "pilot-spec.json"
    plan = json.loads(plan_path.read_text())
    plan["window_spec_sha256"] = hashlib.sha256(window_bytes).hexdigest()
    plan_path.write_bytes(_canonical(plan))


def _rewrite_pilot_config(pilot: Path, config: dict[str, object]) -> None:
    config_bytes = _canonical(config)
    (pilot / "acquisition" / "config.json").write_bytes(config_bytes)
    provenance_path = pilot / "acquisition" / "retained-data-provenance.json"
    provenance = json.loads(provenance_path.read_text())
    provenance["files"]["config.json"] = {
        "bytes": len(config_bytes),
        "sha256": hashlib.sha256(config_bytes).hexdigest(),
    }
    _rewrite_source_provenance(pilot, provenance)


def test_t0_missing_runtime_capability_is_blocked_data() -> None:
    capability = development_run.freeze_development_capability(None, None, None)

    assert capability.status == "BLOCKED_DATA"
    public = capability.public()
    assert public["status"] == "BLOCKED_DATA"
    assert public["freqtrade_version"] is None
    assert public["holdout"] == "SEALED_UNREAD"
    assert public["holdout_stress"] == "SEALED_UNREAD"

    profile_capability = development_run.freeze_development_capability(
        None, None, None, profile_contract={}
    )
    assert profile_capability.public()["economic_gate"] is None


def test_t0_freeze_binds_pilot_config_to_acquisition_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pilot, python, source = _frozen_capability_fixture(tmp_path, monkeypatch)

    capability = development_run.freeze_development_capability(pilot, python, source)

    assert capability.status == "READY"
    assert capability.config_sha256 == hashlib.sha256(
        (pilot / "acquisition" / "config.json").read_bytes()
    ).hexdigest()
    assert capability.pair == "ADA/USDT:USDT"
    assert capability.instrument_id == "ADA-USDT-SWAP"


def test_t1_rolling_v2_freeze_and_prepare_derive_60_30_boundaries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pilot, python, source = _frozen_capability_fixture(
        tmp_path / "capability", monkeypatch
    )
    _configure_rolling_window_fixture(pilot)

    capability = development_run.freeze_development_capability(
        pilot, python, source
    )

    assert capability.status == "READY"
    assert capability.development_timerange == ROLLING_DEVELOPMENT_TIMERANGE
    database, candidate_id = _approved_candidate_database(tmp_path / "database")
    research_run_id = str(uuid4())
    run_dir = tmp_path / "runtime" / research_run_id
    run_dir.mkdir(parents=True)
    development_run.prepare_development_run(
        database,
        run_dir,
        candidate_id,
        capability,
        research_run_id=research_run_id,
        now=NOW,
    )

    with get_connection(database, read_only=True) as connection:
        run = connection.execute(
            "SELECT input_snapshot_json FROM research_runs WHERE id=?",
            (research_run_id,),
        ).fetchone()
        execution = connection.execute(
            "SELECT timerange_start,timerange_end FROM backtest_executions "
            "WHERE research_run_id=? AND scenario='DEVELOPMENT'",
            (research_run_id,),
        ).fetchone()
    snapshot = json.loads(run["input_snapshot_json"])
    assert snapshot["timerange"] == ROLLING_DEVELOPMENT_TIMERANGE
    assert snapshot["exclusive_stop_utc"] == "2026-05-31T00:00:00Z"
    assert tuple(execution) == (
        "2026-04-01T00:00:00Z",
        "2026-05-30T23:55:00Z",
    )
    provenance = json.loads(
        (
            run_dir / "development-input" / "retained-data-provenance.json"
        ).read_text()
    )
    assert provenance["contract"]["development_timerange"] == (
        ROLLING_DEVELOPMENT_TIMERANGE
    )
    assert provenance["development_isolation"]["exclusive_stop_utc"] == (
        "2026-05-31T00:00:00Z"
    )
    assert "holdout_timerange" not in provenance["contract"]


@pytest.mark.parametrize(
    "mutation",
    (
        "missing_window",
        "missing_hash",
        "wrong_hash",
        "legacy_schema",
        "boundary_drift",
    ),
)
def test_t0_rolling_v2_receipt_drift_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    pilot, python, source = _frozen_capability_fixture(tmp_path, monkeypatch)
    _configure_rolling_window_fixture(pilot)
    plan_path = pilot / "pilot-spec.json"
    window_path = pilot / "window-spec.json"
    plan = json.loads(plan_path.read_text())
    window = json.loads(window_path.read_text())

    if mutation == "missing_window":
        window_path.unlink()
    elif mutation == "missing_hash":
        plan.pop("window_spec_sha256")
        plan_path.write_bytes(_canonical(plan))
    elif mutation == "wrong_hash":
        plan["window_spec_sha256"] = "0" * 64
        plan_path.write_bytes(_canonical(plan))
    else:
        if mutation == "legacy_schema":
            window["schema"] = "freqtrade-lab-okx-window-v1"
        else:
            window["holdout_start_utc"] = "2026-06-01T00:00:00Z"
        window_bytes = _canonical(window)
        window_path.write_bytes(window_bytes)
        plan["window_spec_sha256"] = hashlib.sha256(window_bytes).hexdigest()
        plan_path.write_bytes(_canonical(plan))

    capability = development_run.freeze_development_capability(
        pilot, python, source
    )

    assert capability.status == "BLOCKED_DATA"
    assert capability.development_timerange is None


def test_t0_legacy_dates_do_not_bypass_the_window_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pilot, python, source = _frozen_capability_fixture(tmp_path, monkeypatch)
    plan_path = pilot / "pilot-spec.json"
    plan = json.loads(plan_path.read_text())
    plan["window_spec_sha256"] = "0" * 64
    plan_path.write_bytes(_canonical(plan))

    capability = development_run.freeze_development_capability(
        pilot, python, source
    )

    assert capability.status == "BLOCKED_DATA"
    assert capability.development_timerange is None


@pytest.mark.parametrize(
    "development_timerange",
    ("20260101-20260301", "20260101-20260303"),
)
def test_t0_development_rejects_59_or_61_day_window(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    development_timerange: str,
) -> None:
    pilot, python, source = _frozen_capability_fixture(tmp_path, monkeypatch)
    plan_path = pilot / "pilot-spec.json"
    plan = json.loads(plan_path.read_text())
    plan["development_timerange"] = development_timerange
    plan_path.write_bytes(_canonical(plan))

    capability = development_run.freeze_development_capability(
        pilot, python, source
    )

    assert capability.status == "BLOCKED_DATA"
    assert capability.reason == (
        "Pilot Development timerange must span exactly 60 days"
    )


def test_t0_verified_xrp_market_identity_is_bound() -> None:
    pair, instrument_id = development_run._verified_market_identity(
        {
            "host": "www.okx.com",
            "authentication": "none",
            "pair": "XRP/USDT:USDT",
            "instrument_id": "XRP-USDT-SWAP",
        },
        _canonical(
            {
                "symbol": "XRP/USDT:USDT",
                "id": "XRP-USDT-SWAP",
            }
        ),
        "XRP/USDT:USDT",
    )

    assert pair == "XRP/USDT:USDT"
    assert instrument_id == "XRP-USDT-SWAP"


@pytest.mark.parametrize(
    "drift",
    (
        "source_host",
        "source_authentication",
        "missing_source_id",
        "isolation_id",
        "market_id",
        "market_symbol",
    ),
)
def test_t0_freeze_rejects_instrument_identity_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    drift: str,
) -> None:
    pilot, python, source = _frozen_capability_fixture(tmp_path, monkeypatch)
    acquisition_provenance_path = (
        pilot / "acquisition" / "retained-data-provenance.json"
    )
    acquisition_provenance = json.loads(acquisition_provenance_path.read_text())
    if drift == "source_host":
        acquisition_provenance["source"]["host"] = "attacker.invalid"
        _rewrite_source_provenance(pilot, acquisition_provenance)
    elif drift == "source_authentication":
        acquisition_provenance["source"]["authentication"] = "credentialed"
        _rewrite_source_provenance(pilot, acquisition_provenance)
    elif drift == "missing_source_id":
        acquisition_provenance["source"].pop("instrument_id")
        _rewrite_source_provenance(pilot, acquisition_provenance)
    elif drift == "isolation_id":
        isolation_path = (
            pilot / "development-isolation" / "retained-data-provenance.json"
        )
        isolation = json.loads(isolation_path.read_text())
        isolation["source"]["instrument_id"] = "XRP-USDT-SWAP"
        isolation_path.write_bytes(_canonical(isolation))
    else:
        market_path = pilot / "acquisition" / "market_snapshot.json"
        market = json.loads(market_path.read_text())
        market["id" if drift == "market_id" else "symbol"] = (
            "XRP-USDT-SWAP" if drift == "market_id" else "XRP/USDT:USDT"
        )
        market_bytes = _canonical(market)
        market_path.write_bytes(market_bytes)
        isolation_path = (
            pilot / "development-isolation" / "retained-data-provenance.json"
        )
        isolation = json.loads(isolation_path.read_text())
        isolation["local_only_files"]["market_snapshot.json"] = {
            "bytes": len(market_bytes),
            "sha256": hashlib.sha256(market_bytes).hexdigest(),
        }
        isolation_path.write_bytes(_canonical(isolation))

    capability = development_run.freeze_development_capability(pilot, python, source)

    assert capability.status == "BLOCKED_DATA"
    assert "identity" in capability.reason


@pytest.mark.parametrize(
    ("receipt", "expected_reason"),
    (
        (None, "Pilot config provenance receipt is missing"),
        ({"bytes": "779", "sha256": "0" * 64}, "Pilot config receipt is invalid"),
    ),
)
def test_t0_freeze_rejects_missing_or_invalid_pilot_config_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    receipt: object,
    expected_reason: str,
) -> None:
    pilot, python, source = _frozen_capability_fixture(tmp_path, monkeypatch)
    provenance_path = pilot / "acquisition" / "retained-data-provenance.json"
    provenance = json.loads(provenance_path.read_text())
    if receipt is None:
        provenance["files"].pop("config.json")
    else:
        provenance["files"]["config.json"] = receipt
    _rewrite_source_provenance(pilot, provenance)

    capability = development_run.freeze_development_capability(pilot, python, source)

    assert capability.status == "BLOCKED_DATA"
    assert capability.reason == expected_reason


def test_t0_freeze_requires_canonical_pilot_config_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pilot, python, source = _frozen_capability_fixture(tmp_path, monkeypatch)
    provenance_path = pilot / "acquisition" / "retained-data-provenance.json"
    provenance = json.loads(provenance_path.read_text())
    provenance["contract"]["config"] = "alternate-config.json"
    _rewrite_source_provenance(pilot, provenance)

    capability = development_run.freeze_development_capability(pilot, python, source)

    assert capability.status == "BLOCKED_DATA"
    assert capability.reason == "Pilot config provenance receipt is missing"


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("api_key", "must-never-be-copied-or-returned"),
        ("unexpected_mode", "outside-the-fixed-contract"),
    ),
)
def test_t0_config_credentials_and_extra_keys_block_before_consumption(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: str,
) -> None:
    pilot, python, source = _frozen_capability_fixture(tmp_path, monkeypatch)
    config_path = pilot / "acquisition" / "config.json"
    config = json.loads(config_path.read_text())
    config[field] = value
    _rewrite_pilot_config(pilot, config)

    capability = development_run.freeze_development_capability(
        pilot, python, source
    )

    assert capability.status == "BLOCKED_DATA"
    assert capability.reason == "Pilot config contract mismatch"
    public_text = json.dumps(capability.public(), sort_keys=True)
    assert field not in public_text
    assert value not in public_text

    database, candidate_id = _approved_candidate_database(tmp_path / "database")
    run_id = str(uuid4())
    run_dir = tmp_path / "runtime" / run_id
    run_dir.mkdir(parents=True)
    with pytest.raises(development_run.DevelopmentRunError) as raised:
        development_run.prepare_development_run(
            database,
            run_dir,
            candidate_id,
            capability,
            research_run_id=run_id,
            now=NOW,
        )
    assert raised.value.code == "BLOCKED_DATA"
    with get_connection(database, read_only=True) as connection:
        assert connection.execute("SELECT COUNT(*) FROM research_runs").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM backtest_executions").fetchone()[0] == 0
    assert not (run_dir / "development-input").exists()


def test_t0_provenance_path_is_normalized_without_echo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pilot, python, source = _frozen_capability_fixture(tmp_path, monkeypatch)
    provenance_path = (
        pilot / "development-isolation" / "retained-data-provenance.json"
    )
    provenance = json.loads(provenance_path.read_text())
    original = provenance["contract"]["market_snapshot"]
    malicious = "/private/tmp/must-not-leak-market.json"
    provenance["contract"]["market_snapshot"] = malicious
    provenance["local_only_files"][malicious] = provenance[
        "local_only_files"
    ].pop(original)
    provenance_path.write_bytes(_canonical(provenance))

    capability = development_run.freeze_development_capability(
        pilot, python, source
    )

    assert capability.status == "BLOCKED_DATA"
    assert malicious not in capability.reason
    assert malicious not in json.dumps(capability.public(), sort_keys=True)


def test_t0_freeze_rejects_same_length_pilot_config_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pilot, python, source = _frozen_capability_fixture(tmp_path, monkeypatch)
    config_path = pilot / "acquisition" / "config.json"
    original = config_path.read_bytes()
    changed = original.replace(
        b'"tradable_balance_ratio":0.99', b'"tradable_balance_ratio":0.98'
    )
    assert changed != original and len(changed) == len(original)
    config_path.write_bytes(changed)

    capability = development_run.freeze_development_capability(pilot, python, source)

    assert capability.status == "BLOCKED_DATA"
    assert capability.reason == "Pilot config receipt mismatch"


def test_t0_require_ready_rejects_post_start_pilot_config_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pilot, python, source = _frozen_capability_fixture(tmp_path, monkeypatch)
    capability = development_run.freeze_development_capability(pilot, python, source)
    assert capability.status == "READY"
    config_path = pilot / "acquisition" / "config.json"
    original = config_path.read_bytes()
    changed = original.replace(
        b'"tradable_balance_ratio":0.99', b'"tradable_balance_ratio":0.98'
    )
    assert changed != original and len(changed) == len(original)
    config_path.write_bytes(changed)

    with pytest.raises(development_run.DevelopmentRunError) as raised:
        development_run._require_ready(capability)

    assert raised.value.code == "BLOCKED_DATA"
    assert raised.value.message == "startup-frozen Development inputs changed"


@pytest.mark.parametrize(
    ("field", "value", "profile_pair"),
    (
        ("pair", "XRP/USDT:USDT", "XRP/USDT:USDT"),
        ("instrument_id", "XRP-USDT-SWAP", "ADA/USDT:USDT"),
    ),
)
def test_t0_require_ready_rejects_market_identity_drift_before_database_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: str,
    profile_pair: str,
) -> None:
    pilot, python, source = _frozen_capability_fixture(tmp_path, monkeypatch)
    capability = development_run.freeze_development_capability(pilot, python, source)
    assert capability.status == "READY"
    drifted = replace(capability, **{field: value})
    database, candidate_id = _approved_candidate_database(
        tmp_path / "database", pair=profile_pair
    )
    run_id = str(uuid4())
    run_dir = tmp_path / "runtime" / run_id
    run_dir.mkdir(parents=True)

    monkeypatch.setattr(
        development_run,
        "get_connection",
        lambda *_args, **_kwargs: pytest.fail("database opened before identity gate"),
    )
    with pytest.raises(development_run.DevelopmentRunError) as raised:
        development_run.prepare_development_run(
            database,
            run_dir,
            candidate_id,
            drifted,
            research_run_id=run_id,
            now=NOW,
        )

    assert raised.value.code == "BLOCKED_DATA"
    assert raised.value.message == "startup-frozen Development inputs changed"
    with get_connection(database, read_only=True) as connection:
        assert connection.execute("SELECT COUNT(*) FROM research_runs").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM backtest_executions").fetchone()[0] == 0
    assert not (run_dir / "development-input").exists()


def test_t0_context_prioritizes_security_profile_then_runtime_blockers(
    tmp_path: Path,
) -> None:
    capability = development_run.FrozenDevelopmentCapability(
        status="BLOCKED_DATA",
        reason="runtime missing",
        pair="ADA/USDT:USDT",
    )
    ready_database, ready_candidate = _approved_candidate_database(tmp_path / "ready")
    profile_database, profile_candidate = _approved_candidate_database(
        tmp_path / "profile",
        min_development_trades=29,
    )
    security_database, security_candidate = _approved_candidate_database(
        tmp_path / "security"
    )
    with get_connection(security_database) as connection:
        connection.execute(
            "UPDATE candidates SET code_text = code_text || ? WHERE id = ?",
            ("\n# post-approval mutation", security_candidate),
        )
        connection.commit()

    ready = development_run.research_context(ready_database, capability)
    blocked_profile = development_run.research_context(profile_database, capability)
    blocked_security = development_run.research_context(security_database, capability)

    assert ready["candidates"] == [
        {
            "candidate_id": ready_candidate,
            "display_name": "Bounded Candidate",
            "status": "BLOCKED_DATA",
            "reason": "runtime missing",
        }
    ]
    assert blocked_profile["candidates"][0]["candidate_id"] == profile_candidate
    assert blocked_profile["candidates"][0]["status"] == "BLOCKED_PROFILE"
    assert blocked_security["candidates"][0]["candidate_id"] == security_candidate
    assert blocked_security["candidates"][0]["status"] == "BLOCKED_SECURITY"


def test_t0_context_offers_one_retry_for_same_frozen_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database, candidate_id = _approved_candidate_database(tmp_path)
    capability = development_run.FrozenDevelopmentCapability(
        status="READY",
        reason="test-ready",
        pair="ADA/USDT:USDT",
        development_timerange="20260601-20260731",
    )
    monkeypatch.setattr(development_run, "_require_ready", lambda _capability: None)
    with get_connection(database) as connection:
        connection.execute("BEGIN IMMEDIATE")
        candidate = development_run._bound_candidate(connection, candidate_id)
        snapshot = development_run._snapshot(capability, candidate)
        snapshot["materialized_input_hashes"] = {"config.json": "0" * 64}
        connection.execute(
            """
            INSERT INTO research_runs (
                id,candidate_id,research_profile_id,trigger_type,status,stage,
                verdict,pipeline_version,input_snapshot_json,checks_json,run_dir,
                rejection_reasons_json,created_at,started_at,finished_at
            ) VALUES (?,?,?,?, 'FAILED','DEVELOPMENT_BACKTEST',NULL,?,?, '{}',?,
                      '[]',?,?,?)
            """,
            (
                str(uuid4()),
                candidate_id,
                candidate["research_profile_id"],
                "MANUAL",
                development_run.DEVELOPMENT_PIPELINE_VERSION,
                json.dumps(snapshot),
                str(tmp_path / "first"),
                NOW,
                NOW,
                NOW,
            ),
        )
        connection.commit()

    context = development_run.research_context(database, capability)
    assert context["candidates"][0]["status"] == "READY"

    with get_connection(database) as connection:
        connection.execute(
            """
            INSERT INTO research_runs (
                id,candidate_id,research_profile_id,trigger_type,status,stage,
                verdict,pipeline_version,input_snapshot_json,checks_json,run_dir,
                rejection_reasons_json,created_at,started_at,finished_at
            ) VALUES (?,?,?,?, 'FAILED','DEVELOPMENT_BACKTEST',NULL,?,?, '{}',?,
                      '[]',?,?,?)
            """,
            (
                str(uuid4()),
                candidate_id,
                candidate["research_profile_id"],
                "RETRY",
                development_run.DEVELOPMENT_PIPELINE_VERSION,
                json.dumps(snapshot),
                str(tmp_path / "retry"),
                NOW,
                NOW,
                NOW,
            ),
        )
        connection.commit()
    context = development_run.research_context(database, capability)
    assert context["candidates"][0]["status"] == "ALREADY_PENDING"


def test_t0_profile_development_requires_finalist_binding_before_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database, candidate_id = _approved_candidate_database(
        tmp_path / "database", timeframe="1d"
    )
    with get_connection(database, read_only=True) as connection:
        connection.execute("BEGIN")
        profile = dict(
            codex_generation.load_approved_candidate_snapshot(
                connection, candidate_id
            ).profile
        )
    contract = pilot.profile_search_contract(
        profile, "20260201-20260313", "20260313-20260512", 20
    )
    pilot_root, python, source = _frozen_capability_fixture(
        tmp_path / "capability",
        monkeypatch,
        timeframe="1d",
        profile_contract=contract,
    )
    capability = development_run.freeze_development_capability(
        pilot_root, python, source, profile_contract=contract
    )
    assert capability.status == "READY"
    run_id = str(uuid4())
    run_dir = tmp_path / "runtime" / run_id
    run_dir.mkdir(parents=True)

    with pytest.raises(development_run.DevelopmentRunError) as raised:
        development_run.prepare_development_run(
            database, run_dir, candidate_id, capability,
            research_run_id=run_id, now=NOW,
        )

    assert raised.value.code == "BLOCKED_SECURITY"
    assert not any(run_dir.iterdir())
    with get_connection(database, read_only=True) as connection:
        assert connection.execute("SELECT COUNT(*) FROM research_runs").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM backtest_executions").fetchone()[0] == 0


def test_t0_profile_development_accepts_exact_non_hour_base_warmup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database, candidate_id = _approved_candidate_database(tmp_path / "database")
    with get_connection(database, read_only=True) as connection:
        connection.execute("BEGIN")
        profile = dict(
            codex_generation.load_approved_candidate_snapshot(
                connection, candidate_id
            ).profile
        )
    contract = pilot.profile_search_contract(
        profile, "20260601-20260701", "20260701-20260731", 25
    )
    pilot_root, python, source = _frozen_capability_fixture(
        tmp_path / "capability",
        monkeypatch,
        timeframe="5m",
        profile_contract=contract,
    )

    capability = development_run.freeze_development_capability(
        pilot_root, python, source, profile_contract=contract
    )

    assert capability.status == "READY"
    window = json.loads((pilot_root / "window-spec.json").read_bytes())
    assert window["data_start_utc"] == "2026-06-30T21:55:00Z"


def test_t1_child_rejects_replaced_startup_frozen_python(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database, candidate_id = _approved_candidate_database(tmp_path / "database")
    pilot, python, source = _frozen_capability_fixture(
        tmp_path / "capability", monkeypatch
    )
    capability = development_run.freeze_development_capability(
        pilot, python, source
    )
    assert capability.status == "READY"
    run_id = str(uuid4())
    run_dir = tmp_path / "runtime" / run_id
    run_dir.mkdir(parents=True)
    development_run.prepare_development_run(
        database,
        run_dir,
        candidate_id,
        capability,
        research_run_id=run_id,
        now=NOW,
    )
    replacement = python.with_name("replacement-python")
    replacement.write_text("#!/bin/sh\nexit 0\n# replacement\n")
    replacement.chmod(0o700)
    replacement.replace(python)
    monkeypatch.setattr(
        development_run,
        "_run_scenario",
        lambda **_kwargs: pytest.fail("changed Python must fail before Freqtrade"),
    )

    with pytest.raises(development_run.DevelopmentRunError) as raised:
        development_run.execute_development_run(
            database, run_dir, run_id, python, source
        )

    assert raised.value.code == "BLOCKED_DATA"
    assert raised.value.message == "Freqtrade Python identity changed"


@pytest.mark.parametrize(
    (
        "total_trades",
        "profit_pct",
        "profit_factor",
        "max_drawdown_pct",
        "expected_reasons",
    ),
    (
        (30, 0.5, 1.1, 5.0, []),
        (31, 0.6, 1.2, 4.9, []),
        (
            0,
            0.0,
            0.0,
            0.0,
            [
                "MINIMUM_TRADES_NOT_MET",
                "MINIMUM_PROFIT_PCT_NOT_MET",
                "MINIMUM_PROFIT_FACTOR_NOT_MET",
            ],
        ),
        (29, 0.5, 1.1, 5.0, ["MINIMUM_TRADES_NOT_MET"]),
        (30, 0.49, 1.1, 5.0, ["MINIMUM_PROFIT_PCT_NOT_MET"]),
        (30, 0.5, None, 5.0, ["MINIMUM_PROFIT_FACTOR_NOT_MET"]),
        (30, 0.5, 1.09, 5.0, ["MINIMUM_PROFIT_FACTOR_NOT_MET"]),
        (30, 0.5, 1.1, 5.01, ["MAXIMUM_DRAWDOWN_EXCEEDED"]),
    ),
)
def test_t0_fixed_development_gate_truth_table_and_public_contract(
    tmp_path: Path,
    total_trades: int,
    profit_pct: float,
    profit_factor: float | None,
    max_drawdown_pct: float,
    expected_reasons: list[str],
) -> None:
    database, research_run_id = _seed_development_run(
        tmp_path,
        total_trades=total_trades,
        profit_pct=profit_pct,
        profit_factor=profit_factor,
        max_drawdown_pct=max_drawdown_pct,
    )

    public = development_run.finalize_development_gate(database, research_run_id)
    repeated = development_run.finalize_development_gate(database, research_run_id)

    assert repeated == public
    assert [item["criterion"] for item in public["gate_results"]] == [
        "minimum_trades",
        "minimum_profit_pct",
        "minimum_profit_factor",
        "maximum_drawdown_pct",
    ]
    assert all(
        set(item) == {"criterion", "threshold", "actual", "passed"}
        and isinstance(item["passed"], bool)
        for item in public["gate_results"]
    )
    if profit_factor is None:
        profit_factor_gate = public["gate_results"][2]
        assert profit_factor_gate["actual"] is None
        assert profit_factor_gate["passed"] is False
    assert public["rejection_reasons"] == expected_reasons
    assert public["development"]["status"] == "SUCCEEDED"
    assert public["development"]["scenario_passed"] is (not expected_reasons)
    if expected_reasons:
        assert (public["status"], public["stage"], public["verdict"]) == (
            "COMPLETED",
            "COMPLETED",
            "REJECTED",
        )
        assert public["finished_at"] is not None
        assert public["checks"]["development_gate"] == "REJECTED"
    else:
        assert (public["status"], public["stage"], public["verdict"]) == (
            "PENDING",
            "PENDING",
            None,
        )
        assert public["finished_at"] is None
        assert public["checks"]["development_gate"] == "PASSED"

    assert public["holdout"] == {"status": "SEALED_UNREAD", "execution_rows": 0}
    assert public["holdout_stress"] == {
        "status": "SEALED_UNREAD",
        "execution_rows": 0,
    }
    serialized = json.dumps(public, sort_keys=True)
    assert "/private/" not in serialized
    for private_key in (
        "run_dir",
        "config_path",
        "strategy_path",
        "result_archive_path",
        "stdout_path",
        "stderr_path",
        "input_snapshot_json",
        "command_json",
    ):
        assert private_key not in public

    with get_connection(database, read_only=True) as connection:
        rows = connection.execute(
            "SELECT scenario, scenario_passed FROM backtest_executions WHERE research_run_id=?",
            (research_run_id,),
        ).fetchall()
    assert [(row["scenario"], row["scenario_passed"]) for row in rows] == [
        ("DEVELOPMENT", 0 if expected_reasons else 1)
    ]


@pytest.mark.parametrize(
    ("initial_trades", "tampered_trades", "tampered_profit"),
    [(30, 0, -99.0), (29, 29, -99.0)],
)
def test_t0_public_terminal_gate_is_recomputed_from_current_metrics(
    tmp_path: Path,
    initial_trades: int,
    tampered_trades: int,
    tampered_profit: float,
) -> None:
    database, research_run_id = _seed_development_run(
        tmp_path, total_trades=initial_trades
    )
    development_run.finalize_development_gate(database, research_run_id)
    with get_connection(database) as connection:
        connection.execute(
            """
            UPDATE backtest_executions
            SET total_trades=?, profit_pct=?
            WHERE research_run_id=? AND scenario='DEVELOPMENT'
            """,
            (tampered_trades, tampered_profit, research_run_id),
        )
        connection.commit()

    with pytest.raises(development_run.DevelopmentRunError) as raised:
        development_run.load_public_research_run(database, research_run_id)
    assert raised.value.code == "run_state_conflict"


def test_t0_public_terminal_gate_rejects_missing_required_actual(tmp_path: Path) -> None:
    database, research_run_id = _seed_development_run(tmp_path)
    development_run.finalize_development_gate(database, research_run_id)
    with get_connection(database) as connection:
        connection.execute(
            "UPDATE backtest_executions SET profit_pct=NULL WHERE research_run_id=?",
            (research_run_id,),
        )
        connection.commit()

    with pytest.raises(development_run.DevelopmentRunError) as raised:
        development_run.load_public_research_run(database, research_run_id)
    assert raised.value.code == "run_state_conflict"


def test_t0_succeeded_execution_requires_finished_timestamp(
    tmp_path: Path,
) -> None:
    database, research_run_id = _seed_development_run(tmp_path)
    with get_connection(database) as connection:
        connection.execute(
            "UPDATE backtest_executions SET finished_at=? WHERE research_run_id=?",
            (NOW, research_run_id),
        )
        connection.commit()

    public = development_run.load_public_research_run(database, research_run_id)
    assert (public["status"], public["development"]["status"]) == (
        "RUNNING",
        "SUCCEEDED",
    )
    assert all(item["passed"] is None for item in public["gate_results"])

    with get_connection(database) as connection:
        connection.execute(
            "UPDATE backtest_executions SET finished_at=NULL WHERE research_run_id=?",
            (research_run_id,),
        )
        connection.commit()
    with pytest.raises(development_run.DevelopmentRunError) as raised:
        development_run.load_public_research_run(database, research_run_id)
    assert raised.value.code == "run_state_conflict"


@pytest.mark.parametrize("execution_status", ("PENDING", "RUNNING"))
def test_t0_nonterminal_execution_rejects_preexisting_metrics(
    tmp_path: Path, execution_status: str
) -> None:
    database, research_run_id = _seed_development_run(
        tmp_path, status=execution_status
    )

    with pytest.raises(development_run.DevelopmentRunError) as raised:
        development_run.load_public_research_run(database, research_run_id)

    assert raised.value.code == "run_state_conflict"


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("max_drawdown_pct", -0.01),
        ("max_drawdown_pct", 100.01),
        ("win_rate", -0.01),
        ("win_rate", 100.01),
        ("profit_factor", -0.01),
    ),
)
def test_t0_public_metrics_reject_impossible_ranges(
    tmp_path: Path, field: str, value: float
) -> None:
    database, research_run_id = _seed_development_run(tmp_path)
    development_run.finalize_development_gate(database, research_run_id)
    with get_connection(database) as connection:
        connection.execute(
            f"UPDATE backtest_executions SET {field}=? WHERE research_run_id=?",
            (value, research_run_id),
        )
        connection.commit()

    with pytest.raises(development_run.DevelopmentRunError) as raised:
        development_run.load_public_research_run(database, research_run_id)

    assert raised.value.code == "run_state_conflict"


def test_t1_failed_development_clears_all_metrics_and_paths(tmp_path: Path) -> None:
    database, research_run_id = _seed_development_run(tmp_path, status="PENDING")

    public = development_run.fail_development_run(
        database,
        research_run_id,
        "FAILED",
        "DEVELOPMENT_FAILED",
    )

    assert (public["status"], public["verdict"]) == ("FAILED", None)
    assert public["error_stage"] == "DEVELOPMENT_BACKTEST"
    assert public["error_message"] == "DEVELOPMENT_FAILED"
    assert public["development"]["status"] == "FAILED"
    assert public["development"]["scenario_passed"] is None
    assert all(
        item["actual"] is None and item["passed"] is None
        for item in public["gate_results"]
    )
    assert public["holdout"]["status"] == "SEALED_UNREAD"
    assert public["holdout_stress"]["status"] == "SEALED_UNREAD"

    with get_connection(database, read_only=True) as connection:
        row = connection.execute(
            "SELECT * FROM backtest_executions WHERE research_run_id=?",
            (research_run_id,),
        ).fetchone()
        assert row is not None
        assert row["metrics_json"] == "{}"
        assert row["error_message"] == "DEVELOPMENT_FAILED"
        for field in (
            "result_archive_path",
            "stdout_path",
            "stderr_path",
            "return_code",
            "total_trades",
            "profit_pct",
            "max_drawdown_pct",
            "win_rate",
            "profit_factor",
            "sharpe",
            "sortino",
            "calmar",
            "long_profit_pct",
            "short_profit_pct",
            "scenario_passed",
        ):
            assert row[field] is None


def test_t1_recovery_finalizes_an_already_succeeded_execution(tmp_path: Path) -> None:
    database, research_run_id = _seed_development_run(tmp_path)

    public = development_run.fail_development_run(
        database,
        research_run_id,
        "INTERRUPTED",
        "SERVER_RESTARTED",
    )

    assert (public["status"], public["stage"], public["verdict"]) == (
        "PENDING",
        "PENDING",
        None,
    )
    assert public["error_message"] is None
    assert public["development"]["status"] == "SUCCEEDED"
    assert public["development"]["scenario_passed"] is True
    assert public["development"]["total_trades"] == 30


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        ("other_pipeline", "run_not_found"),
        ("missing_execution", "run_state_conflict"),
        ("wrong_scenario", "run_state_conflict"),
        ("extra_execution", "run_state_conflict"),
    ],
)
def test_t0_public_loader_requires_this_pipeline_and_one_development_execution(
    tmp_path: Path,
    mutation: str,
    expected_code: str,
) -> None:
    database, research_run_id = _seed_development_run(tmp_path)
    with get_connection(database) as connection:
        if mutation == "other_pipeline":
            connection.execute(
                "UPDATE research_runs SET pipeline_version='OTHER_PIPELINE' WHERE id=?",
                (research_run_id,),
            )
        elif mutation == "missing_execution":
            connection.execute(
                "DELETE FROM backtest_executions WHERE research_run_id=?",
                (research_run_id,),
            )
        elif mutation == "wrong_scenario":
            connection.execute(
                "UPDATE backtest_executions SET scenario='HOLDOUT' WHERE research_run_id=?",
                (research_run_id,),
            )
        else:
            connection.execute(
                """
                INSERT INTO backtest_executions (
                    id, research_run_id, scenario, status, sequence,
                    timerange_start, timerange_end, timeframe, fee_rate,
                    fee_multiplier, command_json, config_path, strategy_path,
                    metrics_json, created_at
                ) VALUES (?, ?, 'HOLDOUT', 'PENDING', 2,
                          '2026-07-31T00:00:00Z', '2026-08-29T23:55:00Z',
                          '5m', 0.0005, 1.0, '{}', '/private/later-config',
                          '/private/later-strategy', '{}', ?)
                """,
                (str(uuid4()), research_run_id, NOW),
            )
        connection.commit()

    with pytest.raises(development_run.DevelopmentRunError) as raised:
        development_run.load_public_research_run(database, research_run_id)
    assert raised.value.code == expected_code
    assert "/private/" not in str(raised.value)


@pytest.mark.parametrize(
    "field", ["checks", "checks_state", "rejection_reasons"]
)
def test_t0_public_loader_rejects_non_allowlisted_public_evidence(
    tmp_path: Path, field: str
) -> None:
    database, research_run_id = _seed_development_run(tmp_path)
    with get_connection(database) as connection:
        if field in {"checks", "checks_state"}:
            checks = json.loads(
                connection.execute(
                    "SELECT checks_json FROM research_runs WHERE id=?",
                    (research_run_id,),
                ).fetchone()[0]
            )
            if field == "checks":
                checks["private_path"] = "/private/check-evidence"
            else:
                checks["development_gate"] = "REJECTED"
            connection.execute(
                "UPDATE research_runs SET checks_json=? WHERE id=?",
                (json.dumps(checks), research_run_id),
            )
        else:
            connection.execute(
                "UPDATE research_runs SET rejection_reasons_json=? WHERE id=?",
                ('["/private/rejection-evidence"]', research_run_id),
            )
        connection.commit()

    with pytest.raises(development_run.DevelopmentRunError) as raised:
        development_run.load_public_research_run(database, research_run_id)
    assert raised.value.code == "run_state_conflict"
    assert "/private/" not in str(raised.value)


def test_t0_public_loader_normalizes_untrusted_error_text(tmp_path: Path) -> None:
    database, research_run_id = _seed_development_run(tmp_path, status="PENDING")
    public = development_run.fail_development_run(
        database,
        research_run_id,
        "FAILED",
        "/private/raw-worker-error.log",
    )
    with get_connection(database) as connection:
        connection.execute(
            "UPDATE research_runs SET error_stage='/private/raw-stage' WHERE id=?",
            (research_run_id,),
        )
        connection.commit()

    public = development_run.load_public_research_run(database, research_run_id)
    assert public["error_stage"] == "DEVELOPMENT_BACKTEST"
    assert public["error_message"] == "DEVELOPMENT_FAILED"
    assert "/private/" not in json.dumps(public, sort_keys=True)


@pytest.mark.parametrize(
    ("table", "column", "value"),
    [
        ("research_runs", "created_at", "/private/run-created.secret"),
        ("research_runs", "started_at", "2026-01-01T00:00:00+00:00"),
        ("research_runs", "finished_at", None),
        ("backtest_executions", "created_at", "/private/execution-created.secret"),
        ("backtest_executions", "started_at", "/private/execution-started.secret"),
        ("backtest_executions", "finished_at", None),
    ],
)
def test_t0_public_loader_rejects_invalid_or_impossible_timestamps(
    tmp_path: Path,
    table: str,
    column: str,
    value: str | None,
) -> None:
    database, research_run_id = _seed_development_run(tmp_path, total_trades=29)
    development_run.finalize_development_gate(database, research_run_id)
    with get_connection(database) as connection:
        connection.execute(
            f"UPDATE {table} SET {column}=? WHERE "
            + ("id=?" if table == "research_runs" else "research_run_id=?"),
            (value, research_run_id),
        )
        connection.commit()

    with pytest.raises(development_run.DevelopmentRunError) as raised:
        development_run.load_public_research_run(database, research_run_id)
    assert raised.value.code == "run_state_conflict"
    assert "/private/" not in str(raised.value)


def test_t1_execute_keeps_zero_trade_development_inside_the_run_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database, candidate_id = _approved_candidate_database(tmp_path / "database")
    pilot, python, source = _frozen_capability_fixture(
        tmp_path / "capability", monkeypatch
    )
    capability = development_run.freeze_development_capability(
        pilot, python, source
    )
    assert capability.status == "READY"
    run_id = str(uuid4())
    run_dir = tmp_path / "runtime" / run_id
    run_dir.mkdir(parents=True)
    prepared = development_run.prepare_development_run(
        database,
        run_dir,
        candidate_id,
        capability,
        research_run_id=run_id,
        now=NOW,
    )
    calls: dict[str, object] = {}

    def fake_source_snapshot(
        source_root: Path,
        destination: Path,
        git_home: Path,
        sandbox_exec: Path,
    ) -> str:
        calls["source_snapshot"] = {
            "source_root": source_root,
            "destination": destination,
            "git_home": git_home,
            "sandbox_exec": sandbox_exec,
        }
        destination.mkdir()
        return development_run.SUPPORTED_FREQTRADE_TREE

    def fake_run_scenario(**kwargs: object) -> tuple[object, object, object]:
        calls["runner"] = kwargs
        return object(), {"fake": "runner-summary"}, ("fixed-command-shape",)

    def fake_sanitize_raw_artifact(**kwargs: object) -> SimpleNamespace:
        calls["sanitizer"] = kwargs
        archive = Path(kwargs["bundle_dir"]) / "development-01.zip"
        archive.write_bytes(b"sanitized-development-artifact")
        return SimpleNamespace(
            archive=str(archive),
            provenance_sha256="a" * 64,
        )

    def fake_import_backtest_execution(
        database_path: Path,
        bundle_root: Path,
        archive: Path,
        research_run_id: str,
        scenario: str,
        strategy: str,
        freqtrade_version: str,
        provenance_sha256: str,
        *,
        allow_zero_trades: bool,
        mark_execution_finished: bool,
    ) -> None:
        calls["importer"] = {
            "database_path": database_path,
            "bundle_root": bundle_root,
            "archive": archive,
            "research_run_id": research_run_id,
            "scenario": scenario,
            "strategy": strategy,
            "freqtrade_version": freqtrade_version,
            "provenance_sha256": provenance_sha256,
            "allow_zero_trades": allow_zero_trades,
            "mark_execution_finished": mark_execution_finished,
        }
        with get_connection(database_path) as connection:
            changed = connection.execute(
                """
                UPDATE backtest_executions
                SET status='SUCCEEDED', result_archive_path=?, return_code=0,
                    total_trades=0, profit_pct=0.0, max_drawdown_pct=0.0,
                    win_rate=0.0, profit_factor=0.0,
                    metrics_json='{"source":"fake-import-boundary"}',
                    finished_at=?
                WHERE research_run_id=? AND scenario='DEVELOPMENT'
                  AND status='PENDING' AND scenario_passed IS NULL
                """,
                (str(archive), NOW, research_run_id),
            ).rowcount
            assert changed == 1
            connection.commit()

    monkeypatch.setattr(
        development_run,
        "_prepare_freqtrade_source_snapshot",
        fake_source_snapshot,
    )
    monkeypatch.setattr(development_run, "_run_scenario", fake_run_scenario)
    monkeypatch.setattr(
        development_run,
        "_sanitize_raw_artifact",
        fake_sanitize_raw_artifact,
    )
    monkeypatch.setattr(
        development_run,
        "import_backtest_execution",
        fake_import_backtest_execution,
    )

    public = development_run.execute_development_run(
        database,
        run_dir,
        prepared.research_run_id,
        python,
        source,
    )

    runner = calls["runner"]
    sanitizer = calls["sanitizer"]
    importer = calls["importer"]
    assert isinstance(runner, dict)
    assert isinstance(sanitizer, dict)
    assert isinstance(importer, dict)
    assert runner["allow_zero_trades"] is True
    assert sanitizer["allow_zero_trades"] is True
    assert importer["allow_zero_trades"] is True
    assert importer["mark_execution_finished"] is True
    assert runner["scenario_open_receipt"] is None
    assert importer["research_run_id"] == run_id
    assert importer["scenario"] == "DEVELOPMENT"

    source_snapshot = calls["source_snapshot"]
    assert isinstance(source_snapshot, dict)
    data_paths = [
        source_snapshot["destination"],
        source_snapshot["git_home"],
        *(
            runner[key]
            for key in (
                "source",
                "config_path",
                "data_dir",
                "user_data_dir",
                "strategy_path",
                "strategy_file",
                "export_dir",
                "market_snapshot",
                "leverage_tiers",
                "data_provenance",
                "home",
            )
        ),
        sanitizer["raw_dir"],
        sanitizer["bundle_dir"],
        importer["bundle_root"],
        importer["archive"],
    ]
    allowed_roots = {
        "development-input",
        "development-runtime",
        "development-evidence",
    }
    for value in data_paths:
        path = Path(value).resolve(strict=False)
        relative = path.relative_to(run_dir.resolve())
        assert relative.parts[0] in allowed_roots
        assert not any(
            token in part.lower()
            for part in relative.parts
            for token in ("pilot", "acquisition", "holdout", "stress")
        )

    assert (public["research_run_id"], public["status"], public["stage"]) == (
        run_id,
        "COMPLETED",
        "COMPLETED",
    )
    assert public["verdict"] == "REJECTED"
    assert public["development"]["status"] == "SUCCEEDED"
    assert public["development"]["total_trades"] == 0
    assert public["development"]["scenario_passed"] is False
    assert public["rejection_reasons"] == [
        "MINIMUM_TRADES_NOT_MET",
        "MINIMUM_PROFIT_PCT_NOT_MET",
        "MINIMUM_PROFIT_FACTOR_NOT_MET",
    ]
    assert public["holdout"] == {
        "status": "SEALED_UNREAD",
        "execution_rows": 0,
    }
    assert public["holdout_stress"] == {
        "status": "SEALED_UNREAD",
        "execution_rows": 0,
    }
    with get_connection(database, read_only=True) as connection:
        executions = connection.execute(
            """
            SELECT research_run_id, scenario, status, scenario_passed
            FROM backtest_executions WHERE research_run_id=?
            """,
            (run_id,),
        ).fetchall()
        later_rows = connection.execute(
            """
            SELECT COUNT(*) FROM backtest_executions
            WHERE research_run_id=? AND scenario!='DEVELOPMENT'
            """,
            (run_id,),
        ).fetchone()[0]
        releases = connection.execute(
            "SELECT COUNT(*) FROM releases WHERE research_run_id=?",
            (run_id,),
        ).fetchone()[0]
    assert [tuple(row) for row in executions] == [
        (run_id, "DEVELOPMENT", "SUCCEEDED", 0)
    ]
    assert later_rows == 0
    assert releases == 0
