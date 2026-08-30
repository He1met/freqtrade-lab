"""Database initialization, constraint, and relationship tests."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from typing import Iterator, Optional
from uuid import uuid4

import pytest

from lab import database as database_module
from lab.database import get_connection, get_schema_version, init_database


NOW = "2026-08-29T10:00:00.000Z"
BUSINESS_TABLES = {
    "research_profiles",
    "generation_runs",
    "candidates",
    "research_runs",
    "backtest_executions",
    "releases",
}


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "database" / "lab.sqlite"
    init_database(path)
    return path


@pytest.fixture
def connection(db_path: Path) -> Iterator[sqlite3.Connection]:
    conn = get_connection(db_path)
    try:
        yield conn
    finally:
        conn.close()


def insert_profile(
    connection: sqlite3.Connection,
    *,
    profile_id: Optional[str] = None,
    name: Optional[str] = None,
    is_default: int = 0,
) -> str:
    profile_id = profile_id or str(uuid4())
    connection.execute(
        """
        INSERT INTO research_profiles (
            id, name, domain, pairs_json, timeframe, history_start_date,
            smoke_days, holdout_days, starting_balance, stake_amount,
            max_open_trades, taker_fee_rate, stress_fee_multiplier,
            max_drawdown_pct, min_development_trades, min_holdout_trades,
            min_profit_factor, is_default, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            profile_id,
            name or f"profile-{profile_id}",
            "OKX_CRYPTO_PERP",
            '["BTC/USDT:USDT"]',
            "5m",
            "2025-01-01",
            7,
            30,
            1000.0,
            None,
            3,
            0.0005,
            2.0,
            25.0,
            100,
            30,
            1.2,
            is_default,
            NOW,
            NOW,
        ),
    )
    return profile_id


def insert_generation_run(
    connection: sqlite3.Connection,
    profile_id: str,
    *,
    generation_run_id: Optional[str] = None,
    returned_strategy_count: int = 0,
) -> str:
    generation_run_id = generation_run_id or str(uuid4())
    connection.execute(
        """
        INSERT INTO generation_runs (
            id, research_profile_id, source, status, request_json,
            returned_strategy_count, started_at, created_at, updated_at
        ) VALUES (?, ?, 'MANUAL', 'COMPLETED', '{}', ?, ?, ?, ?)
        """,
        (generation_run_id, profile_id, returned_strategy_count, NOW, NOW, NOW),
    )
    return generation_run_id


def insert_candidate(
    connection: sqlite3.Connection,
    generation_run_id: str,
    *,
    candidate_id: Optional[str] = None,
    source_item_index: int = 0,
    parent_candidate_id: Optional[str] = None,
    code_sha256: Optional[str] = None,
) -> str:
    candidate_id = candidate_id or str(uuid4())
    code_sha256 = code_sha256 or uuid4().hex * 2
    connection.execute(
        """
        INSERT INTO candidates (
            id, generation_run_id, source_item_index, parent_candidate_id,
            display_name, class_name, timeframe, code_text, code_sha256,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, 'ExampleStrategy', '5m', ?, ?, ?, ?)
        """,
        (
            candidate_id,
            generation_run_id,
            source_item_index,
            parent_candidate_id,
            f"candidate-{candidate_id}",
            "class ExampleStrategy: pass",
            code_sha256,
            NOW,
            NOW,
        ),
    )
    return candidate_id


def insert_research_run(
    connection: sqlite3.Connection,
    candidate_id: str,
    profile_id: str,
    *,
    research_run_id: Optional[str] = None,
    status: str = "COMPLETED",
    verdict: Optional[str] = "PASSED",
) -> str:
    research_run_id = research_run_id or str(uuid4())
    stage = "COMPLETED" if status == "COMPLETED" else "PENDING"
    connection.execute(
        """
        INSERT INTO research_runs (
            id, candidate_id, research_profile_id, trigger_type, status,
            stage, verdict, pipeline_version, input_snapshot_json,
            run_dir, created_at
        ) VALUES (?, ?, ?, 'MANUAL', ?, ?, ?, '1', '{}', ?, ?)
        """,
        (
            research_run_id,
            candidate_id,
            profile_id,
            status,
            stage,
            verdict,
            f"/tmp/run-{research_run_id}",
            NOW,
        ),
    )
    return research_run_id


