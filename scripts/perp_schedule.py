#!/usr/bin/env python3
"""Persist due work and receipts; this CLI does not execute market research."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lab import perp_schedule as s


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',required=True); parser.add_argument('--policy',required=True)
    parser.add_argument('command',choices=['status','tick','enqueue','claim','ready','finish','migrate-policy','materialize'])
    parser.add_argument('--task-json'); parser.add_argument('--task-id')
    parser.add_argument('--summary'); parser.add_argument('--report')
    parser.add_argument('--new-policy')
    parser.add_argument('--preflight')
    args=parser.parse_args()
    if args.command=='status': result=s.read_status(args.root,args.policy)
    elif args.command=='tick': result=s.tick(args.root,args.policy)
    elif args.command=='enqueue': result=s.enqueue(args.root,args.policy,json.loads(Path(args.task_json).read_bytes()))
    elif args.command=='finish': result=s.finish(args.root,args.policy,args.task_id,args.summary,args.report)
    elif args.command=='migrate-policy': result=s.migrate_policy(args.root,args.policy,args.new_policy,args.task_id)
    elif args.command=='materialize': result=s.materialize(args.root,args.policy,args.task_id,args.preflight)
    else: result=getattr(s,args.command)(args.root,args.policy,args.task_id)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True,allow_nan=False))


if __name__=='__main__':
    main()
