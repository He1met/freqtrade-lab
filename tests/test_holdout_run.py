"""T0/T1 contracts for the one-shot Holdout/Stress continuation."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from lab import backtest_artifact, development_run, holdout_run, research_bundle
from lab.database import get_connection
from tests.test_development_run import (
    BOUNDED_SOURCE,
    NOW,
    ROLLING_DEVELOPMENT_TIMERANGE,
    ROLLING_HOLDOUT_TIMERANGE,
    _approved_candidate_database,
    _configure_legacy_window_fixture,
    _configure_rolling_window_fixture,
    _frozen_capability_fixture,
    _timerange_datetimes,
)


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "freqtrade_2026_7"
DEVELOPMENT_ARCHIVE = "backtest-result-2026-08-30_12-55-02.zip"
DEVELOPMENT_PROVENANCE = "backtest-result-2026-08-30_12-55-02.provenance.json"
RESULT_FIELDS = (
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
)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _eligible_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    development_timerange: str = "20260601-20260731",
    holdout_timerange: str = "20260731-20260830",
    window_schema: str | None = None,
) -> tuple[
    Path,
    str,
    Path,
    holdout_run.FrozenHoldoutCapability,
    backtest_artifact.ParsedBacktestArtifact,
]:
    """Create a real approved Candidate and a passed Development-only Run.

    Only the artifact parser boundary is replaced in callers: the SQLite rows,
    frozen Candidate/Profile bindings, input materialization, and Gate transition
    remain production behavior.  The adapted tracked artifact is explicitly
    TEST_ONLY_SYNTHETIC and is never presented as economic evidence.
    """

    pair = "XRP/USDT:USDT"
    instrument_id = "XRP-USDT-SWAP"
    holdout_start, holdout_stop = _timerange_datetimes(holdout_timerange)
    database, candidate_id = _approved_candidate_database(
        tmp_path / "database",
        pair=pair,
        holdout_days=(holdout_stop - holdout_start).days,
    )
    pilot_root, freqtrade_python, freqtrade_source = _frozen_capability_fixture(
        tmp_path / "capability",
        monkeypatch,
        pair=pair,
        instrument_id=instrument_id,
    )
    rolling = (
        development_timerange != "20260601-20260731"
        or holdout_timerange != "20260731-20260830"
    )
    if window_schema == "v1":
        _configure_legacy_window_fixture(
            pilot_root,
            holdout_timerange=holdout_timerange,
        )
    elif rolling:
        _configure_rolling_window_fixture(
            pilot_root,
            development_timerange=development_timerange,
            holdout_timerange=holdout_timerange,
        )
    development_capability = development_run.freeze_development_capability(
        pilot_root, freqtrade_python, freqtrade_source
    )
    assert development_capability.status == "READY"
    frozen_holdout_capability = (
        holdout_run.freeze_holdout_capability(
            pilot_root, freqtrade_python, freqtrade_source
        )
        if rolling
        else None
    )
    if frozen_holdout_capability is not None:
        assert frozen_holdout_capability.status == "READY"

    research_run_id = str(uuid4())
    run_dir = tmp_path / "runtime" / research_run_id
    run_dir.mkdir(parents=True)
    development_run.prepare_development_run(
        database,
        run_dir,
        candidate_id,
        development_capability,
        research_run_id=research_run_id,
        now=NOW,
    )

    provenance_sha256 = _sha256((FIXTURE_ROOT / DEVELOPMENT_PROVENANCE).read_bytes())
    tracked = backtest_artifact.parse_backtest_artifact(
        FIXTURE_ROOT,
        DEVELOPMENT_ARCHIVE,
        "StrategyTestV3Futures",
        "2026.7",
        provenance_sha256,
    )
    evidence = run_dir / "development-evidence"
    evidence.mkdir()
    archive = evidence / "development-01.zip"
    provenance = evidence / "development-01.provenance.json"
    metadata = evidence / "development-01.meta.json"
    archive.write_bytes(b"TEST_ONLY_SYNTHETIC development artifact\n")
    provenance.write_bytes(b'{"test_only_synthetic":true}\n')
    metadata.write_bytes(b'{"test_only_synthetic":true}\n')
    source_sha256 = _sha256(BOUNDED_SOURCE.encode("utf-8"))
    development_start, development_stop = _timerange_datetimes(
        development_timerange
    )
    parsed = replace(
        tracked,
        archive_path=archive,
        archive_sha256=_sha256(archive.read_bytes()),
        metadata_sha256=_sha256(metadata.read_bytes()),
        provenance_sha256=_sha256(provenance.read_bytes()),
        strategy="BoundedCandidate",
        strategy_member="development-01_BoundedCandidate.py",
        strategy_source=BOUNDED_SOURCE,
        strategy_sha256=source_sha256,
        pairs=(pair,),
        backtest_start=development_start.isoformat().replace("+00:00", "Z"),
        backtest_end=(development_stop - timedelta(minutes=5))
        .isoformat()
        .replace("+00:00", "Z"),
        configured_fee=0.0005,
        total_trades=30,
        profit_pct=0.5,
        max_drawdown_pct=5.0,
        win_rate=66.6666666667,
        profit_factor=1.1,
        wins=20,
        draws=0,
        losses=10,
    )
    values = backtest_artifact.execution_result_values(parsed)
    with get_connection(database) as connection:
        changed = connection.execute(
            """
            UPDATE backtest_executions
            SET status='SUCCEEDED', result_archive_path=:result_archive_path,
                stdout_path=NULL, stderr_path=NULL, return_code=0,
                total_trades=:total_trades, profit_pct=:profit_pct,
                max_drawdown_pct=:max_drawdown_pct, win_rate=:win_rate,
                profit_factor=:profit_factor, sharpe=:sharpe, sortino=:sortino,
                calmar=:calmar, long_profit_pct=:long_profit_pct,
                short_profit_pct=:short_profit_pct, metrics_json=:metrics_json,
                scenario_passed=NULL, error_message=NULL, finished_at=:finished_at
            WHERE research_run_id=:research_run_id AND scenario='DEVELOPMENT'
            """,
            {**values, "research_run_id": research_run_id, "finished_at": NOW},
        ).rowcount
        assert changed == 1
        connection.commit()
    development_run.finalize_development_gate(database, research_run_id)

    acquisition = pilot_root / "acquisition"
    development_data = (
        pilot_root
        / "development-isolation"
        / "data"
        / "okx"
        / "futures"
        / "XRP-5m.feather"
    )
    full_data = acquisition / "data" / "okx" / "futures" / "XRP-5m.feather"
    full_data.parent.mkdir(parents=True, exist_ok=True)
    full_data.write_bytes(development_data.read_bytes() + b"holdout-only\n")
    local_paths = (
        acquisition / "market_snapshot.json",
        acquisition / "isolated_tiers_snapshot.json",
        full_data,
    )
    local_receipts = tuple(
        (
            path.relative_to(acquisition).as_posix(),
            len(path.read_bytes()),
            _sha256(path.read_bytes()),
            None,
        )
        for path in local_paths
    )
    acquisition_provenance = acquisition / "retained-data-provenance.json"
    capability = frozen_holdout_capability or holdout_run.FrozenHoldoutCapability(
        status="READY",
        reason="TEST_ONLY_SYNTHETIC ready capability",
        development=development_capability,
        pilot_root=pilot_root,
        freqtrade_python=freqtrade_python,
        freqtrade_source=freqtrade_source,
        plan_sha256=_sha256((pilot_root / "pilot-spec.json").read_bytes()),
        acquisition_provenance_sha256=_sha256(acquisition_provenance.read_bytes()),
        config_sha256=_sha256((acquisition / "config.json").read_bytes()),
        runner_sha256=_sha256(holdout_run.DEFAULT_RUNNER.read_bytes()),
        development_timerange=development_timerange,
        holdout_timerange=holdout_timerange,
        stress_fee_multiplier=2.0,
        pair=pair,
        local_receipts=local_receipts,
    )
    return database, research_run_id, run_dir, capability, parsed


def _execution_rows(database: Path, research_run_id: str) -> list[dict[str, Any]]:
    with get_connection(database, read_only=True) as connection:
        rows = connection.execute(
            """
            SELECT * FROM backtest_executions
            WHERE research_run_id=? ORDER BY sequence
            """,
            (research_run_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def _assert_no_later_rows(database: Path, research_run_id: str) -> None:
    rows = _execution_rows(database, research_run_id)
    assert [(row["scenario"], row["sequence"]) for row in rows] == [
        ("DEVELOPMENT", 1)
    ]


def _assert_empty_result(row: dict[str, Any]) -> None:
    assert row["metrics_json"] == "{}"
    for field in RESULT_FIELDS:
        assert row[field] is None, field


def _prepare_continuation(
    database: Path,
    research_run_id: str,
    run_dir: Path,
    capability: holdout_run.FrozenHoldoutCapability,
    parsed_development: backtest_artifact.ParsedBacktestArtifact,
    monkeypatch: pytest.MonkeyPatch,
) -> holdout_run.PreparedHoldoutContinuation:
    monkeypatch.setattr(
        holdout_run,
        "_require_ready",
        lambda _capability: None,
    )
    monkeypatch.setattr(
        holdout_run,
        "parse_backtest_artifact",
        lambda *_args, **_kwargs: parsed_development,
    )
    return holdout_run.prepare_holdout_continuation(
        database,
        run_dir,
        research_run_id,
        capability,
        now=NOW,
    )


def test_t0_schema_blob_and_six_business_tables_remain_exact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    schema = Path(__file__).parents[1] / "sql" / "schema_v1.sql"
    data = schema.read_bytes()
    git_blob = hashlib.sha1(
        f"blob {len(data)}\0".encode("ascii") + data,
        usedforsecurity=False,
    ).hexdigest()
    assert git_blob == "2447bf90447a333a703e208a4ec6503fb7c5112b"

    database, _, _, _, _ = _eligible_run(tmp_path, monkeypatch)
    with get_connection(database, read_only=True) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_schema "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
    assert tables == {
        "research_profiles",
        "generation_runs",
        "candidates",
        "research_runs",
        "backtest_executions",
        "releases",
    }


def test_t0_one_shot_receipt_fsyncs_file_and_parent_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed_modes: list[int] = []
    real_fsync = holdout_run.os.fsync

    def recording_fsync(descriptor: int) -> None:
        observed_modes.append(os.fstat(descriptor).st_mode)
        real_fsync(descriptor)

    monkeypatch.setattr(holdout_run.os, "fsync", recording_fsync)

    holdout_run._write_exclusive(
        tmp_path / holdout_run.HOLDOUT_ATTEMPT_NAME,
        b"{}\n",
        sync_parent=True,
    )

    assert any(stat.S_ISREG(mode) for mode in observed_modes)
    assert stat.S_ISDIR(observed_modes[-1])


def test_t1_rolling_v2_60_30_prepares_contiguous_holdout_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database, research_run_id, run_dir, capability, parsed = _eligible_run(
        tmp_path,
        monkeypatch,
        development_timerange=ROLLING_DEVELOPMENT_TIMERANGE,
        holdout_timerange=ROLLING_HOLDOUT_TIMERANGE,
    )

    assert capability.status == "READY"
    assert capability.development_timerange == ROLLING_DEVELOPMENT_TIMERANGE
    assert capability.holdout_timerange == ROLLING_HOLDOUT_TIMERANGE
    _prepare_continuation(
        database,
        research_run_id,
        run_dir,
        capability,
        parsed,
        monkeypatch,
    )

    rows = _execution_rows(database, research_run_id)
    assert [
        (
            row["scenario"],
            row["timerange_start"],
            row["timerange_end"],
        )
        for row in rows
    ] == [
        (
            "DEVELOPMENT",
            "2026-04-01T00:00:00Z",
            "2026-05-30T23:55:00Z",
        ),
        (
            "HOLDOUT",
            "2026-05-31T00:00:00Z",
            "2026-06-29T23:55:00Z",
        ),
        (
            "HOLDOUT_STRESS",
            "2026-05-31T00:00:00Z",
            "2026-06-29T23:55:00Z",
        ),
    ]
    authorization = json.loads(
        (run_dir / "holdout-input" / "authorization.json").read_text()
    )
    assert authorization["holdout_timerange"] == ROLLING_HOLDOUT_TIMERANGE
    provenance = json.loads(
        (
            run_dir / "holdout-input" / "retained-data-provenance.json"
        ).read_text()
    )
    assert provenance["contract"]["development_timerange"] == (
        ROLLING_DEVELOPMENT_TIMERANGE
    )
    assert provenance["contract"]["holdout_timerange"] == (
        ROLLING_HOLDOUT_TIMERANGE
    )


def test_t1_legacy_v1_short_holdout_remains_authorizable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    holdout_timerange = "20260731-20260807"
    database, research_run_id, run_dir, capability, parsed = _eligible_run(
        tmp_path,
        monkeypatch,
        holdout_timerange=holdout_timerange,
        window_schema="v1",
    )

    assert capability.status == "READY"
    assert capability.development is not None
    assert capability.development.window_schema == "freqtrade-lab-okx-window-v1"
    _prepare_continuation(
        database,
        research_run_id,
        run_dir,
        capability,
        parsed,
        monkeypatch,
    )

    rows = _execution_rows(database, research_run_id)
    assert [row["scenario"] for row in rows] == [
        "DEVELOPMENT",
        "HOLDOUT",
        "HOLDOUT_STRESS",
    ]
    assert rows[1]["timerange_start"] == "2026-07-31T00:00:00Z"
    assert rows[1]["timerange_end"] == "2026-08-06T23:55:00Z"
    assert rows[2]["timerange_start"] == "2026-07-31T00:00:00Z"
    assert rows[2]["timerange_end"] == "2026-08-06T23:55:00Z"


@pytest.mark.parametrize(
    "holdout_timerange",
    (
        pytest.param("20260731-20260829", id="29-days"),
        pytest.param("20260731-20260831", id="31-days"),
        pytest.param("20260801-20260831", id="gap"),
        pytest.param("20260730-20260829", id="overlap"),
    ),
)
def test_t0_holdout_window_drift_fails_before_attempt_or_database_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    holdout_timerange: str,
) -> None:
    database, research_run_id, run_dir, capability, parsed = _eligible_run(
        tmp_path, monkeypatch
    )
    drifted = replace(capability, holdout_timerange=holdout_timerange)
    monkeypatch.setattr(
        holdout_run,
        "parse_backtest_artifact",
        lambda *_args, **_kwargs: parsed,
    )
    monkeypatch.setattr(
        holdout_run,
        "_require_ready",
        lambda _capability: pytest.fail(
            "invalid window must fail before retained inputs are opened"
        ),
    )

    with pytest.raises(holdout_run.HoldoutRunError) as raised:
        holdout_run.prepare_holdout_continuation(
            database,
            run_dir,
            research_run_id,
            drifted,
            now=NOW,
        )

    assert (raised.value.code, raised.value.status) == ("run_not_eligible", 409)
    _assert_no_later_rows(database, research_run_id)
    assert not (run_dir / holdout_run.HOLDOUT_ATTEMPT_NAME).exists()
    assert not (run_dir / "holdout-input").exists()
    with get_connection(database, read_only=True) as connection:
        run = connection.execute(
            "SELECT status,stage,verdict FROM research_runs WHERE id=?",
            (research_run_id,),
        ).fetchone()
    assert tuple(run) == ("PENDING", "PENDING", None)


def test_t0_shifted_30_day_authorization_receipt_fails_before_database_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database, research_run_id, run_dir, capability, parsed = _eligible_run(
        tmp_path, monkeypatch
    )
    real_authorize = holdout_run._authorize_holdout_run
    captured: dict[str, Any] = {}

    def capture_receipt(
        _database: Path,
        _research_run_id: str,
        receipt: dict[str, Any],
        **_kwargs: Any,
    ) -> None:
        captured.update(receipt)

    monkeypatch.setattr(holdout_run, "_authorize_holdout_run", capture_receipt)
    _prepare_continuation(
        database,
        research_run_id,
        run_dir,
        capability,
        parsed,
        monkeypatch,
    )
    forged = dict(captured)
    forged["holdout_timerange"] = "20260801-20260831"
    monkeypatch.setattr(holdout_run, "_authorize_holdout_run", real_authorize)

    with pytest.raises(holdout_run.HoldoutRunError) as raised:
        holdout_run._authorize_holdout_run(
            database,
            research_run_id,
            forged,
            now=NOW,
        )

    assert (raised.value.code, raised.value.status) == ("BLOCKED_DATA", 503)
    assert raised.value.message == "Holdout authorization receipt drifted"
    _assert_no_later_rows(database, research_run_id)
    with get_connection(database, read_only=True) as connection:
        run = connection.execute(
            "SELECT status,stage,verdict FROM research_runs WHERE id=?",
            (research_run_id,),
        ).fetchone()
    assert tuple(run) == ("PENDING", "PENDING", None)


def test_t0_prepare_uses_same_run_seq_2_3_and_consumes_authorization_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database, research_run_id, run_dir, capability, parsed = _eligible_run(
        tmp_path, monkeypatch
    )
    with get_connection(database, read_only=True) as connection:
        before = {
            "research_runs": connection.execute(
                "SELECT COUNT(*) FROM research_runs"
            ).fetchone()[0],
            "candidates": connection.execute(
                "SELECT COUNT(*) FROM candidates"
            ).fetchone()[0],
            "generation_runs": connection.execute(
                "SELECT COUNT(*) FROM generation_runs"
            ).fetchone()[0],
        }
        development_before = dict(
            connection.execute(
                "SELECT * FROM backtest_executions "
                "WHERE research_run_id=? AND scenario='DEVELOPMENT'",
                (research_run_id,),
            ).fetchone()
        )

    prepared = _prepare_continuation(
        database,
        research_run_id,
        run_dir,
        capability,
        parsed,
        monkeypatch,
    )

    assert prepared.research_run_id == research_run_id
    assert prepared.run_dir == run_dir
    with get_connection(database, read_only=True) as connection:
        run = connection.execute(
            "SELECT status,stage,verdict,finished_at FROM research_runs WHERE id=?",
            (research_run_id,),
        ).fetchone()
        counts = {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in before
        }
        release_count = connection.execute(
            "SELECT COUNT(*) FROM releases WHERE research_run_id=?",
            (research_run_id,),
        ).fetchone()[0]
    rows = _execution_rows(database, research_run_id)
    assert tuple(run) == ("RUNNING", "HOLDOUT_BACKTEST", None, None)
    assert counts == before
    assert [(row["scenario"], row["sequence"], row["status"]) for row in rows] == [
        ("DEVELOPMENT", 1, "SUCCEEDED"),
        ("HOLDOUT", 2, "PENDING"),
        ("HOLDOUT_STRESS", 3, "PENDING"),
    ]
    assert {
        key: rows[0][key]
        for key in development_before
    } == development_before
    assert release_count == 0
    provenance = json.loads(
        (run_dir / "holdout-input" / "retained-data-provenance.json").read_text()
    )
    assert provenance["source"]["instrument_id"] == "XRP-USDT-SWAP"

    second_dir = tmp_path / "second-attempt"
    second_dir.mkdir()
    with pytest.raises(holdout_run.HoldoutRunError) as raised:
        holdout_run.prepare_holdout_continuation(
            database,
            second_dir,
            research_run_id,
            capability,
            now=NOW,
        )
    assert raised.value.status == 409
    assert len(_execution_rows(database, research_run_id)) == 3


def test_t0_child_manifest_check_does_not_open_retained_market_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database, research_run_id, run_dir, capability, parsed = _eligible_run(
        tmp_path, monkeypatch
    )
    _prepare_continuation(
        database,
        research_run_id,
        run_dir,
        capability,
        parsed,
        monkeypatch,
    )
    real_read_regular = holdout_run._read_regular

    def guard_retained_bytes(
        path: Path, label: str, limit: int = 64 * 1024 * 1024
    ) -> bytes:
        relative = Path(path).relative_to(run_dir / "holdout-input").as_posix()
        if relative in {
            "market_snapshot.json",
            "isolated_tiers_snapshot.json",
        } or relative.startswith("data/okx/"):
            raise AssertionError(
                f"retained market bytes opened before scenario receipt: {relative}"
            )
        return real_read_regular(Path(path), label, limit)

    monkeypatch.setattr(holdout_run, "_read_regular", guard_retained_bytes)

    manifest, authorization = holdout_run._load_holdout_input(
        run_dir, research_run_id
    )

    assert manifest["research_run_id"] == research_run_id
    assert authorization["action"] == "AUTHORIZE_HOLDOUT"


@pytest.mark.parametrize(
    ("relative", "is_directory"),
    (
        (".holdout-input-preparing", True),
        (".holdout-attempt.json", False),
        ("holdout-input", True),
        ("holdout-runtime", True),
        ("holdout-receipts", True),
        ("holdout-evidence", True),
        ("holdout-result.json", False),
        ("holdout-request.json", False),
        ("holdout-status.json", False),
        ("holdout-owner.json", False),
        ("holdout.stdout.log", False),
        ("holdout.stderr.log", False),
    ),
)
def test_t0_any_residual_continuation_directory_consumes_public_authorization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    relative: str,
    is_directory: bool,
) -> None:
    database, research_run_id, run_dir, capability, parsed = _eligible_run(
        tmp_path, monkeypatch
    )
    if is_directory:
        (run_dir / relative).mkdir()
    else:
        (run_dir / relative).write_text("prior attempt\n")
    monkeypatch.setattr(
        holdout_run,
        "parse_backtest_artifact",
        lambda *_args, **_kwargs: parsed,
    )

    public = holdout_run.load_public_research_run(
        database, research_run_id, capability
    )

    assert public["authorization"]["status"] == "CONSUMED_OR_INTERRUPTED"
    assert public["authorization"]["can_authorize"] is False
    monkeypatch.setattr(
        holdout_run,
        "_require_ready",
        lambda _capability: pytest.fail(
            "residual authorization must block before retained inputs are opened"
        ),
    )
    with pytest.raises(holdout_run.HoldoutRunError) as raised:
        holdout_run.prepare_holdout_continuation(
            database,
            run_dir,
            research_run_id,
            capability,
            now=NOW,
        )
    assert (raised.value.code, raised.value.status) == ("already_authorized", 409)


def test_t0_materialization_failure_consumes_the_one_shot_action(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database, research_run_id, run_dir, capability, parsed = _eligible_run(
        tmp_path, monkeypatch
    )
    monkeypatch.setattr(holdout_run, "_require_ready", lambda _capability: None)
    monkeypatch.setattr(
        holdout_run,
        "parse_backtest_artifact",
        lambda *_args, **_kwargs: parsed,
    )
    real_copy = holdout_run._copy_frozen_input
    monkeypatch.setattr(
        holdout_run,
        "_copy_frozen_input",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            holdout_run.HoldoutRunError(
                "BLOCKED_DATA", "TEST_ONLY materialization failure"
            )
        ),
    )

    with pytest.raises(holdout_run.HoldoutRunError) as first:
        holdout_run.prepare_holdout_continuation(
            database,
            run_dir,
            research_run_id,
            capability,
            now=NOW,
        )

    assert first.value.code == "BLOCKED_DATA"
    assert (run_dir / holdout_run.HOLDOUT_ATTEMPT_NAME).is_file()
    assert not (run_dir / "holdout-input").exists()
    _assert_no_later_rows(database, research_run_id)

    monkeypatch.setattr(holdout_run, "_copy_frozen_input", real_copy)
    monkeypatch.setattr(
        holdout_run,
        "_require_ready",
        lambda _capability: pytest.fail(
            "a failed one-shot action must reject before reopening retained inputs"
        ),
    )
    with pytest.raises(holdout_run.HoldoutRunError) as repeated:
        holdout_run.prepare_holdout_continuation(
            database,
            run_dir,
            research_run_id,
            capability,
            now=NOW,
        )
    assert (repeated.value.code, repeated.value.status) == (
        "already_authorized",
        409,
    )


def test_t0_db_authorization_failure_preserves_one_shot_attempt_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database, research_run_id, run_dir, capability, parsed = _eligible_run(
        tmp_path, monkeypatch
    )
    real_authorize = holdout_run._authorize_holdout_run
    monkeypatch.setattr(holdout_run, "_require_ready", lambda _capability: None)
    monkeypatch.setattr(
        holdout_run,
        "parse_backtest_artifact",
        lambda *_args, **_kwargs: parsed,
    )
    monkeypatch.setattr(
        holdout_run,
        "_authorize_holdout_run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            holdout_run.HoldoutRunError(
                "authorization_failed", "TEST_ONLY injected DB authorization failure"
            )
        ),
    )

    with pytest.raises(holdout_run.HoldoutRunError) as first:
        holdout_run.prepare_holdout_continuation(
            database,
            run_dir,
            research_run_id,
            capability,
            now=NOW,
        )

    assert first.value.code == "authorization_failed"
    authorization = run_dir / "holdout-input" / "authorization.json"
    assert authorization.is_file()
    _assert_no_later_rows(database, research_run_id)
    public = holdout_run.load_public_research_run(
        database, research_run_id, capability
    )
    assert public["authorization"]["status"] == "CONSUMED_OR_INTERRUPTED"

    monkeypatch.setattr(holdout_run, "_authorize_holdout_run", real_authorize)
    monkeypatch.setattr(
        holdout_run,
        "_require_ready",
        lambda _capability: pytest.fail(
            "consumed failed authorization must block before retained inputs reopen"
        ),
    )
    with pytest.raises(holdout_run.HoldoutRunError) as repeated:
        holdout_run.prepare_holdout_continuation(
            database,
            run_dir,
            research_run_id,
            capability,
            now=NOW,
        )
    assert repeated.value.code == "already_authorized"


def test_t0_profile_drift_before_authorization_write_lock_creates_no_later_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database, research_run_id, run_dir, capability, parsed = _eligible_run(
        tmp_path, monkeypatch
    )
    real_authorize = holdout_run._authorize_holdout_run

    def drift_then_authorize(*args: Any, **kwargs: Any):
        with get_connection(database) as connection:
            connection.execute(
                "UPDATE research_profiles SET starting_balance=starting_balance+1 "
                "WHERE id=(SELECT research_profile_id FROM research_runs WHERE id=?)",
                (research_run_id,),
            )
            connection.commit()
        return real_authorize(*args, **kwargs)

    monkeypatch.setattr(
        holdout_run,
        "_authorize_holdout_run",
        drift_then_authorize,
    )

    with pytest.raises(holdout_run.HoldoutRunError) as raised:
        _prepare_continuation(
            database,
            research_run_id,
            run_dir,
            capability,
            parsed,
            monkeypatch,
        )

    assert raised.value.code == "BLOCKED_DATA"
    assert (run_dir / holdout_run.HOLDOUT_ATTEMPT_NAME).is_file()
    assert (run_dir / "holdout-input" / "authorization.json").is_file()
    _assert_no_later_rows(database, research_run_id)


@pytest.mark.parametrize(
    ("mutation", "parameters"),
    (
        (
            "UPDATE research_runs SET pipeline_version=? WHERE id=?",
            ("OTHER_PIPELINE",),
        ),
        (
            "UPDATE research_runs SET status='RUNNING', stage='HOLDOUT_BACKTEST' "
            "WHERE id=?",
            (),
        ),
        (
            "UPDATE research_runs SET checks_json=? WHERE id=?",
            (
                json.dumps(
                    {
                        "candidate_binding": "PASSED",
                        "security_gate": "PASSED",
                        "development_data": "PHYSICALLY_ISOLATED",
                        "development_gate": "PASSED",
                        "next_phase": "NONE_REJECTED",
                        "holdout": "SEALED_UNREAD",
                        "holdout_stress": "SEALED_UNREAD",
                    },
                    separators=(",", ":"),
                ),
            ),
        ),
        (
            "UPDATE backtest_executions SET scenario_passed=0 "
            "WHERE research_run_id=? AND scenario='DEVELOPMENT'",
            (),
        ),
        (
            "UPDATE candidates SET code_text=code_text || ? "
            "WHERE id=(SELECT candidate_id FROM research_runs WHERE id=?)",
            ("\n# drift",),
        ),
    ),
)
def test_t0_authorization_eligibility_truth_table_fails_without_side_effects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
    parameters: tuple[Any, ...],
) -> None:
    database, research_run_id, run_dir, capability, parsed = _eligible_run(
        tmp_path, monkeypatch
    )
    with get_connection(database) as connection:
        connection.execute(mutation, (*parameters, research_run_id))
        connection.commit()
    monkeypatch.setattr(
        holdout_run,
        "_require_ready",
        lambda _capability: pytest.fail(
            "ineligible Run must not open startup-frozen retained inputs"
        ),
    )
    monkeypatch.setattr(
        holdout_run,
        "parse_backtest_artifact",
        lambda *_args, **_kwargs: parsed,
    )

    with pytest.raises(holdout_run.HoldoutRunError) as raised:
        holdout_run.prepare_holdout_continuation(
            database,
            run_dir,
            research_run_id,
            capability,
            now=NOW,
        )

    assert raised.value.status == 409
    _assert_no_later_rows(database, research_run_id)
    assert not (run_dir / "holdout-input").exists()


def _write_open_receipt(run_dir: Path, scenario: str) -> None:
    receipts = run_dir / "holdout-receipts"
    receipts.mkdir(exist_ok=True)
    name = (
        "holdout-open.json"
        if scenario == "HOLDOUT"
        else "holdout-stress-open.json"
    )
    (receipts / name).write_text(
        '{"schema":"TEST_ONLY_SYNTHETIC_SCENARIO_OPEN"}\n',
        encoding="utf-8",
    )


def test_t1_failure_maps_opened_failed_unopened_skipped_and_clears_results(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database, research_run_id, run_dir, capability, parsed = _eligible_run(
        tmp_path, monkeypatch
    )
    _prepare_continuation(
        database,
        research_run_id,
        run_dir,
        capability,
        parsed,
        monkeypatch,
    )
    _write_open_receipt(run_dir, "HOLDOUT")
    with get_connection(database) as connection:
        connection.execute(
            """
            UPDATE backtest_executions
            SET result_archive_path='/private/uncommitted.zip',
                stdout_path='/private/stdout.log',
                stderr_path='/private/stderr.log', return_code=9,
                total_trades=9, profit_pct=-9.0, max_drawdown_pct=9.0,
                win_rate=9.0, profit_factor=0.9, sharpe=-1.0,
                sortino=-1.0, calmar=-1.0, long_profit_pct=-4.0,
                short_profit_pct=-5.0,
                metrics_json='{"private":"uncommitted"}',
                scenario_passed=1
            WHERE research_run_id=? AND scenario IN ('HOLDOUT','HOLDOUT_STRESS')
            """,
            (research_run_id,),
        )
        connection.commit()

    public = holdout_run.fail_holdout_continuation(
        database,
        run_dir,
        research_run_id,
        "FAILED",
        "HOLDOUT_NONZERO_OR_INVALID",
        now="2026-01-01T00:01:00.000Z",
    )

    assert (public["status"], public["stage"], public["verdict"]) == (
        "FAILED",
        "HOLDOUT_BACKTEST",
        None,
    )
    assert public["authorization"] == {
        "status": "CONSUMED",
        "can_authorize": False,
        "reason": "one-shot Holdout authorization has been consumed",
    }
    assert (
        public["holdout"]["status"],
        public["holdout"]["scenario_opened"],
        public["holdout_stress"]["status"],
        public["holdout_stress"]["scenario_opened"],
    ) == ("FAILED", True, "SKIPPED", False)
    later = _execution_rows(database, research_run_id)[1:]
    assert [row["error_message"] for row in later] == [
        "HOLDOUT_NONZERO_OR_INVALID",
        "NOT_OPENED_AFTER_TERMINAL",
    ]
    for row in later:
        _assert_empty_result(row)

    before = later
    repeated = holdout_run.fail_holdout_continuation(
        database,
        run_dir,
        research_run_id,
        "FAILED",
        "CONTROLLER_FAILED",
        now="2026-01-01T00:02:00.000Z",
    )
    assert repeated["status"] == "FAILED"
    assert repeated["error_message"] == "HOLDOUT_NONZERO_OR_INVALID"
    assert _execution_rows(database, research_run_id)[1:] == before


def test_t0_holdout_error_codes_are_allowlisted_and_never_echo_database_text(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database, research_run_id, run_dir, capability, parsed = _eligible_run(
        tmp_path, monkeypatch
    )
    _prepare_continuation(
        database,
        research_run_id,
        run_dir,
        capability,
        parsed,
        monkeypatch,
    )
    secret_like = "SECRET_API_TOKEN_123"

    with pytest.raises(holdout_run.HoldoutRunError) as rejected:
        holdout_run.fail_holdout_continuation(
            database,
            run_dir,
            research_run_id,
            "FAILED",
            secret_like,
            now="2026-01-01T00:01:00.000Z",
        )
    assert rejected.value.code == "invalid_terminal"
    assert secret_like not in str(rejected.value)
    assert [row["status"] for row in _execution_rows(database, research_run_id)] == [
        "SUCCEEDED",
        "PENDING",
        "PENDING",
    ]

    holdout_run.fail_holdout_continuation(
        database,
        run_dir,
        research_run_id,
        "FAILED",
        "CONTROLLER_FAILED",
        now="2026-01-01T00:01:00.000Z",
    )
    with get_connection(database) as connection:
        connection.execute(
            "UPDATE research_runs SET error_message=? WHERE id=?",
            (secret_like, research_run_id),
        )
        connection.commit()
    with pytest.raises(holdout_run.HoldoutRunError) as public_rejected:
        holdout_run.load_public_research_run(database, research_run_id)
    assert public_rejected.value.code == "run_state_conflict"
    assert secret_like not in str(public_rejected.value)


def test_t1_failure_cannot_override_an_already_completed_authoritative_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database, research_run_id, run_dir, capability, parsed = _eligible_run(
        tmp_path, monkeypatch
    )
    _prepare_continuation(
        database,
        research_run_id,
        run_dir,
        capability,
        parsed,
        monkeypatch,
    )
    _write_open_receipt(run_dir, "HOLDOUT")
    _write_open_receipt(run_dir, "HOLDOUT_STRESS")
    with get_connection(database) as connection:
        connection.execute(
            """
            UPDATE backtest_executions
            SET status='SUCCEEDED', result_archive_path='/private/result.zip',
                return_code=0, total_trades=1, profit_pct=0.1,
                max_drawdown_pct=1.0, win_rate=100.0, profit_factor=1.0,
                long_profit_pct=0.1, short_profit_pct=0.0,
                metrics_json='{"test_only_synthetic":true}',
                scenario_passed=NULL, error_message=NULL, finished_at=?
            WHERE research_run_id=? AND scenario IN ('HOLDOUT','HOLDOUT_STRESS')
            """,
            ("2026-01-01T00:01:00.000Z", research_run_id),
        )
        checks = json.loads(
            connection.execute(
                "SELECT checks_json FROM research_runs WHERE id=?",
                (research_run_id,),
            ).fetchone()[0]
        )
        checks.update(
            {
                "next_phase": "HUMAN_ECONOMIC_REVIEW",
                "holdout": "SUCCEEDED",
                "holdout_stress": "SUCCEEDED",
                "judge": "NOT_RUN",
            }
        )
        connection.execute(
            """
            UPDATE research_runs
            SET status='COMPLETED', stage='COMPLETED', verdict=NULL,
                checks_json=?, finished_at=?
            WHERE id=?
            """,
            (
                json.dumps(checks, sort_keys=True, separators=(",", ":")),
                "2026-01-01T00:01:00.000Z",
                research_run_id,
            ),
        )
        connection.commit()
    before = _execution_rows(database, research_run_id)

    public = holdout_run.fail_holdout_continuation(
        database,
        run_dir,
        research_run_id,
        "FAILED",
        "CONTROLLER_FAILED",
        now="2026-01-01T00:02:00.000Z",
    )

    assert (public["status"], public["stage"], public["verdict"]) == (
        "COMPLETED",
        "COMPLETED",
        None,
    )
    assert public["authorization"]["status"] == "CONSUMED"
    assert [item["status"] for item in public["executions"]] == [
        "SUCCEEDED",
        "SUCCEEDED",
        "SUCCEEDED",
    ]
    assert _execution_rows(database, research_run_id) == before

    decided_at = "2026-01-01T00:03:00.000Z"
    human_review = {
        "action": "REJECT",
        "reason": "TEST_ONLY human economic rejection",
        "source": "RESEARCH_CONSOLE",
        "decided_at": decided_at,
    }
    checks.update(
        {
            "next_phase": "TERMINAL_REJECTED",
            "judge": "HUMAN",
            "human_review": human_review,
        }
    )
    with get_connection(database) as connection:
        connection.execute(
            """
            UPDATE research_runs
            SET verdict='REJECTED', checks_json=?, rejection_reasons_json=?
            WHERE id=?
            """,
            (
                json.dumps(checks, sort_keys=True, separators=(",", ":")),
                json.dumps(
                    [
                        {
                            "code": "HUMAN_REJECT",
                            "reason": human_review["reason"],
                            "source": human_review["source"],
                            "decided_at": human_review["decided_at"],
                        }
                    ],
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                research_run_id,
            ),
        )
        connection.commit()
    rejected = holdout_run.load_public_research_run(database, research_run_id)
    assert rejected["verdict"] == "REJECTED"
    assert rejected["economic_review"] == "REJECTED"
    assert rejected["release_count"] == 0


def test_t1_public_authorization_states_and_exact_strategy_detail_url(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database, research_run_id, run_dir, capability, parsed = _eligible_run(
        tmp_path / "available", monkeypatch
    )
    monkeypatch.setattr(
        holdout_run,
        "parse_backtest_artifact",
        lambda *_args, **_kwargs: parsed,
    )
    available = holdout_run.load_public_research_run(
        database, research_run_id, capability
    )
    expected_url = (
        "/strategy?profile_id="
        f"{available['research_profile_id']}&candidate_id={available['candidate_id']}"
        f"&research_run_id={research_run_id}"
    )
    assert available["authorization"] == {
        "status": "AVAILABLE",
        "can_authorize": True,
        "reason": "fixed one-shot Holdout continuation is available",
    }
    assert available["strategy_detail_url"] == expected_url

    _prepare_continuation(
        database,
        research_run_id,
        run_dir,
        capability,
        parsed,
        monkeypatch,
    )
    consumed = holdout_run.load_public_research_run(database, research_run_id)
    assert consumed["authorization"] == {
        "status": "CONSUMED",
        "can_authorize": False,
        "reason": "one-shot Holdout authorization has been consumed",
    }
    assert consumed["strategy_detail_url"] == expected_url

    interrupted_db, interrupted_id, interrupted_dir, interrupted_capability, interrupted_parsed = _eligible_run(
        tmp_path / "interrupted", monkeypatch
    )
    residual = interrupted_dir / "holdout-input"
    residual.mkdir()
    (residual / "authorization.json").write_text(
        '{"test_only_synthetic":true}\n', encoding="utf-8"
    )
    monkeypatch.setattr(
        holdout_run,
        "parse_backtest_artifact",
        lambda *_args, **_kwargs: interrupted_parsed,
    )
    interrupted = holdout_run.load_public_research_run(
        interrupted_db, interrupted_id, interrupted_capability
    )
    interrupted_url = (
        "/strategy?profile_id="
        f"{interrupted['research_profile_id']}&candidate_id={interrupted['candidate_id']}"
        f"&research_run_id={interrupted_id}"
    )
    assert interrupted["authorization"] == {
        "status": "CONSUMED_OR_INTERRUPTED",
        "can_authorize": False,
        "reason": (
            "Holdout authorization files already exist; "
            "manual confirmation is required"
        ),
    }
    assert interrupted["strategy_detail_url"] == interrupted_url


def _later_artifacts(
    development: backtest_artifact.ParsedBacktestArtifact,
    run_dir: Path,
) -> dict[str, backtest_artifact.ParsedBacktestArtifact]:
    holdout = replace(
        development,
        archive_path=run_dir / "holdout-evidence" / "holdout-02.zip",
        archive_sha256="2" * 64,
        metadata_sha256="4" * 64,
        provenance_sha256="6" * 64,
        report_sha256="8" * 64,
        config_sha256="a" * 64,
        backtest_start="2026-07-31T00:00:00Z",
        backtest_end="2026-08-29T23:55:00Z",
        configured_fee=0.0005,
        total_trades=31,
        wins=20,
        draws=1,
        losses=10,
    )
    stress = replace(
        holdout,
        archive_path=run_dir / "holdout-evidence" / "holdout-stress-03.zip",
        archive_sha256="3" * 64,
        metadata_sha256="5" * 64,
        provenance_sha256="7" * 64,
        report_sha256="9" * 64,
        config_sha256="b" * 64,
        configured_fee=0.001,
    )
    return {"HOLDOUT": holdout, "HOLDOUT_STRESS": stress}


def _profile_spec() -> research_bundle.ProfileSpec:
    return research_bundle.ProfileSpec(
        name="TEST_ONLY_SYNTHETIC profile",
        history_start_date="2026-01-01",
        smoke_days=7,
        holdout_days=30,
        stress_fee_multiplier=2.0,
        max_drawdown_pct=5.0,
        min_development_trades=30,
        min_holdout_trades=30,
        min_profit_factor=1.1,
    )


def test_t0_later_execution_contract_accepts_only_frozen_timerange_and_fee(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database, research_run_id, run_dir, capability, development = _eligible_run(
        tmp_path, monkeypatch
    )
    _prepare_continuation(
        database,
        research_run_id,
        run_dir,
        capability,
        development,
        monkeypatch,
    )
    rows = {row["scenario"]: row for row in _execution_rows(database, research_run_id)}
    later = _later_artifacts(development, run_dir)

    holdout_run._require_execution_contract(rows["HOLDOUT"], later["HOLDOUT"])
    holdout_run._require_execution_contract(
        rows["HOLDOUT_STRESS"], later["HOLDOUT_STRESS"]
    )


@pytest.mark.parametrize(
    ("scenario", "field", "value"),
    (
        ("HOLDOUT", "backtest_start", "2026-08-01T00:00:00Z"),
        ("HOLDOUT", "backtest_end", "2026-08-29T23:50:00Z"),
        ("HOLDOUT", "timeframe", "1h"),
        ("HOLDOUT", "detail_timeframe", "1m"),
        ("HOLDOUT_STRESS", "configured_fee", 0.0005),
    ),
)
def test_t0_later_execution_contract_rejects_timerange_or_fee_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    scenario: str,
    field: str,
    value: Any,
) -> None:
    database, research_run_id, run_dir, capability, development = _eligible_run(
        tmp_path, monkeypatch
    )
    _prepare_continuation(
        database,
        research_run_id,
        run_dir,
        capability,
        development,
        monkeypatch,
    )
    row = next(
        row
        for row in _execution_rows(database, research_run_id)
        if row["scenario"] == scenario
    )
    parsed = replace(_later_artifacts(development, run_dir)[scenario], **{field: value})

    with pytest.raises(holdout_run.HoldoutRunError) as raised:
        holdout_run._require_execution_contract(row, parsed)

    assert (raised.value.code, raised.value.status) == ("run_state_conflict", 409)


@pytest.mark.parametrize(
    ("scenario", "field", "value", "message"),
    (
        (
            "HOLDOUT",
            "configured_fee",
            0.0006,
            "DEVELOPMENT and HOLDOUT artifacts must use the same base fee",
        ),
        (
            "HOLDOUT_STRESS",
            "configured_fee",
            0.0009,
            "HOLDOUT_STRESS fee must equal base fee times stress_fee_multiplier",
        ),
        (
            "HOLDOUT_STRESS",
            "backtest_start",
            "2026-08-01T00:00:00Z",
            "HOLDOUT_STRESS must use the same timerange as HOLDOUT",
        ),
        (
            "PROFILE",
            "holdout_days",
            29,
            "profile holdout_days must equal the HOLDOUT artifact calendar span",
        ),
        (
            "HOLDOUT",
            "pairs",
            ("ETH/USDT:USDT",),
            "HOLDOUT artifact disagrees on common field pairs",
        ),
    ),
)
def test_t0_cross_scenario_timerange_fee_and_identity_truth_table(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    scenario: str,
    field: str,
    value: Any,
    message: str,
) -> None:
    _, _, run_dir, _, development = _eligible_run(tmp_path, monkeypatch)
    later = _later_artifacts(development, run_dir)
    valid = {"DEVELOPMENT": development, **later}
    research_bundle._validate_cross_scenario(_profile_spec(), valid)
    drifted = dict(valid)
    profile = _profile_spec()
    if scenario == "PROFILE":
        profile = replace(profile, **{field: value})
    else:
        drifted[scenario] = replace(drifted[scenario], **{field: value})

    with pytest.raises(research_bundle.ResearchBundleImportError, match=message):
        research_bundle._validate_cross_scenario(profile, drifted)


def _stub_finalizer_artifacts(
    database: Path,
    research_run_id: str,
    run_dir: Path,
    development: backtest_artifact.ParsedBacktestArtifact,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with get_connection(database, read_only=True) as connection:
        run = connection.execute(
            "SELECT candidate_id,input_snapshot_json FROM research_runs WHERE id=?",
            (research_run_id,),
        ).fetchone()
    snapshot = json.loads(run["input_snapshot_json"])
    authorization = snapshot["holdout_authorization"]
    result = {
        "candidate_id": run["candidate_id"],
        "input_manifest_sha256": authorization["input_manifest_sha256"],
        "data_provenance_sha256": authorization["data_provenance_sha256"],
        "source_tree_sha256": "0" * 64,
        "producer_sha256": _sha256(Path(holdout_run.__file__).read_bytes()),
        "runner_sha256": authorization["runner_sha256"],
    }
    later = _later_artifacts(development, run_dir)
    monkeypatch.setattr(
        holdout_run,
        "_load_holdout_result",
        lambda *_args, **_kwargs: (result, "c" * 64),
    )
    monkeypatch.setattr(
        holdout_run,
        "_parsed_development",
        lambda *_args, **_kwargs: development,
    )
    monkeypatch.setattr(
        holdout_run,
        "_parse_later_artifacts",
        lambda *_args, **_kwargs: later,
    )


@pytest.mark.parametrize("fault", ("second_execution", "final_run"))
def test_t1_finalizer_update_fault_rolls_back_both_later_results(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    database, research_run_id, run_dir, capability, development = _eligible_run(
        tmp_path, monkeypatch
    )
    _prepare_continuation(
        database,
        research_run_id,
        run_dir,
        capability,
        development,
        monkeypatch,
    )
    _stub_finalizer_artifacts(
        database, research_run_id, run_dir, development, monkeypatch
    )
    with get_connection(database) as connection:
        if fault == "second_execution":
            connection.execute(
                """
                CREATE TRIGGER inject_second_execution_update
                BEFORE UPDATE ON backtest_executions
                WHEN OLD.scenario='HOLDOUT_STRESS'
                BEGIN
                    SELECT RAISE(ABORT, 'TEST_ONLY second execution fault');
                END
                """
            )
        else:
            connection.execute(
                """
                CREATE TRIGGER inject_final_run_update
                BEFORE UPDATE ON research_runs
                WHEN NEW.status='COMPLETED'
                BEGIN
                    SELECT RAISE(ABORT, 'TEST_ONLY final Run fault');
                END
                """
            )
        connection.commit()

    with pytest.raises(holdout_run.HoldoutRunError) as raised:
        holdout_run.finalize_holdout_continuation(
            database,
            run_dir,
            research_run_id,
            now="2026-01-01T00:01:00.000Z",
        )

    assert raised.value.code == "attach_failed"
    rows = _execution_rows(database, research_run_id)
    assert [row["status"] for row in rows] == ["SUCCEEDED", "PENDING", "PENDING"]
    for row in rows[1:]:
        _assert_empty_result(row)
    with get_connection(database, read_only=True) as connection:
        run = connection.execute(
            "SELECT status,stage,verdict,input_snapshot_json FROM research_runs WHERE id=?",
            (research_run_id,),
        ).fetchone()
    assert (run["status"], run["stage"], run["verdict"]) == (
        "RUNNING",
        "HOLDOUT_BACKTEST",
        None,
    )
    assert "holdout_results" not in json.loads(run["input_snapshot_json"])


def test_t1_result_receipt_drift_before_write_lock_keeps_both_results_pending(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database, research_run_id, run_dir, capability, development = _eligible_run(
        tmp_path, monkeypatch
    )
    _prepare_continuation(
        database,
        research_run_id,
        run_dir,
        capability,
        development,
        monkeypatch,
    )
    _stub_finalizer_artifacts(
        database, research_run_id, run_dir, development, monkeypatch
    )
    result, result_sha = holdout_run._load_holdout_result(
        run_dir, research_run_id
    )
    calls = 0

    def drifting_result(*_args: Any, **_kwargs: Any):
        nonlocal calls
        calls += 1
        if calls == 1:
            return result, result_sha
        return {**result, "candidate_id": "TEST_ONLY_DRIFT"}, result_sha

    monkeypatch.setattr(holdout_run, "_load_holdout_result", drifting_result)

    with pytest.raises(holdout_run.HoldoutRunError) as raised:
        holdout_run.finalize_holdout_continuation(
            database,
            run_dir,
            research_run_id,
            now="2026-01-01T00:01:00.000Z",
        )

    assert raised.value.code == "artifact_invalid"
    assert calls == 2
    rows = _execution_rows(database, research_run_id)
    assert [row["status"] for row in rows] == ["SUCCEEDED", "PENDING", "PENDING"]
    for row in rows[1:]:
        _assert_empty_result(row)


def test_t1_authorization_snapshot_drift_before_write_lock_keeps_results_pending(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database, research_run_id, run_dir, capability, development = _eligible_run(
        tmp_path, monkeypatch
    )
    _prepare_continuation(
        database,
        research_run_id,
        run_dir,
        capability,
        development,
        monkeypatch,
    )
    _stub_finalizer_artifacts(
        database, research_run_id, run_dir, development, monkeypatch
    )
    real_get_connection = holdout_run.get_connection
    calls = 0

    def drifting_connection(*args: Any, **kwargs: Any):
        nonlocal calls
        calls += 1
        if calls == 2:
            with real_get_connection(database) as drift:
                snapshot = json.loads(
                    drift.execute(
                        "SELECT input_snapshot_json FROM research_runs WHERE id=?",
                        (research_run_id,),
                    ).fetchone()[0]
                )
                snapshot["holdout_authorization"]["input_manifest_sha256"] = (
                    "d" * 64
                )
                drift.execute(
                    "UPDATE research_runs SET input_snapshot_json=? WHERE id=?",
                    (
                        json.dumps(snapshot, sort_keys=True, separators=(",", ":")),
                        research_run_id,
                    ),
                )
                drift.commit()
        return real_get_connection(*args, **kwargs)

    monkeypatch.setattr(holdout_run, "get_connection", drifting_connection)

    with pytest.raises(holdout_run.HoldoutRunError) as raised:
        holdout_run.finalize_holdout_continuation(
            database,
            run_dir,
            research_run_id,
            now="2026-01-01T00:01:00.000Z",
        )

    assert raised.value.code == "run_state_conflict"
    assert calls == 2
    rows = _execution_rows(database, research_run_id)
    assert [row["status"] for row in rows] == ["SUCCEEDED", "PENDING", "PENDING"]
    for row in rows[1:]:
        _assert_empty_result(row)


def test_t1_profile_drift_before_finalize_keeps_both_results_pending(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database, research_run_id, run_dir, capability, development = _eligible_run(
        tmp_path, monkeypatch
    )
    _prepare_continuation(
        database,
        research_run_id,
        run_dir,
        capability,
        development,
        monkeypatch,
    )
    _stub_finalizer_artifacts(
        database, research_run_id, run_dir, development, monkeypatch
    )
    with get_connection(database) as connection:
        connection.execute(
            "UPDATE research_profiles SET max_open_trades=max_open_trades+1 "
            "WHERE id=(SELECT research_profile_id FROM research_runs WHERE id=?)",
            (research_run_id,),
        )
        connection.commit()

    with pytest.raises(holdout_run.HoldoutRunError) as raised:
        holdout_run.finalize_holdout_continuation(
            database,
            run_dir,
            research_run_id,
            now="2026-01-01T00:01:00.000Z",
        )

    assert raised.value.code == "run_state_conflict"
    rows = _execution_rows(database, research_run_id)
    assert [row["status"] for row in rows] == ["SUCCEEDED", "PENDING", "PENDING"]
    for row in rows[1:]:
        _assert_empty_result(row)


def test_t0_public_payload_recursively_redacts_paths_commands_and_market_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database, research_run_id, run_dir, capability, development = _eligible_run(
        tmp_path, monkeypatch
    )
    _prepare_continuation(
        database,
        research_run_id,
        run_dir,
        capability,
        development,
        monkeypatch,
    )
    secret_values = (
        "/private/holdout/secret-path",
        "SECRET_ARGV_TOKEN",
        "SECRET_STDERR_TOKEN",
        "SECRET_MARKET_VALUE_987654321",
    )
    with get_connection(database) as connection:
        snapshot = json.loads(
            connection.execute(
                "SELECT input_snapshot_json FROM research_runs WHERE id=?",
                (research_run_id,),
            ).fetchone()[0]
        )
        snapshot.update(
            {
                "run_dir": secret_values[0],
                "argv": [secret_values[1]],
                "stderr": secret_values[2],
                "raw_market_value": secret_values[3],
            }
        )
        connection.execute(
            "UPDATE research_runs SET input_snapshot_json=? WHERE id=?",
            (
                json.dumps(snapshot, sort_keys=True, separators=(",", ":")),
                research_run_id,
            ),
        )
        connection.execute(
            """
            UPDATE backtest_executions
            SET command_json=?, config_path=?, strategy_path=?
            WHERE research_run_id=? AND scenario IN ('HOLDOUT','HOLDOUT_STRESS')
            """,
            (
                json.dumps({"argv": [secret_values[1]]}),
                secret_values[0],
                secret_values[0],
                research_run_id,
            ),
        )
        connection.commit()

    public = holdout_run.load_public_research_run(database, research_run_id)
    forbidden_keys = {
        "run_dir",
        "argv",
        "command",
        "command_json",
        "config_path",
        "strategy_path",
        "stdout_path",
        "stderr",
        "stderr_path",
        "result_archive_path",
        "input_snapshot_json",
        "raw_market_value",
    }

    def assert_public(value: Any) -> None:
        if isinstance(value, dict):
            for key, nested in value.items():
                assert key not in forbidden_keys
                assert not key.endswith("_path")
                assert_public(nested)
        elif isinstance(value, list):
            for nested in value:
                assert_public(nested)
        elif isinstance(value, str):
            assert all(secret not in value for secret in secret_values)

    assert_public(public)
    serialized = json.dumps(public, sort_keys=True)
    assert "/private/" not in serialized
    assert "SECRET_" not in serialized
