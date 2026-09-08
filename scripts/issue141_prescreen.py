#!/usr/bin/env python3
"""One externally authorized, offline exposed-data event analysis; no wallet."""
import argparse
from collections import Counter
from contextlib import contextmanager, ExitStack
from datetime import datetime, timezone
from decimal import Decimal as D, getcontext
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import sys
import time

getcontext().prec = 50
REPO = Path(__file__).resolve().parents[1]
ROOT = Path('/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue141-hourly-prescreen-v1')
COSTS = {'base': (D('.001'), D('.0006')), 'stress': (D('.002'), D('.0012'))}
CELLS = ['C/base', 'C/stress', 'R/base', 'R/stress']


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def utc():
    return datetime.now(timezone.utc).isoformat()


def write(path, data):
    with Path(path).open('x') as stream:
        json.dump(data, stream, indent=2, default=str, allow_nan=False)
        stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
    sync(Path(path).parent)


def sync(path):
    fd = os.open(path, os.O_RDONLY)
    try: os.fsync(fd)
    finally: os.close(fd)


@contextmanager
def deadline(seconds):
    if seconds <= 0: raise TimeoutError('deadline expired')
    def expired(*_): raise TimeoutError('180-second task deadline')
    old = signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try: yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0); signal.signal(signal.SIGALRM, old)


def net(gross, cost):
    f, s = COSTS[cost]
    return (1 + gross) * (1 - s) / (1 + s) * (1 - f) ** 2 - 1


def datepart(hour, kind):
    return datetime.fromtimestamp(hour * 3600, timezone.utc).strftime(kind)


