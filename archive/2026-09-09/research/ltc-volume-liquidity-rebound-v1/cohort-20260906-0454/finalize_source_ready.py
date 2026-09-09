"""Verify prepared evidence; record source/QC progress without consuming Search."""
import fcntl
import hashlib
import json
import os
from datetime import datetime,timezone
from pathlib import Path
from binding import logical_snapshot

ROOT=Path(__file__).resolve().parent
LEDGER=Path('/Users/shenjianpeng/Documents/freqtrade-lab-local/search-research-supervision-20260902/global-research-ledger.jsonl')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def digest(b):return hashlib.sha256(b).hexdigest()

def main():
    frozen=json.loads((ROOT/'freeze-receipt.json').read_text());qc=json.loads((ROOT/'source-consumer-qc.json').read_text())
    for n,h in frozen['files_sha256'].items():assert sha(ROOT/n)==h
    for n,h in qc['source_all_file_sha256'].items():assert sha(ROOT/'source'/n)==h
    for p,h in {**frozen['producer_files_sha256'],**frozen['native_files_sha256']}.items():assert sha(Path(p))==h
    binding=logical_snapshot(ROOT/'research.sqlite',frozen['profile_id'],frozen['candidate_id'])
    assert binding==json.loads((ROOT/'database-logical-snapshot.json').read_text())
    context=json.loads((ROOT/'console-search-context.json').read_text());preflight=json.loads((ROOT/'console-preflight.json').read_text())
    assert context['state']['status']=='SEARCH_READY' and context['state']['campaign_id'] is None
    assert context['state']['budget']['consumed_total']==0 and context['state']['budget']['remaining']==1
    assert len(context['candidates'])==1 and context['candidates'][0]['candidate_id']==frozen['candidate_id']
    assert context['candidates'][0]['strategy_sha256']==frozen['files_sha256']['LtcVolumeLiquidityReboundV1.py']
    assert context['capability']['single_baseline']==json.loads((ROOT/'single-baseline.json').read_text())
    assert preflight['checks']['search_research']['status']=='READY'
    assert preflight['checks']['sqlite']['exact_six_tables'] is True
    assert not list((ROOT/'search').rglob('*.zip')) and not (ROOT/'search/search-terminal.json').exists()
    requests=[json.loads(l) for l in (ROOT/'source-attempts.jsonl').read_text().splitlines()]
    started=[x for x in requests if x['event']=='ATTEMPT_BEFORE_NETWORK']
    assert len(started)==15
    first=datetime.fromisoformat(started[0]['utc']);last=datetime.fromisoformat(started[-1]['utc'])
    assert first>datetime.fromisoformat(frozen['created_at']) and (last-first).total_seconds()<1800
    previous=json.loads((ROOT/'ledger-preregistration-receipt.json').read_text())
    with open(str(LEDGER)+'.lock','a+b') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        before=LEDGER.read_bytes();assert len(before)==previous['after_bytes'] and digest(before)==previous['after_sha256']
        row={'record_type':'SOURCE_AND_CONSUMERS_VERIFIED_NOT_EXECUTED','recorded_at_utc':datetime.now(timezone.utc).isoformat(),'issue':93,'cohort_id':frozen['planned_campaign_id'],'actual_campaign_id':None,'exchange':'okx','trading_mode':'spot','pair':'LTC/USDT','instrument_id':'LTC-USDT','timeframe':'1d','root':str(ROOT),'search_timerange':'20210501-20240101','development_timerange':'20240101-20250101','holdout_timerange':'20250101-20260531','status':'SOURCE_AND_S_CONSUMER_QC_PASSED_SEARCH_NOT_RUN','source_rows':1381,'source_start_utc':'2021-03-22T00:00:00Z','source_end_exclusive_utc':'2025-01-01T00:00:00Z','S_rows_including_startup':1015,'S':'PREPARED_QC_ONLY_NOT_ECONOMICALLY_CONSUMED','D':'PRODUCER_QC_ONLY_NOT_RUN','H':'SEALED_UNREAD_NOT_ACQUIRED','Stress':'SEALED_UNREAD_NOT_RUN','source_acquisitions':1,'actual_http_requests':15,'native_backtests':0,'actual_search_attempts':0,'search_finalist':None,'research_run_id':None,'freeze_sha256':sha(ROOT/'freeze-receipt.json'),'source_provenance_sha256':qc['source_provenance_sha256'],'source_receipt_sha256':qc['source_receipt_sha256'],'source_consumer_qc_sha256':sha(ROOT/'source-consumer-qc.json'),'prior_ledger_sha256':digest(before)}
        addition=(json.dumps(row,ensure_ascii=False,separators=(',',':'))+'\n').encode()
        with LEDGER.open('ab') as out:out.write(addition);out.flush();os.fsync(out.fileno())
        after=LEDGER.read_bytes();assert after==before+addition
        ledger_receipt={'before_bytes':len(before),'before_sha256':digest(before),'after_bytes':len(after),'after_sha256':digest(after),'old_prefix_unchanged':True,'record_line':len(after.splitlines()),'cohort_id':row['cohort_id'],'new_record_sha256':digest(addition)}
        with (ROOT/'ledger-source-qc-receipt.json').open('x') as out:json.dump(ledger_receipt,out,indent=2)
    paths=['freeze-receipt.json','protocol.md','LtcVolumeLiquidityReboundV1.py','runtime-config.json','profile-snapshot.json','database-logical-snapshot.json','source-consumer-qc.json','source-attempts.jsonl','console-page.html','console-preflight.json','console-search-context.json','ledger-preregistration-receipt.json','ledger-source-qc-receipt.json','prepare-search-command.json','prepare-search-command.log','prepare-search-command-2.json','prepare-search-command-2.log','prepare_and_qc.py','finalize_source_ready.py']
    result={'status':'READY_FOR_SUPERVISOR_SEARCH_REVIEW_NOT_AUTHORIZED','issue':93,'issue_url':'https://github.com/He1met/freqtrade-lab/issues/93','root':str(ROOT),'profile_id':frozen['profile_id'],'generation_id':frozen['generation_id'],'candidate_id':frozen['candidate_id'],'planned_campaign_id':frozen['planned_campaign_id'],'actual_campaign_id':None,'native_backtests':0,'counts':binding['counts'],'page':'http://127.0.0.1:52800/console','http_gets_verified':['/console','/api/control/preflight','/api/search/context'],'search_capability':'READY','search_state':'SEARCH_READY','overall_console_status':preflight['overall_status'],'frequi_status':preflight['checks']['frequi']['status'],'frequi_reason':preflight['checks']['frequi']['reason'],'budget':{'source_used':15,'source_maximum':24,'source_acquisitions':1,'automatic_retries':0,'search_used':0,'search_remaining':1},'source':qc['source'],'search_slices':qc['search_slices'],'D':qc['D'],'H':qc['H'],'first_request_after_freeze':True,'request_start_span_seconds':(last-first).total_seconds(),'source_provenance_sha256':qc['source_provenance_sha256'],'source_receipt_sha256':qc['source_receipt_sha256'],'files_sha256':{n:sha(ROOT/n) for n in paths},'known_preparation_corrections':['validator Boolean column syntax replaced by equivalent entry-mask expression before freezing','pinned native PYTHONPATH supplied before any DB registration','QC timestamp equality compares UTC instants across ms/us storage units','missing frozen Development CLI argument corrected before output creation; source not retried','Console directories created after initial startup refusal; no old server replaced']}
    with (ROOT/'source-ready.json').open('x') as out:json.dump(result,out,indent=2)
    print(json.dumps({'status':result['status'],'source_ready_sha256':sha(ROOT/'source-ready.json'),'ledger':ledger_receipt,'page':result['page'],'counts':result['counts']}))

if __name__=='__main__':main()
