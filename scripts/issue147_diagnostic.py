#!/usr/bin/env python3
"""One externally authorized, offline exposed-data event prediction and existing-action diagnostic; no wallet simulation."""
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
ROOT = Path('/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue147-relative-events-v1')
COSTS = {'base': (D('.001'), D('.0006')), 'stress': (D('.002'), D('.0012'))}
CELLS = ['base','stress']


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


SYMS = ['BTCUSDT', 'ETHUSDT']
START = 447288  # 2021-01-10T00Z
SCORE = 447985  # 2021-02-08T01Z
END = 464592

class DataError(ValueError):
    """Bound source contents cannot support the authorized analysis."""


def load_sources(m):
    bars = {'BTCUSDT':{}, 'ETHUSDT':{}}
    for src in m['sources']:
        if sha(src['path'])!=src['sha256']: raise DataError('source SHA drift')
    for src in m['sources']:
        q=src['request']
        if q.get('interval')!='1h': continue  # metadata and 2020 daily warmup: hash only
        s=q['symbol']; last=None
        for x in json.loads(Path(src['path']).read_bytes()):
            if not isinstance(x,list) or len(x)!=12 or type(x[0]) is not int or type(x[6]) is not int: raise DataError('kline shape')
            t=x[0]//3600000
            if not m['start']<=t<m['end']: continue  # no OHLC decoding outside authorized domain
            if x[0]%3600000 or not m['start']<=t<m['end'] or t in bars[s] or (last is not None and t<=last): raise DataError('time/duplicate/order')
            if not q['startTime']<=x[0]<=q['endTime'] or not x[0]<=x[6]<x[0]+3600000: raise DataError('request/close boundary')
            o,h,l,c=map(D,x[1:5]); volume=D(x[5])
            if not all(v.is_finite() and v>0 for v in [o,h,l,c]) or not volume.is_finite() or volume<0 or not l<=min(o,c)<=max(o,c)<=h: raise DataError('OHLC invalid')
            bars[s][t]=dict(open=o,close=c,full=x[6]==x[0]+3599999);last=t
    for s in bars:
        observed=[dict(kind='MISSING',open_ms=t*3600000) for t in range(m['start'],m['end']) if t not in bars[s]]
        observed += [dict(kind='SHORT',open_ms=t*3600000) for t,r in bars[s].items() if not r['full']]
        expected=[{k:a[k] for k in ['kind','open_ms']} for a in m['anomalies'][s] if m['start']*3600000<=a['open_ms']<m['end']*3600000]
        if sorted(observed,key=lambda a:a['open_ms'])!=sorted(expected,key=lambda a:a['open_ms']): raise DataError('anomaly inventory drift')
    return bars


def once(root, action, seconds=180, identity=None):
    root=Path(root)
    root.mkdir()  # Existing root, including a failed attempt, rejects without retry.
    sync(root.parent)
    write(root/'attempt.json',dict(event='ATTEMPT',at_utc=utc(),identity=identity,invocations=1,units_limit=17,retries=0))
    started=time.monotonic()
    try:
        with deadline(seconds): result=action(root)
        write(root/'terminal.json',dict(status='SUCCEEDED',elapsed_seconds=time.monotonic()-started,at_utc=utc(),**result))
    except BaseException as exc:
        write(root/'terminal.json',dict(status='FAILED',verdict='BLOCKED_DATA' if isinstance(exc,DataError) else 'ATTEMPT_FAILED_NO_RETRY',error=type(exc).__name__+': '+str(exc),elapsed_seconds=time.monotonic()-started,at_utc=utc()))
        raise




def stamp(hour):
    return datetime.fromtimestamp(hour*3600,timezone.utc).isoformat()


def anchors():
    return [h for h in range(SCORE-1,END,42*24) if h+1+7*24<END]


def event_return(entry,exit,cost):
    fee,slip=COSTS[cost]
    gross=exit/entry-1
    acquired=(1-fee)/(entry*(1+slip))  # one quote spent, buy fee in base
    final_quote=acquired*exit*(1-slip)*(1-fee)
    return dict(gross=gross,net=final_quote-1,quote_spent=D(1),base_acquired=acquired,quote_received=final_quote)


def input_ratio(bars,t):
    begin=t-29*24
    bad=[h for h in range(begin,t) if any(h not in bars[s] or not bars[s][h]['full'] for s in SYMS)]
    if bad:return None,bad
    first=[bars[s][begin+23]['close'] for s in SYMS];last=[bars[s][t-1]['close'] for s in SYMS]
    return last[1]*first[0]/(first[1]*last[0]),[]


