#!/usr/bin/env python3
"""Run one Candidate through Development, Holdout, and Holdout Stress."""

import argparse
import json
import shlex
import sqlite3
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Tuple


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from lab.research_candidate import (
    ResearchCandidateError,
    run_research_candidate,
)
from lab.database import init_database
from lab.strategy_library import (
    DEFAULT_PORT,
    StrategyLibraryError,
    validate_strategy_library_database,
)


PRESET_PROVENANCE = "retained-data-provenance.json"
PRESET_RESEARCH_SPEC = "research-spec.json"
_EXPLICIT_INPUTS = (
    ("config", "--config"),
    ("data_dir", "--data-dir"),
    ("strategy_path", "--strategy-path"),
    ("strategy_file", "--strategy-file"),
    ("strategy", "--strategy"),
    ("research_spec", "--research-spec"),
    ("data_provenance", "--data-provenance"),
    ("market_snapshot", "--market-snapshot"),
    ("leverage_tiers", "--leverage-tiers"),
    ("development_timerange", "--development-timerange"),
    ("holdout_timerange", "--holdout-timerange"),
    ("stress_fee_multiplier", "--stress-fee-multiplier"),
)


def _read_json_object(path: Path, label: str) -> Dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ResearchCandidateError(f"{label} cannot be read as JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ResearchCandidateError(f"{label} must be a JSON object")
    return value


def _prepare_workspace(value: Path) -> Path:
    try:
        workspace = value.expanduser()
        workspace.mkdir(parents=True, exist_ok=True)
        workspace = workspace.resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as exc:
        raise ResearchCandidateError(f"workspace cannot be prepared: {exc}") from exc
    if not workspace.is_dir():
        raise ResearchCandidateError("workspace must be a directory")
    return workspace


def _prepare_database(path: Path) -> Path:
    try:
        database = path.expanduser()
        if not database.exists():
            init_database(database)
        return validate_strategy_library_database(database)
    except (StrategyLibraryError, OSError, RuntimeError, ValueError, sqlite3.Error) as exc:
        raise ResearchCandidateError(
            f"workspace database failed schema-v1 validation: {exc}"
        ) from exc


def _preset_arguments(args: argparse.Namespace) -> Tuple[Dict[str, Any], Path]:
    if args.input_root is None or args.workspace is None:
        raise ResearchCandidateError(
            "preset mode requires both --input-root and --workspace"
        )
    conflicts = [option for field, option in _EXPLICIT_INPUTS if getattr(args, field) is not None]
    if conflicts:
        raise ResearchCandidateError(
            "preset mode derives input paths and contracts; remove: " + ", ".join(conflicts)
        )

    try:
        input_root = args.input_root.expanduser().resolve(strict=True)
        provenance_path = input_root / PRESET_PROVENANCE
        research_spec_path = input_root / PRESET_RESEARCH_SPEC
        provenance = _read_json_object(provenance_path, "preset data provenance")
        research_spec = _read_json_object(research_spec_path, "preset research spec")
        contract = provenance["contract"]
        profile = research_spec["profile"]
        candidate = research_spec["candidate"]
        if not all(isinstance(value, dict) for value in (contract, profile, candidate)):
            raise TypeError("contract, profile, and candidate must be JSON objects")
        strategy = candidate["class_name"]
        multiplier = profile["stress_fee_multiplier"]
        if not isinstance(strategy, str) or not strategy:
            raise TypeError("candidate.class_name must be a non-empty string")
        if isinstance(multiplier, bool) or not isinstance(multiplier, (int, float)):
            raise TypeError("profile.stress_fee_multiplier must be numeric")
        config_path = input_root / Path(contract["config"])
        data_path = input_root / Path(contract["data_dir"])
        strategy_file = input_root / Path(contract["strategy"])
        market_path = input_root / Path(contract["market_snapshot"])
        tiers_path = input_root / Path(contract["leverage_tiers"])
        development_timerange = contract["development_timerange"]
        holdout_timerange = contract["holdout_timerange"]
    except ResearchCandidateError:
        raise
    except (KeyError, OSError, RuntimeError, TypeError, ValueError) as exc:
        raise ResearchCandidateError(f"preset contract cannot be mapped: {exc}") from exc

    workspace = _prepare_workspace(args.workspace)
    database = _prepare_database(
        args.database if args.database is not None else workspace / "lab.sqlite"
    )
    if args.output_dir is None:
        artifact_root = workspace / "artifacts"
        try:
            artifact_root.mkdir(exist_ok=True)
            artifact_root = artifact_root.resolve(strict=True)
        except (OSError, RuntimeError, ValueError) as exc:
            raise ResearchCandidateError(
                f"workspace artifact root cannot be prepared: {exc}"
            ) from exc
        output_dir = artifact_root / f"research-{uuid.uuid4().hex}"
        serve_artifact_root = artifact_root
    else:
        output_dir = args.output_dir.expanduser()
        serve_artifact_root = output_dir

    return (
        {
            "freqtrade_python": args.freqtrade_python,
            "freqtrade_source": args.freqtrade_source,
            "config": config_path,
            "data_dir": data_path,
            "strategy_path": strategy_file.parent,
            "strategy_file": strategy_file,
            "strategy": strategy,
            "research_spec": research_spec_path,
            "data_provenance": provenance_path,
            "market_snapshot": market_path,
            "leverage_tiers": tiers_path,
            "development_timerange": development_timerange,
            "holdout_timerange": holdout_timerange,
            "stress_fee_multiplier": float(multiplier),
            "output_dir": output_dir,
            "database": database,
        },
        serve_artifact_root,
    )


def _run_arguments(
    args: argparse.Namespace,
) -> Tuple[Dict[str, Any], Optional[Path]]:
    preset_requested = args.input_root is not None or args.workspace is not None
    if preset_requested:
        return _preset_arguments(args)
    missing = [option for field, option in _EXPLICIT_INPUTS if getattr(args, field) is None]
    if args.output_dir is None:
        missing.append("--output-dir")
    if missing:
        raise ResearchCandidateError(
            "explicit mode requires: " + ", ".join(missing)
        )
    return (
        {
            "freqtrade_python": args.freqtrade_python,
            "freqtrade_source": args.freqtrade_source,
            **{field: getattr(args, field) for field, _ in _EXPLICIT_INPUTS},
            "output_dir": args.output_dir,
            "database": args.database,
        },
        None,
    )


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freqtrade-python", required=True, type=Path)
    parser.add_argument("--freqtrade-source", required=True, type=Path)
    parser.add_argument(
        "--input-root",
        type=Path,
        help="trusted local preset root containing retained provenance and research spec",
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        help="personal workspace for schema-v1 SQLite and unique artifact bundles",
    )
    parser.add_argument("--config", type=Path)
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--strategy-path", type=Path)
    parser.add_argument("--strategy-file", type=Path)
    parser.add_argument("--strategy")
    parser.add_argument("--research-spec", type=Path)
    parser.add_argument("--data-provenance", type=Path)
    parser.add_argument("--market-snapshot", type=Path)
    parser.add_argument("--leverage-tiers", type=Path)
    parser.add_argument("--development-timerange")
    parser.add_argument("--holdout-timerange")
    parser.add_argument("--stress-fee-multiplier", type=float)
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="explicit new bundle path; optional preset-mode override",
    )
    parser.add_argument(
        "--database",
        type=Path,
        help=(
            "explicit schema-v1 SQLite path; preset mode initializes it if missing, "
            "explicit mode preserves the existing no-inference behavior"
        ),
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    run_arguments, serve_artifact_root = _run_arguments(args)
    result = run_research_candidate(**run_arguments)
    print("Research candidate produced")
    print(f"Bundle: {result.bundle_root}")
    print(f"Manifest: {result.manifest_path}")
    print(f"Manifest SHA-256: {result.manifest_sha256}")
    for artifact in result.artifacts:
        print(
            f"{artifact.scenario}: {artifact.archive} | "
            f"trades={artifact.total_trades} | sha256={artifact.archive_sha256}"
        )
    if result.imported is None:
        print("Database import: not requested")
    else:
        print(f"Research run: {result.imported.research_run_id}")
        print("Executions: 3 SUCCEEDED")
    if serve_artifact_root is not None:
        serve_command = (
            sys.executable,
            str(PROJECT_ROOT / "scripts" / "serve_strategy_library.py"),
            "--database",
            str(run_arguments["database"]),
            "--artifact-root",
            str(serve_artifact_root.resolve(strict=True)),
            "--port",
            str(DEFAULT_PORT),
        )
        print(f"Strategy library command: {shlex.join(serve_command)}")
        print(f"Strategy library URL: http://127.0.0.1:{DEFAULT_PORT}/")
    print("Research verdict: not evaluated")
    print("Trading/profitability claim: none")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ResearchCandidateError as exc:
        print(f"Research candidate failed: {exc}", file=sys.stderr)
        raise SystemExit(2)
