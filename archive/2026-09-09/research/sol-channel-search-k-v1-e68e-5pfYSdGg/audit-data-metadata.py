"""Metadata/hash only audit; never opens archive bytes or market value columns."""
from pathlib import Path
import json,hashlib
R=Path(__file__).resolve().parent;sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
source=R/'source-acquisition';receipt=json.loads((source/'retrieval_receipt.json').read_text())
sp=json.loads((R/'search/acquisition/retained-data-provenance.json').read_text())
dp=json.loads((R/'development/acquisition/retained-data-provenance.json').read_text())
assert sp['source_acquisition']==dp['source_acquisition']
for rel,record in receipt['landed_files'].items():
    assert sha(source/rel)==record['sha256']
    assert (source/rel).stat().st_size==record['bytes']
archives=[v for v in receipt['requests'] if v.get('method')=='GET' and v['label'].startswith('funding-archive-')]
assert len(archives)==25
assert sum(x['rate_selection']['selected_rows'] for x in archives)==2190
assert archives[0]['label']=='funding-archive-2024-03' and archives[-1]['label']=='funding-archive-2026-03'
assert archives[-1]['rate_selection']['selected_rows']==1
assert archives[-1]['rate_selection']['uninterpreted_rate_rows']==92
assert all(a['rate_selection']['uninterpreted_rate_validation']=='NOT_PERFORMED' for a in archives)
assert all(a['timestamp_normalization']['maximum_allowed_drift_ms']==2000 for a in archives)
assert max(a['timestamp_normalization']['maximum_observed_drift_ms'] for a in archives)<=2000
document={'source_receipt_sha256':sha(source/'retrieval_receipt.json'),'source_provenance_sha256':sha(source/'retained-data-provenance.json'),'actual_series':receipt['series'],'request_count':len(receipt['requests']),'archive_GET_count':25,'catalog_attempts':[x for x in receipt['requests'] if 'catalog' in x['label']],'archive_metadata':archives,'search_consumer_provenance_sha256':sha(R/'search/acquisition/retained-data-provenance.json'),'development_consumer_provenance_sha256':sha(R/'development/acquisition/retained-data-provenance.json'),'same_source_acquisition':sp['source_acquisition'],'same_source_binding_verified':True,'four_layers':{'physical':'S+D source acquired; necessary March2026 boundary opaque ZIP/CSV bytes acquired and hashed in memory','raw_retained':False,'deterministic_QC':'Official producer validates S+D; both official consumers validated and materialized their exact isolated windows','agent_semantic':'No D price/funding values, indicators, chart, statistics or results read; analysis uses isolated Search only','evaluation':'Search only; no D/H/Stress executed','protected_H_rates':'92 boundary-package rates not accessed/interpreted/validated by official timestamp-first selector','protected_H_rate_finiteness':'UNKNOWN','actual_raw_timestamp_envelope':'UNKNOWN: current safe receipt exposes selection counts and selected drift, not full raw envelope; no raw re-download or custom scan','H_OHLC_mark_acquired':False},'unknown_external_exposure':'UNKNOWN','runtime':receipt['runtime']}
target=R/'data-metadata-audit.json';assert not target.exists();target.write_text(json.dumps(document,indent=2)+'\n')
print(json.dumps({'archive_GET_count':25,'source_series':receipt['series'],'source_binding':'PASS','protected_rates_uninterpreted':92,'raw_retained':False,'raw_timestamp_envelope':'UNKNOWN'},indent=2))
