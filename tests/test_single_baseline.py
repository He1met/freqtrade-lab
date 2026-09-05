"""Single-baseline contracts; synthetic evidence only, no market acquisition."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import sys
import sqlite3

import pytest

from lab import bounded_research as pilot, search_campaign, development_run, research_console
from lab.database import get_connection
from tests.test_development_run import _approved_candidate_database
from tests.test_search_campaign import _frozen_capability, _prepare_round_one, _economic_search_trial


def _single(source_sha):
    return {"mode": "SINGLE_BASELINE_V1", "version": 1,
            "maximum_rounds": 1, "maximum_attempts": 1,
            "protocol_sha256": "d" * 64, "strategy_sha256": source_sha}


def _candidate_sha(database, candidate):
    with get_connection(database, read_only=True) as connection:
        return connection.execute("SELECT code_sha256 FROM candidates WHERE id=?", (candidate,)).fetchone()[0]


@pytest.fixture
def single_plan(tmp_path, monkeypatch):
    database, candidate = _approved_candidate_database(tmp_path)
    policy = _single(_candidate_sha(database, candidate))
    capability = _frozen_capability(tmp_path, monkeypatch, database, candidate, single_baseline=policy)
    try:
        _prepare_round_one(database, capability, [candidate], campaign_id="single-contract")
        yield database, capability, pilot.load_plan(capability.search_root, pilot.SEARCH_CAMPAIGN)
    finally:
        capability.close()


@pytest.mark.parametrize("mutation", ["null_candidate", "number_candidate", "bool_budget", "two_seeds",
                                      "wrong_source", "round_two", "extra", "null_policy", "bool_limit"])
def test_t0_single_plan_rejects_malformed_or_expanded_contract(single_plan, mutation):
    database, capability, original = single_plan
    plan = {k: deepcopy(v) for k, v in original.items() if not k.startswith("_")}
    if mutation == "null_candidate": plan["candidates"] = [None]
    elif mutation == "number_candidate": plan["candidates"] = [1]
    elif mutation == "bool_budget": plan["active_attempt_limit"] = True
    elif mutation == "two_seeds": plan["candidates"] *= 2
    elif mutation == "wrong_source": plan["single_baseline"]["strategy_sha256"] = "e" * 64
    elif mutation == "round_two": plan["round"] = 2
    elif mutation == "extra": plan["single_baseline"]["allow_legacy"] = True
    elif mutation == "null_policy": plan["single_baseline"] = None
    elif mutation == "bool_limit": plan["single_baseline"]["maximum_attempts"] = True
    before = search_campaign.business_table_digest(database)
    with pytest.raises(pilot.PilotError):
        pilot._load_search_campaign(plan, pilot.canonical(plan))
    assert search_campaign.business_table_digest(database) == before
    assert not (capability.search_root / pilot.SEARCH_TRIALS).exists()


def test_t0_single_gate_and_default_round_one_remain_distinct(single_plan):
    _, _, plan = single_plan
    trial = _economic_search_trial(total_trades=40, net_profit_after_base_fees_pct=1.0,
                                   gross_profit_before_fees_pct=1.1, max_drawdown_pct=1.0)
    trial.update(round=1, attempt_number=1)
    _, status, finalist = pilot._search_round_outcome(plan, [trial], [trial], 0)
    assert status == "SEARCH_FINALIST_FROZEN" and finalist is not None
    for metrics in ({"total_trades": 1}, {"net_profit_after_base_fees_pct": -0.1,
                                         "gross_profit_before_fees_pct": 0.0}, {"profit_factor": 0.5}):
        failed = deepcopy(trial)
        failed["search_metrics"].update(metrics)
        _, status, finalist = pilot._search_round_outcome(plan, [failed], [failed], 0)
        assert status == "SEARCH_TERMINATED_NO_FINALIST" and finalist is None
    old = dict(plan)
    old.pop("single_baseline")
    old["active_attempt_limit"] = pilot.PROFILE_ACTIVE_ATTEMPTS
    _, status, finalist = pilot._search_round_outcome(old, [trial], [trial], 0)
    assert status == "SEARCH_ROUND_READY_FOR_CHILDREN" and finalist is None


def test_t0_single_capability_policy_drift_and_round_two_fail_before_mutation(single_plan):
    database, capability, plan = single_plan
    before = search_campaign.business_table_digest(database)
    with pytest.raises(search_campaign.SearchCampaignError, match="Round 2"):
        search_campaign.prepare_round_two(database, capability, plan["campaign_id"], [])
    for policy in (None, {**capability.single_baseline, "protocol_sha256": "e" * 64}):
        with pytest.raises(search_campaign.SearchCampaignError, match="changed"):
            search_campaign._require_ready(replace(capability, single_baseline=policy))
    assert search_campaign.business_table_digest(database) == before
    assert not (capability.search_root / pilot.SEARCH_TRIALS).exists()


@pytest.mark.parametrize("mode", ["no-parent", "no-finalist"])
def test_t1_single_failed_attempt_preserves_technical_economic_distinction(tmp_path, monkeypatch, mode):
    from tests.test_search_console_http import _env, _serve, _post, _wait_search, _wait_file
    env = _env(tmp_path, monkeypatch, mode)
    single = _single(_candidate_sha(env.database, env.seeds[0]))
    acquisition = search_campaign._acquisition_snapshot
    monkeypatch.setattr(search_campaign, "_acquisition_snapshot",
                        lambda *args: {**acquisition(*args), "single_baseline": single})
    with _serve(env) as server:
        status, created, _ = _post(server, "/api/search-campaigns", {
            "profile_id": env.profile_id, "candidate_ids": list(env.seeds)})
        assert status == 202
        _wait_file(env.control / "started-1")
        (env.control / "release-1").write_text("release")
        result, _ = _wait_search(server, created["campaign_id"], "SEARCH_TERMINATED_NO_FINALIST")
        assert result["search_finalist"] is None and result["budget"]["remaining"] == 0
        assert "Round 2" not in result["message"]
        if mode == "no-parent":
            assert result["attempts"][0]["technical_status"] == "INVALID"
            assert result["attempts"][0]["search_metrics"] is None
            assert "economic outcome is UNKNOWN" in result["message"]
        else:
            assert result["attempts"][0]["technical_status"] == "VALID"
            assert result["attempts"][0]["search_metrics"]["net_profit_after_base_fees_pct"] < 0
            assert "did not pass" in result["message"]
        with get_connection(env.database, read_only=True) as connection:
            assert connection.execute("SELECT COUNT(*) FROM research_runs").fetchone()[0] == 0


def test_t2_single_source_http_projection_review_and_atomic_development(tmp_path, monkeypatch):
    """Real Feather/SQLite/HTTP/runner/projection; only native boundaries are fakes."""
    from tests.test_search_data_producer import (
        _source_acquisition, _profile_prepare_kwargs, _profile_candidate_id,
    )
    from tests.test_search_console_http import (
        Env, REAL_SCREEN, _fake_codex, _serve, _post, _request, _wait_search, _wait_file,
    )
    from scripts import fetch_okx_profile_data as producer

    kwargs = _profile_prepare_kwargs(tmp_path)
    database = kwargs["database_path"]
    candidate = _profile_candidate_id(database)
    single = _single(_candidate_sha(database, candidate))
    gate = {"name": pilot.PROFILE_ECONOMIC_GATE, "version": 1,
            "minimum_net_profit_after_base_fees_pct": 0.5,
            "minimum_average_holding_period_minutes": 30.0, "maximum_roi_exit_count": 0}
    window = tmp_path / "window.json"
    window.write_bytes(pilot.canonical({"schema": producer.PROFILE_WINDOW_SCHEMA,
        "data_start_utc": "2026-05-31T22:00:00Z", "search_start_utc": "2026-06-01T00:00:00Z",
        "development_start_utc": "2026-07-01T00:00:00Z", "end_exclusive_utc": "2026-07-31T00:00:00Z"}))
    # Production configure performs no requests; the source files below are
    # explicitly generated synthetic candles, never a live endpoint response.
    configured = producer.configure_profile_acquisition(database, kwargs["profile_id"], window,
                                                        kwargs["pre_roll_candles"], gate, single)
    assert configured["single_baseline"] == single
    complete, provenance_sha, receipt_sha = _source_acquisition(tmp_path, economic_gate=gate, single_baseline=single)
    source_bytes = (complete / "retained-data-provenance.json").read_bytes()
    assert json.loads(source_bytes)["contract"]["profile_acquisition"]["single_baseline"] == single
    policy_path, gate_path = tmp_path / "single.json", tmp_path / "gate.json"
    policy_path.write_bytes(pilot.canonical(single))
    gate_path.write_bytes(pilot.canonical(gate))
    roots = [tmp_path / "search", tmp_path / "development"]
    for command, root in zip(("prepare-search-data", "prepare-development-data"), roots):
        assert pilot.main([command, "--source-root", str(complete), "--output-root", str(root),
            "--source-provenance-sha256", provenance_sha, "--source-receipt-sha256", receipt_sha,
            "--database", str(database), "--profile-id", kwargs["profile_id"],
            "--search-timerange", kwargs["search_timerange"], "--development-timerange", kwargs["development_timerange"],
            "--pre-roll-candles", str(kwargs["pre_roll_candles"]), "--single-baseline", str(policy_path),
            "--economic-gate", str(gate_path)]) == 0
    # The existing source cannot be relabelled after acquisition, including
    # removing opt-in or swapping the precommitted protocol.
    for policy in (None, {**single, "protocol_sha256": "e" * 64}):
        output = tmp_path / "relabelled"
        with pytest.raises(pilot.PilotError):
            pilot.prepare_search_data(complete, output, provenance_sha, receipt_sha,
                                      **kwargs, economic_gate=gate, single_baseline=policy)
        assert not output.exists()
    runtime, control, native = (tmp_path / name for name in ("runtime", "control", "fake-native"))
    for path in (runtime, control, native): path.mkdir()
    python = Path(sys.executable).resolve()
    pi, si = python.stat(), native.stat()
    monkeypatch.setattr(search_campaign, "_freqtrade_snapshot", lambda *_: {
        "freqtrade_python": python, "freqtrade_source": native,
        "python_identity": (pi.st_dev, pi.st_ino, pi.st_size, pi.st_mtime_ns),
        "source_identity": (si.st_dev, si.st_ino)})
    monkeypatch.setattr(development_run, "_verify_python", lambda *_: None)
    monkeypatch.setattr(development_run, "_git_value", lambda _source, *args: {
        ("rev-parse", "HEAD"): development_run.SUPPORTED_FREQTRADE_COMMIT,
        ("rev-parse", "HEAD^{tree}"): development_run.SUPPORTED_FREQTRADE_TREE,
        ("describe", "--exact-match", "--tags", "HEAD"): development_run.SUPPORTED_FREQTRADE_VERSION,
        ("status", "--porcelain=v1", "--untracked-files=all"): "",
    }[args])
    screen = REAL_SCREEN.replace('if current["round"] == 2 else -0.1 - index',
                                 'if current["round"] == 2 or "single_baseline" in current else -0.1 - index')
    screen = screen.replace('"total_trades": 40, "profit_pct": profit,',
                            '"total_trades": 40, "profit_pct": profit, "roi_exit_count": 0,')
    monkeypatch.setattr(search_campaign, "_argv", lambda cap: (
        str(python), "-c", screen, str(cap.search_root), str(native), str(control), "real"))
    env = Env(database, kwargs["profile_id"], (candidate,), None, roots[0], runtime, roots[1],
              native, control, _fake_codex(tmp_path), {"value": False})
    with _serve(env) as server:
        controller = server.research_console_controller
        assert controller._development_capability.status == "READY"
        status, context, _ = _request(server, "/api/search/context")
        assert status == 200 and context["capability"]["single_baseline"] == single
        assert context["limits"]["maximum_candidates_per_round"] == 1
        before = search_campaign.business_table_digest(database)
        status, started, _ = _post(server, "/api/search-campaigns", {
            "profile_id": kwargs["profile_id"], "candidate_ids": [candidate]})
        assert status == 202, started
        campaign = started["campaign_id"]
        _wait_file(control / "started-1")
        assert search_campaign.business_table_digest(database) == before
        (control / "release-1").write_text("release")
        final, _ = _wait_search(server, campaign, "SEARCH_FINALIST_FROZEN")
        assert final["budget"]["consumed_total"] == 1 and final["budget"]["remaining"] == 0
        for path, body in (("/api/search-campaigns", {"profile_id": kwargs["profile_id"], "candidate_ids": [candidate]}),
                           (f"/api/search-campaigns/{campaign}/actions", {"action": "START_ROUND_2", "candidates": []})):
            assert _post(server, path, body)[0] == 409
        binding = search_campaign.verified_finalist_binding(database, controller._search_capability, candidate)
        verified = search_campaign.verify_persisted_finalist_projection(database, binding)
        review = {**verified["protocol_review_identity"], "all_protocol_gates": "PASSED"}
        frozen = search_campaign.business_table_digest(database)
        # Neither a missing/damaged receipt nor edited raw evidence may be
        # repaired into a new single-round verdict by a subsequent API call.
        terminal_path = roots[0] / pilot.SEARCH_TERMINAL
        ledger_path = roots[0] / pilot.SEARCH_TRIALS
        raw_path = next((roots[0] / f"search-results-round-1/{candidate}/raw").glob("*.zip"))
        for path in (terminal_path, ledger_path, raw_path):
            original = path.read_bytes()
            try:
                path.write_bytes(b"{}\n" if path != raw_path else b"tampered")
                assert _post(server, "/api/research-runs", {"candidate_id": candidate, "protocol_review": review})[0] == 409
                assert search_campaign.business_table_digest(database) == frozen
            finally:
                path.write_bytes(original)
        terminal_original = terminal_path.read_bytes()
        try:
            terminal_path.unlink()
            assert _post(server, "/api/research-runs", {"candidate_id": candidate, "protocol_review": review})[0] == 409
        finally:
            terminal_path.write_bytes(terminal_original)
        # A policy removed from the R1 plan is still bound by the immutable
        # acquisition/capability, before considering any terminal status.
        plan_path = roots[0] / search_campaign.ROUND_ONE_CAMPAIGN
        plan_original = plan_path.read_bytes()
        try:
            legacy = json.loads(plan_original)
            legacy.pop("single_baseline")
            legacy["active_attempt_limit"] = pilot.PROFILE_ACTIVE_ATTEMPTS
            plan_path.write_bytes(pilot.canonical(legacy))
            assert _post(server, "/api/research-runs", {"candidate_id": candidate, "protocol_review": review})[0] == 409
        finally:
            plan_path.write_bytes(plan_original)
        for invalid in (None, {**review, "all_protocol_gates": "UNKNOWN"},
                        {**review, "all_protocol_gates": "FAILED"}, {**review, "attempt_number": True},
                        *({**review, key: "e" * 64} for key in ("protocol_sha256", "data_provenance_sha256",
                          "source_sha256", "raw_artifact_sha256", "candidate_id"))):
            body = {"candidate_id": candidate, "protocol_review": invalid}
            status, error, _ = _post(server, "/api/research-runs", body)
            assert status == 409 and error["error"] == "BLOCKED_SECURITY", error
            assert search_campaign.business_table_digest(database) == frozen
        # Fail after inputs were written but before inserting rows: transaction
        # and controller cleanup leave no half-run, then the same handoff works.
        materialize = development_run._materialize_inputs
        def fail_after_materialization(*args):
            materialize(*args)
            raise sqlite3.OperationalError("injected")
        before_directories = set(runtime.rglob("*"))
        with monkeypatch.context() as patch:
            patch.setattr(development_run, "_materialize_inputs", fail_after_materialization)
            assert _post(server, "/api/research-runs", {"candidate_id": candidate, "protocol_review": review})[0] == 503
        assert search_campaign.business_table_digest(database) == frozen
        assert set(runtime.rglob("*")) == before_directories
        # Stub only the Development worker process; no D market result is made.
        # Its deliberate failure still consumes the single-baseline handoff.
        popen = research_console.subprocess.Popen
        monkeypatch.setattr(research_console.subprocess, "Popen", lambda argv, **kw: popen(
            [str(python), "-c", "raise SystemExit(7)"] if "--research-run-id" in argv else argv, **kw))
        status, created, _ = _post(server, "/api/research-runs", {"candidate_id": candidate, "protocol_review": review})
        assert status == 202, created
        run_id = created["research_run_id"]
        with get_connection(database, read_only=True) as connection:
            assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
            rows = connection.execute("SELECT id,input_snapshot_json FROM research_runs").fetchall()
            assert len(rows) == 1 and rows[0]["id"] == run_id
            snap = json.loads(rows[0]["input_snapshot_json"])
            assert snap["protocol_review"] == review and snap["search_finalist_binding"] == binding
            assert snap["holdout"] == snap["holdout_stress"] == "SEALED_UNREAD"
            assert connection.execute("SELECT research_run_id FROM backtest_executions").fetchone()[0] == run_id
        assert _post(server, "/api/research-runs", {"candidate_id": candidate, "protocol_review": review})[0] == 409
        # Completion/failure of the stub worker cannot reopen this one-shot
        # handoff. Exercise the transaction gate even after worker shutdown.
        with get_connection(database) as connection:
            connection.execute("UPDATE research_runs SET status='FAILED' WHERE id=?", (run_id,))
        directory = tmp_path / "duplicate-run"
        directory.mkdir()
        with pytest.raises(development_run.DevelopmentRunError, match="already consumed"):
            development_run.prepare_development_run(database, directory, candidate,
                controller._development_capability, research_run_id=directory.name,
                search_finalist_binding=binding, protocol_review=review)
        assert not list(directory.iterdir())
        assert (complete / "retained-data-provenance.json").read_bytes() == source_bytes
