"""T0/T1 tests for explicit human Judge and immutable Release publication."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any, Iterator

import pytest

from lab import manual_release
from lab.database import get_connection, init_database


NOW = "2026-09-02T00:00:00Z"
RUN_ID = "run-manual-review"
CANDIDATE_ID = "candidate-manual-review"
PROFILE_ID = "profile-manual-review"
SOURCE = "class ManualCandidate:\n    pass\n"
SOURCE_SHA = hashlib.sha256(SOURCE.encode()).hexdigest()


def _seed_database(tmp_path: Path) -> Path:
    database = tmp_path / "lab.sqlite"
    init_database(database)
    with get_connection(database) as connection:
        connection.execute(
            """
            INSERT INTO research_profiles (
                id,name,domain,exchange,trading_mode,margin_mode,pairs_json,
                timeframe,history_start_date,smoke_days,holdout_days,
                starting_balance,stake_amount,max_open_trades,taker_fee_rate,
                stress_fee_multiplier,max_drawdown_pct,min_development_trades,
                min_holdout_trades,min_profit_factor,is_default,created_at,updated_at
            ) VALUES (?,?, 'OKX_CRYPTO_PERP','okx','futures','isolated',
                      '["XRP/USDT:USDT"]','5m','2026-01-01',3,30,1000,100,1,
                      0.0005,2,25,1,1,1,1,?,?)
            """,
            (PROFILE_ID, "Manual Profile", NOW, NOW),
        )
        connection.execute(
            """
            INSERT INTO generation_runs (
                id,research_profile_id,source,status,request_json,
                returned_strategy_count,started_at,finished_at,created_at,updated_at
            ) VALUES ('generation-manual-review',?,'MANUAL','COMPLETED','{}',1,?,?,?,?)
            """,
            (PROFILE_ID, NOW, NOW, NOW, NOW),
        )
        connection.execute(
            """
            INSERT INTO candidates (
                id,generation_run_id,source_item_index,display_name,class_name,
                timeframe,code_text,code_sha256,created_at,updated_at
            ) VALUES (?,'generation-manual-review',0,'Manual Candidate',
                      'ManualCandidate','5m',?,?,?,?)
            """,
            (CANDIDATE_ID, SOURCE, SOURCE_SHA, NOW, NOW),
        )
        connection.execute(
            """
            INSERT INTO research_runs (
                id,candidate_id,research_profile_id,trigger_type,status,stage,
                verdict,pipeline_version,freqtrade_version,input_snapshot_json,
                checks_json,run_dir,rejection_reasons_json,created_at,started_at,finished_at
            ) VALUES (?,?,?,'MANUAL','COMPLETED','COMPLETED',NULL,
                      'development-one-shot-v1','2026.7','{}','{}','/test/run','[]',?,?,?)
            """,
            (RUN_ID, CANDIDATE_ID, PROFILE_ID, NOW, NOW, NOW),
        )
        connection.commit()
    return database


def _evidence() -> manual_release.EligibleManualReview:
    artifacts = tuple(
        {
            "execution_id": f"execution-{index}",
            "scenario": scenario,
            "archive_sha256": str(index) * 64,
            "metadata_sha256": str(index + 3) * 64,
            "provenance_sha256": str(index + 6) * 64,
            "report_sha256": "a" * 64,
            "config_sha256": "b" * 64,
            "strategy_sha256": SOURCE_SHA,
        }
        for index, scenario in enumerate(
            ("DEVELOPMENT", "HOLDOUT", "HOLDOUT_STRESS"), start=1
        )
    )
    return manual_release.EligibleManualReview(
        research_run_id=RUN_ID,
        candidate_id=CANDIDATE_ID,
        profile_id=PROFILE_ID,
        display_name="Manual Candidate",
        class_name="ManualCandidate",
        strategy_source=SOURCE,
        strategy_sha256=SOURCE_SHA,
        profile={
            "id": PROFILE_ID,
            "name": "Manual Profile",
            "exchange": "okx",
            "trading_mode": "futures",
            "margin_mode": "isolated",
            "pairs": ["XRP/USDT:USDT"],
            "timeframe": "5m",
            "starting_balance": 1000.0,
            "stake_amount": 100.0,
            "max_open_trades": 1,
            "taker_fee_rate": 0.0005,
        },
        profile_sha256="c" * 64,
        freqtrade_version="2026.7",
        source_bindings={"source_provenance_sha256": "d" * 64},
        artifacts=artifacts,
        binding_sha256="e" * 64,
    )


@pytest.fixture
def frozen_root(tmp_path: Path) -> Iterator[manual_release.FrozenReleaseRoot]:
    root = tmp_path / "releases"
    root.mkdir(mode=0o700)
    frozen = manual_release.freeze_release_root(
        root, Path(__file__).resolve().parents[1]
    )
    try:
        yield frozen
    finally:
        frozen.close()


def _fake_eligibility(connection: sqlite3.Connection, run_id: str):
    row = connection.execute(
        "SELECT verdict,checks_json FROM research_runs WHERE id=?", (run_id,)
    ).fetchone()
    if row is None or row["verdict"] is not None or row["checks_json"] != "{}":
        raise manual_release.ManualReleaseError(
            "review_not_eligible", "TEST_ONLY database state drifted"
        )
    return _evidence()


def test_t0_reason_boundary_and_shell_safe_command(
    frozen_root: manual_release.FrozenReleaseRoot,
) -> None:
    assert manual_release.normalize_reason("  人工复核通过  ") == "人工复核通过"
    with pytest.raises(manual_release.ManualReleaseError, match="1–1000"):
        manual_release.normalize_reason(" ")
    with pytest.raises(manual_release.ManualReleaseError, match="1–1000"):
        manual_release.normalize_reason("x" * 1001)
    with pytest.raises(manual_release.ManualReleaseError, match="普通文本"):
        manual_release.normalize_reason({"command": "freqtrade"})

    package = manual_release._build_release(  # noqa: SLF001 - T0 pure contract
        _evidence(),
        frozen_root,
        "11111111-1111-4111-8111-111111111111",
        "人工复核通过",
        NOW,
    )
    manifest = package["manifest"]
    command = manifest["dry_run_handoff"]["command"]
    assert manifest["dry_run_handoff"]["status"] == "NOT_EXECUTED"
    assert command.startswith("freqtrade trade --dry-run")
    assert "api_key" not in json.dumps(manifest).lower()
    assert manifest["files"]["strategies/ManualCandidate.py"] == SOURCE_SHA


def test_t1_reject_is_one_transaction_and_creates_no_release(
    tmp_path: Path,
    frozen_root: manual_release.FrozenReleaseRoot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = _seed_database(tmp_path)
    monkeypatch.setattr(manual_release, "_eligible_manual_review", _fake_eligibility)

    manual_release.reject_research_run(
        database, frozen_root, RUN_ID, "人工决定终止该假设", now=NOW
    )

    with get_connection(database, read_only=True) as connection:
        run = connection.execute(
            "SELECT verdict,checks_json,rejection_reasons_json FROM research_runs WHERE id=?",
            (RUN_ID,),
        ).fetchone()
        count = connection.execute("SELECT COUNT(*) FROM releases").fetchone()[0]
    assert run["verdict"] == "REJECTED"
    assert json.loads(run["checks_json"])["next_phase"] == "TERMINAL_REJECTED"
    assert json.loads(run["rejection_reasons_json"])[0]["reason"] == "人工决定终止该假设"
    assert count == 0
    assert list(frozen_root.path.iterdir()) == []
    (frozen_root.path / "unknown-orphan").mkdir(mode=0o700)
    unknown = manual_release.inspect_manual_review(database, frozen_root, RUN_ID)
    assert unknown["status"] == "UNKNOWN"
    assert unknown["release"] is None
    assert "command" not in json.dumps(unknown)
    with pytest.raises(manual_release.ManualReleaseError):
        manual_release.reject_research_run(
            database, frozen_root, RUN_ID, "重复请求", now=NOW
        )


def test_t1_pass_publishes_hash_bound_package_then_commits_sqlite(
    tmp_path: Path,
    frozen_root: manual_release.FrozenReleaseRoot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = _seed_database(tmp_path)
    monkeypatch.setattr(manual_release, "_eligible_manual_review", _fake_eligibility)

    package = manual_release.pass_and_create_release(
        database, frozen_root, RUN_ID, "人工经济复核通过", now=NOW
    )

    release_dir = Path(package["release_dir"])
    assert sorted(path.relative_to(release_dir).as_posix() for path in release_dir.rglob("*") if path.is_file()) == [
        "README.md",
        "config-dry-run.json",
        "manifest.json",
        "strategies/ManualCandidate.py",
    ]
    manifest_bytes = (release_dir / "manifest.json").read_bytes()
    assert hashlib.sha256(manifest_bytes).hexdigest() == package["manifest_sha256"]
    assert (release_dir / "strategies" / "ManualCandidate.py").read_text() == SOURCE
    with get_connection(database, read_only=True) as connection:
        run = connection.execute(
            "SELECT verdict,checks_json FROM research_runs WHERE id=?", (RUN_ID,)
        ).fetchone()
        release = connection.execute("SELECT * FROM releases").fetchone()
        unverified = manual_release.stored_manual_review(connection, RUN_ID)
        stored = manual_release.stored_manual_review(
            connection,
            RUN_ID,
            release_root=frozen_root,
        )
    assert run["verdict"] == "PASSED"
    assert json.loads(run["checks_json"])["judge"] == "HUMAN"
    assert release["manifest_sha256"] == package["manifest_sha256"]
    assert unverified["status"] == "UNAVAILABLE"
    assert "dry_run_handoff" not in unverified["release"]
    assert stored["release"]["dry_run_handoff"]["status"] == "NOT_EXECUTED"
    with pytest.raises(manual_release.ManualReleaseError):
        manual_release.pass_and_create_release(
            database, frozen_root, RUN_ID, "重复请求", now=NOW
        )
    assert [path.name for path in frozen_root.path.iterdir()] == [release_dir.name]
    (frozen_root.path / "unknown-orphan").mkdir(mode=0o700)
    unknown = manual_release.inspect_manual_review(database, frozen_root, RUN_ID)
    assert unknown["status"] == "UNKNOWN"
    assert "command" not in json.dumps(unknown)


@pytest.mark.parametrize("drift", ["delete_manifest", "tamper_strategy"])
def test_t1_stored_pass_file_drift_is_unknown_and_hides_handoff(
    tmp_path: Path,
    frozen_root: manual_release.FrozenReleaseRoot,
    monkeypatch: pytest.MonkeyPatch,
    drift: str,
) -> None:
    database = _seed_database(tmp_path)
    monkeypatch.setattr(manual_release, "_eligible_manual_review", _fake_eligibility)
    package = manual_release.pass_and_create_release(
        database, frozen_root, RUN_ID, "人工经济复核通过", now=NOW
    )
    release_dir = Path(package["release_dir"])
    if drift == "delete_manifest":
        release_dir.chmod(0o700)
        (release_dir / "manifest.json").unlink()
        release_dir.chmod(0o500)
    else:
        strategies = release_dir / "strategies"
        strategy = strategies / "ManualCandidate.py"
        strategy.chmod(0o600)
        strategy.write_text(SOURCE + "# drift\n")
        strategy.chmod(0o400)

    public = manual_release.inspect_manual_review(database, frozen_root, RUN_ID)
    assert public["status"] == "UNKNOWN"
    assert public["release"] is None
    assert "command" not in json.dumps(public)


def test_t1_database_drift_after_publish_is_unknown_and_not_retried(
    tmp_path: Path,
    frozen_root: manual_release.FrozenReleaseRoot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = _seed_database(tmp_path)
    monkeypatch.setattr(manual_release, "_eligible_manual_review", _fake_eligibility)
    original_publish = manual_release._publish_release  # noqa: SLF001

    def publish_then_drift(root: Any, package: Any) -> None:
        original_publish(root, package)
        with get_connection(database) as connection:
            connection.execute(
                "UPDATE research_runs SET checks_json=? WHERE id=?",
                ('{"drift":true}', RUN_ID),
            )
            connection.commit()

    monkeypatch.setattr(manual_release, "_publish_release", publish_then_drift)
    with pytest.raises(
        manual_release.ManualReleaseError, match="automatic retry is disabled"
    ) as failure:
        manual_release.pass_and_create_release(
            database, frozen_root, RUN_ID, "人工经济复核通过", now=NOW
        )
    assert failure.value.code == "release_state_unknown"
    with get_connection(database, read_only=True) as connection:
        state = connection.execute(
            "SELECT verdict FROM research_runs WHERE id=?", (RUN_ID,)
        ).fetchone()[0]
        releases = connection.execute("SELECT COUNT(*) FROM releases").fetchone()[0]
    assert state is None
    assert releases == 0
    assert len(list(frozen_root.path.iterdir())) == 1
    public = manual_release.inspect_manual_review(database, frozen_root, RUN_ID)
    assert public["status"] == "UNKNOWN"
    assert public["can_pass_and_create_release"] is False
    with pytest.raises(
        manual_release.ManualReleaseError, match="automatic retry is disabled"
    ) as reject_failure:
        manual_release.reject_research_run(
            database, frozen_root, RUN_ID, "不得覆盖 UNKNOWN", now=NOW
        )
    assert reject_failure.value.code == "release_state_unknown"
