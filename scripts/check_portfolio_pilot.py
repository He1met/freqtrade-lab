#!/usr/bin/env python3
"""Read metadata only; print admission report. No subprocess/network/DB writes."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lab.portfolio_preflight import AdmissionError, PROTOCOL_PATH, load_protocol, preflight, read_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=PROTOCOL_PATH)
    parser.add_argument("--registry", type=Path, help="curated sanitized control metadata, never raw market data")
    parser.add_argument("--exchange-info", type=Path, help="normalized anonymous exchange rules")
    args = parser.parse_args()
    try:
        protocol = load_protocol(args.protocol)
        report = preflight(protocol,
                           registry=read_json(args.registry)[0] if args.registry else None,
                           exchange=read_json(args.exchange_info)[0] if args.exchange_info else None)
    except (AdmissionError, OSError) as exc:
        # No local paths, raw JSON, or source exception payload in public output.
        report = {"status": "INVALID_METADATA", "market_execution_allowed": False,
                  "error": str(exc) if isinstance(exc, AdmissionError) else "metadata file unavailable"}
        print(json.dumps(report, sort_keys=True))
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "METADATA_VALIDATED_ONLY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
