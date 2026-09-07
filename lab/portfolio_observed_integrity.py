"""Frozen pre-call file identities and unconditional terminal integrity audit."""
import hashlib
import importlib.metadata
import json
from pathlib import Path
import subprocess
import sys
from lab.portfolio_observed_prepare import ROOT,PREPARED,ACTIVATION,NATIVE_SOURCE,DEPENDENCIES
from lab.portfolio_observed_source import RECEIPT,RAW_ROOT,RECEIPT_SHA
from lab.portfolio_source import SourceError


def git_state(path):
    def git(*args):
        return subprocess.check_output(['git','-C',str(path),*args],text=True,timeout=10).strip()
    return dict(commit=git('rev-parse','HEAD'),tree=git('rev-parse','HEAD^{tree}'),
                dirty=git('status','--porcelain','--untracked-files=all'))


def controlled_hashes(manifest_path,manifest,manifest_raw,activation_raw,plan_raw,
                      *, prepared=PREPARED, activation_path=ACTIVATION):
    receipt_raw=RECEIPT.read_bytes()
    if hashlib.sha256(receipt_raw).hexdigest()!=RECEIPT_SHA:
        raise SourceError('CONTROL_INTEGRITY source receipt changed before freeze')
    receipt=json.loads(receipt_raw)
    expected={str(ROOT/name):value for name,value in manifest['code_files'].items()}
    expected.update({str(prepared/'data'/name):value for name,value in manifest['data_files'].items()})
    expected.update({str(RAW_ROOT/item['name']):item['sha256'] for item in receipt['source_files']})
    expected.update({str(RECEIPT):RECEIPT_SHA,
        str(Path(sys.executable)):manifest['environment']['interpreter_sha256'],
        str(manifest_path):hashlib.sha256(manifest_raw).hexdigest(),
        str(activation_path):hashlib.sha256(activation_raw).hexdigest(),
        str(prepared/'plan.json'):hashlib.sha256(plan_raw).hexdigest(),
        str(prepared/'assembly.json'):manifest['assembly_sha256'],
        str(prepared/'events.json'):manifest['funding_event_table_sha256']})
    return expected


def snapshot(paths):
    result={'files':{},'errors':{}}
    for name in paths:
        try:result['files'][name]=hashlib.sha256(Path(name).read_bytes()).hexdigest()
        except Exception as exc:result['errors'][name]=f'{type(exc).__name__}: {exc}'
    for label,reader in (
        ('project',lambda:git_state(ROOT)),('native',lambda:git_state(NATIVE_SOURCE)),
        ('environment',lambda:dict(python=sys.version,executable=sys.executable,
                                  packages={k:importlib.metadata.version(k) for k in DEPENDENCIES}))):
        try:result[label]=reader()
        except Exception as exc:result['errors'][label]=f'{type(exc).__name__}: {exc}'
    return result


def freeze(paths,expected=None):
    result=snapshot(paths)
    if expected is not None and result["files"]!=expected:
        raise SourceError("CONTROL_INTEGRITY approved hashes changed at reservation boundary")
    if result['errors'] or result['project']['dirty'] or result['native']['dirty']:
        raise SourceError('CONTROL_INTEGRITY cannot freeze invalid pre-call controls')
    return result


def terminal_audit(before):
    after=snapshot(before['files'])
    return dict(status='PASS' if before==after else 'CONTROL_INTEGRITY',before=before,after=after)
