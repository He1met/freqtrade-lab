"""T2 synthetic execution and atomic Holdout/Stress attachment contracts."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import shutil
import subprocess
import threading
import time
import zipfile
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterator, Mapping, Optional

import pytest

from lab import (
    backtest_artifact,
    development_run,
    holdout_run,
    research_candidate,
    research_console,
)
from lab.database import get_connection
from lab.research_candidate import SCENARIO_TIMEOUT_SECONDS
from scripts import run_freqtrade_backtest as runner_module
from tests.test_development_console_http import _post, _request
from tests.test_development_run import NOW
from tests.test_holdout_run import (
    _eligible_run,
    _execution_rows,
    _prepare_continuation,
)


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "freqtrade_2026_7"
NATIVE_FIXTURES = {
    "DEVELOPMENT": "backtest-result-2026-08-30_12-55-02.zip",
    "HOLDOUT": "backtest-result-2026-08-30_06-43-00.zip",
    "HOLDOUT_STRESS": "backtest-result-2026-08-30_06-43-22.zip",
}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def _file_receipt(path: Path, role: Optional[str] = None) -> dict[str, Any]:
    data = path.read_bytes()
    receipt: dict[str, Any] = {"bytes": len(data), "sha256": _sha256(data)}
    if role is not None:
        receipt["role"] = role
    return receipt


def _input_receipts(provenance: Mapping[str, Any]) -> dict[str, Any]:
    contract = provenance["contract"]
    local = provenance["local_only_files"]
    prefix = str(contract.get("data_dir", "data/okx")) + "/"
    data = {
        name.removeprefix(prefix): record["sha256"]
        for name, record in local.items()
        if name.startswith(prefix)
    }
    return {
        "market_snapshot_sha256": local[contract["market_snapshot"]]["sha256"],
        "leverage_tiers_sha256": local[contract["leverage_tiers"]]["sha256"],
        "data_sha256": data,
    }


def _write_native_export(
    *,
    scenario: str,
    config_path: Path,
    strategy_file: Path,
    strategy: str,
    timerange: str,
    fee: float,
    export_dir: Path,
) -> int:
    """Emit one native-looking ZIP/meta pair at the fake Freqtrade boundary."""
    fixture = FIXTURE_ROOT / NATIVE_FIXTURES[scenario]
    with zipfile.ZipFile(fixture) as unit:
        report_member = next(
            name
            for name in unit.namelist()
            if name.endswith(".json") and not name.endswith("_config.json")
        )
        report = json.loads(unit.read(report_member))

    original = report["strategy"].pop("StrategyTestV3Futures")
    start_text, stop_text = timerange.split("-", 1)
    start = datetime.strptime(start_text, "%Y%m%d").replace(tzinfo=timezone.utc)
    stop = datetime.strptime(stop_text, "%Y%m%d").replace(tzinfo=timezone.utc)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    timeframe = config["timeframe"]
    end = stop - (timedelta(minutes=5) if timeframe == "5m" else timedelta(days=1))
    pair = config["exchange"]["pair_whitelist"][0]
    trades = json.loads(json.dumps(original["trades"]))
    if scenario == "DEVELOPMENT":
        trades = [
            json.loads(json.dumps(trades[index % len(trades)]))
            for index in range(30)
        ]
    for trade in trades:
        trade["pair"] = pair
        trade["fee_open"] = fee
        trade["fee_close"] = fee
    original.update(
        {
            "strategy_name": strategy,
            "timeframe": timeframe,
            "timerange": timerange,
            "backtest_start": start.strftime("%Y-%m-%d %H:%M:%S"),
            "backtest_end": end.strftime("%Y-%m-%d %H:%M:%S"),
            "backtest_start_ts": int(start.timestamp() * 1000),
            "backtest_end_ts": int(end.timestamp() * 1000),
            "pairlist": [pair],
            "trades": trades,
            "total_trades": len(trades),
        }
    )
    if scenario == "DEVELOPMENT":
        original.update(
            {
                "wins": 20,
                "draws": 0,
                "losses": 10,
                "profit_total": 0.005,
                "max_drawdown_account": 0.05,
                "winrate": 2.0 / 3.0,
                "profit_factor": 1.1,
                "profit_total_long": 0.004,
                "profit_total_short": 0.001,
            }
        )
    report["strategy"] = {strategy: original}
    for comparison in report.get("strategy_comparison", []):
        comparison["key"] = strategy
        comparison["trades"] = len(trades)
        comparison["wins"] = original["wins"]
        comparison["draws"] = original["draws"]
        comparison["losses"] = original["losses"]

    slug = scenario.lower().replace("_", "-")
    stem = f"backtest-result-native-{slug}"
    archive = export_dir / f"{stem}.zip"
    metadata = export_dir / f"{stem}.meta.json"
    archive.write_bytes(
        research_candidate._zip_bytes(
            (
                (f"{stem}.json", _canonical(report)),
                (f"{stem}_config.json", config_path.read_bytes()),
                (f"{stem}_{strategy}.py", strategy_file.read_bytes()),
            )
        )
    )
    metadata.write_bytes(
        _canonical(
            {
                strategy: {
                    "run_id": f"TEST_ONLY_SYNTHETIC_{scenario}",
                    "backtest_start_time": int(start.timestamp()),
                    "timeframe": timeframe,
                    "timeframe_detail": None,
                    "backtest_start_ts": int(start.timestamp()),
                    "backtest_end_ts": int(end.timestamp()),
                }
            }
        )
    )
    return len(trades)


class _NativeFakeFreqtrade:
    """Fake only Freqtrade's outer command; producer/sanitizer/parser stay real."""

    def __init__(self) -> None:
        self.scenarios: list[str] = []

    def __call__(
        self, command: list[str], **kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
        assert kwargs["check"] is False
        assert kwargs["capture_output"] is True
        assert kwargs["text"] is True
        assert kwargs["timeout"] == SCENARIO_TIMEOUT_SECONDS
        scenario = command[command.index("--scenario") + 1]
        self.scenarios.append(scenario)
        timerange = command[command.index("--timerange") + 1]
        strategy = command[command.index("--strategy") + 1]
        strategy_sha256 = command[command.index("--strategy-sha256") + 1]
        fee = float(command[command.index("--fee") + 1])
        provenance_path = Path(
            command[command.index("--data-provenance") + 1]
        )
        provenance_bytes = provenance_path.read_bytes()
        provenance = json.loads(provenance_bytes)
        receipts = _input_receipts(provenance)
        stop = datetime.strptime(timerange.split("-", 1)[1], "%Y%m%d").replace(
            tzinfo=timezone.utc
        )
        exclusive_stop = stop.isoformat().replace("+00:00", "Z")
        if "--scenario-open-receipt" in command:
            receipt = Path(
                command[command.index("--scenario-open-receipt") + 1]
            )
            receipt.write_bytes(
                _canonical(
                    {
                        "schema": "freqtrade-lab-scenario-open-v1",
                        "scenario": scenario,
                        "timerange": timerange,
                        "strategy": strategy,
                        "strategy_sha256": strategy_sha256,
                        "data_provenance_sha256": _sha256(provenance_bytes),
                        "exclusive_stop_utc": exclusive_stop,
                        "meaning": (
                            "one-shot scenario execution budget was consumed before "
                            "retained market data validation began"
                        ),
                        "opened_at_utc": NOW,
                    }
                )
            )
        export_dir = Path(command[command.index("--export-dir") + 1])
        total_trades = _write_native_export(
            scenario=scenario,
            config_path=Path(command[command.index("--config") + 1]),
            strategy_file=Path(command[command.index("--strategy-file") + 1]),
            strategy=strategy,
            timerange=timerange,
            fee=fee,
            export_dir=export_dir,
        )
        archive = next(export_dir.glob("backtest-result-*.zip"))
        metadata = export_dir / f"{archive.stem}.meta.json"
        summary = {
            "scenario": scenario,
            "archive": archive.name,
            "metadata": metadata.name,
            "total_trades": total_trades,
            "dependencies": {
                "freqtrade": holdout_run.SUPPORTED_FREQTRADE_VERSION,
                **holdout_run.SUPPORTED_DEPENDENCIES,
            },
            "official_core": holdout_run.SUPPORTED_OFFICIAL_CORE,
            "freqtrade_commit": backtest_artifact.SUPPORTED_FREQTRADE_COMMIT,
            "source_tree_sha256": command[
                command.index("--source-tree-sha256") + 1
            ],
            "runner_sha256": command[command.index("--runner-sha256") + 1],
            "data_provenance_sha256": _sha256(provenance_bytes),
            "input_receipts": receipts,
            "scenario_data_view": {
                "exclusive_stop_utc": exclusive_stop,
                "files": {
                    name: {"rows": 1, "sha256": digest}
                    for name, digest in receipts["data_sha256"].items()
                },
            },
        }
        return subprocess.CompletedProcess(
            command, 0, json.dumps(summary, separators=(",", ":")) + "\n", ""
        )


def _fake_verified_python(root: Path) -> Path:
    python = root / "fake-freqtrade-venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    expected = {
        "freqtrade": holdout_run.SUPPORTED_FREQTRADE_VERSION,
        **holdout_run.SUPPORTED_DEPENDENCIES,
    }
    python.write_text(
        "#!/bin/sh\nprintf '%s\\n' '"
        + json.dumps(expected, sort_keys=True, separators=(",", ":"))
        + "'\n",
        encoding="utf-8",
    )
    python.chmod(0o700)
    (python.parent.parent / "pyvenv.cfg").write_text(
        "home = /test\n", encoding="utf-8"
    )
    (
        python.parent.parent / "lib" / "python3.13" / "site-packages"
    ).mkdir(parents=True)
    return python


