#!/usr/bin/env python3
"""Private child entrypoint for one Development-only Candidate backtest."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional, Sequence


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from lab.development_run import DevelopmentRunError, execute_development_run


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--research-run-id", required=True)
    parser.add_argument("--freqtrade-python", required=True, type=Path)
    parser.add_argument("--freqtrade-source", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    try:
        result = execute_development_run(
            args.database,
            args.run_dir,
            args.research_run_id,
            args.freqtrade_python,
            args.freqtrade_source,
        )
    except DevelopmentRunError as exc:
        print(
            json.dumps(
                {"status": "FAILED", "code": exc.code, "message": exc.message},
                sort_keys=True,
                separators=(",", ":"),
            ),
            file=sys.stderr,
        )
        return 2
    print(
        json.dumps(
            {
                "status": result["status"],
                "research_run_id": result["research_run_id"],
                "verdict": result["verdict"],
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
