"""T0/T1 tests and a real loopback smoke for the strategy library."""

from __future__ import annotations

import hashlib
import http.client
import json
import selectors
import signal
import sqlite3
import subprocess
import sys
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import uuid4

import pytest

from lab.database import get_connection, init_database
from lab.research_bundle import import_research_bundle
from lab.strategy_library import (
    ExecutionNotFoundError,
    ProfileNotFoundError,
    ProfileRequiredError,
    ResearchRunNotFoundError,
    StrategyLibraryError,
    create_strategy_library_server,
    load_execution_archive,
    load_research_run_detail,
    load_strategy_library,
    render_strategy_library_page,
)
from lab.strategy_library import _profile_query


PROJECT_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_ROOT = PROJECT_ROOT / "tests" / "fixtures" / "freqtrade_2026_7"
MANIFEST_NAME = "research-bundle-v1.json"
CLI = PROJECT_ROOT / "scripts" / "serve_strategy_library.py"
# Must remain later than the dynamic import timestamp used by this fixture.
NOW = "2099-01-01T00:00:00.000Z"
NEWER_THAN_NOW = (
    datetime.fromisoformat(NOW.replace("Z", "+00:00")) + timedelta(days=1)
).isoformat(timespec="milliseconds").replace("+00:00", "Z")
BUSINESS_TABLES = (
    "research_profiles",
    "generation_runs",
    "candidates",
    "research_runs",
    "backtest_executions",
    "releases",
)


@pytest.fixture
def database(tmp_path: Path) -> Path:
    path = tmp_path / "lab.sqlite"
    init_database(path)
    return path


def _import_real_bundle(database: Path):
    return import_research_bundle(database, FIXTURE_ROOT, MANIFEST_NAME)


def _snapshot(database: Path) -> Dict[str, list[tuple[Any, ...]]]:
    with get_connection(database) as connection:
        return {
            table: [
                tuple(row)
                for row in connection.execute(f"SELECT * FROM {table} ORDER BY id")
            ]
            for table in BUSINESS_TABLES
        }


def _candidate_and_profile(database: Path) -> tuple[str, str, str]:
    with get_connection(database) as connection:
        candidate = connection.execute("SELECT id FROM candidates").fetchone()[0]
        profile = connection.execute("SELECT id FROM research_profiles").fetchone()[0]
        run = connection.execute("SELECT id FROM research_runs").fetchone()[0]
    return str(candidate), str(profile), str(run)


def _insert_run(
    connection: sqlite3.Connection,
    candidate_id: str,
    profile_id: str,
    *,
    status: str,
    verdict: Optional[str] = None,
    created_at: str = NOW,
) -> str:
    run_id = str(uuid4())
    stage = "COMPLETED" if status == "COMPLETED" else "LOAD"
    finished_at = created_at if status in ("COMPLETED", "FAILED", "INTERRUPTED") else None
    connection.execute(
        """
        INSERT INTO research_runs (
            id, candidate_id, research_profile_id, trigger_type, status, stage,
            verdict, pipeline_version, freqtrade_version, input_snapshot_json,
            checks_json, run_dir, rejection_reasons_json, created_at,
            started_at, finished_at
        ) VALUES (?, ?, ?, 'MANUAL', ?, ?, ?, 'test', '2026.7', '{}', '{}',
                  ?, '[]', ?, ?, ?)
        """,
        (
            run_id,
            candidate_id,
            profile_id,
            status,
            stage,
            verdict,
            f"/tmp/{run_id}",
            created_at,
            created_at,
            finished_at,
        ),
    )
    return run_id


