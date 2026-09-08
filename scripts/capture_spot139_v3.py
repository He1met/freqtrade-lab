#!/usr/bin/env python3
"""One authorized SOURCE_INVENTORY_V3; no execution admission."""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from lab.portfolio_source import SourceError,digest,exclusive,write_json
from lab.spot139_source import SpotFetcher,encoded
from lab.spot139_inventory import InventoryBudget,reuse,collect_inventory
from scripts.capture_spot139 import RUN,LEDGER

REPO=Path(__file__).resolve().parents[1]
OLD=RUN/'issue139-spot-source-v1';ROOT=OLD/'inventory-v3'
PARENT=RUN/'btc-eth-portfolio-v1/acquisition-spot139-continuation-v2.json'
BUDGET=PARENT.with_name('acquisition-spot139-inventory-v3.json')
EXPECTED='2410984776b3d7942de5671d50954a6b227c01d88c87137997c2cb175e8bdb46'
FILES=['lab/__init__.py','lab/database.py','lab/portfolio_source.py','lab/spot139_source.py','lab/spot139_gap_proposal.py','lab/spot139_continuation.py','scripts/capture_spot139.py','lab/spot139_inventory.py','scripts/capture_spot139_v3.py','docs/protocols/issue139-source-inventory-v3.md']


def bindings():return {p:digest((REPO/p).read_bytes()) for p in FILES}


def prepare(path):
    raw=LEDGER.read_bytes()
    if digest(raw)!=EXPECTED:raise SourceError('ledger drift; incremental scope review required')
    if ROOT.exists() or BUDGET.exists():raise SourceError('continuation already attempted')
    prior=json.loads((REPO/'docs/issue139-spot-launch-v2.json').read_text())
    names={'001-exchangeInfo.json':'metadata','002-klines.json':'warmup_BTC','003-klines.json':'warmup_ETH','004-klines.json':'BTC_page1'}
    hashes={names[n]:dict(path=str(OLD/'raw'/n),sha256=h) for n,h in prior['reuse_hashes'].items()}
    hashes['BTC_page2']=dict(path=str(OLD/'continuation-v2/raw/005-klines.json'),sha256='74bc04b810500293d57e459927606921ebb052d58f1135179470c2252bc1afa1')
    retained=reuse(hashes);cursor=retained['BTC_page2'][-1][0]+3600000
    if digest(PARENT.read_bytes())!='486bc2a541d52fd72a454699f8bc339fbaf225f02ccf23e71d7dac7ee1413924':raise SourceError('v2 budget changed')
    record=dict(record_type='SPOT_SOURCE_INVENTORY_REGISTERED',issue=139,exchange='binance',instrument_type='SPOT',symbols=['BTCUSDT','ETHUSDT'],
        source_window=['2020-04-02T00:00:00Z','2023-01-01T00:00:00Z'],training_window=['2021-01-01T00:00:00Z','2023-01-01T00:00:00Z'],
        purpose='EXPLORATORY_EXPOSED_SOURCE_INVENTORY_NOT_EXECUTION',independent_evidence=False,prior_ledger_sha256=EXPECTED,
        protocol_sha256=bindings()['docs/protocols/issue139-source-inventory-v3.md'],native_authorized=False,
        authorization='supervisor:01a07c6a-d535-7030-814c-7775d0f27f99/afe06be-inventory-approved',prepared_at_utc=dt.datetime.now(dt.timezone.utc).isoformat())
    controls=prior['controls'].copy()
    controls.update({str(OLD/'continuation-v2/terminal.json'):'64732bccefec28b027988ba6c0ae2c37d0559aab50fa96c8da7dbe681bb67f71',str(PARENT):digest(PARENT.read_bytes()),str(OLD/'terminal.json'):digest((OLD/'terminal.json').read_bytes()),str(RUN/'btc-eth-portfolio-v1/acquisition-continuation-v2.json'):'9f9ed03a227070842591370bb6a2d07f7175d9057d0b2e3a2b025319794b3897'})
    m=dict(files=bindings(),root=str(ROOT),budget=str(BUDGET),reuse_hashes=hashes,btc_cursor=cursor,controls=controls,ledger_before=EXPECTED,ledger_after=digest(raw+encoded(record)),registration=record,
        python=str(Path(sys.executable).resolve()),python_sha256=digest(Path(sys.executable).resolve().read_bytes()),native_authorized=False,
        limits=dict(new_gets=34,new_bytes=16305102,new_seconds=895,response_bytes=1048576,request_seconds=20,retries=0,redirects=0))
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
        retained=reuse(m['reuse_hashes'])
        if ROOT.exists() or BUDGET.exists():raise SourceError('one shot already attempted')
        b=InventoryBudget(BUDGET,ROOT,json.loads(PARENT.read_bytes()))
        ROOT.mkdir();(ROOT/'raw').mkdir();post=False
        try:
            old=LEDGER.read_bytes()
            if not old.endswith(b'\n') or digest(old+encoded(m['registration']))!=m['ledger_after']:raise SourceError('own registration mismatch')
            with LEDGER.open('ab') as f:f.write(encoded(m['registration']));f.flush();os.fsync(f.fileno())
            post=True;verify(m,path,sha,True)
            write_json(ROOT/'activation.json',dict(launch_sha256=sha,ledger_after=m['ledger_after'],native_authorized=False))
            receipt=collect_inventory(SpotFetcher(b,ROOT,lambda:verify(m,path,sha,True)),retained,m['btc_cursor'])
        except BaseException as exc:receipt=dict(status='BLOCKED_DATA' if post else 'BLOCKED_CONTROL',reason=str(exc),native_calls=0,economic_result=None)
        try:verify(m,path,sha,post)
        except Exception as exc:receipt.update(status='CONTROL_INTEGRITY',reason=str(exc))
        elapsed=b.now()-b.state['started']
        if elapsed>895:receipt.update(status='BLOCKED_DATA',reason='active time budget exceeded')
        b.terminal(receipt['status']);new=b.state['attempts'][5:]
        receipt.update(launch_sha256=sha,ledger_after=digest(LEDGER.read_bytes()),new_gets=len(new),spot_cumulative_gets=len(b.state['attempts']),global_cumulative_gets=73+len(b.state['attempts']),
            new_charged_bytes=b.state['charged_bytes']-472114,spot_cumulative_bytes=b.state['charged_bytes'],global_cumulative_bytes=14603929+b.state['charged_bytes'],
            new_active_seconds=elapsed,spot_cumulative_seconds=3.841052293777466+elapsed,global_cumulative_seconds=169.6002914905548+elapsed,
            reused_hashes=m['reuse_hashes'],budget_sha256=digest(BUDGET.read_bytes()),responses=[dict(number=r['number'],endpoint=r['endpoint'],status=r['status'],bytes=r['charged_bytes'],sha256=r.get('sha256')) for r in new])
        write_json(ROOT/'terminal.json',receipt);print(json.dumps(receipt,sort_keys=True))
        return 0 if receipt['status']=='SOURCE_INVENTORY_COMPLETE_NOT_EXECUTION_ADMITTED' else 2


def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['prepare','capture']);p.add_argument('manifest',type=Path);a=p.parse_args()
    try:return prepare(a.manifest) if a.action=='prepare' else capture(a.manifest)
    except SourceError as exc:print(json.dumps(dict(status='BLOCKED_CONTROL',reason=str(exc))));return 2
if __name__=='__main__':sys.exit(main())