def _upgrade_pilot_contract(
    pilot: Path,
    fake_python: Path,
    source: Path,
) -> holdout_run.FrozenHoldoutCapability:
    plan_path = pilot / "pilot-spec.json"
    plan = json.loads(plan_path.read_text())
    plan.update(
        {
            "holdout_timerange": "20260731-20260830",
            "stress_fee_multiplier": 2.0,
            "holdout_policy": {
                "max_open_count": 1,
                "retry_after_open": False,
                "tune_after_result": False,
            },
        }
    )
    plan_path.write_bytes(_canonical(plan))

    acquisition = pilot / "acquisition"
    data = acquisition / "data" / "okx" / "futures" / "XRP-5m.feather"
    market = acquisition / "market_snapshot.json"
    tiers = acquisition / "isolated_tiers_snapshot.json"
    config = acquisition / "config.json"
    provenance = {
        "schema": "freqtrade-lab-retained-okx-data-v1",
        "portable_retained_fixture": "BLOCKED_LICENSE",
        "source": {
            "host": "www.okx.com",
            "authentication": "none",
            "pair": "XRP/USDT:USDT",
            "instrument_id": "XRP-USDT-SWAP",
        },
        "contract": {
            "config": "config.json",
            "development_timerange": "20260601-20260731",
            "holdout_timerange": "20260731-20260830",
            "timeframe": "5m",
        },
        "files": {"config.json": _file_receipt(config)},
        "local_only_files": {
            "market_snapshot.json": _file_receipt(market, "market_snapshot"),
            "isolated_tiers_snapshot.json": _file_receipt(
                tiers, "leverage_tiers"
            ),
            "data/okx/futures/XRP-5m.feather": _file_receipt(data, "ohlcv"),
        },
    }
    provenance_bytes = _canonical(provenance)
    (acquisition / "retained-data-provenance.json").write_bytes(
        provenance_bytes
    )
    isolation_path = pilot / "development-isolation" / "retained-data-provenance.json"
    isolation = json.loads(isolation_path.read_text())
    isolation["development_isolation"]["source_provenance_sha256"] = _sha256(
        provenance_bytes
    )
    isolation_path.write_bytes(_canonical(isolation))

    development = development_run.freeze_development_capability(
        pilot, fake_python, source
    )
    assert development.status == "READY", development.reason
    capability = holdout_run.freeze_holdout_capability(
        pilot, fake_python, source
    )
    assert capability.status == "READY", capability.reason
    return capability


