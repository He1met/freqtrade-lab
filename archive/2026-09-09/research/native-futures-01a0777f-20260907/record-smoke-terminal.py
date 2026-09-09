import fcntl
import hashlib
import json
import os
from datetime import datetime,timezone
from pathlib import Path

root=Path(__file__).resolve().parent
smoke=root/'technical-smoke-v1'
ledger=Path('/Users/shenjianpeng/Documents/freqtrade-lab-local/search-research-supervision-20260902/global-research-ledger.jsonl')
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
record={'event':'TECHNICAL_SMOKE_TERMINAL','qc_id':'NATIVE_FUTURES_RESEARCH_V1_SMOKE_TERMINAL_01a0777f',
    'registered_qc_id':'NATIVE_FUTURES_RESEARCH_V1_SMOKE_01a0777f',
    'thread_id':'01a0777f-815b-7823-9819-6e292f7757f5','issue':94,'time_utc':datetime.now(timezone.utc).isoformat(),
    'exchange':'binance','instrument_id':'BCHUSDT','pair_family':'BCH-USDT',
    'window':['2023-11-06T00:00:00Z','2023-11-13T00:00:00Z'],
    'exposure':'TECHNICAL_ECONOMIC_EXPOSURE','search_consumed':False,'strategy_selection':False,
    'actual_native_invocations':1,'technical_trade_count':2,'native_artifact_parser':'PASSED',
    'funding_audit':'RECONCILED','economic_verdict':'NOT_EVALUATED',
    'prelaunch_failure':'duplicate timeout keyword before subprocess; fixed without changing frozen inputs',
    'artifact_sha256':sha(smoke/'bundle/backtest-result-engineering-only.zip'),
    'artifact_provenance_sha256':sha(smoke/'bundle/backtest-result-engineering-only.provenance.json'),
    'acceptance_sha256':sha(smoke/'acceptance.json'), 'root':str(smoke),
    'later_research_must_account_for_this_exposure':True}
with ledger.with_suffix(ledger.suffix+'.lock').open('a+b') as lock:
    fcntl.flock(lock.fileno(),fcntl.LOCK_EX)
    before=ledger.read_bytes()
    assert record['qc_id'].encode() not in before and before.endswith(b'\n')
    addition=(json.dumps(record,sort_keys=True)+'\n').encode()
    with ledger.open('ab') as handle:
        handle.write(addition);handle.flush();os.fsync(handle.fileno())
    after=ledger.read_bytes();assert after==before+addition
    receipt={'before_bytes':len(before),'after_bytes':len(after),
        'before_sha256':hashlib.sha256(before).hexdigest(),'after_sha256':hashlib.sha256(after).hexdigest(),
        'original_prefix_preserved':True,'record_sha256':hashlib.sha256(addition).hexdigest()}
    with (root/'smoke-terminal-receipt.json').open('x') as handle:json.dump(receipt,handle)
    print(json.dumps(receipt))
