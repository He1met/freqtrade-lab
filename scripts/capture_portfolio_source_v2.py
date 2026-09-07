#!/usr/bin/env python3
"""One explicitly approved V2 continuation; no native or economic evaluation."""
import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO))
from lab.portfolio_source import SourceError,check_scope,collect,digest,Fetcher,ms,qc_summary,read_json,register,write_json
from lab.portfolio_source_continuation import continuation_allowance,locked_continuation

CONTRACT=REPO/'docs/protocols/issue123-source-continuation-v2.json'
SCOPE=REPO/'docs/issue121-scope-snapshot.json'
FILES=('lab/__init__.py','lab/database.py','lab/portfolio_source.py','lab/portfolio_source_continuation.py',
       'scripts/capture_portfolio_source_v2.py','docs/protocols/issue123-source-continuation-v2.json',
       'docs/issue121-scope-snapshot.json')


def bindings():
    return {p:digest((REPO/p).read_bytes()) for p in FILES}


def prepare(path):
    c=read_json(CONTRACT)
    check_scope(c,read_json(SCOPE),Path(c['registry']).read_bytes())
    continuation_allowance(Path(c['parent_budget_path']).read_bytes(),c)
    python=str(Path(sys.executable).resolve())
    m=dict(schema='issue123-full-launch-manifest-v2',files=bindings(),python=python,
           python_sha256=digest(Path(python).read_bytes()),
           code_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip(),
           command=[python,str(Path(__file__).resolve()),'capture',str(Path(path).resolve())],
           wrappers=[],parent_budget_sha256=c['parent_budget_sha256'],
           output_root=c['output_root'],budget_path=c['budget_path'],native_authorized=False)
    write_json(path,m)
    print(json.dumps({'manifest_sha256':digest(Path(path).read_bytes())}))


def verify(path,expected=None):
    raw=Path(path).read_bytes();m=json.loads(raw)
    if expected is not None and digest(raw)!=expected:raise SourceError('manifest changed')
    if m['files']!=bindings():raise SourceError('code/contract/scope drift')
    if m['python']!=str(Path(sys.executable).resolve()) or m['python_sha256']!=digest(Path(sys.executable).resolve().read_bytes()):
        raise SourceError('interpreter drift')
    c=read_json(CONTRACT)
    if digest(Path(c['parent_budget_path']).read_bytes())!=c['parent_budget_sha256'] or m['parent_budget_sha256']!=c['parent_budget_sha256']:
        raise SourceError('parent budget drift')
    if m['command']!=[m['python'],str(Path(__file__).resolve()),'capture',str(Path(path).resolve())] or m['wrappers']:
        raise SourceError('launch drift')
    if m['output_root']!=c['output_root'] or m['budget_path']!=c['budget_path']:
        raise SourceError('budget/root drift')
    return c,digest(raw)


def capture(path):
    c,manifest_sha=verify(path)
    root=Path(c['output_root'])
    if root.exists():raise SourceError('continuation root already exists')
    check_scope(c,read_json(SCOPE),Path(c['registry']).read_bytes())
    with locked_continuation(c['parent_budget_path'],c,c['authorization']) as budget:
        # Recheck all bindings under the acquisition lock before registry write.
        phase='CONTROL'
        try:
            verify(path,manifest_sha)
            if str(budget.path)!=c['budget_path'] or budget.state['segment_root']!=str(root):
                raise SourceError('cumulative budget binding mismatch')
            root.mkdir();(root/'raw').mkdir()
            registration=register(c,read_json(SCOPE),c['registry'],manifest_sha,issue=123)
            write_json(root/'registration.json',registration)
            phase='DATA'
            fetch=Fetcher(budget,root)
            info=fetch.get('exchangeInfo',{})
            adjustment=fetch.get('fundingInfo',{})
            if not isinstance(adjustment,list):raise SourceError('funding metadata shape')
            for symbol in c['symbols']:
                selected=[r for r in info['symbols'] if r['symbol']==symbol]
                if len(selected)!=1 or selected[0]['contractType']!='PERPETUAL' or selected[0]['onboardDate']>ms(c['start']):
                    raise SourceError('contract metadata mismatch')
            start,end=ms(c['start']),ms(c['end_exclusive'])
            data={s:{} for s in c['symbols']}
            for symbol in c['symbols']:
                data[symbol]['fundingRate']=collect(fetch,'fundingRate',symbol,start,end)
            for symbol in c['symbols']:
                for kind in ('klines','markPriceKlines'):
                    data[symbol][kind]=collect(fetch,kind,symbol,start,end)
            summary=qc_summary(data,start,end)
            if budget.remaining_time()<=0:raise SourceError('active time exhausted')
        except Exception as exc:
            summary=dict(status='BLOCKED_CONTROL' if phase=='CONTROL' else 'BLOCKED_DATA',
                         structure='INCOMPLETE_OR_FAILED',reason=str(exc),executable_source_published=False,
                         economic_result=None,market_native_calls=0,historical_interval_evidence='UNKNOWN')
        try:
            verify(path,manifest_sha)
            summary['terminal_binding_check']='PASS'
        except Exception as exc:
            summary.update(status='CONTROL_INTEGRITY',terminal_binding_check='FAIL',reason=str(exc),executable_source_published=False)
        summary.update(funding_eligibility='UNKNOWN',settlement_precision='UNKNOWN',
                       requests_new=len(budget.state['attempts'])-37,requests_cumulative=len(budget.state['attempts']),
                       charged_bytes_cumulative=budget.state['charged_bytes'],
                       parent_seconds_conservative_charge=130,
                       active_seconds_new=budget.now()-budget.state['continuation_started'],
                       launch_manifest_sha256=manifest_sha,parent_budget_sha256=c['parent_budget_sha256'])
        budget.state['active_seconds_new']=summary['active_seconds_new']
        budget.terminal(summary['status'])
        summary['budget_sha256']=digest(budget.path.read_bytes())
        # If control failed before root creation, retain terminal at shared budget
        # directory, never invent a source root or publish a source-ready file.
        target=(root if root.exists() else budget.path.parent)/'qc-v2-receipt.json'
        write_json(target,summary)
        print(json.dumps(summary,sort_keys=True))
        return 0 if summary['status']=='PASS' else 2


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['prepare','capture']);p.add_argument('manifest',type=Path);a=p.parse_args()
    try:return prepare(a.manifest) if a.action=='prepare' else capture(a.manifest)
    except SourceError as exc:
        print(json.dumps({'status':'BLOCKED_CONTROL','reason':str(exc)}));return 2


if __name__=='__main__':raise SystemExit(main())
