"""Risk-tiered tests for the single-process local Research Console."""

from __future__ import annotations

import http.client
import json
import os
import re
import selectors
import signal
import socket
import sqlite3
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping, Optional, Sequence
from urllib.parse import urlsplit
from uuid import uuid4

import pytest

from lab import research_console
from lab.database import init_database


BUSINESS_TABLES = (
    "research_profiles",
    "generation_runs",
    "candidates",
    "research_runs",
    "backtest_executions",
    "releases",
)
TERMINAL_STATUSES = {
    "SUCCEEDED",
    "FAILED",
    "CANCELLED",
    "TIMED_OUT",
    "INTERRUPTED_NEEDS_CONFIRMATION",
}
FAKE_CHILD_SOURCE = r"""
import json
import os
import signal
import sys
import time
from pathlib import Path

mode, marker = sys.argv[1:3]
Path(marker).write_text(
    json.dumps({"argv": sys.argv[1:], "pid": os.getpid()}),
    encoding="utf-8",
)
if mode == "success":
    print(json.dumps({"status": "DATA_READY"}), flush=True)
    raise SystemExit(0)
if mode == "fail":
    print("private-secret /tmp/should-not-leak", file=sys.stderr, flush=True)
    raise SystemExit(7)
if mode == "invalid":
    print(json.dumps({"status": "NOT_DATA_READY"}), flush=True)
    raise SystemExit(0)
if mode == "sleep":
    while True:
        time.sleep(0.05)
if mode == "ignore_term":
    signal.signal(
        signal.SIGTERM,
        lambda *_args: Path(str(marker) + ".term").write_text(
            "TERM", encoding="utf-8"
        ),
    )
    while True:
        time.sleep(0.05)
raise SystemExit(9)
""".lstrip()


@pytest.fixture
def database(tmp_path: Path) -> Path:
    path = tmp_path / "lab.sqlite"
    init_database(path)
    return path


def _write_fake_child(tmp_path: Path) -> tuple[Path, Path]:
    script = tmp_path / "fake_check_data.py"
    marker = tmp_path / "fake-child.json"
    script.write_text(FAKE_CHILD_SOURCE, encoding="utf-8")
    return script, marker


@contextmanager
def _serve_console(
    monkeypatch: pytest.MonkeyPatch,
    database: Path,
    tmp_path: Path,
    *,
    mode: Optional[str] = "success",
    timeout: float = 5.0,
) -> Iterator[tuple[Any, Path, Path]]:
    runtime_root = tmp_path / "runtime"
    pilot_root = tmp_path / "pilot"
    runtime_root.mkdir(exist_ok=True)
    pilot_root.mkdir(exist_ok=True)
    marker = tmp_path / "unused-marker"
    if mode is not None:
        script, marker = _write_fake_child(tmp_path)
        frozen_argv = (sys.executable, str(script), mode, str(marker))
        monkeypatch.setattr(
            research_console,
            "build_check_data_argv",
            lambda _pilot_root, _python: frozen_argv,
        )
    server = research_console.create_research_console_server(
        database,
        runtime_root,
        pilot_root,
        0,
        codex_binary=tmp_path / "missing-codex",
        task_timeout_seconds=timeout,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, marker, runtime_root
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
) -> tuple[int, Mapping[str, str], bytes, Any]:
    return _request(
        server,
        path,
        method="POST",
        body=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        headers=_post_headers(server),
    )


def _raw_post_with_headers(
    server: Any,
    headers: Sequence[tuple[str, str]],
    body: bytes,
) -> tuple[int, dict[str, Any]]:
    connection = http.client.HTTPConnection(
        "127.0.0.1", server.server_port, timeout=5
    )
    try:
        connection.putrequest(
            "POST", "/api/campaigns", skip_host=True, skip_accept_encoding=True
        )
        for name, value in headers:
            connection.putheader(name, value)
        connection.endheaders(body)
        response = connection.getresponse()
        return response.status, json.loads(response.read().decode("utf-8"))
    finally:
        connection.close()


def _raw_http(
    server: Any,
    method: str,
    target: str,
    headers: Sequence[tuple[str, str]],
    body: bytes = b"",
) -> tuple[int, Mapping[str, str], bytes]:
    request = (
        f"{method} {target} HTTP/1.1\r\n"
        + "".join(f"{name}: {value}\r\n" for name, value in headers)
        + "Connection: close\r\n\r\n"
    ).encode("ascii") + body
    with socket.create_connection(("127.0.0.1", server.server_port), timeout=5) as stream:
        stream.sendall(request)
        chunks = []
        while True:
            chunk = stream.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
    raw = b"".join(chunks)
    head, _, response_body = raw.partition(b"\r\n\r\n")
    lines = head.decode("iso-8859-1").split("\r\n")
    status = int(lines[0].split()[1])
    response_headers = {
        name.strip(): value.strip()
        for name, value in (line.split(":", 1) for line in lines[1:] if ":" in line)
    }
    return status, response_headers, response_body


def _assert_security_headers(headers: Mapping[str, str]) -> None:
    assert headers["Cache-Control"] == "no-store"
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["Referrer-Policy"] == "no-referrer"
    assert "default-src 'none'" in headers["Content-Security-Policy"]


