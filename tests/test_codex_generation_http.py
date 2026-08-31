"""T1/T2 HTTP and process-boundary tests for Issue #28."""

from __future__ import annotations

import http.client
import json
import os
import sqlite3
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping, Optional
from uuid import uuid4

import pytest

from lab import research_console
from lab.codex_generation import (
    build_codex_argv,
    load_generation,
    start_generation,
    validate_generation_request,
)
from lab.database import init_database
from lab.strategy_library import load_strategy_library


PROFILE_ID = "profile-btc-5m"
VALID_REQUEST = {
    "profile_id": PROFILE_ID,
    "idea": "Test one bounded EMA pullback hypothesis.",
    "strategy_family": "trend",
    "expected_failure_mode": "Sideways markets may whipsaw.",
}
TERMINAL_DATABASE_STATUSES = {"COMPLETED", "FAILED"}


def test_t0_console_keeps_polling_until_database_and_runtime_are_terminal() -> None:
    assert "value.status === 'RUNNING' || runtimeActive" in research_console.CONSOLE_JS
    assert (
        "value.status === 'RUNNING' || (value.runtime_status !== null && "
        "!terminal(value.runtime_status))"
    ) in research_console.CONSOLE_JS
    assert "value.runtime_status === 'SUCCEEDED'" in research_console.CONSOLE_JS


def _database(tmp_path: Path) -> Path:
    database = tmp_path / "lab.sqlite"
    init_database(database)
    connection = sqlite3.connect(database)
    try:
        connection.execute(
            """
            INSERT INTO research_profiles (
                id, name, domain, pairs_json, timeframe, history_start_date,
                smoke_days, holdout_days, starting_balance, max_open_trades,
                taker_fee_rate, stress_fee_multiplier, max_drawdown_pct,
                min_development_trades, min_holdout_trades, min_profit_factor,
                is_default, created_at, updated_at
            ) VALUES (
                ?, 'BTC 5m', 'OKX_CRYPTO_PERP', '["BTC/USDT:USDT"]',
                '5m', '2026-01-01', 7, 30, 1000, 1, 0.0005, 2, 20,
                10, 10, 1.1, 1, '2026-09-01T00:00:00Z',
                '2026-09-01T00:00:00Z'
            )
            """,
            (PROFILE_ID,),
        )
        connection.commit()
    finally:
        connection.close()
    return database


