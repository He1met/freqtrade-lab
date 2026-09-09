from pathlib import Path
import json,hashlib
from urllib.parse import urlparse
import pandas as pd
r=Path(__file__).parent
sha=lambda b:hashlib.sha256(b).hexdigest()
records=[json.loads(x) for x in (r/'native-capture-v2/http-receipts.jsonl').read_text().splitlines()]
for rec in records:
 b=(r/'native-capture-v2/raw'/rec['body_file']).read_bytes()
 assert sha(b)==rec['sha256'] and len(b)==rec['bytes'] and rec['error_class'] is None
 assert urlparse(rec['url']).hostname=='fapi.binance.com'
assert len(records)<=2000
rows=[]
for stage,relative,start,end,fstart,expected in [
 ('S+D','complete-source-v2','2023-10-02','2025-11-03','2023-11-06',(763,18312,2184)),
 ('S','search-campaign/acquisition','2023-10-02','2024-11-04','2023-11-06',(399,9576,1092)),
 ('D_QC_ONLY','development-pilot/development-isolation','2024-09-30','2025-11-03','2024-11-04',(399,9576,1092))]:
 root=r/relative
 p=json.loads((root/'retained-data-provenance.json').read_bytes())
 assert p['source']['pair']=='BNB/USDT:USDT' and p['source']['instrument_id']=='BNBUSDT'
 for group in ('files','local_only_files'):
  for name,meta in p.get(group,{}).items():
   path=root/name
   if path.is_file():assert sha(path.read_bytes())==meta['sha256']
 counts=[]
 for suffix,freq,n in [('1d-futures','1D',expected[0]),('1h-mark','1h',expected[1])]:
  path=root/'data/binance/futures'/('BNB_USDT_USDT-'+suffix+'.feather')
  dates=pd.read_feather(path,columns=['date'])['date']
  target=pd.date_range(start,end,freq=freq,tz='UTC',inclusive='left')
  assert len(dates)==n and list(dates)==list(target)
  counts.append(n)
 events=p['source']['funding_events']
 target=pd.date_range(fstart,end,freq='8h',tz='UTC',inclusive='left')
 assert len(events)==expected[2]
 # Frozen BINANCE_ASSOCIATED_MARK_BOUNDARY_V1 maps actual timestamps to native minutes.
 # The first draft mistakenly required exact millisecond equality; no source was changed.
 assert [e['fundingTime']//60000*60000 for e in events]==[int(t.timestamp()*1000) for t in target]
 counts.append(len(events))
 rows.append(dict(stage=stage,counts=counts,continuous=True,provenance_sha256=sha((root/'retained-data-provenance.json').read_bytes())))
out=dict(status='SOURCE_QC_PASS',CCXT_fetch=len(records),wire_HTTP_attempts='UNKNOWN',decoded_bytes=sum(x['bytes'] for x in records),capture_runs=2,successful_capture_runs=1,first_capture='BLOCKED_DATA_NO_MARKET_SERIES',authorized_recovery_captures=1,automatic_source_retries=0,source_root='complete-source-v2',phase_qc=rows,D_strategy_execution=0,H_Stress='OHLCV_SEALED_LIMITED_FUNDING_METADATA_QC',native_download_incomplete_tail='Compiled retained responses with drop_incomplete=False; exact complete rows verified')
(r/'source-aggregation-qc.json').write_text(json.dumps(out,indent=2)+'\n')
print(json.dumps(out))
