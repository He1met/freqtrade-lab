"""Narrow T1/T2 HTTP/process tests for the Issue #32 Search Console."""

from __future__ import annotations

import hashlib
import http.client
import json
import subprocess
import sys
import threading
import time
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Mapping, Optional
from uuid import uuid4

import pytest

from lab import (
    backtest_artifact,
    codex_generation,
    development_run,
    research_candidate,
    research_console,
    search_campaign,
)
from lab.database import get_connection
from lab import bounded_research as pilot
from tests.test_bounded_research_pilot import _search_root
from tests.test_codex_generation_http import _request, _wait_generation
from tests.test_development_run import (
    BOUNDED_SOURCE,
    _approved_candidate_database,
    _frozen_capability_fixture,
)
from tests.test_holdout_atomic import _NativeFakeFreqtrade, _input_receipts
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
from lab import bounded_research as pilot
root, control, mode = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
plan = pilot.load_plan(root, pilot.SEARCH_CAMPAIGN)
(control / ("started-" + str(plan["round"]))).write_text("started")
if mode == "fail": raise SystemExit(7)
while True: time.sleep(0.05)
"""

# T2 calls production screen_search. Only its physical Freqtrade artifact edge is
# replaced; the production function owns ledger, receipts, ranking and Gate.
REAL_SCREEN = r"""
import json, sys, time, zipfile
from pathlib import Path
from lab import bounded_research as pilot
root, source, control, mode = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4]
plan = pilot.load_plan(root, pilot.SEARCH_CAMPAIGN)
(control / ("started-" + str(plan["round"]))).write_text("started")
release = control / ("release-" + str(plan["round"]))
while not release.exists(): time.sleep(0.01)
pilot.verify_data = lambda *_a, **_k: {"status": "DATA_READY"}
def outer_isolation(campaign_root, current):
    isolation = campaign_root / (
        "search-isolation-round-" + str(current["round"])
    )
    data_dir = isolation / "data" / "okx"
    data_dir.mkdir(parents=True)
    return {"data_dir": data_dir}
pilot.materialize_screening_isolation = outer_isolation
pilot.materialize_inputs = lambda campaign_root, current, **_k: {
    item["candidate_id"]: campaign_root for item in current["candidates"]}
def outer_screen(campaign_root, current, *_a, **_k):
    result_root = campaign_root / (
        "search-results-round-" + str(current["round"])
    )
    result_root.mkdir()
    if mode == "no-parent":
        return [{"candidate_id": item["candidate_id"], "class_name": item["class_name"],
                 "strategy_sha256": item["strategy_sha256"], "technical_status": "FAILED",
                 "failure_reason": "bounded outer screen failure"}
                for item in current["candidates"]]
    results = []
    for index, item in enumerate(current["candidates"]):
        if mode == "real" and current["round"] == 1 and index == 1:
            results.append({
                "candidate_id": item["candidate_id"],
                "class_name": item["class_name"],
                "strategy_sha256": item["strategy_sha256"],
                "technical_status": "FAILED",
                "failure_reason": "bounded mixed-attempt fixture failure",
            })
            continue
        profit = ((1.25 if mode != "no-finalist" else -0.25)
                  if current["round"] == 2 else -0.1 - index)
        result = {
            "candidate_id": item["candidate_id"],
            "class_name": item["class_name"],
            "strategy_sha256": item["strategy_sha256"],
            "technical_status": "VALID", "failure_reason": None,
            "total_trades": 40, "profit_pct": profit,
            "max_drawdown_pct": 2.0 + index, "profit_factor": 1.2,
            "gross_profit_before_fees_pct": profit + 0.1,
            "configured_fee_cost_pct": 0.1,
            "average_holding_period_minutes": 60.0,
            "direction_concentration": 1.0,
            "market_state_concentration": 1.0,
            "market_state_definition": pilot.MARKET_STATE_DEFINITION,
            "market_state_lookback_candles": current["pre_roll_candles"],
        }
        run_root = result_root / item["candidate_id"]
        raw_root = run_root / "raw"
        raw_root.mkdir(parents=True)
        archive_name = "backtest-result.zip"
        report = {"strategy": {item["class_name"]: {
            "total_trades": 40, "profit_total": profit / 100}}}
        with zipfile.ZipFile(raw_root / archive_name, "w") as archive:
            archive.writestr(
                "backtest-result.json",
                json.dumps(report, separators=(",", ":")),
            )
        result.update(
            archive=archive_name,
            archive_sha256=pilot.digest(
                (raw_root / archive_name).read_bytes()
            ),
            report_semantic_sha256=pilot.digest(
                pilot.canonical(report["strategy"][item["class_name"]])
            ),
        )
        (run_root / "result.json").write_bytes(pilot.canonical(result))
        results.append(result)
    return results
pilot.screen = outer_screen
out = pilot.screen_search(root, plan, Path(sys.executable), source)
if mode == "database-change" and plan["round"] == 2:
    (control / "terminal-written-2").write_text("terminal-written")
    while not (control / "allow-exit-2").exists(): time.sleep(0.01)
raise SystemExit(0 if out["status"] in {
    "SEARCH_ROUND_READY_FOR_CHILDREN", "SEARCH_FINALIST_FROZEN"} else 3)