def _rebind_frozen_snapshot(
    database: Path,
    research_run_id: str,
    run_dir: Path,
    capability: holdout_run.FrozenHoldoutCapability,
) -> None:
    assert capability.development is not None
    input_root = run_dir / "development-input"
    provenance_path = input_root / "retained-data-provenance.json"
    manifest_path = input_root / "manifest.json"
    input_root.chmod(0o700)
    provenance_path.chmod(0o600)
    manifest_path.chmod(0o600)
    provenance = json.loads(provenance_path.read_text())
    provenance["development_isolation"]["source_provenance_sha256"] = (
        capability.development.source_provenance_sha256
    )
    provenance_path.write_bytes(_canonical(provenance))
    manifest = json.loads(manifest_path.read_text())
    hashes = dict(manifest["input_hashes"])
    hashes["retained-data-provenance.json"] = _sha256(
        provenance_path.read_bytes()
    )
    with get_connection(database) as connection:
        connection.execute("BEGIN")
        run = connection.execute(
            "SELECT candidate_id,input_snapshot_json FROM research_runs WHERE id=?",
            (research_run_id,),
        ).fetchone()
        candidate = development_run._bound_candidate(
            connection, str(run["candidate_id"])
        )
        snapshot = development_run._snapshot(capability.development, candidate)
        snapshot["materialized_input_hashes"] = dict(sorted(hashes.items()))
        manifest["input_hashes"] = snapshot["materialized_input_hashes"]
        manifest["snapshot"] = snapshot
        manifest_path.write_bytes(_canonical(manifest))
        connection.execute(
            "UPDATE research_runs SET run_dir=?,input_snapshot_json=? WHERE id=?",
            (
                str(run_dir),
                json.dumps(snapshot, sort_keys=True, separators=(",", ":")),
                research_run_id,
            ),
        )
        connection.execute(
            """
            UPDATE backtest_executions
            SET config_path=?,strategy_path=?
            WHERE research_run_id=? AND scenario='DEVELOPMENT'
            """,
            (
                str(input_root / "config.json"),
                str(input_root / "strategies" / "BoundedCandidate.py"),
                research_run_id,
            ),
        )
        connection.commit()
    provenance_path.chmod(0o400)
    manifest_path.chmod(0o400)
    input_root.chmod(0o500)


