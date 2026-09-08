#!/usr/bin/env python3
"""Bound EFFR acquisition and one exposed BTC monthly diagnostic; no wallet."""
import argparse
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal as D
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

from issue147_diagnostic import COSTS, DataError, deadline, event_return, sha, stats, utc, write

REPO = Path(__file__).resolve().parents[1]
ROOT = Path('/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue151-effr-v1')
URL = 'https://markets.newyorkfed.org/api/rates/unsecured/effr/search.json?startDate=2021-01-01&endDate=2022-10-31&type=rate'
FIRST, LAST = date(2021,1,1), date(2022,10,31)

def month(d, offset):
    y,m=divmod(d.year*12+d.month-1+offset,12)
    return date(y,m+1,1)

def hour(d, h=1):
    return int(datetime(d.year,d.month,d.day,h,tzinfo=timezone.utc).timestamp())//3600

START, END = hour(date(2021,3,8),0), hour(date(2022,12,8))

def calendar_days():
    # RULE_RECONSTRUCTED, with explicit financial-service dates, not exchange holidays.
    holidays=set()
    for y in (2021,2022):
        fixed=[date(y,1,1),date(y,7,4),date(y,11,11),date(y,12,25)]
        if y>=2022: fixed.append(date(y,6,19))
        for d in fixed:
            holidays.add(d+timedelta(days=1) if d.weekday()==6 else d)
        for m,w,n in [(1,0,3),(2,0,3),(5,0,-1),(9,0,1),(10,0,2),(11,3,4)]:
            ds=[date(y,m,k) for k in range(1,32) if k<=(month(date(y,m,1),1)-timedelta(days=1)).day and date(y,m,k).weekday()==w]
            holidays.add(ds[n-1] if n>0 else ds[-1])
    return [(FIRST+timedelta(days=i)).isoformat() for i in range((LAST-FIRST).days+1)
            if (FIRST+timedelta(days=i)).weekday()<5 and FIRST+timedelta(days=i) not in holidays]

def macro_check(payload, expected):
    if not isinstance(payload,dict) or set(payload)!={'refRates'} or not isinstance(payload['refRates'],list) or not payload['refRates']:
        raise DataError('macro envelope/empty/pagination')
    records={}; bad={}; issues=[]
    def flag(d,why):
        bad.setdefault(d[:7],[]).append({'date':d,'reason':why})
    for r in payload['refRates']:
        if not isinstance(r,dict) or r.get('type')!='EFFR': raise DataError('macro identity')
        raw=r.get('effectiveDate'); d=date.fromisoformat(raw)
        if d.isoformat()!=raw or not FIRST<=d<=LAST: raise DataError('macro date/domain')
        if raw in records: flag(raw,'DUPLICATE_DATE')
        value=D(str(r.get('percent')))
        if not value.is_finite(): raise DataError('nonfinite EFFR')
        if raw not in expected: flag(raw,'UNEXPECTED_DATE')
        # Y is an explicit final-history revision, retained rather than concealed.
        if r.get('revisionIndicator') not in (None,'','Y','N'): flag(raw,'UNEXPLAINED_REVISION')
        if r.get('footnoteId') not in (None,'',0): flag(raw,'FOOTNOTE_REQUIRES_EXPLANATION')
        records[raw]=dict(percent=value,revision=r.get('revisionIndicator'),footnote=r.get('footnoteId'))
    for d in expected:
        if d not in records: flag(d,'MISSING_EXPECTED_DATE')
    months={}
    for i in range(22):
        m=month(FIRST,i).strftime('%Y-%m'); days=[d for d in expected if d.startswith(m)]
        months[m]=dict(expected=len(days),observed=sum(d in records for d in days),issues=bad.get(m,[]),
                       mean=None if m in bad else sum((records[d]['percent'] for d in days),D(0))/len(days))
    return dict(grade='RECONSTRUCTED_EX_POST',calendar='RULE_RECONSTRUCTED',rows=len(records),months=months,
                revisions=[d for d,r in records.items() if r['revision']=='Y'],records=records)