def _insert_execution(
    connection: sqlite3.Connection,
    run_id: str,
    scenario: str,
    *,
    status: str = "SUCCEEDED",
    profit_pct: Optional[float] = 1.0,
    max_drawdown_pct: Optional[float] = 2.0,
    profit_factor: Optional[float] = 1.5,
    total_trades: Optional[int] = 10,
    losses: int = 2,
) -> None:
    sequence = {"DEVELOPMENT": 1, "HOLDOUT": 2, "HOLDOUT_STRESS": 3}[scenario]
    metrics = json.dumps({"losses": losses}, separators=(",", ":"))
    connection.execute(
        """
        INSERT INTO backtest_executions (
            id, research_run_id, scenario, status, sequence, timerange_start,
            timerange_end, timeframe, fee_rate, fee_multiplier, command_json,
            config_path, strategy_path, total_trades, profit_pct,
            max_drawdown_pct, profit_factor, metrics_json, created_at
        ) VALUES (?, ?, ?, ?, ?, '2026-08-01T00:00:00Z',
                  '2026-08-03T23:55:00Z', '5m', 0.0005, ?, '[]',
                  'zip+file:///fixture.zip!/config.json',
                  'zip+file:///fixture.zip!/strategy.py', ?, ?, ?, ?, ?, ?)
        """,
        (
            str(uuid4()),
            run_id,
            scenario,
            status,
            sequence,
            2.0 if scenario == "HOLDOUT_STRESS" else 1.0,
            total_trades,
            profit_pct,
            max_drawdown_pct,
            profit_factor,
            metrics,
            NOW,
        ),
    )


def _insert_complete_scenarios(
    connection: sqlite3.Connection,
    run_id: str,
    *,
    failed_scenario: Optional[str] = None,
    null_holdout_profit_factor: bool = False,
    holdout_profit_factor: float = 1.5,
    holdout_losses: int = 2,
) -> None:
    for scenario in ("DEVELOPMENT", "HOLDOUT", "HOLDOUT_STRESS"):
        _insert_execution(
            connection,
            run_id,
            scenario,
            status="FAILED" if scenario == failed_scenario else "SUCCEEDED",
            profit_factor=(
                None
                if scenario == "HOLDOUT" and null_holdout_profit_factor
                else holdout_profit_factor
            ),
            losses=holdout_losses if scenario == "HOLDOUT" else 2,
        )


def _add_profile_candidate(
    connection: sqlite3.Connection,
    *,
    name: str,
    is_default: int = 0,
    display_name: str = "Second candidate",
) -> tuple[str, str]:
    profile_id = str(uuid4())
    generation_id = str(uuid4())
    candidate_id = str(uuid4())
    source = f"class Candidate{candidate_id.replace('-', '')}: pass"
    source_hash = hashlib.sha256(source.encode()).hexdigest()
    connection.execute(
        """
        INSERT INTO research_profiles (
            id, name, domain, exchange, trading_mode, margin_mode, pairs_json,
            timeframe, history_start_date, smoke_days, holdout_days,
            starting_balance, stake_amount, max_open_trades, taker_fee_rate,
            stress_fee_multiplier, max_drawdown_pct, min_development_trades,
            min_holdout_trades, min_profit_factor, is_default, created_at, updated_at
        ) VALUES (?, ?, 'OKX_CRYPTO_PERP', 'okx', 'futures', 'isolated',
                  '["BTC/USDT:USDT"]', '5m', '2026-01-01', 3, 3, 1000, 100,
                  1, 0.0005, 2, 25, 0, 0, 0, ?, ?, ?)
        """,
        (profile_id, name, is_default, NOW, NOW),
    )
    connection.execute(
        """
        INSERT INTO generation_runs (
            id, research_profile_id, source, status, request_json,
            returned_strategy_count, started_at, finished_at, created_at, updated_at
        ) VALUES (?, ?, 'MANUAL', 'COMPLETED', '{}', 1, ?, ?, ?, ?)
        """,
        (generation_id, profile_id, NOW, NOW, NOW, NOW),
    )
    connection.execute(
        """
        INSERT INTO candidates (
            id, generation_run_id, source_item_index, display_name, class_name,
            timeframe, code_text, code_sha256, created_at, updated_at
        ) VALUES (?, ?, 0, ?, 'SecondStrategy', '5m', ?, ?, ?, ?)
        """,
        (
            candidate_id,
            generation_id,
            display_name,
            source,
            source_hash,
            NOW,
            NOW,
        ),
    )
    return profile_id, candidate_id


