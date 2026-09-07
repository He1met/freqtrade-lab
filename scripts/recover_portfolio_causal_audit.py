#!/usr/bin/env python3
"""Re-audit the immutable synthetic/6 archive; no native execution interface."""
from pathlib import Path
import hashlib
import json
import subprocess
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from lab.portfolio_budget import NativeBudget,RUNTIME_ROOT,verify_anchor,checkpoint_budget,canonical,BudgetError
from lab.portfolio_native_export import read_strategy_export
from lab.portfolio_causal_audit import audit_causal
from lab.portfolio_causal_fixture import expand,input_sha
from scripts.run_portfolio_synthetic import verify_environment,sha
from scripts.dispatch_portfolio_causal_probe import write_new
REPO=Path(__file__).resolve().parents[1]
SOURCE=Path.home()/'.codex/runs/freqtrade-lab/issue-43-profile-driven-v1/freqtrade'


def recover():
    plan=json.loads((REPO/'docs/issue115-synthetic6-observed.json').read_bytes())
    root=RUNTIME_ROOT/'runs/synthetic-6'
    # This receipt was published before recovery; it fixes original bytes.
    hashes={**plan['artifact_sha256'],'runs/synthetic-6/evidence.json':plan['original_failed_evidence_sha256']}
    def verify_artifacts():
        for name,expected in hashes.items():
            if sha(RUNTIME_ROOT/name)!=expected: raise BudgetError('original artifact hash changed')
    with NativeBudget(RUNTIME_ROOT).locked() as budget:
        verify_anchor();verify_artifacts()
        if sha(RUNTIME_ROOT/'calls.jsonl')!=plan['budget_sha256']:
            raise BudgetError('budget changed since published failed attempt')
        reservation=next((e for e in budget.events if e['key']=='synthetic/6' and e['event']=='RESERVED'),None)
        if reservation is None or not any(e['key']=='synthetic/6' and e['event']=='FAILED' for e in budget.events):
            raise BudgetError('original failed reservation missing')
        if budget.pending() or any(e['key']=='synthetic/6' and e['event']=='AUDIT_RECOVERED' for e in budget.events):
            raise BudgetError('pending or already recovered attempt')
        binding=json.loads((root/'bindings.json').read_bytes())
        for name in ('input_sha256','code_sha256','source_sha256','semantics_sha256'):
            if binding.get(name)!=reservation.get(name): raise BudgetError('original reservation binding mismatch')
        if input_sha()!=reservation['input_sha256'] or binding['input_sha256']!=plan['input_sha256']:
            raise BudgetError('original input changed')
        if hashlib.sha256(canonical(binding['code'])).hexdigest()!=reservation['code_sha256']:
            raise BudgetError('original code manifest changed')
        tree=verify_environment(SOURCE)
        if tree!=binding['source_tree'] or hashlib.sha256(tree.encode()).hexdigest()!=reservation['source_sha256']:
            raise BudgetError('original native source changed')
        # The parser is repaired, but the full control/economic audit and its
        # causal/execution dependencies must have exactly their execution bytes.
        for name in ('lab/portfolio_causal_audit.py','lab/portfolio_execution.py','lab/portfolio_causal.py','lab/portfolio_causal_fixture.py'):
            if sha(REPO/name)!=binding['code'][name]: raise BudgetError('original audit rules changed')
        recovery_files=('scripts/recover_portfolio_causal_audit.py','lab/portfolio_native_export.py')
        recovery_code={name:sha(REPO/name) for name in recovery_files}
        head=subprocess.check_output(['git','-C',str(REPO),'rev-parse','HEAD'],text=True).strip()
        archives=[RUNTIME_ROOT/name for name in hashes if name.endswith('.zip')]
        if len(archives)!=1: raise BudgetError('published archive ambiguous')
        target=root/'audit-evidence.json'
        if target.exists(): raise BudgetError('audit artifact already exists')
        result=read_strategy_export(archives[0],'PortfolioCausalProbe')
        trace=json.loads((root/'trace.json').read_bytes())
        try:
            audit=audit_causal(result,trace,expand()[1])
            audit_status='PASSED'
        except Exception as exc:
            audit_status='FAILED'
            audit=dict(error_type=type(exc).__name__,reason=str(exc),halt_liquidation=getattr(exc,'receipt',None))
        verify_artifacts()
        if verify_environment(SOURCE)!=tree or any(sha(REPO/name)!=value for name,value in recovery_code.items()):
            raise BudgetError('recovery code/source changed during audit')
        evidence=dict(schema='synthetic6-readonly-audit-recovery-v1',audit_status=audit_status,audit=audit,
            original_budget_status='FAILED',original_artifact_sha256=hashes,
            reservation_sha256=hashlib.sha256(canonical(reservation)).hexdigest(),
            original_code_sha256=reservation['code_sha256'],input_sha256=reservation['input_sha256'],
            source_sha256=reservation['source_sha256'],recovery_commit=head,recovery_code=recovery_code,
            recovery_code_sha256=hashlib.sha256(canonical(recovery_code)).hexdigest(),
            additional_native_constructors=0,additional_backtesting_start_calls=0,
            meaning='AUDIT_RECOVERED records recovered evidence, not control success; original FAILED preserved',
            market_execution_allowed=False,economic_result=None)
        result_hash=write_new(target,evidence)
        budget.recover_audit('synthetic/6',result_hash)
        checkpoint_budget()
        print(json.dumps(dict(status='AUDIT_RECORDED',audit_status=audit_status,evidence=str(target),
                              sha256=result_hash,additional_native_calls=0)))


if __name__=='__main__': recover()