def insert_backtest_execution(
    connection: sqlite3.Connection,
    research_run_id: str,
    *,
    scenario: str = "SMOKE",
    sequence: int = 1,
) -> str:
    execution_id = str(uuid4())
    connection.execute(
        """
        INSERT INTO backtest_executions (
            id, research_run_id, scenario, status, sequence,
            timerange_start, timerange_end, timeframe, fee_rate,
            fee_multiplier, command_json, config_path, strategy_path,
            created_at
        ) VALUES (?, ?, ?, 'SUCCEEDED', ?, '2026-01-01', '2026-01-07',
                  '5m', 0.0005, 1.0, '[]', '/tmp/config.json',
                  '/tmp/strategy.py', ?)
        """,
        (execution_id, research_run_id, scenario, sequence, NOW),
    )
    return execution_id


def insert_release(
    connection: sqlite3.Connection,
    research_run_id: str,
    strategy_sha256: str,
) -> str:
    release_id = str(uuid4())
    connection.execute(
        """
        INSERT INTO releases (
            id, research_run_id, display_name, release_dir,
            strategy_sha256, config_sha256, manifest_json,
            manifest_sha256, freqtrade_version, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, '{}', ?, '2026.8', ?)
        """,
        (
            release_id,
            research_run_id,
            f"release-{release_id}",
            f"/tmp/release-{release_id}",
            strategy_sha256,
            uuid4().hex * 2,
            uuid4().hex * 2,
            NOW,
        ),
    )
    return release_id


def insert_candidate_chain(
    connection: sqlite3.Connection,
) -> tuple[str, str, str]:
    profile_id = insert_profile(connection)
    generation_run_id = insert_generation_run(connection, profile_id)
    candidate_id = insert_candidate(connection, generation_run_id)
    return profile_id, generation_run_id, candidate_id


def candidate_sha(connection: sqlite3.Connection, candidate_id: str) -> str:
    row = connection.execute(
        "SELECT code_sha256 FROM candidates WHERE id = ?", (candidate_id,)
    ).fetchone()
    assert row is not None
    return str(row[0])


def test_initialization_creates_exactly_six_business_tables(
    connection: sqlite3.Connection,
) -> None:
    rows = connection.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    assert {row[0] for row in rows} == BUSINESS_TABLES
    assert connection.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE name = 'sqlite_sequence'"
    ).fetchone()[0] == 0


def test_all_business_primary_keys_reject_null(
    connection: sqlite3.Connection,
) -> None:
    for table in BUSINESS_TABLES:
        id_column = next(
            row for row in connection.execute(f"PRAGMA table_info({table})")
            if row[1] == "id"
        )
        assert id_column[3] == 1
        assert id_column[5] == 1


def test_initialization_is_idempotent_and_preserves_data(db_path: Path) -> None:
    connection = get_connection(db_path)
    try:
        profile_id = insert_profile(connection)
        connection.commit()
    finally:
        connection.close()

    init_database(db_path)
    init_database(db_path)

    connection = get_connection(db_path)
    try:
        assert connection.execute(
            "SELECT COUNT(*) FROM research_profiles WHERE id = ?", (profile_id,)
        ).fetchone()[0] == 1
    finally:
        connection.close()


def test_user_version_is_one(db_path: Path) -> None:
    assert get_schema_version(db_path) == 1


def test_connection_pragmas(connection: sqlite3.Connection) -> None:
    assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert connection.execute("PRAGMA busy_timeout").fetchone()[0] == 5000


def test_complete_relationship_chain(connection: sqlite3.Connection) -> None:
    profile_id, _, candidate_id = insert_candidate_chain(connection)
    research_run_id = insert_research_run(connection, candidate_id, profile_id)
    execution_id = insert_backtest_execution(connection, research_run_id)
    release_id = insert_release(
        connection, research_run_id, candidate_sha(connection, candidate_id)
    )
    connection.commit()

    assert connection.execute(
        "SELECT COUNT(*) FROM backtest_executions WHERE id = ?", (execution_id,)
    ).fetchone()[0] == 1
    assert connection.execute(
        "SELECT COUNT(*) FROM releases WHERE id = ?", (release_id,)
    ).fetchone()[0] == 1


def test_generation_runs_has_no_requested_count(connection: sqlite3.Connection) -> None:
    columns = {
        row[1] for row in connection.execute("PRAGMA table_info(generation_runs)")
    }
    assert "requested_count" not in columns


