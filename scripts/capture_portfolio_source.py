#!/usr/bin/env python3
"""Offline prepare; then the explicitly authorized one-shot public capture."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from lab.portfolio_source import (Budget, Fetcher, SourceError, check_scope, collect,
                                  digest, exclusive, ms, qc_summary, read_json,
                                  register, write_json)

CONTRACT = REPO / 'docs/protocols/issue119-source-contract.json'
SCOPE = REPO / 'docs/issue119-scope-snapshot.json'
FILES = ('lab/portfolio_source.py', 'scripts/capture_portfolio_source.py',
         'docs/protocols/issue119-source-contract.json', 'docs/issue119-scope-snapshot.json')


def prepare(target):
    contract = read_json(CONTRACT)
    check_scope(contract, read_json(SCOPE), Path(contract['registry']).read_bytes())
    manifest = dict(schema='issue119-launch-manifest-v1',
                    code_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip(),
                    files={f:digest((REPO/f).read_bytes()) for f in FILES},
                    python=str(Path(sys.executable).resolve()),
                    python_sha256=digest(Path(sys.executable).resolve().read_bytes()),
                    command=[str(Path(sys.executable).resolve()),str(Path(__file__).resolve()),'capture',str(Path(target).resolve())],
                    external_root=contract['output_root'], budget=contract['budget_path'],
                    wrappers=[], native_authorized=False)
    write_json(target, manifest)
    print(json.dumps({'manifest':str(target),'sha256':digest(Path(target).read_bytes())}))


def verify_manifest(target, expected_sha=None):
    raw = Path(target).read_bytes()
    if expected_sha is not None and digest(raw) != expected_sha:
        raise SourceError('launch manifest changed during capture')
    manifest = json.loads(raw)
    if set(manifest['files']) != set(FILES):
        raise SourceError('manifest file coverage mismatch')
    for f, expected in manifest['files'].items():
        if digest((REPO/f).read_bytes()) != expected:
            raise SourceError('manifest drift: '+f)
    if (str(Path(sys.executable).resolve()) != manifest['python'] or
        digest(Path(sys.executable).resolve().read_bytes()) != manifest['python_sha256']):
        raise SourceError('Python runtime drift')
    return manifest, digest(raw)


def capture(target):
    manifest, manifest_sha = verify_manifest(target)
    contract, snapshot = read_json(CONTRACT), read_json(SCOPE)
    root, budget_path = Path(contract['output_root']), Path(contract['budget_path'])
    if manifest['external_root'] != str(root) or manifest['budget'] != str(budget_path):
        raise SourceError('root/budget binding mismatch')
    if manifest['command'] != [manifest['python'],str(Path(__file__).resolve()),'capture',str(Path(target).resolve())] or manifest['wrappers']:
        raise SourceError('launch command mismatch')
    with exclusive(str(budget_path)+'.lock'):
        check_scope(contract, snapshot, Path(contract['registry']).read_bytes())
        if root.exists():
            raise SourceError('source root already exists')
        # Budget initialized before registration/network; interrupted control steps
        # retain the same root and cannot reset the allowance.
        budget = Budget(budget_path, root, contract['limits'])
        root.mkdir(parents=True)
        (root/'raw').mkdir()
        phase = 'CONTROL'
        try:
            receipt = register(contract, snapshot, contract['registry'], manifest_sha)
            write_json(root/'registration.json', receipt)
            phase = 'DATA'
            fetcher = Fetcher(budget, root)
            metadata = fetcher.get('exchangeInfo', {})
            info = fetcher.get('fundingInfo', {})
            for symbol in contract['symbols']:
                selected = [x for x in metadata['symbols'] if x['symbol']==symbol]
                if len(selected)!=1 or selected[0]['contractType']!='PERPETUAL' or selected[0]['onboardDate']>ms(contract['start']):
                    raise SourceError('contract identity/history-start metadata failed')
            if not isinstance(info, list):
                raise SourceError('fundingInfo response shape')
            start,end = ms(contract['start']),ms(contract['end_exclusive'])
            data = {}
            for symbol in contract['symbols']:
                data[symbol] = {}
                for kind in ('klines','markPriceKlines','fundingRate'):
                    data[symbol][kind] = collect(fetcher,kind,symbol,start,end)
            summary = qc_summary(data,start,end)
            if budget.remaining_time() <= 0:
                raise SourceError('capture wall-clock budget exhausted')
        except Exception as exc:
            summary = dict(status='BLOCKED_CONTROL' if phase=='CONTROL' else 'BLOCKED_DATA',structure='INCOMPLETE_OR_FAILED',
                           reason=str(exc),historical_interval_evidence='UNKNOWN',
                           executable_source_published=False,market_native_calls=0,economic_result=None)
        # Check both successful and failed DATA paths before a terminal receipt.
        # The original launch identity is immutable even if its file changes.
        try:
            verify_manifest(target, expected_sha=manifest_sha)
            summary['terminal_binding_check'] = 'PASS'
        except Exception as exc:
            summary.update(status='CONTROL_INTEGRITY',terminal_binding_check='FAIL',
                           reason=type(exc).__name__ + ': ' + str(exc),
                           executable_source_published=False)
        budget.terminal(summary['status'])
        summary.update(requests=len(budget.state['attempts']), charged_bytes=budget.state['charged_bytes'],
                       budget_sha256=digest(budget_path.read_bytes()),
                       launch_manifest_sha256=manifest_sha)
        write_json(root/'qc-receipt.json',summary)
        print(json.dumps(summary,sort_keys=True))
        return 0 if summary['status']=='PASS' else 2


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['prepare','capture'])
    parser.add_argument('manifest',type=Path)
    args=parser.parse_args()
    try:
        return prepare(args.manifest) if args.action=='prepare' else capture(args.manifest)
    except SourceError as exc:
        print(json.dumps({'status':'BLOCKED_CONTROL','reason':str(exc)}))
        return 2


if __name__=='__main__':
    raise SystemExit(main())
