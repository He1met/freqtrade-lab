import fcntl
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

root = Path(__file__).resolve().parent
ledger = Path('/Users/shenjianpeng/Documents/freqtrade-lab-local/search-research-supervision-20260902/global-research-ledger.jsonl')
record = {
    'qc_id': 'NATIVE_FUTURES_RESEARCH_V1_A_01a0777f',
    'thread_id': '01a0777f-815b-7823-9819-6e292f7757f5',
    'issue': 94, 'event': 'DATA_QC_REGISTERED_PRE_GET',
    'time_utc': datetime.now(timezone.utc).isoformat(),
    'exchange': 'binance', 'instrument_id': 'BCHUSDT',
    'pair': 'BCH/USDT:USDT', 'market': 'USDT_PERPETUAL',
    'data_window': ['2023-08-01T00:00:00Z', '2023-09-01T00:00:00Z'],
    'conditional_full_S_history_window': ['2023-07-03T00:00:00Z', '2024-07-15T00:00:00Z'],
    'exposure': 'DATA_QC_ONLY', 'search_consumed': False,
    'strategy_runs': 0, 'raw_sha256': 'UNKNOWN',
    'prior_unregistered_exposure': 'UNKNOWN',
    'cross_exchange_independence': False,
    'excluded_all_assets_window': ['2026-05-31T00:00:00Z', '2026-07-31T00:00:00Z'],
    'objects': ['fapi/v1/fundingRate', 'fapi/v1/markPriceKlines', 'fapi/v1/klines'],
    'root': str(root), 'budget_file': 'work-summary.md',
}
with ledger.with_suffix(ledger.suffix+'.lock').open('a+b') as lock:
    fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
    before = ledger.read_bytes()
    assert b'NATIVE_FUTURES_RESEARCH_V1_A_01a0777f' not in before
    assert before.endswith(b'\n')
    addition = (json.dumps(record, sort_keys=True, ensure_ascii=False)+'\n').encode()
    with ledger.open('ab') as target:
        target.write(addition)
        target.flush()
        import os
        os.fsync(target.fileno())
    after = ledger.read_bytes()
    assert after == before+addition
    receipt = {'before_bytes':len(before),'after_bytes':len(after),'before_sha256':hashlib.sha256(before).hexdigest(),'after_sha256':hashlib.sha256(after).hexdigest(),'original_prefix_preserved':True,'appended_sha256':hashlib.sha256(addition).hexdigest()}
    (root/'ledger-registration-receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps(receipt))
