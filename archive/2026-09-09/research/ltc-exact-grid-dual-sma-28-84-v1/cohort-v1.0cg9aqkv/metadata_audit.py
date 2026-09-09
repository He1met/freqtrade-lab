import hashlib, json, subprocess
from pathlib import Path
from datetime import datetime, timedelta, timezone

ROOT = Path(__file__).resolve().parent
BASE = ROOT.parents[1]
INDEX = BASE / 'xrp-28-84-dual-sma-trend-v1/cohort-v1.pos_2t8c/consumption-metadata.json'
def digest(p): return hashlib.sha256(p.read_bytes()).hexdigest()
index = json.loads(INDEX.read_text())
checks=[]
for record in index['records']:
    for item in [record, *record.get('identity_sources', [])]:
        p=Path(item['path'])
        assert p.is_relative_to(BASE) and p.is_file(), str(p)
        actual=digest(p)
        assert actual==item['sha256'], str(p)
        checks.append({'path':str(p),'sha256':actual})
# Metadata only: never load price, result, ZIP, database or sealed metrics.
names={'window-spec.json','search-window-spec.json','research-contract.json','profile-acquisition-contract.json','retained-data-provenance.json','cohort-claimed.json','search-contract.json','search-terminal.json','acquisition-terminal.json'}
allowed={'pair','pairs','symbol','instrument_id','instId','timeframe','status','phase','schema','holdout','holdout_status','data_start_utc','search_start_utc','development_start_utc','holdout_start_utc','holdout_end_exclusive_utc','end_exclusive_utc','timerange','search_timerange','development_timerange'}
def select(v, prefix=''):
    out={}
    if isinstance(v,dict):
        for k,x in v.items():
            key=prefix+'.'+k if prefix else k
            if k in allowed and not isinstance(x,dict):out[key]=x
            elif isinstance(x,(dict,list)):out.update(select(x,key))
    elif isinstance(v,list):
        for i,x in enumerate(v):
            if isinstance(x,(dict,list)):out.update(select(x,prefix+f'[{i}]'))
    return out
records=[]
for p in sorted(BASE.rglob('*.json')):
    if p.name not in names or p.is_relative_to(ROOT):continue
    data=json.loads(p.read_text())
    fields=select(data)
    records.append({'path':str(p),'sha256':digest(p),'metadata':fields})
conflicts=[r for r in records if 'LTC' in json.dumps(r['metadata'])]
utc=timezone.utc
start=datetime(2024,2,1,tzinfo=utc);dev=datetime(2025,2,1,tzinfo=utc);end=datetime(2026,2,1,tzinfo=utc)
assert start-timedelta(days=120)==datetime(2023,10,4,tzinfo=utc)
assert end+timedelta(days=180)==datetime(2026,7,31,tzinfo=utc)
assert (dev-start).days==366 and (end-dev).days==365
assert int((end-start).total_seconds()//28800)==2193
report={'scope':str(BASE),'index':{'path':str(INDEX),'sha256':digest(INDEX)},'index_file_hash_checks':checks,'canonical_metadata':records,'ltc_any_timeframe_records':conflicts,'external_runs':'NOT_AUDITED_UNKNOWN','conclusion':'NO_IDENTIFIED_CANONICAL_LTC_CONFLICT' if not conflicts else 'BLOCKED_REQUIRES_CONFLICT_REVIEW','program_assertions':{'search_days':366,'development_days':365,'pre_roll_days':120,'holdout_days':180,'expected_funding_events':2193},'github_ltc_issue_search':[]}
(ROOT/'consumption-metadata.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({'index_checks':len(checks),'canonical_records':len(records),'ltc_records':conflicts,'conclusion':report['conclusion'],'date_assertions':report['program_assertions']}))