def test_returned_strategy_count_can_be_zero(
    connection: sqlite3.Connection,
) -> None:
    profile_id = insert_profile(connection)
    generation_run_id = insert_generation_run(
        connection, profile_id, returned_strategy_count=0
    )
    assert connection.execute(
        "SELECT returned_strategy_count FROM generation_runs WHERE id = ?",
        (generation_run_id,),
    ).fetchone()[0] == 0


def test_candidate_count_is_derived_by_generation_run(
    connection: sqlite3.Connection,
) -> None:
    profile_id = insert_profile(connection)
    generation_run_id = insert_generation_run(
        connection, profile_id, returned_strategy_count=2
    )
    insert_candidate(connection, generation_run_id, source_item_index=0)
    insert_candidate(connection, generation_run_id, source_item_index=1)
    assert connection.execute(
        "SELECT COUNT(*) FROM candidates WHERE generation_run_id = ?",
        (generation_run_id,),
    ).fetchone()[0] == 2


def test_duplicate_code_sha256_is_rejected(connection: sqlite3.Connection) -> None:
    profile_id = insert_profile(connection)
    generation_run_id = insert_generation_run(connection, profile_id)
    code_sha256 = uuid4().hex * 2
    insert_candidate(connection, generation_run_id, code_sha256=code_sha256)
    with pytest.raises(sqlite3.IntegrityError):
        insert_candidate(
            connection,
            generation_run_id,
            source_item_index=1,
            code_sha256=code_sha256,
        )


def test_duplicate_source_item_index_in_same_generation_is_rejected(
    connection: sqlite3.Connection,
) -> None:
    profile_id = insert_profile(connection)
    generation_run_id = insert_generation_run(connection, profile_id)
    insert_candidate(connection, generation_run_id, source_item_index=0)
    with pytest.raises(sqlite3.IntegrityError):
        insert_candidate(connection, generation_run_id, source_item_index=0)


def test_same_source_item_index_in_different_generations_is_allowed(
    connection: sqlite3.Connection,
) -> None:
    profile_id = insert_profile(connection)
    first_generation = insert_generation_run(connection, profile_id)
    second_generation = insert_generation_run(connection, profile_id)
    insert_candidate(connection, first_generation, source_item_index=0)
    insert_candidate(connection, second_generation, source_item_index=0)
    assert connection.execute("SELECT COUNT(*) FROM candidates").fetchone()[0] == 2


def test_candidate_display_name_can_be_updated(connection: sqlite3.Connection) -> None:
    _, _, candidate_id = insert_candidate_chain(connection)
    connection.execute(
        "UPDATE candidates SET display_name = ?, updated_at = ? WHERE id = ?",
        ("Renamed", NOW, candidate_id),
    )
    assert connection.execute(
        "SELECT display_name FROM candidates WHERE id = ?", (candidate_id,)
    ).fetchone()[0] == "Renamed"


def test_deleting_parent_candidate_sets_parent_to_null(
    connection: sqlite3.Connection,
) -> None:
    profile_id = insert_profile(connection)
    generation_run_id = insert_generation_run(connection, profile_id)
    parent_id = insert_candidate(connection, generation_run_id, source_item_index=0)
    child_id = insert_candidate(
        connection,
        generation_run_id,
        source_item_index=1,
        parent_candidate_id=parent_id,
    )
    connection.execute("DELETE FROM candidates WHERE id = ?", (parent_id,))
    assert connection.execute(
        "SELECT parent_candidate_id FROM candidates WHERE id = ?", (child_id,)
    ).fetchone()[0] is None


def test_candidate_can_have_multiple_research_runs(
    connection: sqlite3.Connection,
) -> None:
    profile_id, _, candidate_id = insert_candidate_chain(connection)
    insert_research_run(connection, candidate_id, profile_id)
    insert_research_run(connection, candidate_id, profile_id)
    assert connection.execute(
        "SELECT COUNT(*) FROM research_runs WHERE candidate_id = ?", (candidate_id,)
    ).fetchone()[0] == 2


def test_research_run_can_have_all_four_scenarios(
    connection: sqlite3.Connection,
) -> None:
    profile_id, _, candidate_id = insert_candidate_chain(connection)
    research_run_id = insert_research_run(connection, candidate_id, profile_id)
    scenarios = ("SMOKE", "DEVELOPMENT", "HOLDOUT", "HOLDOUT_STRESS")
    for sequence, scenario in enumerate(scenarios, start=1):
        insert_backtest_execution(
            connection, research_run_id, scenario=scenario, sequence=sequence
        )
    assert connection.execute(
        "SELECT COUNT(*) FROM backtest_executions WHERE research_run_id = ?",
        (research_run_id,),
    ).fetchone()[0] == 4


