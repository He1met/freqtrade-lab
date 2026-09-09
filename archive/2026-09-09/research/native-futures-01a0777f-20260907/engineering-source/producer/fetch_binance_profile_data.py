#!/usr/bin/env python3
"""Package bounded native Binance download responses for a frozen Profile."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from lab.binance_source import compile_source
from scripts.fetch_okx_profile_data import configure_profile_acquisition


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile-database',type=Path,required=True)
    parser.add_argument('--profile-id',required=True)
    parser.add_argument('--window-spec',type=Path,required=True)
    parser.add_argument('--pre-roll-candles',type=int,required=True)
    parser.add_argument('--http-receipts',type=Path,required=True)
    parser.add_argument('--raw-dir',type=Path,required=True)
    parser.add_argument('--output-root',type=Path,required=True)
    args=parser.parse_args()
    contract=configure_profile_acquisition(args.profile_database,args.profile_id,args.window_spec,args.pre_roll_candles)
    print(json.dumps(compile_source(args.output_root,args.http_receipts,args.raw_dir,contract)))


if __name__=='__main__':main()
