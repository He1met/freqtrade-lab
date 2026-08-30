import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

import pytest

import lab.research_candidate as research_candidate_module
import scripts.run_research_candidate as candidate_entry
from lab.backtest_artifact import SUPPORTED_FREQTRADE_COMMIT
from lab.database import get_connection, get_schema_version, init_database
from lab.frequi import configure_frequi
from lab.research_candidate import (
    SUPPORTED_OFFICIAL_CORE,
    ResearchCandidateError,
    run_research_candidate,
)
from lab.strategy_library import (
    load_execution_archive,
    load_research_run_detail,
    load_strategy_library,
)


ROOT = Path(__file__).resolve().parent.parent
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "freqtrade_2026_7"
PRODUCER_ROOT = FIXTURE_ROOT / "producer"
MANIFEST = json.loads((FIXTURE_ROOT / "research-bundle-v1.json").read_text())
SCENARIO_FIXTURES = {
    "DEVELOPMENT": "backtest-result-2026-08-30_12-55-02",
    "HOLDOUT": "backtest-result-2026-08-30_06-43-00",
    "HOLDOUT_STRESS": "backtest-result-2026-08-30_06-43-22",
}
EXPECTED_OUTPUT_STEMS = {
    "DEVELOPMENT": "backtest-result-development-01",
    "HOLDOUT": "backtest-result-holdout-02",
    "HOLDOUT_STRESS": "backtest-result-holdout-stress-03",
}
TABLES = (
    "research_profiles",
    "generation_runs",
    "candidates",
    "research_runs",
    "backtest_executions",
    "releases",
)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _strategy_bytes() -> bytes:
    archive = FIXTURE_ROOT / f"{SCENARIO_FIXTURES['DEVELOPMENT']}.zip"
    with zipfile.ZipFile(archive) as unit:
        name = next(name for name in unit.namelist() if name.endswith("_StrategyTestV3Futures.py"))
        return unit.read(name)


def _config_value() -> Mapping[str, Any]:
    return json.loads((PRODUCER_ROOT / "config.json").read_text(encoding="utf-8"))


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _record(path: Path, role: Optional[str] = None) -> Dict[str, Any]:
    data = path.read_bytes()
    result: Dict[str, Any] = {"bytes": len(data), "sha256": _sha256(data)}
    if role is not None:
        result["role"] = role
    return result


def _inputs(tmp_path: Path) -> Dict[str, Any]:
    receipt_root = tmp_path / "fixture"
    strategy_root = receipt_root / "strategies"
    strategy_file = strategy_root / "StrategyTestV3Futures.py"
    config = receipt_root / "config.json"
    research_spec = receipt_root / "research-spec.json"
    tracked_note = receipt_root / "source-receipt.json"
    data_dir = tmp_path / "private-data" / "data" / "okx"
    market = tmp_path / "private-data" / "market_snapshot.json"
    tiers = tmp_path / "private-data" / "isolated_tiers_snapshot.json"
    source = tmp_path / "freqtrade-source"
    runner = tmp_path / "run_freqtrade_backtest.py"
    fake_python = tmp_path / "venv" / "bin" / "python"
    sandbox = tmp_path / "sandbox-exec"

    _write(strategy_file, _strategy_bytes())
    _write(config, _json_bytes(_config_value()))
    _write(
        research_spec,
        _json_bytes(
            {
                "schema": "freqtrade-lab-research-spec-v1",
                "profile": MANIFEST["profile"],
                "candidate": MANIFEST["candidate"],
            }
        ),
    )
    _write(tracked_note, b'{"source":"test receipt only"}\n')
    data_files = {
        "data/okx/futures/XRP_USDT_USDT-5m-futures.feather": (b"five-minute", "ohlcv"),
        "data/okx/futures/XRP_USDT_USDT-1h-mark.feather": (b"mark", "mark"),
        "data/okx/futures/XRP_USDT_USDT-1h-funding_rate.feather": (b"funding", "funding"),
    }
    for relative, (data, _) in data_files.items():
        under_data = Path(relative).relative_to("data/okx")
        _write(data_dir / under_data, data)
    _write(market, b'{"symbol":"XRP/USDT:USDT"}\n')
    _write(tiers, b'[{"symbol":"XRP/USDT:USDT"}]\n')
    source.mkdir()
    for executable in (runner, fake_python, sandbox):
        _write(executable, b"#!/bin/sh\nexit 0\n")
        executable.chmod(0o755)
    _write(tmp_path / "venv" / "pyvenv.cfg", b"home = /test\n")
    (tmp_path / "venv" / "lib" / "python3.13" / "site-packages").mkdir(
        parents=True
    )

    provenance = receipt_root / "retained-data-provenance.json"
    local_only = {
        relative: _record(data_dir / Path(relative).relative_to("data/okx"), role)
        for relative, (_, role) in data_files.items()
    }
    local_only.update(
        {
            "market_snapshot.json": _record(market, "market_snapshot"),
            "isolated_tiers_snapshot.json": _record(tiers, "leverage_tiers"),
        }
    )
    _write(
        provenance,
        _json_bytes(
            {
                "schema": "freqtrade-lab-retained-okx-data-v1",
                "portable_retained_fixture": "BLOCKED_LICENSE",
                "source": {
                    "host": "www.okx.com",
                    "authentication": "none",
                    "pair": "XRP/USDT:USDT",
                    "instrument_id": "XRP-USDT-SWAP",
                },
                "freqtrade": {
                    "version": "2026.7",
                    "tag": "2026.7",
                    "commit": SUPPORTED_FREQTRADE_COMMIT,
                    "dependencies": {
                        "ccxt": "4.5.68",
                        "pandas": "3.0.3",
                        "pyarrow": "25.0.0",
                        "python": "3.13.13",
                    },
                },
                "contract": {
                    "config": "config.json",
                    "strategy": "strategies/StrategyTestV3Futures.py",
                    "data_dir": "data/okx",
                    "market_snapshot": "market_snapshot.json",
                    "leverage_tiers": "isolated_tiers_snapshot.json",
                    "development_timerange": "20260801-20260804",
                    "holdout_timerange": "20260804-20260807",
                    "timeframe": "5m",
                },
                "files": {
                    "config.json": _record(config),
                    "research-spec.json": _record(research_spec),
                    "source-receipt.json": _record(tracked_note),
                    "strategies/StrategyTestV3Futures.py": _record(strategy_file),
                },
                "local_only_files": local_only,
            }
        ),
    )
    return {
        "freqtrade_python": fake_python,
        "freqtrade_source": source,
        "config": config,
        "data_dir": data_dir,
        "strategy_path": strategy_root,
        "strategy_file": strategy_file,
        "strategy": "StrategyTestV3Futures",
        "research_spec": research_spec,
        "data_provenance": provenance,
        "market_snapshot": market,
        "leverage_tiers": tiers,
        "development_timerange": "20260801-20260804",
        "holdout_timerange": "20260804-20260807",
        "stress_fee_multiplier": 2.0,
        "output_dir": tmp_path / "bundle",
        "sandbox_exec": sandbox,
        "runner_script": runner,
    }