def _fake_codex(tmp_path: Path, mode: str) -> tuple[Path, Path]:
    executable = tmp_path / f"fake-codex-{mode}"
    marker = tmp_path / f"fake-codex-{mode}.json"
    source = f'''#!{sys.executable}
import json
import os
import signal
import sys
import time
from pathlib import Path

MODE = {mode!r}
MARKER = Path({str(marker)!r})
args = sys.argv[1:]
if args == ["--version"]:
    print("codex-cli fake-issue-28")
    raise SystemExit(0)
if args == ["exec", "--help"]:
    flags = "--cd --config --disable --ephemeral --ignore-user-config --ignore-rules --json --output-schema --output-last-message --sandbox --skip-git-repo-check --color"
    print(flags.replace("--output-schema", "") if MODE == "missing_flag" else flags)
    raise SystemExit(0)
if args[-2:] == ["features", "list"]:
    disabled = [args[index + 1] for index, item in enumerate(args[:-2]) if item == "--disable"]
    for feature in disabled:
        print(feature + " stable false")
    raise SystemExit(0)
if MODE == "never_read_stdin":
    while True:
        time.sleep(0.05)
prompt = sys.stdin.buffer.read()
business_context = json.loads(prompt.decode("utf-8").split("BUSINESS_CONTEXT_JSON:\\n", 1)[1])
MARKER.write_text(json.dumps({{
    "argv": args,
    "cwd": os.getcwd(),
    "env_keys": sorted(os.environ),
    "prompt": prompt.decode("utf-8"),
}}, ensure_ascii=False), encoding="utf-8")
if MODE == "sleep":
    while True:
        time.sleep(0.05)
if MODE == "nonzero":
    print("private failure", file=sys.stderr, flush=True)
    raise SystemExit(7)
if MODE == "stderr":
    print("hidden diagnostic", file=sys.stderr, flush=True)
if MODE == "oversize":
    sys.stdout.write("x" * (1024 * 1024 + 1))
    sys.stdout.flush()
    while True:
        time.sleep(0.05)
output_path = Path(args[args.index("--output-last-message") + 1])
if MODE == "output_oversize":
    output_path.write_bytes(b"x" * ({research_console.MAX_CODE_BYTES * 2 + 1}))
    while True:
        time.sleep(0.05)
if MODE == "output_symlink":
    output_path.symlink_to(MARKER)
    while True:
        time.sleep(0.05)
if MODE == "output_hardlink":
    source = output_path.with_name("codex-output-source.json")
    source.write_bytes(b"{{}}")
    os.link(source, output_path)
    while True:
        time.sleep(0.05)
if MODE == "invalid":
    output_path.write_bytes(b"{{bad-json")
else:
    if business_context["parent"] is not None:
        display_name = "Child EMA Pullback"
        class_name = "ChildEmaPullback"
    elif "pending unique" in business_context["request"]["idea"].lower():
        display_name = "Pending EMA Pullback"
        class_name = "PendingEmaPullback"
    else:
        display_name = "Bounded EMA Pullback"
        class_name = "BoundedEmaPullback"
    output_path.write_text(json.dumps({{
        "display_name": display_name,
        "class_name": class_name,
        "code_text": "from freqtrade.strategy import IStrategy\\n\\nclass " + class_name + "(IStrategy):\\n    timeframe = \\\"5m\\\"\\n",
    }}, separators=(",", ":")), encoding="utf-8")
print(json.dumps({{"type":"thread.started","thread_id":"thread-fake"}}), flush=True)
print(json.dumps({{"type":"turn.started"}}), flush=True)
if MODE == "tool":
    print(json.dumps({{"type":"item.completed","item":{{"type":"command_execution"}}}}), flush=True)
else:
    print(json.dumps({{"type":"item.completed","item":{{"type":"agent_message","text":"done"}}}}), flush=True)
print(json.dumps({{"type":"turn.completed","usage":{{"input_tokens":1,"output_tokens":1}}}}), flush=True)
'''
    executable.write_text(source, encoding="utf-8")
    executable.chmod(0o700)
    return executable, marker


@contextmanager
def _serve(
    tmp_path: Path,
    *,
    mode: str,
    timeout: float = 5.0,
) -> Iterator[tuple[Any, Path, Path, Path]]:
    database = _database(tmp_path)
    runtime = tmp_path / "runtime"
    pilot = tmp_path / "pilot"
    runtime.mkdir()
    pilot.mkdir()
    codex, marker = _fake_codex(tmp_path, mode)
    server = research_console.create_research_console_server(
        database,
        runtime,
        pilot,
        0,
        codex_binary=codex,
        task_timeout_seconds=timeout,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, database, runtime, marker
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
    payload: Optional[Mapping[str, Any]] = None,
) -> tuple[int, dict[str, Any], bytes]:
    body = None
    headers: dict[str, str] = {}
    if payload is not None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        headers = {
            "Origin": f"http://127.0.0.1:{server.server_port}",
            "X-CSRF-Token": server.research_console_csrf_token,
            "Content-Type": "application/json",
        }
    connection = http.client.HTTPConnection(
        "127.0.0.1", server.server_port, timeout=5
    )
    try:
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        raw = response.read()
        value = json.loads(raw.decode("utf-8")) if raw else {}
        return response.status, value, raw
    finally:
        connection.close()


def _wait_generation(
    server: Any, generation_id: str, *, timeout: float = 6.0
) -> tuple[int, dict[str, Any], bytes]:
    deadline = time.monotonic() + timeout
    latest: tuple[int, dict[str, Any], bytes] | None = None
    while time.monotonic() < deadline:
        latest = _request(server, f"/api/generations/{generation_id}")
        runtime_status = latest[1].get("runtime_status")
        if (
            latest[1].get("status") in TERMINAL_DATABASE_STATUSES
            and runtime_status in research_console.TERMINAL_STATUSES
        ):
            return latest
        time.sleep(0.02)
    pytest.fail(f"generation did not finish: {latest!r}")


def _counts(database: Path) -> dict[str, int]:
    connection = sqlite3.connect(database)
    try:
        return {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in (
                "generation_runs",
                "candidates",
                "research_runs",
                "backtest_executions",
                "releases",
            )
        }
    finally:
        connection.close()