def coverage(t,prior,summary):
    result={}
    for cost in COSTS:
        e=prior['R/'+cost]; weeks=e['weeks']; w=next((z for z in weeks if z['decision_hour']==t),None)
        if w is None:
            result[cost]=dict(status='NOT_OBSERVED',prior_half=None,prior_no_buy=None,risk_buy_allowed=None,actual_rotation=None,trades=None)
            continue
        risks=[z for z in summary['cells']['R/'+cost]['risks'] if z['close_known_utc']<=stamp(t)]
        half=any('DD10_LATCH' in z['events'] for z in risks);halt=any('DD15_NO_BUY_LATCH' in z['events'] for z in risks)
        trades=[z for z in e['trades'] if t+1<=z['hour']<t+1+168]
        atopen=[z for z in trades if z['hour']==t+1 and z['reason']=='WEEKLY']
        previous=[z for z in weeks if z['decision_hour']<t and z['execution']=='EXECUTED' and D(z['relative_ratio'])!=1]
        q=D(w['relative_ratio']) if w['relative_ratio'] is not None else None
        direction=1 if q is not None and q>1 else -1 if q is not None and q<1 else 0
        oldq=D(previous[-1]['relative_ratio']) if previous else None
        old=1 if oldq is not None and oldq>1 else -1 if oldq is not None and oldq<1 else 0
        oldcoin=SYMS[1] if old==1 else SYMS[0];newcoin=SYMS[1] if direction==1 else SYMS[0]
        rotation=bool(old and direction and old!=direction and any(z['side']=='SELL' and z['symbol']==oldcoin for z in atopen) and any(z['side']=='BUY' and z['symbol']==newcoin for z in atopen))
        last_h=max(z['hour'] for z in e['marks']) if e['marks'] else SCORE-1
        result[cost]=dict(status='OBSERVED' if last_h>=t+168 else 'PARTIAL_ORIGINAL_LOG_WEEK',prior_half=half,prior_no_buy=halt,
            risk_buy_allowed=not halt,week_execution=w['execution'],risk_permission_is_not_data_or_execution_permission=True,
            actual_rotation=rotation,buy_count=sum(z['side']=='BUY' for z in trades),sell_count=sum(z['side']=='SELL' for z in trades),
            trades=trades,original_log_last_close_known=summary['cells']['R/'+cost]['last_joint_observed_utc'])
    return result