def _seed_real_development_artifact(
    database: Path,
    research_run_id: str,
    run_dir: Path,
) -> backtest_artifact.ParsedBacktestArtifact:
    input_root = run_dir / "development-input"
    evidence = run_dir / "development-evidence"
    for child in evidence.iterdir():
        child.unlink()
    staging = run_dir / "t2-development-staging"
    raw = staging / "raw"
    user_data = staging / "user_data"
    home = staging / "home"
    for directory in (raw, user_data, home / "tmp"):
        directory.mkdir(parents=True)
    config_source = input_root / "config.json"
    strategy_file = input_root / "strategies" / "BoundedCandidate.py"
    provenance_path = input_root / "retained-data-provenance.json"
    runtime_config = staging / "config.json"
    runtime_config.write_bytes(
        research_candidate._canonical_bytes(
            research_candidate._runtime_config(
                json.loads(config_source.read_text()),
                config_source=config_source,
                data_dir=input_root / "data" / "okx",
                user_data_dir=user_data,
                strategy_path=strategy_file.parent,
                strategy="BoundedCandidate",
                timerange="20260601-20260731",
                fee=0.0005,
                export_dir=raw,
            )
        )
    )
    runner_sha = _sha256(holdout_run.DEFAULT_RUNNER.read_bytes())
    provenance_bytes = provenance_path.read_bytes()
    provenance = json.loads(provenance_bytes)
    fake = _NativeFakeFreqtrade()
    command = [
        "TEST_ONLY_SYNTHETIC_FREQTRADE",
        "--scenario",
        "DEVELOPMENT",
        "--timerange",
        "20260601-20260731",
        "--strategy",
        "BoundedCandidate",
        "--strategy-sha256",
        _sha256(strategy_file.read_bytes()),
        "--fee",
        "0.0005",
        "--config",
        str(runtime_config),
        "--strategy-file",
        str(strategy_file),
        "--export-dir",
        str(raw),
        "--data-provenance",
        str(provenance_path),
        "--source-tree-sha256",
        "0" * 64,
        "--runner-sha256",
        runner_sha,
    ]
    completed = fake(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=SCENARIO_TIMEOUT_SECONDS,
    )
    summary = json.loads(completed.stdout)
    producer_bytes = holdout_run.__file__.encode("utf-8")
    produced = research_candidate._sanitize_raw_artifact(
        scenario="DEVELOPMENT",
        slug="development-01",
        raw_dir=raw,
        runner_summary=summary,
        completed=completed,
        command_shape=("TEST_ONLY_SYNTHETIC_FREQTRADE", "DEVELOPMENT"),
        bundle_dir=evidence,
        strategy="BoundedCandidate",
        strategy_source=strategy_file.read_bytes(),
        data_provenance=provenance,
        data_provenance_sha256=_sha256(provenance_bytes),
        expected_input_receipts=_input_receipts(provenance),
        source_tree_sha256="0" * 64,
        implementation_receipts={
            "producer": {
                "bytes": len(producer_bytes),
                "sha256": _sha256(producer_bytes),
            },
            "runner": {
                "bytes": len(holdout_run.DEFAULT_RUNNER.read_bytes()),
                "sha256": runner_sha,
            },
        },
        timerange="20260601-20260731",
        network_policy="test outer Freqtrade only; no economic evidence",
    )
    parsed = backtest_artifact.parse_backtest_artifact(
        evidence,
        produced.archive,
        "BoundedCandidate",
        holdout_run.SUPPORTED_FREQTRADE_VERSION,
        produced.provenance_sha256,
    )
    values = backtest_artifact.execution_result_values(parsed)
    with get_connection(database) as connection:
        changed = connection.execute(
            """
            UPDATE backtest_executions
            SET status='SUCCEEDED',result_archive_path=:result_archive_path,
                stdout_path=NULL,stderr_path=NULL,return_code=0,
                total_trades=:total_trades,profit_pct=:profit_pct,
                max_drawdown_pct=:max_drawdown_pct,win_rate=:win_rate,
                profit_factor=:profit_factor,sharpe=:sharpe,sortino=:sortino,
                calmar=:calmar,long_profit_pct=:long_profit_pct,
                short_profit_pct=:short_profit_pct,metrics_json=:metrics_json,
                scenario_passed=1,error_message=NULL,finished_at=:finished_at
            WHERE research_run_id=:research_run_id AND scenario='DEVELOPMENT'
            """,
            {
                **values,
                "finished_at": NOW,
                "research_run_id": research_run_id,
            },
        ).rowcount
        assert changed == 1
        connection.commit()
    shutil.rmtree(staging)
    return parsed


def _real_t2_eligible_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[
    Path,
    str,
    Path,
    Path,
    holdout_run.FrozenHoldoutCapability,
    backtest_artifact.ParsedBacktestArtifact,
]:
    database, research_run_id, original_dir, old_capability, _ = _eligible_run(
        tmp_path / "seed", monkeypatch
    )
    runtime_root = tmp_path / "console-runtime"
    campaigns = runtime_root / "campaigns"
    campaigns.mkdir(parents=True)
    run_dir = campaigns / research_run_id
    shutil.move(str(original_dir), run_dir)
    fake_python = _fake_verified_python(tmp_path)
    assert old_capability.pilot_root is not None
    assert old_capability.freqtrade_source is not None
    capability = _upgrade_pilot_contract(
        old_capability.pilot_root,
        fake_python,
        old_capability.freqtrade_source,
    )
    _rebind_frozen_snapshot(database, research_run_id, run_dir, capability)
    development = _seed_real_development_artifact(
        database, research_run_id, run_dir
    )
    return (
        database,
        research_run_id,
        runtime_root,
        run_dir,
        capability,
        development,
    )


class _InlineWorkerProcess:
    """Exercise the production worker core behind the controller's process seam."""

    pid = 2_000_000_034

    def __init__(
        self,
        argv: tuple[str, ...],
        runner: _NativeFakeFreqtrade,
        errors: list[BaseException],
    ) -> None:
        self.argv = argv
        self.runner = runner
        self.errors = errors
        self.returncode: Optional[int] = None
        self._lock = threading.Lock()

    def poll(self) -> Optional[int]:
        with self._lock:
            if self.returncode is not None:
                return self.returncode
            try:
                holdout_run.execute_holdout_continuation(
                    self.argv[self.argv.index("--database") + 1],
                    self.argv[self.argv.index("--run-dir") + 1],
                    self.argv[self.argv.index("--research-run-id") + 1],
                    self.argv[self.argv.index("--freqtrade-python") + 1],
                    self.argv[self.argv.index("--freqtrade-source") + 1],
                    command_runner=self.runner,
                )
            except BaseException as exc:  # pragma: no branch - asserted by caller
                self.errors.append(exc)
                self.returncode = 2
            else:
                self.returncode = 0
            return self.returncode

    def wait(self, timeout: Optional[float] = None) -> int:
        del timeout
        result = self.poll()
        assert result is not None
        return result


