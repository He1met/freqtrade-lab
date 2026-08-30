#!/usr/bin/env python3
"""Validate and atomically import one three-scenario research bundle."""

import argparse
import sys
from pathlib import Path
from typing import Optional, Sequence


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from lab.research_bundle import ResearchBundleImportError, import_research_bundle


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--bundle-root", required=True, type=Path)
    parser.add_argument(
        "--manifest",
        required=True,
        type=Path,
        help="Relative manifest JSON path inside bundle root",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    imported = import_research_bundle(
        args.database,
        args.bundle_root,
        args.manifest,
    )
    print("Research bundle imported")
    print(f"Research run: {imported.research_run_id}")
    print(f"Profile: {imported.profile_id}")
    print(f"Candidate: {imported.candidate_id}")
    print("Scenarios: DEVELOPMENT, HOLDOUT, HOLDOUT_STRESS")
    print("Research verdict: not evaluated")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ResearchBundleImportError as exc:
        print(f"Research bundle import failed: {exc}", file=sys.stderr)
        raise SystemExit(2)