def test_t2_real_http_generate_preview_approve_and_library_visibility(
    tmp_path: Path,
) -> None:
    with _serve(tmp_path, mode="success") as (server, database, runtime, marker):
        status, context, _ = _request(server, "/api/generation/context")
        assert status == 200
        assert context["profiles"] == [
            {
                "id": PROFILE_ID,
                "is_default": True,
                "name": "BTC 5m",
                "timeframe": "5m",
            }
        ]
        assert context["approved_parents"] == []

        for forbidden in ("model", "argv", "cwd", "path", "env", "prompt", "command"):
            status, error, _ = _request(
                server,
                "/api/generations",
                method="POST",
                payload={**VALID_REQUEST, forbidden: "attacker"},
            )
            assert status == 400
            assert error["error"] == "invalid_request_fields"
        assert _counts(database)["generation_runs"] == 0
        assert list((runtime / "campaigns").iterdir()) == []

        status, created, raw = _request(
            server,
            "/api/generations",
            method="POST",
            payload=VALID_REQUEST,
        )
        assert status == 202
        generation_id = created["id"]
        status, completed, raw = _wait_generation(server, generation_id)
        assert status == 200
        assert completed["status"] == "COMPLETED"
        assert completed["runtime_status"] == "SUCCEEDED"
        assert completed["tool_event_count"] == 0
        assert completed["candidate"]["review_status"] == "PENDING"
        assert completed["candidate"]["code_sha256"]
        assert str(tmp_path).encode() not in raw
        assert b"stdout" not in raw and b"stderr" not in raw
        assert load_strategy_library(database)["strategies"] == []

        captured = json.loads(marker.read_text(encoding="utf-8"))
        campaign = runtime / "campaigns" / generation_id
        expected_argv = build_codex_argv(
            Path(server.research_console_controller.config.codex_binary),
            campaign / "workspace",
            campaign / "output-schema.json",
            campaign / "codex-output.json",
            model=None,
        )[1:]
        assert tuple(captured["argv"]) == expected_argv
        assert captured["cwd"] == str(campaign / "workspace")
        captured_env = set(captured["env_keys"])
        expected_env = set(research_console._codex_environment())
        assert expected_env.issubset(captured_env)
        assert captured_env - expected_env <= {"__CF_USER_TEXT_ENCODING"}
        context_json = json.loads(captured["prompt"].split("BUSINESS_CONTEXT_JSON:\n", 1)[1])
        assert context_json["request"] == {
            **VALID_REQUEST,
            "parent_candidate_id": None,
        }
        assert "model" not in context_json["request"]

        status, approved, _ = _request(
            server,
            f"/api/generations/{generation_id}/actions",
            method="POST",
            payload={"action": "APPROVE"},
        )
        assert status == 200
        assert approved["candidate"]["review_status"] == "APPROVED"
        assert approved["runtime_status"] == "SUCCEEDED"
        assert "人工批准" in approved["message"]
        assert len(load_strategy_library(database)["strategies"]) == 1
        status, repeated, _ = _request(
            server,
            f"/api/generations/{generation_id}/actions",
            method="POST",
            payload={"action": "APPROVE"},
        )
        assert status == 200
        assert repeated == approved
        status, conflict, _ = _request(
            server,
            f"/api/generations/{generation_id}/actions",
            method="POST",
            payload={"action": "REJECT"},
        )
        assert status == 409
        assert conflict["error"] == "review_conflict"
        assert _counts(database) == {
            "generation_runs": 1,
            "candidates": 1,
            "research_runs": 0,
            "backtest_executions": 0,
            "releases": 0,
        }
        for name in ("candidate.py", "codex-output.json", "output-schema.json"):
            assert (campaign / name).stat().st_mode & 0o077 == 0


def test_t0_maximum_legal_multibyte_business_input_fits_http_limit(
    tmp_path: Path,
) -> None:
    payload = {
        "profile_id": PROFILE_ID,
        "idea": "研" * 1200,
        "strategy_family": "策" * 80,
        "expected_failure_mode": "失" * 600,
    }
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )
    assert 4096 < len(raw) <= research_console.MAX_REQUEST_BYTES
    with _serve(tmp_path, mode="success") as (server, _database, _runtime, _marker):
        status, created, _ = _request(
            server, "/api/generations", method="POST", payload=payload
        )
        assert status == 202
        status, completed, _ = _wait_generation(server, created["id"])
        assert status == 200
        assert completed["status"] == "COMPLETED"


