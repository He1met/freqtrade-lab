#!/usr/bin/env python3
"""Thin command-line entry point for the bounded research implementation."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from lab.bounded_research import PilotError, main


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except PilotError as exc:
        print(
            f"Bounded research Pilot failed: {' '.join(str(exc).split())}",
            file=sys.stderr,
        )
        raise SystemExit(2)
