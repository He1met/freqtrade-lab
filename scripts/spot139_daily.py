#!/usr/bin/env python3
"""Manual synthetic-only entrypoint. No real observation/acquisition mode exists."""
import argparse
import json
import sys
import tempfile
from pathlib import Path
from decimal import Decimal as D
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lab.spot139_binding import deny_network
from lab.spot139_daily import (Rule, SYMBOLS, candidate_sha, initial_state, pack, unpack,
                              validate_day, initialize, commit_day, committed, write)


def synthetic_fixture(day, price='117', missing=()):
    p = D(price)
    return dict(kind='SYNTHETIC_ONLY', candidate_sha256=candidate_sha(), day=day, received_at_hour=(day+1)*24+1,
                bars={s:[dict(hour=h, ohlc=[str(p),str(p+1),str(p-1),str(p)],full=True)
                         for h in range(day*24,(day+1)*24) if h not in missing] for s in SYMBOLS})


def demo(root):
    r = Rule(D('.001'),D('.001'),D(5),D(1000),D('.000001'),D('.000001'),D('.01'))
    history = {s:{d:(D(100)+D(d)/5,D(101)+D(d)/5,D(99)+D(d)/5,D(100)+D(d)/5) for d in range(85)} for s in SYMBOLS}
    state = pack(initial_state({s:r for s in SYMBOLS},85,history,0))
    initialize(root,state)
    for day, price in [(85,'117'),(86,'85'),(87,'119'),(88,'120')]:
        packet=synthetic_fixture(day,price);write(root/f'fixture-{day}.json',packet)
        commit_day(root,state,packet); state=committed(root)
    return dict(status='SYNTHETIC_DEMO_COMPLETED',root=str(root),days=4,native_instances=0,market_calculations=0,new_gets=0,
                note='Artificial prices; candidate not qualified; no real execution mode')


def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    d=sub.add_parser('demo');d.add_argument('--root',help='New synthetic output directory; defaults to a temporary directory')
    for command in ('check','apply','init'):
        q=sub.add_parser(command);q.add_argument('--state',required=True)
        if command!='init':q.add_argument('--day',required=True)
        if command!='check':q.add_argument('--root',required=True)
    args=p.parse_args();sys.addaudithook(deny_network)
    if args.command=='demo':
        root=Path(args.root) if args.root else Path(tempfile.mkdtemp(prefix='spot139-demo-parent-'))/'synthetic'
        print(json.dumps(demo(root)));return
    envelope=json.loads(Path(args.state).read_bytes());state=unpack(envelope)
    if args.command=='init':initialize(args.root,envelope);print('SYNTHETIC_ROOT_CREATED');return
    packet=json.loads(Path(args.day).read_bytes());validate_day(packet,state)
    if args.command=='check':print('SYNTHETIC_CHECK_PASS_NO_COMPUTATION_OR_WRITE');return
    print(json.dumps(commit_day(args.root,envelope,packet)))


if __name__=='__main__':main()