def test_t1_generation_hard_fails_when_frozen_codex_capability_is_missing(
    tmp_path: Path,
) -> None:
    with _serve(tmp_path, mode="missing_flag") as (
        server,
        database,
        runtime,
        marker,
    ):
        status, preflight, _ = _request(server, "/api/control/preflight")
        assert status == 200
        assert preflight["checks"]["codex"]["status"] == "UNAVAILABLE"
        assert preflight["checks"]["codex"]["model_invoked"] is False
        status, error, _ = _request(
            server, "/api/generations", method="POST", payload=VALID_REQUEST
        )
        assert status == 503
        assert error["error"] == "codex_capability_unavailable"
        assert _counts(database)["generation_runs"] == 0
        assert not marker.exists()
        assert list((runtime / "campaigns").iterdir()) == []


def test_t1_generation_rejects_replaced_frozen_codex_executable(
    tmp_path: Path,
) -> None:
    with _serve(tmp_path, mode="success") as (server, database, runtime, marker):
        controller = server.research_console_controller
        frozen = Path(controller.config.codex_binary)
        frozen_identity = controller.config.codex_identity
        replacement_root = tmp_path / "replacement"
        replacement_root.mkdir()
        replacement, replacement_marker = _fake_codex(replacement_root, "success")
        os.replace(replacement, frozen)
        assert research_console._executable_identity(frozen) != frozen_identity

        status, preflight, _ = _request(server, "/api/control/preflight")
        assert status == 200
        assert preflight["checks"]["codex"]["status"] == "UNAVAILABLE"
        assert preflight["checks"]["codex"]["binary_identity_unchanged"] is False
        status, error, raw = _request(
            server, "/api/generations", method="POST", payload=VALID_REQUEST
        )
        assert status == 409
        assert error["error"] == "codex_binary_changed"
        assert str(frozen).encode() not in raw
        assert _counts(database)["generation_runs"] == 0
        assert list((runtime / "campaigns").iterdir()) == []
        assert not marker.exists()
        assert not replacement_marker.exists()


@pytest.mark.parametrize(
    ("mode", "error_code"),
    (
        ("nonzero", "CODEX_NONZERO"),
        ("invalid", "INVALID_JSON"),
        ("tool", "CODEX_TOOL_EVENT"),
        ("stderr", "CODEX_STDERR_NONEMPTY"),
        ("oversize", "OUTPUT_LIMIT_EXCEEDED"),
        ("output_oversize", "OUTPUT_LIMIT_EXCEEDED"),
        ("output_symlink", "OUTPUT_LIMIT_EXCEEDED"),
        ("output_hardlink", "OUTPUT_LIMIT_EXCEEDED"),
    ),
)
def test_t1_fake_codex_failures_are_failed_with_zero_candidate(
    tmp_path: Path, mode: str, error_code: str
) -> None:
    with _serve(tmp_path, mode=mode) as (server, database, _runtime, _marker):
        status, created, _ = _request(
            server,
            "/api/generations",
            method="POST",
            payload=VALID_REQUEST,
        )
        assert status == 202
        status, failed, raw = _wait_generation(server, created["id"])
        assert status == 200
        assert failed["status"] == "FAILED"
        assert failed["error_code"] == error_code
        assert failed["candidate"] is None
        assert _counts(database)["candidates"] == 0
        assert str(tmp_path).encode() not in raw


