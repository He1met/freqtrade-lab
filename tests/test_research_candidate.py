import hashlib
import json
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
from lab.backtest_artifact import SUPPORTED_FREQTRADE_COMMIT
from lab.database import get_connection, init_database
from lab.research_candidate import (
    SUPPORTED_OFFICIAL_CORE,
    ResearchCandidateError,
    run_research_candidate,
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


def test_t1_fake_subprocess_produces_imports_and_preserves_null_judge(tmp_path: Path) -> None:
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
    for path in result.bundle_root.iterdir():
        data = path.read_bytes()
        assert str(tmp_path).encode() not in data
        assert b"/private/tmp/" not in data
    provenance = json.loads(
        (result.bundle_root / "backtest-result-development.provenance.json").read_text()
    )
    assert "adversarial strategy code" in provenance["generation"]["candidate_code_trust"]
    receipts = provenance["generation"]["implementation_receipts"]
    assert set(receipts) == {"producer", "runner"}
    assert all(len(receipt["sha256"]) == 64 for receipt in receipts.values())


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
