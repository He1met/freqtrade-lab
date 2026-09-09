import hashlib,json,os,subprocess,sys
from pathlib import Path
from lab import bounded_research as b
from lab.database import get_connection

os.umask(0o077)
r=Path(__file__).resolve().parent
source=r/'source-acquisition'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
pre=json.loads((r/'funding-precheck-terminal.json').read_text())
actual=json.loads((source/'retrieval_receipt.json').read_text())
prior={x['producer_parser']['archive_filename']:x for x in pre['requests'] if 'producer_parser' in x}
formal={x['archive_filename']:x for x in actual['requests'] if 'archive_filename' in x}
assert len(prior)==len(formal)==25 and set(prior)==set(formal),'archive set changed'
matched=[]
for name,x in prior.items():
    y=formal[name]
    assert sha(r/'raw'/name)==x['archive_sha256']==y['archive_sha256'],'formal ZIP changed'
    assert x['csv_sha256']==y['csv_sha256'],'formal CSV changed'
    assert y['timestamp_normalization']['maximum_observed_drift_ms']==0,'formal raw offset nonzero'
    matched.append({'archive':name,'archive_sha256':y['archive_sha256'],'csv_sha256':y['csv_sha256']})
gate=json.loads((r/'economic-gate.json').read_text())
common={'database_path':r/'lab.sqlite','profile_id':'bch-exact-grid-dual-sma-10-30-v1','search_timerange':'20240201-20250201','development_timerange':'20250201-20260201','pre_roll_candles':120,'economic_gate':gate}
provenance=sha(source/'retained-data-provenance.json');receipt=sha(source/'retrieval_receipt.json')
search=b.prepare_search_data(source,r/'search-data',provenance,receipt,**common)
development=b.prepare_development_data(source,r/'development-pilot',provenance,receipt,**common)
result={'status':'SOURCE_AND_SLICES_PREPARED','formal_matches_precheck':matched,'source_provenance_sha256':provenance,'source_receipt_sha256':receipt,'search':search,'development':development,'holdout_status':'SEALED_UNREAD'}
(r/'source-verification.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result))
