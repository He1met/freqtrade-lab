#!/usr/bin/env python3
"""Prepare only; corrected native runs require a separate reviewed activation."""
import argparse
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from lab.portfolio_corrected import prepare,run,encoded


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare',action='store_true')
    parser.add_argument('--run-key')
    args=parser.parse_args()
    if args.prepare==bool(args.run_key):parser.error('choose --prepare or --run-key')
    result=prepare() if args.prepare else run(args.run_key)
    print(encoded(result).decode())
    if args.run_key and result['status']!='SUCCEEDED':raise SystemExit(2)


if __name__=='__main__':main()