"""

@dataclass
class Env:
    database: Path
    profile_id: str
    seeds: tuple[str, ...]
    child: Optional[str]
    root: Path
    runtime: Path
    pilot_root: Path
    source: Path
    control: Path
    codex: Path
    damaged: dict[str, bool]


def _request_document(
    server: Any, path: str
) -> tuple[int, Mapping[str, str], bytes]:
    connection = http.client.HTTPConnection(
        "127.0.0.1", server.server_port, timeout=5
    )
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        connection.close()


def _add_candidate(
    database: Path,
    profile_id: str,
    class_name: str,
    family: str,
    *,
    parent: Optional[str] = None,
    stoploss: Optional[str] = None,
    timeframe: str = "5m",
) -> str:
    generation_id = str(uuid4())
    source = BOUNDED_SOURCE.replace("BoundedCandidate", class_name)
    source = source.replace('timeframe = "5m"', f'timeframe = "{timeframe}"')
    if stoploss is not None:
        source = source.replace("stoploss = -0.02", f"stoploss = {stoploss}")
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
        codex_generation.parse_candidate_output(raw, timeframe=timeframe),
        raw_output=raw,
        jsonl_summary={"event_count": 4, "tool_event_count": 0},
        finished_at=NOW,
    )
    codex_generation.review_generation(database, generation_id, "APPROVED", decided_at=NOW)
    return candidate_id


def _database(
    tmp_path: Path, seeds: int, child: bool, timeframe: str = "5m"
) -> tuple[Path, str, tuple[str, ...], Optional[str]]:
    database, first = _approved_candidate_database(tmp_path, timeframe=timeframe)
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
        seed_ids.append(_add_candidate(database, profile_id, class_name, family, timeframe=timeframe))
    child_id = (
        _add_candidate(
            database,
            profile_id,
            "PreparedSearchChild",
            "trend",
            parent=first,
            stoploss="-0.03",
            timeframe=timeframe,
        )
        if child
        else None
    )
    return database, profile_id, tuple(seed_ids), child_id


def _fake_codex(tmp_path: Path, timeframe: str = "5m") -> Path:
    binary = tmp_path / "fake-codex-search"
    child_source = BOUNDED_SOURCE.replace(
        "BoundedCandidate", "GeneratedSearchChild"
    ).replace('timeframe = "5m"', f'timeframe = "{timeframe}"').replace(
        "stoploss = -0.02", "stoploss = -0.03"
    )
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
    timeframe: str = "5m",
    economic_gate: Optional[Mapping[str, Any]] = None,
) -> Env:
    database, profile_id, seed_ids, child_id = _database(tmp_path, seeds, child, timeframe)
    with get_connection(database, read_only=True) as connection:
        connection.execute("BEGIN")
        profile = search_campaign.load_approved_candidate_snapshot(
            connection, seed_ids[0]
        ).profile
    root, source = _search_root(tmp_path)
    root.chmod(0o700)
    runtime, pilot_root, control = (tmp_path / name for name in ("runtime", "pilot", "control"))
    for path in (runtime, pilot_root, control):
        path.mkdir()
    python = Path(sys.executable).resolve()
    python_info, source_info = python.stat(), source.stat()
    provenance = (root / pilot.ACQUISITION / "retained-data-provenance.json").read_bytes()
    damaged = {"value": False}
    search_timerange, development_timerange = (
        ("20260201-20260313", "20260313-20260512")
        if timeframe == "1d"
        else ("20260102-20260201", "20260201-20260303")
    )

    def acquisition(_root: Path, _database: Path) -> dict[str, Any]:
        if damaged["value"]:
            raise search_campaign.SearchCampaignError("BLOCKED_DATA", "Search input changed", status=503)
        result = {
            "search_timerange": search_timerange,
            "data_provenance_sha256": pilot.digest(provenance),
            "source_acquisition_sha256": "b" * 64,
            "pair": profile["pairs"][0],
            "timeframe": profile["timeframe"],
            "base_fee": profile["taker_fee_rate"],
            "profile_snapshot": profile,
            "profile_snapshot_sha256": pilot.digest(pilot.canonical(profile)),
            "development_timerange": development_timerange,
            "pre_roll_candles": 20,
        }
        if economic_gate is not None:
            result["economic_gate"] = dict(economic_gate)
        return result

    monkeypatch.setattr(search_campaign, "_acquisition_snapshot", acquisition)
    monkeypatch.setattr(
        pilot, "verify_data", lambda *_args, **_kwargs: {"status": "DATA_READY"}
    )
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
    if mode in {"sleep", "fail", "production-failure"}:
        process_mode = "fail" if mode == "production-failure" else mode
        monkeypatch.setattr(
            search_campaign,
            "_argv",
            lambda _cap: (
                str(python),
                "-c",
                PROCESS,
                str(root),
                str(control),
                process_mode,
            ),
        )
    elif mode in {"real", "no-parent", "no-finalist", "database-change"}:
        monkeypatch.setattr(
            search_campaign,
            "_argv",
            lambda _cap: (
                str(python), "-c", REAL_SCREEN, str(root), str(source), str(control), mode
            ),
        )
    return Env(
        database, profile_id, seed_ids, child_id, root, runtime, pilot_root, source, control,
        _fake_codex(tmp_path, timeframe), damaged
    )


def _start(
    environment: Env, *, configure_search: bool = True
) -> tuple[Any, threading.Thread]:
    server = research_console.create_research_console_server(
        environment.database,
        environment.runtime,
        environment.pilot_root,
        0,
        search_root=environment.root if configure_search else None,
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
def _serve(
    environment: Env, *, configure_search: bool = True
) -> Iterator[Any]:
    server, thread = _start(environment, configure_search=configure_search)
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


def _assert_only_terminal_projection(
    database: Path,
    before: Mapping[str, Any],
    campaign_id: str,
    *,
    status: str,
) -> dict[str, Any]:
    after = _snapshot(database)
    for table in TABLES:
        if table != "generation_runs":
            assert after["tables"][table] == before["tables"][table]
    assert after["tables"]["generation_runs"]["count"] == (
        before["tables"]["generation_runs"]["count"] + 1
    )
    with get_connection(database, read_only=True) as connection:
        rows = connection.execute(
            "SELECT * FROM generation_runs WHERE id=?", (campaign_id,)
        ).fetchall()
    assert len(rows) == 1
    assert rows[0]["source"] == "MANUAL"
    assert rows[0]["status"] == status
    return after


def _path_free(raw: bytes, tmp_path: Path) -> None:
    assert str(tmp_path).encode() not in raw
    assert all(token not in raw for token in (b'"argv"', b'"stderr"', b'"stdout"'))


def _patch_outer_screen(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        pilot, "verify_data", lambda *_a, **_k: {"status": "DATA_READY"}
    )
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
    def screen(root: Path, plan: Mapping[str, Any], *_args: Any, **_kwargs: Any):
        result_root = root / f"search-results-round-{plan['round']}"
        result_root.mkdir()
        results = []
        for item in plan["candidates"]:
            result = {
                "candidate_id": item["candidate_id"],
                "class_name": item["class_name"],
                "strategy_sha256": item["strategy_sha256"],
                "technical_status": "VALID",
                "failure_reason": None,
                "total_trades": 40,
                "profit_pct": -0.25,
                "max_drawdown_pct": 2.0,
                "profit_factor": 0.8,
                "gross_profit_before_fees_pct": -0.15,
                "configured_fee_cost_pct": 0.1,
                "average_holding_period_minutes": 60.0,
                "direction_concentration": 1.0,
                "market_state_concentration": 1.0,
                "market_state_definition": pilot.MARKET_STATE_DEFINITION,
                "market_state_lookback_candles": plan["pre_roll_candles"],
            }
            run_root = result_root / item["candidate_id"]
            raw_root = run_root / "raw"
            raw_root.mkdir(parents=True)
            archive_name = "backtest-result.zip"
            report = {
                "strategy": {
                    item["class_name"]: {
                        "total_trades": 40,
                        "profit_total": -0.0025,
                    }
                }
            }
            with zipfile.ZipFile(raw_root / archive_name, "w") as archive:
                archive.writestr(
                    "backtest-result.json",
                    json.dumps(report, separators=(",", ":")),
                )
            result.update(
                archive=archive_name,
                archive_sha256=pilot.digest(
                    (raw_root / archive_name).read_bytes()
                ),
                report_semantic_sha256=pilot.digest(
                    pilot.canonical(report["strategy"][item["class_name"]])
                ),
            )
            (run_root / "result.json").write_bytes(pilot.canonical(result))
            results.append(result)
        return results

    monkeypatch.setattr(pilot, "screen", screen)


def _native_1d_development_artifact(
    run_dir: Path,
    strategy: str,
    timerange: str,
    fee: float,
) -> tuple[research_candidate.ProducedArtifact, str]:
    input_root = run_dir / "development-input"
    evidence = run_dir / "development-evidence"
    raw = run_dir / "native-1d-raw"
    user_data = run_dir / "native-1d-user-data"
    raw.mkdir(exist_ok=True)
    user_data.mkdir(exist_ok=True)
    evidence.mkdir(exist_ok=True)
    config_source = input_root / "config.json"
    strategy_file = input_root / "strategies" / f"{strategy}.py"
    provenance_path = input_root / "retained-data-provenance.json"
    runtime_config = run_dir / "native-1d-config.json"
    runtime_config.write_bytes(
        research_candidate._canonical_bytes(
            research_candidate._runtime_config(
                json.loads(config_source.read_text()),
                config_source=config_source,
                data_dir=input_root / "data" / "okx",
                user_data_dir=user_data,
                strategy_path=strategy_file.parent,
                strategy=strategy,
                timerange=timerange,
                fee=fee,
                export_dir=raw,
            )
        )
    )
    runner_bytes = research_candidate.DEFAULT_RUNNER.read_bytes()
    runner_sha = hashlib.sha256(runner_bytes).hexdigest()
    provenance_bytes = provenance_path.read_bytes()
    provenance_sha = hashlib.sha256(provenance_bytes).hexdigest()
    command = [
        "TEST_ONLY_NATIVE_1D_FREQTRADE",
        "--scenario", "DEVELOPMENT",
        "--timerange", timerange,
        "--strategy", strategy,
        "--strategy-sha256", hashlib.sha256(strategy_file.read_bytes()).hexdigest(),
        "--fee", str(fee),
        "--config", str(runtime_config),
        "--strategy-file", str(strategy_file),
        "--export-dir", str(raw),
        "--data-provenance", str(provenance_path),
        "--source-tree-sha256", "0" * 64,
        "--runner-sha256", runner_sha,
    ]
    completed = _NativeFakeFreqtrade()(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=research_candidate.SCENARIO_TIMEOUT_SECONDS,
    )
    summary = json.loads(completed.stdout)
    producer_bytes = Path(research_candidate.__file__).read_bytes()
    produced = research_candidate._sanitize_raw_artifact(
        scenario="DEVELOPMENT",
        slug="development-01",
        raw_dir=raw,
        runner_summary=summary,
        completed=completed,
        command_shape=("TEST_ONLY_NATIVE_1D_FREQTRADE", "DEVELOPMENT"),
        bundle_dir=evidence,
        strategy=strategy,
        strategy_source=strategy_file.read_bytes(),
        data_provenance=json.loads(provenance_bytes),
        data_provenance_sha256=provenance_sha,
        expected_input_receipts=_input_receipts(json.loads(provenance_bytes)),
        source_tree_sha256="0" * 64,
        implementation_receipts={
            "producer": {
                "bytes": len(producer_bytes),
                "sha256": hashlib.sha256(producer_bytes).hexdigest(),
            },
            "runner": {"bytes": len(runner_bytes), "sha256": runner_sha},
        },
        timerange=timerange,
        network_policy="test-native 1d outer boundary; no economic evidence",
        allow_zero_trades=True,
    )
    parsed = backtest_artifact.parse_backtest_artifact(
        evidence,
        produced.archive,
        strategy,
        "2026.7",
        produced.provenance_sha256,
        allow_zero_trades=True,
    )
    assert parsed.timeframe == "1d"
    return produced, provenance_sha


def test_t1_explicit_search_root_seals_later_phase_page_and_http_actions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    environment = _env(tmp_path, monkeypatch, "sleep")
    research_run_id = "sealed-search-research-run"
    development_projection = {
        "research_run_id": research_run_id,
        "candidate_id": "candidate-1",
        "research_profile_id": "profile-1",
        "status": "COMPLETED",
        "stage": "COMPLETED",
        "verdict": "REJECTED",
        "rejection_reasons": ["MINIMUM_PROFIT_FACTOR_NOT_MET"],
        "checks": {
            "candidate_binding": "PASSED",
            "security_gate": "PASSED",
            "development_data": "PHYSICALLY_ISOLATED",
            "development_gate": "REJECTED",
            "next_phase": "NONE_REJECTED",
            "holdout": "SEALED_UNREAD",
            "holdout_stress": "SEALED_UNREAD",
        },
        "development": {
            "status": "SUCCEEDED",
            "profit_pct": -0.25,
            "net_profit_after_base_fees_pct": -0.25,
            "average_holding_period_minutes": 1440.0,
            "roi_exit_count": 0,
        },
        "gate_results": [
            {
                "criterion": "minimum_profit_pct",
                "threshold": 0.5,
                "actual": 1.0,
                "passed": True,
            }
        ],
        "executions": [
            {"scenario": "DEVELOPMENT", "status": "SUCCEEDED", "profit_pct": -0.25},
        ],
    }

    def forbidden(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("sealed later-phase implementation was reached")

    campaign_id = str(uuid4())
    campaign_dir = environment.runtime / "campaigns" / campaign_id
    campaign_dir.mkdir(parents=True, mode=0o700)
    (campaign_dir / "status.json").write_bytes(
        pilot.canonical(
            {
                "schema": research_console.STATUS_SCHEMA,
                "campaign_id": campaign_id,
                "action": "DEVELOPMENT",
                "status": "SUCCEEDED",
                "created_at_utc": NOW,
                "started_at_utc": NOW,
                "finished_at_utc": NOW,
                "return_code": 0,
                "message": "Development completed",
            }
        )
    )
    (campaign_dir / "holdout-status.json").write_bytes(
        pilot.canonical(
            {
                "schema": research_console.STATUS_SCHEMA,
                "campaign_id": campaign_id,
                "action": "HOLDOUT_CONTINUATION",
                "status": "SUCCEEDED",
                "created_at_utc": NOW,
                "started_at_utc": NOW,
                "finished_at_utc": NOW,
                "return_code": 0,
                "message": "/private/HOLDOUT_STATUS_SENTINEL",
            }
        )
    )
    (campaign_dir / "events.json").write_bytes(
        pilot.canonical(
            {
                "schema": research_console.EVENTS_SCHEMA,
                "campaign_id": campaign_id,
                "events": [
                    {
                        "sequence": 1,
                        "at_utc": NOW,
                        "type": "COMPLETED",
                        "status": "SUCCEEDED",
                        "message": "/private/HOLDOUT_EVENT_SENTINEL",
                    }
                ],
            }
        )
    )
    monkeypatch.setattr(research_console, "freeze_holdout_capability", forbidden)
    monkeypatch.setattr(research_console, "load_public_holdout_run", forbidden)
    monkeypatch.setattr(
        research_console.ResearchConsoleController,
        "_reconcile_holdout_at",
        forbidden,
    )
    monkeypatch.setattr(research_console, "copy_frequi_results", forbidden)
    monkeypatch.setattr(
        research_console,
        "load_public_development_run",
        lambda *_args, **_kwargs: dict(development_projection),
    )
    monkeypatch.setattr(research_console, "inspect_manual_review", forbidden)
    monkeypatch.setattr(
        research_console, "prepare_holdout_continuation", forbidden
    )
    monkeypatch.setattr(research_console, "reject_research_run", forbidden)
    monkeypatch.setattr(
        research_console, "pass_and_create_release", forbidden
    )

    with _serve(environment) as server:
        sealed_reason = research_console.EXPLICIT_SEARCH_SEALED_REASON
        before_database = _snapshot(environment.database)
        releases = environment.runtime / "releases"
        before_release_files = tuple(
            sorted(
                path.relative_to(releases).as_posix()
                for path in releases.rglob("*")
                if path.is_file()
            )
        )

        page_status, page_headers, page_raw = _request_document(server, "/console")
        assert page_status == 200
        assert page_headers["Content-Type"].startswith("text/html")
        page = page_raw.decode("utf-8")
        assert '<script src="/console.js" defer></script>' in page
        assert 'id="research-holdout" class="danger" disabled' in page
        assert 'id="manual-reject" class="danger" disabled' in page
        assert 'id="manual-pass" disabled' in page
        assert "/private/" not in page

        script_status, script_headers, script_raw = _request_document(
            server, "/console.js"
        )
        assert script_status == 200
        assert script_headers["Content-Type"].startswith("text/javascript")
        script = script_raw.decode("utf-8")
        assert "function renderResearch(value)" in script
        for metric in (
            "net_profit_after_base_fees_pct",
            "average_holding_period_minutes",
            "roi_exit_count",
        ):
            assert metric in script
        assert "/private/" not in script

        status, context, _ = _request(server, "/api/research/context")
        assert status == 200
        sealed_capability = {
            "status": "SEALED_UNREAD",
            "reason": sealed_reason,
            "pipeline_version": development_run.DEVELOPMENT_PIPELINE_VERSION,
            "action": None,
            "holdout": "SEALED_UNREAD",
            "holdout_stress": "SEALED_UNREAD",
            "holdout_timerange": None,
            "stress_fee_multiplier": None,
            "one_shot": True,
        }
        assert context["holdout_capability"] == sealed_capability
        assert set(context["boundaries"].values()) == {"SEALED_UNREAD"}

        status, preflight, raw = _request(server, "/api/control/preflight")
        assert status == 200
        assert preflight["checks"]["holdout_continuation"] == {
            **sealed_capability,
            "message": sealed_reason,
        }
        assert preflight["latest_campaign"]["action"] == "DEVELOPMENT"
        assert b"HOLDOUT_STATUS_SENTINEL" not in raw
        assert b"HOLDOUT_EVENT_SENTINEL" not in raw

        status, detail, _ = _request(
            server, f"/api/research-runs/{research_run_id}"
        )
        assert status == 200
        assert detail["authorization"] == {
            "status": "SEALED_UNREAD",
            "can_authorize": False,
            "reason": "Explicit Search mode keeps Holdout and Holdout Stress sealed",
        }
        assert detail["status"] == detail["stage"] == "COMPLETED"
        assert detail["verdict"] == "REJECTED"
        assert detail["rejection_reasons"] == ["MINIMUM_PROFIT_FACTOR_NOT_MET"]
        assert detail["development"] == {
            "status": "SUCCEEDED",
            "profit_pct": -0.25,
            "net_profit_after_base_fees_pct": -0.25,
            "average_holding_period_minutes": 1440.0,
            "roi_exit_count": 0,
            "execution_rows": 1,
        }
        assert [item["scenario"] for item in detail["executions"]] == ["DEVELOPMENT"]
        assert detail["holdout"] == {"status": "SEALED_UNREAD", "execution_rows": 0}
        assert detail["holdout_stress"] == {
            "status": "SEALED_UNREAD", "execution_rows": 0
        }
        assert detail["gate_results"] == development_projection["gate_results"]
        assert not {"release_count", "strategy_detail_url", "manual_review"} & set(detail)
        serialized = json.dumps(detail, sort_keys=True)
        assert "/private/" not in serialized
        assert set(detail["boundaries"].values()) == {"SEALED_UNREAD"}
        for path in ("/", "/api/strategies", "/strategy", "/api/strategy", "/download"):
            status, error, raw = _request(server, path)
            assert status == 404 and error["error"] == "SEALED_UNREAD"
            assert b"/private/" not in raw

        monkeypatch.setattr(
            server.research_console_controller,
            "_load_events",
            forbidden,
        )
        status, safe_status, raw = _request(
            server, f"/api/campaigns/{campaign_id}"
        )
        assert status == 200 and safe_status["action"] == "DEVELOPMENT"
        assert b"HOLDOUT_STATUS_SENTINEL" not in raw
        assert b"HOLDOUT_EVENT_SENTINEL" not in raw
        status, error, raw = _request(
            server, f"/api/campaigns/{campaign_id}/events"
        )
        assert status == 404 and error["error"] == "SEALED_UNREAD"
        assert b"HOLDOUT_STATUS_SENTINEL" not in raw
        assert b"HOLDOUT_EVENT_SENTINEL" not in raw

        status, preflight, raw = _request(server, "/api/control/preflight")
        assert status == 200
        assert preflight["latest_campaign"]["action"] == "DEVELOPMENT"
        assert b"HOLDOUT_STATUS_SENTINEL" not in raw

        for action in (
            {"action": "AUTHORIZE_HOLDOUT"},
            {"action": "REJECT", "reason": "sealed"},
            {"action": "PASS_AND_CREATE_RELEASE", "reason": "sealed"},
        ):
            status, error, _ = _post(
                server,
                f"/api/research-runs/{research_run_id}/actions",
                action,
            )
            assert status == 409
            assert error["error"] == "SEALED_UNREAD"

        assert _snapshot(environment.database) == before_database
        assert tuple(
            sorted(
                path.relative_to(releases).as_posix()
                for path in releases.rglob("*")
                if path.is_file()
            )
        ) == before_release_files


def test_t0_explicit_search_rejects_a_cross_source_development_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    environment = _env(tmp_path, monkeypatch, "sleep")
    monkeypatch.setattr(
        research_console,
        "freeze_development_capability",
        lambda *_args, **_kwargs: development_run.FrozenDevelopmentCapability(
            status="READY",
            reason="ready",
            source_acquisition_sha256="c" * 64,
            profile_contract={},
        ),
    )

    with _serve(environment) as server:
        capability = server.research_console_controller._development_capability
        assert capability.status == "BLOCKED_DATA"
        assert capability.reason == (
            "Search and Development source acquisitions do not match"
        )


def test_t0_console_carries_search_economic_gate_into_development_capability(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gate = {
        "name": pilot.PROFILE_ECONOMIC_GATE,
        "version": 1,
        "minimum_net_profit_after_base_fees_pct": 0.5,
        "minimum_average_holding_period_minutes": 4320.0,
        "maximum_roi_exit_count": 0,
    }
    environment = _env(
        tmp_path,
        monkeypatch,
        "sleep",
        economic_gate=gate,
    )
    captured: dict[str, Any] = {}

    def freeze_development(*_args, **kwargs):
        captured.update(kwargs["profile_contract"])
        return development_run.FrozenDevelopmentCapability(
            status="READY",
            reason="ready",
            source_acquisition_sha256="b" * 64,
            profile_contract=kwargs["profile_contract"],
            profile_economic_gate=gate,
        )

    monkeypatch.setattr(
        research_console,
        "freeze_development_capability",
        freeze_development,
    )

    with _serve(environment) as server:
        assert captured["economic_gate"] == gate
        assert (
            server.research_console_controller._development_capability
            .profile_economic_gate
            == gate
        )


def _ready_round_one(environment: Env, monkeypatch: pytest.MonkeyPatch) -> str:
    _patch_outer_screen(monkeypatch)
    capability = search_campaign.freeze_search_capability(
        environment.database,
        environment.root,
        Path(sys.executable),
        environment.source,
    )
    assert capability.status == "READY"
    try:
        prepared = search_campaign.prepare_round_one(
            environment.database,
            capability,
            environment.seeds,
            profile_id=environment.profile_id,
        )
        result = pilot.screen_search(
            environment.root,
            pilot.load_plan(environment.root, pilot.SEARCH_CAMPAIGN),
            Path(sys.executable),
            environment.source,
        )
        assert result["status"] == "SEARCH_ROUND_READY_FOR_CHILDREN"
        search_campaign.complete_search_round(
            capability,
            prepared.campaign_id,
            0,
            environment.database,
            prepared.database_digest_before,
        )
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
            {"candidate_ids": [environment.seeds[0]]},
            {"profile_id": environment.profile_id, "candidate_ids": []},
            {
                "profile_id": environment.profile_id,
                "candidate_ids": ["a", "b", "c"],
            },
            {
                "profile_id": environment.profile_id,
                "candidate_ids": [environment.seeds[0]] * 2,
            },
            {
                "profile_id": environment.profile_id,
                "candidate_ids": [environment.seeds[0]],
                "path": "/tmp/x",
            },
        ):
            status, error, _ = _post(server, "/api/search-campaigns", body)
            assert status == 400 and error["error"] == "invalid_search_request"
        status, created, raw = _post(
            server,
            "/api/search-campaigns",
            {
                "profile_id": environment.profile_id,
                "candidate_ids": list(environment.seeds),
            },
        )
        assert status == 202
        campaign_id = str(created["campaign_id"])
        _path_free(raw, tmp_path)
        _wait_file(environment.control / "started-1")
        assert _snapshot(environment.database) == before
        active = server.research_console_controller._active
        assert active is not None
        pgid = active.process_group_id
        status, conflict, _ = _post(
            server,
            "/api/search-campaigns",
            {
                "profile_id": environment.profile_id,
                "candidate_ids": list(environment.seeds),
            },
        )
        assert status == 409 and conflict["error"] == "active_campaign"
        assert _post(
            server, f"/api/search-campaigns/{campaign_id}/actions", {"action": "CANCEL"}
        )[0] == 202
        state, raw = _wait_search(server, campaign_id, "FAILED")
        assert state["current_round"] == 1
        _path_free(raw, tmp_path)
        _wait_process_group_gone(pgid)
    _assert_only_terminal_projection(
        environment.database, before, campaign_id, status="FAILED"
    )


def test_t1_exit_three_is_a_legal_http_terminal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    environment = _env(tmp_path, monkeypatch, "no-parent")
    before = _snapshot(environment.database)
    with _serve(environment) as server:
        status, created, _ = _post(
            server,
            "/api/search-campaigns",
            {
                "profile_id": environment.profile_id,
                "candidate_ids": list(environment.seeds),
            },
        )
        assert status == 202
        campaign_id = str(created["campaign_id"])
        _wait_file(environment.control / "started-1")
        assert _snapshot(environment.database) == before
        (environment.control / "release-1").write_text("release")
        state, raw = _wait_search(
            server, campaign_id, "SEARCH_TERMINATED_NO_PARENT"
        )
        assert state["budget"]["consumed_total"] == 1 and state["search_finalist"] is None
        _path_free(raw, tmp_path)
    _assert_only_terminal_projection(
        environment.database, before, campaign_id, status="COMPLETED"
    )


@pytest.mark.parametrize(
    ("case", "expected"),
    (("cancel", "FAILED"), ("fail", "FAILED"), ("restart", "FAILED")),
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
        assert state["search_finalist"] is None
        _path_free(raw, tmp_path)
        if case == "cancel":
            _wait_process_group_gone(pgid)
    finally:
        if server is not None:
            _stop(server, thread)
        if replacement is not None:
            _stop(*replacement)
    _assert_only_terminal_projection(
        environment.database, before, campaign_id, status="FAILED"
    )


def test_t1_search_blocked_and_corrupt_search_are_local_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    environment = _env(tmp_path, monkeypatch, "production-failure")
    before = _snapshot(environment.database)
    with _serve(environment) as server:
        status, created, _ = _post(
            server,
            "/api/search-campaigns",
            {
                "profile_id": environment.profile_id,
                "candidate_ids": list(environment.seeds),
            },
        )
        assert status == 202
        state, raw = _wait_search(server, str(created["campaign_id"]), "FAILED")
        assert state["current_round"] == 1
        _path_free(raw, tmp_path)
        private = json.loads((environment.root / pilot.SEARCH_TERMINAL).read_bytes())
        assert private["status"] == "SEARCH_BLOCKED"

        (environment.root / pilot.SEARCH_TERMINAL).write_bytes(b'{"partial":')
        status, context, raw = _request(server, "/api/search/context")
        assert status == 200
        assert context["capability"]["status"] == "BLOCKED_DATA"
        assert context["state"]["status"] == "BLOCKED_DATA"
        _path_free(raw, tmp_path)
        assert _request(server, "/api/generation/context")[0] == 200
        assert _request(server, "/api/research/context")[0] == 200
        status, error, _ = _post(
            server,
            "/api/search-campaigns",
            {
                "profile_id": environment.profile_id,
                "candidate_ids": list(environment.seeds),
            },
        )
        assert status in {409, 503}
        assert error["error"] in {"campaign_consumed", "BLOCKED_DATA"}
    _assert_only_terminal_projection(
        environment.database,
        before,
        str(created["campaign_id"]),
        status="FAILED",
    )


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
        assert final["budget"]["active_attempt_limit"] == 3
        assert final["budget"]["maximum_attempts"] == 6
        _path_free(raw, tmp_path)
    _assert_only_terminal_projection(
        environment.database, before, campaign_id, status="COMPLETED"
    )


@pytest.mark.parametrize(
    "changed_factor",
    (
        "holdout",
        "stress",
        "development-period",
        "validation",
        search_campaign.ENTRY_SMA_FILTER_84_V1,
    ),
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
        assert status == 409 and error["error"] == "invalid_child_set"

    assert {
        path.relative_to(environment.root).as_posix(): path.read_bytes()
        for path in environment.root.rglob("*")
        if path.is_file()
    } == root_before
    assert _snapshot(environment.database) == before_database


def test_t2_database_change_after_engine_terminal_forces_failed_public_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    environment = _env(tmp_path, monkeypatch, "database-change", child=True)
    assert environment.child is not None
    campaign_id = _ready_round_one(environment, monkeypatch)
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
        _wait_file(environment.control / "terminal-written-2")
        engine_terminal_bytes = (
            environment.root / pilot.SEARCH_TERMINAL
        ).read_bytes()
        engine_terminal = json.loads(engine_terminal_bytes)
        assert engine_terminal["status"] == "SEARCH_FINALIST_FROZEN"
        assert engine_terminal["search_finalist"]["candidate_id"] == environment.child
        with get_connection(environment.database) as connection:
            connection.execute(
                "UPDATE candidates SET display_name=display_name || ' [T2 changed]' WHERE id=?",
                (environment.child,),
            )
        (environment.control / "allow-exit-2").write_text("allow-exit")
        failed, raw = _wait_search(server, campaign_id, "FAILED")

        assert failed["status"] == "FAILED" and failed["search_finalist"] is None
        assert failed["error_code"] == "SEARCH_DATABASE_CHANGED"
        assert not (environment.root / "console-status.json").exists()
        _path_free(raw, tmp_path)

        with get_connection(environment.database, read_only=True) as connection:
            projection = connection.execute(
                "SELECT * FROM generation_runs WHERE id=?", (campaign_id,)
            ).fetchone()
            research_run_count = connection.execute(
                "SELECT COUNT(*) FROM research_runs"
            ).fetchone()[0]
        assert projection is not None
        assert projection["source"] == "MANUAL"
        assert projection["model"] is None
        assert projection["status"] == "FAILED"
        assert projection["returned_strategy_count"] == 0
        assert projection["error_message"] == "SEARCH_DATABASE_CHANGED"
        assert projection["response_json"].encode() == engine_terminal_bytes
        report = json.loads(projection["parse_report_json"])
        assert report["finalist_binding"] is None
        assert report["evidence"]["terminal"]["sha256"] == pilot.digest(
            engine_terminal_bytes
        )
        assert research_run_count == 0

        status, context, raw = _request(server, "/api/search/context")
        assert status == 200
        assert context["state"]["status"] == "FAILED"
        assert context["state"]["error_code"] == "SEARCH_DATABASE_CHANGED"
        assert context["state"]["search_finalist"] is None
        assert context["generation_run"]["status"] == "FAILED"
        assert context["generation_run"]["error_code"] == "SEARCH_DATABASE_CHANGED"
        assert context["generation_run"]["finalist_binding"] is None
        assert context["generation_run"]["terminal"]["search_finalist"] is None
        _path_free(raw, tmp_path)

        status, error, raw = _post(
            server, "/api/research-runs", {"candidate_id": environment.child}
        )
        assert status == 409
        assert error["error"] == "search_finalist_required"
        _path_free(raw, tmp_path)
        with get_connection(environment.database, read_only=True) as connection:
            assert connection.execute(
                "SELECT COUNT(*) FROM research_runs"
            ).fetchone()[0] == 0


def test_t2_restart_cannot_complete_an_unprojected_engine_finalist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    environment = _env(tmp_path, monkeypatch, "real", child=True)
    assert environment.child is not None
    campaign_id = _ready_round_one(environment, monkeypatch)
    capability = search_campaign.freeze_search_capability(
        environment.database,
        environment.root,
        Path(sys.executable),
        environment.source,
    )
    assert capability.status == "READY"
    try:
        prepared = search_campaign.prepare_round_two(
            environment.database,
            capability,
            campaign_id,
            [{"candidate_id": environment.child, "changed_factor": "stoploss"}],
        )
        (environment.control / "release-2").write_text("release")
        completed = subprocess.run(
            prepared.argv,
            cwd=Path(__file__).resolve().parent.parent,
            capture_output=True,
            timeout=10,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr.decode()
        terminal = json.loads(
            (environment.root / pilot.SEARCH_TERMINAL).read_bytes()
        )
        assert terminal["status"] == "SEARCH_FINALIST_FROZEN"
        with get_connection(environment.database) as connection:
            connection.execute(
                "UPDATE candidates SET display_name=display_name || ' [crashed]' WHERE id=?",
                (environment.child,),
            )
    finally:
        capability.close()

    with _serve(environment) as server:
        status, state, raw = _request(
            server, f"/api/search-campaigns/{campaign_id}"
        )
        assert status == 200
        assert state["status"] == "INTERRUPTED"
        assert state["search_finalist"] is None
        _path_free(raw, tmp_path)

        status, context, raw = _request(server, "/api/search/context")
        assert status == 200
        assert context["state"]["status"] == "INTERRUPTED"
        assert context["state"]["search_finalist"] is None
        assert context["generation_run"] is None
        _path_free(raw, tmp_path)

        status, error, raw = _post(
            server, "/api/research-runs", {"candidate_id": environment.child}
        )
        assert status == 409
        assert error["error"] == "search_finalist_required"
        _path_free(raw, tmp_path)
        with get_connection(environment.database, read_only=True) as connection:
            assert connection.execute(
                "SELECT COUNT(*) FROM generation_runs WHERE id=?", (campaign_id,)
            ).fetchone()[0] == 0
            assert connection.execute(
                "SELECT COUNT(*) FROM research_runs"
            ).fetchone()[0] == 0


def test_t1_terminal_projection_covers_two_rounds_and_invalid_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    environment = _env(tmp_path, monkeypatch, "real", seeds=2, timeframe="1d")
    with _serve(environment) as server:
        status, context, _ = _request(server, "/api/search/context")
        assert status == 200 and len(context["candidates"]) == 2
        before_r1 = _snapshot(environment.database)
        status, created, _ = _post(
            server,
            "/api/search-campaigns",
            {
                "profile_id": environment.profile_id,
                "candidate_ids": list(environment.seeds),
            },
        )
        assert status == 202
        campaign_id = str(created["campaign_id"])
        _wait_file(environment.control / "started-1")
        assert _snapshot(environment.database) == before_r1
        (environment.control / "release-1").write_text("release")
        r1, raw = _wait_search(server, campaign_id, "SEARCH_ROUND_READY_FOR_CHILDREN")
        assert r1["selected_parent"]["candidate_id"] == environment.seeds[0]
        assert len(r1["frozen_ranking"]) == 1
        assert r1["budget"]["consumed_total"] == 2
        assert r1["budget"]["active_attempt_limit"] == 3
        assert r1["budget"]["maximum_attempts"] == 6
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
        assert final["budget"]["consumed_total"] == 3
        assert final["budget"]["active_attempt_limit"] == 3
        assert final["budget"]["maximum_attempts"] == 6
        assert final["boundaries"]["research_runs_created_by_search"] == 0
        _path_free(raw, tmp_path)
        _assert_only_terminal_projection(
            environment.database, before_r2, campaign_id, status="COMPLETED"
        )

        records = [json.loads(line) for line in
                   (environment.root / pilot.SEARCH_TRIALS).read_text().splitlines()]
        assert sum(r["record_type"] == "ROUND_RECEIPT" for r in records) == 2
        assert sum(r["record_type"] == "TRIAL" for r in records) == 3
        terminal = json.loads((environment.root / pilot.SEARCH_TERMINAL).read_bytes())
        assert terminal["status"] == "SEARCH_FINALIST_FROZEN"
        round_one = json.loads(
            (environment.root / search_campaign.ROUND_ONE_CAMPAIGN).read_bytes()
        )
        round_two = json.loads(
            (environment.root / pilot.SEARCH_CAMPAIGN).read_bytes()
        )
        assert terminal["finalist_gate"] == pilot.profile_search_finalist_gate(
            round_one["profile_snapshot"]
        )
        with get_connection(environment.database, read_only=True) as connection:
            projection = connection.execute(
                "SELECT request_json,response_json,parse_report_json "
                "FROM generation_runs WHERE id=?",
                (campaign_id,),
            ).fetchone()
        request = json.loads(projection["request_json"])
        response = json.loads(projection["response_json"])
        report = json.loads(projection["parse_report_json"])
        attempts = report["evidence"]["attempts"]
        assert request == {
            "schema": pilot.SEARCH_PROJECTION_SCHEMA,
            "campaign_id": campaign_id,
            "round_contracts": [round_one, round_two],
        }
        assert [item["attempt_number"] for item in attempts] == [1, 2, 3]
        assert attempts[1]["technical_status"] == "INVALID"
        assert attempts[1]["failure_reason"] == (
            "bounded mixed-attempt fixture failure"
        )
        assert attempts[1]["search_metrics"] is None
        assert attempts[1]["evidence"] is None
        assert response == terminal
        assert response["brief"]["frozen_ranking"] == [
            {
                key: attempt[key]
                for key in (
                    "candidate_id",
                    "strategy_sha256",
                    "round",
                    "attempt_number",
                )
            }
            for attempt in (attempts[2], attempts[0])
        ]
        assert response["search_finalist"]["candidate_id"] == child_id
        assert report["finalist_binding"]["projection_sha256"] == (
            pilot.search_projection_sha256(
                request, response, report["evidence"]
            )
        )

        profile = round_one["profile_snapshot"]
        profile_contract = pilot.profile_search_contract(
            profile, round_one["search_timerange"],
            round_one["development_timerange"], round_one["pre_roll_candles"],
        )
        dev_root, dev_python, dev_source = _frozen_capability_fixture(
            tmp_path / "development-capability",
            monkeypatch,
            pair=profile["pairs"][0],
            instrument_id="ADA-USDT-SWAP",
            timeframe="1d",
            profile_contract=profile_contract,
        )
        dev_capability = development_run.freeze_development_capability(
            dev_root, dev_python, dev_source, profile_contract=profile_contract
        )
        assert dev_capability.status == "READY"
        server.research_console_controller._development_capability = dev_capability
        status, research_context, _ = _request(server, "/api/research/context")
        assert status == 200
        assert research_context["capability"]["timeframe"] == "1d"
        assert research_context["capability"]["economic_gate"] == pilot.PROFILE_SEARCH_GATE

        with get_connection(environment.database, read_only=True) as connection:
            candidate = connection.execute(
                "SELECT class_name,code_text,code_sha256 FROM candidates WHERE id=?", (child_id,)
            ).fetchone()

        class DevelopmentProcess:
            pid = 2_000_000_001

            def __init__(self, argv: tuple[str, ...]) -> None:
                self.argv, self.returncode = argv, None

            def poll(self) -> Optional[int]:
                if self.returncode is None:
                    self.returncode = 1
                    run_id = self.argv[self.argv.index("--research-run-id") + 1]
                    database = self.argv[self.argv.index("--database") + 1]
                    run_dir = Path(self.argv[self.argv.index("--run-dir") + 1])
                    produced, _ = _native_1d_development_artifact(
                        run_dir,
                        candidate["class_name"],
                        profile_contract["development_timerange"],
                        profile["taker_fee_rate"],
                    )
                    backtest_artifact.import_backtest_execution(
                        database, run_dir / "development-evidence", produced.archive,
                        run_id, "DEVELOPMENT", candidate["class_name"], "2026.7",
                        produced.provenance_sha256,
                        allow_zero_trades=True, mark_execution_finished=True,
                    )
                    development_run.finalize_development_gate(database, run_id)
                    self.returncode = 0
                return self.returncode

            def wait(self, timeout: Optional[float] = None) -> int:
                del timeout
                return int(self.poll())

        monkeypatch.setattr(
            research_console.subprocess,
            "Popen",
            lambda argv, **_kwargs: DevelopmentProcess(tuple(str(item) for item in argv)),
        )
        status, created, _ = _post(server, "/api/research-runs", {"candidate_id": child_id})
        assert status == 202
        run_id = created["research_run_id"]
        public = created
        for _ in range(200):
            status, public, _ = _request(server, f"/api/research-runs/{run_id}")
            if status == 200 and server.research_console_controller._active is None:
                break
            time.sleep(0.01)
        assert public["candidate_id"] == child_id
        assert public["holdout"]["status"] == "SEALED_UNREAD"
        assert public["holdout_stress"]["status"] == "SEALED_UNREAD"
        with get_connection(environment.database, read_only=True) as connection:
            run_rows = connection.execute(
                "SELECT candidate_id,research_profile_id,input_snapshot_json FROM research_runs WHERE id=?",
                (run_id,),
            ).fetchall()
            executions = connection.execute(
                "SELECT scenario,timeframe FROM backtest_executions WHERE research_run_id=?", (run_id,)
            ).fetchall()
        assert len(run_rows) == 1 and [tuple(item) for item in executions] == [("DEVELOPMENT", "1d")]
        snapshot = json.loads(run_rows[0]["input_snapshot_json"])
        assert (run_rows[0]["candidate_id"], run_rows[0]["research_profile_id"]) == (child_id, profile["id"])
        assert snapshot["normalized_profile_contract"]["profile_snapshot"] == profile
        assert snapshot["normalized_profile_contract"]["profile_snapshot_sha256"] == profile_contract["profile_snapshot_sha256"]
        assert snapshot["timerange"] == profile_contract["development_timerange"]
        assert snapshot["gate"] == profile_contract["finalist_gate"]
        assert snapshot["search_finalist_binding"]["projection_sha256"] == report["finalist_binding"]["projection_sha256"]
        assert snapshot["search_finalist_binding"]["source_sha256"] == candidate["code_sha256"]
        assert snapshot["search_finalist_binding"]["search_timerange"] == profile_contract["search_timerange"]
        assert snapshot["holdout"] == snapshot["holdout_stress"] == "SEALED_UNREAD"