@contextmanager
def _serve_real_t2(
    database: Path,
    runtime_root: Path,
    run_dir: Path,
    capability: holdout_run.FrozenHoldoutCapability,
    tmp_path: Path,
) -> Iterator[Any]:
    server = research_console.create_research_console_server(
        database,
        runtime_root,
        capability.pilot_root,
        0,
        artifact_root=run_dir,
        codex_binary=tmp_path / "missing-codex",
        freqtrade_python=capability.freqtrade_python,
        freqtrade_source=capability.freqtrade_source,
        task_timeout_seconds=5,
    )
    assert server.research_console_controller._holdout_capability.status == "READY"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.research_console_controller.shutdown()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_t2_http_controller_worker_parser_sqlite_and_library_chain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        database,
        research_run_id,
        runtime_root,
        run_dir,
        capability,
        development,
    ) = _real_t2_eligible_run(tmp_path, monkeypatch)
    runner = _NativeFakeFreqtrade()
    worker_errors: list[BaseException] = []
    worker_argv: list[tuple[str, ...]] = []
    original_popen = subprocess.Popen

    def routed_popen(argv: Any, **kwargs: Any) -> Any:
        normalized = tuple(str(value) for value in argv)
        if len(normalized) > 1 and normalized[1].endswith(
            "scripts/run_holdout_continuation.py"
        ):
            assert kwargs["shell"] is False
            assert kwargs["start_new_session"] is True
            assert kwargs["close_fds"] is True
            worker_argv.append(normalized)
            return _InlineWorkerProcess(normalized, runner, worker_errors)
        return original_popen(argv, **kwargs)

    monkeypatch.setattr(research_console.subprocess, "Popen", routed_popen)
    with _serve_real_t2(
        database, runtime_root, run_dir, capability, tmp_path
    ) as server:
        status, _, _, authorized = _post(
            server,
            f"/api/research-runs/{research_run_id}/actions",
            {"action": "AUTHORIZE_HOLDOUT"},
        )
        assert status == 202, authorized
        public: Mapping[str, Any] = authorized
        for _ in range(300):
            status, _, _, public = _request(
                server, f"/api/research-runs/{research_run_id}"
            )
            assert status == 200, public
            if public["status"] in {
                "COMPLETED",
                "FAILED",
                "CANCELLED",
                "INTERRUPTED",
            }:
                break
            time.sleep(0.01)
        assert worker_errors == []
        assert runner.scenarios == ["HOLDOUT", "HOLDOUT_STRESS"]
        assert len(worker_argv) == 1
        assert (public["status"], public["stage"], public["verdict"]) == (
            "COMPLETED",
            "COMPLETED",
            None,
        )
        assert public["manual_review"]["status"] == "AVAILABLE", public[
            "manual_review"
        ]
        assert public["manual_review"]["can_reject"] is True
        assert public["manual_review"]["can_pass_and_create_release"] is True

        reject_database = tmp_path / "reject-lab.sqlite"
        with get_connection(database, read_only=True) as source, sqlite3.connect(
            reject_database
        ) as destination:
            source.backup(destination)
        reject_runtime = tmp_path / "reject-console-runtime"
        (reject_runtime / "campaigns").mkdir(parents=True)
        with _serve_real_t2(
            reject_database,
            reject_runtime,
            run_dir,
            capability,
            tmp_path,
        ) as reject_server:
            status, _, _, rejected = _post(
                reject_server,
                f"/api/research-runs/{research_run_id}/actions",
                {
                    "action": "REJECT",
                    "reason": "隔离 T2：人工决定终止该假设。",
                },
            )
            assert status == 200, rejected
            assert rejected["verdict"] == "REJECTED"
            assert rejected["release_count"] == 0
            assert rejected["manual_review"]["status"] == "REJECTED"
        with get_connection(reject_database, read_only=True) as connection:
            assert connection.execute(
                "SELECT COUNT(*) FROM releases WHERE research_run_id=?",
                (research_run_id,),
            ).fetchone()[0] == 0
        assert list((reject_runtime / "releases").iterdir()) == []

        status, _, _, illegal = _post(
            server,
            f"/api/research-runs/{research_run_id}/actions",
            {
                "action": "PASS_AND_CREATE_RELEASE",
                "reason": "人工经济复核通过",
                "release_root": str(tmp_path / "browser-must-not-control"),
            },
        )
        assert status == 400
        assert illegal["error"] == "invalid_action"
        with get_connection(database, read_only=True) as connection:
            assert connection.execute(
                "SELECT verdict FROM research_runs WHERE id=?", (research_run_id,)
            ).fetchone()[0] is None

        status, _, _, public = _post(
            server,
            f"/api/research-runs/{research_run_id}/actions",
            {
                "action": "PASS_AND_CREATE_RELEASE",
                "reason": "人工经济复核通过；仅生成 dry-run handoff，不执行。",
            },
        )
        assert status == 200, public
        assert public["verdict"] == "PASSED"
        assert public["release_count"] == 1
        review = public["manual_review"]
        assert review["status"] == "PASSED"
        assert review["reason"].startswith("人工经济复核通过")
        release = review["release"]
        assert release["dry_run_handoff"]["status"] == "NOT_EXECUTED"
        assert release["dry_run_handoff"]["command"].startswith(
            "freqtrade trade --dry-run"
        )
        release_root = runtime_root / "releases"
        release_dirs = list(release_root.iterdir())
        assert len(release_dirs) == 1
        release_dir = release_dirs[0]
        assert (release_dir / "strategies" / "BoundedCandidate.py").is_file()
        manifest_bytes = (release_dir / "manifest.json").read_bytes()
        assert hashlib.sha256(manifest_bytes).hexdigest() == release["manifest_sha256"]
        assert json.loads(manifest_bytes)["research_run_id"] == research_run_id
        assert len(worker_argv) == 1

        detail_url = public["strategy_detail_url"]
        assert detail_url.endswith(f"research_run_id={research_run_id}")
        status, _, page, _ = _request(server, detail_url)
        assert status == 200
        page_text = page.decode("utf-8")
        assert "SUCCEEDED 只表示 Artifact 已验证落库" in page_text
        assert ">PASSED<" in page_text
        assert release["id"] in page_text
        assert str(run_dir) not in page_text
        assert "result_archive_path" not in page_text

        api_url = detail_url.replace("/strategy?", "/api/strategy?", 1)
        status, _, _, detail = _request(server, api_url)
        assert status == 200
        selected = detail["selected_run"]
        assert (
            selected["research_run_id"],
            selected["status"],
            selected["stage"],
            selected["verdict"],
            selected["scenario_count"],
            selected["succeeded_count"],
        ) == (research_run_id, "COMPLETED", "COMPLETED", "PASSED", 3, 3)
        assert detail["manual_review"]["release"]["id"] == release["id"]
        assert [item["scenario"] for item in detail["scenarios"]] == [
            "DEVELOPMENT",
            "HOLDOUT",
            "HOLDOUT_STRESS",
        ]
        assert [item["status"] for item in detail["scenarios"]] == [
            "SUCCEEDED",
            "SUCCEEDED",
            "SUCCEEDED",
        ]
        assert detail["scenarios"][0]["scenario_passed"] == 1
        assert [
            item["scenario_passed"] for item in detail["scenarios"][1:]
        ] == [None, None]
        assert all(item["download"]["available"] for item in detail["scenarios"])

    rows = _execution_rows(database, research_run_id)
    assert {row["research_run_id"] for row in rows} == {research_run_id}
    assert [(row["scenario"], row["status"]) for row in rows] == [
        ("DEVELOPMENT", "SUCCEEDED"),
        ("HOLDOUT", "SUCCEEDED"),
        ("HOLDOUT_STRESS", "SUCCEEDED"),
    ]
    assert rows[0]["result_archive_path"] == str(development.archive_path)
    assert [row["scenario_passed"] for row in rows] == [1, None, None]
    holdout_provenance = json.loads(
        (run_dir / "holdout-input" / "retained-data-provenance.json").read_text()
    )
    holdout_market = json.loads(
        (run_dir / "holdout-input" / "market_snapshot.json").read_text()
    )
    assert holdout_provenance["source"] == {
        "host": "www.okx.com",
        "authentication": "none",
        "pair": "XRP/USDT:USDT",
        "instrument_id": "XRP-USDT-SWAP",
    }
    assert holdout_market["id"] == holdout_provenance["source"]["instrument_id"]
    assert holdout_market["symbol"] == holdout_provenance["source"]["pair"]
    verified_market, verified_tiers = runner_module._verify_market_inputs(
        holdout_market,
        json.loads(
            (
                run_dir
                / "holdout-input"
                / "isolated_tiers_snapshot.json"
            ).read_text()
        ),
        pair="XRP/USDT:USDT",
        provenance=holdout_provenance,
    )
    assert verified_market["id"] == "XRP-USDT-SWAP"
    assert verified_tiers[0]["symbol"] == "XRP/USDT:USDT"
    with get_connection(database, read_only=True) as connection:
        run = connection.execute(
            "SELECT status,stage,verdict,checks_json FROM research_runs WHERE id=?",
            (research_run_id,),
        ).fetchone()
        releases = connection.execute(
            "SELECT COUNT(*) FROM releases WHERE research_run_id=?",
            (research_run_id,),
        ).fetchone()[0]
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_schema "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
    assert (run["status"], run["stage"], run["verdict"]) == (
        "COMPLETED",
        "COMPLETED",
        "PASSED",
    )
    checks = json.loads(run["checks_json"])
    assert checks["next_phase"] == "MANUAL_DRY_RUN_HANDOFF"
    assert checks["judge"] == "HUMAN"
    assert releases == 1
    assert tables == {
        "research_profiles",
        "generation_runs",
        "candidates",
        "research_runs",
        "backtest_executions",
        "releases",
    }
    schema = Path(__file__).parents[1] / "sql" / "schema_v1.sql"
    schema_bytes = schema.read_bytes()
    schema_blob = hashlib.sha1(
        f"blob {len(schema_bytes)}\0".encode("ascii") + schema_bytes,
        usedforsecurity=False,
    ).hexdigest()
    assert schema_blob == "2447bf90447a333a703e208a4ec6503fb7c5112b"


