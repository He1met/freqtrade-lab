#!/usr/bin/env python3
"""Prepare or execute the single supervisor-authorized Issue139 spot capture."""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from lab.portfolio_source import SourceError, check_scope, digest, exclusive, write_json
from lab.spot139_source import SpotBudget, SpotFetcher, collect, encoded

REPO=Path(__file__).resolve().parents[1]
RUN=Path('/Users/shenjianpeng/.codex/runs/freqtrade-lab')
ROOT=RUN/'issue139-spot-source-v1'
BUDGET=RUN/'btc-eth-portfolio-v1/acquisition-spot139-v1.json'
PARENT=RUN/'btc-eth-portfolio-v1/acquisition-continuation-v2.json'
LEDGER=Path('/Users/shenjianpeng/Documents/freqtrade-lab-local/search-research-supervision-20260902/global-research-ledger.jsonl')
EXPECTED='692c595eb32e928332d4d7759aabcf726e28f1d5ddda07a74a2a5a3a420d7439'
FILES=['lab/__init__.py','lab/database.py','lab/portfolio_source.py','lab/spot139_source.py','scripts/capture_spot139.py','docs/protocols/issue139-spot-experiment-v1.md','docs/issue121-scope-snapshot.json']


CONTROLS=[RUN/'btc-eth-portfolio-v1'/n for n in ['calls.jsonl','acquisition-budget.json','observed-v3-activation.json','corrected-exploration-activation.json']]

def bindings():return {p:digest((REPO/p).read_bytes()) for p in FILES}


def review(raw):
    if digest(raw)!=EXPECTED:raise SourceError('current ledger drift: stop and review increments')
    snapshot=json.loads((REPO/'docs/issue121-scope-snapshot.json').read_text())
    lines=raw.splitlines(keepends=True)
    if digest(b''.join(lines[:176]))!=snapshot['ledger_sha256']:raise SourceError('old scope prefix changed')
    extra=[json.loads(x) for x in lines[176:]]
    if len(extra)!=41 or extra[0]['issue']!=123 or extra[0]['instrument_type']!='USDT_PERPETUAL':raise SourceError('new registration unknown')
    if any(x['record_type']!='PORTFOLIO_NATIVE_BUDGET_CHECKPOINT' for x in extra[1:]):raise SourceError('new scope records require review')
    snapshot['ledger_sha256']=EXPECTED
    check_scope(dict(start='2020-04-02T00:00:00Z',end_exclusive='2023-01-01T00:00:00Z',exchange='binance',instrument_type='SPOT',symbols=['BTCUSDT','ETHUSDT']),snapshot,raw)


def prepare(path):
    raw=LEDGER.read_bytes();review(raw)
    if ROOT.exists() or BUDGET.exists():raise SourceError('already attempted; no reset')
    parent=PARENT.read_bytes()
    if digest(parent)!='9f9ed03a227070842591370bb6a2d07f7175d9057d0b2e3a2b025319794b3897':raise SourceError('parent drift')
    record=dict(record_type='SPOT_EXPLORATORY_SOURCE_REGISTERED',issue=139,exchange='binance',instrument_type='SPOT',symbols=['BTCUSDT','ETHUSDT'],
        source_window=['2020-04-02T00:00:00Z','2023-01-01T00:00:00Z'],warmup_window=['2020-04-02T00:00:00Z','2021-01-01T00:00:00Z'],
        training_window=['2021-01-01T00:00:00Z','2023-01-01T00:00:00Z'],purpose='EXPLORATORY_EXPOSED_TRAINING',independent_evidence=False,
        protocol_sha256=bindings()['docs/protocols/issue139-spot-experiment-v1.md'],prior_ledger_sha256=EXPECTED,native_authorized=False,
        authorization='supervisor:01a07c6a-d535-7030-814c-7775d0f27f99/efd315e-acquisition-approved',prepared_at_utc=dt.datetime.now(dt.timezone.utc).isoformat())
    m=dict(schema='issue139-one-shot-spot-launch-v1',files=bindings(),python=str(Path(sys.executable).resolve()),python_sha256=digest(Path(sys.executable).resolve().read_bytes()),
        root=str(ROOT),budget=str(BUDGET),parent_sha256=digest(parent),ledger_before=EXPECTED,registration=record,ledger_after=digest(raw+encoded(record)),
        control_hashes={str(p):digest(p.read_bytes()) for p in CONTROLS},native_authorized=False,official_parameter_review='supervisor independent 0 searches +2 document operations; kline max1000 UTC verified',
        limits=dict(gets=39,total_bytes=16777216,response_bytes=1048576,seconds=900,request_seconds=20,retries=0,redirects=0,workers=1))
    write_json(path,m)


