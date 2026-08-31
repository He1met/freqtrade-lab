#!/usr/bin/env python3
"""Serve the local Research Console and Strategy Library on one loopback port."""

import argparse
import sys
from pathlib import Path
from typing import Optional, Sequence


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from lab.research_console import create_research_console_server
from lab.strategy_library import DEFAULT_PORT, StrategyLibraryError


def _port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("port must be an integer") from exc
    if not 0 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be from 0 to 65535")
    return port


def _timeout(value: str) -> float:
    try:
        timeout = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("timeout must be a number") from exc
    if not 0.1 <= timeout <= 86400:
        raise argparse.ArgumentTypeError("timeout must be from 0.1 to 86400 seconds")
    return timeout


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--runtime-root", required=True, type=Path)
    parser.add_argument("--pilot-root", required=True, type=Path)
    parser.add_argument("--artifact-root", type=Path)
    parser.add_argument("--frequi-base-url")
    parser.add_argument("--frequi-results-root", type=Path)
    parser.add_argument("--codex-binary", type=Path)
    parser.add_argument(
        "--codex-model",
        help="trusted startup-frozen Codex model; never accepted from the browser",
    )
    parser.add_argument(
        "--check-data-python",
        type=Path,
        default=Path(sys.executable),
        help="trusted startup-frozen Python/fake executable for fixed CHECK_DATA argv",
    )
    parser.add_argument(
        "--freqtrade-python",
        type=Path,
        help="startup-frozen Freqtrade 2026.7 Python for Development research",
    )
    parser.add_argument(
        "--freqtrade-source",
        type=Path,
        help="startup-frozen clean Freqtrade 2026.7 source checkout",
    )
    parser.add_argument(
        "--webserver-base-url",
        default="http://127.0.0.1:8080",
        help="public numeric-loopback Freqtrade/FreqUI probe origin",
    )
    parser.add_argument("--task-timeout-seconds", type=_timeout, default=300.0)
    parser.add_argument("--port", type=_port, default=DEFAULT_PORT)
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    server = create_research_console_server(
        args.database,
        args.runtime_root,
        args.pilot_root,
        args.port,
        artifact_root=args.artifact_root,
        frequi_base_url=args.frequi_base_url,
        frequi_results_root=args.frequi_results_root,
        codex_binary=args.codex_binary,
        codex_model=args.codex_model,
        check_data_python=args.check_data_python,
        freqtrade_python=args.freqtrade_python,
        freqtrade_source=args.freqtrade_source,
        webserver_base_url=args.webserver_base_url,
        task_timeout_seconds=args.task_timeout_seconds,
    )
    host, port = server.server_address[:2]
    print(f"Research Console: http://{host}:{port}/console", flush=True)
    print(f"Strategy Library: http://{host}:{port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        try:
            server.research_console_controller.shutdown()
        finally:
            server.server_close()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except StrategyLibraryError as exc:
        print(f"Research Console failed: {exc}", file=sys.stderr)
        raise SystemExit(2)
