#!/usr/bin/env python3
"""Read one local mechanism card; emit a deterministic JSON precheck, never run."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from lab.mechanism_precheck import read_card,precheck,serial,PrecheckError


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--card',type=Path,required=True)
    args=parser.parse_args()
    try:
        card,sha=read_card(args.card);result=precheck(card);result['card_sha256']=sha
    except (PrecheckError,OSError) as exc:
        print(json.dumps({'status':'PRECHECK_BLOCKED','reason_code':'INVALID_OR_DRIFTED_INPUT','detail':str(exc)},ensure_ascii=False))
        raise SystemExit(2)
    print(json.dumps(serial(result),sort_keys=True,ensure_ascii=False,allow_nan=False))


if __name__=='__main__':main()