def _preset_root(
    tmp_path: Path,
    *,
    class_name: str = "StrategyTestV3Futures",
) -> tuple[Dict[str, Any], Path]:
    inputs = _inputs(tmp_path)
    root = Path(inputs["data_provenance"]).parent
    shutil.copytree(inputs["data_dir"], root / "data" / "okx")
    shutil.copyfile(inputs["market_snapshot"], root / "market_snapshot.json")
    shutil.copyfile(
        inputs["leverage_tiers"], root / "isolated_tiers_snapshot.json"
    )
    if class_name == "StrategyTestV3Futures":
        return inputs, root

    old_strategy = root / "strategies" / "StrategyTestV3Futures.py"
    strategy = root / "strategies" / f"{class_name}.py"
    strategy.write_bytes(
        old_strategy.read_bytes().replace(b"StrategyTestV3Futures", class_name.encode())
    )
    old_strategy.unlink()

    config_path = root / "config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["strategy"] = class_name
    config_path.write_bytes(_json_bytes(config))

    spec_path = root / "research-spec.json"
    research_spec = json.loads(spec_path.read_text(encoding="utf-8"))
    research_spec["candidate"]["class_name"] = class_name
    research_spec["candidate"]["display_name"] = f"Preset test - {class_name}"
    spec_path.write_bytes(_json_bytes(research_spec))

    provenance_path = root / "retained-data-provenance.json"
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    provenance["contract"]["strategy"] = f"strategies/{class_name}.py"
    del provenance["files"]["strategies/StrategyTestV3Futures.py"]
    provenance["files"].update(
        {
            "config.json": _record(config_path),
            "research-spec.json": _record(spec_path),
            f"strategies/{class_name}.py": _record(strategy),
        }
    )
    provenance_path.write_bytes(_json_bytes(provenance))
    return inputs, root