def load_btc(m):
    bars={}
    for s in m['sources']:
        if sha(s['path'])!=s['sha256']: raise DataError('BTC SHA drift')
        for x in json.loads(Path(s['path']).read_bytes()):
            if not isinstance(x,list) or len(x)!=12 or type(x[0]) is not int: raise DataError('kline shape')
            t=x[0]//3600000
            if not START<=t<=END: continue
            if x[0]%3600000 or t in bars or type(x[6]) is not int or not x[0]<=x[6]<x[0]+3600000: raise DataError('bar time')
            op=D(x[1])
            if not op.is_finite() or op<=0: raise DataError('open invalid')
            bars[t]=dict(open=op,full=x[6]==x[0]+3599999)
    actual=[{'kind':'MISSING','open_ms':t*3600000} for t in range(START,END+1) if t not in bars]
    actual += [{'kind':'SHORT','open_ms':t*3600000} for t,r in bars.items() if not r['full']]
    if sorted(actual,key=lambda r:(r['open_ms'],r['kind']))!=m['anomalies']: raise DataError('BTC anomaly inventory drift')
    return bars

def analyze(bars, macro):
    rows=[]
    for i in range(21):
        m=month(date(2021,3,1),i); begin=hour(m.replace(day=8)); end=hour(month(m,1).replace(day=8))
        a,b=[month(m,j).strftime('%Y-%m') for j in (-2,-1)]
        av,bv=macro['months'][a]['mean'],macro['months'][b]['mean']
        diff=None if av is None or bv is None else D(str(bv))-D(str(av))
        bad=[t for t in range(begin,end) if t not in bars or not bars[t]['full']]
        reasons=[]
        if diff is None: reasons.append('MACRO_MONTH_UNKNOWN')
        if bad: reasons.append('HELD_HOUR_UNKNOWN_OR_SHORT')
        if end not in bars: reasons.append('EXIT_OPEN_MISSING')
        row=dict(unit=i,month=m.strftime('%Y-%m'),decision_hour=begin-1,entry_hour=begin,exit_hour=end,
                 input_months=[a,b],rate_difference_pp=diff,group=None if diff is None else 'UP' if diff>0 else 'NOT_UP',
                 status='UNKNOWN' if reasons else 'SCORED',reasons=reasons,bad_hours=bad,costs=None)
        if not reasons: row['costs']={c:event_return(bars[begin]['open'],bars[end]['open'],c) for c in COSTS}
        rows.append(row)
    good=[r for r in rows if r['status']=='SCORED']
    groups={g:len([r for r in good if r['group']==g]) for g in ('UP','NOT_UP')}
    cases={c:{g:stats([(r['unit'],r['costs'][c]['net']) for r in good if r['group']==g]) for g in groups} for c in COSTS}
    for c in cases:
        u,n=[cases[c][g]['mean'] for g in groups]
        cases[c]['up_minus_not_up']=None if u is None or n is None else u-n
    verdict='UNDERPOWERED' if min(groups.values())<5 else 'STOP_RULE_NOT_SUPPORTED' if any(cases[c]['up_minus_not_up']>=0 for c in COSTS) else 'NO_LONG_COST_SUPPORT' if any(cases[c]['NOT_UP']['mean']<=0 for c in COSTS) else 'EXPOSED_DEVELOPMENT_ASSOCIATION'
    return dict(verdict=verdict,planned=21,status_counts=dict(Counter(r['status'] for r in rows)),groups=groups,costs=cases,
                independent_confirmation=False,causal_identification=False,wallet=False),rows

def check(m):
    if m['root']!=str(ROOT) or m['url']!=URL or m['budget']!={'macro_get':1,'bytes':1048576,'download_seconds':20,'analysis':1,'seconds':180,'units':21,'retries':0}: raise ValueError('identity/budget')
    for p,h in m['bindings'].items():
        if sha(p)!=h: raise ValueError('binding drift: '+p)
    cal=json.loads(Path(m['calendar_path']).read_text())
    if cal['expected_days']!=calendar_days(): raise ValueError('calendar drift')
    old=json.loads((REPO/'docs/issue139-v3-first-diagnostics-manifest.json').read_text())
    expected=[s for s in old['sources'] if s['request'].get('symbol')=='BTCUSDT' and s['request'].get('interval')=='1h' and s['request']['startTime']<=END*3600000]
    if m['sources']!=expected: raise ValueError('BTC sources drift')
    return cal['expected_days']

