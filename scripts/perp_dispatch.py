#!/usr/bin/env python3
"""One confirmation wait plus one bounded development task; no market execution."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from lab import perp_dispatch as d


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',required=True);p.add_argument('--policy',required=True)
    p.add_argument('--dispatch-policy',required=True)
    p.add_argument('command',choices=['install','status','enqueue','claim','check-inputs'])
    p.add_argument('--task-json');p.add_argument('--task-id');a=p.parse_args()
    args=(a.root,a.policy,a.dispatch_policy)
    if a.command=='enqueue': result=d.enqueue(*args,json.loads(Path(a.task_json).read_bytes()))
    elif a.command=='claim':result=d.claim(*args,a.task_id)
    elif a.command=='check-inputs':
        policy,_=d.load(a.dispatch_policy,a.policy)
        result=d.development_inputs(a.root,json.loads(Path(a.task_json).read_bytes()),policy)
    else:result=getattr(d,a.command)(*args)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True,allow_nan=False))


if __name__=='__main__':main()
