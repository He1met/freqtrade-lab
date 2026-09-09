import json
from runtime_control import ROOT, append, put, sha
from lab.database import get_connection

capture = json.loads((ROOT / 'capture-execution-receipt.json').read_text())
source = json.loads((ROOT / 'source-identity-receipt.json').read_text())
assert json.loads((ROOT / 'source-qc-failure.json').read_text())['return_codes'] == {'prepare_search': 2}
assert not any((ROOT / n).exists() for n in ['search-data-01','development-data-01','console-runtime'])
con = get_connection(ROOT / 'lab.sqlite', read_only=True, must_exist=True)
try:
    counts = {t: con.execute('SELECT COUNT(*) FROM ' + t).fetchone()[0] for t in ['research_profiles','generation_runs','candidates','research_runs','backtest_executions','releases']}
finally:
    con.close()
result = {
    'status': 'BLOCKED_CONTROL_COMMAND_BEFORE_SOURCE_SLICE',
    'failure_class': 'FROZEN_PREPARE_SEARCH_ARGV_OMISSION',
    'error': 'Bounded research Pilot failed: Development must use YYYYMMDD-YYYYMMDD',
    'cause': 'Executor commands.json prepare_search omitted --development-timerange 20220201-20230201. CLI accepts omission syntactically, normal Profile acquisition contract rejects None.',
    'responsibility': 'Executor review-package omission; not a data quality failure or strategy negative result.',
    'where': 'lab/bounded_research.py prepare_search_data -> profile_acquisition_contract before _load_search_source and output publication',
    'source_status': 'Producer completed its original acquisition validation; consumer source QC and S/D slicing did not execute.',
    'source_identity': source, 'capture': capture,
    'profile_id': 'sol-spot-fixed-rule-validation-f590-v2', 'database': str(ROOT / 'lab.sqlite'),
    'database_counts': counts,
    'generation_id': None, 'candidate_id': None, 'search_campaign_id': None,
    'archive': None, 'archive_sha256': None, 'source_S_provenance_sha256': None,
    'strategy_sha256': sha((ROOT / 'BtcWeeklyMomentumFixedStake.py').read_bytes()),
    'protocol_sha256': sha((ROOT / 'protocol.json').read_bytes()),
    'benchmark_convention_sha256': sha((ROOT / 'benchmark-convention.json').read_bytes()),
    'benchmark_artificial_receipt_sha256': sha((ROOT / 'benchmark-artificial-receipt.json').read_bytes()),
    'benchmark_artificial_checks': 'PASS',
    'market_benchmark': 'NOT_RUN', 'fees': None, 'gross': None, 'net': None,
    'summary_DD': None, 'wallet_daily_open_DD': None, 'full_S_gate': 'NOT_EVALUATED',
    'calls': {'prior_metadata_GET': 1, 'capture_invocations': 1, 'capture_HTTP_GET': 9,
              'prepare_S_invocations': 1, 'prepare_D_invocations': 0, 'Generation': 0,
              'S_native': 0, 'benchmark_native': 0, 'benchmark_market_diagnostic': 0,
              'D_native': 0, 'H_capture': 0, 'H_native': 0, 'Stress_native': 0, 'BTC_R2': 0},
    'D_exposure': 'Producer machine acquisition/QC only; no researcher values, signals, economics or native; physical isolation not yet created',
    'H_Stress': 'SEALED_UNREAD_UNACQUIRED', 'search_score_consumed': False,
    'page': None, 'page_reason': 'Dedicated Console not started; old BTC page is not SOL evidence',
    'remaining_slots': {'capture': 0, 'Generation': 1, 'S_native': 1, 'S_benchmark_diagnostic': 1},
    'remaining_slots_authorization_state': 'STOPPED: unspent slots are not automatic continuation authorization after this failure',
    'disposition': 'Preserve raw source, original frozen argv and failure receipts. No retry, recapture, date/rule/gate change or source editing. Report to root.',
}
put('S-preparation-stop-delivery.json', result)
ledger = append({'record_type': 'CONTROL_PREPARATION_TERMINAL', 'status': result['status'],
    'failure_class': result['failure_class'], 'failure_reason': result['cause'],
    'receipt_path': str(ROOT / 'S-preparation-stop-delivery.json'),
    'receipt_sha256': sha((ROOT / 'S-preparation-stop-delivery.json').read_bytes()),
    'source': source, 'calls': result['calls'], 'search_window_consumed': False,
    'economic_results_computed': False, 'D_researcher_values_or_results_read': False,
    'H_Stress_values_acquired': False, 'source_quality_failure_proven': False,
    'original_failure_status_clarification': 'SOURCE_QC_FAILED_STOP was wrapper stage status; actual failure is missing control argv before consumer source QC.'})
put('S-preparation-stop-ledger.json', ledger)
print(json.dumps({'status': result['status'], 'receipt_sha256': sha((ROOT / 'S-preparation-stop-delivery.json').read_bytes()), 'source': source, 'ledger': ledger, 'counts': counts}))
