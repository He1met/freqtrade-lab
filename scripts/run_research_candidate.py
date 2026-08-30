#!/usr/bin/env python3
"""Run one Candidate through Development, Holdout, and Holdout Stress."""

import argparse
import sys
from pathlib import Path
from typing import Optional, Sequence


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from lab.research_candidate import (
    ResearchCandidateError,
    run_research_candidate,
)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freqtrade-python", required=True, type=Path)
    parser.add_argument("--freqtrade-source", required=True, type=Path)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--strategy-path", required=True, type=Path)
    parser.add_argument("--strategy-file", required=True, type=Path)
    parser.add_argument("--strategy", required=True)
    parser.add_argument("--research-spec", required=True, type=Path)
    parser.add_argument("--data-provenance", required=True, type=Path)
    parser.add_argument("--market-snapshot", required=True, type=Path)
    parser.add_argument("--leverage-tiers", required=True, type=Path)
    parser.add_argument("--development-timerange", required=True)
    parser.add_argument("--holdout-timerange", required=True)
    parser.add_argument("--stress-fee-multiplier", required=True, type=float)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument(
        "--database",
        type=Path,
        help="Optional existing schema-v1 SQLite path; never inferred or initialized",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    result = run_research_candidate(
        freqtrade_python=args.freqtrade_python,
        freqtrade_source=args.freqtrade_source,
        config=args.config,
        data_dir=args.data_dir,
        strategy_path=args.strategy_path,
        strategy_file=args.strategy_file,
        strategy=args.strategy,
        research_spec=args.research_spec,
        data_provenance=args.data_provenance,
        market_snapshot=args.market_snapshot,
        leverage_tiers=args.leverage_tiers,
        development_timerange=args.development_timerange,
        holdout_timerange=args.holdout_timerange,
        stress_fee_multiplier=args.stress_fee_multiplier,
        output_dir=args.output_dir,
        database=args.database,
    )
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
    print("Research verdict: not evaluated")
    print("Trading/profitability claim: none")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ResearchCandidateError as exc:
        print(f"Research candidate failed: {exc}", file=sys.stderr)
        raise SystemExit(2)