def acquire(m,manifest_sha):
    ROOT.mkdir(exist_ok=True)
    path=ROOT/'acquisition';path.mkdir()  # A failed attempt consumes the same fixed slot.
    write(path/'attempt.json',dict(at_utc=utc(),url=URL,manifest_sha256=manifest_sha,budget=m['budget']))
    args=['curl','--silent','--show-error','--fail','--max-time','20','--max-filesize','1048576','--retry','0','--proto','=https',
          '--dump-header',str(path/'headers.txt'),'--output',str(path/'response.json'),'--write-out','%{http_code}',URL]
    try:
        proc=subprocess.run(args,capture_output=True,text=True,timeout=22)
        response=path/'response.json'
        info=dict(returncode=proc.returncode,http_status=proc.stdout.strip(),stderr=proc.stderr,sha256=sha(response) if response.exists() else None,bytes=response.stat().st_size if response.exists() else 0,at_utc=utc())
        write(path/'receipt.json',info)
        if proc.returncode or proc.stdout.strip()!='200' or info['bytes']>1048576: raise DataError('macro download failed')
        out=macro_check(json.loads(response.read_text(),parse_float=D),check(m))
        write(path/'check.json',out)
        write(path/'terminal.json',dict(status='CHECKED',response_sha256=info['sha256'],unknown_months=[k for k,v in out['months'].items() if v['mean'] is None]))
    except BaseException as e:
        write(path/'failure.json',dict(status='BLOCKED_DATA',error=str(e),at_utc=utc()));raise

def execute(m,manifest_sha,binding_path):
    b=json.loads(Path(binding_path).read_text())
    if b['manifest_sha256']!=manifest_sha or b['response_sha256']!=sha(ROOT/'acquisition/response.json') or b['check_sha256']!=sha(ROOT/'acquisition/check.json'): raise ValueError('acquisition binding')
    if json.loads((ROOT/'acquisition/terminal.json').read_text())['status']!='CHECKED': raise ValueError('acquisition not checked')
    path=ROOT/'analysis';path.mkdir()
    write(path/'attempt.json',dict(at_utc=utc(),manifest_sha256=manifest_sha,binding_sha256=sha(binding_path),units=21,seconds=180))
    started=time.monotonic()
    try:
        with deadline(180):
            def deny(event,args):
                if event in ('socket.connect','socket.getaddrinfo','socket.bind'): raise ValueError('network forbidden')
            sys.addaudithook(deny)
            macro=macro_check(json.loads((ROOT/'acquisition/response.json').read_text(),parse_float=D),check(m))
            summary,rows=analyze(load_btc(m),macro)
            check(m)
            for s in m['sources']:
                if sha(s['path'])!=s['sha256']: raise DataError('post SHA drift')
            write(path/'events.json',rows);write(path/'summary.json',summary)
            write(path/'terminal.json',dict(status='SUCCEEDED',verdict=summary['verdict'],elapsed_seconds=time.monotonic()-started,events_sha256=sha(path/'events.json'),summary_sha256=sha(path/'summary.json')))
    except BaseException as e:
        write(path/'failure.json',dict(status='FAILED_NO_RETRY',error=str(e)));raise

def main():
    p=argparse.ArgumentParser();p.add_argument('command',choices=['check','acquire','execute']);p.add_argument('--manifest',required=True);p.add_argument('--sha256',required=True);p.add_argument('--acquisition-binding');a=p.parse_args()
    if sha(a.manifest)!=a.sha256: raise ValueError('manifest SHA')
    m=json.loads(Path(a.manifest).read_text());check(m)
    if a.command=='check': print('CONTROL_PASS_NO_MARKET_READ')
    elif a.command=='acquire': acquire(m,a.sha256)
    else: execute(m,a.sha256,a.acquisition_binding)

if __name__=='__main__': main()