class _FakeLaterCommandRunner:
    """Consume only the two later scenario commands and write real open receipts."""

    def __init__(self) -> None:
        self.scenarios: list[str] = []

    def __call__(
        self, command: list[str], **kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
        assert kwargs["check"] is False
        assert kwargs["capture_output"] is True
        assert kwargs["text"] is True
        assert kwargs["timeout"] == SCENARIO_TIMEOUT_SECONDS

        scenario = command[command.index("--scenario") + 1]
        assert scenario in {"HOLDOUT", "HOLDOUT_STRESS"}
        self.scenarios.append(scenario)

        timerange = command[command.index("--timerange") + 1]
        strategy = command[command.index("--strategy") + 1]
        strategy_sha256 = command[command.index("--strategy-sha256") + 1]
        provenance_path = Path(
            command[command.index("--data-provenance") + 1]
        )
        provenance_sha256 = _sha256(provenance_path.read_bytes())
        stop = datetime.strptime(timerange.split("-", 1)[1], "%Y%m%d").replace(
            tzinfo=timezone.utc
        )
        exclusive_stop = stop.isoformat().replace("+00:00", "Z")
        open_receipt = Path(
            command[command.index("--scenario-open-receipt") + 1]
        )
        open_receipt.write_bytes(
            _canonical(
                {
                    "schema": "freqtrade-lab-scenario-open-v1",
                    "scenario": scenario,
                    "timerange": timerange,
                    "strategy": strategy,
                    "strategy_sha256": strategy_sha256,
                    "data_provenance_sha256": provenance_sha256,
                    "exclusive_stop_utc": exclusive_stop,
                    "meaning": (
                        "one-shot scenario execution budget was consumed before "
                        "retained market data validation began"
                    ),
                    "opened_at_utc": NOW,
                }
            )
        )
        summary = {
            "scenario_data_view": {
                "exclusive_stop_utc": exclusive_stop,
                "files": {"TEST_ONLY_SYNTHETIC": {"rows": 1}},
            }
        }
        return subprocess.CompletedProcess(
            command, 0, json.dumps(summary, separators=(",", ":")) + "\n", ""
        )


def _install_synthetic_sanitizer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep the producer/finalizer boundary real while replacing Freqtrade bytes."""

    def fake_sanitize_raw_artifact(**kwargs: Any) -> SimpleNamespace:
        scenario = str(kwargs["scenario"])
        stem = f"backtest-result-{kwargs['slug']}"
        bundle_dir = Path(kwargs["bundle_dir"])
        archive = bundle_dir / f"{stem}.zip"
        metadata = bundle_dir / f"{stem}.meta.json"
        provenance = bundle_dir / f"{stem}.provenance.json"
        archive.write_bytes(f"TEST_ONLY_SYNTHETIC {scenario}\n".encode("ascii"))
        metadata.write_bytes(_canonical({"test_only_synthetic": scenario}))
        provenance_bytes = _canonical(
            {
                "test_only_synthetic": True,
                "acquisition": {
                    "retained_data_provenance_sha256": kwargs[
                        "data_provenance_sha256"
                    ]
                },
                "freqtrade": {
                    "source_tree_sha256": kwargs["source_tree_sha256"],
                    "dependencies": {
                        "freqtrade": holdout_run.SUPPORTED_FREQTRADE_VERSION,
                        **holdout_run.SUPPORTED_DEPENDENCIES,
                    },
                },
                "generation": {
                    "scenario": scenario,
                    "return_code": kwargs["completed"].returncode,
                    "official_core": holdout_run.SUPPORTED_OFFICIAL_CORE,
                    "scenario_data_view": kwargs["runner_summary"][
                        "scenario_data_view"
                    ],
                    "implementation_receipts": kwargs[
                        "implementation_receipts"
                    ],
                },
            }
        )
        provenance.write_bytes(provenance_bytes)
        return SimpleNamespace(
            scenario=scenario,
            archive=archive.name,
            archive_sha256=_sha256(archive.read_bytes()),
            provenance_sha256=_sha256(provenance_bytes),
        )

    monkeypatch.setattr(
        holdout_run, "_sanitize_raw_artifact", fake_sanitize_raw_artifact
    )


def _later_artifacts(
    run_dir: Path,
    development: backtest_artifact.ParsedBacktestArtifact,
) -> dict[str, backtest_artifact.ParsedBacktestArtifact]:
    result = json.loads((run_dir / holdout_run.HOLDOUT_RESULT_NAME).read_text())
    records = {record["scenario"]: record for record in result["artifacts"]}
    evidence = run_dir / "holdout-evidence"
    artifacts: dict[str, backtest_artifact.ParsedBacktestArtifact] = {}
    for scenario, fee in (
        ("HOLDOUT", development.configured_fee),
        ("HOLDOUT_STRESS", development.configured_fee * 2.0),
    ):
        record = records[scenario]
        archive = evidence / record["archive"]
        stem = archive.stem
        metadata = evidence / f"{stem}.meta.json"
        artifacts[scenario] = replace(
            development,
            archive_path=archive,
            archive_sha256=record["archive_sha256"],
            metadata_sha256=_sha256(metadata.read_bytes()),
            provenance_sha256=record["provenance_sha256"],
            report_member=f"{stem}.json",
            config_member=f"{stem}_config.json",
            strategy_member=f"{stem}_{development.strategy}.py",
            report_sha256=_sha256(f"report:{scenario}".encode("ascii")),
            config_sha256=_sha256(f"config:{scenario}".encode("ascii")),
            backtest_start="2026-07-31T00:00:00Z",
            backtest_end="2026-08-29T23:55:00Z",
            configured_fee=fee,
            total_trades=31,
            wins=20,
            draws=0,
            losses=11,
        )
    return artifacts


def _install_artifact_parser(
    monkeypatch: pytest.MonkeyPatch,
    development: backtest_artifact.ParsedBacktestArtifact,
    later: dict[str, backtest_artifact.ParsedBacktestArtifact],
) -> None:
    by_name = {
        development.archive_path.name: development,
        **{artifact.archive_path.name: artifact for artifact in later.values()},
    }

    def fake_parse(
        _root: Path,
        archive: Path,
        strategy: str,
        version: str,
        expected_provenance_sha256: str,
        **_kwargs: Any,
    ) -> backtest_artifact.ParsedBacktestArtifact:
        parsed = by_name[Path(archive).name]
        assert parsed.strategy == strategy
        assert parsed.freqtrade_version == version
        assert parsed.provenance_sha256 == expected_provenance_sha256
        return parsed

    monkeypatch.setattr(holdout_run, "parse_backtest_artifact", fake_parse)


def _execute_synthetic_later_scenarios(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[
    Path,
    str,
    Path,
    backtest_artifact.ParsedBacktestArtifact,
    dict[str, backtest_artifact.ParsedBacktestArtifact],
    _FakeLaterCommandRunner,
]:
    database, research_run_id, run_dir, capability, development = _eligible_run(
        tmp_path, monkeypatch
    )
    _prepare_continuation(
        database,
        research_run_id,
        run_dir,
        capability,
        development,
        monkeypatch,
    )
    fake_python = tmp_path / "fake-command-venv" / "bin" / "python"
    fake_python.parent.mkdir(parents=True)
    fake_python.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake_python.chmod(0o700)
    (fake_python.parent.parent / "pyvenv.cfg").write_text(
        "home = /test\n", encoding="utf-8"
    )
    (
        fake_python.parent.parent
        / "lib"
        / "python3.13"
        / "site-packages"
    ).mkdir(parents=True)
    monkeypatch.setattr(
        holdout_run,
        "_child_runtime_paths",
        lambda _python, source, _authorization: (fake_python, Path(source)),
    )
    _install_synthetic_sanitizer(monkeypatch)
    runner = _FakeLaterCommandRunner()

    result = holdout_run.execute_holdout_continuation(
        database,
        run_dir,
        research_run_id,
        capability.freqtrade_python,
        capability.freqtrade_source,
        command_runner=runner,
    )

    assert result == {
        "research_run_id": research_run_id,
        "status": "RESULTS_READY",
        "scenarios": ["HOLDOUT", "HOLDOUT_STRESS"],
    }
    assert runner.scenarios == ["HOLDOUT", "HOLDOUT_STRESS"]
    later = _later_artifacts(run_dir, development)
    _install_artifact_parser(monkeypatch, development, later)
    return database, research_run_id, run_dir, development, later, runner


def test_t2_fake_runner_executes_two_later_scenarios_and_attaches_atomically(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database, research_run_id, run_dir, _development, later, _runner = (
        _execute_synthetic_later_scenarios(tmp_path, monkeypatch)
    )

    public = holdout_run.finalize_holdout_continuation(
        database,
        run_dir,
        research_run_id,
        now="2026-01-01T00:01:00.000Z",
    )

    assert public["research_run_id"] == research_run_id
    assert (public["status"], public["stage"], public["verdict"]) == (
        "COMPLETED",
        "COMPLETED",
        None,
    )
    with get_connection(database, read_only=True) as connection:
        run = connection.execute(
            "SELECT status,stage,verdict,checks_json FROM research_runs WHERE id=?",
            (research_run_id,),
        ).fetchone()
        releases = connection.execute(
            "SELECT COUNT(*) FROM releases WHERE research_run_id=?",
            (research_run_id,),
        ).fetchone()[0]
    rows = _execution_rows(database, research_run_id)
    checks = json.loads(run["checks_json"])
    assert (run["status"], run["stage"], run["verdict"]) == (
        "COMPLETED",
        "COMPLETED",
        None,
    )
    assert checks["next_phase"] == "HUMAN_ECONOMIC_REVIEW"
    assert checks["judge"] == "NOT_RUN"
    assert {row["research_run_id"] for row in rows} == {research_run_id}
    assert [(row["scenario"], row["status"]) for row in rows] == [
        ("DEVELOPMENT", "SUCCEEDED"),
        ("HOLDOUT", "SUCCEEDED"),
        ("HOLDOUT_STRESS", "SUCCEEDED"),
    ]
    assert rows[0]["scenario_passed"] == 1
    assert [row["scenario_passed"] for row in rows[1:]] == [None, None]
    assert [row["result_archive_path"] for row in rows[1:]] == [
        str(later["HOLDOUT"].archive_path),
        str(later["HOLDOUT_STRESS"].archive_path),
    ]
    assert releases == 0


@pytest.mark.parametrize("drift", ("cross_scenario", "later_provenance"))
def test_t2_validation_drift_keeps_both_later_rows_pending(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    drift: str,
) -> None:
    database, research_run_id, run_dir, development, later, _runner = (
        _execute_synthetic_later_scenarios(tmp_path, monkeypatch)
    )
    if drift == "cross_scenario":
        later["HOLDOUT_STRESS"] = replace(
            later["HOLDOUT_STRESS"], pairs=("BTC/USDT:USDT",)
        )
        _install_artifact_parser(monkeypatch, development, later)
    else:
        provenance = (
            run_dir
            / "holdout-evidence"
            / "backtest-result-holdout-stress-03.provenance.json"
        )
        value = json.loads(provenance.read_text())
        value["acquisition"]["retained_data_provenance_sha256"] = "f" * 64
        provenance.write_bytes(_canonical(value))

    with pytest.raises(holdout_run.HoldoutRunError) as raised:
        holdout_run.finalize_holdout_continuation(
            database,
            run_dir,
            research_run_id,
            now="2026-01-01T00:01:00.000Z",
        )

    assert raised.value.code == "artifact_invalid"
    rows = _execution_rows(database, research_run_id)
    later_rows = rows[1:]
    assert [row["status"] for row in later_rows] == ["PENDING", "PENDING"]
    assert [row["result_archive_path"] for row in later_rows] == [None, None]
    assert [row["metrics_json"] for row in later_rows] == ["{}", "{}"]
    assert [row["scenario_passed"] for row in later_rows] == [None, None]
    with get_connection(database, read_only=True) as connection:
        run = connection.execute(
            "SELECT status,stage,verdict,checks_json FROM research_runs WHERE id=?",
            (research_run_id,),
        ).fetchone()
        releases = connection.execute(
            "SELECT COUNT(*) FROM releases WHERE research_run_id=?",
            (research_run_id,),
        ).fetchone()[0]
    assert (run["status"], run["stage"], run["verdict"]) == (
        "RUNNING",
        "HOLDOUT_BACKTEST",
        None,
    )
    assert json.loads(run["checks_json"])["next_phase"] == "HOLDOUT_IN_PROGRESS"
    assert releases == 0
