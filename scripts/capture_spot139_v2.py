#!/usr/bin/env python3
"""One authorized Issue139 continuation. Existing v1 files are immutable."""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from lab.portfolio_source import SourceError,digest,exclusive,write_json
from lab.spot139_source import SpotFetcher,encoded
from lab.spot139_continuation import ContinuationBudget,reuse,collect_continuation
from scripts.capture_spot139 import RUN,LEDGER

REPO=Path(__file__).resolve().parents[1]
OLD=RUN/'issue139-spot-source-v1';ROOT=OLD/'continuation-v2'
PARENT=RUN/'btc-eth-portfolio-v1/acquisition-spot139-v1.json'
BUDGET=PARENT.with_name('acquisition-spot139-continuation-v2.json')
EXPECTED='8456411bc6020bc6ccb2d81e5b789d4f2926ad196cb8a5492bfee3caa9732020'
FILES=['lab/__init__.py','lab/database.py','lab/portfolio_source.py','lab/spot139_source.py','lab/spot139_gap_proposal.py','lab/spot139_continuation.py','scripts/capture_spot139.py','scripts/capture_spot139_v2.py','docs/protocols/issue139-spot-gap-continuation-v2.md']


def bindings():return {p:digest((REPO/p).read_bytes()) for p in FILES}


def prepare(path):
    raw=LEDGER.read_bytes()
    if digest(raw)!=EXPECTED:raise SourceError('ledger drift; incremental scope review required')
    if ROOT.exists() or BUDGET.exists():raise SourceError('continuation already attempted')
    terminal=json.loads((OLD/'terminal.json').read_bytes())
    if digest((OLD/'terminal.json').read_bytes())!='e357a2ef4a93b03d2053c79ca338838854d6293ce5e324c06a940b86f24d1a44':raise SourceError('old terminal changed')
    hashes={f'{r["number"]:03d}-{r["endpoint"]}.json':r['sha256'] for r in terminal['responses']}
    reuse(OLD,hashes)
    if digest(PARENT.read_bytes())!='c66ad06906688d5a946262ee0378d39e584931fbd4402edf002716967ce3145b':raise SourceError('v1 budget changed')
    record=dict(record_type='SPOT_EXPLORATORY_SOURCE_CONTINUATION_REGISTERED',issue=139,exchange='binance',instrument_type='SPOT',symbols=['BTCUSDT','ETHUSDT'],
        source_window=['2020-04-02T00:00:00Z','2023-01-01T00:00:00Z'],training_window=['2021-01-01T00:00:00Z','2023-01-01T00:00:00Z'],
        purpose='EXPLORATORY_EXPOSED_TRAINING_GAP_MODEL',independent_evidence=False,prior_ledger_sha256=EXPECTED,
        protocol_sha256=bindings()['docs/protocols/issue139-spot-gap-continuation-v2.md'],native_authorized=False,
        authorization='supervisor:01a07c6a-d535-7030-814c-7775d0f27f99/cc68645-continuation-approved',prepared_at_utc=dt.datetime.now(dt.timezone.utc).isoformat())
    controls=json.loads((REPO/'docs/issue139-spot-launch-v1.json').read_text())['control_hashes']
    controls.update({str(PARENT):digest(PARENT.read_bytes()),str(OLD/'terminal.json'):digest((OLD/'terminal.json').read_bytes()),str(RUN/'btc-eth-portfolio-v1/acquisition-continuation-v2.json'):'9f9ed03a227070842591370bb6a2d07f7175d9057d0b2e3a2b025319794b3897'})
    m=dict(files=bindings(),root=str(ROOT),budget=str(BUDGET),reuse_hashes=hashes,controls=controls,ledger_before=EXPECTED,ledger_after=digest(raw+encoded(record)),registration=record,
        python=str(Path(sys.executable).resolve()),python_sha256=digest(Path(sys.executable).resolve().read_bytes()),native_authorized=False,
        limits=dict(new_gets=35,new_bytes=16486288,new_seconds=896,response_bytes=1048576,request_seconds=20,retries=0,redirects=0))
    write_json(path,m)


