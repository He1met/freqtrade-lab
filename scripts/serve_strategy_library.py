#!/usr/bin/env python3
"""Serve the local read-only strategy library on loopback."""

import argparse
import sys
from pathlib import Path
from typing import Optional, Sequence


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from lab.strategy_library import (
    DEFAULT_PORT,
    StrategyLibraryError,
    create_strategy_library_server,
)


def _port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("port must be an integer") from exc
    if not 0 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be from 0 to 65535")
    return port


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--port", type=_port, default=DEFAULT_PORT)
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    server = create_strategy_library_server(args.database, args.port)
    host, port = server.server_address[:2]
    print(f"Strategy library: http://{host}:{port}/", flush=True)
    print(f"JSON API: http://{host}:{port}/api/strategies", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except StrategyLibraryError as exc:
        print(f"Strategy library failed: {exc}", file=sys.stderr)
        raise SystemExit(2)
