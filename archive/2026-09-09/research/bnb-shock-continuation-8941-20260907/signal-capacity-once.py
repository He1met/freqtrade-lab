from pathlib import Path
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib.util
import json
import os
import pandas as pd

R = Path(__file__).resolve().parent
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
assert json.loads((R/'source-aggregation-qc.json').read_text())['status'] == 'SOURCE_QC_PASS'
assert sha(R/'BnbDailyShockContinuation48H.py') == 'd250751eb5314acb622266a6033e603da2c137b96592d7a16c7bd7498ddc4ba6'
assert sha(R/'final-protocol.md') == '0bac2485cbe9265e6657891cd3e94f8330945d70964bced95524aed95d454bfb'
g = json.loads((R/'generation-approved.json').read_text())
assert g['candidate']['review_status'] == 'APPROVED'
assert g['candidate']['code_sha256'] == sha(R/'BnbDailyShockContinuation48H.py')
with (R/'capacity-started.json').open('x') as f:
    json.dump({'started_at_utc': datetime.now(timezone.utc).isoformat(), 'S_signal_exposure_started': True, 'maximum_invocations': 1}, f)
spec = importlib.util.spec_from_file_location('frozen_bnb', R/'BnbDailyShockContinuation48H.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
strategy = module.BnbDailyShockContinuation48H({})
path = R/'search-campaign/acquisition/data/binance/futures/BNB_USDT_USDT-1d-futures.feather'
df = pd.read_feather(path)
assert len(df) == 399 and df.date.min() == pd.Timestamp('2023-10-02', tz='UTC')
assert df.date.max() < pd.Timestamp('2024-11-04', tz='UTC')
x = strategy.ft_advise_signals(strategy.populate_indicators(df.copy(), {}), {'pair': 'BNB/USDT:USDT'})
bounds = pd.to_datetime(['2023-11-06','2024-02-05','2024-05-06','2024-08-05','2024-11-04'], utc=True)
entry_time = x.date + pd.Timedelta(days=1)
eligible_signal = x.date >= bounds[0]  # actual native trim-before-shift excludes preheat entries
blocks = []
for a, b in zip(bounds[:-1], bounds[1:]):
    mask = eligible_signal & (entry_time >= a) & (entry_time < b)
    blocks.append({'start': a.isoformat(), 'end_exclusive': b.isoformat(),
                   'E_long': int((x.loc[mask, 'enter_long'] == 1).sum()),
                   'E_short': int((x.loc[mask, 'enter_short'] == 1).sum())})
longs, shorts = sum(v['E_long'] for v in blocks), sum(v['E_short'] for v in blocks)
status = 'CAPACITY_UPPER_BOUND_POSSIBLE' if longs+shorts >= 24 else 'UNDERPOWERED'
out = {'status': status, 'exposure': 'S_SIGNAL_EXPOSED', 'E_total': longs+shorts,
       'E_long': longs, 'E_short': shorts, 'blocks': blocks,
       'assignment': 'ACTUAL_NEXT_OPEN_DATE_IN_S; preheat signals excluded; unusable tail may still be counted optimistically',
       'thresholds': {'natural_total': 24, 'long': 8, 'short': 8, 'each_block_nonzero': True},
       'only_total_prefilter_decides': True, 'all_E_is_optimistic_natural_upper_bound': True,
       'PnL_or_future_returns_computed': False, 'native_backtests': 0,
       'D': 'MECHANICAL_QC_ONLY_NO_SIGNALS', 'H_Stress': 'OHLCV_SEALED_LIMITED_FUNDING_METADATA_QC',
       'source_sha256': sha(path), 'strategy_sha256': sha(R/'BnbDailyShockContinuation48H.py'),
       'protocol_sha256': sha(R/'final-protocol.md'), 'profile_snapshot_sha256': sha(R/'profile-snapshot.json'),
       'generation_id': g['id'], 'candidate_id': g['candidate']['id'], 'profile_id': g['profile_id']}
with (R/'signal-capacity.json').open('x') as f: json.dump(out, f, indent=2)
ledger = Path('/Users/shenjianpeng/Documents/freqtrade-lab-local/search-research-supervision-20260902/global-research-ledger.jsonl')
with Path(str(ledger)+'.lock').open('a+b') as lock:
    fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
    before = ledger.read_bytes()
    record = {'record_type': 'S_SIGNAL_CAPACITY_TERMINAL', 'issue': 104,
        'cohort_id': 'issue104-bnb-daily-shock-continuation-single-v1', 'root': str(R),
        'pair': 'BNB/USDT:USDT', 'search_window': ['2023-11-06','2024-11-04'],
        'recorded_at_utc': datetime.now(timezone.utc).isoformat(), 'status': status,
        'exposure': 'S_SIGNAL_EXPOSED', 'search_consumed': True, 'actual_native_Search_runs': 0,
        'candidate_id': out['candidate_id'], 'generation_id': out['generation_id'],
        'report_sha256': sha(R/'signal-capacity.json'), 'previous_prefix_sha256': hashlib.sha256(before).hexdigest(),
        'next_gate': 'SUPERVISOR_REVIEW_BEFORE_NATIVE_SEARCH' if longs+shorts >= 24 else 'SUPERVISOR_REVIEW_BEFORE_PREFILTER_ATTACHMENT',
        'D': out['D'], 'H_Stress': out['H_Stress']}
    addition = (json.dumps(record, sort_keys=True)+'\n').encode()
    with ledger.open('ab') as f: f.write(addition); f.flush(); os.fsync(f.fileno())
    after = ledger.read_bytes()
    assert after == before+addition
    (R/'ledger-capacity-receipt.json').write_text(json.dumps({'before_sha256': hashlib.sha256(before).hexdigest(),
        'after_sha256': hashlib.sha256(after).hexdigest(), 'before_bytes': len(before), 'after_bytes': len(after),
        'prefix_preserved': True, 'record': record}, indent=2)+'\n')
print(json.dumps(out))