def verify(m,path,sha,post=False):
    if digest(Path(path).read_bytes())!=sha or bindings()!=m['files']:raise SourceError('manifest/code drift')
    if m['root']!=str(ROOT) or m['budget']!=str(BUDGET) or m['native_authorized'] is not False:raise SourceError('identity drift')
    if m['python']!=str(Path(sys.executable).resolve()) or digest(Path(sys.executable).resolve().read_bytes())!=m['python_sha256']:raise SourceError('python drift')
    if any(digest(Path(p).read_bytes())!=h for p,h in m['controls'].items()):raise SourceError('old control drift')
    if digest(LEDGER.read_bytes())!=m['ledger_after' if post else 'ledger_before']:raise SourceError('ledger drift')


def capture(path):
    raw=Path(path).read_bytes();m=json.loads(raw);sha=digest(raw)
    with exclusive(str(PARENT.with_name('acquisition-budget.json'))+'.lock'),exclusive(str(LEDGER)+'.lock'):
        verify(m,path,sha)
        retained=reuse(OLD,m['reuse_hashes'])
        if ROOT.exists() or BUDGET.exists():raise SourceError('one shot already attempted')
        b=ContinuationBudget(BUDGET,ROOT,json.loads(PARENT.read_bytes()))
        ROOT.mkdir();(ROOT/'raw').mkdir();post=False
        try:
            old=LEDGER.read_bytes()
            if not old.endswith(b'\n') or digest(old+encoded(m['registration']))!=m['ledger_after']:raise SourceError('own registration mismatch')
            with LEDGER.open('ab') as f:f.write(encoded(m['registration']));f.flush();os.fsync(f.fileno())
            post=True;verify(m,path,sha,True)
            write_json(ROOT/'activation.json',dict(launch_sha256=sha,ledger_after=m['ledger_after'],native_authorized=False))
            receipt=collect_continuation(SpotFetcher(b,ROOT,lambda:verify(m,path,sha,True)),retained)
        except BaseException as exc:receipt=dict(status='BLOCKED_DATA' if post else 'BLOCKED_CONTROL',reason=str(exc),native_calls=0,economic_result=None)
        try:verify(m,path,sha,post)
        except Exception as exc:receipt.update(status='CONTROL_INTEGRITY',reason=str(exc))
        elapsed=b.now()-b.state['started']
        if elapsed>896:receipt.update(status='BLOCKED_DATA',reason='active time budget exceeded')
        b.terminal(receipt['status']);new=b.state['attempts'][4:]
        receipt.update(launch_sha256=sha,ledger_after=digest(LEDGER.read_bytes()),new_gets=len(new),spot_cumulative_gets=len(b.state['attempts']),global_cumulative_gets=73+len(b.state['attempts']),
            new_charged_bytes=b.state['charged_bytes']-290928,spot_cumulative_bytes=b.state['charged_bytes'],global_cumulative_bytes=14603929+b.state['charged_bytes'],
            new_active_seconds=elapsed,spot_cumulative_seconds=3.4234702587127686+elapsed,global_cumulative_seconds=169.1827094554901+elapsed,
            reused_hashes=m['reuse_hashes'],budget_sha256=digest(BUDGET.read_bytes()),responses=[dict(number=r['number'],endpoint=r['endpoint'],status=r['status'],bytes=r['charged_bytes'],sha256=r.get('sha256')) for r in new])
        write_json(ROOT/'terminal.json',receipt);print(json.dumps(receipt,sort_keys=True))
        return 0 if receipt['status']=='EXPLORATORY_SOURCE_WITH_UNOBSERVED_INTERVALS' else 2


def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['prepare','capture']);p.add_argument('manifest',type=Path);a=p.parse_args()
    try:return prepare(a.manifest) if a.action=='prepare' else capture(a.manifest)
    except SourceError as exc:print(json.dumps(dict(status='BLOCKED_CONTROL',reason=str(exc))));return 2
if __name__=='__main__':sys.exit(main())
