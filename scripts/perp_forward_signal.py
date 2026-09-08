#!/usr/bin/env python3
"""Persist observed signals only; no network, matching, native runs or account access."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from lab.perp_forward_signal import run


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['check','tick','activate'])
    for name in ('root','registration','protocol','binding','seed-root','incremental-root'):
        parser.add_argument('--'+name,required=True,type=Path)
    parser.add_argument('--native-acceptance',type=Path)
    parser.add_argument('--native-acceptance-sha256')
    parser.add_argument('--runtime-policy',type=Path)
    args=parser.parse_args()
    print(json.dumps(run(args.root,args.registration,args.protocol,args.binding,args.seed_root,
        args.incremental_root,args.command,native_acceptance_path=args.native_acceptance,
        native_acceptance_sha256=args.native_acceptance_sha256,runtime_policy_path=args.runtime_policy),ensure_ascii=False,allow_nan=False))


if __name__=='__main__': main()
