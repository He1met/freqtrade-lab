#!/usr/bin/env python3
"""Validate one frozen literature batch offline; emit knowledge cards, never execute."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lab.literature_discovery import discover, read_batch
from lab.mechanism_precheck import PrecheckError, serial


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--batch', type=Path, required=True)
    parser.add_argument('--cache-root', type=Path, required=True)
    args = parser.parse_args()
    try:
        batch, digest = read_batch(args.batch)
        result = discover(batch, args.cache_root)
        result['batch_sha256'] = digest
    except (PrecheckError, OSError, ValueError, TypeError, RecursionError) as exc:
        print(json.dumps(dict(status='DISCOVERY_BLOCKED', reason='INVALID_OR_DRIFTED_INPUT', detail=str(exc))))
        return 2
    print(json.dumps(serial(result), sort_keys=True, ensure_ascii=False, allow_nan=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
