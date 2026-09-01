#!/usr/bin/env python3
"""Private child entrypoint for the fixed one-shot Holdout continuation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional, Sequence


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from lab.holdout_run import HoldoutRunError, execute_holdout_continuation


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
        result = execute_holdout_continuation(
            args.database,
            args.run_dir,
            args.research_run_id,
            args.freqtrade_python,
            args.freqtrade_source,
        )
    except HoldoutRunError as exc:
        print(
            json.dumps(
                {"status": "FAILED", "code": exc.code, "message": exc.message},
                sort_keys=True,
                separators=(",", ":"),
            ),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
