#!/usr/bin/env python3
"""Attach a reviewed, hash-pinned Search protocol rejection without running research."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lab.search_campaign import attach_search_protocol_rejection, SearchCampaignError


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--campaign-id', required=True)
    parser.add_argument('--review-path', type=Path, required=True)
    parser.add_argument('--archive-path', type=Path, required=True)
    parser.add_argument('--review-sha256', required=True)
    args = parser.parse_args()
    try:
        value = attach_search_protocol_rejection(args.database, args.campaign_id,
            args.review_path, args.archive_path, review_sha256=args.review_sha256)
    except SearchCampaignError as exc:
        parser.exit(1, f'{exc.code}: {exc.message}\n')
    print(json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False))


if __name__ == '__main__':
    main()
