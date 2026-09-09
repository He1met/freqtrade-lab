from pathlib import Path
from datetime import datetime,timezone
import fcntl,hashlib,json,os
r=Path(__file__).parent
ledger=Path('/Users/shenjianpeng/Documents/freqtrade-lab-local/search-research-supervision-20260902/global-research-ledger.jsonl')
sha=lambda b:hashlib.sha256(b).hexdigest()
S=Path('/Users/shenjianpeng/.codex/runs/freqtrade-lab/native-futures-01a0777f-20260907')
sr=S/'native-full-s-http-receipts.jsonl';records=[json.loads(l) for l in sr.read_text().splitlines()]
for rec in records:
 b=(S/'native-full-s-raw'/rec['body_file']).read_bytes();assert len(b)==rec['bytes'] and sha(b)==rec['sha256'] and rec['error_class'] is None
record={'record_type':'COHORT_PREREGISTERED','cohort_id':'issue96-binance-bch-trend28-single-v1','issue':96,'recorded_at_utc':datetime.now(timezone.utc).isoformat(),'root':str(r),'pair':'BCH/USDT:USDT','instrument_id':'BCHUSDT','pair_family':'BCH-USDT','exchange':'binance','same_asset_cross_exchange_independent':False,'search_window':['2023-11-13T00:00:00Z','2024-07-15T00:00:00Z'],'development_window':['2024-07-15T00:00:00Z','2025-07-14T00:00:00Z'],'holdout_stress_window':['2025-07-14T00:00:00Z','2026-05-25T00:00:00Z'],'excluded_technical_exposure':['2023-11-06','2023-11-13'],'pre_roll_candles':29,'mode':'SINGLE_BASELINE_V1','maximum_rounds':1,'maximum_attempts':1,'candidate_id':'89c0c792-93a3-4e3b-b8ac-67a56eca4dea','generation_id':'bdd08312-e427-4ce8-9145-5612a862704b','profile_id':'issue96-bch-trend28-v1','database':str(r/'lab.sqlite'),'status':'FROZEN_BEFORE_SOURCE_VALUES','actual_Search_attempts':0,'D_strategy_runs':0,'H_Stress':'SEALED_UNREAD_UNACQUIRED','D_source':'AUTHORIZED_MECHANICAL_QC_ONLY','source_provenance_sha256':None,'source_receipt_sha256':None,'retained_S_http_receipts_sha256':sha(sr.read_bytes()),'retained_S_responses_verified':len(records),'external_unregistered_exposure':'UNKNOWN'}
for name,field in [('frozen-protocol.md','protocol_sha256'),('supervisor-authorization.json','authorization_sha256'),('profile-snapshot.json','profile_snapshot_sha256'),('BchPriorCloseTrend28.py','strategy_sha256'),('single-baseline.json','single_baseline_sha256'),('economic-gate.json','economic_gate_sha256'),('window.json','window_sha256')]:record[field]=sha((r/name).read_bytes())
with ledger.with_suffix(ledger.suffix+'.lock').open('a+b') as lock:
 fcntl.flock(lock.fileno(),fcntl.LOCK_EX)
 before=ledger.read_bytes();assert len(before)==105613 and sha(before)=='4a3a95c716b90b3bf065fc52ad6d7a11a8fca2027087c2ff6bf35b589ece0459';assert record['cohort_id'].encode() not in before
 record['previous_prefix_sha256']=sha(before);addition=(json.dumps(record,sort_keys=True)+'\n').encode()
 with ledger.open('ab') as f:f.write(addition);f.flush();os.fsync(f.fileno())
 after=ledger.read_bytes();assert after==before+addition
 receipt={'before_sha256':sha(before),'after_sha256':sha(after),'before_bytes':len(before),'after_bytes':len(after),'prefix_preserved':True,'record_sha256':sha(addition)}
 (r/'ledger-preregistration.json').write_text(json.dumps(record,indent=2)+'\n');(r/'ledger-preregistration-receipt.json').write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt))
