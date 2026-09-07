"""Four bounded groups: synthetic Search archives, HTTP and temporary SQLite only."""
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from lab import search_campaign as sc, codex_generation as cg, development_run as dr
from lab import bounded_research as pilot
from lab.database import get_connection
from tests.test_single_baseline import _single, _candidate_sha
from tests.test_search_console_http import _env, _serve, _post, _request, _wait_search, _wait_file, REAL_SCREEN
from tests.test_prefilter_evidence import state


@pytest.fixture
def evidence(tmp_path, monkeypatch):
    env = _env(tmp_path, monkeypatch, "real")
    cid = env.seeds[0]
    single = _single(_candidate_sha(env.database, cid))
    acquisition = sc._acquisition_snapshot
    monkeypatch.setattr(sc, "_acquisition_snapshot", lambda *a: {**acquisition(*a), "single_baseline": single})
    screen = REAL_SCREEN.replace('if current["round"] == 2 else -0.1 - index',
                                'if current["round"] == 2 or "single_baseline" in current else -0.1 - index')
    monkeypatch.setattr(sc, "_argv", lambda cap: (sys.executable, "-c", screen,
        str(cap.search_root), str(env.source), str(env.control), "real"))
    with _serve(env) as server:
        code, created, _ = _post(server, "/api/search-campaigns", {"profile_id": env.profile_id, "candidate_ids": [cid]})
        assert code == 202, created
        campaign = created["campaign_id"]
        _wait_file(env.control / "started-1")
        (env.control / "release-1").write_text("release")
        _wait_search(server, campaign, "SEARCH_FINALIST_FROZEN")
        cap = server.research_console_controller._search_capability
        binding = sc.verified_finalist_binding(env.database, cap, cid)
        parsed = sc.verify_persisted_finalist_projection(env.database, binding)
        identity = parsed["protocol_review_identity"]
        archive = next(env.root.glob(f"search-results-round-1/{cid}/raw/*.zip"))
        report = dict(campaign_id=campaign, candidate_id=cid, protocol_sha256=identity["protocol_sha256"],
            strategy_sha256=identity["source_sha256"], archive_sha256=identity["raw_artifact_sha256"],
            actual_Search_attempts=1, all_protocol_gates="FAILED",
            gates=[dict(gate="synthetic_distribution", status="FAILED", actual=1, frozen_requirement=">=3")],
            cost_decomposition={"conservative_net_usdt": 12.5}, native_metrics={"total_trades": 40, "profit_pct": 1.25})
        path = tmp_path / "review.json"
        def write():
            path.write_bytes(pilot.canonical(report))
            return pilot.digest(path.read_bytes())
        sha = write()
        yield SimpleNamespace(**locals())


def attach(e, **kw):
    return sc.attach_search_protocol_rejection(e.env.database, e.campaign, e.path, e.archive,
        review_sha256=kw.get("sha", e.sha))


def test_cli_public_read_and_unchanged_history(evidence):
    e = evidence
    before = state(e.env.database)
    gid = e.binding["generation_run_id"]
    assert cg.load_generation(e.env.database, gid)["candidate"]["review_status"] == "APPROVED"
    command = [sys.executable, str(Path(__file__).resolve().parents[1] / "scripts/attach_search_protocol_rejection.py"),
        "--database", str(e.env.database), "--campaign-id", e.campaign, "--review-path", str(e.path),
        "--archive-path", str(e.archive), "--review-sha256", e.sha]
    run = subprocess.run(command, capture_output=True, text=True, timeout=15)
    assert run.returncode == 0, run.stderr
    value = json.loads(run.stdout)
    public = cg.load_generation(e.env.database, gid)["candidate"]
    assert public["review_status"] == "APPROVED" and public["search_protocol_rejection"] == value
    status, context, _ = _request(e.server, "/api/search/context")
    assert status == 200 and context["state"]["status"] == "SEARCH_FINALIST_FROZEN"
    assert context["state"]["search_protocol_rejection"] == value
    assert context["generation_run"]["status"] == "COMPLETED"
    after = state(e.env.database)
    assert len(after) == 6
    for table in before:
        if table != "candidates": assert before[table] == after[table]


@pytest.mark.parametrize("bad", ["hash", "identity", "empty", "infinite", "null", "symlink", "deep", "existing_run",
                                 "archive", "protocol", "source", "attempt", "overlap"])