def distribution(values):
    n = len(values)
    if not n: return dict(n=0, mean=None, median=None, stddev=None, positive_fraction=None, worst=None)
    mean = sum(values, D(0)) / n; ordered = sorted(values)
    return dict(n=n, mean=mean, median=(ordered[(n-1)//2]+ordered[n//2])/2,
                stddev=(sum(((x-mean)**2 for x in values), D(0))/(n-1)).sqrt() if n>1 else None,
                positive_fraction=D(sum(x>0 for x in values))/n, worst=min(values))


def summarize(rows, cost, periods):
    scored = [r for r in rows if r['status']=='SCORED']
    vals = [net(r['gross'], cost) for r in scored]
    positive = sum((max(x, D(0)) for x in vals), D(0))
    months = {}
    years = {}
    for k in periods:
        v = [net(r['gross'], cost) for r in scored if r['month']==k]
        months[k] = dict(triggered=sum(r['month']==k for r in rows), net=distribution(v),
                         gross=distribution([r['gross'] for r in scored if r['month']==k]))
    for k in sorted({x[:4] for x in periods}):
        rs = [r for r in scored if r['month'].startswith(k)]
        years[k] = dict(triggered=sum(r['month'].startswith(k) for r in rows),
                       net=distribution([net(r['gross'], cost) for r in rs]), gross=distribution([r['gross'] for r in rs]))
    clusters = longest = run = 0; previous = None
    for r in rows:
        if previous is None or r['t'] != previous+1: clusters += 1; run = 0
        run += 1; longest = max(longest, run); previous = r['t']
    monthly_positive = [sum((max(net(r['gross'], cost), D(0)) for r in scored if r['month']==k), D(0)) for k in periods]
    return dict(triggered=len(rows), status_counts=dict(Counter(r['status'] for r in rows)),
                net=distribution(vals), gross=distribution([r['gross'] for r in scored]),
                years=years, months=months, adjacent_trigger_clusters=clusters, longest_trigger_run=longest,
                largest_positive_event_share=max([max(x,D(0)) for x in vals], default=D(0))/positive if positive else None,
                largest_positive_month_share=max(monthly_positive, default=D(0))/positive if positive else None,
                event_return_sum_is_not_wallet_pnl=True)


def analyze(bars, start, end):
    events = []; unavailable = []; nontrigger = 0
    for t in range(start, end):
        if any(t not in bars[s] or not bars[s][t]['full'] for s in ['BTCUSDT','ETHUSDT']):
            unavailable.append(t); continue
        btc, eth = bars['BTCUSDT'][t], bars['ETHUSDT'][t]
        if eth['close'] > eth['open']: nontrigger += 1; continue
        c = btc['close'] > btc['open']; missing = []
        for label, h in [('ENTRY_OPEN_MISSING',t+1),('EXIT_OPEN_MISSING',t+2)]:
            if h>=end or h not in bars['ETHUSDT']: missing.append(label)
        row = dict(t=t, month=datepart(t,'%Y-%m'), C=c, R=True, entry_hour=t+1, exit_hour=t+2,
                   status='+'.join(missing) if missing else 'SCORED', gross=None,
                   execution_short_hours=[h for h in [t+1,t+2] if h<end and h in bars['ETHUSDT'] and not bars['ETHUSDT'][h]['full']])
        if not missing: row['gross']=bars['ETHUSDT'][t+2]['open']/bars['ETHUSDT'][t+1]['open']-1
        events.append(row)
    periods=sorted({datepart(t,'%Y-%m') for t in range(start,end)})
    cells = {f'{condition}/{cost}': summarize([r for r in events if r[condition]],cost,periods)
             for condition in ['C','R'] for cost in COSTS}
    differences={}
    for cost in COSTS:
        c=cells['C/'+cost]['net']['mean']; r=cells['R/'+cost]['net']['mean']
        differences[cost]=c-r if c is not None and r is not None else None
    if any(cells['C/'+cost]['net']['mean'] is None or differences[cost] is None for cost in COSTS): verdict='INSUFFICIENT_EVIDENCE'
    elif any(cells['C/'+cost]['net']['mean']<=0 or differences[cost]<=0 for cost in COSTS): verdict='STOP_RULE_NOT_SUPPORTED'
    else: verdict='POSITIVE_DESCRIPTIVE_ONLY_REQUIRES_SUPERVISOR_REVIEW'
    return dict(cells=cells, mean_C_minus_R=differences, verdict=verdict, independent_qualification=False,
                input_unscorable_hours=unavailable, complete_nontrigger_hours=nontrigger,
                total_signal_hours=end-start, shared_C_R_events=cells['C/base']['triggered'],
                missing_event_details=[r for r in events if r['status']!='SCORED'],
                execution_short_event_details=[r for r in events if r['execution_short_hours']]), events


def load_sources(m):
    bars = {'BTCUSDT':{}, 'ETHUSDT':{}}
    for src in m['sources']:
        if sha(src['path'])!=src['sha256']: raise ValueError('source SHA drift')
    for src in m['sources']:
        q=src['request']
        if q.get('interval')!='1h': continue  # metadata and 2020 daily warmup: hash only
        s=q['symbol']; last=None
        for x in json.loads(Path(src['path']).read_bytes()):
            if not isinstance(x,list) or len(x)!=12 or type(x[0]) is not int or type(x[6]) is not int: raise ValueError('kline shape')
            t=x[0]//3600000
            if x[0]%3600000 or not m['start']<=t<m['end'] or t in bars[s] or (last is not None and t<=last): raise ValueError('time/duplicate/order')
            if not q['startTime']<=x[0]<=q['endTime'] or not x[0]<=x[6]<x[0]+3600000: raise ValueError('request/close boundary')
            o,h,l,c=map(D,x[1:5]); volume=D(x[5])
            if not all(v.is_finite() and v>0 for v in [o,h,l,c]) or not volume.is_finite() or volume<0 or not l<=min(o,c)<=max(o,c)<=h: raise ValueError('OHLC invalid')
            bars[s][t]=dict(open=o,close=c,full=x[6]==x[0]+3599999);last=t
    for s in bars:
        observed=[dict(kind='MISSING',open_ms=t*3600000) for t in range(m['start'],m['end']) if t not in bars[s]]
        observed += [dict(kind='SHORT',open_ms=t*3600000) for t,r in bars[s].items() if not r['full']]
        expected=[{k:a[k] for k in ['kind','open_ms']} for a in m['anomalies'][s]]
        if sorted(observed,key=lambda a:a['open_ms'])!=sorted(expected,key=lambda a:a['open_ms']): raise ValueError('anomaly inventory drift')
    return bars


def check(m):
    if m['root']!=str(ROOT) or m['cells']!=CELLS or m['budget']!={'invocations':1,'cells':4,'seconds':180,'retries':0}: raise ValueError('identity/budget')
    if (m['start'],m['end'])!=(447072,464592) or m['costs']!={k:[str(x) for x in v] for k,v in COSTS.items()}: raise ValueError('window/cost')
    for p,h in m['bindings'].items():
        if sha(p)!=h: raise ValueError('control/code binding drift: '+p)
    old=json.loads((REPO/'docs/issue139-v3-first-diagnostics-manifest.json').read_bytes())
    inv=json.loads((REPO/'docs/issue139-source-inventory-v3-terminal.json').read_bytes())
    if m['sources']!=old['sources'] or len(m['sources'])!=39: raise ValueError('source manifest')
    if m['anomalies']!={s:v['anomalies'] for s,v in inv['symbols'].items()}: raise ValueError('anomaly identity')


def once(root, action, seconds=180, identity=None):
    root=Path(root)
    root.mkdir()  # Existing root, including a failed attempt, rejects without retry.
    sync(root.parent)
    write(root/'attempt.json',dict(event='ATTEMPT',at_utc=utc(),identity=identity,invocations=1,cells_limit=4,retries=0))
    started=time.monotonic()
    try:
        with deadline(seconds): result=action(root)
        write(root/'terminal.json',dict(status='SUCCEEDED',elapsed_seconds=time.monotonic()-started,at_utc=utc(),**result))
    except BaseException as exc:
        write(root/'terminal.json',dict(status='FAILED',error=type(exc).__name__+': '+str(exc),elapsed_seconds=time.monotonic()-started,at_utc=utc()))
        raise


def main():
    parser=argparse.ArgumentParser();parser.add_argument('command',choices=['check','execute']);parser.add_argument('--manifest',required=True);parser.add_argument('--sha256',required=True)
    parser.add_argument('--grant');parser.add_argument('--grant-sha256');a=parser.parse_args()
    if sha(a.manifest)!=a.sha256: raise ValueError('manifest SHA')
    m=json.loads(Path(a.manifest).read_bytes());check(m)
    if a.command=='check': print('CONTROL_CHECK_PASS_NO_RAW_READ');return
    if not a.grant or sha(a.grant)!=a.grant_sha256: raise ValueError('grant SHA')
    g=json.loads(Path(a.grant).read_bytes())
    if g!={'authorized':True,'manifest_sha256':a.sha256,'authorization_reference':m['authorization_reference'],'root':m['root'],'budget':m['budget']}: raise ValueError('exact grant')
    with ExitStack() as stack:
        for path in m['lock_paths']:
            stream=stack.enter_context(Path(path).open('r'));fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
        check(m)
        def deny(event,args):
            if event in ('socket.connect','socket.getaddrinfo','socket.bind'): raise ValueError('network forbidden')
        sys.addaudithook(deny)
        def work(root):
            bars=load_sources(m);summary,events=analyze(bars,m['start'],m['end'])
            summary.update(source_anomalies=m['anomalies'],source_grade='EXPOSED_DEVELOPMENT',cells_completed=4)
            write(root/'events.json',events);write(root/'summary.json',summary)
            check(m)
            for src in m['sources']:
                if sha(src['path'])!=src['sha256']:raise ValueError('post source drift')
            return dict(manifest_sha256=a.sha256,grant_sha256=a.grant_sha256,summary_sha256=sha(root/'summary.json'),events_sha256=sha(root/'events.json'),source_code_postcheck='PASS',cells_completed=4,verdict=summary['verdict'])
        once(ROOT,work,180,dict(manifest_sha256=a.sha256,grant_sha256=a.grant_sha256))
    print((ROOT/'terminal.json').read_text())


if __name__=='__main__': main()