def test_real_bundle_is_a_complete_but_not_passed_summary(database: Path) -> None:
    imported = _import_real_bundle(database)

    model = load_strategy_library(database)

    assert model["profile"]["id"] == imported.profile_id
    assert len(model["strategies"]) == 1
    card = model["strategies"][0]
    assert card["latest_status"]["status"] == "COMPLETED"
    assert card["latest_status"]["verdict"] is None
    assert card["latest_summary"]["research_run_id"] == imported.research_run_id
    assert card["latest_summary"]["holdout_total_trades"] == 9
    assert card["latest_summary"]["holdout_losses"] == 5
    assert card["completed_count"] == 1
    assert card["passed_count"] == 0
    assert card["summary_state"] == "COMPLETE"
    assert "最近完整摘要（非当前 Run）" not in render_strategy_library_page(
        model
    ).decode("utf-8")


def test_t0_library_visibility_is_legacy_or_approved_only(database: Path) -> None:
    imported = _import_real_bundle(database)
    with get_connection(database) as connection:
        original = json.loads(
            connection.execute(
                "SELECT metadata_json FROM candidates WHERE id = ?",
                (imported.candidate_id,),
            ).fetchone()[0]
        )
        execution_id = connection.execute(
            """
            SELECT id FROM backtest_executions
            WHERE research_run_id = ? ORDER BY sequence LIMIT 1
            """,
            (imported.research_run_id,),
        ).fetchone()[0]

    assert len(load_strategy_library(database)["strategies"]) == 1
    load_research_run_detail(
        database,
        imported.profile_id,
        imported.candidate_id,
        imported.research_run_id,
    )

    cases = (
        ({**original, "review": {"status": "APPROVED"}}, True),
        ({**original, "review": {"status": "PENDING"}}, False),
        ({**original, "review": {"status": "REJECTED"}}, False),
        ({**original, "review": {"status": "UNKNOWN"}}, False),
        ({**original, "review": None}, False),
        ({**original, "review": "APPROVED"}, False),
    )
    for metadata, visible in cases:
        with get_connection(database) as connection:
            connection.execute(
                "UPDATE candidates SET metadata_json = ? WHERE id = ?",
                (
                    json.dumps(metadata, separators=(",", ":"), sort_keys=True),
                    imported.candidate_id,
                ),
            )
            connection.commit()
        assert bool(load_strategy_library(database)["strategies"]) is visible
        if visible:
            load_research_run_detail(
                database,
                imported.profile_id,
                imported.candidate_id,
                imported.research_run_id,
            )
        else:
            with pytest.raises(ResearchRunNotFoundError):
                load_research_run_detail(
                    database,
                    imported.profile_id,
                    imported.candidate_id,
                    imported.research_run_id,
                )
            with pytest.raises(ExecutionNotFoundError):
                load_execution_archive(
                    database,
                    execution_id,
                    artifact_root=None,
                    artifact_root_fd=None,
                )


def test_empty_query_selects_no_explicit_profile() -> None:
    assert _profile_query("") is None


def test_new_running_run_does_not_hide_older_complete_summary(database: Path) -> None:
    imported = _import_real_bundle(database)
    candidate_id, profile_id, _ = _candidate_and_profile(database)
    with get_connection(database) as connection:
        running_id = _insert_run(
            connection, candidate_id, profile_id, status="RUNNING"
        )
        connection.commit()

    card = load_strategy_library(database)["strategies"][0]

    assert card["latest_status"]["research_run_id"] == running_id
    assert card["latest_status"]["status"] == "RUNNING"
    assert card["latest_summary"]["research_run_id"] == imported.research_run_id
    assert card["completed_count"] == 1
    page = render_strategy_library_page(load_strategy_library(database)).decode(
        "utf-8"
    )
    assert "最近完整摘要（非当前 Run）" in page
    assert card["latest_summary"]["finished_at"] in page


