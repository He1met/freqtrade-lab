"""T1/T2 HTTP contracts for the bounded DEVELOPMENT Research Console slice."""

from __future__ import annotations

import http.client
import hashlib
import json
import threading
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any, Iterator, Mapping, Optional
from uuid import uuid4

import pytest

from lab import backtest_artifact, development_run, research_console
from lab.database import get_connection, init_database


NOW = "2026-01-01T00:00:00.000Z"


@pytest.fixture
def database(tmp_path: Path) -> Path:
    path = tmp_path / "lab.sqlite"
    init_database(path)
    return path


@contextmanager
def _serve_console(
    database: Path,
    tmp_path: Path,
    *,
    pilot_root: Optional[Path] = None,
    freqtrade_python: Optional[Path] = None,
    freqtrade_source: Optional[Path] = None,
) -> Iterator[Any]:
    runtime_root = tmp_path / f"runtime-{uuid4()}"
    runtime_root.mkdir()
    selected_pilot_root = pilot_root or tmp_path / f"pilot-{uuid4()}"
    if pilot_root is None:
        selected_pilot_root.mkdir()
    server = research_console.create_research_console_server(
        database,
        runtime_root,
        selected_pilot_root,
        0,
        codex_binary=tmp_path / "missing-codex",
        freqtrade_python=freqtrade_python,
        freqtrade_source=freqtrade_source,
        task_timeout_seconds=2,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.research_console_controller.shutdown()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _request(
    server: Any,
    path: str,
    *,
    method: str = "GET",
    body: Optional[bytes] = None,
    headers: Optional[Mapping[str, str]] = None,
) -> tuple[int, Mapping[str, str], bytes, Any]:
    connection = http.client.HTTPConnection(
        "127.0.0.1", server.server_port, timeout=5
    )
    try:
        connection.request(method, path, body=body, headers=dict(headers or {}))
        response = connection.getresponse()
        raw = response.read()
        content_type = response.getheader("Content-Type", "")
        payload = (
            json.loads(raw.decode("utf-8"))
            if raw and content_type.startswith("application/json")
            else None
        )
        return response.status, dict(response.getheaders()), raw, payload
    finally:
        connection.close()


def _post_headers(server: Any) -> dict[str, str]:
    return {
        "Origin": f"http://127.0.0.1:{server.server_port}",
        "X-CSRF-Token": server.research_console_csrf_token,
        "Content-Type": "application/json",
    }


def _post(
    server: Any,
    path: str,
    payload: Mapping[str, Any],
    *,
    headers: Optional[Mapping[str, str]] = None,
) -> tuple[int, Mapping[str, str], bytes, Any]:
    return _request(
        server,
        path,
        method="POST",
        body=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        headers=_post_headers(server) if headers is None else headers,
    )


def _seed_public_research_run(database: Path) -> tuple[str, str]:
    profile_id = str(uuid4())
    generation_id = str(uuid4())
    candidate_id = str(uuid4())
    research_run_id = str(uuid4())
    execution_id = str(uuid4())
    checks = {
        "candidate_binding": "PASSED",
        "security_gate": "PASSED",
        "development_data": "PHYSICALLY_ISOLATED",
        "development_gate": "REJECTED",
        "next_phase": "NONE_REJECTED",
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
            (candidate_id, generation_id, "a" * 64, NOW, NOW),
        )
        connection.execute(
            """
            INSERT INTO research_runs (
                id, candidate_id, research_profile_id, trigger_type, status,
                stage, verdict, pipeline_version, freqtrade_version,
                input_snapshot_json, checks_json, run_dir,
                rejection_reasons_json, created_at, started_at, finished_at
            ) VALUES (?, ?, ?, 'MANUAL', 'COMPLETED', 'COMPLETED',
                      'REJECTED', 'BOUNDED_DEVELOPMENT_V1', '2026.7', '{}', ?,
                      '/private/local/run-dir',
                      '["MINIMUM_TRADES_NOT_MET","MINIMUM_PROFIT_PCT_NOT_MET","MINIMUM_PROFIT_FACTOR_NOT_MET"]',
                      ?, ?, ?)
            """,
            (
                research_run_id,
                candidate_id,
                profile_id,
                json.dumps(checks, separators=(",", ":")),
                NOW,
                NOW,
                NOW,
            ),
        )
        connection.execute(
            """
            INSERT INTO backtest_executions (
                id, research_run_id, scenario, status, sequence,
                timerange_start, timerange_end, timeframe, fee_rate,
                fee_multiplier, command_json, config_path, strategy_path,
                result_archive_path, stdout_path, stderr_path, return_code,
                total_trades, profit_pct, max_drawdown_pct, win_rate,
                profit_factor, metrics_json, scenario_passed,
                created_at, started_at, finished_at
            ) VALUES (?, ?, 'DEVELOPMENT', 'SUCCEEDED', 1,
                      '2026-06-01T00:00:00Z', '2026-07-30T23:55:00Z',
                      '5m', 0.0005, 1.0, '{"private":"raw-command"}',
                      '/private/local/config.json',
                      '/private/local/strategy.py',
                      '/private/local/result.zip',
                      '/private/local/stdout.log',
                      '/private/local/stderr.log', 0, 12, -1.5, 2.0, 0.4,
                      0.8, '{"raw_private_log":"must-not-leak"}', 0,
                      ?, ?, ?)
            """,
            (execution_id, research_run_id, NOW, NOW, NOW),
        )
        connection.commit()
    return candidate_id, research_run_id


def test_t1_fake_post_create_reaches_single_slot_monitor_terminal(
    monkeypatch: pytest.MonkeyPatch,
    database: Path,
    tmp_path: Path,
) -> None:
    finalized: set[str] = set()

    class DoneProcess:
        pid = 987654
        returncode = 0

        @staticmethod
        def poll() -> int:
            return 0

        @staticmethod
        def wait(timeout: Optional[float] = None) -> int:
            return 0

    monkeypatch.setattr(
        research_console.subprocess,
        "Popen",
        lambda _argv, **_kwargs: DoneProcess(),
    )
    with _serve_console(database, tmp_path) as server:
        controller = server.research_console_controller
        controller._development_capability = development_run.FrozenDevelopmentCapability(
            status="READY",
            reason="fake T2 capability",
            freqtrade_python=Path("/fake/freqtrade-python"),
            freqtrade_source=Path("/fake/freqtrade-source"),
        )

        def fake_prepare(
            _database: Path,
            run_dir: Path,
            candidate_id: str,
            _capability: Any,
            *,
            research_run_id: str,
            now: str,
        ) -> development_run.PreparedDevelopmentRun:
            return development_run.PreparedDevelopmentRun(
                research_run_id, candidate_id, "MANUAL", run_dir
            )

        def fake_public(_database: Path, run_id: str) -> dict[str, Any]:
            return {
                "research_run_id": run_id,
                "candidate_id": "candidate-t2",
                "status": "PENDING" if run_id in finalized else "RUNNING",
                "stage": "PENDING" if run_id in finalized else "DEVELOPMENT_BACKTEST",
                "verdict": None,
                "development": {"status": "SUCCEEDED" if run_id in finalized else "PENDING"},
                "holdout": {"status": "SEALED_UNREAD", "execution_rows": 0},
                "holdout_stress": {"status": "SEALED_UNREAD", "execution_rows": 0},
            }

        def fake_finalize(_database: Path, run_id: str) -> dict[str, Any]:
            finalized.add(run_id)
            return fake_public(_database, run_id)

        monkeypatch.setattr(research_console, "prepare_development_run", fake_prepare)
        monkeypatch.setattr(
            research_console,
            "development_worker_argv",
            lambda *_args: ("/fake/worker",),
        )
        monkeypatch.setattr(
            research_console, "load_public_research_run", fake_public
        )
        monkeypatch.setattr(
            research_console, "finalize_development_gate", fake_finalize
        )

        status, _, _, payload = _post(
            server, "/api/research-runs", {"candidate_id": "candidate-t2"}
        )
        assert status == 202
        run_id = payload["research_run_id"]
        for _ in range(100):
            if controller._active is None:
                break
            threading.Event().wait(0.01)
        assert controller._active is None
        assert run_id in finalized
        runtime = controller.get_status(run_id)
        assert runtime["action"] == "DEVELOPMENT"
        assert runtime["status"] == "SUCCEEDED"


def test_t2_http_real_prepare_import_and_gate_on_tracked_fixture(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Fake only the Freqtrade artifact boundary; keep the slice core real."""

    from tests.test_development_run import (
        BOUNDED_SOURCE,
        _approved_candidate_database,
        _frozen_capability_fixture,
    )

    fixture_root = Path(__file__).parent / "fixtures" / "freqtrade_2026_7"
    archive_name = "backtest-result-2026-08-30_12-55-02.zip"
    provenance_name = "backtest-result-2026-08-30_12-55-02.provenance.json"
    provenance_sha256 = hashlib.sha256(
        (fixture_root / provenance_name).read_bytes()
    ).hexdigest()
    tracked = backtest_artifact.parse_backtest_artifact(
        fixture_root,
        archive_name,
        "StrategyTestV3Futures",
        "2026.7",
        provenance_sha256,
    )

    database, candidate_id = _approved_candidate_database(tmp_path)
    pilot, freqtrade_python, freqtrade_source = _frozen_capability_fixture(
        tmp_path, monkeypatch
    )
    source_sha256 = hashlib.sha256(BOUNDED_SOURCE.encode("utf-8")).hexdigest()
    adapted = replace(
        tracked,
        strategy="BoundedCandidate",
        strategy_source=BOUNDED_SOURCE,
        strategy_member=(
            "backtest-result-2026-08-30_12-55-02_BoundedCandidate.py"
        ),
        strategy_sha256=source_sha256,
        pairs=("ADA/USDT:USDT",),
        backtest_start="2026-06-01T00:00:00Z",
        backtest_end="2026-07-30T23:55:00Z",
    )

    parse_calls: list[tuple[str, str, str]] = []

    def fake_produced_artifact(
        _root: Path,
        archive: Path,
        strategy: str,
        version: str,
        expected_receipt: str,
        *,
        allow_zero_trades: bool = False,
    ) -> backtest_artifact.ParsedBacktestArtifact:
        parse_calls.append((str(archive), strategy, expected_receipt))
        assert version == "2026.7"
        assert allow_zero_trades is True
        return adapted

    monkeypatch.setattr(
        backtest_artifact, "parse_backtest_artifact", fake_produced_artifact
    )
    launched_argv: list[tuple[str, ...]] = []

    class ImportingProcess:
        pid = 2_000_000_000

        def __init__(self, argv: tuple[str, ...]) -> None:
            self.argv = argv
            self.returncode: Optional[int] = None
            self._finished = False

        def poll(self) -> Optional[int]:
            if not self._finished:
                run_id = self.argv[self.argv.index("--research-run-id") + 1]
                database_arg = self.argv[self.argv.index("--database") + 1]
                backtest_artifact.import_backtest_execution(
                    database_arg,
                    fixture_root,
                    archive_name,
                    run_id,
                    "DEVELOPMENT",
                    "BoundedCandidate",
                    "2026.7",
                    provenance_sha256,
                    allow_zero_trades=True,
                    mark_execution_finished=True,
                )
                development_run.finalize_development_gate(database_arg, run_id)
                self._finished = True
                self.returncode = 0
            return self.returncode

        def wait(self, timeout: Optional[float] = None) -> int:
            del timeout
            result = self.poll()
            assert result is not None
            return result

    def fake_freqtrade_process(argv: Any, **_kwargs: Any) -> ImportingProcess:
        normalized = tuple(str(value) for value in argv)
        launched_argv.append(normalized)
        return ImportingProcess(normalized)

    monkeypatch.setattr(research_console.subprocess, "Popen", fake_freqtrade_process)

    with _serve_console(
        database,
        tmp_path,
        pilot_root=pilot,
        freqtrade_python=freqtrade_python,
        freqtrade_source=freqtrade_source,
    ) as server:
        status, _, _, created = _post(
            server, "/api/research-runs", {"candidate_id": candidate_id}
        )
        assert status == 202
        run_id = created["research_run_id"]

        public: Mapping[str, Any] = created
        for _ in range(200):
            status, _, raw, public = _request(
                server, f"/api/research-runs/{run_id}"
            )
            assert status == 200, public
            if public["status"] in {"PENDING", "COMPLETED"}:
                break
            threading.Event().wait(0.01)
        assert public["research_run_id"] == run_id
        assert public["candidate_id"] == candidate_id
        assert (public["status"], public["stage"], public["verdict"]) == (
            "COMPLETED",
            "COMPLETED",
            "REJECTED",
        )
        assert public["development"]["total_trades"] == tracked.total_trades
        assert public["development"]["scenario_passed"] is False
        assert [item["criterion"] for item in public["gate_results"]] == [
            "minimum_trades",
            "minimum_profit_pct",
            "minimum_profit_factor",
            "maximum_drawdown_pct",
        ]
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
        public_text = raw.decode("utf-8")
        assert str(tmp_path) not in public_text
        for private_field in (
            "config_path",
            "strategy_path",
            "result_archive_path",
            "stdout_path",
            "stderr_path",
            "run_dir",
        ):
            assert private_field not in public_text

    assert len(launched_argv) == 1
    assert Path(launched_argv[0][1]).name == "run_development_candidate.py"
    assert "HOLDOUT" not in " ".join(launched_argv[0]).upper()
    assert parse_calls == [(archive_name, "BoundedCandidate", provenance_sha256)]
    with get_connection(database, read_only=True) as connection:
        run_rows = connection.execute(
            "SELECT id FROM research_runs WHERE id=?", (run_id,)
        ).fetchall()
        executions = connection.execute(
            "SELECT research_run_id, scenario, status FROM backtest_executions WHERE research_run_id=?",
            (run_id,),
        ).fetchall()
        later_rows = connection.execute(
            "SELECT COUNT(*) FROM backtest_executions WHERE research_run_id=? AND scenario IN ('HOLDOUT','HOLDOUT_STRESS')",
            (run_id,),
        ).fetchone()[0]
        releases = connection.execute(
            "SELECT COUNT(*) FROM releases WHERE research_run_id=?", (run_id,)
        ).fetchone()[0]
    assert [row["id"] for row in run_rows] == [run_id]
    assert [tuple(row) for row in executions] == [
        (run_id, "DEVELOPMENT", "SUCCEEDED")
    ]
    assert later_rows == 0
    assert releases == 0


def test_t1_get_context_and_public_run_routes_do_not_expose_private_paths(
    monkeypatch: pytest.MonkeyPatch,
    database: Path,
    tmp_path: Path,
) -> None:
    candidate_id, research_run_id = _seed_public_research_run(database)
    context = {
        "capability": {
            "status": "READY",
            "holdout": "SEALED_UNREAD",
            "holdout_stress": "SEALED_UNREAD",
        },
        "candidates": [
            {
                "candidate_id": candidate_id,
                "display_name": "Bounded Candidate",
                "status": "READY",
                "reason": "approved and bounded",
            }
        ],
    }
    with _serve_console(database, tmp_path) as server:
        monkeypatch.setattr(
            server.research_console_controller,
            "research_context",
            lambda: context,
        )

        status, headers, _, payload = _request(server, "/api/research/context")
        assert status == 200
        assert payload == context
        assert headers["Cache-Control"] == "no-store"

        status, _, raw, payload = _request(
            server, f"/api/research-runs/{research_run_id}"
        )
        assert status == 200
        assert payload["research_run_id"] == research_run_id
        assert payload["development"] == {
            "status": "SUCCEEDED",
            "total_trades": 12,
            "profit_pct": -1.5,
            "max_drawdown_pct": 2.0,
            "win_rate": 0.4,
            "profit_factor": 0.8,
            "scenario_passed": False,
            "started_at": NOW,
            "finished_at": NOW,
        }
        assert payload["holdout"] == {
            "status": "SEALED_UNREAD",
            "execution_rows": 0,
        }
        assert payload["holdout_stress"] == {
            "status": "SEALED_UNREAD",
            "execution_rows": 0,
        }
        public_text = raw.decode("utf-8")
        for private_value in (
            "/private/",
            "raw-command",
            "stdout.log",
            "stderr.log",
            "raw_private_log",
            "must-not-leak",
        ):
            assert private_value not in public_text


@pytest.mark.parametrize(
    ("mutation", "expected_status", "expected_error"),
    [
        ("other_pipeline", 404, "run_not_found"),
        ("later_scenario", 409, "run_state_conflict"),
    ],
)
def test_t1_get_run_rejects_other_pipelines_and_non_development_evidence(
    database: Path,
    tmp_path: Path,
    mutation: str,
    expected_status: int,
    expected_error: str,
) -> None:
    _, research_run_id = _seed_public_research_run(database)
    with get_connection(database) as connection:
        if mutation == "other_pipeline":
            connection.execute(
                """
                UPDATE research_runs
                SET pipeline_version='OTHER_PIPELINE',
                    checks_json='{"private":"/private/check-secret"}',
                    error_stage='/private/stage',
                    error_message='/private/error.log'
                WHERE id=?
                """,
                (research_run_id,),
            )
        else:
            connection.execute(
                """
                UPDATE backtest_executions
                SET scenario='HOLDOUT', config_path='/private/holdout-config',
                    strategy_path='/private/holdout-strategy',
                    metrics_json='{"later_value":"private-market-value"}'
                WHERE research_run_id=?
                """,
                (research_run_id,),
            )
        connection.commit()

    with _serve_console(database, tmp_path) as server:
        status, _, raw, payload = _request(
            server, f"/api/research-runs/{research_run_id}"
        )

    assert status == expected_status
    assert payload["error"] == expected_error
    public_text = raw.decode("utf-8")
    for private_value in (
        "/private/",
        "check-secret",
        "error.log",
        "HOLDOUT",
        "private-market-value",
    ):
        assert private_value not in public_text


def test_t1_get_run_normalizes_database_error_text(
    database: Path,
    tmp_path: Path,
) -> None:
    _, research_run_id = _seed_public_research_run(database)
    with get_connection(database) as connection:
        failed_checks = json.dumps(
            {
                "candidate_binding": "PASSED",
                "security_gate": "PASSED",
                "development_data": "PHYSICALLY_ISOLATED",
                "development_gate": "PENDING",
                "next_phase": "DEVELOPMENT_GATE",
                "holdout": "SEALED_UNREAD",
                "holdout_stress": "SEALED_UNREAD",
            },
            separators=(",", ":"),
        )
        connection.execute(
            """
            UPDATE research_runs
            SET status='FAILED', stage='DEVELOPMENT_BACKTEST', verdict=NULL,
                checks_json=?, rejection_reasons_json='[]',
                error_stage='/private/raw-stage',
                error_message='/private/raw-worker-error.log'
            WHERE id=?
            """,
            (failed_checks, research_run_id),
        )
        connection.execute(
            """
            UPDATE backtest_executions
            SET status='FAILED', total_trades=NULL, profit_pct=NULL,
                max_drawdown_pct=NULL, win_rate=NULL, profit_factor=NULL,
                scenario_passed=NULL
            WHERE research_run_id=?
            """,
            (research_run_id,),
        )
        connection.commit()

    with _serve_console(database, tmp_path) as server:
        status, _, raw, payload = _request(
            server, f"/api/research-runs/{research_run_id}"
        )

    assert status == 200
    assert payload["error_stage"] == "DEVELOPMENT_BACKTEST"
    assert payload["error_message"] == "DEVELOPMENT_FAILED"
    assert "/private/" not in raw.decode("utf-8")


def test_t1_get_run_rejects_tampered_passed_gate_metrics(
    database: Path,
    tmp_path: Path,
) -> None:
    _, research_run_id = _seed_public_research_run(database)
    passed_checks = {
        "candidate_binding": "PASSED",
        "security_gate": "PASSED",
        "development_data": "PHYSICALLY_ISOLATED",
        "development_gate": "PASSED",
        "next_phase": "HOLDOUT_AUTHORIZATION_REQUIRED",
        "holdout": "SEALED_UNREAD",
        "holdout_stress": "SEALED_UNREAD",
    }
    with get_connection(database) as connection:
        connection.execute(
            """
            UPDATE research_runs
            SET status='PENDING', stage='PENDING', verdict=NULL,
                checks_json=?, rejection_reasons_json='[]', finished_at=NULL
            WHERE id=?
            """,
            (json.dumps(passed_checks), research_run_id),
        )
        connection.execute(
            """
            UPDATE backtest_executions
            SET scenario_passed=1, total_trades=0, profit_pct=-99.0,
                profit_factor=1.1, max_drawdown_pct=5.0
            WHERE research_run_id=?
            """,
            (research_run_id,),
        )
        connection.commit()

    with _serve_console(database, tmp_path) as server:
        status, _, raw, payload = _request(
            server, f"/api/research-runs/{research_run_id}"
        )

    assert status == 409
    assert payload["error"] == "run_state_conflict"
    assert "-99" not in raw.decode("utf-8")


@pytest.mark.parametrize(
    ("table", "column", "secret"),
    [
        ("research_runs", "created_at", "/private/run-created.secret"),
        (
            "backtest_executions",
            "started_at",
            "/private/execution-started.secret",
        ),
    ],
)
def test_t1_get_run_rejects_private_timestamp_text_without_echo(
    database: Path,
    tmp_path: Path,
    table: str,
    column: str,
    secret: str,
) -> None:
    _, research_run_id = _seed_public_research_run(database)
    with get_connection(database) as connection:
        connection.execute(
            f"UPDATE {table} SET {column}=? WHERE "
            + ("id=?" if table == "research_runs" else "research_run_id=?"),
            (secret, research_run_id),
        )
        connection.commit()

    with _serve_console(database, tmp_path) as server:
        status, _, raw, payload = _request(
            server, f"/api/research-runs/{research_run_id}"
        )

    assert status == 409
    assert payload["error"] == "run_state_conflict"
    assert secret not in raw.decode("utf-8")


@pytest.mark.parametrize(
    "body",
    [
        {"candidate_id": "candidate-1", "path": "/tmp/strategy.py"},
        {"candidate_id": "candidate-1", "threshold": 0.1},
        {"candidate_id": "candidate-1", "scenario": "HOLDOUT"},
    ],
)
def test_t1_create_research_run_accepts_only_exact_candidate_id(
    monkeypatch: pytest.MonkeyPatch,
    database: Path,
    tmp_path: Path,
    body: Mapping[str, Any],
) -> None:
    calls: list[str] = []
    with _serve_console(database, tmp_path) as server:
        monkeypatch.setattr(
            server.research_console_controller,
            "create_research_run",
            lambda candidate_id: calls.append(candidate_id) or {
                "research_run_id": "run-1",
                "candidate_id": candidate_id,
                "status": "RUNNING",
            },
        )

        status, _, _, payload = _post(server, "/api/research-runs", body)

    assert status == 400
    assert payload["error"] == "invalid_research_request"
    assert calls == []


def test_t1_create_and_cancel_routes_enforce_origin_csrf_and_exact_actions(
    monkeypatch: pytest.MonkeyPatch,
    database: Path,
    tmp_path: Path,
) -> None:
    calls: list[tuple[str, str]] = []
    with _serve_console(database, tmp_path) as server:
        monkeypatch.setattr(
            server.research_console_controller,
            "create_research_run",
            lambda candidate_id: calls.append(("create", candidate_id)) or {
                "research_run_id": "run-1",
                "candidate_id": candidate_id,
                "status": "RUNNING",
            },
        )
        monkeypatch.setattr(
            server.research_console_controller,
            "cancel_research_run",
            lambda run_id: calls.append(("cancel", run_id)) or {
                "research_run_id": run_id,
                "status": "CANCELLED",
            },
        )

        status, _, _, payload = _post(
            server,
            "/api/research-runs",
            {"candidate_id": "candidate-1"},
            headers={"Content-Type": "application/json"},
        )
        assert status == 403
        assert payload["error"] == "bad_origin"

        headers = _post_headers(server)
        headers.pop("X-CSRF-Token")
        status, _, _, payload = _post(
            server,
            "/api/research-runs",
            {"candidate_id": "candidate-1"},
            headers=headers,
        )
        assert status == 403
        assert payload["error"] == "bad_csrf"

        status, _, _, payload = _post(
            server, "/api/research-runs", {"candidate_id": "candidate-1"}
        )
        assert status == 202
        assert payload["research_run_id"] == "run-1"

        status, _, _, payload = _post(
            server,
            "/api/research-runs/run-1/actions",
            {"action": "CANCEL", "scenario": "DEVELOPMENT"},
        )
        assert status == 400
        assert payload["error"] == "invalid_action"

        status, _, _, payload = _post(
            server,
            "/api/research-runs/run-1/actions",
            {"action": "HOLDOUT"},
        )
        assert status == 400
        assert payload["error"] == "invalid_action"

        status, _, _, payload = _post(
            server,
            "/api/research-runs/run-1/actions",
            {"action": "CANCEL"},
        )
        assert status == 202
        assert payload == {"research_run_id": "run-1", "status": "CANCELLED"}

    assert calls == [("create", "candidate-1"), ("cancel", "run-1")]


def test_t1_single_slot_conflict_is_preserved_by_http_route(
    monkeypatch: pytest.MonkeyPatch,
    database: Path,
    tmp_path: Path,
) -> None:
    def conflict(_candidate_id: str) -> dict[str, Any]:
        raise research_console.ControlRequestError(
            409, "active_campaign", "已有一个受控任务正在运行"
        )

    with _serve_console(database, tmp_path) as server:
        monkeypatch.setattr(
            server.research_console_controller, "create_research_run", conflict
        )
        status, _, _, payload = _post(
            server, "/api/research-runs", {"candidate_id": "candidate-1"}
        )

    assert status == 409
    assert payload["error"] == "active_campaign"


def test_t1_missing_pilot_keeps_console_up_and_blocks_only_research_data(
    database: Path,
    tmp_path: Path,
) -> None:
    missing_pilot = tmp_path / "missing-external-pilot"
    assert not missing_pilot.exists()

    with _serve_console(database, tmp_path, pilot_root=missing_pilot) as server:
        status, _, _, research = _request(server, "/api/research/context")
        assert status == 200
        assert research["capability"]["status"] == "BLOCKED_DATA"
        assert research["capability"]["holdout"] == "SEALED_UNREAD"
        assert research["capability"]["holdout_stress"] == "SEALED_UNREAD"

        status, _, _, generation = _request(server, "/api/generation/context")
        assert status == 200
        assert isinstance(generation, dict)

        status, _, _, check_data = _post(
            server, "/api/campaigns", {"action": "CHECK_DATA"}
        )
        assert status == 503
        assert check_data["error"] == "pilot_unavailable"