def _wait_terminal(server: Any, campaign_id: str, timeout: float = 5.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: Any = None
    while time.monotonic() < deadline:
        status, _, _, payload = _request(
            server, f"/api/campaigns/{campaign_id}"
        )
        assert status == 200
        last = payload
        if payload["status"] in TERMINAL_STATUSES:
            return payload
        time.sleep(0.02)
    pytest.fail(f"campaign did not reach a terminal state: {last!r}")


def _wait_file(path: Path, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.is_file():
            return
        time.sleep(0.01)
    pytest.fail(f"fake child did not create its marker: {path.name}")


def _sqlite_snapshot(database: Path) -> dict[str, Any]:
    connection = sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True)
    try:
        schema = connection.execute(
            """
            SELECT type, name, tbl_name, sql
            FROM sqlite_master
            WHERE name NOT LIKE 'sqlite_%'
            ORDER BY type, name
            """
        ).fetchall()
        rows = {
            table: connection.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()
            for table in BUSINESS_TABLES
        }
        return {
            "version": connection.execute("PRAGMA user_version").fetchone()[0],
            "schema": schema,
            "rows": rows,
        }
    finally:
        connection.close()


def _start_console_cli(
    database: Path,
    runtime: Path,
    pilot: Path,
    fake_python: Path,
    missing_codex: Path,
) -> tuple[subprocess.Popen[str], int]:
    process = subprocess.Popen(
        [
            sys.executable,
            str(research_console.PROJECT_ROOT / "scripts" / "serve_research_console.py"),
            "--database",
            str(database),
            "--runtime-root",
            str(runtime),
            "--pilot-root",
            str(pilot),
            "--check-data-python",
            str(fake_python),
            "--codex-binary",
            str(missing_codex),
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
        assert selector.select(timeout=5), "console CLI did not print its URL"
        line = process.stdout.readline().strip()
    finally:
        selector.close()
    assert line.startswith("Research Console: http://127.0.0.1:")
    parsed = urlsplit(line.removeprefix("Research Console: "))
    assert parsed.port is not None
    return process, parsed.port


def _external_request(
    port: int,
    path: str,
    *,
    method: str = "GET",
    body: Optional[bytes] = None,
    headers: Optional[Mapping[str, str]] = None,
) -> tuple[int, bytes, Mapping[str, str]]:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        connection.request(method, path, body=body, headers=dict(headers or {}))
        response = connection.getresponse()
        return response.status, response.read(), dict(response.getheaders())
    finally:
        connection.close()


def test_t0_post_requires_exact_security_headers_and_body(
    database: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with _serve_console(monkeypatch, database, tmp_path) as (server, marker, runtime):
        valid = _post_headers(server)
        body = b'{"action":"CHECK_DATA"}'
        cases: Sequence[tuple[str, dict[str, str], bytes, str, int]] = (
            (
                "bad-host",
                {**valid, "Host": "attacker.example"},
                body,
                "/api/campaigns",
                400,
            ),
            (
                "missing-origin",
                {key: value for key, value in valid.items() if key != "Origin"},
                body,
                "/api/campaigns",
                403,
            ),
            (
                "bad-origin",
                {**valid, "Origin": "http://localhost:9999"},
                body,
                "/api/campaigns",
                403,
            ),
            (
                "missing-csrf",
                {
                    key: value
                    for key, value in valid.items()
                    if key != "X-CSRF-Token"
                },
                body,
                "/api/campaigns",
                403,
            ),
            (
                "bad-csrf",
                {**valid, "X-CSRF-Token": "wrong"},
                body,
                "/api/campaigns",
                403,
            ),
            (
                "bad-content-type",
                {**valid, "Content-Type": "text/plain"},
                body,
                "/api/campaigns",
                415,
            ),
            (
                "content-type-parameters",
                {**valid, "Content-Type": "application/json; charset=utf-8"},
                body,
                "/api/campaigns",
                415,
            ),
            (
                "extra-fields",
                valid,
                b'{"action":"CHECK_DATA","executable":"x","argv":[],"cwd":"/tmp","path":"x","prompt":"x","model":"x","env":{},"timeout":1}',
                "/api/campaigns",
                400,
            ),
            (
                "duplicate-action",
                valid,
                b'{"action":"CHECK_DATA","action":"CANCEL"}',
                "/api/campaigns",
                400,
            ),
            (
                "query-string",
                valid,
                body,
                "/api/campaigns?cwd=/tmp",
                400,
            ),
        )
        for label, headers, raw, path, expected in cases:
            status, _, _, payload = _request(
                server, path, method="POST", body=raw, headers=headers
            )
            assert status == expected, label
            assert payload["error"] in {
                "bad_host",
                "bad_origin",
                "bad_csrf",
                "unsupported_media_type",
                "invalid_action",
                "bad_request",
            }

        for path in ("/api/exec", "/api/shell"):
            status, _, _, _ = _request(server, path)
            assert status == 404
            status, _, _, _ = _request(
                server, path, method="POST", body=body, headers=valid
            )
            assert status == 405

        assert not marker.exists()
        assert list((runtime / "campaigns").iterdir()) == []


def test_t0_child_invocation_is_one_fixed_argv_and_never_a_shell(
    database: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}

    class AlreadyDone:
        pid = 987654

        @staticmethod
        def poll() -> int:
            return 0

    def fake_popen(argv: Sequence[str], **kwargs: Any) -> AlreadyDone:
        captured["argv"] = tuple(argv)
        captured["kwargs"] = kwargs
        kwargs["stdout"].write(b'{"status":"DATA_READY"}\n')
        kwargs["stdout"].flush()
        return AlreadyDone()

    monkeypatch.setattr(research_console.subprocess, "Popen", fake_popen)
    with _serve_console(
        monkeypatch, database, tmp_path, mode=None
    ) as (server, _, _runtime):
        pilot_root = tmp_path / "pilot"
        expected = research_console.build_check_data_argv(
            pilot_root.resolve(),
            server.research_console_controller.config.check_data_python,
        )
        status, _, _, created = _post(
            server, "/api/campaigns", {"action": "CHECK_DATA"}
        )
        assert status == 202
        terminal = _wait_terminal(server, created["campaign_id"])
        assert terminal["status"] == "SUCCEEDED"

    assert captured["argv"] == expected
    assert captured["kwargs"]["shell"] is False
    assert captured["kwargs"]["start_new_session"] is True
    assert captured["kwargs"]["close_fds"] is True
    assert captured["kwargs"]["cwd"] == str(research_console.PROJECT_ROOT)
    assert set(captured["kwargs"]["env"]) == {
        "LANG",
        "LC_ALL",
        "PATH",
        "PYTHONDONTWRITEBYTECODE",
        "PYTHONUNBUFFERED",
    }


def test_t0_duplicate_security_headers_have_zero_side_effect(
    database: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with _serve_console(monkeypatch, database, tmp_path) as (
        server,
        marker,
        runtime,
    ):
        body = b'{"action":"CHECK_DATA"}'
        expected_host = f"127.0.0.1:{server.server_port}"
        expected_origin = f"http://{expected_host}"
        token = server.research_console_csrf_token
        base = [
            ("Host", expected_host),
            ("Origin", expected_origin),
            ("X-CSRF-Token", token),
            ("Content-Type", "application/json"),
            ("Content-Length", str(len(body))),
        ]
        cases = (
            (base + [("Host", expected_host)], 400),
            (base + [("Origin", expected_origin)], 403),
            (base + [("X-CSRF-Token", token)], 403),
            (base + [("Content-Type", "application/json")], 415),
            (base + [("Content-Length", str(len(body)))], 400),
            (base + [("Transfer-Encoding", "chunked")], 400),
        )
        for headers, expected_status in cases:
            status, payload = _raw_post_with_headers(server, headers, body)
            assert status == expected_status
            assert "error" in payload

        assert not marker.exists()
        assert list((runtime / "campaigns").iterdir()) == []


def test_t0_rejects_non_origin_and_malformed_targets_without_side_effects(
    database: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with _serve_console(monkeypatch, database, tmp_path) as (
        server,
        marker,
        runtime,
    ):
        body = b'{"action":"CHECK_DATA"}'
        host = f"127.0.0.1:{server.server_port}"
        headers = (
            ("Host", host),
            ("Origin", f"http://{host}"),
            ("X-CSRF-Token", server.research_console_csrf_token),
            ("Content-Type", "application/json"),
            ("Content-Length", str(len(body))),
        )
        targets = (
            f"http://{host}/api/campaigns",
            "//attacker/api/campaigns",
            "/api/campaigns#fragment",
            "http://[::1/api/campaigns",
            "\x00/api/campaigns",
            "\x1f/api/campaigns",
        )
        for target in targets:
            status, response_headers, response_body = _raw_http(
                server, "POST", target, headers, body
            )
            assert status == 400, target
            assert json.loads(response_body)["error"] == "bad_target"
            _assert_security_headers(response_headers)

        assert not marker.exists()
        assert list((runtime / "campaigns").iterdir()) == []


def test_t0_methods_body_cap_head_and_security_headers_are_bounded(
    database: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with _serve_console(monkeypatch, database, tmp_path) as (
        server,
        marker,
        runtime,
    ):
        for method, path, expected, allow in (
            ("TRACE", "/console", 405, "GET, HEAD"),
            ("CONNECT", "/api/control/preflight", 405, "GET, HEAD"),
            ("BREW", "/api/campaigns", 405, "POST"),
            ("GET", "/api/campaigns", 405, "POST"),
            ("PUT", "/api/campaigns/example/actions", 405, "POST"),
        ):
            status, headers, _, payload = _request(server, path, method=method)
            assert status == expected
            assert headers["Allow"] == allow
            assert payload["error"] == "method_not_allowed"
            _assert_security_headers(headers)

        status, headers, _, payload = _request(
            server,
            "/console",
            method="TRACE",
            headers={"Host": "attacker.example"},
        )
        assert status == 400
        assert payload["error"] == "bad_host"
        _assert_security_headers(headers)

        oversized = b"x" * (research_console.MAX_REQUEST_BYTES + 1)
        status, headers, _, payload = _request(
            server,
            "/api/campaigns",
            method="POST",
            body=oversized,
            headers=_post_headers(server),
        )
        assert status == 413
        assert payload["error"] == "body_too_large"
        _assert_security_headers(headers)

        for path in ("/console", "/api/control/preflight", "/api/campaigns"):
            status, headers, body, _ = _request(server, path, method="HEAD")
            assert status == (405 if path == "/api/campaigns" else 200)
            assert body == b""
            assert int(headers["Content-Length"]) > 0
            _assert_security_headers(headers)

        assert not marker.exists()
        assert list((runtime / "campaigns").iterdir()) == []


def test_t0_atomic_writer_preserves_old_document_when_replace_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "status.json"
    research_console._atomic_write_json(target, {"status": "OLD"})
    before = target.read_bytes()

    def fail_replace(_source: Path, _target: Path) -> None:
        raise OSError("injected replace failure")

    monkeypatch.setattr(research_console.os, "replace", fail_replace)
    with pytest.raises(OSError, match="injected replace failure"):
        research_console._atomic_write_json(target, {"status": "NEW"})

    assert target.read_bytes() == before
    assert list(tmp_path.glob(".status.json.*.tmp")) == []


def test_t0_runtime_root_has_one_process_owner(
    database: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with _serve_console(monkeypatch, database, tmp_path) as (
        _server,
        _marker,
        runtime,
    ):
        with pytest.raises(
            research_console.ResearchConsoleError,
            match="already owned",
        ):
            research_console.create_research_console_server(
                database,
                runtime,
                tmp_path / "pilot",
                0,
                codex_binary=tmp_path / "missing-codex",
            )


def test_t0_post_spawn_receipt_failure_terminates_and_reaps_child(
    database: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spawned: list[subprocess.Popen[bytes]] = []
    original_popen = research_console.subprocess.Popen
    original_atomic = research_console._atomic_write_json
    failed_owner = False

    def capture_popen(*args: Any, **kwargs: Any) -> subprocess.Popen[bytes]:
        process = original_popen(*args, **kwargs)
        spawned.append(process)
        return process

    def fail_first_owner(path: Path, payload: Mapping[str, Any]) -> None:
        nonlocal failed_owner
        if path.name == "owner.json" and not failed_owner:
            failed_owner = True
            raise OSError("injected owner receipt failure")
        original_atomic(path, payload)

    monkeypatch.setattr(research_console.subprocess, "Popen", capture_popen)
    monkeypatch.setattr(research_console, "_atomic_write_json", fail_first_owner)
    with _serve_console(
        monkeypatch, database, tmp_path, mode="sleep"
    ) as (server, marker, _runtime):
        status, _, _, payload = _post(
            server, "/api/campaigns", {"action": "CHECK_DATA"}
        )
        assert status == 500
        assert payload["error"] == "start_receipt_failed"
        assert spawned and spawned[0].poll() is not None
        assert server.research_console_controller._active is None

        status, _, _, created = _post(
            server, "/api/campaigns", {"action": "CHECK_DATA"}
        )
        assert status == 202
        _wait_file(marker)
        _post(
            server,
            f"/api/campaigns/{created['campaign_id']}/actions",
            {"action": "CANCEL"},
        )
        assert _wait_terminal(server, created["campaign_id"])["status"] == "CANCELLED"


def test_t0_event_sequence_stays_monotonic_after_bounded_truncation(
    database: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with _serve_console(monkeypatch, database, tmp_path) as (
        server,
        _marker,
        runtime,
    ):
        campaign_id = str(uuid4())
        campaign = runtime / "campaigns" / campaign_id
        campaign.mkdir(mode=0o700)
        controller = server.research_console_controller
        for index in range(research_console.MAX_EVENTS + 2):
            controller._append_event(
                campaign, "TEST", "RUNNING", f"event {index}"
            )
        events = json.loads((campaign / "events.json").read_text())["events"]
        sequences = [event["sequence"] for event in events]
        assert len(sequences) == research_console.MAX_EVENTS
        assert sequences == list(range(3, research_console.MAX_EVENTS + 3))


def test_t0_campaigns_directory_identity_is_frozen(
    database: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with _serve_console(monkeypatch, database, tmp_path) as (
        server,
        marker,
        runtime,
    ):
        campaigns = runtime / "campaigns"
        campaigns.rename(runtime / "campaigns-original")
        campaigns.mkdir()

        status, _, _, preflight = _request(server, "/api/control/preflight")
        assert status == 200
        assert preflight["checks"]["runtime_root"]["status"] == "UNAVAILABLE"
        status, _, _, payload = _post(
            server, "/api/campaigns", {"action": "CHECK_DATA"}
        )
        assert status == 409
        assert payload["error"] == "frozen_path_changed"
        assert not marker.exists()
        assert list(campaigns.iterdir()) == []


def test_t0_missing_sqlite_is_unavailable_without_creating_it(
    tmp_path: Path,
) -> None:
    runtime = tmp_path / "runtime-missing-db"
    pilot = tmp_path / "pilot-missing-db"
    runtime.mkdir()
    pilot.mkdir()
    missing = tmp_path / "missing-parent" / "lab.sqlite"
    server = research_console.create_research_console_server(
        missing,
        runtime,
        pilot,
        0,
        codex_binary=tmp_path / "missing-codex",
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, _, _, preflight = _request(server, "/api/control/preflight")
        assert status == 200
        assert preflight["checks"]["sqlite"]["status"] == "UNAVAILABLE"
        status, _, _, _ = _request(server, "/")
        assert status == 500
        assert not missing.exists()
        assert not missing.parent.exists()
    finally:
        server.research_console_controller.shutdown()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_t1_console_preflight_and_strategy_library_share_one_loopback_server(
    database: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with _serve_console(monkeypatch, database, tmp_path) as (server, _, _runtime):
        monkeypatch.setattr(
            research_console,
            "probe_frequi",
            lambda _config: {
                "configured": True,
                "reachable": False,
                "available": False,
                "ui_installed": None,
                "webserver_mode": None,
                "version": None,
                "reason": "UNREACHABLE",
                "message": "loopback endpoint unavailable",
            },
        )
        for path in ("/console", "/", "/api/strategies"):
            status, headers, body, _ = _request(server, path)
            assert status == 200
            assert headers["Cache-Control"] == "no-store"
            assert body
        status, _, body, _ = _request(server, "/", method="HEAD")
        assert status == 200
        assert body == b""

        status, _, _, preflight = _request(server, "/api/control/preflight")
        assert status == 200
        assert preflight["overall_status"] == "NOT_READY"
        assert preflight["checks"]["sqlite"]["status"] == "READY"
        assert preflight["checks"]["runtime_root"]["status"] == "READY"
        assert preflight["checks"]["freqtrade"]["status"] == "UNAVAILABLE"
        serialized = json.dumps(preflight)
        assert str(database) not in serialized
        assert str(tmp_path) not in serialized


@pytest.mark.parametrize(
    ("mode", "expected_status", "expected_return_code"),
    (
        ("success", "SUCCEEDED", 0),
        ("fail", "FAILED", 7),
        ("invalid", "FAILED", 0),
    ),
)
def test_t1_real_fake_child_success_and_failure_are_truthful(
    database: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    expected_status: str,
    expected_return_code: int,
) -> None:
    with _serve_console(monkeypatch, database, tmp_path, mode=mode) as (
        server,
        marker,
        _runtime,
    ):
        status, _, _, created = _post(
            server, "/api/campaigns", {"action": "CHECK_DATA"}
        )
        assert status == 202
        terminal = _wait_terminal(server, created["campaign_id"])
        assert terminal["status"] == expected_status
        assert terminal["return_code"] == expected_return_code
        assert marker.is_file()

        status, _, _, events = _request(
            server, f"/api/campaigns/{created['campaign_id']}/events"
        )
        assert status == 200
        assert events["events"][-1]["status"] == expected_status
        public = json.dumps({"status": terminal, "events": events})
        assert "private-secret" not in public
        assert str(tmp_path) not in public
        assert "stdout" not in terminal
        assert "stderr" not in terminal


def test_t1_single_slot_returns_409_and_cancel_reaches_terminal(
    database: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with _serve_console(monkeypatch, database, tmp_path, mode="sleep") as (
        server,
        marker,
        _runtime,
    ):
        status, _, _, created = _post(
            server, "/api/campaigns", {"action": "CHECK_DATA"}
        )
        assert status == 202
        campaign_id = created["campaign_id"]
        _wait_file(marker)

        status, _, _, conflict = _post(
            server, "/api/campaigns", {"action": "CHECK_DATA"}
        )
        assert status == 409
        assert conflict["error"] == "active_campaign"

        status, _, _, cancelling = _post(
            server,
            f"/api/campaigns/{campaign_id}/actions",
            {"action": "CANCEL"},
        )
        assert status == 202
        assert cancelling["status"] in {"CANCEL_REQUESTED", "CANCELLED"}
        terminal = _wait_terminal(server, campaign_id)
        assert terminal["status"] == "CANCELLED"
        assert marker.is_file()


def test_t1_slow_cancel_receipt_cannot_overwrite_terminal_status(
    database: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entered = threading.Event()
    release = threading.Event()
    outcome: dict[str, Any] = {}
    with _serve_console(
        monkeypatch, database, tmp_path, mode="sleep"
    ) as (server, marker, _runtime):
        controller = server.research_console_controller
        original_record = controller._record_transition

        def block_cancel_receipt(
            campaign_dir: Path,
            status_value: str,
            message: str,
            event_type: str,
            **updates: Any,
        ) -> Optional[dict[str, Any]]:
            if status_value == "CANCEL_REQUESTED":
                entered.set()
                assert release.wait(timeout=3)
            return original_record(
                campaign_dir,
                status_value,
                message,
                event_type,
                **updates,
            )

        monkeypatch.setattr(controller, "_record_transition", block_cancel_receipt)
        status, _, _, created = _post(
            server, "/api/campaigns", {"action": "CHECK_DATA"}
        )
        assert status == 202
        _wait_file(marker)

        def cancel() -> None:
            try:
                outcome["status"] = controller.cancel_campaign(
                    created["campaign_id"]
                )
            except Exception as exc:  # pragma: no cover - asserted below
                outcome["error"] = exc

        cancel_thread = threading.Thread(target=cancel)
        cancel_thread.start()
        assert entered.wait(timeout=2)
        release.set()
        cancel_thread.join(timeout=2)
        assert "error" not in outcome
        assert outcome["status"]["status"] == "CANCEL_REQUESTED"
        terminal = _wait_terminal(server, created["campaign_id"])
        assert terminal["status"] == "CANCELLED"
        disk = json.loads(
            (
                controller.campaigns_root
                / created["campaign_id"]
                / "status.json"
            ).read_text()
        )
        assert disk["status"] == "CANCELLED"


def test_t1_fake_child_timeout_reaches_truthful_terminal(
    database: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with _serve_console(
        monkeypatch, database, tmp_path, mode="sleep", timeout=0.5
    ) as (server, marker, _runtime):
        status, _, _, created = _post(
            server, "/api/campaigns", {"action": "CHECK_DATA"}
        )
        assert status == 202
        terminal = _wait_terminal(server, created["campaign_id"])
        assert terminal["status"] == "TIMED_OUT"
        assert isinstance(terminal["return_code"], int)
        assert marker.is_file()


def test_t1_timeout_still_terminates_when_event_receipt_fails(
    database: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with _serve_console(
        monkeypatch, database, tmp_path, mode="sleep", timeout=0.6
    ) as (server, marker, runtime):
        controller = server.research_console_controller
        original_append = controller._append_event

        status, _, _, created = _post(
            server, "/api/campaigns", {"action": "CHECK_DATA"}
        )
        assert status == 202
        _wait_file(marker)

        def fail_timeout_event(
            campaign_dir: Path,
            event_type: str,
            status_value: str,
            message: str,
        ) -> None:
            if event_type == "TIMEOUT":
                raise OSError("injected timeout event failure")
            original_append(campaign_dir, event_type, status_value, message)

        monkeypatch.setattr(controller, "_append_event", fail_timeout_event)
        terminal = _wait_terminal(server, created["campaign_id"])
        assert terminal["status"] == "TIMED_OUT"
        deadline = time.monotonic() + 1
        while controller._active is not None and time.monotonic() < deadline:
            time.sleep(0.01)
        assert controller._active is None
        assert (runtime / "campaigns" / created["campaign_id"] / "status.json").is_file()


def test_t1_timeout_signal_precedes_blocked_receipt_and_cancel_cannot_override(
    database: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entered = threading.Event()
    release = threading.Event()
    with _serve_console(
        monkeypatch, database, tmp_path, mode="ignore_term", timeout=0.25
    ) as (server, marker, _runtime):
        controller = server.research_console_controller
        original_record = controller._record_transition

        def block_timeout_receipt(
            campaign_dir: Path,
            status_value: str,
            message: str,
            event_type: str,
            **updates: Any,
        ) -> Optional[dict[str, Any]]:
            if status_value == "TIMEOUT_TERMINATING":
                entered.set()
                assert release.wait(timeout=3)
            return original_record(
                campaign_dir,
                status_value,
                message,
                event_type,
                **updates,
            )

        monkeypatch.setattr(controller, "_record_transition", block_timeout_receipt)
        status, _, _, created = _post(
            server, "/api/campaigns", {"action": "CHECK_DATA"}
        )
        assert status == 202
        _wait_file(marker)
        assert entered.wait(timeout=2)
        _wait_file(Path(str(marker) + ".term"))

        status, _, _, conflict = _post(
            server,
            f"/api/campaigns/{created['campaign_id']}/actions",
            {"action": "CANCEL"},
        )
        assert status == 409
        assert conflict["error"] == "termination_in_progress"
        release.set()
        terminal = _wait_terminal(server, created["campaign_id"])
        assert terminal["status"] == "TIMED_OUT"


def test_t2_restart_marks_running_interrupted_and_preserves_six_table_database(
    database: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = _sqlite_snapshot(database)
    assert before["version"] == 1
    assert {
        row[1] for row in before["schema"] if row[0] == "table"
    } == set(BUSINESS_TABLES)

    runtime = tmp_path / "runtime"
    pilot = tmp_path / "pilot"
    campaigns = runtime / "campaigns"
    campaign_id = str(uuid4())
    campaign = campaigns / campaign_id
    campaign.mkdir(parents=True)
    pilot.mkdir()
    status_document = {
        "schema": research_console.STATUS_SCHEMA,
        "campaign_id": campaign_id,
        "action": "CHECK_DATA",
        "status": "RUNNING",
        "created_at_utc": "2026-09-03T00:00:00.000Z",
        "started_at_utc": "2026-09-03T00:00:01.000Z",
        "finished_at_utc": None,
        "return_code": None,
        "message": "running before restart",
    }
    (campaign / "status.json").write_text(
        json.dumps(status_document), encoding="utf-8"
    )

    script, marker = _write_fake_child(tmp_path)
    monkeypatch.setattr(
        research_console,
        "build_check_data_argv",
        lambda _pilot_root, _python: (
            sys.executable,
            str(script),
            "success",
            str(marker),
        ),
    )
    server = research_console.create_research_console_server(
        database,
        runtime,
        pilot,
        0,
        codex_binary=tmp_path / "missing-codex",
        task_timeout_seconds=1,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, _, _, recovered = _request(
            server, f"/api/campaigns/{campaign_id}"
        )
        assert status == 200
        assert recovered["status"] == "INTERRUPTED_NEEDS_CONFIRMATION"
        assert recovered["return_code"] is None

        status, _, _, events = _request(
            server, f"/api/campaigns/{campaign_id}/events"
        )
        assert status == 200
        assert events["events"][-1]["type"] == "INTERRUPTED"
        assert events["events"][-1]["status"] == (
            "INTERRUPTED_NEEDS_CONFIRMATION"
        )
        status, _, _, preflight = _request(server, "/api/control/preflight")
        assert status == 200
        assert preflight["checks"]["runtime_root"][
            "restart_confirmation_required"
        ] is True
        status, _, _, conflict = _post(
            server, "/api/campaigns", {"action": "CHECK_DATA"}
        )
        assert status == 409
        assert conflict["error"] == "restart_confirmation_required"
        assert not marker.exists()
    finally:
        server.research_console_controller.shutdown()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert _sqlite_snapshot(database) == before


def test_t2_legacy_interrupted_receipt_without_confirmation_field_stays_latched(
    database: Path, tmp_path: Path
) -> None:
    runtime = tmp_path / "runtime-legacy-interrupted"
    pilot = tmp_path / "pilot-legacy-interrupted"
    campaign_id = str(uuid4())
    campaign = runtime / "campaigns" / campaign_id
    campaign.mkdir(parents=True)
    pilot.mkdir()
    (campaign / "status.json").write_text(
        json.dumps(
            {
                "schema": research_console.STATUS_SCHEMA,
                "campaign_id": campaign_id,
                "action": "CHECK_DATA",
                "status": "INTERRUPTED_NEEDS_CONFIRMATION",
                "created_at_utc": "2026-09-03T00:00:00.000Z",
                "started_at_utc": "2026-09-03T00:00:01.000Z",
                "finished_at_utc": "2026-09-03T00:00:02.000Z",
                "return_code": None,
                "message": "legacy interruption receipt",
            }
        ),
        encoding="utf-8",
    )
    server = research_console.create_research_console_server(
        database,
        runtime,
        pilot,
        0,
        codex_binary=tmp_path / "missing-codex",
    )
    try:
        controller = server.research_console_controller
        assert controller._restart_confirmation_required is True
        with pytest.raises(
            research_console.ControlRequestError,
            match="未闭合任务",
        ):
            controller.create_campaign()
    finally:
        server.research_console_controller.shutdown()
        server.server_close()


def test_t2_shutdown_keeps_runtime_lock_until_terminal_monitor_finishes(
    database: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entered = threading.Event()
    release = threading.Event()
    with _serve_console(monkeypatch, database, tmp_path, mode="success") as (
        server,
        _marker,
        runtime,
    ):
        controller = server.research_console_controller
        original_record = controller._record_transition

        def block_terminal_receipt(
            campaign_dir: Path,
            status_value: str,
            message: str,
            event_type: str,
            **updates: Any,
        ) -> Optional[dict[str, Any]]:
            if status_value == "SUCCEEDED":
                entered.set()
                assert release.wait(timeout=8)
            return original_record(
                campaign_dir,
                status_value,
                message,
                event_type,
                **updates,
            )

        monkeypatch.setattr(controller, "_record_transition", block_terminal_receipt)
        status, _, _, _created = _post(
            server, "/api/campaigns", {"action": "CHECK_DATA"}
        )
        assert status == 202
        assert entered.wait(timeout=2)
        job = controller._active
        assert job is not None and job.monitor is not None

        with pytest.raises(
            research_console.ResearchConsoleError,
            match="monitor did not finalize",
        ):
            controller.shutdown()
        with pytest.raises(
            research_console.ResearchConsoleError,
            match="already owned",
        ):
            research_console.create_research_console_server(
                database,
                runtime,
                tmp_path / "pilot",
                0,
                codex_binary=tmp_path / "missing-codex",
            )

        release.set()
        job.monitor.join(timeout=2)
        controller.shutdown()

    replacement = research_console.create_research_console_server(
        database,
        runtime,
        tmp_path / "pilot",
        0,
        codex_binary=tmp_path / "missing-codex",
    )
    try:
        assert replacement.research_console_controller._closed is False
    finally:
        replacement.research_console_controller.shutdown()
        replacement.server_close()


def test_t2_terminal_receipt_failure_clears_owner_and_restart_fails_closed(
    database: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = tmp_path / "runtime-terminal-failure"
    pilot = tmp_path / "pilot-terminal-failure"
    runtime.mkdir()
    pilot.mkdir()
    script, marker = _write_fake_child(tmp_path)
    monkeypatch.setattr(
        research_console,
        "build_check_data_argv",
        lambda _pilot_root, _python: (
            sys.executable,
            str(script),
            "success",
            str(marker),
        ),
    )
    server = research_console.create_research_console_server(
        database,
        runtime,
        pilot,
        0,
        codex_binary=tmp_path / "missing-codex",
    )
    controller = server.research_console_controller
    original_write_status = controller._write_status

    def fail_succeeded_status(
        campaign_dir: Path,
        status_value: str,
        message: str,
        **updates: Any,
    ) -> dict[str, Any]:
        if status_value == "SUCCEEDED":
            raise OSError("injected terminal status failure")
        return original_write_status(
            campaign_dir, status_value, message, **updates
        )

    monkeypatch.setattr(controller, "_write_status", fail_succeeded_status)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, _, _, created = _post(
            server, "/api/campaigns", {"action": "CHECK_DATA"}
        )
        assert status == 202
        deadline = time.monotonic() + 5
        while controller._active is not None and time.monotonic() < deadline:
            time.sleep(0.02)
        assert controller._active is None
        disk_status = json.loads(
            (
                runtime
                / "campaigns"
                / created["campaign_id"]
                / "status.json"
            ).read_text()
        )
        assert disk_status["status"] == "RUNNING"
        status, _, _, unavailable = _request(
            server, f"/api/campaigns/{created['campaign_id']}"
        )
        assert status == 409
        assert unavailable["error"] == "campaign_state_unavailable"
        status, _, _, preflight = _request(server, "/api/control/preflight")
        assert status == 200
        assert preflight["checks"]["runtime_root"][
            "restart_confirmation_required"
        ] is True
        status, _, _, blocked = _post(
            server, "/api/campaigns", {"action": "CHECK_DATA"}
        )
        assert status == 409
        assert blocked["error"] == "restart_confirmation_required"
    finally:
        controller.shutdown()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    restarted = research_console.create_research_console_server(
        database,
        runtime,
        pilot,
        0,
        codex_binary=tmp_path / "missing-codex",
    )
    try:
        assert restarted.research_console_controller._restart_confirmation_required
        with pytest.raises(
            research_console.ControlRequestError,
            match="未闭合任务",
        ):
            restarted.research_console_controller.create_campaign()
    finally:
        restarted.research_console_controller.shutdown()
        restarted.server_close()


def test_t2_shutdown_reaps_child_and_unlocks_when_all_receipt_writes_fail(
    database: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_atomic = research_console._atomic_write_json
    runtime: Optional[Path] = None
    with _serve_console(
        monkeypatch, database, tmp_path, mode="sleep"
    ) as (server, marker, selected_runtime):
        runtime = selected_runtime
        status, _, _, created = _post(
            server, "/api/campaigns", {"action": "CHECK_DATA"}
        )
        assert status == 202
        _wait_file(marker)
        controller = server.research_console_controller
        job = controller._active
        assert job is not None

        def fail_all_receipts(
            _path: Path, _payload: Mapping[str, Any]
        ) -> None:
            raise OSError("injected persistent receipt failure")

        monkeypatch.setattr(
            research_console, "_atomic_write_json", fail_all_receipts
        )
        controller.shutdown()
        assert job.process.poll() is not None
        assert controller._active is None
        assert controller._closed is True
        monkeypatch.setattr(
            research_console, "_atomic_write_json", original_atomic
        )

        disk = json.loads(
            (
                selected_runtime
                / "campaigns"
                / created["campaign_id"]
                / "status.json"
            ).read_text()
        )
        assert disk["status"] == "RUNNING"

    assert runtime is not None
    restarted = research_console.create_research_console_server(
        database,
        runtime,
        tmp_path / "pilot",
        0,
        codex_binary=tmp_path / "missing-codex",
    )
    try:
        assert restarted.research_console_controller._restart_confirmation_required
    finally:
        restarted.research_console_controller.shutdown()
        restarted.server_close()


def test_t2_cross_process_cli_restart_does_not_resume_or_signal_old_child(
    database: Path, tmp_path: Path
) -> None:
    before = _sqlite_snapshot(database)
    runtime = tmp_path / "runtime-cli"
    pilot = tmp_path / "pilot-cli"
    runtime.mkdir()
    pilot.mkdir()
    fake_python = tmp_path / "fake-python"
    fake_python.write_text(
        """#!/usr/bin/env python3
import json
import os
import sys
import time
from pathlib import Path

marker = Path(sys.argv[-1]) / "cli-fake-invocations.jsonl"
with marker.open("a", encoding="utf-8") as stream:
    stream.write(json.dumps({"pid": os.getpid(), "argv": sys.argv[1:]}) + "\\n")
    stream.flush()
time.sleep(2.0)
print(json.dumps({"status": "DATA_READY"}), flush=True)
""",
        encoding="utf-8",
    )
    fake_python.chmod(0o700)
    missing_codex = tmp_path / "missing-codex"
    marker = pilot / "cli-fake-invocations.jsonl"
    first: Optional[subprocess.Popen[str]] = None
    second: Optional[subprocess.Popen[str]] = None
    child_pid: Optional[int] = None
    try:
        first, first_port = _start_console_cli(
            database, runtime, pilot, fake_python, missing_codex
        )
        status, page, _ = _external_request(first_port, "/console")
        assert status == 200
        match = re.search(rb'<meta name="csrf-token" content="([^"]+)">', page)
        assert match is not None
        token = match.group(1).decode("ascii")
        body = b'{"action":"CHECK_DATA"}'
        status, raw, _ = _external_request(
            first_port,
            "/api/campaigns",
            method="POST",
            body=body,
            headers={
                "Origin": f"http://127.0.0.1:{first_port}",
                "X-CSRF-Token": token,
                "Content-Type": "application/json",
            },
        )
        assert status == 202
        campaign_id = json.loads(raw)["campaign_id"]
        _wait_file(marker)
        invocation = json.loads(marker.read_text(encoding="utf-8").splitlines()[0])
        assert invocation["argv"] == [
            str(research_console.PILOT_SCRIPT),
            "check-data",
            "--pilot-root",
            str(pilot.resolve()),
        ]
        child_pid = int(invocation["pid"])

        first.kill()
        first.wait(timeout=5)

        second, second_port = _start_console_cli(
            database, runtime, pilot, fake_python, missing_codex
        )
        status, raw, _ = _external_request(
            second_port, f"/api/campaigns/{campaign_id}"
        )
        assert status == 200
        recovered = json.loads(raw)
        assert recovered["status"] == "INTERRUPTED_NEEDS_CONFIRMATION"
        assert len(marker.read_text(encoding="utf-8").splitlines()) == 1
        os.kill(child_pid, 0)
        status, page, _ = _external_request(second_port, "/console")
        assert status == 200
        match = re.search(rb'<meta name="csrf-token" content="([^"]+)">', page)
        assert match is not None
        second_token = match.group(1).decode("ascii")
        status, raw, _ = _external_request(
            second_port,
            "/api/campaigns",
            method="POST",
            body=body,
            headers={
                "Origin": f"http://127.0.0.1:{second_port}",
                "X-CSRF-Token": second_token,
                "Content-Type": "application/json",
            },
        )
        assert status == 409
        assert json.loads(raw)["error"] == "restart_confirmation_required"
        assert len(marker.read_text(encoding="utf-8").splitlines()) == 1
        assert (runtime / "campaigns" / campaign_id / "status.json").is_file()
        assert (runtime / "campaigns" / campaign_id / "events.json").is_file()
    finally:
        for process in (first, second):
            if process is not None and process.poll() is None:
                process.send_signal(signal.SIGINT)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
        if child_pid is not None:
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                try:
                    os.kill(child_pid, 0)
                except ProcessLookupError:
                    break
                time.sleep(0.05)
            else:
                os.kill(child_pid, signal.SIGKILL)

    assert _sqlite_snapshot(database) == before
    assert not any(path.is_relative_to(research_console.PROJECT_ROOT) for path in runtime.rglob("*"))


def test_t2_cli_sigint_reaps_active_child_and_releases_runtime_lock(
    database: Path, tmp_path: Path
) -> None:
    runtime = tmp_path / "runtime-sigint"
    pilot = tmp_path / "pilot-sigint"
    runtime.mkdir()
    pilot.mkdir()
    fake_python = tmp_path / "fake-python-sigint"
    fake_python.write_text(
        """#!/usr/bin/env python3
import json
import os
import sys
import time
from pathlib import Path

Path(sys.argv[-1], "sigint-marker.json").write_text(
    json.dumps({"pid": os.getpid(), "argv": sys.argv[1:]}),
    encoding="utf-8",
)
time.sleep(30)
""",
        encoding="utf-8",
    )
    fake_python.chmod(0o700)
    missing_codex = tmp_path / "missing-codex-sigint"
    first: Optional[subprocess.Popen[str]] = None
    second: Optional[subprocess.Popen[str]] = None
    try:
        first, port = _start_console_cli(
            database, runtime, pilot, fake_python, missing_codex
        )
        status, page, _ = _external_request(port, "/console")
        assert status == 200
        match = re.search(rb'<meta name="csrf-token" content="([^"]+)">', page)
        assert match is not None
        token = match.group(1).decode("ascii")
        body = b'{"action":"CHECK_DATA"}'
        status, raw, _ = _external_request(
            port,
            "/api/campaigns",
            method="POST",
            body=body,
            headers={
                "Origin": f"http://127.0.0.1:{port}",
                "X-CSRF-Token": token,
                "Content-Type": "application/json",
            },
        )
        assert status == 202
        campaign_id = json.loads(raw)["campaign_id"]
        _wait_file(pilot / "sigint-marker.json")

        first.send_signal(signal.SIGINT)
        assert first.wait(timeout=5) == 0
        terminal = json.loads(
            (runtime / "campaigns" / campaign_id / "status.json").read_text()
        )
        assert terminal["status"] == "INTERRUPTED_NEEDS_CONFIRMATION"
        assert terminal["return_code"] == -signal.SIGTERM
        assert terminal["requires_confirmation"] is False

        second, second_port = _start_console_cli(
            database, runtime, pilot, fake_python, missing_codex
        )
        status, raw, _ = _external_request(
            second_port, "/api/control/preflight"
        )
        assert status == 200
        assert json.loads(raw)["checks"]["runtime_root"]["status"] == "READY"
    finally:
        for process in (first, second):
            if process is not None and process.poll() is None:
                process.send_signal(signal.SIGINT)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
