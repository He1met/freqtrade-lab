"""Fresh private six-table Profile bootstrap, immutable freeze and append-only prereg."""
from pathlib import Path
import json, hashlib, datetime, fcntl
from lab.database import init_database,get_connection
R=Path(__file__).resolve().parent
REPO=Path('/Users/shenjianpeng/.codex/worktrees/e68e/freqtrade-lab')
LEDGER=Path('/Users/shenjianpeng/Documents/freqtrade-lab-local/search-research-supervision-20260902/global-research-ledger.jsonl')
sha=lambda b:hashlib.sha256(b).hexdigest()
now=datetime.datetime.now(datetime.UTC).isoformat()
p=json.loads((R/'profile.json').read_text());db=R/'research.sqlite'
if not db.exists(): init_database(db)
with get_connection(db) as con:
    cols=','.join(p);marks=','.join('?' for x in p)
    existing=con.execute('SELECT * FROM research_profiles').fetchall()
    if not existing:
        con.execute(f'INSERT INTO research_profiles ({cols}) VALUES ({marks})',tuple(p.values()))
    else:
        assert len(existing)==1
        old=dict(existing[0]); assert old['id']=='sol-channel-k-v1-e68e-5pfYSdGg'
        old['id']=p['id']; assert old==p
        assert con.execute('SELECT COUNT(*) FROM generation_runs').fetchone()[0]==0
        con.execute('UPDATE research_profiles SET id=? WHERE id=?',(p['id'],'sol-channel-k-v1-e68e-5pfYSdGg'))
    tables=[x[0] for x in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    assert len(tables)==6
from lab.bounded_research import profile_acquisition_contract,load_profile_economic_gate
contract=profile_acquisition_contract(db,p['id'],'20240301-20250301','20250301-20260301',29,load_profile_economic_gate(R/'economic-gate.json'))
(R/'actual-profile-contract.json').write_text(json.dumps(contract,indent=2)+'\n')
names=['profile.json','economic-gate.json','source-window.json','frozen-contract.md','ConsolidationChannelR1.py','ConsolidationChannelR2.py','audit-results.py','bootstrap.py','actual-profile-contract.json']
sources=['scripts/fetch_okx_profile_data.py','tests/fixtures/freqtrade_2026_7/producer/fetch_okx_public_data.py','lab/bounded_research.py','lab/codex_generation.py','lab/search_campaign.py','lab/research_console.py','sql/schema_v1.sql']
manifest={'frozen_at_utc':now,'issue':76,'root':str(R),'repo_head':'0ace04b7c10ea35fb8ce6f25e043ac78be87c19e','native_head':'52bc96f4480b1a0da6a9b455bd00b17fbb6786a5','files':{n:sha((R/n).read_bytes()) for n in names},'implementation_sha256':{n:sha((REPO/n).read_bytes()) for n in sources},'pre_value':True,'actual_source_rows':None,'actual_native_executions':0,'generation_reasoning_effort':'UNKNOWN','generation_service_tier':'UNKNOWN'}
raw=(json.dumps(manifest,indent=2)+'\n').encode();(R/'freeze-manifest.json').write_bytes(raw)
record={'record_type':'COHORT_PREREGISTERED','recorded_at_utc':now,'cohort_id':'SOL_PRIOR_CLOSE_CHANNEL_CONSOLIDATION_V1-e68e-5pfYSdGg','issue':76,'pair':'SOL/USDT:USDT','timeframe':'1d','search_window':['2024-03-01T00:00:00Z','2025-03-01T00:00:00Z'],'development_window':['2025-03-01T00:00:00Z','2026-03-01T00:00:00Z'],'holdout_stress_window':['2026-03-01T00:00:00Z','2026-08-31T00:00:00Z'],'maximum_native_attempts':2,'actual_native_attempts':0,'runtime_root':str(R),'freeze_manifest_sha256':sha(raw),'status':'FROZEN_PRE_VALUE_AWAITING_PRODUCER_FAILURE_RETENTION_DISPOSITION','data_acquired':False,'D_researcher_semantic_exposure':False,'H_values_opened':False,'external_exposure':'UNKNOWN','identified_conflict':False}
with LEDGER.open('r+b') as f:
    fcntl.flock(f,fcntl.LOCK_EX);prefix=f.read()
    assert len(prefix.splitlines())==78 and sha(prefix)=='962daaf9558e591030bb798d0d4ce352d7c7bd42c1ecdd8a232cfc9940b6957d'
    addition=(json.dumps(record,separators=(',',':'))+'\n').encode();f.write(addition);f.flush()
    f.seek(0);after=f.read();assert after[:len(prefix)]==prefix
(R/'prereg-ledger-receipt.json').write_text(json.dumps({'prior_sha256':sha(prefix),'prior_bytes':len(prefix),'prior_lines':78,'after_sha256':sha(after),'after_lines':79,'appended_sha256':sha(addition),'prefix_unchanged':True},indent=2)+'\n')
print(json.dumps({'freeze_manifest_sha256':sha(raw),'ledger_after_sha256':sha(after),'profile_contract':contract,'database':str(db),'table_count':len(tables)},indent=2))