def test_t1_generation_shares_slot_cancel_and_timeout_fail_database(
    tmp_path: Path,
) -> None:
    with _serve(tmp_path, mode="sleep", timeout=5.0) as (
        server,
        database,
        _runtime,
        marker,
    ):
        status, created, _ = _request(
            server,
            "/api/generations",
            method="POST",
            payload=VALID_REQUEST,
        )
        assert status == 202
        deadline = time.monotonic() + 3
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert marker.exists()

        status, conflict, _ = _request(
            server,
            "/api/campaigns",
            method="POST",
            payload={"action": "CHECK_DATA"},
        )
        assert status == 409
        assert conflict["error"] == "active_campaign"

        status, _, _ = _request(
            server,
            f"/api/generations/{created['id']}/actions",
            method="POST",
            payload={"action": "CANCEL"},
        )
        assert status == 202
        _, failed, _ = _wait_generation(server, created["id"])
        assert failed["status"] == "FAILED"
        assert failed["runtime_status"] == "CANCELLED"
        assert failed["error_code"] == "CANCELLED"
        assert _counts(database)["candidates"] == 0

    timeout_root = tmp_path / "timeout-case"
    timeout_root.mkdir()
    with _serve(timeout_root, mode="sleep", timeout=0.15) as (
        server,
        database,
        _runtime,
        _marker,
    ):
        status, created, _ = _request(
            server,
            "/api/generations",
            method="POST",
            payload=VALID_REQUEST,
        )
        assert status == 202
        _, failed, _ = _wait_generation(server, created["id"])
        assert failed["status"] == "FAILED"
        assert failed["runtime_status"] == "TIMED_OUT"
        assert failed["error_code"] == "TIMED_OUT"
        assert _counts(database)["candidates"] == 0


def test_t1_large_controlled_stdin_cannot_block_timeout_monitor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with _serve(tmp_path, mode="never_read_stdin", timeout=0.15) as (
        server,
        database,
        _runtime,
        _marker,
    ):
        monkeypatch.setattr(
            research_console,
            "build_prompt",
            lambda *_args: b"x" * (192 * 1024),
        )
        started = time.monotonic()
        status, created, _ = _request(
            server, "/api/generations", method="POST", payload=VALID_REQUEST
        )
        assert status == 202
        assert time.monotonic() - started < 2.0
        _, failed, _ = _wait_generation(server, created["id"])
        assert failed["status"] == "FAILED"
        assert failed["runtime_status"] == "TIMED_OUT"
        assert failed["error_code"] == "TIMED_OUT"
        assert _counts(database)["candidates"] == 0


def test_t1_duplicate_is_http_409_and_never_overwrites_candidate(
    tmp_path: Path,
) -> None:
    with _serve(tmp_path, mode="success") as (server, database, _runtime, _marker):
        status, first, _ = _request(
            server, "/api/generations", method="POST", payload=VALID_REQUEST
        )
        assert status == 202
        status, completed, _ = _wait_generation(server, first["id"])
        assert status == 200
        existing_id = completed["candidate"]["id"]

        status, second, _ = _request(
            server,
            "/api/generations",
            method="POST",
            payload={**VALID_REQUEST, "idea": "A different idea with identical source."},
        )
        assert status == 202
        status, duplicate, raw = _wait_generation(server, second["id"])
        assert status == 409
        assert duplicate["status"] == "FAILED"
        assert duplicate["error"] == "duplicate_candidate"
        assert duplicate["error_code"] == "DUPLICATE_CODE_SHA256"
        assert duplicate["existing_candidate_id"] == existing_id
        assert duplicate["candidate"] is None
        assert duplicate["runtime_status"] == "FAILED"
        assert _counts(database)["candidates"] == 1
        assert str(tmp_path).encode() not in raw