class FakeFreqtrade:
    def __init__(
        self,
        fail_scenario: Optional[str] = None,
        bad_version: bool = False,
        dirty_source: bool = False,
        omit_receipt_field: Optional[str] = None,
    ):
        self.fail_scenario = fail_scenario
        self.bad_version = bad_version
        self.dirty_source = dirty_source
        self.omit_receipt_field = omit_receipt_field
        self.commands = []
        self.scenarios = []

    def __call__(self, command, **kwargs):
        assert isinstance(command, list)
        assert kwargs["check"] is False
        assert kwargs["capture_output"] is True
        assert kwargs["timeout"] == research_candidate_module.SCENARIO_TIMEOUT_SECONDS
        self.commands.append(command)
        if command[:3] == ["git", "rev-parse", "HEAD"]:
            return subprocess.CompletedProcess(command, 0, SUPPORTED_FREQTRADE_COMMIT + "\n", "")
        if command[:4] == ["git", "describe", "--exact-match", "--tags"]:
            return subprocess.CompletedProcess(command, 0, "2026.7\n", "")
        if command[:3] == ["git", "status", "--porcelain=v1"]:
            stdout = " M freqtrade/optimize/backtesting.py\n" if self.dirty_source else ""
            return subprocess.CompletedProcess(command, 0, stdout, "")
        if "-m" in command and "freqtrade" in command and "--version" in command:
            version = "2026.6" if self.bad_version else "2026.7"
            stdout = f"Freqtrade Version:\tfreqtrade {version}\n"
            return subprocess.CompletedProcess(command, 0, stdout, "")

        scenario = command[command.index("--scenario") + 1]
        self.scenarios.append(scenario)
        if self.bad_version or self.dirty_source:
            return subprocess.CompletedProcess(
                command, 2, "", "sandboxed runtime preflight rejected"
            )
        if scenario == self.fail_scenario:
            return subprocess.CompletedProcess(command, 17, "", "controlled failure")
        export_dir = Path(command[command.index("--export-dir") + 1])
        stem = SCENARIO_FIXTURES[scenario]
        archive = FIXTURE_ROOT / f"{stem}.zip"
        metadata = FIXTURE_ROOT / f"{stem}.meta.json"
        shutil.copyfile(archive, export_dir / archive.name)
        shutil.copyfile(metadata, export_dir / metadata.name)
        provenance_path = Path(command[command.index("--data-provenance") + 1])
        provenance_bytes = provenance_path.read_bytes()
        provenance = json.loads(provenance_bytes)
        contract = provenance["contract"]
        local_only = provenance["local_only_files"]
        data_prefix = contract["data_dir"] + "/"
        data_sha256 = {
            name.removeprefix(data_prefix): record["sha256"]
            for name, record in local_only.items()
            if name.startswith(data_prefix)
        }
        with zipfile.ZipFile(archive) as unit:
            report_name = next(
                name
                for name in unit.namelist()
                if name.endswith(".json") and not name.endswith("_config.json")
            )
            report = json.loads(unit.read(report_name))
        total_trades = report["strategy"]["StrategyTestV3Futures"]["total_trades"]
        timerange = command[command.index("--timerange") + 1]
        stop = datetime.strptime(timerange.split("-", 1)[1], "%Y%m%d").replace(
            tzinfo=timezone.utc
        )
        receipt = {
            "scenario": scenario,
            "archive": archive.name,
            "metadata": metadata.name,
            "total_trades": total_trades,
            "dependencies": {
                "freqtrade": "2026.7",
                "ccxt": "4.5.68",
                "pandas": "3.0.3",
                "pyarrow": "25.0.0",
                "python": "3.13.13",
            },
            "official_core": SUPPORTED_OFFICIAL_CORE,
            "freqtrade_commit": SUPPORTED_FREQTRADE_COMMIT,
            "source_tree_sha256": command[
                command.index("--source-tree-sha256") + 1
            ],
            "runner_sha256": command[command.index("--runner-sha256") + 1],
            "data_provenance_sha256": _sha256(provenance_bytes),
            "input_receipts": {
                "market_snapshot_sha256": local_only[contract["market_snapshot"]]["sha256"],
                "leverage_tiers_sha256": local_only[contract["leverage_tiers"]]["sha256"],
                "data_sha256": data_sha256,
            },
            "scenario_data_view": {
                "exclusive_stop_utc": stop.isoformat().replace("+00:00", "Z"),
                "files": {
                    name: {"rows": 1, "sha256": digest}
                    for name, digest in data_sha256.items()
                },
            },
        }
        if self.omit_receipt_field is not None:
            receipt.pop(self.omit_receipt_field)
        return subprocess.CompletedProcess(command, 0, json.dumps(receipt) + "\n", "logs")


def _counts(database: Path) -> Dict[str, int]:
    with get_connection(database) as connection:
        return {table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in TABLES}


