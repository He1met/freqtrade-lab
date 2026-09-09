"""One-off value-blind Issue90 registration through existing project APIs.

No acquisition, native invocation or Search execution is called here.
"""
import hashlib
import json
import subprocess
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from lab import bounded_research as pilot, codex_generation as generation
from lab.bounded_strategy import analyze_bounded_causal_strategy
from lab.database import init_database, get_connection
from lab.search_campaign import _candidate_plan
from scripts import fetch_okx_profile_data as producer

ROOT = Path(__file__).resolve().parent
PROJECT = Path('/Users/shenjianpeng/.codex/worktrees/7183/freqtrade-lab')
PROTOCOL = 'ba627b813510ed26cb5ace447d4673d27fd4a694d20e5211a9e323733c1cad4d'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(name, value):
    with (ROOT / name).open('xb') as output:
        output.write(pilot.canonical(value))


def main():
    assert sha(ROOT / 'protocol.md') == PROTOCOL
    resume = sys.argv[1:] == ['--finish-controls']
    assert resume or not (ROOT / 'research.sqlite').exists()
    assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=PROJECT, text=True).strip() == '9a5c00ba2ad1617645b67c1d0475508ba02c401a'
    runtime = producer.validate_runtime()  # local pinned identity only
    source = (ROOT / 'XlmSpotSma90.py').read_text()
    analysis = analyze_bounded_causal_strategy(source, 'XlmSpotSma90', expected_timeframe='1d')
    now = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    profile_id, generation_id, campaign_id = (str(uuid4()) for _ in range(3))
    raw = pilot.canonical(dict(display_name='XLM spot SMA90 trend V1', class_name='XlmSpotSma90', code_text=source))
    if resume:
        database = ROOT / 'research.sqlite'
        with get_connection(database, read_only=True) as connection:
            connection.execute('BEGIN')
            row = connection.execute('SELECT id,generation_run_id FROM candidates').fetchone()
            candidate_id, generation_id = row['id'], row['generation_run_id']
            profile_id = connection.execute('SELECT research_profile_id FROM generation_runs WHERE id=?', (generation_id,)).fetchone()[0]
            profile = generation.load_profile_snapshot(connection, profile_id)
        assert not (ROOT / 'freeze-receipt.json').exists()
    else:
        database = init_database(ROOT / 'research.sqlite')
        profile_values = dict(
            id=profile_id, name='XLM_SPOT_SMA90_TREND_V1', domain='OKX_CRYPTO_SPOT',
            exchange='okx', trading_mode='spot', margin_mode='', pairs_json='["XLM/USDT"]',
            timeframe='1d', detail_timeframe=None, history_start_date='2021-01-31',
            smoke_days=7, holdout_days=699, starting_balance=1000., stake_amount=500.,
            max_open_trades=1, taker_fee_rate=.001, stress_fee_multiplier=2.,
            max_drawdown_pct=20., min_development_trades=6, min_holdout_trades=6,
            min_profit_factor=1., is_default=0, created_at=now, updated_at=now,
        )
        # The project has no Profile write route. Use its connection factory and
        # unchanged schema-v1 insert, then validate via load_profile_snapshot.
        with get_connection(database) as connection:
            connection.execute('INSERT INTO research_profiles (' + ','.join(profile_values) + ') VALUES (' + ','.join('?' for _ in profile_values) + ')', tuple(profile_values.values()))
            profile = generation.load_profile_snapshot(connection, profile_id)
            connection.commit()
        request = generation.validate_generation_request(dict(
            profile_id=profile_id, strategy_family='xlm_spot_sma90_trend_v1',
            idea='Issue90 sole value-blind SMA90 long-only baseline; protocol SHA256 ' + PROTOCOL,
            expected_failure_mode='Sideways whipsaws, long downtrends, costly reentry and insufficient independent complete 90-day exposure groups.',
        ))
        prepared = generation.start_generation(database, generation_id, request, model=None, started_at=now)
        raw = pilot.canonical(dict(display_name='XLM spot SMA90 trend V1', class_name='XlmSpotSma90', code_text=source))
        # Source is authored by this Codex task. No Codex CLI JSONL subprocess was
        # used; zero counts describe the absent CLI stream, not this whole task.
        candidate_id = generation.complete_generation(database, prepared,
            generation.parse_candidate_output(raw, timeframe='1d'), raw_output=raw,
            jsonl_summary={'event_count': 0, 'tool_event_count': 0}, finished_at=now)
        generation.review_generation(database, generation_id, 'APPROVED', decided_at=now)
    with get_connection(database, read_only=True) as connection:
        connection.execute('BEGIN')
        approved = generation.load_approved_candidate_snapshot(connection, candidate_id)
        counts = {table: connection.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0]
                  for table in ('research_profiles','generation_runs','candidates','research_runs','backtest_executions','releases')}
    assert counts == dict(research_profiles=1, generation_runs=1, candidates=1, research_runs=0, backtest_executions=0, releases=0)
    single = pilot.validate_single_baseline(dict(mode='SINGLE_BASELINE_V1', version=1,
        maximum_rounds=1, maximum_attempts=1, protocol_sha256=PROTOCOL, strategy_sha256=sha(ROOT / 'XlmSpotSma90.py')))
    contract = producer.configure_profile_acquisition(database, profile_id, ROOT / 'window-spec.json', 90, single_baseline=single)
    candidate_plan = _candidate_plan(approved, 'strategies/round-1-' + candidate_id + '.py', round_number=1, changed_factor=None, parent_sha256=None)
    write('single-baseline.json', single)
    write('profile-snapshot.json', profile)
    write('acquisition-contract.json', contract)
    write('runtime-config.json', pilot.profile_search_config(profile))
    write('candidate-output.json', json.loads(raw))
    write('search-plan-intent.json', dict(
        schema='issue90-value-blind-search-intent-v1', campaign_id=campaign_id,
        candidate=candidate_plan, strategy_analysis=asdict(analysis),
        profile_contract=pilot.profile_search_contract(profile, '20210501-20230101', '20230101-20240701', 90, single_baseline=single),
        data_provenance_sha256=None, source_receipt_sha256=None,
        executable=False, status='AWAITING_SOURCE_AUTHORIZATION',
        note='Actual executable Search plan is materialized by existing prepare-search-data and Console only after acquired source hashes exist; no fabricated hash placeholders.',
    ))
    paths = ['protocol.md','XlmSpotSma90.py','window-spec.json','single-baseline.json',
             'profile-snapshot.json','acquisition-contract.json','runtime-config.json','candidate-output.json','search-plan-intent.json']
    write('freeze-receipt.json', dict(
        schema='issue90-value-blind-freeze-v1', created_at=now, issue=90,
        status='FROZEN_VALUE_BLIND_AWAITING_AUTHORIZATION', database=str(database),
        profile_id=profile_id, generation_id=generation_id, candidate_id=candidate_id,
        planned_campaign_id=campaign_id, research_run_id=None, counts=counts,
        protocol_sha256=PROTOCOL, files_sha256={name:sha(ROOT/name) for name in paths},
        database_initial_sha256=sha(database), native_identity=runtime,
        engineering_commit='9a5c00ba2ad1617645b67c1d0475508ba02c401a', engineering_issue=88,
        generation_origin={'kind':'CURRENT_CODEX_TASK_DIRECT_SOURCE_VIA_EXISTING_API',
                           'codex_cli_executed':False,'model':None,'reasoning':None,'tier':None},
        source={'status':'NOT_REQUESTED','output_root':str(ROOT/'source'), 'planned_rows':1247,
                'planned_http_requests':14,'instrument_requests':1,'candle_pages':13,
                'request_hard_budget':64,'maximum_seconds':3600,'automatic_retries':0,
                'hard_budget_enforced':False,'execution_blocker':'Existing endpoint guard lacks attempt count and wall-clock deadline; separate execution envelope awaits supervision approval before any network.',
                'retry_basis':'Pinned CCXT fetch2 default maxRetriesOnFailure=0, no producer spot retry loop; request redirects forbidden; no implicit load_markets after set_markets.'},
        real_search={'used':0,'maximum_attempts':1,'maximum_rounds':1,'maximum_seconds':1800},
        holdout='SEALED_UNREAD',holdout_stress='SEALED_UNREAD',development='SEALED_UNREAD',
        approvals={'source':False,'search':False,'development':False,'holdout':False,'release':False},
        capacity={'S':{'days':610,'complete_90d_upper_bound':6,'required_groups':4},
                  'D':{'days':547,'complete_90d_upper_bound':6,'required_groups':4},
                  'H':{'days':699,'complete_90d_upper_bound':7,'required_groups':6},
                  'D_plus_H':{'days':1246,'complete_90d_upper_bound':13,'required_groups':12,'slack_days_at_12':166},
                  'meaning':'Calendar upper bound only. Actual groups UNKNOWN; empty intervals and extended positions reduce capacity. Insufficient groups => UNDERPOWERED.'},
        qualification={'source':'protocol.md exact four-gate definitions',
            'native_gate':'mechanical only; natural closes, slippage, cash, daily MTM DD, exposure groups and concentration require separate supervised S audit before D',
            'all_assets_excluded_utc':['2026-05-31','2026-07-31'],
            'exposure_evidence':'protocol v2 identity-only audit snapshot; finite coverage and prior unknowns retained, no old market-value files read'},
        spot_selection='Single mechanism test with current accounting capability; no claimed return advantage over derivatives',
    ))
    print(json.dumps(dict(profile_id=profile_id,generation_id=generation_id,candidate_id=candidate_id,
        planned_campaign_id=campaign_id,receipt_sha256=sha(ROOT/'freeze-receipt.json'),counts=counts)))


if __name__ == '__main__':
    main()