def stats(items):
    if not items:return dict(n=0,mean=None,median=None,positive_count=0,largest_absolute_unit=None,largest_absolute_share=None,largest_positive_unit=None,largest_positive_share=None)
    values=[v for _,v in items];ordered=sorted(values);n=len(values);denom=sum((abs(v) for v in values),D(0));pos=sum((max(v,D(0)) for v in values),D(0))
    big=max(items,key=lambda z:abs(z[1]));positive=max(items,key=lambda z:z[1])
    return dict(n=n,mean=sum(values,D(0))/n,median=(ordered[(n-1)//2]+ordered[n//2])/2,positive_count=sum(v>0 for v in values),
        largest_absolute_unit=big[0],largest_absolute_share=abs(big[1])/denom if denom else None,
        largest_positive_unit=positive[0] if pos else None,largest_positive_share=positive[1]/pos if pos else None)


def analyze(bars,prior,prior_summary):
    rows=[]
    for i,t in enumerate(anchors()):
        q,signal_bad=input_ratio(bars,t);entry=t+1;exit=entry+168
        # Include the entry through last held hour; exit open separately must be full as well.
        event_bad=[h for h in range(entry,exit) if any(h not in bars[s] or not bars[s][h]['full'] for s in SYMS)]
        exit_missing=[s for s in SYMS if exit not in bars[s]]
        reasons=[]
        if signal_bad:reasons.append('SIGNAL_29_DAY_INCOMPLETE')
        if event_bad:reasons.append('HELD_7_DAYS_UNKNOWN_OR_SHORT')
        if exit_missing:reasons.append('EXIT_OPEN_MISSING')
        row=dict(unit=i,decision_utc=stamp(t),last_signal_close_known_utc=stamp(t),entry_open_utc=stamp(entry),exit_open_utc=stamp(exit),
            Q=q,status='UNKNOWN' if reasons else 'TIE' if q==1 else 'SCORED',reasons=reasons,signal_bad_hours=signal_bad,event_bad_hours=event_bad,exit_open_missing=exit_missing,
            stronger=None if q is None or q==1 else SYMS[1] if q>1 else SYMS[0],weaker=None if q is None or q==1 else SYMS[0] if q>1 else SYMS[1],
            cost_cases=None,action_coverage=coverage(t,prior,prior_summary))
        if not reasons:
            row['cost_cases']={}
            for cost in COSTS:
                assets={s:event_return(bars[s][entry]['open'],bars[s][exit]['open'],cost) for s in SYMS}
                case=dict(assets=assets,stronger=None,weaker=None,paired_net=None,paired_gross=None)
                if q!=1:
                    strong=assets[row['stronger']];weak=assets[row['weaker']]
                    case.update(stronger=strong,weaker=weak,paired_net=strong['net']-weak['net'],paired_gross=strong['gross']-weak['gross'])
                row['cost_cases'][cost]=case
        rows.append(row)
    scored=[r for r in rows if r['status']=='SCORED'];directions=dict(Counter(r['stronger'] for r in scored))
    cases={c:dict(stronger_net=stats([(r['unit'],r['cost_cases'][c]['stronger']['net']) for r in scored]),
                 paired_net=stats([(r['unit'],r['cost_cases'][c]['paired_net']) for r in scored])) for c in COSTS}
    return dict(verdict='EXPOSED_DIAGNOSTIC_ONLY',independent_qualification=False,planned_units=len(rows),status_counts=dict(Counter(r['status'] for r in rows)),
        direction_counts=directions,cost_cases=cases,sample_status='UNDERPOWERED_DIRECTION_COVERAGE' if len(directions)<2 else 'FINITE_SMALL_SAMPLE_NO_POWER_CLAIM',
        actual_rotation_count={c:sum(r['action_coverage'][c]['actual_rotation'] is True for r in rows) for c in COSTS},
        action_coverage_counts={c:dict(Counter(r['action_coverage'][c]['status'] for r in rows)) for c in COSTS},
        not_wallet_or_dd=True,source_grade='EXPOSED_DEVELOPMENT',batch_history_exploration='CONCLUDED_NO_AUTOMATIC_FOLLOWUP'),rows


def check(m):
    if m['root']!=str(ROOT) or m['cells']!=CELLS or m['budget']!={'invocations':1,'units':17,'seconds':180,'retries':0}: raise ValueError('identity/budget')
    if (m['start'],m['score'],m['end'])!=(START,SCORE,END) or m['costs']!={k:[str(x) for x in v] for k,v in COSTS.items()}: raise ValueError('window/cost')
    for p,h in m['bindings'].items():
        if sha(p)!=h: raise ValueError('control/code binding drift: '+p)
    old=json.loads((REPO/'docs/issue139-v3-first-diagnostics-manifest.json').read_bytes())
    inv=json.loads((REPO/'docs/issue139-source-inventory-v3-terminal.json').read_bytes())
    if m['sources']!=old['sources'] or len(m['sources'])!=39: raise ValueError('source manifest')
    if m['anomalies']!={s:v['anomalies'] for s,v in inv['symbols'].items()}: raise ValueError('anomaly identity')
    if m['incomplete_days_utc']!={s:v['incomplete_days_utc'] for s,v in inv['symbols'].items()}: raise ValueError('incomplete day identity')


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
            write(root/'analysis-ledger.json',dict(invocations_consumed=1,cost_cases=CELLS,units_planned=17,native_calls=0,market_http=0,retries=0))
            try: bars=load_sources(m)
            except TimeoutError: raise
            except (OSError,ValueError,TypeError,KeyError,IndexError) as exc: raise DataError(str(exc)) from exc
            for s in SYMS:
                missing=[datetime.fromtimestamp(d*86400,timezone.utc).strftime('%Y-%m-%d') for d in range(START//24,END//24)
                    if any(t not in bars[s] or not bars[s][t]['full'] for t in range(d*24,(d+1)*24))]
                if missing!=m['incomplete_days_utc'][s]: raise DataError('incomplete calendar drift')
            prior=json.loads(Path(m['prior_events']).read_bytes()); prior_summary=json.loads(Path(m['prior_summary']).read_bytes())
            summary,rows=analyze(bars,prior,prior_summary)
            summary.update(source_anomalies=m['anomalies'])
            write(root/'events.json',rows);write(root/'summary.json',summary)
            check(m)
            for src in m['sources']:
                if sha(src['path'])!=src['sha256']:raise ValueError('post source drift')
            return dict(manifest_sha256=a.sha256,grant_sha256=a.grant_sha256,summary_sha256=sha(root/'summary.json'),events_sha256=sha(root/'events.json'),source_code_postcheck='PASS',units_completed=len(rows),verdict=summary['verdict'])
        once(ROOT,work,180,dict(manifest_sha256=a.sha256,grant_sha256=a.grant_sha256))
    print((ROOT/'terminal.json').read_text())


if __name__=='__main__': main()
