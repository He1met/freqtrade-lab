#!/usr/bin/env python3
"""Attach one verified diagnostic comparison; never execute research."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lab.research_comparison import attach_comparison, ComparisonError

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--search-root", type=Path, help="Configured Search root; required for S")
    parser.add_argument("--artifact-root", type=Path, help="Separate artifact root with S derivative directory; required for S")
    args = parser.parse_args()
    try:
        print(json.dumps(attach_comparison(args.database, args.manifest, args.manifest_sha256,
                         search_root=args.search_root, artifact_root=args.artifact_root), allow_nan=False))
    except ComparisonError as exc:
        print(json.dumps({"error": "invalid_cost_comparison", "message": str(exc)}), file=sys.stderr)
        return 1
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