def test_duplicate_scenario_in_same_research_run_is_rejected(
    connection: sqlite3.Connection,
) -> None:
    profile_id, _, candidate_id = insert_candidate_chain(connection)
    research_run_id = insert_research_run(connection, candidate_id, profile_id)
    insert_backtest_execution(connection, research_run_id, scenario="SMOKE", sequence=1)
    with pytest.raises(sqlite3.IntegrityError):
        insert_backtest_execution(
            connection, research_run_id, scenario="SMOKE", sequence=2
        )


def test_release_rejects_rejected_research_run(
    connection: sqlite3.Connection,
) -> None:
    profile_id, _, candidate_id = insert_candidate_chain(connection)
    research_run_id = insert_research_run(
        connection, candidate_id, profile_id, verdict="REJECTED"
    )
    with pytest.raises(sqlite3.IntegrityError, match="PASSED"):
        insert_release(
            connection, research_run_id, candidate_sha(connection, candidate_id)
        )


def test_release_rejects_non_completed_research_run(
    connection: sqlite3.Connection,
) -> None:
    profile_id, _, candidate_id = insert_candidate_chain(connection)
    research_run_id = insert_research_run(
        connection, candidate_id, profile_id, status="RUNNING", verdict=None
    )
    with pytest.raises(sqlite3.IntegrityError, match="COMPLETED"):
        insert_release(
            connection, research_run_id, candidate_sha(connection, candidate_id)
        )


def test_release_rejects_mismatched_strategy_sha(
    connection: sqlite3.Connection,
) -> None:
    profile_id, _, candidate_id = insert_candidate_chain(connection)
    research_run_id = insert_research_run(connection, candidate_id, profile_id)
    with pytest.raises(sqlite3.IntegrityError, match="does not match"):
        insert_release(connection, research_run_id, "0" * 64)


def test_release_accepts_passed_research_run(connection: sqlite3.Connection) -> None:
    profile_id, _, candidate_id = insert_candidate_chain(connection)
    research_run_id = insert_research_run(connection, candidate_id, profile_id)
    release_id = insert_release(
        connection, research_run_id, candidate_sha(connection, candidate_id)
    )
    assert connection.execute(
        "SELECT research_run_id FROM releases WHERE id = ?", (release_id,)
    ).fetchone()[0] == research_run_id


def test_research_run_can_have_only_one_release(
    connection: sqlite3.Connection,
) -> None:
    profile_id, _, candidate_id = insert_candidate_chain(connection)
    research_run_id = insert_research_run(connection, candidate_id, profile_id)
    sha = candidate_sha(connection, candidate_id)
    insert_release(connection, research_run_id, sha)
    with pytest.raises(sqlite3.IntegrityError):
        insert_release(connection, research_run_id, sha)


def test_invalid_json_is_rejected(connection: sqlite3.Connection) -> None:
    profile_id = str(uuid4())
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """
            INSERT INTO research_profiles (
                id, name, domain, pairs_json, timeframe, history_start_date,
                smoke_days, holdout_days, starting_balance, max_open_trades,
                taker_fee_rate, stress_fee_multiplier, max_drawdown_pct,
                min_development_trades, min_holdout_trades, min_profit_factor,
                created_at, updated_at
            ) VALUES (?, ?, 'OKX_CRYPTO_PERP', 'not-json', '5m', '2025-01-01',
                      7, 30, 1000, 3, 0.0005, 2, 25, 100, 30, 1.2, ?, ?)
            """,
            (profile_id, f"profile-{profile_id}", NOW, NOW),
        )


def test_pairs_json_requires_an_array(connection: sqlite3.Connection) -> None:
    profile_id = str(uuid4())
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """
            INSERT INTO research_profiles (
                id, name, domain, pairs_json, timeframe, history_start_date,
                smoke_days, holdout_days, starting_balance, max_open_trades,
                taker_fee_rate, stress_fee_multiplier, max_drawdown_pct,
                min_development_trades, min_holdout_trades, min_profit_factor,
                created_at, updated_at
            ) VALUES (?, ?, 'OKX_CRYPTO_PERP', '{}', '5m', '2025-01-01',
                      7, 30, 1000, 3, 0.0005, 2, 25, 100, 30, 1.2, ?, ?)
            """,
            (profile_id, f"profile-{profile_id}", NOW, NOW),
        )