def test_t0_t1_fake_producer_reaches_existing_read_only_consumers(
    tmp_path: Path,
) -> None:
    inputs = _inputs(tmp_path)
    database = init_database(tmp_path / "lab.sqlite")
    fake = FakeFreqtrade()
    result = run_research_candidate(**inputs, database=database, command_runner=fake)

    assert fake.scenarios == ["DEVELOPMENT", "HOLDOUT", "HOLDOUT_STRESS"]
    assert result.bundle_root == inputs["output_dir"]
    assert result.imported is not None
    assert _counts(database) == {
        "research_profiles": 1,
        "generation_runs": 1,
        "candidates": 1,
        "research_runs": 1,
        "backtest_executions": 3,
        "releases": 0,
    }
    with get_connection(database) as connection:
        run = connection.execute("SELECT status, verdict FROM research_runs").fetchone()
        rows = connection.execute(
            "SELECT research_run_id, status, scenario_passed, return_code FROM backtest_executions ORDER BY sequence"
        ).fetchall()
    assert tuple(run) == ("COMPLETED", None)
    assert len({row["research_run_id"] for row in rows}) == 1
    assert [row["status"] for row in rows] == ["SUCCEEDED"] * 3
    assert all(row["scenario_passed"] is None and row["return_code"] is None for row in rows)

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    manifest_artifacts = {
        artifact["scenario"]: artifact for artifact in manifest["artifacts"]
    }
    assert {
        artifact.scenario: Path(artifact.archive).stem for artifact in result.artifacts
    } == EXPECTED_OUTPUT_STEMS
    assert len(set(EXPECTED_OUTPUT_STEMS.values())) == 3
    for artifact in result.artifacts:
        stem = EXPECTED_OUTPUT_STEMS[artifact.scenario]
        archive = result.bundle_root / f"{stem}.zip"
        metadata = result.bundle_root / f"{stem}.meta.json"
        provenance_path = result.bundle_root / f"{stem}.provenance.json"
        provenance_bytes = provenance_path.read_bytes()
        provenance = json.loads(provenance_bytes)
        expected_members = {
            f"{stem}.json",
            f"{stem}_config.json",
            f"{stem}_StrategyTestV3Futures.py",
        }

        assert manifest_artifacts[artifact.scenario] == {
            "scenario": artifact.scenario,
            "archive": archive.name,
            "provenance_sha256": _sha256(provenance_bytes),
        }
        assert artifact.archive == archive.name
        assert artifact.archive_sha256 == _sha256(archive.read_bytes())
        assert artifact.provenance_sha256 == _sha256(provenance_bytes)
        assert provenance["artifact"]["archive"] == archive.name
        assert provenance["artifact"]["archive_sha256"] == _sha256(
            archive.read_bytes()
        )
        assert provenance["artifact"]["metadata"] == metadata.name
        assert provenance["artifact"]["metadata_sha256"] == _sha256(
            metadata.read_bytes()
        )
        with zipfile.ZipFile(archive) as unit:
            assert set(unit.namelist()) == expected_members
            assert provenance["artifact"]["members"] == {
                name: _sha256(unit.read(name)) for name in expected_members
            }

    for path in result.bundle_root.iterdir():
        data = path.read_bytes()
        assert str(tmp_path).encode() not in data
        assert b"/private/tmp/" not in data
    provenance = json.loads(
        (
            result.bundle_root
            / "backtest-result-development-01.provenance.json"
        ).read_text()
    )
    assert "adversarial strategy code" in provenance["generation"]["candidate_code_trust"]
    receipts = provenance["generation"]["implementation_receipts"]
    assert set(receipts) == {"producer", "runner"}
    assert all(len(receipt["sha256"]) == 64 for receipt in receipts.values())

    library = load_strategy_library(database)
    assert len(library["strategies"]) == 1
    assert (
        library["strategies"][0]["latest_summary"]["research_run_id"]
        == result.imported.research_run_id
    )

    results_root = tmp_path / "frequi-results"
    results_root.mkdir()
    for stem in EXPECTED_OUTPUT_STEMS.values():
        shutil.copyfile(
            result.bundle_root / f"{stem}.zip",
            results_root / f"{stem}.zip",
        )
        shutil.copyfile(
            result.bundle_root / f"{stem}.meta.json",
            results_root / f"{stem}.meta.json",
        )
    frequi_config = configure_frequi(
        "http://127.0.0.1:8080",
        results_root,
        artifact_root=result.bundle_root,
    )
    frequi_probe = {
        "available": True,
        "version": "3.1.1",
        "url": "http://127.0.0.1:8080/backtest",
    }
    root_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(
        os, "O_NOFOLLOW", 0
    )
    artifact_root_fd = os.open(result.bundle_root, root_flags)
    try:
        detail = load_research_run_detail(
            database,
            result.imported.profile_id,
            result.imported.candidate_id,
            result.imported.research_run_id,
            artifact_root=result.bundle_root.resolve(),
            artifact_root_fd=artifact_root_fd,
            frequi_config=frequi_config,
            frequi_probe=frequi_probe,
        )
        assert (
            detail["selected_run"]["research_run_id"]
            == result.imported.research_run_id
        )
        assert detail["selected_run"]["verdict"] is None
        assert [scenario["scenario"] for scenario in detail["scenarios"]] == list(
            EXPECTED_OUTPUT_STEMS
        )
        for scenario in detail["scenarios"]:
            assert scenario["scenario_passed"] is None
            assert scenario["download"]["available"] is True
            assert scenario["frequi"]["available"] is True
            assert scenario["frequi"]["local_copy_ready"] is True
            assert scenario["frequi"]["history_visibility"] is None
            stem = EXPECTED_OUTPUT_STEMS[scenario["scenario"]]
            assert scenario["frequi"]["artifact_filename"] == f"{stem}.zip"
            archive_bytes, _ = load_execution_archive(
                database,
                scenario["execution_id"],
                artifact_root=result.bundle_root.resolve(),
                artifact_root_fd=artifact_root_fd,
            )
            assert archive_bytes == (result.bundle_root / f"{stem}.zip").read_bytes()
    finally:
        os.close(artifact_root_fd)


