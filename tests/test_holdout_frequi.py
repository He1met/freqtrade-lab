"""T1 contracts for optional one-shot FreqUI result copying."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from lab import holdout_run
from lab.database import get_connection, init_database
from lab.frequi import (
    FREQUI_COMPLETION_RECEIPT_NAME,
    configure_frequi,
    scenario_frequi_status,
    unconfigured_frequi,
)


NOW = "2026-01-01T00:00:00.000Z"
SCENARIOS = ("DEVELOPMENT", "HOLDOUT", "HOLDOUT_STRESS")
AVAILABLE_PROBE = {
    "available": True,
    "reason": None,
    "message": "TEST_ONLY available",
    "version": "3.1.1",
    "url": "http://127.0.0.1:18080/backtest",
}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _completed_run(
    tmp_path: Path,
) -> tuple[Path, str, Path, Path, dict[str, tuple[Path, Path]]]:
    database = tmp_path / "lab.sqlite"
    artifact_root = tmp_path / "frozen-artifacts"
    results_root = tmp_path / "frequi-results"
    run_dir = tmp_path / "run"
    artifact_root.mkdir()
    results_root.mkdir()
    run_dir.mkdir()
    init_database(database)

    profile_id = str(uuid4())
    generation_id = str(uuid4())
    candidate_id = str(uuid4())
    research_run_id = str(uuid4())
    code = "class TestOnlyCandidate: pass\n"
    artifacts: dict[str, tuple[Path, Path]] = {}
    for sequence, scenario in enumerate(SCENARIOS, 1):
        slug = scenario.lower().replace("_", "-")
        archive = artifact_root / f"backtest-result-{slug}-{sequence:02d}.zip"
        metadata = archive.with_name(archive.stem + ".meta.json")
        archive.write_bytes(f"TEST_ONLY {scenario} archive\n".encode("ascii"))
        metadata.write_bytes(
            json.dumps(
                {
                    "TestOnlyCandidate": {
                        "backtest_start_time": sequence,
                        "run_id": f"test-only-{scenario.lower()}",
                    }
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("ascii")
            + b"\n"
        )
        artifacts[scenario] = (archive, metadata)

    with get_connection(database) as connection:
        connection.execute(
            """
            INSERT INTO research_profiles (
                id,name,domain,exchange,trading_mode,margin_mode,pairs_json,
                timeframe,detail_timeframe,history_start_date,smoke_days,
                holdout_days,starting_balance,stake_amount,max_open_trades,
                taker_fee_rate,stress_fee_multiplier,max_drawdown_pct,
                min_development_trades,min_holdout_trades,min_profit_factor,
                created_at,updated_at
            ) VALUES (?,?,'OKX_CRYPTO_PERP','okx','futures','isolated',
                      '["ADA/USDT:USDT"]','5m',NULL,'2026-01-01',7,30,
                      1000.0,100.0,1,0.0005,2.0,5.0,30,30,1.1,?,?)
            """,
            (profile_id, f"profile-{profile_id}", NOW, NOW),
        )
        connection.execute(
            """
            INSERT INTO generation_runs (
                id,research_profile_id,source,status,request_json,
                returned_strategy_count,started_at,finished_at,created_at,updated_at
                ) VALUES (?,?,'MANUAL','COMPLETED','{}',1,?,?,?,?)
            """,
            (generation_id, profile_id, NOW, NOW, NOW, NOW),
        )
        connection.execute(
            """
            INSERT INTO candidates (
                id,generation_run_id,source_item_index,display_name,class_name,
                timeframe,code_text,code_sha256,metadata_json,created_at,updated_at
            ) VALUES (?,?,0,'Test Only Candidate','TestOnlyCandidate','5m',?,?,
                      '{}',?,?)
            """,
            (candidate_id, generation_id, code, _sha256(code.encode()), NOW, NOW),
        )
        connection.execute(
            """
            INSERT INTO research_runs (
                id,candidate_id,research_profile_id,trigger_type,status,stage,
                verdict,pipeline_version,freqtrade_version,input_snapshot_json,
                checks_json,run_dir,rejection_reasons_json,created_at,started_at,
                finished_at
            ) VALUES (?,?,?,'MANUAL','COMPLETED','COMPLETED',NULL,
                      'BOUNDED_DEVELOPMENT_V1','2026.7','{}','{}',?,'[]',?,?,?)
            """,
            (
                research_run_id,
                candidate_id,
                profile_id,
                str(run_dir),
                NOW,
                NOW,
                NOW,
            ),
        )
        for sequence, scenario in enumerate(SCENARIOS, 1):
            archive, metadata = artifacts[scenario]
            metrics = {
                "artifact": {
                    "archive_sha256": _sha256(archive.read_bytes()),
                    "metadata_sha256": _sha256(metadata.read_bytes()),
                    "report_member": archive.with_suffix(".json").name,
                    "strategy": "TestOnlyCandidate",
                }
            }
            connection.execute(
                """
                INSERT INTO backtest_executions (
                    id,research_run_id,scenario,status,sequence,timerange_start,
                    timerange_end,timeframe,detail_timeframe,fee_rate,
                    fee_multiplier,command_json,config_path,strategy_path,
                    result_archive_path,return_code,total_trades,profit_pct,
                    max_drawdown_pct,win_rate,profit_factor,metrics_json,
                    scenario_passed,created_at,started_at,finished_at
                ) VALUES (?,?,?,'SUCCEEDED',?,'2026-07-31T00:00:00Z',
                          '2026-08-29T23:55:00Z','5m',NULL,?,?, '{}',?,?,?,0,
                          1,0.1,1.0,100.0,1.0,?,?,?,?,?)
                """,
                (
                    str(uuid4()),
                    research_run_id,
                    scenario,
                    sequence,
                    0.001 if scenario == "HOLDOUT_STRESS" else 0.0005,
                    2.0 if scenario == "HOLDOUT_STRESS" else 1.0,
                    str(run_dir / "config.json"),
                    str(run_dir / "strategy.py"),
                    str(archive),
                    json.dumps(metrics, sort_keys=True, separators=(",", ":")),
                    1 if scenario == "DEVELOPMENT" else None,
                    NOW,
                    NOW,
                    NOW,
                ),
            )
        connection.commit()
    return database, research_run_id, artifact_root, results_root, artifacts


def _public_completed(
    _database: Path,
    research_run_id: str,
    *_args: Any,
    **_kwargs: Any,
) -> dict[str, Any]:
    return {
        "research_run_id": research_run_id,
        "status": "COMPLETED",
        "verdict": None,
        "release_count": 0,
    }


def _database_snapshot(database: Path, research_run_id: str) -> dict[str, Any]:
    with get_connection(database, read_only=True) as connection:
        run = dict(
            connection.execute(
                "SELECT status,stage,verdict,finished_at FROM research_runs WHERE id=?",
                (research_run_id,),
            ).fetchone()
        )
        executions = [
            dict(row)
            for row in connection.execute(
                """
                SELECT scenario,status,result_archive_path,metrics_json
                FROM backtest_executions
                WHERE research_run_id=? ORDER BY sequence
                """,
                (research_run_id,),
            ).fetchall()
        ]
    return {"run": run, "executions": executions}


def _scenario_statuses(
    database: Path,
    research_run_id: str,
    config: Any,
) -> dict[str, dict[str, Any]]:
    with get_connection(database, read_only=True) as connection:
        rows = connection.execute(
            """
            SELECT scenario,result_archive_path,metrics_json
            FROM backtest_executions
            WHERE research_run_id=? ORDER BY sequence
            """,
            (research_run_id,),
        ).fetchall()
    return {
        str(row["scenario"]): scenario_frequi_status(
            config,
            AVAILABLE_PROBE,
            research_run_id=research_run_id,
            raw_archive_path=row["result_archive_path"],
            raw_metrics=row["metrics_json"],
            candidate_class_name="TestOnlyCandidate",
            canonical_artifact_available=True,
        )
        for row in rows
    }


def test_unconfigured_frequi_returns_unavailable_without_copying(
    tmp_path: Path,
) -> None:
    database, research_run_id, artifact_root, results_root, _ = _completed_run(
        tmp_path
    )
    before = _database_snapshot(database, research_run_id)

    result = holdout_run.copy_frequi_results(
        database,
        research_run_id,
        artifact_root,
        unconfigured_frequi(),
    )

    assert result == {"status": "UNAVAILABLE", "reason": "FreqUI is not configured"}
    assert list(results_root.iterdir()) == []
    assert _database_snapshot(database, research_run_id) == before


def test_copy_uses_distinct_regular_o_excl_files_with_single_links(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database, research_run_id, artifact_root, results_root, artifacts = _completed_run(
        tmp_path
    )
    config = configure_frequi(
        "http://127.0.0.1:18080",
        results_root,
        artifact_root=artifact_root,
    )
    monkeypatch.setattr(holdout_run, "load_public_research_run", _public_completed)

    result = holdout_run.copy_frequi_results(
        database, research_run_id, artifact_root, config
    )

    assert result["status"] == "COPIED"
    assert result["research_run_id"] == research_run_id
    assert [item["scenario"] for item in result["files"]] == list(SCENARIOS)
    completion = results_root / FREQUI_COMPLETION_RECEIPT_NAME
    completion_info = os.lstat(completion)
    assert stat.S_ISREG(completion_info.st_mode)
    assert completion_info.st_nlink == 1
    assert all(
        status["available"] is True
        for status in _scenario_statuses(
            database, research_run_id, config
        ).values()
    )
    for archive, metadata in artifacts.values():
        for source in (archive, metadata):
            destination = results_root / source.name
            source_info = os.lstat(source)
            destination_info = os.lstat(destination)
            assert stat.S_ISREG(source_info.st_mode)
            assert stat.S_ISREG(destination_info.st_mode)
            assert source_info.st_nlink == destination_info.st_nlink == 1
            assert (source_info.st_dev, source_info.st_ino) != (
                destination_info.st_dev,
                destination_info.st_ino,
            )
            assert destination.read_bytes() == source.read_bytes()


def test_all_six_sources_are_validated_before_any_destination_is_published(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database, research_run_id, artifact_root, results_root, artifacts = _completed_run(
        tmp_path
    )
    config = configure_frequi(
        "http://127.0.0.1:18080",
        results_root,
        artifact_root=artifact_root,
    )
    monkeypatch.setattr(holdout_run, "load_public_research_run", _public_completed)
    artifacts["HOLDOUT_STRESS"][1].write_bytes(b"TEST_ONLY drifted metadata\n")

    with pytest.raises(holdout_run.HoldoutRunError) as raised:
        holdout_run.copy_frequi_results(
            database, research_run_id, artifact_root, config
        )

    assert raised.value.code == "presentation_unavailable"
    assert list(results_root.iterdir()) == []


def test_mid_publish_failure_never_returns_a_copied_declaration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database, research_run_id, artifact_root, results_root, _ = _completed_run(
        tmp_path
    )
    config = configure_frequi(
        "http://127.0.0.1:18080",
        results_root,
        artifact_root=artifact_root,
    )
    monkeypatch.setattr(holdout_run, "load_public_research_run", _public_completed)
    real_write = holdout_run._write_exclusive_at
    calls = 0

    def fail_third_publish(
        directory_fd: int,
        name: str,
        data: bytes,
        mode: int = 0o400,
    ) -> None:
        nonlocal calls
        calls += 1
        if calls == 3:
            raise OSError("TEST_ONLY injected publication failure")
        real_write(directory_fd, name, data, mode)

    monkeypatch.setattr(holdout_run, "_write_exclusive_at", fail_third_publish)

    with pytest.raises(holdout_run.HoldoutRunError) as raised:
        holdout_run.copy_frequi_results(
            database, research_run_id, artifact_root, config
        )

    assert raised.value.code == "presentation_unavailable"
    assert len(list(results_root.iterdir())) == 2
    assert not (results_root / FREQUI_COMPLETION_RECEIPT_NAME).exists()
    assert all(
        status["available"] is False
        for status in _scenario_statuses(
            database, research_run_id, config
        ).values()
    )
    with pytest.raises(holdout_run.HoldoutRunError) as repeated:
        holdout_run.copy_frequi_results(
            database, research_run_id, artifact_root, config
        )
    assert repeated.value.code == "presentation_unavailable"


def test_second_copy_conflict_never_overwrites_and_failure_keeps_completed_db(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database, research_run_id, artifact_root, results_root, _ = _completed_run(
        tmp_path
    )
    config = configure_frequi(
        "http://127.0.0.1:18080",
        results_root,
        artifact_root=artifact_root,
    )
    monkeypatch.setattr(holdout_run, "load_public_research_run", _public_completed)
    holdout_run.copy_frequi_results(database, research_run_id, artifact_root, config)
    file_state = {
        path.name: (path.read_bytes(), os.lstat(path).st_ino, os.lstat(path).st_nlink)
        for path in results_root.iterdir()
    }
    database_state = _database_snapshot(database, research_run_id)

    with pytest.raises(holdout_run.HoldoutRunError) as repeated:
        holdout_run.copy_frequi_results(
            database, research_run_id, artifact_root, config
        )

    assert repeated.value.code == "presentation_unavailable"
    assert {
        path.name: (path.read_bytes(), os.lstat(path).st_ino, os.lstat(path).st_nlink)
        for path in results_root.iterdir()
    } == file_state
    assert _database_snapshot(database, research_run_id) == database_state
    assert database_state["run"] == {
        "status": "COMPLETED",
        "stage": "COMPLETED",
        "verdict": None,
        "finished_at": NOW,
    }


def test_occupied_disposable_root_is_rejected_without_copying(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database, research_run_id, artifact_root, results_root, _ = _completed_run(
        tmp_path
    )
    prior = results_root / "prior-unrelated.txt"
    prior.write_text("must remain isolated\n")
    config = configure_frequi(
        "http://127.0.0.1:18080",
        results_root,
        artifact_root=artifact_root,
    )
    monkeypatch.setattr(holdout_run, "load_public_research_run", _public_completed)
    before = _database_snapshot(database, research_run_id)

    with pytest.raises(holdout_run.HoldoutRunError) as raised:
        holdout_run.copy_frequi_results(
            database, research_run_id, artifact_root, config
        )

    assert raised.value.code == "presentation_unavailable"
    assert [path.name for path in results_root.iterdir()] == [prior.name]
    assert prior.read_text() == "must remain isolated\n"
    assert _database_snapshot(database, research_run_id) == before


def test_destination_replacement_after_open_cannot_redirect_copies(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database, research_run_id, artifact_root, results_root, _ = _completed_run(
        tmp_path
    )
    config = configure_frequi(
        "http://127.0.0.1:18080",
        results_root,
        artifact_root=artifact_root,
    )
    monkeypatch.setattr(holdout_run, "load_public_research_run", _public_completed)
    original_results = tmp_path / "opened-results-root"
    replacement = tmp_path / "replacement-results-root"
    replacement.mkdir()
    real_write = holdout_run._write_exclusive_at
    swapped = False

    def swap_then_write(
        directory_fd: int,
        name: str,
        data: bytes,
        mode: int = 0o400,
    ) -> None:
        nonlocal swapped
        if not swapped:
            results_root.rename(original_results)
            results_root.symlink_to(replacement, target_is_directory=True)
            swapped = True
        real_write(directory_fd, name, data, mode)

    monkeypatch.setattr(holdout_run, "_write_exclusive_at", swap_then_write)

    with pytest.raises(holdout_run.HoldoutRunError) as raised:
        holdout_run.copy_frequi_results(
            database, research_run_id, artifact_root, config
        )

    assert raised.value.code == "presentation_unavailable"
    assert swapped is True
    assert list(replacement.iterdir()) == []
    assert len(list(original_results.iterdir())) == 7
