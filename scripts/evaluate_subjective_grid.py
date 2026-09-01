#!/usr/bin/env python3
"""Evaluate one frozen subjective-grid ticket against one frozen OHLCV CSV."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional, Sequence


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from lab.subjective_grid import (
    RESULT_FILENAME,
    SUMMARY_FILENAME,
    SubjectiveGridError,
    evaluate_subjective_grid,
)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticket", required=True, type=Path)
    parser.add_argument("--data", required=True, type=Path)
    parser.add_argument(
        "--output-dir",
        required=True,
        type=Path,
        help="New output directory; existing paths are never replaced",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    try:
        result = evaluate_subjective_grid(args.ticket, args.data, args.output_dir)
    except SubjectiveGridError as exc:
        print(f"Subjective grid evaluation failed: {exc}", file=sys.stderr)
        return 2
    output = args.output_dir.expanduser().resolve()
    print(
        json.dumps(
            {
                "status": "PUBLISHED",
                "verdict": result["gate"]["verdict"],
                "economic_evidence_status": result["gate"]["economic_evidence_status"],
                "result": str(output / RESULT_FILENAME),
                "summary": str(output / SUMMARY_FILENAME),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