def test_t1_mid_scenario_failure_publishes_nothing_and_writes_no_rows(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    database = init_database(tmp_path / "lab.sqlite")
    fake = FakeFreqtrade(fail_scenario="HOLDOUT")

    with pytest.raises(ResearchCandidateError, match="HOLDOUT backtesting failed"):
        run_research_candidate(**inputs, database=database, command_runner=fake)

    assert fake.scenarios == ["DEVELOPMENT", "HOLDOUT"]
    assert not inputs["output_dir"].exists()
    assert _counts(database) == {table: 0 for table in TABLES}
    assert not list(tmp_path.glob(".bundle.work-*"))


def test_t1_incomplete_runner_receipt_publishes_nothing(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    fake = FakeFreqtrade(omit_receipt_field="input_receipts")

    with pytest.raises(ResearchCandidateError, match="runner receipt is missing fields"):
        run_research_candidate(**inputs, command_runner=fake)

    assert not inputs["output_dir"].exists()


def test_t1_database_import_failure_removes_newly_published_bundle(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    invalid_database = tmp_path / "not-schema-v1.sqlite"
    sqlite3.connect(invalid_database).close()
    fake = FakeFreqtrade()

    with pytest.raises(ResearchCandidateError, match="database import failed"):
        run_research_candidate(
            **inputs,
            database=invalid_database,
            command_runner=fake,
        )

    assert fake.scenarios == []
    assert not inputs["output_dir"].exists()


def test_t1_import_interrupt_removes_newly_published_bundle(
    monkeypatch, tmp_path: Path
) -> None:
    inputs = _inputs(tmp_path)
    database = init_database(tmp_path / "lab.sqlite")
    fake = FakeFreqtrade()

    def interrupt_import(*args, **kwargs):
        raise KeyboardInterrupt("controlled")

    monkeypatch.setattr(
        research_candidate_module, "import_research_bundle", interrupt_import
    )
    with pytest.raises(ResearchCandidateError, match="before a visible commit"):
        run_research_candidate(**inputs, database=database, command_runner=fake)

    assert not inputs["output_dir"].exists()
    assert _counts(database) == {table: 0 for table in TABLES}


def test_t1_post_commit_interrupt_retains_bundle_for_database_locators(
    monkeypatch, tmp_path: Path
) -> None:
    inputs = _inputs(tmp_path)
    database = init_database(tmp_path / "lab.sqlite")
    fake = FakeFreqtrade()
    real_import = research_candidate_module.import_research_bundle

    def commit_then_interrupt(*args, **kwargs):
        real_import(*args, **kwargs)
        raise KeyboardInterrupt("controlled after commit")

    monkeypatch.setattr(
        research_candidate_module, "import_research_bundle", commit_then_interrupt
    )
    with pytest.raises(ResearchCandidateError, match="bundle was retained"):
        run_research_candidate(**inputs, database=database, command_runner=fake)

    assert inputs["output_dir"].is_dir()
    assert _counts(database) == {
        "research_profiles": 1,
        "generation_runs": 1,
        "candidates": 1,
        "research_runs": 1,
        "backtest_executions": 3,
        "releases": 0,
    }


def test_t0_rejects_wrong_freqtrade_version_before_any_backtest(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    fake = FakeFreqtrade(bad_version=True)
    with pytest.raises(ResearchCandidateError, match="DEVELOPMENT backtesting failed"):
        run_research_candidate(**inputs, command_runner=fake)
    assert fake.scenarios == ["DEVELOPMENT"]
    assert not inputs["output_dir"].exists()


def test_t0_accepts_virtualenv_python_symlink_without_resolving_it(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    python_link = Path(inputs["freqtrade_python"])
    python_link.unlink()
    python_target = tmp_path / "python-target"
    _write(python_target, b"#!/bin/sh\nexit 0\n")
    python_target.chmod(0o755)
    python_link.symlink_to(python_target)
    fake = FakeFreqtrade()

    run_research_candidate(**inputs, command_runner=fake)

    assert any(str(python_link) in command for command in fake.commands)


def test_t0_rejects_dirty_freqtrade_source_before_any_backtest(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    fake = FakeFreqtrade(dirty_source=True)

    with pytest.raises(ResearchCandidateError, match="DEVELOPMENT backtesting failed"):
        run_research_candidate(**inputs, command_runner=fake)

    assert fake.scenarios == ["DEVELOPMENT"]
    assert not inputs["output_dir"].exists()


def test_t0_rejects_nonempty_credentials_before_any_subprocess(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    config = json.loads(Path(inputs["config"]).read_text())
    config["exchange"]["key"] = "must-not-be-read"
    Path(inputs["config"]).write_bytes(_json_bytes(config))
    fake = FakeFreqtrade()
    with pytest.raises(ResearchCandidateError, match="credential field"):
        run_research_candidate(**inputs, command_runner=fake)
    assert fake.commands == []


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        (lambda config: config.update({"add_config_files": ["other.json"]}), "add_config_files"),
        (lambda config: config["exchange"].update({"private_key": "unsafe"}), "credential field"),
        (
            lambda config: config["exchange"].update(
                {"ccxt_config": {"headers": {"Authorization": "Bearer unsafe"}}}
            ),
            "unknown fields",
        ),
        (lambda config: config.update({"logfile": "/tmp/unsafe.log"}), "unknown fields"),
        (
            lambda config: config.update(
                {"webhook": {"enabled": False, "url": "https://example.invalid/token"}}
            ),
            "unknown fields",
        ),
        (lambda config: config.update({"pairlists": [{"method": "VolumePairList"}]}), "StaticPairList"),
    ),
)
def test_t0_rejects_config_include_secret_and_dynamic_pairlist(
    tmp_path: Path, mutation, message: str
) -> None:
    inputs = _inputs(tmp_path)
    config = json.loads(Path(inputs["config"]).read_text())
    mutation(config)
    Path(inputs["config"]).write_bytes(_json_bytes(config))
    fake = FakeFreqtrade()

    with pytest.raises(ResearchCandidateError, match=message):
        run_research_candidate(**inputs, command_runner=fake)

    assert fake.commands == []


def test_t0_rejects_scenario_overlap_and_stress_identity(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    fake = FakeFreqtrade()
    inputs["development_timerange"] = "20260801-20260805"
    with pytest.raises(ResearchCandidateError, match="Development must end"):
        run_research_candidate(**inputs, command_runner=fake)
    assert fake.commands == []

    inputs = _inputs(tmp_path / "second")
    inputs["stress_fee_multiplier"] = 1.0
    with pytest.raises(ResearchCandidateError, match="greater than 1"):
        run_research_candidate(**inputs, command_runner=fake)
    assert fake.commands == []


def test_t0_rejects_local_data_hash_mismatch(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    data_file = next(Path(inputs["data_dir"]).rglob("*5m-futures.feather"))
    data_file.write_bytes(b"tampered")
    fake = FakeFreqtrade()
    with pytest.raises(ResearchCandidateError, match="retained receipt"):
        run_research_candidate(**inputs, command_runner=fake)
    assert fake.commands == []


def test_t0_rejects_dependency_version_mismatch(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    provenance_path = Path(inputs["data_provenance"])
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    provenance["freqtrade"]["dependencies"]["ccxt"] = "4.5.67"
    provenance_path.write_bytes(_json_bytes(provenance))
    fake = FakeFreqtrade()

    with pytest.raises(ResearchCandidateError, match="dependency versions"):
        run_research_candidate(**inputs, command_runner=fake)

    assert fake.commands == []


def test_t0_rejects_secret_in_candidate_metadata(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    spec_path = Path(inputs["research_spec"])
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    spec["candidate"]["metadata"]["api_key"] = "must-not-be-published"
    spec_path.write_bytes(_json_bytes(spec))
    fake = FakeFreqtrade()

    with pytest.raises(ResearchCandidateError, match="credential field"):
        run_research_candidate(**inputs, command_runner=fake)

    assert fake.commands == []


def test_t0_requires_config_strategy_and_spec_receipts(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    provenance_path = Path(inputs["data_provenance"])
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    del provenance["files"]["config.json"]
    provenance_path.write_bytes(_json_bytes(provenance))
    fake = FakeFreqtrade()

    with pytest.raises(ResearchCandidateError, match="must all be bound"):
        run_research_candidate(**inputs, command_runner=fake)

    assert fake.commands == []


def test_t0_rejects_symlink_inside_local_data(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    data_file = next(Path(inputs["data_dir"]).rglob("*5m-futures.feather"))
    original = data_file.read_bytes()
    outside = tmp_path / "outside.feather"
    outside.write_bytes(original)
    data_file.unlink()
    data_file.symlink_to(outside)
    fake = FakeFreqtrade()

    with pytest.raises(ResearchCandidateError, match="must not contain symlinks"):
        run_research_candidate(**inputs, command_runner=fake)

    assert fake.commands == []


def test_t0_uses_argument_arrays_and_network_deny_sandbox(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    fake = FakeFreqtrade()
    run_research_candidate(**inputs, command_runner=fake)
    scenario_commands = [command for command in fake.commands if "--scenario" in command]
    assert len(scenario_commands) == 3
    for command in scenario_commands:
        assert isinstance(command, list)
        assert command[1] == "-p"
        assert "(deny default)" in command[2]
        assert "(deny network*)" in command[2]
        assert "(allow process-fork)" not in command[2]
        process_rules = [
            line for line in command[2].splitlines() if line.startswith("(allow process-exec")
        ]
        assert process_rules
        assert all(line.count("(literal ") == 1 for line in process_rules)
        assert "--data-dir" in command
        assert "--freqtrade-source" in command
        assert "--runner-sha256" in command
        assert "--source-tree-sha256" in command
        assert "--market-snapshot" in command
        assert "--leverage-tiers" in command
        assert "--strategy-file" in command
        assert "--strategy-sha256" in command


def test_publication_never_replaces_a_concurrently_created_directory(
    tmp_path: Path,
) -> None:
    source = tmp_path / "staging"
    destination = tmp_path / "bundle"
    source.mkdir()
    destination.mkdir()
    (source / "new.txt").write_text("new", encoding="utf-8")

    with pytest.raises(ResearchCandidateError, match="created concurrently"):
        research_candidate_module._publish_directory_exclusive(source, destination)

    assert list(destination.iterdir()) == []
    assert (source / "new.txt").read_text(encoding="utf-8") == "new"


def test_raw_zip_expansion_limits_are_checked_before_reading() -> None:
    info = zipfile.ZipInfo("report.json")
    info.file_size = research_candidate_module.MAX_RAW_ZIP_MEMBER_BYTES + 1
    info.compress_size = 1

    with pytest.raises(ResearchCandidateError, match="expansion limit"):
        research_candidate_module._validate_raw_zip_infos([info])


def test_supplied_checkout_git_has_a_separate_deny_default_sandbox(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    git_home = tmp_path / "git-home"
    source.mkdir()
    git_home.mkdir()

    policy = research_candidate_module._git_sandbox_policy(source, git_home)
    process_rules = [
        line for line in policy.splitlines() if line.startswith("(allow process-exec")
    ]

    assert "(deny default)" in policy
    assert "(deny network*)" in policy
    assert "(allow process-fork)" not in policy
    assert len(process_rules) == 1
    assert str(research_candidate_module.DEFAULT_GIT_EXECUTABLE) in process_rules[0]
    assert "/bin/sh" not in policy
    assert f'(allow file-read* (subpath "{source}"))' in policy
    assert f'(allow file-write* (subpath "{git_home}"))' in policy
    command = research_candidate_module._exact_git_command(("rev-parse", "HEAD"))
    environment = research_candidate_module._git_environment(git_home)
    assert "--no-replace-objects" in command
    assert environment["GIT_NO_REPLACE_OBJECTS"] == "1"


def test_cli_invalid_input_is_exit_2_without_traceback(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "run_research_candidate.py"),
            "--freqtrade-python",
            str(tmp_path / "missing"),
            "--freqtrade-source",
            str(tmp_path),
            "--config",
            str(tmp_path / "missing-config"),
            "--data-dir",
            str(tmp_path),
            "--strategy-path",
            str(tmp_path),
            "--strategy-file",
            str(tmp_path / "missing-strategy"),
            "--strategy",
            "Strategy",
            "--research-spec",
            str(tmp_path / "missing-spec"),
            "--data-provenance",
            str(tmp_path / "missing-provenance"),
            "--market-snapshot",
            str(tmp_path / "missing-market"),
            "--leverage-tiers",
            str(tmp_path / "missing-tiers"),
            "--development-timerange",
            "20260101-20260102",
            "--holdout-timerange",
            "20260102-20260103",
            "--stress-fee-multiplier",
            "2",
            "--output-dir",
            str(tmp_path / "bundle"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "Research candidate failed:" in result.stderr
    assert "Traceback" not in result.stderr


def _preset_argv(inputs: Mapping[str, Any], root: Path, workspace: Path) -> list[str]:
    return [
        "--freqtrade-python",
        str(inputs["freqtrade_python"]),
        "--freqtrade-source",
        str(inputs["freqtrade_source"]),
        "--input-root",
        str(root),
        "--workspace",
        str(workspace),
    ]


def test_preset_maps_existing_contract_and_non_fixture_candidate(
    tmp_path: Path,
) -> None:
    inputs, root = _preset_root(tmp_path, class_name="TrustedLocalCandidate")
    workspace = tmp_path / "persistent-workspace"
    explicit_output = tmp_path / "controlled-output"
    args = candidate_entry.parse_args(
        [*_preset_argv(inputs, root, workspace), "--output-dir", str(explicit_output)]
    )

    values, serve_root = candidate_entry._run_arguments(args)

    assert values["config"] == root / "config.json"
    assert values["data_dir"] == root / "data" / "okx"
    assert values["strategy_path"] == root / "strategies"
    assert values["strategy_file"] == root / "strategies" / "TrustedLocalCandidate.py"
    assert values["strategy"] == "TrustedLocalCandidate"
    assert values["research_spec"] == root / "research-spec.json"
    assert values["development_timerange"] == "20260801-20260804"
    assert values["holdout_timerange"] == "20260804-20260807"
    assert values["stress_fee_multiplier"] == 2.0
    assert values["database"] == workspace / "lab.sqlite"
    assert values["output_dir"] == explicit_output
    assert serve_root == explicit_output
    assert get_schema_version(values["database"]) == 1


def test_preset_requires_existing_json_before_workspace_creation(tmp_path: Path) -> None:
    inputs, root = _preset_root(tmp_path)
    (root / "research-spec.json").unlink()
    workspace = tmp_path / "workspace-never-created"

    with pytest.raises(ResearchCandidateError, match="cannot be read as JSON"):
        candidate_entry._run_arguments(
            candidate_entry.parse_args(_preset_argv(inputs, root, workspace))
        )

    assert not workspace.exists()


def test_preset_requires_complete_mode_and_rejects_explicit_input_mix(
    tmp_path: Path,
) -> None:
    inputs, root = _preset_root(tmp_path)
    common = [
        "--freqtrade-python",
        str(inputs["freqtrade_python"]),
        "--freqtrade-source",
        str(inputs["freqtrade_source"]),
    ]
    with pytest.raises(ResearchCandidateError, match="both --input-root and --workspace"):
        candidate_entry._run_arguments(
            candidate_entry.parse_args([*common, "--input-root", str(root)])
        )
    with pytest.raises(ResearchCandidateError, match="remove: --config"):
        candidate_entry._run_arguments(
            candidate_entry.parse_args(
                [
                    *_preset_argv(inputs, root, tmp_path / "workspace"),
                    "--config",
                    str(root / "config.json"),
                ]
            )
        )


def test_preset_initializes_reuses_workspace_and_prints_executable_serve_command(
    monkeypatch,
    capsys,
    tmp_path: Path,
) -> None:
    inputs, root = _preset_root(tmp_path)
    workspace = tmp_path / "persistent-workspace"
    fake = FakeFreqtrade()

    def run_with_fake(**kwargs):
        return run_research_candidate(
            **kwargs,
            sandbox_exec=inputs["sandbox_exec"],
            runner_script=inputs["runner_script"],
            command_runner=fake,
        )

    monkeypatch.setattr(candidate_entry, "run_research_candidate", run_with_fake)
    argv = _preset_argv(inputs, root, workspace)

    assert candidate_entry.main(argv) == 0
    first_output = capsys.readouterr().out
    first_bundles = set((workspace / "artifacts").iterdir())
    assert len(first_bundles) == 1
    assert _counts(workspace / "lab.sqlite")["research_runs"] == 1
    assert _counts(workspace / "lab.sqlite")["backtest_executions"] == 3
    assert "Strategy library command:" in first_output
    assert str(workspace / "lab.sqlite") in first_output
    assert str(workspace / "artifacts") in first_output
    assert "--port 8765" in first_output
    assert "Strategy library URL: http://127.0.0.1:8765/" in first_output

    assert candidate_entry.main(argv) == 0
    second_output = capsys.readouterr().out
    second_bundles = set((workspace / "artifacts").iterdir())
    assert len(second_bundles) == 2
    assert first_bundles < second_bundles
    assert _counts(workspace / "lab.sqlite")["research_runs"] == 2
    assert _counts(workspace / "lab.sqlite")["backtest_executions"] == 6
    assert "Strategy library command:" in second_output
    assert fake.scenarios == [
        "DEVELOPMENT",
        "HOLDOUT",
        "HOLDOUT_STRESS",
        "DEVELOPMENT",
        "HOLDOUT",
        "HOLDOUT_STRESS",
    ]


def test_preset_mid_scenario_failure_leaves_empty_database_and_no_bundle(
    monkeypatch,
    tmp_path: Path,
) -> None:
    inputs, root = _preset_root(tmp_path)
    workspace = tmp_path / "failure-workspace"
    fake = FakeFreqtrade(fail_scenario="HOLDOUT")

    def run_with_fake(**kwargs):
        return run_research_candidate(
            **kwargs,
            sandbox_exec=inputs["sandbox_exec"],
            runner_script=inputs["runner_script"],
            command_runner=fake,
        )

    monkeypatch.setattr(candidate_entry, "run_research_candidate", run_with_fake)
    with pytest.raises(ResearchCandidateError, match="HOLDOUT backtesting failed"):
        candidate_entry.main(_preset_argv(inputs, root, workspace))

    assert fake.scenarios == ["DEVELOPMENT", "HOLDOUT"]
    assert _counts(workspace / "lab.sqlite") == {table: 0 for table in TABLES}
    assert list((workspace / "artifacts").iterdir()) == []
    assert not list((workspace / "artifacts").glob(".*.work-*"))


def test_preset_rejects_bad_database_and_hash_mismatch_before_any_scenario(
    monkeypatch,
    tmp_path: Path,
) -> None:
    bad_inputs, bad_root = _preset_root(tmp_path / "bad-database")
    bad_workspace = tmp_path / "bad-database-workspace"
    bad_database = tmp_path / "schema-zero.sqlite"
    sqlite3.connect(bad_database).close()
    called = False

    def should_not_run(**kwargs):
        nonlocal called
        called = True
        raise AssertionError("producer must not run")

    monkeypatch.setattr(candidate_entry, "run_research_candidate", should_not_run)
    with pytest.raises(ResearchCandidateError, match="schema-v1 validation"):
        candidate_entry.main(
            [
                *_preset_argv(bad_inputs, bad_root, bad_workspace),
                "--database",
                str(bad_database),
            ]
        )
    assert called is False

    inputs, root = _preset_root(tmp_path / "hash-mismatch")
    workspace = tmp_path / "hash-mismatch-workspace"
    Path(root / "strategies" / "StrategyTestV3Futures.py").write_bytes(
        b"class StrategyTestV3Futures(object):\n    pass\n"
    )
    fake = FakeFreqtrade()

    def run_with_fake(**kwargs):
        return run_research_candidate(
            **kwargs,
            sandbox_exec=inputs["sandbox_exec"],
            runner_script=inputs["runner_script"],
            command_runner=fake,
        )

    monkeypatch.setattr(candidate_entry, "run_research_candidate", run_with_fake)
    with pytest.raises(ResearchCandidateError, match="does not match its retained receipt"):
        candidate_entry.main(_preset_argv(inputs, root, workspace))
    assert fake.scenarios == []
    assert _counts(workspace / "lab.sqlite") == {table: 0 for table in TABLES}
    assert list((workspace / "artifacts").iterdir()) == []


def test_legacy_explicit_cli_maps_all_original_arguments(
    monkeypatch,
    capsys,
    tmp_path: Path,
) -> None:
    inputs = _inputs(tmp_path)
    captured: Dict[str, Any] = {}

    class Result:
        bundle_root = inputs["output_dir"]
        manifest_path = inputs["output_dir"] / "research-bundle-v1.json"
        manifest_sha256 = "0" * 64
        artifacts = ()
        imported = None

    def capture(**kwargs):
        captured.update(kwargs)
        return Result()

    monkeypatch.setattr(candidate_entry, "run_research_candidate", capture)
    argv = []
    original_options = (
        ("--freqtrade-python", "freqtrade_python"),
        ("--freqtrade-source", "freqtrade_source"),
        ("--config", "config"),
        ("--data-dir", "data_dir"),
        ("--strategy-path", "strategy_path"),
        ("--strategy-file", "strategy_file"),
        ("--strategy", "strategy"),
        ("--research-spec", "research_spec"),
        ("--data-provenance", "data_provenance"),
        ("--market-snapshot", "market_snapshot"),
        ("--leverage-tiers", "leverage_tiers"),
        ("--development-timerange", "development_timerange"),
        ("--holdout-timerange", "holdout_timerange"),
        ("--stress-fee-multiplier", "stress_fee_multiplier"),
        ("--output-dir", "output_dir"),
    )
    for option, key in original_options:
        argv.extend((option, str(inputs[key])))

    assert candidate_entry.main(argv) == 0

    assert captured == {
        key: (float(inputs[key]) if key == "stress_fee_multiplier" else inputs[key])
        for _, key in original_options
    } | {"database": None}
    output = capsys.readouterr().out
    assert "Database import: not requested" in output
    assert "Strategy library command:" not in output
