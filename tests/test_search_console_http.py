"""Narrow T1/T2 HTTP/process tests for the Issue #32 Search Console."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Mapping, Optional
from uuid import uuid4

import pytest

from lab import codex_generation, research_console, search_campaign
from lab.database import get_connection
from scripts import run_bounded_research_pilot as pilot
from tests.test_bounded_research_pilot import _search_root
from tests.test_codex_generation_http import _request, _wait_generation
from tests.test_development_run import BOUNDED_SOURCE, _approved_candidate_database
from tests.test_research_console import _wait_file, _wait_process_group_gone


NOW = "2026-09-01T00:00:00.000Z"
TABLES = (
    "research_profiles",
    "generation_runs",
    "candidates",
    "research_runs",
    "backtest_executions",
    "releases",
)
SNAPSHOT = r"""
import hashlib, json, sqlite3, sys
tables = ("research_profiles", "generation_runs", "candidates",
          "research_runs", "backtest_executions", "releases")
db = sqlite3.connect("file:" + sys.argv[1] + "?mode=ro", uri=True)
try:
    names = [r[0] for r in db.execute(
        "SELECT name FROM sqlite_schema WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    if names != sorted(tables): raise SystemExit("not exact six-table schema")
    out = {"user_version": db.execute("PRAGMA user_version").fetchone()[0], "tables": {}}
    for table in tables:
        columns = [r[1] for r in db.execute("PRAGMA table_info(" + table + ")")]
        rows = db.execute("SELECT * FROM " + table + " ORDER BY id").fetchall()
        body = json.dumps({"columns": columns, "rows": rows},
                          sort_keys=True, separators=(",", ":")).encode()
        out["tables"][table] = {"count": len(rows),
                                "sha256": hashlib.sha256(body).hexdigest()}
    print(json.dumps(out, sort_keys=True, separators=(",", ":")))
finally: db.close()
"""

# T1 process fake: no Search ledger, ranking, receipt, or terminal implementation.
PROCESS = r"""
import sys, time
from pathlib import Path
from scripts import run_bounded_research_pilot as pilot
root, control, mode = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
plan = pilot.load_plan(root, pilot.SEARCH_CAMPAIGN)
(control / ("started-" + str(plan["round"]))).write_text("started")
if mode == "fail": raise SystemExit(7)
while True: time.sleep(0.05)
"""

# T2 calls production screen_search. Only its physical Freqtrade artifact edge is
# replaced; the production function owns ledger, receipts, ranking and Gate.
REAL_SCREEN = r"""
import sys, time
from pathlib import Path
from scripts import run_bounded_research_pilot as pilot
root, source, control, mode = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4]
plan = pilot.load_plan(root, pilot.SEARCH_CAMPAIGN)
(control / ("started-" + str(plan["round"]))).write_text("started")
release = control / ("release-" + str(plan["round"]))
while not release.exists(): time.sleep(0.01)
pilot.materialize_screening_isolation = lambda *_a, **_k: {
    "receipt": {}, "provenance": Path("unused"), "data_dir": Path("unused")}
pilot.materialize_inputs = lambda campaign_root, current, **_k: {
    item["candidate_id"]: campaign_root for item in current["candidates"]}
def outer_screen(campaign_root, current, *_a, **_k):
    (campaign_root / ("search-results-round-" + str(current["round"]))).mkdir()
    if mode == "no-parent":
        return [{"candidate_id": item["candidate_id"], "class_name": item["class_name"],
                 "strategy_sha256": item["strategy_sha256"], "technical_status": "FAILED",
                 "failure_reason": "bounded outer screen failure"}
                for item in current["candidates"]]
    return [{"candidate_id": item["candidate_id"], "class_name": item["class_name"],
             "strategy_sha256": item["strategy_sha256"], "technical_status": "VALID",
             "failure_reason": None, "total_trades": 40,
             "profit_pct": (1.25 if mode != "no-finalist" else -0.25)
                           if current["round"] == 2 else -0.1 - index,
             "max_drawdown_pct": 2.0 + index, "profit_factor": 1.2}
            for index, item in enumerate(current["candidates"])]
pilot.screen = outer_screen
out = pilot.screen_search(root, plan, Path(sys.executable), source)
raise SystemExit(0 if out["status"] in {
    "SEARCH_ROUND_READY_FOR_CHILDREN", "SEARCH_FINALIST_FROZEN"} else 3)
"""

@dataclass
class Env:
    database: Path
    seeds: tuple[str, ...]
    child: Optional[str]
    root: Path
    runtime: Path
    pilot_root: Path
    source: Path
    control: Path
    codex: Path
    damaged: dict[str, bool]


def _add_candidate(
    database: Path,
    profile_id: str,
    class_name: str,
    family: str,
    *,
    parent: Optional[str] = None,
) -> str:
    generation_id = str(uuid4())
    source = BOUNDED_SOURCE.replace("BoundedCandidate", class_name)
    request = codex_generation.validate_generation_request(
        {
            "profile_id": profile_id,
            "parent_candidate_id": parent,
            "idea": f"Bounded fixture for {class_name}.",
            "strategy_family": family,
            "expected_failure_mode": "Sideways markets may whipsaw.",
        }
    )
    prepared = codex_generation.start_generation(
        database, generation_id, request, model="fixed-test", started_at=NOW
    )
    raw = json.dumps(
        {"display_name": class_name, "class_name": class_name, "code_text": source},
        separators=(",", ":"),
    ).encode()
    candidate_id = codex_generation.complete_generation(
        database,
        prepared,
        codex_generation.parse_candidate_output(raw, timeframe="5m"),
        raw_output=raw,
        jsonl_summary={"event_count": 4, "tool_event_count": 0},
        finished_at=NOW,
    )
    codex_generation.review_generation(database, generation_id, "APPROVED", decided_at=NOW)
    return candidate_id


def _database(tmp_path: Path, seeds: int, child: bool) -> tuple[Path, tuple[str, ...], Optional[str]]:
    database, first = _approved_candidate_database(tmp_path)
    with get_connection(database, read_only=True) as connection:
        profile_id = str(
            connection.execute(
                "SELECT research_profile_id FROM generation_runs WHERE id="
                "(SELECT generation_run_id FROM candidates WHERE id=?)",
                (first,),
            ).fetchone()[0]
        )
    seed_ids = [first]
    for class_name, family in (("MomentumSeed", "momentum"), ("ChannelSeed", "channel"))[
        : seeds - 1
    ]:
        seed_ids.append(_add_candidate(database, profile_id, class_name, family))
    child_id = (
        _add_candidate(database, profile_id, "PreparedSearchChild", "trend", parent=first)
        if child
        else None
    )
    return database, tuple(seed_ids), child_id


def _fake_codex(tmp_path: Path) -> Path:
    binary = tmp_path / "fake-codex-search"
    child_source = BOUNDED_SOURCE.replace("BoundedCandidate", "GeneratedSearchChild")
    binary.write_text(
        f'''#!{sys.executable}
import json, sys
from pathlib import Path
args = sys.argv[1:]
if args == ["--version"]: print("codex-cli test"); raise SystemExit(0)
if args == ["exec", "--help"]:
    print("--cd --config --disable --ephemeral --ignore-user-config --ignore-rules --json --output-schema --output-last-message --sandbox --skip-git-repo-check --color")
    raise SystemExit(0)
if args[-2:] == ["features", "list"]:
    [print(args[i + 1] + " stable false") for i, x in enumerate(args[:-2]) if x == "--disable"]
    raise SystemExit(0)
sys.stdin.buffer.read()
Path(args[args.index("--output-last-message") + 1]).write_text(json.dumps({{
    "display_name":"Generated Search Child", "class_name":"GeneratedSearchChild",
    "code_text":{child_source!r}}}, separators=(",", ":")))
for value in ({{"type":"thread.started","thread_id":"t"}}, {{"type":"turn.started"}},
              {{"type":"item.completed","item":{{"type":"agent_message","text":"done"}}}},
              {{"type":"turn.completed","usage":{{"input_tokens":1,"output_tokens":1}}}}):
    print(json.dumps(value), flush=True)
''',
        encoding="utf-8",
    )
    binary.chmod(0o700)
    return binary


def _env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    *,
    seeds: int = 1,
    child: bool = False,
) -> Env:
    database, seed_ids, child_id = _database(tmp_path, seeds, child)
    root, source = _search_root(tmp_path)
    root.chmod(0o700)
    runtime, pilot_root, control = (tmp_path / name for name in ("runtime", "pilot", "control"))
    for path in (runtime, pilot_root, control):
        path.mkdir()
    python = Path(sys.executable).resolve()
    python_info, source_info = python.stat(), source.stat()
    provenance = (root / pilot.ACQUISITION / "retained-data-provenance.json").read_bytes()
    damaged = {"value": False}

    def acquisition(_root: Path) -> dict[str, Any]:
        if damaged["value"]:
            raise search_campaign.SearchCampaignError("BLOCKED_DATA", "Search input changed", status=503)
        return {
            "search_timerange": "20260101-20260131",
            "data_provenance_sha256": pilot.digest(provenance),
            "pair": "ADA/USDT:USDT",
            "timeframe": "5m",
            "base_fee": 0.0005,
            "acquisition_receipts": (),
        }

    monkeypatch.setattr(search_campaign, "_acquisition_snapshot", acquisition)
    monkeypatch.setattr(
        search_campaign,
        "_freqtrade_snapshot",
        lambda *_args: {
            "freqtrade_python": python,
            "freqtrade_source": source,
            "python_identity": (
                python_info.st_dev, python_info.st_ino, python_info.st_size, python_info.st_mtime_ns
            ),
            "source_identity": (source_info.st_dev, source_info.st_ino),
        },
    )
    if mode in {"sleep", "fail"}:
        monkeypatch.setattr(
            search_campaign,
            "_argv",
            lambda _cap: (str(python), "-c", PROCESS, str(root), str(control), mode),
        )
    elif mode in {"real", "no-parent", "no-finalist"}:
        monkeypatch.setattr(
            search_campaign,
            "_argv",
            lambda _cap: (
                str(python), "-c", REAL_SCREEN, str(root), str(source), str(control), mode
            ),
        )
    return Env(
        database, seed_ids, child_id, root, runtime, pilot_root, source, control,
        _fake_codex(tmp_path), damaged
    )


def _start(environment: Env) -> tuple[Any, threading.Thread]:
    server = research_console.create_research_console_server(
        environment.database,
        environment.runtime,
        environment.pilot_root,
        0,
        search_root=environment.root,
        codex_binary=environment.codex,
        freqtrade_python=Path(sys.executable),
        freqtrade_source=environment.source,
        task_timeout_seconds=5,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def _stop(server: Any, thread: threading.Thread) -> None:
    server.research_console_controller.shutdown()
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)
    assert not thread.is_alive()


@contextmanager
def _serve(environment: Env) -> Iterator[Any]:
    server, thread = _start(environment)
    try:
        yield server
    finally:
        _stop(server, thread)


def _post(server: Any, path: str, payload: Mapping[str, Any]) -> tuple[int, dict[str, Any], bytes]:
    return _request(server, path, method="POST", payload=payload)


def _wait_search(server: Any, campaign_id: str, expected: str) -> tuple[dict[str, Any], bytes]:
    deadline, last = time.monotonic() + 8, None
    while time.monotonic() < deadline:
        status, value, raw = _request(server, f"/api/search-campaigns/{campaign_id}")
        last = (status, value)
        if (
            status == 200
            and value.get("status") == expected
            and server.research_console_controller._active is None
        ):
            return value, raw
        time.sleep(0.02)
    pytest.fail(f"Search did not reach {expected}: {last!r}")


def _snapshot(database: Path) -> dict[str, Any]:
    completed = subprocess.run(
        [sys.executable, "-I", "-c", SNAPSHOT, str(database)],
        capture_output=True, text=True, timeout=10, check=False,
    )
    assert completed.returncode == 0, completed.stderr
    value = json.loads(completed.stdout)
    assert value["user_version"] == 1 and set(value["tables"]) == set(TABLES)
    return value


def _path_free(raw: bytes, tmp_path: Path) -> None:
    assert str(tmp_path).encode() not in raw
    assert all(token not in raw for token in (b'"argv"', b'"stderr"', b'"stdout"'))


def _patch_outer_screen(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        pilot,
        "materialize_screening_isolation",
        lambda *_a, **_k: {"receipt": {}, "provenance": Path("unused"), "data_dir": Path("unused")},
    )
    monkeypatch.setattr(
        pilot,
        "materialize_inputs",
        lambda root, plan, **_k: {item["candidate_id"]: root for item in plan["candidates"]},
    )
    monkeypatch.setattr(
        pilot,
        "screen",
        lambda _root, plan, *_a, **_k: [
            {"candidate_id": item["candidate_id"], "class_name": item["class_name"],
             "strategy_sha256": item["strategy_sha256"], "technical_status": "VALID",
             "failure_reason": None, "total_trades": 40, "profit_pct": -0.25,
             "max_drawdown_pct": 2.0, "profit_factor": 0.8}
            for item in plan["candidates"]
        ],
    )


def _ready_round_one(environment: Env, monkeypatch: pytest.MonkeyPatch) -> str:
    _patch_outer_screen(monkeypatch)
    capability = search_campaign.freeze_search_capability(
        environment.root, Path(sys.executable), environment.source
    )
    assert capability.status == "READY"
    try:
        prepared = search_campaign.prepare_round_one(
            environment.database, capability, environment.seeds
        )
        result = pilot.screen_search(
            environment.root,
            pilot.load_plan(environment.root, pilot.SEARCH_CAMPAIGN),
            Path(sys.executable),
            environment.source,
        )
        assert result["status"] == "SEARCH_ROUND_READY_FOR_CHILDREN"
        search_campaign.complete_search_round(capability, prepared.campaign_id, 0)
        return prepared.campaign_id
    finally:
        capability.close()


def test_t1_initial_context_strict_request_single_slot_and_cancel_group(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    environment = _env(tmp_path, monkeypatch, "sleep")
    before = _snapshot(environment.database)
    with _serve(environment) as server:
        status, context, raw = _request(server, "/api/search/context")
        assert status == 200
        assert context["state"]["status"] == "SEARCH_READY"
        assert context["codex_parent_lock"] is None
        _path_free(raw, tmp_path)
        for body in (
            {"candidate_ids": []},
            {"candidate_ids": ["a", "b", "c", "d"]},
            {"candidate_ids": [environment.seeds[0]] * 2},
            {"candidate_ids": [environment.seeds[0]], "path": "/tmp/x"},
        ):
            status, error, _ = _post(server, "/api/search-campaigns", body)
            assert status == 400 and error["error"] == "invalid_search_request"
        status, created, raw = _post(
            server, "/api/search-campaigns", {"candidate_ids": list(environment.seeds)}
        )
        assert status == 202
        campaign_id = str(created["campaign_id"])
        _path_free(raw, tmp_path)
        _wait_file(environment.control / "started-1")
        active = server.research_console_controller._active
        assert active is not None
        pgid = active.process_group_id
        status, conflict, _ = _post(
            server, "/api/search-campaigns", {"candidate_ids": list(environment.seeds)}
        )
        assert status == 409 and conflict["error"] == "active_campaign"
        assert _post(
            server, f"/api/search-campaigns/{campaign_id}/actions", {"action": "CANCEL"}
        )[0] == 202
        state, raw = _wait_search(server, campaign_id, "CANCELLED")
        assert state["current_round"] == 1
        _path_free(raw, tmp_path)
        _wait_process_group_gone(pgid)
    assert _snapshot(environment.database) == before


def test_t1_exit_three_is_a_legal_http_terminal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    environment = _env(tmp_path, monkeypatch, "no-parent")
    before = _snapshot(environment.database)
    with _serve(environment) as server:
        status, created, _ = _post(
            server, "/api/search-campaigns", {"candidate_ids": list(environment.seeds)}
        )
        assert status == 202
        _wait_file(environment.control / "started-1")
        (environment.control / "release-1").write_text("release")
        state, raw = _wait_search(server, str(created["campaign_id"]), "SEARCH_TERMINATED_NO_PARENT")
        assert state["budget"]["consumed_total"] == 1 and state["search_finalist"] is None
        _path_free(raw, tmp_path)
    assert _snapshot(environment.database) == before


@pytest.mark.parametrize(
    ("case", "expected"),
    (("cancel", "CANCELLED"), ("fail", "FAILED"), ("restart", "INTERRUPTED")),
)
def test_t1_round_two_runtime_terminal_wins_over_round_one_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str, expected: str
) -> None:
    environment = _env(
        tmp_path, monkeypatch, "fail" if case == "fail" else "sleep", child=True
    )
    assert environment.child is not None
    campaign_id = _ready_round_one(environment, monkeypatch)
    before = _snapshot(environment.database)
    server, thread = _start(environment)
    replacement: Optional[tuple[Any, threading.Thread]] = None
    try:
        assert _post(
            server,
            f"/api/search-campaigns/{campaign_id}/actions",
            {"action": "START_ROUND_2", "candidates": [
                {"candidate_id": environment.child, "changed_factor": "stoploss"}]},
        )[0] == 202
        _wait_file(environment.control / "started-2")
        active = server.research_console_controller._active
        assert active is not None
        pgid, target = active.process_group_id, server
        if case == "cancel":
            assert _post(
                server, f"/api/search-campaigns/{campaign_id}/actions", {"action": "CANCEL"}
            )[0] == 202
        elif case == "restart":
            _stop(server, thread)
            server = thread = None
            _wait_process_group_gone(pgid)
            replacement = _start(environment)
            target = replacement[0]
        state, raw = _wait_search(target, campaign_id, expected)
        assert state["current_round"] == 2
        assert state["selected_parent"]["candidate_id"] == environment.seeds[0]
        _path_free(raw, tmp_path)
        if case == "cancel":
            _wait_process_group_gone(pgid)
    finally:
        if server is not None:
            _stop(server, thread)
        if replacement is not None:
            _stop(*replacement)
    assert _snapshot(environment.database) == before


def test_t1_search_blocked_and_corrupt_search_are_local_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    environment = _env(tmp_path, monkeypatch, "production-failure")
    before = _snapshot(environment.database)
    with _serve(environment) as server:
        status, created, _ = _post(
            server, "/api/search-campaigns", {"candidate_ids": list(environment.seeds)}
        )
        assert status == 202
        state, raw = _wait_search(server, str(created["campaign_id"]), "FAILED")
        assert state["current_round"] == 1
        _path_free(raw, tmp_path)
        private = json.loads((environment.root / pilot.SEARCH_TERMINAL).read_bytes())
        assert private["status"] == "SEARCH_BLOCKED"

        with (environment.root / pilot.SEARCH_TRIALS).open("ab") as ledger:
            ledger.write(b'{"partial":')
        environment.damaged["value"] = True
        status, context, raw = _request(server, "/api/search/context")
        assert status == 200
        assert context["capability"]["status"] == "BLOCKED_DATA"
        assert context["state"]["status"] == "BLOCKED_DATA"
        _path_free(raw, tmp_path)
        assert _request(server, "/api/generation/context")[0] == 200
        assert _request(server, "/api/research/context")[0] == 200
        status, error, _ = _post(
            server, "/api/search-campaigns", {"candidate_ids": list(environment.seeds)}
        )
        assert status in {409, 503}
        assert error["error"] in {"campaign_consumed", "BLOCKED_DATA"}
    assert _snapshot(environment.database) == before


def test_t1_unavailable_search_receipt_cannot_fall_back_to_engine_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    environment = _env(tmp_path, monkeypatch, "sleep")
    campaign_id = _ready_round_one(environment, monkeypatch)
    with _serve(environment) as server:
        server.research_console_controller._state_unavailable.add(campaign_id)

        for path in (
            "/api/search/context",
            f"/api/search-campaigns/{campaign_id}",
        ):
            status, error, raw = _request(server, path)
            assert status == 409
            assert error["error"] == "search_state_unavailable"
            _path_free(raw, tmp_path)
        assert _request(server, "/api/generation/context")[0] == 200
        assert _request(server, "/api/research/context")[0] == 200


def test_t1_round_two_exit_three_is_a_legal_no_finalist_terminal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    environment = _env(tmp_path, monkeypatch, "no-finalist", child=True)
    assert environment.child is not None
    campaign_id = _ready_round_one(environment, monkeypatch)
    before = _snapshot(environment.database)
    with _serve(environment) as server:
        status, running, _ = _post(
            server,
            f"/api/search-campaigns/{campaign_id}/actions",
            {"action": "START_ROUND_2", "candidates": [
                {"candidate_id": environment.child, "changed_factor": "stoploss"}
            ]},
        )
        assert status == 202 and running["status"] == "RUNNING"
        _wait_file(environment.control / "started-2")
        (environment.control / "release-2").write_text("release")
        final, raw = _wait_search(
            server, campaign_id, "SEARCH_TERMINATED_NO_FINALIST"
        )
        assert final["search_finalist"] is None
        assert final["budget"]["consumed_total"] == 2
        _path_free(raw, tmp_path)
    assert _snapshot(environment.database) == before


@pytest.mark.parametrize(
    "changed_factor", ("holdout", "stress", "development-period", "validation")
)
def test_t1_reserved_changed_factor_fails_before_any_round_two_root_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    changed_factor: str,
) -> None:
    environment = _env(tmp_path, monkeypatch, "sleep", child=True)
    assert environment.child is not None
    campaign_id = _ready_round_one(environment, monkeypatch)
    before_database = _snapshot(environment.database)
    root_before = {
        path.relative_to(environment.root).as_posix(): path.read_bytes()
        for path in environment.root.rglob("*")
        if path.is_file()
    }

    with _serve(environment) as server:
        status, error, _ = _post(
            server,
            f"/api/search-campaigns/{campaign_id}/actions",
            {"action": "START_ROUND_2", "candidates": [
                {"candidate_id": environment.child, "changed_factor": changed_factor}
            ]},
        )
        assert status == 400 and error["error"] == "invalid_search_request"

    assert {
        path.relative_to(environment.root).as_posix(): path.read_bytes()
        for path in environment.root.rglob("*")
        if path.is_file()
    } == root_before
    assert _snapshot(environment.database) == before_database


def test_t2_database_change_after_engine_terminal_forces_failed_public_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    environment = _env(tmp_path, monkeypatch, "real", child=True)
    assert environment.child is not None
    campaign_id = _ready_round_one(environment, monkeypatch)
    authoritative_digest = search_campaign.business_table_digest
    changed = False

    def change_database_before_terminal_audit(database: Path) -> str:
        nonlocal changed
        if not changed:
            with get_connection(database) as connection:
                connection.execute(
                    "UPDATE candidates SET display_name=display_name || ' [T2 changed]' WHERE id=?",
                    (environment.child,),
                )
            changed = True
        return authoritative_digest(database)

    monkeypatch.setattr(
        research_console, "business_table_digest", change_database_before_terminal_audit
    )
    with _serve(environment) as server:
        status, running, _ = _post(
            server,
            f"/api/search-campaigns/{campaign_id}/actions",
            {"action": "START_ROUND_2", "candidates": [
                {"candidate_id": environment.child, "changed_factor": "stoploss"}
            ]},
        )
        assert status == 202 and running["status"] == "RUNNING"
        _wait_file(environment.control / "started-2")
        (environment.control / "release-2").write_text("release")
        failed, raw = _wait_search(server, campaign_id, "FAILED")

        engine_terminal = json.loads(
            (environment.root / pilot.SEARCH_TERMINAL).read_bytes()
        )
        console_status = json.loads(
            (environment.root / search_campaign.STATUS_FILE).read_bytes()
        )
        assert changed is True
        assert engine_terminal["status"] == "SEARCH_FINALIST_FROZEN"
        assert failed["status"] == "FAILED" and failed["search_finalist"] is None
        assert console_status["error_code"] == "SEARCH_DATABASE_CHANGED"
        _path_free(raw, tmp_path)

        status, context, raw = _request(server, "/api/search/context")
        assert status == 200
        assert context["state"]["status"] == "FAILED"
        assert context["state"]["search_finalist"] is None
        _path_free(raw, tmp_path)


def test_t2_real_screen_search_two_round_http_and_cross_process_zero_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    environment = _env(tmp_path, monkeypatch, "real", seeds=3)
    with _serve(environment) as server:
        status, context, _ = _request(server, "/api/search/context")
        assert status == 200 and len(context["candidates"]) == 3
        before_r1 = _snapshot(environment.database)
        status, created, _ = _post(
            server, "/api/search-campaigns", {"candidate_ids": list(environment.seeds)}
        )
        assert status == 202
        campaign_id = str(created["campaign_id"])
        _wait_file(environment.control / "started-1")
        assert _snapshot(environment.database) == before_r1
        (environment.control / "release-1").write_text("release")
        r1, raw = _wait_search(server, campaign_id, "SEARCH_ROUND_READY_FOR_CHILDREN")
        assert r1["selected_parent"]["candidate_id"] == environment.seeds[0]
        assert len(r1["frozen_ranking"]) == 3
        _path_free(raw, tmp_path)
        assert _snapshot(environment.database) == before_r1

        _, context, _ = _request(server, "/api/search/context")
        lock = context["codex_parent_lock"]
        status, generated, _ = _post(
            server,
            "/api/generations",
            {"profile_id": lock["profile_id"], "parent_candidate_id": lock["parent_candidate_id"],
             "idea": "Change only stoploss.", "strategy_family": lock["strategy_family"],
             "expected_failure_mode": "Tighter exits may overtrade."},
        )
        assert status == 202
        generation_id = str(generated["id"])
        completed = _wait_generation(server, generation_id)[1]
        child_id = str(completed["candidate"]["id"])
        status, reviewed, _ = _post(
            server, f"/api/generations/{generation_id}/actions", {"action": "APPROVE"}
        )
        assert status == 200 and reviewed["candidate"]["review_status"] == "APPROVED"

        before_r2 = _snapshot(environment.database)
        assert before_r2["tables"]["research_profiles"] == before_r1["tables"]["research_profiles"]
        for table in ("generation_runs", "candidates"):
            assert before_r2["tables"][table]["count"] == before_r1["tables"][table]["count"] + 1
            assert before_r2["tables"][table]["sha256"] != before_r1["tables"][table]["sha256"]
        for table in ("research_runs", "backtest_executions", "releases"):
            assert before_r2["tables"][table] == before_r1["tables"][table]
            assert before_r2["tables"][table]["count"] == 0
        status, error, _ = _post(
            server, f"/api/search-campaigns/{campaign_id}/actions",
            {"action": "START_ROUND_2", "candidates": [
                {"candidate_id": child_id, "changed_factor": "../unsafe"}]},
        )
        assert status == 400 and error["error"] == "invalid_search_request"
        status, running, raw = _post(
            server, f"/api/search-campaigns/{campaign_id}/actions",
            {"action": "START_ROUND_2", "candidates": [
                {"candidate_id": child_id, "changed_factor": "stoploss"}]},
        )
        assert status == 202 and running["status"] == "RUNNING"
        _path_free(raw, tmp_path)
        _wait_file(environment.control / "started-2")
        assert _snapshot(environment.database) == before_r2
        (environment.control / "release-2").write_text("release")
        final, raw = _wait_search(server, campaign_id, "SEARCH_FINALIST_FROZEN")
        assert final["search_finalist"]["candidate_id"] == child_id
        assert final["budget"]["consumed_total"] == 4
        assert final["boundaries"]["research_runs_created_by_search"] == 0
        _path_free(raw, tmp_path)
        assert _snapshot(environment.database) == before_r2

        records = [json.loads(line) for line in
                   (environment.root / pilot.SEARCH_TRIALS).read_text().splitlines()]
        assert sum(r["record_type"] == "ROUND_RECEIPT" for r in records) == 2
        terminal = json.loads((environment.root / pilot.SEARCH_TERMINAL).read_bytes())
        assert terminal["status"] == "SEARCH_FINALIST_FROZEN"
        assert terminal["finalist_gate"] == pilot.SEARCH_GATE_CONTRACT
