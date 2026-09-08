#!/usr/bin/env python3
"""One USDC Ethereum supply acquisition and bounded ETH monthly diagnostic."""
import argparse
from collections import Counter
from datetime import date, timedelta
from decimal import Decimal as D, InvalidOperation
import json
from pathlib import Path
import re
import subprocess
import sys
import time
from issue147_diagnostic import COSTS, DataError, deadline, event_return, sha, stats, utc, write
from issue151_diagnostic import month, hour

REPO=Path(__file__).resolve().parents[1]
ROOT=Path('/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue153-usdc-supply-v1')
URL='https://community-api.coinmetrics.io/v4/timeseries/asset-metrics?assets=usdc_eth&metrics=SplyCur&frequency=1d&start_time=2021-01-01&end_time=2022-10-31&page_size=10000'
FIRST,LAST=date(2021,1,1),date(2022,10,31)
START,END=hour(date(2021,3,8),0),hour(date(2022,12,8))

def expected_days():
    return [(FIRST+timedelta(days=i)).isoformat() for i in range((LAST-FIRST).days+1)]

def supply_check(payload):
    if not isinstance(payload,dict) or set(payload)-{'data','next_page_token','next_page_url'} or not isinstance(payload.get('data'),list) or not payload['data']:
        raise DataError('supply envelope/empty')
    if payload.get('next_page_token') or payload.get('next_page_url'): raise DataError('pagination forbidden')
    records={};bad={};seen=set()
    def flag(d,why):bad.setdefault(d[:7],[]).append({'date':d,'reason':why})
    for r in payload['data']:
        if not isinstance(r,dict) or r.get('asset')!='usdc_eth' or set(r)-{'asset','time','SplyCur'} or 'SplyCur' not in r: raise DataError('asset/metric schema')
        raw=r.get('time')
        if not isinstance(raw,str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T00:00:00(?:\.0{1,9})?(?:Z|\+00:00)',raw): raise DataError('non UTC midnight daily label')
        d=date.fromisoformat(raw[:10]);label=d.isoformat()
        if not FIRST<=d<=LAST: raise DataError('outside supply domain')
        if label in seen:flag(label,'DUPLICATE_DATE')
        seen.add(label)
        try:
            if isinstance(r['SplyCur'],bool): raise ValueError('boolean')
            value=D(str(r['SplyCur']))
            if not value.is_finite() or value<=0: raise ValueError('not positive finite')
        except (InvalidOperation,ValueError):
            flag(label,'INVALID_SUPPLY');continue
        records[label]=value
    for d in expected_days():
        if d not in seen:flag(d,'MISSING_DATE')
    months={}
    for i in range(22):
        m=month(FIRST,i);key=m.strftime('%Y-%m');last=(month(m,1)-timedelta(days=1)).isoformat()
        months[key]=dict(issues=bad.get(key,[]),month_end=last,value=None if key in bad else records[last])
    return dict(grade='RECONSTRUCTED_EX_POST',daily_label_interpretation='UTC calendar day stock; first availability UNKNOWN',rows=len(payload['data']),unique_days=len(seen),expected_days=len(expected_days()),months=months)

def load_eth(m):
    bars={}
    for s in m['sources']:
        if sha(s['path'])!=s['sha256']: raise DataError('ETH SHA drift')
        for x in json.loads(Path(s['path']).read_bytes()):
            if not isinstance(x,list) or len(x)!=12 or type(x[0]) is not int: raise DataError('kline shape')
            t=x[0]//3600000
            if not START<=t<=END:continue
            if x[0]%3600000 or t in bars or type(x[6]) is not int or not x[0]<=x[6]<x[0]+3600000:raise DataError('bar timestamp')
            if not s['request']['startTime']<=x[0]<=s['request']['endTime']:raise DataError('request boundary')
            op=D(x[1])
            if not op.is_finite() or op<=0:raise DataError('invalid open')
            bars[t]=dict(open=op,full=x[6]==x[0]+3599999)
    actual=[dict(kind='MISSING',open_ms=t*3600000) for t in range(START,END+1) if t not in bars]
    actual += [dict(kind='SHORT',open_ms=t*3600000) for t,r in bars.items() if not r['full']]
    if sorted(actual,key=lambda r:(r['open_ms'],r['kind']))!=m['anomalies']:raise DataError('ETH anomaly drift')
    return bars

def analyze(bars,supply):
    rows=[]
    for i in range(21):
        m=month(date(2021,3,1),i);begin=hour(m.replace(day=8));end=hour(month(m,1).replace(day=8))
        keys=[month(m,k).strftime('%Y-%m') for k in (-2,-1)];a,b=[supply['months'][k]['value'] for k in keys]
        growth=None if a is None or b is None else D(str(b))/D(str(a))-1
        bad=[t for t in range(begin,end) if t not in bars or not bars[t]['full']]
        why=[]
        if growth is None:why.append('SUPPLY_MONTH_UNKNOWN')
        if bad:why.append('HELD_HOUR_UNKNOWN_OR_SHORT')
        if end not in bars:why.append('EXIT_OPEN_MISSING')
        row=dict(unit=i,month=m.strftime('%Y-%m'),decision_hour=begin-1,entry_hour=begin,exit_hour=end,input_months=keys,
                 supply_growth=growth,group=None if growth is None else 'EXPAND' if growth>0 else 'OTHER',status='UNKNOWN' if why else 'SCORED',reasons=why,bad_hours=bad,costs=None)
        if not why:row['costs']={c:event_return(bars[begin]['open'],bars[end]['open'],c) for c in COSTS}
        rows.append(row)
    good=[r for r in rows if r['status']=='SCORED'];groups={g:sum(r['group']==g for r in good) for g in ('EXPAND','OTHER')}
    cases={c:{g:stats([(r['unit'],r['costs'][c]['net']) for r in good if r['group']==g]) for g in groups} for c in COSTS}
    for c in cases:
        a,b=[cases[c][g]['mean'] for g in groups];cases[c]['expand_minus_other']=None if a is None or b is None else a-b
    verdict='UNDERPOWERED' if min(groups.values())<5 else 'STOP_RULE_NOT_SUPPORTED' if any(cases[c]['expand_minus_other']<=0 for c in COSTS) else 'NO_LONG_COST_SUPPORT' if any(cases[c]['EXPAND']['mean']<=0 for c in COSTS) else 'EXPOSED_DEVELOPMENT_ASSOCIATION'
    return dict(verdict=verdict,planned=21,status_counts=dict(Counter(r['status'] for r in rows)),groups=groups,costs=cases,independent_confirmation=False,causal_identification=False,wallet=False),rows

def check(m):
    if m['root']!=str(ROOT) or m['url']!=URL or m['budget']!={'supply_get':1,'bytes':1048576,'download_seconds':20,'analysis':1,'seconds':180,'units':21,'retries':0}:raise ValueError('identity/budget')
    for p,h in m['bindings'].items():
        if sha(p)!=h:raise ValueError('binding drift: '+p)
    original=json.loads((REPO/'docs/issue139-v3-first-diagnostics-manifest.json').read_text())
    sources=[s for s in original['sources'] if s['request'].get('symbol')=='ETHUSDT' and s['request'].get('interval')=='1h' and s['request']['startTime']<=END*3600000]
    if m['sources']!=sources:raise ValueError('source identity')

def acquire(m,msha):
    ROOT.mkdir(exist_ok=True);r=ROOT/'acquisition';r.mkdir()
    write(r/'attempt.json',dict(at_utc=utc(),url=URL,manifest_sha256=msha,budget=m['budget']))
    try:
        p=subprocess.run(['curl','--silent','--show-error','--fail','--max-time','20','--max-filesize','1048576','--retry','0','--proto','=https','--dump-header',str(r/'headers.txt'),'--output',str(r/'response.json'),'--write-out','%{http_code}',URL],capture_output=True,text=True,timeout=22)
        raw=r/'response.json';info=dict(at_utc=utc(),returncode=p.returncode,http_status=p.stdout.strip(),stderr=p.stderr,sha256=sha(raw) if raw.exists() else None,bytes=raw.stat().st_size if raw.exists() else 0)
        write(r/'receipt.json',info)
        if p.returncode or p.stdout.strip()!='200' or info['bytes']>1048576:raise DataError('download failed')
        result=supply_check(json.loads(raw.read_text(),parse_float=D));check(m);write(r/'check.json',result)
        write(r/'terminal.json',dict(status='CHECKED',response_sha256=info['sha256'],check_sha256=sha(r/'check.json'),unknown_months=[k for k,v in result['months'].items() if v['value'] is None]))
    except BaseException as e:write(r/'failure.json',dict(status='BLOCKED_DATA',error=type(e).__name__+': '+str(e)));raise

def execute(m,msha,binding):
    b=json.loads(Path(binding).read_text());a=ROOT/'acquisition'
    if b!={'manifest_sha256':msha,'response_sha256':sha(a/'response.json'),'check_sha256':sha(a/'check.json'),'terminal_sha256':sha(a/'terminal.json')}:raise ValueError('acquisition binding')
    if json.loads((a/'terminal.json').read_text())['status']!='CHECKED':raise ValueError('acquisition not checked')
    r=ROOT/'analysis';r.mkdir();write(r/'attempt.json',dict(at_utc=utc(),manifest_sha256=msha,binding_sha256=sha(binding),units=21,seconds=180));start=time.monotonic()
    try:
        with deadline(180):
            def deny(event,args):
                if event in ('socket.connect','socket.getaddrinfo','socket.bind'):raise ValueError('network forbidden')
            sys.addaudithook(deny)
            summary,rows=analyze(load_eth(m),json.loads((a/'check.json').read_text(),parse_float=D));check(m)
            for s in m['sources']:
                if sha(s['path'])!=s['sha256']:raise DataError('post source drift')
            write(r/'events.json',rows);write(r/'summary.json',summary)
            write(r/'terminal.json',dict(status='SUCCEEDED',verdict=summary['verdict'],elapsed_seconds=time.monotonic()-start,events_sha256=sha(r/'events.json'),summary_sha256=sha(r/'summary.json')))
    except BaseException as e:write(r/'failure.json',dict(status='FAILED_NO_RETRY',error=str(e)));raise

def main():
    p=argparse.ArgumentParser();p.add_argument('command',choices=['check','acquire','execute']);p.add_argument('--manifest',required=True);p.add_argument('--sha256',required=True);p.add_argument('--acquisition-binding');a=p.parse_args()
    if sha(a.manifest)!=a.sha256:raise ValueError('manifest SHA')
    m=json.loads(Path(a.manifest).read_text());check(m)
    if a.command=='check':print('CONTROL_PASS_NO_RAW_READ')
    elif a.command=='acquire':acquire(m,a.sha256)
    else:execute(m,a.sha256,a.acquisition_binding)

if __name__=='__main__':main()
