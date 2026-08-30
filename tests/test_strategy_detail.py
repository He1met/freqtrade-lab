"""T0/T1/T2 tests for exact-run detail and bounded ZIP downloads."""

from __future__ import annotations

import http.client
import json
import os
import shutil
import signal
import sqlite3
import subprocess
import sys
import threading
import zipfile
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
    ResearchRunNotFoundError,
    StrategyLibraryError,
    create_strategy_library_server,
    load_research_run_detail,
    load_strategy_library,
    render_research_run_detail_page,
    render_strategy_library_page,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_ROOT = PROJECT_ROOT / "tests" / "fixtures" / "freqtrade_2026_7"
MANIFEST_NAME = "research-bundle-v1.json"
CLI = PROJECT_ROOT / "scripts" / "serve_strategy_library.py"
NOW = "2026-09-02T00:00:00.000Z"
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


def _import_bundle(database: Path):
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


def _insert_run(
    connection: sqlite3.Connection,
    candidate_id: str,
    profile_id: str,
    *,
    status: str,
    created_at: str = NOW,
) -> str:
    run_id = str(uuid4())
    stage = "COMPLETED" if status == "COMPLETED" else "LOAD"
    finished_at = created_at if status in ("COMPLETED", "FAILED", "INTERRUPTED") else None
    connection.execute(
        """
        INSERT INTO research_runs (
            id, candidate_id, research_profile_id, trigger_type, status, stage,
            pipeline_version, freqtrade_version, input_snapshot_json,
            checks_json, run_dir, rejection_reasons_json,
            created_at, started_at, finished_at
        ) VALUES (?, ?, ?, 'MANUAL', ?, ?, 'test', '2026.7', '{}', '{}', ?,
                  '[]', ?, ?, ?)
        """,
        (
            run_id,
            candidate_id,
            profile_id,
            status,
            stage,
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
) -> str:
    execution_id = str(uuid4())
    sequence = {"DEVELOPMENT": 1, "HOLDOUT": 2, "HOLDOUT_STRESS": 3}[scenario]
    connection.execute(
        """
        INSERT INTO backtest_executions (
            id, research_run_id, scenario, status, sequence, timerange_start,
            timerange_end, timeframe, fee_rate, fee_multiplier, command_json,
            config_path, strategy_path, total_trades, profit_pct,
            max_drawdown_pct, win_rate, profit_factor, metrics_json,
            scenario_passed, created_at
        ) VALUES (?, ?, ?, ?, ?, '2026-08-01T00:00:00Z',
                  '2026-08-03T23:55:00Z', '5m', 0.0005, ?, '[]',
                  'zip+file:///fixture.zip!/config.json',
                  'zip+file:///fixture.zip!/strategy.py', 0, 0.0, 0.0, 0.0,
                  0.0, '{"wins":0,"draws":0,"losses":0}', NULL, ?)
        """,
        (
            execution_id,
            run_id,
            scenario,
            status,
            sequence,
            2.0 if scenario == "HOLDOUT_STRESS" else 1.0,
            NOW,
        ),
    )
    return execution_id


def _ids(database: Path) -> tuple[str, str, str]:
    with get_connection(database) as connection:
        profile_id = str(connection.execute("SELECT id FROM research_profiles").fetchone()[0])
        candidate_id = str(connection.execute("SELECT id FROM candidates").fetchone()[0])
        run_id = str(connection.execute("SELECT id FROM research_runs").fetchone()[0])
    return profile_id, candidate_id, run_id


def _detail_url(base: str, profile_id: str, candidate_id: str, run_id: str) -> str:
    return base + "/strategy?" + urlencode(
        {
            "profile_id": profile_id,
            "candidate_id": candidate_id,
            "research_run_id": run_id,
        }
    )


def _serve(database: Path, artifact_root: Optional[Path] = None):
    server = create_strategy_library_server(database, 0, artifact_root=artifact_root)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    return server, thread, f"http://127.0.0.1:{server.server_port}"


def _stop(server, thread: threading.Thread) -> None:
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


def _prepare_download(database: Path, artifact_root: Path) -> tuple[str, Path, bytes]:
    artifact_root.mkdir()
    nested = artifact_root / "nested"
    nested.mkdir()
    with get_connection(database) as connection:
        row = connection.execute(
            """
            SELECT id, result_archive_path
            FROM backtest_executions
            WHERE scenario = 'HOLDOUT'
            """
        ).fetchone()
        destination = nested / "holdout.zip"
        shutil.copy2(Path(row["result_archive_path"]), destination)
        connection.execute(
            "UPDATE backtest_executions SET result_archive_path = ? WHERE id = ?",
            (str(destination), row["id"]),
        )
        connection.commit()
    return str(row["id"]), destination, destination.read_bytes()


def test_real_bundle_detail_has_exact_three_scenarios_and_honest_unknowns(
    database: Path,
) -> None:
    imported = _import_bundle(database)

    model = load_research_run_detail(
        database,
        imported.profile_id,
        imported.candidate_id,
        imported.research_run_id,
    )

    assert model["selected_run"]["research_run_id"] == imported.research_run_id
    assert [item["scenario"] for item in model["scenarios"]] == [
        "DEVELOPMENT",
        "HOLDOUT",
        "HOLDOUT_STRESS",
    ]
    assert [item["total_trades"] for item in model["scenarios"]] == [11, 9, 9]
    assert model["scenarios"][1]["profit_pct"] == pytest.approx(-0.082626944)
    assert all(item["scenario_passed"] is None for item in model["scenarios"])
    assert all(item["download"]["reason"] == "ROOT_NOT_CONFIGURED" for item in model["scenarios"])
    assert model["selected_run"]["succeeded_count"] == 3
    assert len(model["history"]) == 1

    page = render_research_run_detail_page(model).decode("utf-8")
    assert "UNKNOWN" in page
    assert "SUCCEEDED 只表示 Artifact 已验证落库" in page
    assert "0.1000%（倍率 2.00x）" in page
    assert "0.1000% × 2.00" not in page
    assert str(FIXTURE_ROOT) not in page
    assert "result_archive_path" not in page


def test_list_link_binds_the_summary_run_exactly(database: Path) -> None:
    imported = _import_bundle(database)
    page = render_strategy_library_page(load_strategy_library(database)).decode("utf-8")

    expected = _detail_url(
        "",
        imported.profile_id,
        imported.candidate_id,
        imported.research_run_id,
    )
    assert f'href="{expected}"' in page.replace("&amp;", "&")


def test_selected_old_run_stays_selected_and_partial_new_run_never_splices(
    database: Path,
) -> None:
    imported = _import_bundle(database)
    with get_connection(database) as connection:
        newer = _insert_run(
            connection,
            imported.candidate_id,
            imported.profile_id,
            status="RUNNING",
        )
        development = _insert_execution(connection, newer, "DEVELOPMENT")
        connection.commit()

    old = load_research_run_detail(
        database,
        imported.profile_id,
        imported.candidate_id,
        imported.research_run_id,
    )
    partial = load_research_run_detail(
        database,
        imported.profile_id,
        imported.candidate_id,
        newer,
    )

    assert old["selected_run"]["research_run_id"] == imported.research_run_id
    assert old["history"][0]["research_run_id"] == newer
    assert old["history"][0]["selected"] is False
    assert [item["execution_id"] for item in partial["scenarios"]] == [
        development,
        None,
        None,
    ]
    assert [item["status"] for item in partial["scenarios"]] == [
        "SUCCEEDED",
        "MISSING",
        "MISSING",
    ]
    assert partial["selected_run"]["succeeded_count"] == 1
    partial_page = render_research_run_detail_page(partial).decode("utf-8")
    assert partial_page.count(
        "<span>Detail timeframe</span><strong>未配置</strong>"
    ) == 1
    assert partial_page.count(
        "<span>Detail timeframe</span><strong>UNKNOWN</strong>"
    ) == 2
    library_page = render_strategy_library_page(
        load_strategy_library(database)
    ).decode("utf-8").replace("&amp;", "&")
    assert _detail_url(
        "",
        imported.profile_id,
        imported.candidate_id,
        imported.research_run_id,
    ) in library_page
    assert _detail_url(
        "",
        imported.profile_id,
        imported.candidate_id,
        newer,
    ) not in library_page


@pytest.mark.parametrize("status", ["FAILED", "INTERRUPTED"])
def test_failed_and_interrupted_runs_remain_honest_history_entries(
    database: Path, status: str
) -> None:
    imported = _import_bundle(database)
    with get_connection(database) as connection:
        run_id = _insert_run(
            connection,
            imported.candidate_id,
            imported.profile_id,
            status=status,
        )
        connection.execute(
            "UPDATE research_runs SET error_stage = 'LOAD', error_message = ? WHERE id = ?",
            (f"{status} evidence", run_id),
        )
        connection.commit()

    model = load_research_run_detail(
        database,
        imported.profile_id,
        imported.candidate_id,
        run_id,
    )

    assert model["selected_run"]["status"] == status
    assert model["selected_run"]["scenario_count"] == 0
    assert all(item["status"] == "MISSING" for item in model["scenarios"])
    assert model["history"][0]["evidence_state"] == "NO_SCENARIOS"
    page = render_research_run_detail_page(model).decode("utf-8")
    assert ("失败" if status == "FAILED" else "中断待确认") in page
    assert f"{status} evidence" in page


def test_detail_tuple_must_match_generation_profile_candidate_and_run(
    database: Path,
) -> None:
    imported = _import_bundle(database)
    with pytest.raises(ResearchRunNotFoundError):
        load_research_run_detail(
            database,
            imported.profile_id,
            str(uuid4()),
            imported.research_run_id,
        )

    second_profile = str(uuid4())
    with get_connection(database) as connection:
        connection.execute(
            """
            INSERT INTO research_profiles (
                id, name, domain, pairs_json, timeframe, history_start_date,
                smoke_days, holdout_days, starting_balance, max_open_trades,
                taker_fee_rate, stress_fee_multiplier, max_drawdown_pct,
                min_development_trades, min_holdout_trades, min_profit_factor,
                created_at, updated_at
            ) VALUES (?, 'mismatched', 'OKX_CRYPTO_PERP', '["BTC/USDT:USDT"]',
                      '5m', '2026-01-01', 1, 1, 1000, 1, 0.0005, 2, 25, 0, 0,
                      0, ?, ?)
            """,
            (second_profile, NOW, NOW),
        )
        cross_profile_run = _insert_run(
            connection,
            imported.candidate_id,
            second_profile,
            status="RUNNING",
        )
        connection.commit()
    scoped = load_research_run_detail(
        database,
        imported.profile_id,
        imported.candidate_id,
        imported.research_run_id,
    )
    assert cross_profile_run not in {
        item["research_run_id"] for item in scoped["history"]
    }
    for profile_id in (imported.profile_id, second_profile):
        with pytest.raises(ResearchRunNotFoundError):
            load_research_run_detail(
                database,
                profile_id,
                imported.candidate_id,
                cross_profile_run,
            )


def test_null_zero_and_scenario_judge_states_are_distinct(database: Path) -> None:
    imported = _import_bundle(database)
    with get_connection(database) as connection:
        connection.execute(
            """
            UPDATE backtest_executions
            SET sharpe = NULL, sortino = NULL, calmar = NULL,
                scenario_passed = 0
            WHERE scenario = 'DEVELOPMENT'
            """
        )
        connection.execute(
            """
            UPDATE backtest_executions
            SET profit_factor = 0.0,
                metrics_json = json_set(metrics_json, '$.losses', 0),
                scenario_passed = 1
            WHERE scenario = 'HOLDOUT'
            """
        )
        connection.commit()

    model = load_research_run_detail(
        database,
        imported.profile_id,
        imported.candidate_id,
        imported.research_run_id,
    )
    development, holdout, stress = model["scenarios"]

    assert development["sharpe"] is None
    assert development["scenario_passed"] == 0
    assert holdout["profit_factor"] == 0.0
    assert holdout["losses"] == 0
    assert holdout["profit_factor_interpretation"] == "NO_LOSS_SAMPLE"
    assert holdout["scenario_passed"] == 1
    assert stress["scenario_passed"] is None
    page = render_research_run_detail_page(model).decode("utf-8")
    assert "无亏损样本" in page
    assert "未通过" in page
    assert "通过" in page
    assert "UNKNOWN" in page


def test_detail_html_escapes_database_text(database: Path) -> None:
    imported = _import_bundle(database)
    hostile = '<script>alert("detail")</script>&'
    with get_connection(database) as connection:
        connection.execute(
            "UPDATE candidates SET display_name = ? WHERE id = ?",
            (hostile, imported.candidate_id),
        )
        connection.execute(
            "UPDATE research_runs SET error_message = ? WHERE id = ?",
            (hostile, imported.research_run_id),
        )
        connection.execute(
            "UPDATE backtest_executions SET error_message = ? WHERE scenario = 'HOLDOUT'",
            (hostile,),
        )
        connection.commit()

    model = load_research_run_detail(
        database,
        imported.profile_id,
        imported.candidate_id,
        imported.research_run_id,
    )
    page = render_research_run_detail_page(model).decode("utf-8")

    assert hostile not in page
    assert "&lt;script&gt;alert(&quot;detail&quot;)&lt;/script&gt;&amp;" in page


def test_detail_page_api_and_strict_query_contract_hide_host_paths(database: Path) -> None:
    imported = _import_bundle(database)
    server, thread, base = _serve(database)
    detail = _detail_url(
        base,
        imported.profile_id,
        imported.candidate_id,
        imported.research_run_id,
    )
    api = detail.replace("/strategy?", "/api/strategy?")
    try:
        with urlopen(detail, timeout=5) as response:
            page = response.read().decode("utf-8")
            assert response.status == 200
        with urlopen(api, timeout=5) as response:
            payload = json.load(response)
            assert response.status == 200
        serialized = json.dumps(payload)
        assert str(FIXTURE_ROOT) not in page
        assert str(FIXTURE_ROOT) not in serialized
        assert "command_json" not in serialized
        assert payload["selected_run"]["research_run_id"] == imported.research_run_id

        for path in (
            "/strategy",
            "/strategy?profile_id=x&candidate_id=y",
            detail + "&unknown=1",
            detail + "&research_run_id=again",
        ):
            with pytest.raises(HTTPError) as exc_info:
                urlopen(base + path if path.startswith("/") else path, timeout=5)
            assert exc_info.value.code == 400
        mismatch = _detail_url(base, imported.profile_id, imported.candidate_id, str(uuid4()))
        with pytest.raises(HTTPError) as exc_info:
            urlopen(mismatch, timeout=5)
        assert exc_info.value.code == 404
    finally:
        _stop(server, thread)


def test_download_happy_path_get_head_and_read_only_snapshot(
    database: Path, tmp_path: Path
) -> None:
    _import_bundle(database)
    artifact_root = tmp_path / "artifacts"
    execution_id, archive, expected = _prepare_download(database, artifact_root)
    before = _snapshot(database)
    server, thread, base = _serve(database, artifact_root)
    download = base + "/download?" + urlencode({"execution_id": execution_id})
    try:
        profile_id, candidate_id, run_id = _ids(database)
        api = _detail_url(base, profile_id, candidate_id, run_id).replace(
            "/strategy?", "/api/strategy?"
        )
        with urlopen(api, timeout=5) as response:
            payload = json.load(response)
        holdout = next(
            item for item in payload["scenarios"] if item["scenario"] == "HOLDOUT"
        )
        assert holdout["download"]["available"] is True
        assert str(artifact_root) not in json.dumps(payload)

        with urlopen(download, timeout=5) as response:
            body = response.read()
            assert response.status == 200
            assert response.headers["Content-Type"] == "application/zip"
            disposition = response.headers["Content-Disposition"]
            assert disposition.startswith('attachment; filename="evidence-')
            assert execution_id not in disposition
        assert body == expected == archive.read_bytes()

        with urlopen(Request(download, method="HEAD"), timeout=5) as response:
            assert response.status == 200
            assert int(response.headers["Content-Length"]) == len(expected)
            assert response.read() == b""

        connection = http.client.HTTPConnection(
            "127.0.0.1", server.server_port, timeout=5
        )
        connection.request(
            "GET",
            "/download?" + urlencode({"execution_id": execution_id}),
            headers={"Host": "attacker.example"},
        )
        response = connection.getresponse()
        assert response.status == 400
        assert str(artifact_root) not in response.read().decode("utf-8")
        connection.close()
    finally:
        _stop(server, thread)
    assert _snapshot(database) == before


@pytest.mark.parametrize(
    "case",
    [
        "traversal",
        "outside",
        "symlink",
        "leaf_symlink",
        "missing",
        "directory",
        "fifo",
        "not_zip",
        "too_large",
        "hash_missing",
        "hash",
    ],
)
def test_download_gate_fails_closed_for_unsafe_evidence(
    database: Path, tmp_path: Path, case: str
) -> None:
    _import_bundle(database)
    artifact_root = tmp_path / "artifacts"
    execution_id, valid_archive, _ = _prepare_download(database, artifact_root)
    outside = tmp_path / "outside.zip"
    shutil.copy2(valid_archive, outside)
    target: Path
    if case == "traversal":
        target = artifact_root / ".." / "outside.zip"
    elif case == "outside":
        target = outside
    elif case == "symlink":
        link = artifact_root / "outside-link"
        link.symlink_to(tmp_path, target_is_directory=True)
        target = link / "outside.zip"
    elif case == "leaf_symlink":
        target = artifact_root / "leaf.zip"
        target.symlink_to(outside)
    elif case == "missing":
        target = artifact_root / "missing.zip"
    elif case == "directory":
        target = artifact_root / "directory.zip"
        target.mkdir()
    elif case == "fifo":
        target = artifact_root / "pipe.zip"
        os.mkfifo(target)
    elif case == "not_zip":
        target = artifact_root / "bad.zip"
        target.write_bytes(b"not a zip")
    elif case == "too_large":
        target = artifact_root / "large.zip"
        target.write_bytes(b"x" * (4 * 1024 * 1024 + 1))
    elif case == "hash_missing":
        target = valid_archive
    else:
        target = artifact_root / "different.zip"
        with zipfile.ZipFile(target, "w") as archive:
            archive.writestr("different.txt", "different evidence")
    with get_connection(database) as connection:
        connection.execute(
            "UPDATE backtest_executions SET result_archive_path = ? WHERE id = ?",
            (str(target), execution_id),
        )
        if case == "hash_missing":
            row = connection.execute(
                "SELECT metrics_json FROM backtest_executions WHERE id = ?",
                (execution_id,),
            ).fetchone()
            metrics = json.loads(row["metrics_json"])
            del metrics["artifact"]["archive_sha256"]
            connection.execute(
                "UPDATE backtest_executions SET metrics_json = ? WHERE id = ?",
                (json.dumps(metrics), execution_id),
            )
        connection.commit()

    server, thread, base = _serve(database, artifact_root)
    try:
        url = base + "/download?" + urlencode({"execution_id": execution_id})
        with pytest.raises(HTTPError) as exc_info:
            urlopen(url, timeout=5)
        body = exc_info.value.read().decode("utf-8")
        assert exc_info.value.code == 404
        assert str(artifact_root) not in body
        assert str(target) not in body
        assert "Traceback" not in body
    finally:
        _stop(server, thread)


def test_download_rejects_root_symlink_and_malformed_execution_query(
    database: Path, tmp_path: Path
) -> None:
    _import_bundle(database)
    real_root = tmp_path / "real"
    real_root.mkdir()
    linked_root = tmp_path / "linked"
    linked_root.symlink_to(real_root, target_is_directory=True)
    with pytest.raises(StrategyLibraryError, match="symlink"):
        create_strategy_library_server(database, 0, artifact_root=linked_root)

    server, thread, base = _serve(database, real_root)
    try:
        for query in ("", "execution_id=", "execution_id=a&execution_id=b", "other=x"):
            with pytest.raises(HTTPError) as exc_info:
                urlopen(base + "/download" + ("?" + query if query else ""), timeout=5)
            assert exc_info.value.code == 400
    finally:
        _stop(server, thread)


def test_root_fd_never_follows_replacement_symlink(
    database: Path, tmp_path: Path
) -> None:
    _import_bundle(database)
    artifact_root = tmp_path / "artifacts"
    execution_id, _, expected = _prepare_download(database, artifact_root)
    server, thread, base = _serve(database, artifact_root)
    moved = tmp_path / "moved-artifacts"
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        artifact_root.rename(moved)
        artifact_root.symlink_to(outside, target_is_directory=True)
        with zipfile.ZipFile(outside / "nested" / "holdout.zip", "w") as archive:
            archive.writestr("attacker.txt", "outside replacement")
    except FileNotFoundError:
        (outside / "nested").mkdir()
        with zipfile.ZipFile(outside / "nested" / "holdout.zip", "w") as archive:
            archive.writestr("attacker.txt", "outside replacement")
    try:
        url = base + "/download?" + urlencode({"execution_id": execution_id})
        with urlopen(url, timeout=5) as response:
            assert response.read() == expected
    finally:
        _stop(server, thread)


def test_cli_with_artifact_root_serves_real_download(database: Path, tmp_path: Path) -> None:
    _import_bundle(database)
    artifact_root = tmp_path / "artifacts"
    execution_id, _, expected = _prepare_download(database, artifact_root)
    process = subprocess.Popen(
        [
            sys.executable,
            str(CLI),
            "--database",
            str(database),
            "--artifact-root",
            str(artifact_root),
            "--port",
            "0",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert process.stdout is not None
    try:
        line = process.stdout.readline().strip()
        assert line.startswith("Strategy library: http://127.0.0.1:")
        base = line.removeprefix("Strategy library: ").rstrip("/")
        with urlopen(
            base + "/download?" + urlencode({"execution_id": execution_id}),
            timeout=5,
        ) as response:
            assert response.read() == expected
    finally:
        if process.poll() is None:
            process.send_signal(signal.SIGINT)
        process.wait(timeout=5)
    assert process.returncode == 0
