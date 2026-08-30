#!/usr/bin/env python3
"""Import one verified Freqtrade backtest artifact into an existing execution."""

import argparse
import sys
from pathlib import Path
from typing import Optional, Sequence


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from lab.backtest_artifact import (
    SUPPORTED_FREQTRADE_VERSION,
    SUPPORTED_SCENARIOS,
    ArtifactImportError,
    import_backtest_execution,
)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--artifact-root", required=True, type=Path)
    parser.add_argument(
        "--archive",
        required=True,
        type=Path,
        help="Relative backtest-result-*.zip path inside artifact root",
    )
    parser.add_argument("--research-run-id", required=True)
    parser.add_argument("--scenario", required=True, choices=SUPPORTED_SCENARIOS)
    parser.add_argument("--strategy", required=True)
    parser.add_argument(
        "--freqtrade-version",
        required=True,
        help=f"Attested artifact version; only {SUPPORTED_FREQTRADE_VERSION} is supported",
    )
    parser.add_argument(
        "--provenance-sha256",
        required=True,
        help="Trusted SHA-256 receipt for the same-stem provenance JSON",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    parsed = import_backtest_execution(
        args.database,
        args.artifact_root,
        args.archive,
        args.research_run_id,
        args.scenario,
        args.strategy,
        args.freqtrade_version,
        args.provenance_sha256,
    )
    print("Backtest artifact imported")
    print(f"Research run: {args.research_run_id}")
    print(f"Scenario: {args.scenario}")
    print(f"Strategy: {parsed.strategy}")
    print(f"Freqtrade version: {parsed.freqtrade_version}")
    print(f"Freqtrade commit: {parsed.freqtrade_commit}")
    print(f"Trades: {parsed.total_trades}")
    print(f"Archive SHA-256: {parsed.archive_sha256}")
    print(f"Provenance SHA-256: {parsed.provenance_sha256}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ArtifactImportError as exc:
        print(f"Backtest artifact import failed: {exc}", file=sys.stderr)
        raise SystemExit(2)
