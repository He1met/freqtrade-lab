"""Opt-in, one-shot artificial D/H/Stress native batch; never run by pytest.

Usage: pinned Python tests/native_profile_holdout.py NEW_OUTPUT_ROOT
Upstream Search handoff is an explicit stub. Native, artifact import, the
Profile source producer composer, HTTP authorization and H worker are real.
No market endpoint is called. --resume-import reuses only the first retained D
artifact after an importer failure; it never repeats the native D invocation.
"""
import hashlib
import json
import os
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from lab import development_run, holdout_run
from lab import bounded_research as pilot
from lab.backtest_artifact import import_backtest_execution
from lab.database import get_connection
from tests.profile_holdout_fixture import (
    prepared_profile_development, authorized_artificial_holdout, profile_console, canonical,
)
from tests.test_development_console_http import _post
from tests.test_research_console import _request


def main():
    root = Path(sys.argv[1]).resolve()
    resume = sys.argv[2:] == ["--resume-import"]
    if not resume:
        assert len(sys.argv) == 2
        root.mkdir(parents=True, exist_ok=False)
    pinned = Path("/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue-43-profile-driven-v1")
    python, source = pinned / "venv/bin/python", pinned / "freqtrade"
    calls = ([json.loads(line) for line in (root / "native-calls.jsonl").read_text().splitlines()]
             if resume else [])
    lock = threading.Lock()
    def record_call(scenario, evidence):
        with lock:
            if scenario in [row["scenario"] for row in calls]:
                return
            assert len(calls) < 3
            row = {"number": len(calls) + 1, "scenario": scenario,
                   "at_utc": datetime.now(timezone.utc).isoformat(), "evidence": str(evidence),
                   "source": "ARTIFICIAL_ONLY", "retry_allowed": False}
            with (root / "native-calls.jsonl").open("ab") as output:
                output.write(canonical(row)); output.flush(); os.fsync(output.fileno())
            calls.append(row)

    with pytest.MonkeyPatch.context() as patch:
        if resume:
            assert [row["scenario"] for row in calls] == ["DEVELOPMENT"]
            recovery = json.loads((root / "recovery.json").read_bytes())
            database, run_id, run_dir = Path(recovery["database"]), recovery["research_run_id"], Path(recovery["run_dir"])
            assert not (run_dir / "holdout-source-authorization.json").exists()
            assert recovery["native_python"] == str(python) and recovery["native_source"] == str(source)
            assert recovery["source_sha256"] == hashlib.sha256((Path(__file__).parent / "profile_holdout_fixture.py").read_bytes()).hexdigest()
            with get_connection(database, read_only=True) as connection:
                before_run = dict(connection.execute("SELECT * FROM research_runs WHERE id=?", (run_id,)).fetchone())
                before_execution = dict(connection.execute("SELECT * FROM backtest_executions WHERE research_run_id=?", (run_id,)).fetchone())
            snapshot = json.loads(before_run["input_snapshot_json"])
            assert before_run["status"] == "RUNNING" and before_execution["status"] == "PENDING"
            assert snapshot["runner_sha256"] == hashlib.sha256((Path(__file__).resolve().parents[1] / "scripts/run_freqtrade_backtest.py").read_bytes()).hexdigest()
            contract = pilot.profile_search_contract(snapshot["normalized_profile_contract"]["profile_snapshot"], "20260125-20260301", snapshot["timerange"], 20)
            development = development_run.freeze_development_capability(root / "case/capability/pilot", python, source, profile_contract=contract)
            assert development.status == "READY", development.reason
            evidence = run_dir / "development-evidence"
            archive = evidence / "backtest-result-development-01.zip"
            provenance = archive.with_suffix(".provenance.json")
            receipt = {"reason": "Original native D completed; importer rejected spot domain before mutation",
                "native_replayed": False, "before_run": before_run, "before_execution": before_execution,
                "artifact_retention": "Sanitized native report ZIP retained; temporary original export removed by existing executor cleanup",
                "evidence_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in evidence.iterdir() if p.is_file()},
                "importer_sha256": hashlib.sha256((Path(__file__).resolve().parents[1] / "lab/backtest_artifact.py").read_bytes()).hexdigest()}
            receipt_path = root / "import-recovery-receipt.json"
            if receipt_path.exists():
                assert receipt_path.read_bytes() == canonical(receipt)
            else:
                with receipt_path.open("xb") as output:
                    output.write(canonical(receipt))
            import_backtest_execution(database, evidence, Path(archive.name), run_id, "DEVELOPMENT", "BoundedCandidate", "2026.7",
                hashlib.sha256(provenance.read_bytes()).hexdigest(), allow_zero_trades=True, mark_execution_finished=True)
            d = development_run.finalize_development_gate(database, run_id)
        else:
            database, run_id, run_dir, development = prepared_profile_development(
                root / "case", patch, python=python, native_source=source,
            )
            recovery = {"database": str(database), "research_run_id": run_id, "run_dir": str(run_dir),
                        "native_python": str(python), "native_source": str(source),
                        "source_sha256": hashlib.sha256((Path(__file__).parent / "profile_holdout_fixture.py").read_bytes()).hexdigest(),
                        "upstream_search": "TEST_STUB_NOT_RESEARCH", "market_requests": 0}
            recovery["implementation_sha256"] = {
                name: hashlib.sha256((Path(__file__).resolve().parents[1] / name).read_bytes()).hexdigest()
                for name in ("lab/backtest_artifact.py", "lab/holdout_run.py", "lab/research_bundle.py",
                             "lab/research_console.py", "scripts/run_freqtrade_backtest.py",
                             "scripts/fetch_okx_profile_data.py", "tests/native_profile_holdout.py")
            }
            (root / "recovery.json").write_bytes(canonical(recovery))
            record_call("DEVELOPMENT", run_dir / "development-input/manifest.json")
            d = development_run.execute_development_run(database, run_dir, run_id, python, source)
        (root / "development-public.json").write_bytes(canonical(d))
        with get_connection(database, read_only=True) as connection:
            original_snapshot = connection.execute("SELECT input_snapshot_json FROM research_runs WHERE id=?", (run_id,)).fetchone()[0]
            assert connection.execute("SELECT scenario_passed FROM backtest_executions WHERE research_run_id=?", (run_id,)).fetchone()[0] == 1
        authorized_artificial_holdout(database, run_id)
        capability = holdout_run.freeze_profile_holdout_capability(database, run_id, development)
        assert capability.status == "READY", capability.reason

        stop_watch = threading.Event()
        def watch_calls():
            while not stop_watch.is_set():
                for phase, slug, receipt in (("HOLDOUT", "holdout-02", "holdout-open.json"),
                                              ("HOLDOUT_STRESS", "holdout-stress-03", "holdout-stress-open.json")):
                    attempted = run_dir / "holdout-runtime" / slug / "config.json"
                    opened = run_dir / "holdout-receipts" / receipt
                    if attempted.exists() or opened.exists():
                        record_call(phase, opened if opened.exists() else attempted)
                stop_watch.wait(.01)
        watcher = threading.Thread(target=watch_calls, daemon=True)
        watcher.start()
        try:
            with profile_console(database, run_id, run_dir, development, patch) as server:
                status, _, _, initial = _request(server, f"/api/research-runs/{run_id}")
                assert status == 200 and initial["authorization"]["can_authorize"], initial
                status, _, _, public = _post(server, f"/api/research-runs/{run_id}/actions", {"action": "AUTHORIZE_HOLDOUT"})
                (root / "http-authorization.json").write_bytes(canonical({"http_status": status, "body": public}))
                assert status == 202, public
                for _ in range(1800):
                    status, _, _, public = _request(server, f"/api/research-runs/{run_id}")
                    assert status == 200, public
                    if public["status"] in {"COMPLETED", "FAILED", "INTERRUPTED", "CANCELLED"}:
                        break
                    time.sleep(.1)
                (root / "http-terminal.json").write_bytes(canonical(public))
                assert public["status"] == "COMPLETED", public
                assert [row["scenario"] for row in public["executions"]] == ["DEVELOPMENT", "HOLDOUT", "HOLDOUT_STRESS"]
                assert public["manual_review"]["can_pass_and_create_release"] is False
        finally:
            stop_watch.set(); watcher.join(timeout=2)
        with get_connection(database, read_only=True) as connection:
            after = json.loads(connection.execute("SELECT input_snapshot_json FROM research_runs WHERE id=?", (run_id,)).fetchone()[0])
            before = json.loads(original_snapshot)
            assert {key: after[key] for key in before} == before
            rows = [dict(row) for row in connection.execute(
                "SELECT scenario,status,timeframe,fee_rate,result_archive_path FROM backtest_executions WHERE research_run_id=? ORDER BY sequence", (run_id,))]
            assert all(row["status"] == "SUCCEEDED" and row["timeframe"] == "1d" for row in rows)
            assert [row["fee_rate"] for row in rows] == [.0005, .0005, .001]
            assert connection.execute("SELECT COUNT(*) FROM releases").fetchone()[0] == 0
        assert [row["scenario"] for row in calls] == ["DEVELOPMENT", "HOLDOUT", "HOLDOUT_STRESS"]
        (root / "batch-result.json").write_bytes(canonical({"status": "SYNTHETIC_NATIVE_PASS", "calls": calls,
            "executions": rows, "development_snapshot_preserved": True, "market_requests": 0,
            "profitability_evidence": False, "real_search": 0}))
        print(json.dumps({"status": "SYNTHETIC_NATIVE_PASS", **recovery, "native_calls": len(calls)}))


if __name__ == "__main__":
    main()