@pytest.mark.parametrize("defect", ["zero", "missing", "failed", "metric_null"])
def test_new_incomplete_completed_run_does_not_hide_older_summary(
    database: Path, defect: str
) -> None:
    imported = _import_real_bundle(database)
    candidate_id, profile_id, _ = _candidate_and_profile(database)
    with get_connection(database) as connection:
        newer_id = _insert_run(
            connection,
            candidate_id,
            profile_id,
            status="COMPLETED",
            verdict="REJECTED",
        )
        if defect == "missing":
            _insert_execution(connection, newer_id, "DEVELOPMENT")
            _insert_execution(connection, newer_id, "HOLDOUT")
        elif defect == "failed":
            _insert_complete_scenarios(
                connection, newer_id, failed_scenario="HOLDOUT_STRESS"
            )
        elif defect == "metric_null":
            _insert_complete_scenarios(
                connection, newer_id, null_holdout_profit_factor=True
            )
        connection.commit()

    card = load_strategy_library(database)["strategies"][0]

    assert card["latest_status"]["research_run_id"] == newer_id
    assert card["latest_summary"]["research_run_id"] == imported.research_run_id
    assert card["completed_count"] == 2
    assert card["passed_count"] == 0


def test_partial_scenarios_from_different_runs_never_splice(database: Path) -> None:
    _import_real_bundle(database)
    candidate_id, profile_id, _ = _candidate_and_profile(database)
    with get_connection(database) as connection:
        connection.execute("DELETE FROM backtest_executions")
        connection.execute("DELETE FROM research_runs")
        for scenario in ("DEVELOPMENT", "HOLDOUT", "HOLDOUT_STRESS"):
            run_id = _insert_run(
                connection,
                candidate_id,
                profile_id,
                status="COMPLETED",
            )
            _insert_execution(connection, run_id, scenario)
        connection.commit()

    card = load_strategy_library(database)["strategies"][0]

    assert card["latest_summary"] is None
    assert card["summary_state"] == "INCOMPLETE_DATA"
    assert card["completed_count"] == 3


def test_execution_joins_do_not_inflate_run_counts(database: Path) -> None:
    _import_real_bundle(database)
    candidate_id, profile_id, _ = _candidate_and_profile(database)
    with get_connection(database) as connection:
        run_id = _insert_run(
            connection,
            candidate_id,
            profile_id,
            status="COMPLETED",
            verdict="PASSED",
        )
        _insert_complete_scenarios(connection, run_id)
        connection.commit()

    card = load_strategy_library(database)["strategies"][0]

    assert card["latest_summary"]["research_run_id"] == run_id
    assert card["completed_count"] == 2
    assert card["passed_count"] == 1


def test_profile_scope_applies_to_candidates_runs_summaries_and_counts(
    database: Path,
) -> None:
    imported = _import_real_bundle(database)
    with get_connection(database) as connection:
        profile_two, candidate_two = _add_profile_candidate(
            connection, name="Second profile"
        )
        run_two = _insert_run(
            connection,
            candidate_two,
            profile_two,
            status="COMPLETED",
            verdict="PASSED",
        )
        _insert_complete_scenarios(connection, run_two)
        connection.commit()

    first = load_strategy_library(database, imported.profile_id)
    second = load_strategy_library(database, profile_two)

    assert [card["candidate"]["id"] for card in first["strategies"]] == [
        imported.candidate_id
    ]
    assert first["strategies"][0]["passed_count"] == 0
    assert [card["candidate"]["id"] for card in second["strategies"]] == [
        candidate_two
    ]
    assert second["strategies"][0]["passed_count"] == 1


def test_ambiguous_profiles_require_selection_without_mixing(database: Path) -> None:
    _import_real_bundle(database)
    with get_connection(database) as connection:
        _add_profile_candidate(connection, name="Second profile")
        connection.commit()

    page_model = load_strategy_library(database)

    assert page_model["profile"] is None
    assert page_model["strategies"] == []
    with pytest.raises(ProfileRequiredError):
        load_strategy_library(database, require_unambiguous_profile=True)
    with pytest.raises(ProfileNotFoundError):
        load_strategy_library(database, "missing-profile")


