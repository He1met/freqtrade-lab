"""Issue92 one-off registration and freeze; no acquisition or native backtest."""
import hashlib
import json
import os
import shutil
import subprocess
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from lab import bounded_research as pilot, codex_generation as generation
from lab.bounded_strategy import analyze_bounded_causal_strategy
from lab.database import init_database, get_connection
from lab.search_campaign import _candidate_plan
from scripts import fetch_okx_profile_data as producer

ROOT=Path(__file__).resolve().parent
PROJECT=Path('/Users/shenjianpeng/.codex/worktrees/7183/freqtrade-lab')
HEAD='0e4d8e9d33b806239bb13d618b4db2881a892ac3'

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def write(name,value):
    with (ROOT/name).open('xb') as f:
        f.write(pilot.canonical(value));f.flush();os.fsync(f.fileno())

def main():
    assert not (ROOT/'research.sqlite').exists() and not (ROOT/'source').exists()
    assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=PROJECT,text=True).strip()==HEAD
    assert not subprocess.check_output(['git','status','--porcelain'],cwd=PROJECT,text=True).strip()
    issue=json.loads((ROOT/'issue-latest.json').read_text())
    assert issue['number']==92 and issue['state']=='OPEN'
    assert not json.loads((ROOT/'identity-check.json').read_text())['atom_matches']
    checks=json.loads((ROOT/'guard-self-test.json').read_text())
    assert checks['network_requests']==0 and checks['original_stub_calls']==24 and checks['attempt_25_rejected_before_original']
    protocol=sha(ROOT/'protocol.md')
    runtime=producer.validate_runtime()  # only installed versions and local Git identity
    src=(ROOT/'AtomRegimePullbackV1.py').read_text()
    analysis=analyze_bounded_causal_strategy(src,'AtomRegimePullbackV1',expected_timeframe='1d')
    assert analysis.max_lookback==analysis.startup_candle_count==200
    created=datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
    profile_id,generation_id,campaign_id=(str(uuid4()) for _ in range(3))
    db=init_database(ROOT/'research.sqlite')
    values=dict(id=profile_id,name='ATOM_REGIME_PULLBACK_V1',domain='OKX_CRYPTO_SPOT',exchange='okx',trading_mode='spot',margin_mode='',pairs_json='["ATOM/USDT"]',timeframe='1d',detail_timeframe=None,history_start_date='2021-02-13',smoke_days=7,holdout_days=515,starting_balance=1000.,stake_amount=500.,max_open_trades=1,taker_fee_rate=.001,stress_fee_multiplier=2.,max_drawdown_pct=20.,min_development_trades=12,min_holdout_trades=12,min_profit_factor=1.,is_default=0,created_at=created,updated_at=created)
    with get_connection(db) as connection:
        connection.execute('INSERT INTO research_profiles ('+','.join(values)+') VALUES ('+','.join('?' for _ in values)+')',tuple(values.values()))
        profile=generation.load_profile_snapshot(connection,profile_id);connection.commit()
    request=generation.validate_generation_request(dict(profile_id=profile_id,strategy_family='atom_regime_pullback_v1',idea='Issue92 fixed value-blind full-rule baseline; protocol SHA256 '+protocol,expected_failure_mode='Persistent selloff, falling mean, regime failure, costs, clustered trades and insufficient complete extended exposure groups. No incremental filter-effect claim.'))
    prepared=generation.start_generation(db,generation_id,request,model=None,started_at=created)
    raw=pilot.canonical(dict(display_name='ATOM regime pullback V1',class_name='AtomRegimePullbackV1',code_text=src))
    candidate_id=generation.complete_generation(db,prepared,generation.parse_candidate_output(raw,timeframe='1d'),raw_output=raw,jsonl_summary={'event_count':0,'tool_event_count':0},finished_at=created)
    generation.review_generation(db,generation_id,'APPROVED',decided_at=created)
    with get_connection(db,read_only=True) as connection:
        connection.execute('BEGIN')
        approved=generation.load_approved_candidate_snapshot(connection,candidate_id)
        counts={t:connection.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in ('research_profiles','generation_runs','candidates','research_runs','backtest_executions','releases')}
    assert list(counts.values())==[1,1,1,0,0,0]
    single=pilot.validate_single_baseline(dict(mode='SINGLE_BASELINE_V1',version=1,maximum_rounds=1,maximum_attempts=1,protocol_sha256=protocol,strategy_sha256=sha(ROOT/'AtomRegimePullbackV1.py')))
    contract=producer.configure_profile_acquisition(db,profile_id,ROOT/'window-spec.json',200,single_baseline=single)
    plan=_candidate_plan(approved,'strategies/round-1-'+candidate_id+'.py',round_number=1,changed_factor=None,parent_sha256=None)
    write('single-baseline.json',single);write('profile-snapshot.json',profile)
    write('acquisition-contract.json',contract);write('runtime-config.json',pilot.profile_search_config(profile));write('candidate-output.json',json.loads(raw))
    write('search-plan-intent.json',dict(schema='issue92-value-blind-search-intent-v1',campaign_id=campaign_id,candidate=plan,strategy_analysis=asdict(analysis),profile_contract=pilot.profile_search_contract(profile,'20210901-20230901','20230901-20250101',200,single_baseline=single),data_provenance_sha256=None,source_receipt_sha256=None,executable=False,status='SEARCH_NOT_AUTHORIZED'))
    snapshot=ROOT/'producer-frozen';snapshot.mkdir()
    originals=[PROJECT/'scripts/fetch_okx_profile_data.py',producer.HISTORICAL_PRODUCER]
    producer_hashes={str(p):sha(p) for p in originals}
    for i,p in enumerate(originals):shutil.copyfile(p,snapshot/('profile.py' if i==0 else 'historical.py'))
    paths=['protocol.md','AtomRegimePullbackV1.py','window-spec.json','single-baseline.json','profile-snapshot.json','acquisition-contract.json','runtime-config.json','candidate-output.json','search-plan-intent.json','acquire_with_budget.py','guard-parameters.json','guard-self-test.json','prepare_registration.py','issue-latest.json','identity-check.json','producer-frozen/profile.py','producer-frozen/historical.py']
    write('freeze-receipt.json',dict(schema='issue92-value-blind-freeze-v1',created_at=created,issue=92,status='FROZEN_BEFORE_FIRST_SOURCE_REQUEST',database=str(db),profile_id=profile_id,generation_id=generation_id,candidate_id=candidate_id,planned_campaign_id=campaign_id,research_run_id=None,counts=counts,protocol_sha256=protocol,files_sha256={n:sha(ROOT/n) for n in paths},database_initial_sha256=sha(db),native_identity=runtime,project_commit=HEAD,producer_files_sha256=producer_hashes,generation_origin={'kind':'CURRENT_CODEX_TASK_DIRECT_SOURCE_VIA_EXISTING_API','codex_cli_executed':False,'model':None,'reasoning':None,'tier':None},source={'status':'NOT_REQUESTED','output_root':str(ROOT/'source'),'planned_rows':1418,'planned_http_requests':16,'request_hard_budget':24,'maximum_seconds':1800,'automatic_retries':0,'hard_budget_enforced':True},real_search={'used':0,'maximum_attempts':1,'maximum_rounds':1,'authorized':False},approvals={'source':True,'search':False,'development':False,'holdout':False,'finalist_import':False},development='PRODUCER_QC_ONLY_NO_ECONOMIC_READ',holdout='SEALED_UNREAD_NOT_ACQUIRED',holdout_stress='SEALED_UNREAD',qualification={'all_extra_audits_are_hard_gates':True,'native_finalist_pending_until_extra_audits_pass':True,'specification':'protocol.md','group_counts':{'S':8,'D':6,'H':6},'natural_trades_each_stage':12}))
    print(json.dumps({'profile_id':profile_id,'generation_id':generation_id,'candidate_id':candidate_id,'planned_campaign_id':campaign_id,'freeze_sha256':sha(ROOT/'freeze-receipt.json'),'protocol_sha256':protocol,'strategy_sha256':sha(ROOT/'AtomRegimePullbackV1.py'),'counts':counts}))

if __name__=='__main__':main()
