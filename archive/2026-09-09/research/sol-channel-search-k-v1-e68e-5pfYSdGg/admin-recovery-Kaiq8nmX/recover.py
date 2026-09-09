"""Exactly once authorized administrative recovery; never copies Generation or Candidate rows."""
from pathlib import Path
import json,hashlib,datetime,fcntl,sys
from lab.database import init_database,get_connection
from lab.codex_generation import load_profile_snapshot
from lab.bounded_research import canonical,profile_acquisition_contract,load_profile_economic_gate
R=Path(__file__).resolve().parent;OLD=R.parent
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
now=lambda:datetime.datetime.now(datetime.UTC).isoformat()
if sys.argv[1]=='record':
    api=json.loads((OLD/'http-evidence/before-administrative-recovery.json').read_text())['response']['state']
    assert api['campaign_id'] is None and api['attempts']==[] and api['budget']['consumed_total']==0
    assert sorted(p.name for p in (OLD/'search').iterdir())==['acquisition']
    with get_connection(OLD/'research.sqlite',read_only=True) as con:
        tables=[x[0] for x in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        counts={t:con.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in tables}
        assert list(counts.values())==[1,1,1,0,0,0]
    record={'status':'ADMINISTRATIVE_RECOVERY_BEFORE_SEARCH','recorded_at_utc':now(),'supervisor_authorization':'01a05dcc-17fd-7972-9177-9fed95e4b07a explicit message: only once same taskK/Issue76; preserve old records; lowercase family; unchanged Profile/source/analysis/gates; native budget2 cumulative; no download','old_root':str(OLD),'old_database':str(OLD/'research.sqlite'),'old_database_sha256':sha(OLD/'research.sqlite'),'old_db_sidecars':{p.name:sha(p) for p in OLD.glob('research.sqlite-*')},'old_generation':'ea832723-5c6c-4c6f-abb1-feb71053d614','old_candidate':'22c852c0-d0e3-4a68-877c-aed934155100','old_failure_http409_sha256':sha(OLD/'http-evidence/search-1-submitted.json'),'old_freeze_manifest_sha256':sha(OLD/'freeze-manifest.json'),'old_counts':counts,'no_claim_API_sha256':sha(OLD/'http-evidence/before-administrative-recovery.json'),'no_claim_search_entries':['acquisition'],'native_count':0,'researcher_S_results_read':False,'recovery_root':str(R),'only_field_correction':{'strategy_family_before':'SOL_PRIOR_CLOSE_CHANNEL_CONSOLIDATION_V1','strategy_family_after':'sol_prior_close_channel_consolidation_v1'},'maximum_native_attempts_cumulative':2,'additional_downloads_allowed':0}
    target=R/'administrative-recovery-before.json';assert not target.exists();target.write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps({'path':str(target),'sha256':sha(target)}))
elif sys.argv[1]=='initialize':
    assert (R/'administrative-recovery-before.json').exists()
    p=json.loads((OLD/'profile.json').read_text());db=R/'research.sqlite';assert not db.exists();init_database(db)
    with get_connection(db) as con:
        con.execute('INSERT INTO research_profiles ('+','.join(p)+') VALUES ('+','.join('?' for _ in p)+')',tuple(p.values()))
    with get_connection(db,read_only=True) as con: snapshot=load_profile_snapshot(con,p['id'])
    expected=json.loads((OLD/'actual-profile-contract.json').read_text())
    assert snapshot==expected['profile_snapshot']
    assert hashlib.sha256(canonical(snapshot)).hexdigest()==expected['profile_snapshot_sha256']
    actual=profile_acquisition_contract(db,p['id'],'20240301-20250301','20250301-20260301',29,load_profile_economic_gate(OLD/'economic-gate.json'))
    assert actual==expected
    frozen=json.loads((OLD/'freeze-manifest.json').read_text())
    for name,digest in frozen['files'].items(): assert sha(OLD/name)==digest
    (R/'console-runtime').mkdir(mode=0o700)
    receipt={'recorded_at_utc':now(),'recovery_database':str(db),'recovery_db_initial_sha256':sha(db),'profile_snapshot_sha256':expected['profile_snapshot_sha256'],'profile_and_contract_identical':True,'original_frozen_files_unchanged':True,'old_database_after_console_stop_sha256':sha(OLD/'research.sqlite'),'recovery_before_sha256':sha(R/'administrative-recovery-before.json'),'source_reused_no_download':str(OLD/'source-acquisition'),'search_root_reused_without_prior_claim':str(OLD/'search'),'development_QC_root_reused':str(OLD/'development'),'strategy_family':'sol_prior_close_channel_consolidation_v1','native_budget_cumulative':2,'prior_native_count':0,'scope':'same cohort, administrative recovery instance; original successful Generation and original HTTP409 remain unchanged'}
    target=R/'administrative-recovery-initialized.json';target.write_text(json.dumps(receipt,indent=2)+'\n')
    ledger=Path('/Users/shenjianpeng/Documents/freqtrade-lab-local/search-research-supervision-20260902/global-research-ledger.jsonl')
    entry={'record_type':'ADMINISTRATIVE_RECOVERY_BEFORE_SEARCH','cohort_id':'SOL_PRIOR_CLOSE_CHANNEL_CONSOLIDATION_V1-e68e-5pfYSdGg','issue':76,'recorded_at_utc':now(),'original_root':str(OLD),'recovery_root':str(R),'receipt_sha256':sha(target),'prior_native_attempts':0,'maximum_native_attempts_cumulative':2,'reason':'uppercase family accepted by Generation then rejected before Search claim; one authorized fresh DB and real regeneration with lowercase family','windows_sources_gates_strategies_unchanged':True,'new_downloads':0}
    with ledger.open('r+b') as f:
        fcntl.flock(f,fcntl.LOCK_EX);prefix=f.read();assert hashlib.sha256(prefix).hexdigest()=='ff6e884bf0b1f65e2c30d76e67b21167381b2a947dce39ace38d63e2e1782499'
        f.write((json.dumps(entry,separators=(',',':'))+'\n').encode());f.flush();f.seek(0);after=f.read();assert after[:len(prefix)]==prefix
    (R/'administrative-ledger-receipt.json').write_text(json.dumps({'before_sha256':hashlib.sha256(prefix).hexdigest(),'after_sha256':hashlib.sha256(after).hexdigest(),'old_prefix_unchanged':True,'lines':len(after.splitlines())},indent=2)+'\n')
    print(json.dumps(receipt,indent=2))
else: raise RuntimeError('unsupported recovery action')