def test_no_loss_profit_factor_is_not_rendered_as_plain_zero(database: Path) -> None:
    _import_real_bundle(database)
    with get_connection(database) as connection:
        connection.execute(
            """
            UPDATE backtest_executions
            SET profit_factor = 0.0, metrics_json = '{"losses":0}'
            WHERE scenario = 'HOLDOUT'
            """
        )
        connection.commit()

    model = load_strategy_library(database)
    card = model["strategies"][0]
    page = render_strategy_library_page(model).decode("utf-8")

    assert card["latest_summary"]["profit_factor_interpretation"] == "NO_LOSS_SAMPLE"
    assert "无亏损样本" in page
    assert "不可直接解释" in page
    assert "Holdout PF</span><strong>0.00" not in page


def test_release_marker_only_follows_current_unarchived_summary(database: Path) -> None:
    imported = _import_real_bundle(database)
    candidate_id, profile_id, original_run = _candidate_and_profile(database)
    with get_connection(database) as connection:
        connection.execute(
            "UPDATE research_runs SET verdict = 'PASSED' WHERE id = ?",
            (original_run,),
        )
        connection.execute(
            """
            INSERT INTO releases (
                id, research_run_id, display_name, release_dir, strategy_sha256,
                config_sha256, manifest_json, manifest_sha256,
                freqtrade_version, created_at
            ) SELECT ?, ?, 'fixture release', ?, c.code_sha256, ?, '{}', ?,
                     '2026.7', ?
              FROM candidates AS c WHERE c.id = ?
            """,
            (
                str(uuid4()),
                original_run,
                f"/tmp/{uuid4()}",
                uuid4().hex * 2,
                uuid4().hex * 2,
                NOW,
                imported.candidate_id,
            ),
        )
        connection.commit()
    assert load_strategy_library(database)["strategies"][0]["latest_summary"][
        "has_release"
    ] is True

    with get_connection(database) as connection:
        newer = _insert_run(
            connection,
            candidate_id,
            profile_id,
            status="COMPLETED",
            verdict=None,
            created_at=NEWER_THAN_NOW,
        )
        _insert_complete_scenarios(connection, newer)
        connection.commit()

    assert load_strategy_library(database)["strategies"][0]["latest_summary"][
        "has_release"
    ] is False


def test_empty_and_unresearched_states_preserve_unknowns(database: Path) -> None:
    assert load_strategy_library(database) == {
        "profile": None,
        "profiles": [],
        "strategies": [],
    }
    _import_real_bundle(database)
    with get_connection(database) as connection:
        connection.execute("DELETE FROM backtest_executions")
        connection.execute("DELETE FROM research_runs")
        connection.commit()

    model = load_strategy_library(database)
    card = model["strategies"][0]

    assert card["latest_status"] is None
    assert card["latest_summary"] is None
    assert card["completed_count"] == 0
    assert card["passed_count"] == 0
    assert "尚未研究" in render_strategy_library_page(model).decode("utf-8")


@pytest.mark.parametrize(
    ("status", "expected"),
    [("FAILED", "失败"), ("INTERRUPTED", "中断待确认")],
)
def test_failure_and_interruption_have_honest_page_states(
    database: Path, status: str, expected: str
) -> None:
    _import_real_bundle(database)
    candidate_id, profile_id, _ = _candidate_and_profile(database)
    with get_connection(database) as connection:
        connection.execute("DELETE FROM backtest_executions")
        connection.execute("DELETE FROM research_runs")
        _insert_run(connection, candidate_id, profile_id, status=status)
        connection.commit()

    model = load_strategy_library(database)

    assert model["strategies"][0]["summary_state"] == "INCOMPLETE_DATA"
    assert expected in render_strategy_library_page(model).decode("utf-8")


def _request(url: str, *, method: str = "GET"):
    return urlopen(Request(url, method=method), timeout=5)


