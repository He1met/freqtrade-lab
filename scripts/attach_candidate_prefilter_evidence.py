#!/usr/bin/env python3
"""Attach one reviewed PRE_SEARCH capacity failure without running research."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lab.codex_generation import attach_prefilter_evidence, GenerationContractError


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--candidate-id', required=True)
    parser.add_argument('--evidence-root', type=Path, required=True)
    parser.add_argument('--terminal-sha256', required=True)
    parser.add_argument('--boundary-sha256', required=True)
    args = parser.parse_args()
    try:
        value = attach_prefilter_evidence(args.database, args.candidate_id, args.evidence_root,
                                         terminal_sha256=args.terminal_sha256, boundary_sha256=args.boundary_sha256)
    except GenerationContractError as exc:
        parser.exit(1, f'{exc.code}: {exc.message}\n')
    print(json.dumps(value, ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    main()