def test_only_one_default_profile_is_allowed(
    connection: sqlite3.Connection,
) -> None:
    insert_profile(connection, is_default=1)
    with pytest.raises(sqlite3.IntegrityError):
        insert_profile(connection, is_default=1)


def test_independent_connections_can_submit_concurrently(db_path: Path) -> None:
    setup_connection = get_connection(db_path)
    try:
        profile_id = insert_profile(setup_connection)
        setup_connection.commit()
    finally:
        setup_connection.close()

    barrier = Barrier(2)

    def submit(generation_run_id: str) -> str:
        worker_connection = get_connection(db_path)
        try:
            barrier.wait()
            insert_generation_run(
                worker_connection,
                profile_id,
                generation_run_id=generation_run_id,
            )
            worker_connection.commit()
            return generation_run_id
        finally:
            worker_connection.close()

    generation_ids = (str(uuid4()), str(uuid4()))
    with ThreadPoolExecutor(max_workers=2) as executor:
        inserted_ids = tuple(executor.map(submit, generation_ids))

    assert inserted_ids == generation_ids
    verification_connection = get_connection(db_path)
    try:
        assert verification_connection.execute(
            "SELECT COUNT(*) FROM generation_runs WHERE id IN (?, ?)", generation_ids
        ).fetchone()[0] == 2
    finally:
        verification_connection.close()


def test_deleting_research_run_cascades_to_backtests(
    connection: sqlite3.Connection,
) -> None:
    profile_id, _, candidate_id = insert_candidate_chain(connection)
    research_run_id = insert_research_run(connection, candidate_id, profile_id)
    execution_id = insert_backtest_execution(connection, research_run_id)
    connection.execute("DELETE FROM research_runs WHERE id = ?", (research_run_id,))
    assert connection.execute(
        "SELECT COUNT(*) FROM backtest_executions WHERE id = ?", (execution_id,)
    ).fetchone()[0] == 0


def test_generation_run_referenced_by_candidate_cannot_be_deleted(
    connection: sqlite3.Connection,
) -> None:
    _, generation_run_id, _ = insert_candidate_chain(connection)
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "DELETE FROM generation_runs WHERE id = ?", (generation_run_id,)
        )


def test_research_run_with_release_cannot_be_deleted(
    connection: sqlite3.Connection,
) -> None:
    profile_id, _, candidate_id = insert_candidate_chain(connection)
    research_run_id = insert_research_run(connection, candidate_id, profile_id)
    insert_release(
        connection, research_run_id, candidate_sha(connection, candidate_id)
    )
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "DELETE FROM research_runs WHERE id = ?", (research_run_id,)
        )


def test_expected_indexes_and_only_release_trigger_exist(
    connection: sqlite3.Connection,
) -> None:
    expected_indexes = {
        "ux_research_profiles_single_default",
        "ix_generation_runs_profile_created",
        "ix_generation_runs_source_created",
        "ix_generation_runs_status_created",
        "ix_candidates_generation_run",
        "ix_candidates_parent",
        "ix_candidates_created",
        "ix_research_runs_candidate_created",
        "ix_research_runs_profile_created",
        "ix_research_runs_status_created",
        "ix_research_runs_verdict_created",
        "ix_backtest_executions_status_created",
        "ix_releases_created",
        "ix_releases_archived",
    }
    index_rows = connection.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type = 'index' AND name NOT LIKE 'sqlite_autoindex_%'"
    ).fetchall()
    assert {row[0] for row in index_rows} == expected_indexes

    trigger_rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'trigger'"
    ).fetchall()
    assert [row[0] for row in trigger_rows] == ["validate_release_before_insert"]


def test_failed_initialization_rolls_back_all_schema_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    broken_schema = tmp_path / "broken.sql"
    broken_schema.write_text(
        "CREATE TABLE should_be_rolled_back (id TEXT PRIMARY KEY);\n"
        "THIS IS INVALID SQL;\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(database_module, "SCHEMA_PATH", broken_schema)
    path = tmp_path / "rollback.sqlite"

    with pytest.raises(sqlite3.Error):
        database_module.init_database(path)

    verification_connection = get_connection(path)
    try:
        assert verification_connection.execute(
            "SELECT COUNT(*) FROM sqlite_master "
            "WHERE type = 'table' AND name = 'should_be_rolled_back'"
        ).fetchone()[0] == 0
        assert verification_connection.execute(
            "PRAGMA user_version"
        ).fetchone()[0] == 0
    finally:
        verification_connection.close()
