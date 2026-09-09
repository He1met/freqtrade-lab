#!/usr/bin/env python3
"""Package bounded native Binance download responses for a frozen Profile."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from lab.binance_source import compile_source, capture_native, validate_output_path
from scripts.fetch_okx_profile_data import configure_profile_acquisition


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile-database',type=Path,required=True)
    parser.add_argument('--profile-id')
    parser.add_argument('--window-spec',type=Path)
    parser.add_argument('--pre-roll-candles',type=int)
    parser.add_argument('--economic-gate',type=Path)
    parser.add_argument('--single-baseline',type=Path)
    parser.add_argument('--authorize-holdout-source')
    parser.add_argument('--http-receipts',type=Path)
    parser.add_argument('--raw-dir',type=Path)
    parser.add_argument('--capture-root',type=Path,help='New Git-external directory for one bounded native download')
    parser.add_argument('--output-root',type=Path)
    args=parser.parse_args()
    if args.capture_root:
        if args.http_receipts or args.raw_dir:
            parser.error('Choose native capture or retained responses, not both')
    elif args.http_receipts is None or args.raw_dir is None:
        parser.error('Retained mode requires --http-receipts and --raw-dir')
    if args.authorize_holdout_source:
        if any(v is not None for v in (args.profile_id,args.window_spec,args.pre_roll_candles,args.output_root,args.economic_gate,args.single_baseline)):
            parser.error('Holdout forbids Profile/window/output overrides')
        from lab.holdout_run import authorize_profile_holdout_source
        output,auth=authorize_profile_holdout_source(args.profile_database,args.authorize_holdout_source)
        contract={'profile_snapshot':auth['profile_snapshot'],'pre_roll_candles':auth['pre_roll_candles'],'holdout_source':auth}
    else:
        if any(v is None for v in (args.profile_id,args.window_spec,args.pre_roll_candles,args.output_root)):
            parser.error('Profile source requires Profile/window/pre-roll/output')
        economic=None if args.economic_gate is None else json.loads(args.economic_gate.read_bytes())
        baseline=None if args.single_baseline is None else json.loads(args.single_baseline.read_bytes())
        contract=configure_profile_acquisition(args.profile_database,args.profile_id,args.window_spec,args.pre_roll_candles,economic,baseline)
        output=args.output_root
    output=validate_output_path(output)
    receipts, raw = (capture_native(args.capture_root, contract) if args.capture_root
                     else (args.http_receipts, args.raw_dir))
    print(json.dumps(compile_source(output,receipts,raw,contract)))


if __name__=='__main__':main()