def test_bad_attachment_is_atomic(evidence, bad):
    e = evidence
    if bad == "existing_run":
        with get_connection(e.env.database) as c:
            c.execute("INSERT INTO research_runs (id,candidate_id,research_profile_id,trigger_type,status,stage,pipeline_version,input_snapshot_json,run_dir,created_at) VALUES ('prior',?,?,'MANUAL','PENDING','PENDING','synthetic','{}','synthetic','2026-01-01')", (e.cid, e.env.profile_id))
    before = state(e.env.database)
    if bad == "identity": e.report["candidate_id"] = "other"
    if bad == "protocol": e.report["protocol_sha256"] = "e" * 64
    if bad == "source": e.report["strategy_sha256"] = "e" * 64
    if bad == "attempt": e.report["actual_Search_attempts"] = True
    if bad == "overlap": e.report["native_metrics"]["conservative_net_usdt"] = -1
    if bad == "archive": e.archive.write_bytes(b"changed synthetic archive")
    if bad == "empty": e.report["gates"] = []
    if bad == "infinite": e.report["cost_decomposition"]["conservative_net_usdt"] = float("inf")
    if bad == "null": e.report["gates"] = None
    if bad == "deep": e.path.write_bytes(b'{"x":' + b'[' * 2000 + b'0' + b']' * 2000 + b'}')
    elif bad == "infinite": e.path.write_text(json.dumps(e.report))
    else: e.write()
    sha = pilot.digest(e.path.read_bytes())
    if bad == "symlink":
        original = e.path.with_name("original.json")
        e.path.rename(original); e.path.symlink_to(original)
    with pytest.raises(sc.SearchCampaignError):
        attach(e, sha="0" * 64 if bad == "hash" else sha)
    assert state(e.env.database) == before


def test_idempotence_conflict_and_metadata_preservation(evidence):
    e = evidence
    with get_connection(e.env.database, read_only=True) as c:
        original = json.loads(c.execute("SELECT metadata_json FROM candidates WHERE id=?", (e.cid,)).fetchone()[0])
    first = attach(e)
    frozen = state(e.env.database)
    assert attach(e) == first and state(e.env.database) == frozen
    e.report["gates"][0]["actual"] = 2
    with pytest.raises(sc.SearchCampaignError, match="Different"):
        attach(e, sha=e.write())
    assert state(e.env.database) == frozen
    with get_connection(e.env.database, read_only=True) as c:
        metadata = json.loads(c.execute("SELECT metadata_json FROM candidates WHERE id=?", (e.cid,)).fetchone()[0])
    assert metadata.pop("search_protocol_rejection") == first and metadata == original
    # Both optional readers remain strict and independent; neither erases the other.
    from tests.test_prefilter_evidence import fixture
    other = e.tmp_path / "prefilter"; other.mkdir()
    db, gid, cid, root, args = fixture(other)
    cg.attach_prefilter_evidence(db, cid, root, **args)
    with get_connection(db, read_only=True) as c:
        generation = c.execute("SELECT * FROM generation_runs WHERE id=?", (gid,)).fetchone()
        candidate = c.execute("SELECT * FROM candidates WHERE id=?", (cid,)).fetchone()
        combined = json.loads(candidate["metadata_json"])
    value = json.loads(json.dumps(first))
    value.update(profile_id=generation["research_profile_id"], profile_snapshot_sha256=combined["prefilter_evidence"]["profile_snapshot_sha256"])
    value["protocol_review_identity"].update(candidate_id=cid, source_sha256=candidate["code_sha256"])
    combined["search_protocol_rejection"] = value
    assert cg._generated_candidate_review(generation, candidate, combined)["status"] == "APPROVED"
    combined["prefilter_evidence"]["native_search_runs"] = 1
    with pytest.raises(cg.GenerationContractError):
        cg._generated_candidate_review(generation, candidate, combined)


def test_rejected_exact_passed_cannot_materialize_even_directly(evidence, monkeypatch, tmp_path):
    e = evidence
    attach(e)
    frozen = state(e.env.database)
    with pytest.raises(sc.SearchCampaignError, match="REJECTED"):
        sc.verified_finalist_binding(e.env.database, e.cap, e.cid)
    review = {**e.identity, "all_protocol_gates": "PASSED"}
    code, error, _ = _post(e.server, "/api/research-runs", {"candidate_id": e.cid, "protocol_review": review})
    assert code == 409 and error["error"] == "search_protocol_rejected"
    # Bypass only native environment readiness, retaining the real DB/projection/transaction gates.
    monkeypatch.setattr(dr, "_require_ready", lambda *_: None)
    monkeypatch.setattr(dr, "_materialize_inputs", lambda *_: pytest.fail("must reject before materialization"))
    directory = tmp_path / "direct-run"; directory.mkdir()
    capability = SimpleNamespace(profile_contract=e.parsed["profile_contract"], timeframe="5m")
    with pytest.raises(dr.DevelopmentRunError, match="REJECTED"):
        dr.prepare_development_run(e.env.database, directory, e.cid, capability,
            research_run_id=directory.name, search_finalist_binding=e.binding, protocol_review=review)
    assert not list(directory.iterdir()) and state(e.env.database) == frozen
