import fcntl, hashlib, json, os
from pathlib import Path
from datetime import datetime, timezone
r=Path(__file__).parent
ledger=Path('/Users/shenjianpeng/Documents/freqtrade-lab-local/search-research-supervision-20260902/global-research-ledger.jsonl')
def sha(b):return hashlib.sha256(b).hexdigest()
q=json.loads((r/'qc-report.json').read_bytes())
record={'record_type':'SOURCE_QC_TERMINAL','issue':98,'qc_id':'doge-funding-qc-bb9d-20260907',
 'pair':'DOGE/USDT:USDT','instrument_id':'DOGEUSDT','exchange':'binance',
 'source_window':['2023-11-06T00:00:00Z','2024-11-04T00:00:00Z'],
 'exposure':'FUNDING_QC_ONLY','search_consumed':False,'OHLCV':'UNACQUIRED','D':'SEALED_UNREAD_UNACQUIRED',
 'H':'SEALED_UNREAD_UNACQUIRED','future_study_reserved':False,'Search_attempts':0,
 'status':q['status'],'actual_http_get':q['actual_http_get'],'decoded_bytes':q['decoded_bytes'],
 'external_unregistered_exposure':'UNKNOWN','root':str(r),'supervisor':'01a05dcc-17fd-7972-9177-9fed95e4b07a',
 'authorization_sha256':sha((r/'authorization.json').read_bytes()),'qc_report_sha256':sha((r/'qc-report.json').read_bytes()),
 'response_sha256':[x['sha256'] for x in q['receipts']],
 'append_authorization':'Supervisor explicitly authorized existing lock/append-only QC control record in Issue98 implementation turn',
 'recorded_at_utc':datetime.now(timezone.utc).isoformat()}
with ledger.with_suffix(ledger.suffix+'.lock').open('a+b') as lock:
 fcntl.flock(lock.fileno(),fcntl.LOCK_EX)
 before=ledger.read_bytes()
 assert sha(before[:112022])=='84e8c49eab8b40eb39559e0468a914ae80506dbf7b60cb93402e9ecb18891271'
 assert b'DOGE' not in before[112022:] and b'doge-funding-qc-bb9d' not in before
 assert before.endswith(b'\n')
 record['previous_prefix_sha256']=sha(before)
 addition=(json.dumps(record,sort_keys=True)+'\n').encode()
 with ledger.open('ab') as f:f.write(addition);f.flush();os.fsync(f.fileno())
 after=ledger.read_bytes();assert after==before+addition
 receipt={'before_bytes':len(before),'after_bytes':len(after),'before_sha256':sha(before),'after_sha256':sha(after),
  'prefix_preserved':True,'appended_record_sha256':sha(addition)}
 for name,value in [('ledger-record.json',record),('ledger-receipt.json',receipt)]:
  with (r/name).open('x') as f:json.dump(value,f,sort_keys=True,indent=2)
 print(json.dumps(receipt))
