"""T0/T1 HTTP contracts for explicit one-shot Holdout authorization."""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from lab import research_console
from lab import holdout_run
from lab.database import init_database
from tests.test_development_console_http import _post, _serve_console
from tests.test_holdout_run import _eligible_run, _prepare_continuation


@pytest.fixture
def database(tmp_path: Path) -> Path:
    path = tmp_path / "lab.sqlite"
    init_database(path)
    return path


def test_t0_http_accepts_only_exact_authorize_holdout_action(
    tmp_path: Path,
    database: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def fake_authorize(
        _controller: research_console.ResearchConsoleController,
        research_run_id: str,
    ) -> dict[str, Any]:
        calls.append(research_run_id)
        return {
            "research_run_id": research_run_id,
            "status": "RUNNING",
            "stage": "HOLDOUT_BACKTEST",
            "verdict": None,
        }

    monkeypatch.setattr(
        research_console.ResearchConsoleController,
        "authorize_holdout",
        fake_authorize,
    )
    with _serve_console(database, tmp_path) as server:
        status, _, _, payload = _post(
            server,
            "/api/research-runs/run-eligible/actions",
            {"action": "AUTHORIZE_HOLDOUT"},
        )

    assert status == 202
    assert calls == ["run-eligible"]
    assert payload == {
        "research_run_id": "run-eligible",
        "status": "RUNNING",
        "stage": "HOLDOUT_BACKTEST",
        "verdict": None,
    }


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("path", "/private/holdout"),
        ("argv", ["freqtrade", "backtesting"]),
        ("timerange", "20990101-20990201"),
        ("fee", 0.0),
        ("threshold", -999),
        ("scenario", "DEVELOPMENT"),
        ("executable", "/tmp/freqtrade"),
        ("environment", {"PATH": "/tmp"}),
        ("command", "touch /tmp/not-allowed"),
        ("output_location", "/tmp/results"),
    ),
)
def test_t0_http_rejects_browser_control_fields_before_controller(
    tmp_path: Path,
    database: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: Any,
) -> None:
    monkeypatch.setattr(
        research_console.ResearchConsoleController,
        "authorize_holdout",
        lambda *_args, **_kwargs: pytest.fail(
            "invalid browser fields must not reach the controller"
        ),
    )
    with _serve_console(database, tmp_path) as server:
        status, _, _, payload = _post(
            server,
            "/api/research-runs/run-eligible/actions",
            {"action": "AUTHORIZE_HOLDOUT", field: value},
        )

    assert status == 400
    assert payload["error"] == "invalid_action"


@pytest.mark.parametrize(
    ("case", "expected_error"),
    (
        ("missing_origin", "bad_origin"),
        ("missing_csrf", "bad_csrf"),
    ),
)
def test_t0_http_authorization_keeps_same_origin_and_csrf_boundary(
    tmp_path: Path,
    database: Path,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
    expected_error: str,
) -> None:
    monkeypatch.setattr(
        research_console.ResearchConsoleController,
        "authorize_holdout",
        lambda *_args, **_kwargs: pytest.fail(
            "rejected origin/CSRF requests must not reach the controller"
        ),
    )
    with _serve_console(database, tmp_path) as server:
        headers = {"Content-Type": "application/json"}
        if case == "missing_csrf":
            headers["Origin"] = f"http://127.0.0.1:{server.server_port}"
        status, _, _, payload = _post(
            server,
            "/api/research-runs/run-eligible/actions",
            {"action": "AUTHORIZE_HOLDOUT"},
            headers=headers,
        )

    assert status == 403
    assert payload["error"] == expected_error


def test_t1_http_authorization_obeys_existing_single_task_slot(
    tmp_path: Path,
    database: Path,
) -> None:
    with _serve_console(database, tmp_path) as server:
        controller = server.research_console_controller
        controller._active = object()
        try:
            status, _, _, payload = _post(
                server,
                "/api/research-runs/run-eligible/actions",
                {"action": "AUTHORIZE_HOLDOUT"},
            )
        finally:
            controller._active = None

    assert status == 409
    assert payload["error"] == "active_campaign"


def test_t1_http_cancel_uses_the_existing_research_run_cancel_boundary(
    tmp_path: Path,
    database: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def fake_cancel(
        _controller: research_console.ResearchConsoleController,
        research_run_id: str,
    ) -> dict[str, Any]:
        calls.append(research_run_id)
        return {
            "research_run_id": research_run_id,
            "status": "CANCELLED",
            "verdict": None,
        }

    monkeypatch.setattr(
        research_console.ResearchConsoleController,
        "cancel_research_run",
        fake_cancel,
    )
    with _serve_console(database, tmp_path) as server:
        status, _, _, payload = _post(
            server,
            "/api/research-runs/run-authorized/actions",
            {"action": "CANCEL"},
        )

    assert status == 202
    assert calls == ["run-authorized"]
    assert payload == {
        "research_run_id": "run-authorized",
        "status": "CANCELLED",
        "verdict": None,
    }


def test_t1_restart_recovers_authoritative_failed_db_without_confirmation(
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
    holdout_run.fail_holdout_continuation(
        database,
        run_dir,
        research_run_id,
        "FAILED",
        "CONTROLLER_FAILED",
    )
    controller = object.__new__(research_console.ResearchConsoleController)
    controller.config = SimpleNamespace(database_path=database)
    controller.campaigns_root = run_dir.parent
    controller._state_unavailable = set()
    monkeypatch.setattr(controller, "_append_event_at", lambda *_args: None)
    campaign_fd = os.open(run_dir, os.O_RDONLY | os.O_DIRECTORY)
    try:
        recovered = controller._reconcile_holdout_at(
            campaign_fd,
            research_run_id,
            {
                "action": "HOLDOUT_CONTINUATION",
                "status": "RUNNING",
                "created_at_utc": "2026-01-01T00:00:00.000Z",
            },
        )
    finally:
        os.close(campaign_fd)

    receipt = json.loads((run_dir / "holdout-status.json").read_text())
    assert recovered == "UNCHANGED"
    assert receipt["status"] == "FAILED"
    assert receipt["requires_confirmation"] is False
    assert controller._state_unavailable == set()


def test_t1_restart_replaces_stale_confirmation_with_authoritative_failed_db(
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
    holdout_run.fail_holdout_continuation(
        database,
        run_dir,
        research_run_id,
        "INTERRUPTED",
        "RESTART_INTERRUPTED",
    )
    stale = {
        "action": "HOLDOUT_CONTINUATION",
        "status": "INTERRUPTED_NEEDS_CONFIRMATION",
        "requires_confirmation": True,
        "created_at_utc": "2026-01-01T00:00:00.000Z",
    }
    (run_dir / "holdout-status.json").write_text(json.dumps(stale))

    controller = object.__new__(research_console.ResearchConsoleController)
    controller.config = SimpleNamespace(database_path=database)
    controller.campaigns_root = run_dir.parent
    controller._state_unavailable = set()
    monkeypatch.setattr(controller, "_append_event_at", lambda *_args: None)
    campaign_fd = os.open(run_dir, os.O_RDONLY | os.O_DIRECTORY)
    try:
        recovered = controller._reconcile_holdout_at(
            campaign_fd,
            research_run_id,
            stale,
        )
    finally:
        os.close(campaign_fd)

    receipt = json.loads((run_dir / "holdout-status.json").read_text())
    assert recovered == "UNCHANGED"
    assert receipt["status"] == "INTERRUPTED"
    assert receipt["requires_confirmation"] is False
    assert controller._state_unavailable == set()
