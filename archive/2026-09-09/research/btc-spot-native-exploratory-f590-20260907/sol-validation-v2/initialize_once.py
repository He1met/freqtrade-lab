import json
from runtime_control import ROOT, append, put, sha, verify_freeze
from lab.database import init_database, get_connection
from lab.bounded_research import load_profile_snapshot

verify_freeze()
assert not (ROOT / 'lab.sqlite').exists()
assert json.loads((ROOT / 'benchmark-artificial-receipt.json').read_text())['status'] == 'PASS'
metadata = json.loads((ROOT / 'metadata-ledger-append-proposal.json').read_text())
for key in ('append_status', 'append_condition', 'previous_prefix_sha256', 'recorded_at_utc'):
    metadata.pop(key, None)
metadata['observed_at_utc'] = '2026-09-07T09:48:36.256945+00:00'
put('metadata-ledger-receipt.json', append(metadata, '3af0b9dd57be3336bef6973d26ea24157ca248a9d4f92412f9f976dc6d7c0147'))
put('authorization-ledger-receipt.json', append({
    'record_type': 'COHORT_PREREGISTERED', 'status': 'AUTHORIZED_S_ONLY_NORMAL_SINGLE_BASELINE',
    'authorization_source_thread': '01a05dcc-17fd-7972-9177-9fed95e4b07a',
    'protocol_sha256': sha((ROOT / 'protocol.json').read_bytes()),
    'benchmark_convention_sha256': sha((ROOT / 'benchmark-convention.json').read_bytes()),
    'benchmark_artificial_receipt_sha256': sha((ROOT / 'benchmark-artificial-receipt.json').read_bytes()),
    'pair': 'SOL/USDT', 'search_window': ['2021-03-01', '2022-02-01'],
    'development_window': ['2022-02-01', '2023-02-01'], 'holdout_stress_window': ['2023-02-01', '2024-02-01'],
    'source_window': ['2021-01-31', '2023-02-01'],
    'external_exposure': 'UNKNOWN_ACCEPTED; conditional asset validation, not independent macro sample',
    'maximum_capture_invocations': 1, 'maximum_http_get': 9, 'retry': 0,
    'maximum_S_native': 1, 'maximum_normal_Generation': 1,
    'maximum_S_benchmark_diagnostic': 1, 'benchmark_native': 0,
    'D_signal_or_economics_or_native': False, 'D_machine_QC_only': True,
    'H_Stress_acquisition_or_read_or_native': False, 'BTC_R2': False,
}))
init_database(ROOT / 'lab.sqlite')
profile = json.loads((ROOT / 'profile.json').read_text())
columns = dict(profile)
columns['pairs_json'] = json.dumps(columns.pop('pairs'))
connection = get_connection(ROOT / 'lab.sqlite', must_exist=True)
try:
    with connection:
        connection.execute('INSERT INTO research_profiles (' + ','.join(columns) + ') VALUES (' + ','.join('?' for _ in columns) + ')', tuple(columns.values()))
    assert load_profile_snapshot(connection, profile['id']) == profile
    counts = {t: connection.execute('SELECT COUNT(*) FROM ' + t).fetchone()[0] for t in ['research_profiles','generation_runs','candidates','research_runs','backtest_executions','releases']}
    assert connection.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchone()[0] == 6
finally:
    connection.close()
put('database-initialization-receipt.json', {'profile_id': profile['id'], 'profile_exact': True, 'counts': counts})
print(json.dumps({'status': 'INITIALIZED', 'counts': counts}))
