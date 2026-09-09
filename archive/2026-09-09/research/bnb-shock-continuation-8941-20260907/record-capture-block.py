from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import urlsplit
import fcntl
import hashlib
import json
import os
import sqlite3

R = Path(__file__).resolve().parent
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
receipts = R/'native-capture/http-receipts.jsonl'
rows = [json.loads(line) for line in receipts.read_text().splitlines()]
for row in rows:
    raw = R/'native-capture/raw'/row['body_file']
    assert sha(raw) == row['sha256'] and raw.stat().st_size == row['bytes']
assert len(rows) == 1 and urlsplit(rows[0]['url']).path == '/fapi/v1/exchangeInfo'
response = json.loads((R/'native-capture/raw'/rows[0]['body_file']).read_bytes())
assert response['code'] == -1003
assert not (R/'complete-source').exists() and not (R/'signal-capacity.json').exists()
data_files = [str(p.relative_to(R)) for p in (R/'native-capture').rglob('*.feather')]
assert not data_files
conn = sqlite3.connect((R/'lab.sqlite').as_uri()+'?mode=ro', uri=True)
tables = [x[0] for x in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
counts = {name: conn.execute('SELECT count(*) FROM "'+name+'"').fetchone()[0] for name in tables}
conn.close()
g = json.loads((R/'generation-approved.json').read_text())
report = {'status': 'BLOCKED_DATA', 'economic_result': 'UNKNOWN', 'failure': 'HTTP_418_BINANCE_MINUS_1003_TEMPORARY_IP_BAN',
    'ban_until_utc': '2026-09-07T06:29:58.566000+00:00', 'retry_after_seconds_at_failure': 374,
    'capture_invocations': 1, 'capture_budget_consumed': True, 'retry_authorized': False,
    'CCXT_fetch_calls': len(rows), 'wire_attempts': 'UNKNOWN', 'decoded_bytes': sum(x['bytes'] for x in rows),
    'url_categories': ['/fapi/v1/exchangeInfo'], 'OHLCV_requests': 0, 'funding_requests': 0, 'mark_requests': 0,
    'new_market_series_acquired': False, 'source_published': False, 'data_files': data_files,
    'source_publication_bytes': (R/'source-publication.json').stat().st_size,
    'native_Search_runs': 0, 'capacity_runs': 0, 'D_strategy_runs': 0, 'H_strategy_opened': False,
    'D_H_exposure': 'PRIOR_LIMITED_FUNDING_METADATA_QC_ONLY_NO_NEW_CAPTURE',
    'generation_id': g['id'], 'candidate_id': g['candidate']['id'], 'profile_id': g['profile_id'],
    'source_sha256': g['candidate']['code_sha256'], 'six_table_counts': counts,
    'raw_response_sha256': rows[0]['sha256'], 'http_receipts_sha256': sha(receipts),
    'capture_log_sha256': sha(R/'source-capture.log'), 'protocol_sha256': sha(R/'final-protocol.md'),
    'recorded_at_utc': datetime.now(timezone.utc).isoformat(),
    'process_observation': 'No obvious active fetch_binance/fetch_okx/download-data/probe process in local ps metadata; Console services on 8798/8799/8801 remain. This cannot attribute the shared-IP ban or exclude other hosts/users.',
    'next_gate': 'SUPERVISOR_MAY_REASSESS_NEW_EXPLICIT_CAPTURE_BUDGET_AFTER_BAN; NO_AUTOMATIC_RETRY'}
with (R/'capture-blocked-receipt.json').open('x') as f: json.dump(report, f, indent=2)
ledger = Path('/Users/shenjianpeng/Documents/freqtrade-lab-local/search-research-supervision-20260902/global-research-ledger.jsonl')
with Path(str(ledger)+'.lock').open('a+b') as lock:
    fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
    before = ledger.read_bytes()
    event = {'record_type': 'SOURCE_CAPTURE_BLOCKED', 'issue': 104,
        'cohort_id': 'issue104-bnb-daily-shock-continuation-single-v1', 'pair': 'BNB/USDT:USDT',
        'status': 'BLOCKED_DATA', 'economic_result': 'UNKNOWN', 'reason': report['failure'],
        'actual_capture_invocations': 1, 'CCXT_fetch_calls': 1, 'decoded_bytes': 148,
        'OHLCV_acquired': False, 'source_published': False, 'S_signal_exposed': False,
        'D_H_exposure': report['D_H_exposure'], 'generation_id': g['id'], 'candidate_id': g['candidate']['id'],
        'ban_until_utc': report['ban_until_utc'], 'retry_authorized': False,
        'receipt_path': str(R/'capture-blocked-receipt.json'), 'receipt_sha256': sha(R/'capture-blocked-receipt.json'),
        'previous_prefix_sha256': hashlib.sha256(before).hexdigest(), 'recorded_at_utc': report['recorded_at_utc']}
    addition = (json.dumps(event, sort_keys=True)+'\n').encode()
    with ledger.open('ab') as f: f.write(addition); f.flush(); os.fsync(f.fileno())
    after = ledger.read_bytes(); assert after == before+addition
    (R/'capture-blocked-ledger.json').write_text(json.dumps({'before_bytes': len(before), 'after_bytes': len(after),
        'before_sha256': hashlib.sha256(before).hexdigest(), 'after_sha256': hashlib.sha256(after).hexdigest(),
        'prefix_preserved': True, 'receipt_sha256': sha(R/'capture-blocked-receipt.json')}, indent=2)+'\n')
print(json.dumps(report, indent=2))