def test_t1_parent_requires_same_profile_and_approved_then_freezes_lineage(
    tmp_path: Path,
) -> None:
    with _serve(tmp_path, mode="success") as (server, database, _runtime, _marker):
        status, first, _ = _request(
            server, "/api/generations", method="POST", payload=VALID_REQUEST
        )
        assert status == 202
        _, completed, _ = _wait_generation(server, first["id"])
        parent_id = completed["candidate"]["id"]
        status, approved, _ = _request(
            server,
            f"/api/generations/{first['id']}/actions",
            method="POST",
            payload={"action": "APPROVE"},
        )
        assert status == 200
        assert approved["candidate"]["review_status"] == "APPROVED"
        status, context, _ = _request(server, "/api/generation/context")
        assert status == 200
        assert [item["id"] for item in context["approved_parents"]] == [parent_id]

        child_request = {
            **VALID_REQUEST,
            "parent_candidate_id": parent_id,
            "idea": "Revise the approved parent with one bounded increment.",
        }
        status, child, _ = _request(
            server, "/api/generations", method="POST", payload=child_request
        )
        assert status == 202
        status, child_completed, _ = _wait_generation(server, child["id"])
        assert status == 200
        assert child_completed["candidate"]["parent_candidate_id"] == parent_id
        assert child_completed["candidate"]["class_name"] == "ChildEmaPullback"

        status, pending, _ = _request(
            server,
            "/api/generations",
            method="POST",
            payload={**VALID_REQUEST, "idea": "Pending unique candidate."},
        )
        assert status == 202
        _, pending_completed, _ = _wait_generation(server, pending["id"])
        pending_id = pending_completed["candidate"]["id"]
        before = _counts(database)
        status, error, _ = _request(
            server,
            "/api/generations",
            method="POST",
            payload={**child_request, "parent_candidate_id": pending_id},
        )
        assert status == 409
        assert error["error"] == "parent_not_approved"
        assert _counts(database) == before

        connection = sqlite3.connect(database)
        try:
            connection.execute(
                """
                INSERT INTO research_profiles
                SELECT 'profile-eth-5m', 'ETH 5m', domain, exchange, trading_mode,
                       margin_mode, '["ETH/USDT:USDT"]', timeframe,
                       detail_timeframe, history_start_date, smoke_days,
                       holdout_days, starting_balance, stake_amount,
                       max_open_trades, taker_fee_rate, stress_fee_multiplier,
                       max_drawdown_pct, min_development_trades,
                       min_holdout_trades, min_profit_factor, 0, created_at, updated_at
                FROM research_profiles WHERE id = ?
                """,
                (PROFILE_ID,),
            )
            connection.commit()
        finally:
            connection.close()
        status, error, _ = _request(
            server,
            "/api/generations",
            method="POST",
            payload={
                **child_request,
                "profile_id": "profile-eth-5m",
                "parent_candidate_id": parent_id,
            },
        )
        assert status == 409
        assert error["error"] == "parent_profile_mismatch"
        assert _counts(database) == before