def verify(m,path,manifest_sha,post=False):
    if digest(Path(path).read_bytes())!=manifest_sha or bindings()!=m['files']:raise SourceError('manifest/code drift')
    if str(Path(sys.executable).resolve())!=m['python'] or digest(Path(sys.executable).resolve().read_bytes())!=m['python_sha256']:raise SourceError('interpreter drift')
    if m['root']!=str(ROOT) or m['budget']!=str(BUDGET) or m['native_authorized'] is not False:raise SourceError('launch identity')
    if any(digest(Path(p).read_bytes())!=h for p,h in m['control_hashes'].items()):raise SourceError('protected control drift')
    if digest(PARENT.read_bytes())!=m['parent_sha256']:raise SourceError('parent budget drift')
    if digest(LEDGER.read_bytes())!=m['ledger_after' if post else 'ledger_before']:raise SourceError('ledger drift')


def capture(path):
    manifest_raw=Path(path).read_bytes();m=json.loads(manifest_raw);sha=digest(manifest_raw)
    # Both shared locks span registration, requests and terminal receipt.
    with exclusive(str(PARENT.with_name('acquisition-budget.json'))+'.lock'), exclusive(str(LEDGER)+'.lock'):
        verify(m,path,sha);review(LEDGER.read_bytes())
        if ROOT.exists() or BUDGET.exists():raise SourceError('already attempted; no repeat request')
        budget=SpotBudget(BUDGET,ROOT,json.loads(PARENT.read_bytes()))
        ROOT.mkdir();(ROOT/'raw').mkdir()
        post=False
        try:
            raw=LEDGER.read_bytes()
            if not raw.endswith(b'\n') or digest(raw+encoded(m['registration']))!=m['ledger_after']:raise SourceError('registration binding')
            with LEDGER.open('ab') as f:f.write(encoded(m['registration']));f.flush();os.fsync(f.fileno())
            post=True
            verify(m,path,sha,post=True)
            # Actual post-registration manifest binds own allowed ledger mutation.
            write_json(ROOT/'activation.json',dict(launch_sha256=sha,ledger_after=m['ledger_after'],native_authorized=False))
            receipt=collect(SpotFetcher(budget,ROOT,lambda:verify(m,path,sha,post=True)))
        except BaseException as exc:
            receipt=dict(status='BLOCKED_DATA' if post else 'BLOCKED_CONTROL',reason=str(exc),native_calls=0,economic_result=None)
        try:verify(m,path,sha,post=post)
        except Exception as exc:receipt.update(status='CONTROL_INTEGRITY',reason=str(exc))
        budget.terminal(receipt['status'])
        elapsed=budget.now()-budget.state['started']
        receipt.update(launch_sha256=sha,ledger_after=digest(LEDGER.read_bytes()),parent_sha256=m['parent_sha256'],
            new_gets=len(budget.state['attempts']),cumulative_gets=73+len(budget.state['attempts']),new_charged_bytes=budget.state['charged_bytes'],
            cumulative_charged_bytes=14603929+budget.state['charged_bytes'],new_active_seconds=elapsed,
            cumulative_active_seconds=budget.state['historical_seconds']+elapsed,
            budget_sha256=digest(BUDGET.read_bytes()),responses=[dict(number=r['number'],endpoint=r['endpoint'],status=r['status'],sha256=r.get('sha256'),bytes=r['charged_bytes']) for r in budget.state['attempts']])
        write_json(ROOT/'terminal.json',receipt)
        print(json.dumps(receipt,sort_keys=True))
        return 0 if receipt['status']=='STRUCTURE_PASS_NOT_MARKET_APPROVAL' else 2


def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['prepare','capture']);p.add_argument('manifest',type=Path);a=p.parse_args()
    try:return prepare(a.manifest) if a.action=='prepare' else capture(a.manifest)
    except SourceError as exc:print(json.dumps({'status':'BLOCKED_CONTROL','reason':str(exc)}));return 2
if __name__=='__main__':sys.exit(main())
