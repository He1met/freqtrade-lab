"""Issue93: approved direct-source registration, logical binding, pre-value freeze."""
import hashlib
import json
import os
import subprocess
from contextlib import closing
from dataclasses import asdict
from datetime import datetime,timezone
from pathlib import Path
from uuid import uuid4
from lab import bounded_research as pilot,codex_generation as generation
from lab.bounded_strategy import analyze_bounded_causal_strategy
from lab.database import init_database,get_connection
from lab.search_campaign import _candidate_plan
from scripts import fetch_okx_profile_data as producer
from binding import logical_snapshot,TABLES

ROOT=Path(__file__).resolve().parent
PROJECT=Path('/Users/shenjianpeng/.codex/worktrees/3c7c/freqtrade-lab')
HEAD='7ae2b6b6c45cfb57c40a13dccd697ce1c57d08a4'
NATIVE=Path('/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue-43-profile-driven-v1/freqtrade')

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(name,value):
    with (ROOT/name).open('xb') as f:
        f.write(pilot.canonical(value));f.flush();os.fsync(f.fileno())

def main():
    assert not (ROOT/'research.sqlite').exists() and not (ROOT/'source').exists()
    assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=PROJECT,text=True).strip()==HEAD
    assert not subprocess.check_output(['git','status','--porcelain'],cwd=PROJECT,text=True).strip()
    issue=json.loads((ROOT/'issue-latest.json').read_text());assert issue['number']==93 and issue['state']=='OPEN'
    checks=json.loads((ROOT/'guard-self-test.json').read_text())
    assert checks['network_requests']==0 and checks['original_stub_calls']==24 and checks['attempt_25_rejected_before_original']
    synthetic=json.loads((ROOT/'synthetic-checks.json').read_text());assert synthetic['status']=='PURE_SYNTHETIC_CHECKS_PASSED'
    assert synthetic['native_backtests']==synthetic['market_rows_read']==0
    protocol=sha(ROOT/'protocol.md');src=(ROOT/'LtcVolumeLiquidityReboundV1.py').read_text()
    assert sha(ROOT/'LtcVolumeLiquidityReboundV1.py')==synthetic['strategy_sha256']
    analysis=analyze_bounded_causal_strategy(src,'LtcVolumeLiquidityReboundV1',expected_timeframe='1d')
    assert analysis.max_lookback==37 and analysis.startup_candle_count==40
    runtime=producer.validate_runtime()
    created=datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
    profile_id,generation_id,campaign_id=(str(uuid4()) for _ in range(3))
    db=init_database(ROOT/'research.sqlite')
    values=dict(id=profile_id,name='LTC_VOLUME_LIQUIDITY_REBOUND_V1',domain='OKX_CRYPTO_SPOT',exchange='okx',trading_mode='spot',margin_mode='',pairs_json='["LTC/USDT"]',timeframe='1d',detail_timeframe=None,history_start_date='2021-03-22',smoke_days=7,holdout_days=515,starting_balance=1000.,stake_amount=500.,max_open_trades=1,taker_fee_rate=.001,stress_fee_multiplier=2.,max_drawdown_pct=20.,min_development_trades=12,min_holdout_trades=12,min_profit_factor=1.1,is_default=0,created_at=created,updated_at=created)
    with closing(get_connection(db)) as connection:
        connection.execute('INSERT INTO research_profiles ('+','.join(values)+') VALUES ('+','.join('?' for _ in values)+')',tuple(values.values()))
        connection.commit()
        profile=generation.load_profile_snapshot(connection,profile_id)
    request=generation.validate_generation_request(dict(profile_id=profile_id,strategy_family='ltc_volume_liquidity_rebound_v1',idea='Issue93 supervisor-authorized full-rule conditional reversal hypothesis, protocol SHA256 '+protocol,expected_failure_mode='Informed selling persists; costs exhaust liquidity compensation; clustered or insufficient samples; volume may have no incremental effect. No independent-factor claim or rescue.'))
    prepared=generation.start_generation(db,generation_id,request,model=None,started_at=created)
    raw=pilot.canonical(dict(display_name='LTC volume liquidity rebound V1',class_name='LtcVolumeLiquidityReboundV1',code_text=src))
    candidate_id=generation.complete_generation(db,prepared,generation.parse_candidate_output(raw,timeframe='1d'),raw_output=raw,jsonl_summary={'event_count':0,'tool_event_count':0},finished_at=created)
    generation.review_generation(db,generation_id,'APPROVED',decided_at=created)
    snapshot=logical_snapshot(db,profile_id,candidate_id)
    assert list(snapshot['counts'].values())==[1,1,1,0,0,0]
    assert snapshot['approved_candidate']['code_text']==src
    with closing(get_connection(db,read_only=True)) as connection:
        connection.execute('BEGIN');approved=generation.load_approved_candidate_snapshot(connection,candidate_id)
        plan=_candidate_plan(approved,'strategies/round-1-'+candidate_id+'.py',round_number=1,changed_factor=None,parent_sha256=None)
        connection.rollback()
    single=pilot.validate_single_baseline(dict(mode='SINGLE_BASELINE_V1',version=1,maximum_rounds=1,maximum_attempts=1,protocol_sha256=protocol,strategy_sha256=sha(ROOT/'LtcVolumeLiquidityReboundV1.py')))
    economic=pilot.load_profile_economic_gate(ROOT/'economic-gate.json')
    contract=producer.configure_profile_acquisition(db,profile_id,ROOT/'window-spec.json',40,economic_gate=economic,single_baseline=single)
    write('single-baseline.json',single);write('profile-snapshot.json',profile)
    write('database-logical-snapshot.json',snapshot)
    write('acquisition-contract.json',contract);write('runtime-config.json',pilot.profile_search_config(profile));write('candidate-output.json',json.loads(raw))
    write('search-plan-intent.json',dict(schema='issue93-value-blind-search-intent-v1',campaign_id=campaign_id,candidate=plan,strategy_analysis=asdict(analysis),profile_contract=pilot.profile_search_contract(profile,'20210501-20240101','20240101-20250101',40,economic_gate=economic,single_baseline=single),data_provenance_sha256=None,source_receipt_sha256=None,executable=False,status='SEARCH_NOT_AUTHORIZED'))
    producer_hashes={str(p):sha(p) for p in [PROJECT/'scripts/fetch_okx_profile_data.py',producer.HISTORICAL_PRODUCER]}
    native_hashes={str(p):sha(p) for p in [NATIVE/'freqtrade/optimize/backtesting.py',NATIVE/'freqtrade/strategy/interface.py',NATIVE/'docs/backtesting.md']}
    paths=['protocol.md','LtcVolumeLiquidityReboundV1.py','window-spec.json','economic-gate.json','single-baseline.json','profile-snapshot.json','database-logical-snapshot.json','acquisition-contract.json','runtime-config.json','candidate-output.json','search-plan-intent.json','acquire_with_budget.py','guard-parameters.json','guard-self-test.json','prepare_registration.py','binding.py','accounting_semantics.py','check_synthetic.py','synthetic-checks.json','issue-latest.json']
    assert logical_snapshot(db,profile_id,candidate_id)==snapshot
    write('freeze-receipt.json',dict(schema='issue93-value-blind-freeze-v1',created_at=created,issue=93,status='FROZEN_BEFORE_FIRST_SOURCE_REQUEST',database=str(db),profile_id=profile_id,generation_id=generation_id,candidate_id=candidate_id,planned_campaign_id=campaign_id,research_run_id=None,counts=snapshot['counts'],protocol_sha256=protocol,files_sha256={n:sha(ROOT/n) for n in paths},database_binding={'mode':'APPROVED_PROFILE_CANDIDATE_ONE_READ_TRANSACTION','snapshot_sha256':sha(ROOT/'database-logical-snapshot.json'),'main_file_sha_not_used':True},native_identity=runtime,native_files_sha256=native_hashes,project_commit=HEAD,producer_files_sha256=producer_hashes,generation_origin={'kind':'CURRENT_CODEX_TASK_DIRECT_SOURCE_VIA_EXISTING_API','codex_cli_executed':False,'model':None,'reasoning':None,'tier':None},source={'status':'NOT_REQUESTED','output_root':str(ROOT/'source'),'planned_rows':1381,'planned_http_requests':15,'request_hard_budget':24,'maximum_seconds':1800,'automatic_retries':0,'hard_budget_enforced':True},real_search={'used':0,'maximum_attempts':1,'maximum_rounds':1,'authorized':False},approvals={'source':True,'search':False,'development':False,'holdout':False,'finalist_import':False},development='PRODUCER_QC_ONLY_NO_ECONOMIC_READ',holdout='SEALED_UNREAD_NOT_ACQUIRED',holdout_stress='SEALED_UNREAD',qualification={'all_extra_audits_are_hard_gates':True,'native_finalist_pending_until_extra_audits_pass':True,'specification':'protocol.md','group_counts':{'S':8,'D':6,'H':8},'natural_trades_each_stage':12}))
    print(json.dumps({'profile_id':profile_id,'generation_id':generation_id,'candidate_id':candidate_id,'planned_campaign_id':campaign_id,'freeze_sha256':sha(ROOT/'freeze-receipt.json'),'protocol_sha256':protocol,'strategy_sha256':sha(ROOT/'LtcVolumeLiquidityReboundV1.py'),'counts':snapshot['counts']}))

if __name__=='__main__':main()