def test_http_page_api_escaping_and_read_only_methods(database: Path) -> None:
    _import_real_bundle(database)
    hostile = '<script>alert("x")</script>&'
    with get_connection(database) as connection:
        connection.execute("UPDATE candidates SET display_name = ?", (hostile,))
        connection.commit()
    before = _snapshot(database)
    server = create_strategy_library_server(database, 0)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        with _request(base + "/") as response:
            page = response.read().decode("utf-8")
            assert response.status == 200
            assert response.headers["Cache-Control"] == "no-store"
            assert response.headers.get("Access-Control-Allow-Origin") is None
        assert hostile not in page
        assert "&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;&amp;" in page

        with _request(base + "/api/strategies") as response:
            payload = json.load(response)
            assert response.status == 200
            assert payload["strategies"][0]["candidate"]["display_name"] == hostile

        with pytest.raises(HTTPError) as exc_info:
            _request(base + "/api/strategies", method="POST")
        assert exc_info.value.code == 405
        assert exc_info.value.headers["Allow"] == "GET, HEAD"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert _snapshot(database) == before


@pytest.mark.parametrize(
    ("path", "status"),
    [
        ("/api/strategies?profile_id=missing", 404),
        ("/api/strategies?unknown=1", 400),
        ("/missing", 404),
    ],
)
def test_http_fail_closed_statuses(database: Path, path: str, status: int) -> None:
    _import_real_bundle(database)
    server = create_strategy_library_server(database, 0)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        with pytest.raises(HTTPError) as exc_info:
            _request(f"http://127.0.0.1:{server.server_port}{path}")
        assert exc_info.value.code == status
        body = exc_info.value.read().decode("utf-8")
        assert "Traceback" not in body
        assert str(database) not in body
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_http_api_requires_profile_when_multiple_are_ambiguous(database: Path) -> None:
    _import_real_bundle(database)
    with get_connection(database) as connection:
        second_profile, _ = _add_profile_candidate(connection, name="Second profile")
        connection.commit()
    server = create_strategy_library_server(database, 0)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        with pytest.raises(HTTPError) as exc_info:
            _request(base + "/api/strategies")
        assert exc_info.value.code == 409
        with _request(
            base + "/api/strategies?" + urlencode({"profile_id": second_profile})
        ) as response:
            payload = json.load(response)
            assert payload["profile"]["id"] == second_profile
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_http_rejects_non_loopback_host_header(database: Path) -> None:
    _import_real_bundle(database)
    server = create_strategy_library_server(database, 0)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
    try:
        connection.request(
            "GET",
            "/api/strategies",
            headers={"Host": "attacker.example"},
        )
        response = connection.getresponse()
        body = response.read().decode("utf-8")
        assert response.status == 400
        assert "bad_host" in body
        assert "StrategyTestV3Futures" not in body
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_real_cli_loopback_startup_smoke_is_read_only(database: Path) -> None:
    _import_real_bundle(database)
    before = _snapshot(database)
    process = subprocess.Popen(
        [
            sys.executable,
            str(CLI),
            "--database",
            str(database),
            "--port",
            "0",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert process.stdout is not None
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    try:
        assert selector.select(timeout=5), "server did not print its loopback URL"
        line = process.stdout.readline().strip()
        assert line.startswith("Strategy library: http://127.0.0.1:")
        page_url = line.removeprefix("Strategy library: ")
        with _request(page_url) as response:
            page = response.read().decode("utf-8")
        with _request(page_url + "api/strategies") as response:
            payload = json.load(response)
        assert "StrategyTestV3Futures" in page
        assert "未评审" in page
        assert payload["strategies"][0]["summary_state"] == "COMPLETE"
    finally:
        selector.close()
        if process.poll() is None:
            process.send_signal(signal.SIGINT)
        process.wait(timeout=5)

    assert process.returncode == 0
    assert _snapshot(database) == before


def test_cli_missing_database_fails_without_creating_it(tmp_path: Path) -> None:
    missing = tmp_path / "missing.sqlite"

    completed = subprocess.run(
        [sys.executable, str(CLI), "--database", str(missing), "--port", "0"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert completed.stdout == ""
    assert completed.stderr.count("\n") == 1
    assert "Traceback" not in completed.stderr
    assert not missing.exists()


def test_wrong_schema_version_fails_before_listening(tmp_path: Path) -> None:
    database = tmp_path / "wrong.sqlite"
    connection = sqlite3.connect(database)
    connection.execute("PRAGMA user_version = 2")
    connection.close()

    with pytest.raises(StrategyLibraryError, match="schema version"):
        create_strategy_library_server(database, 0)
