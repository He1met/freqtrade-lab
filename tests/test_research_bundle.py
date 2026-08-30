"""T0/T1/T2 tests for the three-scenario research bundle importer."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict

import pytest

import lab.research_bundle as research_bundle_module
from lab.database import get_connection, init_database
from lab.research_bundle import (
    BUNDLE_SCENARIOS,
    ResearchBundleImportError,
    import_research_bundle,
    validate_research_bundle,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_ROOT = PROJECT_ROOT / "tests" / "fixtures" / "freqtrade_2026_7"
MANIFEST_NAME = "research-bundle-v1.json"
CLI = PROJECT_ROOT / "scripts" / "import_research_bundle.py"
TABLES = (
    "research_profiles",
    "generation_runs",
    "candidates",
    "research_runs",
    "backtest_executions",
    "releases",
)


def _database(tmp_path: Path) -> Path:
    path = tmp_path / "lab.sqlite"
    init_database(path)
    return path


def _copy_bundle(tmp_path: Path) -> Path:
    root = tmp_path / "bundle"
    shutil.copytree(FIXTURE_ROOT, root)
    return root


def _manifest(root: Path) -> Dict[str, Any]:
    return json.loads((root / MANIFEST_NAME).read_text(encoding="utf-8"))


def _write_manifest(root: Path, value: Dict[str, Any]) -> None:
    (root / MANIFEST_NAME).write_text(
        json.dumps(value, allow_nan=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _snapshot(database: Path) -> Dict[str, list[tuple[Any, ...]]]:
    with get_connection(database) as connection:
        return {
            table: [
                tuple(row)
                for row in connection.execute(f"SELECT * FROM {table} ORDER BY id")
            ]
            for table in TABLES
        }


def _counts(database: Path) -> Dict[str, int]:
    with get_connection(database) as connection:
        return {
            table: connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in TABLES
        }


def test_validate_real_three_scenario_bundle() -> None:
    bundle = validate_research_bundle(FIXTURE_ROOT, MANIFEST_NAME)

    assert bundle.manifest_sha256 == (
        "cc07c855d71c30d20d59a2ac282b1622402f93bfebeeb5015344c839264312a9"
    )
    assert [scenario for scenario, _ in bundle.artifacts] == list(BUNDLE_SCENARIOS)
    assert [artifact.total_trades for _, artifact in bundle.artifacts] == [11, 9, 9]
    assert [artifact.configured_fee for _, artifact in bundle.artifacts] == [
        0.0005,
        0.0005,
        0.001,
    ]
    assert len({artifact.strategy_sha256 for _, artifact in bundle.artifacts}) == 1
    assert bundle.candidate.metadata["economic_evidence"] == "NOT_EVALUATED"


def test_real_bundle_import_creates_one_complete_honest_loop(tmp_path: Path) -> None:
    database = _database(tmp_path)

    imported = import_research_bundle(database, FIXTURE_ROOT, MANIFEST_NAME)

    assert imported.profile_reused is False
    assert imported.candidate_reused is False
    assert _counts(database) == {
        "research_profiles": 1,
        "generation_runs": 1,
        "candidates": 1,
        "research_runs": 1,
        "backtest_executions": 3,
        "releases": 0,
    }
    with get_connection(database) as connection:
        generation = connection.execute("SELECT * FROM generation_runs").fetchone()
        candidate = connection.execute("SELECT * FROM candidates").fetchone()
        run = connection.execute("SELECT * FROM research_runs").fetchone()
        executions = connection.execute(
            "SELECT * FROM backtest_executions ORDER BY sequence"
        ).fetchall()

    assert generation["source"] == "MANUAL"
    assert generation["status"] == "COMPLETED"
    assert generation["returned_strategy_count"] == 1
    assert candidate["code_sha256"] == (
        "db2d416b5d40daf2dcd8ef8c07a937053c846ca89a9fca1f01facab60dfadc2d"
    )
    assert run["status"] == "COMPLETED"
    assert run["stage"] == "COMPLETED"
    assert run["verdict"] is None
    assert run["freqtrade_version"] == "2026.7"
    assert run["finished_at"] is not None
    assert [row["scenario"] for row in executions] == list(BUNDLE_SCENARIOS)
    assert [row["status"] for row in executions] == ["SUCCEEDED"] * 3
    assert [row["total_trades"] for row in executions] == [11, 9, 9]
    assert [row["fee_multiplier"] for row in executions] == [1.0, 1.0, 2.0]
    assert all(row["command_json"] == "[]" for row in executions)
    assert all(row["config_path"].startswith("zip+file://") for row in executions)
    assert all(row["strategy_path"].startswith("zip+file://") for row in executions)
    for row in executions:
        assert row["return_code"] is None
        assert row["stdout_path"] is None
        assert row["stderr_path"] is None
        assert row["scenario_passed"] is None
        assert row["started_at"] is None
        assert row["finished_at"] is None


def test_second_bundle_reuses_exact_profile_and_candidate_only(tmp_path: Path) -> None:
    database = _database(tmp_path)
    first = import_research_bundle(database, FIXTURE_ROOT, MANIFEST_NAME)

    second = import_research_bundle(database, FIXTURE_ROOT, MANIFEST_NAME)

    assert second.profile_reused is True
    assert second.candidate_reused is True
    assert second.profile_id == first.profile_id
    assert second.candidate_id == first.candidate_id
    assert second.generation_run_id == first.generation_run_id
    assert second.research_run_id != first.research_run_id
    assert _counts(database) == {
        "research_profiles": 1,
        "generation_runs": 1,
        "candidates": 1,
        "research_runs": 2,
        "backtest_executions": 6,
        "releases": 0,
    }


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "unknown"])
def test_manifest_rejects_wrong_scenario_set_and_unknown_fields(
    tmp_path: Path, mutation: str
) -> None:
    root = _copy_bundle(tmp_path)
    manifest = _manifest(root)
    if mutation == "missing":
        manifest["artifacts"].pop()
    elif mutation == "duplicate":
        manifest["artifacts"][2]["scenario"] = "HOLDOUT"
    else:
        manifest["unexpected"] = True
    _write_manifest(root, manifest)

    with pytest.raises(ResearchBundleImportError):
        validate_research_bundle(root, MANIFEST_NAME)


def test_manifest_rejects_duplicate_json_key(tmp_path: Path) -> None:
    root = _copy_bundle(tmp_path)
    original = (root / MANIFEST_NAME).read_text(encoding="utf-8")
    duplicate = original.replace(
        '  "schema": "freqtrade-lab-research-bundle-v1",',
        '  "schema": "freqtrade-lab-research-bundle-v1",\n'
        '  "schema": "freqtrade-lab-research-bundle-v1",',
        1,
    )
    (root / MANIFEST_NAME).write_text(duplicate, encoding="utf-8")

    with pytest.raises(ResearchBundleImportError, match="duplicate JSON key"):
        validate_research_bundle(root, MANIFEST_NAME)


def test_cross_scenario_source_disagreement_fails(tmp_path: Path, monkeypatch) -> None:
    root = _copy_bundle(tmp_path)
    real_parser = research_bundle_module.parse_backtest_artifact

    def divergent_parser(*args, **kwargs):
        parsed = real_parser(*args, **kwargs)
        if Path(args[1]).name == "backtest-result-2026-08-30_06-43-00.zip":
            return replace(parsed, strategy_source=parsed.strategy_source + "\n")
        return parsed

    monkeypatch.setattr(
        research_bundle_module, "parse_backtest_artifact", divergent_parser
    )

    with pytest.raises(ResearchBundleImportError, match="strategy_source"):
        validate_research_bundle(root, MANIFEST_NAME)


def test_bad_provenance_leaves_all_six_tables_unchanged(tmp_path: Path) -> None:
    root = _copy_bundle(tmp_path)
    manifest = _manifest(root)
    manifest["artifacts"][1]["provenance_sha256"] = "0" * 64
    _write_manifest(root, manifest)
    database = _database(tmp_path)
    before = _snapshot(database)

    with pytest.raises(ResearchBundleImportError, match="HOLDOUT artifact"):
        import_research_bundle(database, root, MANIFEST_NAME)

    assert _snapshot(database) == before


def test_profile_holdout_days_must_match_real_artifact_span(tmp_path: Path) -> None:
    root = _copy_bundle(tmp_path)
    manifest = _manifest(root)
    manifest["profile"]["holdout_days"] = 999
    _write_manifest(root, manifest)
    database = _database(tmp_path)
    before = _snapshot(database)

    with pytest.raises(ResearchBundleImportError, match="holdout_days"):
        import_research_bundle(database, root, MANIFEST_NAME)

    assert _snapshot(database) == before


def test_mid_transaction_database_failure_rolls_back_every_row(tmp_path: Path) -> None:
    database = _database(tmp_path)
    with get_connection(database) as connection:
        connection.execute(
            """
            CREATE TRIGGER force_bundle_test_failure
            BEFORE INSERT ON backtest_executions
            WHEN NEW.scenario = 'HOLDOUT'
            BEGIN
                SELECT RAISE(ABORT, 'forced bundle test failure');
            END
            """
        )
        connection.commit()
    before = _snapshot(database)

    with pytest.raises(ResearchBundleImportError, match="forced bundle test failure"):
        import_research_bundle(database, FIXTURE_ROOT, MANIFEST_NAME)

    assert _snapshot(database) == before


@pytest.mark.parametrize(
    ("table", "update", "message"),
    [
        (
            "research_profiles",
            "UPDATE research_profiles SET taker_fee_rate = 0.0006",
            "research profile",
        ),
        (
            "candidates",
            "UPDATE candidates SET display_name = 'conflicting description'",
            "candidate",
        ),
    ],
)
def test_reuse_collision_fails_without_partial_rows(
    tmp_path: Path, table: str, update: str, message: str
) -> None:
    database = _database(tmp_path)
    import_research_bundle(database, FIXTURE_ROOT, MANIFEST_NAME)
    with get_connection(database) as connection:
        connection.execute(update)
        connection.commit()
    before = _snapshot(database)

    with pytest.raises(ResearchBundleImportError, match=message):
        import_research_bundle(database, FIXTURE_ROOT, MANIFEST_NAME)

    assert _snapshot(database) == before
    assert _counts(database)[table] == 1


def test_candidate_reuse_requires_the_same_generation_profile(tmp_path: Path) -> None:
    database = _database(tmp_path)
    import_research_bundle(database, FIXTURE_ROOT, MANIFEST_NAME)
    before = _snapshot(database)
    root = _copy_bundle(tmp_path)
    manifest = _manifest(root)
    manifest["profile"]["name"] = "A different profile with the same strategy"
    _write_manifest(root, manifest)

    with pytest.raises(ResearchBundleImportError, match="generation lineage"):
        import_research_bundle(database, root, MANIFEST_NAME)

    assert _snapshot(database) == before


@pytest.mark.parametrize(
    "update",
    [
        "UPDATE generation_runs SET source = 'CODEX'",
        "UPDATE generation_runs SET status = 'FAILED'",
    ],
)
def test_candidate_reuse_requires_manual_completed_generation(
    tmp_path: Path, update: str
) -> None:
    database = _database(tmp_path)
    import_research_bundle(database, FIXTURE_ROOT, MANIFEST_NAME)
    with get_connection(database) as connection:
        connection.execute(update)
        connection.commit()
    before = _snapshot(database)

    with pytest.raises(ResearchBundleImportError, match="generation lineage"):
        import_research_bundle(database, FIXTURE_ROOT, MANIFEST_NAME)

    assert _snapshot(database) == before


def test_cli_imports_real_bundle(tmp_path: Path) -> None:
    database = _database(tmp_path)

    completed = subprocess.run(
        [
            sys.executable,
            str(CLI),
            "--database",
            str(database),
            "--bundle-root",
            str(FIXTURE_ROOT),
            "--manifest",
            MANIFEST_NAME,
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert "Research bundle imported" in completed.stdout
    assert "Research verdict: not evaluated" in completed.stdout
    assert completed.stderr == ""
    assert _counts(database)["backtest_executions"] == 3


def test_cli_failure_is_exit_2_without_traceback_or_database_changes(
    tmp_path: Path,
) -> None:
    root = _copy_bundle(tmp_path)
    manifest = _manifest(root)
    manifest["profile"]["holdout_days"] = 999
    _write_manifest(root, manifest)
    database = _database(tmp_path)
    before = _snapshot(database)

    completed = subprocess.run(
        [
            sys.executable,
            str(CLI),
            "--database",
            str(database),
            "--bundle-root",
            str(root),
            "--manifest",
            MANIFEST_NAME,
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert completed.stdout == ""
    assert completed.stderr.count("\n") == 1
    assert "Research bundle import failed:" in completed.stderr
    assert "Traceback" not in completed.stderr
    assert _snapshot(database) == before
