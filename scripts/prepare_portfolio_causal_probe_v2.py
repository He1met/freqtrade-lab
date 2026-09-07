#!/usr/bin/env python3
"""Read-only synthetic/7 preparation; no reservation or native execution CLI."""
from pathlib import Path
import argparse,hashlib,json,sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from lab.portfolio_budget import LockedBudget,RUNTIME_ROOT,verify_anchor,BudgetError,canonical
from lab.portfolio_causal import BASE_SHA
from lab.portfolio_risk_v2 import V2_SHA,verify_v2
from lab.portfolio_causal_fixture_v2 import input_sha,expand
from scripts.prepare_portfolio_causal_probe import CODE_FILES as V1_FILES,REPO,run_engine
from scripts.run_portfolio_synthetic import verify_environment,SOURCE_COMMIT,sha
CODE_FILES=tuple(dict.fromkeys((*V1_FILES,'lab/portfolio_risk_v2.py','lab/portfolio_causal_fixture_v2.py',
            'lab/portfolio_causal_strategy_v2.py','lab/portfolio_causal_audit_v2.py','scripts/prepare_portfolio_causal_probe_v2.py')))


def verify_manifest(binding,source):
    verify_v2(binding.get('base_protocol_sha256'),binding.get('semantics_sha256'))
    code=binding.get('code')
    if not isinstance(code,dict) or set(code)!=set(CODE_FILES): raise BudgetError('v2 manifest paths differ')
    if hashlib.sha256(canonical(code)).hexdigest()!=binding.get('code_sha256'): raise BudgetError('v2 code manifest mismatch')
    if any(sha(REPO/p)!=value for p,value in code.items()) or input_sha()!=binding.get('input_sha256'):
        raise BudgetError('v2 code/input changed')
    tree=verify_environment(source)
    if tree!=binding.get('source_tree') or binding.get('source_commit')!=SOURCE_COMMIT or hashlib.sha256(tree.encode()).hexdigest()!=binding.get('source_sha256'):
        raise BudgetError('v2 source changed')


def prepare(source):
    verify_v2(BASE_SHA,V2_SHA);verify_anchor()
    tree=verify_environment(source);b=LockedBudget(RUNTIME_ROOT)
    if b.pending() or any(e['key']=='synthetic/7' for e in b.events):raise BudgetError('synthetic/7 unavailable')
    code={p:sha(REPO/p) for p in CODE_FILES}
    return dict(status='PREPARED_NOT_EXECUTION_AUTHORIZED',key='synthetic/7',base_protocol_sha256=BASE_SHA,
        semantics_sha256=V2_SHA,input_sha256=input_sha(),code=code,code_sha256=hashlib.sha256(canonical(code)).hexdigest(),
        source_commit=SOURCE_COMMIT,source_tree=tree,source_sha256=hashlib.sha256(tree.encode()).hexdigest(),
        budget_prefix_sha256=sha(RUNTIME_ROOT/'calls.jsonl'),existing_reserved_slots=sum(e['event']=='RESERVED' for e in b.events),
        expected_assertions=['real_daily_indicators','hard_cap_full_exit_actual_fill','strict_next_UTC_daily_pause',
            'actual_resume_day1','second_cycle_actual_flat','paused_episode_aging','halt_same_hour_liquidation','net_fee_slippage'],
        old_synthetic6='PERMANENT_NEGATIVE',cash_insufficiency='NOT_COVERED_NATIVE',funding_real_settlement='UNVERIFIED',
        native_calls_this_preparation=0,market_execution_allowed=False)


def run_reserved(root,source,binding):
    verify_manifest(binding,source);verify_anchor()
    if root!=RUNTIME_ROOT/'runs/synthetic-7' or root.is_symlink():raise BudgetError('fixed v2 root required')
    pending=LockedBudget(RUNTIME_ROOT).pending()
    if len(pending)!=1 or pending[0]['key']!='synthetic/7':raise BudgetError('sole durable synthetic/7 reservation required')
    if any(pending[0].get(k)!=binding.get(k) for k in ('input_sha256','code_sha256','source_sha256','semantics_sha256')):
        raise BudgetError('v2 reservation mismatch')
    from lab.portfolio_causal_audit_v2 import audit_v2
    return run_engine(root,source,expand(),'PortfolioCausalProbeV2',input_sha(),audit_v2)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--native-source',type=Path,required=True)
    print(json.dumps(prepare(parser.parse_args().native_source.resolve(strict=True)),indent=2))