def test_t2_restart_marks_running_generation_failed_and_latches_runtime(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    runtime = tmp_path / "runtime"
    pilot = tmp_path / "pilot"
    campaigns = runtime / "campaigns"
    campaigns.mkdir(parents=True)
    pilot.mkdir()
    generation_id = str(uuid4())
    start_generation(
        database,
        generation_id,
        validate_generation_request(VALID_REQUEST),
        model=None,
        started_at="2026-09-01T00:00:00.000Z",
    )
    campaign = campaigns / generation_id
    campaign.mkdir(mode=0o700)
    (campaign / "status.json").write_text(
        json.dumps(
            {
                "schema": research_console.STATUS_SCHEMA,
                "campaign_id": generation_id,
                "action": "CODEX_GENERATION",
                "status": "RUNNING",
                "requires_confirmation": False,
            }
        ),
        encoding="utf-8",
    )
    codex, _marker = _fake_codex(tmp_path, "success")

    server = research_console.create_research_console_server(
        database, runtime, pilot, 0, codex_binary=codex
    )
    try:
        controller = server.research_console_controller
        recovered = load_generation(database, generation_id)
        assert recovered["status"] == "FAILED"
        assert recovered["error_code"] == "RESTART_INTERRUPTED"
        assert recovered["candidate"] is None
        assert controller._restart_confirmation_required is True
        with pytest.raises(research_console.ControlRequestError) as exc_info:
            controller.create_generation(validate_generation_request(VALID_REQUEST))
        assert exc_info.value.status == 409
        assert exc_info.value.code == "restart_confirmation_required"
    finally:
        server.research_console_controller.shutdown()
        server.server_close()


def test_t2_restart_reconciles_interrupted_missing_and_damaged_receipts(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    runtime = tmp_path / "runtime"
    pilot = tmp_path / "pilot"
    campaigns = runtime / "campaigns"
    campaigns.mkdir(parents=True)
    pilot.mkdir()
    generation_ids: list[str] = []
    for receipt_kind in ("interrupted", "missing", "damaged"):
        generation_id = str(uuid4())
        generation_ids.append(generation_id)
        start_generation(
            database,
            generation_id,
            validate_generation_request(
                {**VALID_REQUEST, "idea": f"Restart case {receipt_kind}."}
            ),
            model=None,
            started_at="2026-09-01T00:00:00.000Z",
        )
        campaign = campaigns / generation_id
        campaign.mkdir(mode=0o700)
        if receipt_kind == "interrupted":
            (campaign / "status.json").write_text(
                json.dumps(
                    {
                        "schema": research_console.STATUS_SCHEMA,
                        "campaign_id": generation_id,
                        "action": "CODEX_GENERATION",
                        "status": "INTERRUPTED_NEEDS_CONFIRMATION",
                        "requires_confirmation": True,
                    }
                ),
                encoding="utf-8",
            )
        elif receipt_kind == "damaged":
            (campaign / "status.json").write_text("{bad-json", encoding="utf-8")
    codex, _marker = _fake_codex(tmp_path, "success")

    server = research_console.create_research_console_server(
        database, runtime, pilot, 0, codex_binary=codex
    )
    try:
        controller = server.research_console_controller
        assert controller._restart_confirmation_required is True
        for generation_id in generation_ids:
            recovered = load_generation(database, generation_id)
            assert recovered["status"] == "FAILED"
            assert recovered["error_code"] == "RESTART_INTERRUPTED"
            assert recovered["candidate"] is None
            receipt = controller.get_status(generation_id)
            assert receipt["status"] == "INTERRUPTED_NEEDS_CONFIRMATION"
            assert receipt["requires_confirmation"] is True
        assert _counts(database)["candidates"] == 0
    finally:
        server.research_console_controller.shutdown()
        server.server_close()


def test_t2_restart_restores_completed_database_truth_over_interrupted_receipt(
    tmp_path: Path,
) -> None:
    with _serve(tmp_path, mode="success") as (server, database, runtime, _marker):
        status, created, _ = _request(
            server, "/api/generations", method="POST", payload=VALID_REQUEST
        )
        assert status == 202
        _, completed, _ = _wait_generation(server, created["id"])
        assert completed["status"] == "COMPLETED"
        generation_id = created["id"]
        codex = Path(server.research_console_controller.config.codex_binary)

    status_path = runtime / "campaigns" / generation_id / "status.json"
    interrupted = json.loads(status_path.read_text(encoding="utf-8"))
    interrupted.update(
        {
            "status": "INTERRUPTED_NEEDS_CONFIRMATION",
            "requires_confirmation": True,
            "return_code": None,
            "message": "injected stale receipt",
        }
    )
    status_path.write_text(json.dumps(interrupted), encoding="utf-8")

    restarted = research_console.create_research_console_server(
        database,
        runtime,
        tmp_path / "pilot",
        0,
        codex_binary=codex,
    )
    try:
        controller = restarted.research_console_controller
        assert controller._restart_confirmation_required is False
        recovered = load_generation(database, generation_id)
        assert recovered["status"] == "COMPLETED"
        assert recovered["candidate"] is not None
        receipt = controller.get_status(generation_id)
        assert receipt["status"] == "SUCCEEDED"
        assert receipt["requires_confirmation"] is False
    finally:
        restarted.research_console_controller.shutdown()
        restarted.server_close()


def test_t2_private_file_reads_and_candidate_publish_are_fail_closed(
    tmp_path: Path,
) -> None:
    directory_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        regular = tmp_path / "regular"
        regular.write_bytes(b"bounded")
        assert research_console._read_bounded_private_file_at(
            directory_fd, "regular", 32
        ) == b"bounded"

        (tmp_path / "oversize").write_bytes(b"x" * 33)
        with pytest.raises(ValueError):
            research_console._read_bounded_private_file_at(
                directory_fd, "oversize", 32
            )

        os.symlink("regular", tmp_path / "link")
        with pytest.raises(OSError):
            research_console._read_bounded_private_file_at(directory_fd, "link", 32)

        os.mkfifo(tmp_path / "fifo", 0o600)
        with pytest.raises(ValueError):
            research_console._read_bounded_private_file_at(directory_fd, "fifo", 32)

        os.link(regular, tmp_path / "hardlink")
        with pytest.raises(ValueError):
            research_console._read_bounded_private_file_at(
                directory_fd, "regular", 32
            )

        research_console._atomic_publish_bytes_at(
            directory_fd, "candidate.py", b"first"
        )
        published = tmp_path / "candidate.py"
        assert published.read_bytes() == b"first"
        assert published.stat().st_mode & 0o777 == 0o600
        with pytest.raises(FileExistsError):
            research_console._atomic_publish_bytes_at(
                directory_fd, "candidate.py", b"replacement"
            )
        assert published.read_bytes() == b"first"
        assert not tuple(tmp_path.glob(".candidate.py.*.tmp"))
    finally:
        os.close(directory_fd)
