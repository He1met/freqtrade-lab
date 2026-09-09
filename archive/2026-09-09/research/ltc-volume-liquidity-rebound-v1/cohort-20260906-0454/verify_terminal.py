"""Reconcile the only native terminal, original freeze, SQLite and HTTP."""
import hashlib
import json
import zipfile
from contextlib import closing
from pathlib import Path
from urllib.request import urlopen
from lab.database import get_connection
from lab.codex_generation import load_approved_candidate_snapshot,load_profile_snapshot

ROOT=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    frozen=json.loads((ROOT/'freeze-receipt.json').read_text())
    terminal=json.loads((ROOT/'search/search-terminal.json').read_text())
    audit=json.loads((ROOT/'search-economic-audit.json').read_text())
    for n,h in frozen['files_sha256'].items():assert sha(ROOT/n)==h
    ready=json.loads((ROOT/'source-ready.json').read_text())
    for n,h in ready['files_sha256'].items():assert sha(ROOT/n)==h
    qc=json.loads((ROOT/'source-consumer-qc.json').read_text())
    for n,h in qc['source_all_file_sha256'].items():assert sha(ROOT/'source'/n)==h
    with urlopen('http://127.0.0.1:52800/api/search/context',timeout=10) as f:http=json.load(f)
    state=http['state']
    assert state['campaign_id']==terminal['campaign_id']==audit['actual_campaign_id']
    assert state['status']==terminal['status']==audit['status']=='SEARCH_TERMINATED_NO_FINALIST'
    assert state['budget']['consumed_total']==1 and state['budget']['remaining']==0
    assert len(state['attempts'])==1 and state['search_finalist'] is None
    attempt=state['attempts'][0]
    assert attempt['candidate_id']==frozen['candidate_id'] and attempt['technical_status']=='VALID'
    assert attempt['strategy_sha256']==sha(ROOT/'LtcVolumeLiquidityReboundV1.py')
    archive=Path(audit['archive_path']);assert sha(archive)==audit['archive_sha256']==attempt['evidence']['archive']['sha256']
    with zipfile.ZipFile(archive) as z:report=json.loads(z.read(archive.stem+'.json'))['strategy']['LtcVolumeLiquidityReboundV1']
    assert len(report['trades'])==attempt['search_metrics']['total_trades']==audit['total_trades']
    assert abs(report['profit_total_abs']-float(audit['native_net_usdt']))<1e-7
    assert abs(attempt['search_metrics']['gross_profit_before_fees_pct']*10-float(audit['gross_usdt']))<1e-6
    with closing(get_connection(ROOT/'research.sqlite',read_only=True)) as c:
        c.execute('BEGIN')
        projected=json.loads(c.execute('SELECT response_json FROM generation_runs WHERE id=?',(state['campaign_id'],)).fetchone()[0])
        assert projected==terminal
        counts={t:c.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in ['research_profiles','generation_runs','candidates','research_runs','backtest_executions','releases']}
        assert list(counts.values())==[1,2,1,0,0,0]
        p=load_profile_snapshot(c,frozen['profile_id']);candidate=load_approved_candidate_snapshot(c,frozen['candidate_id'])
        assert p==json.loads((ROOT/'profile-snapshot.json').read_text())
        assert candidate.code_text==(ROOT/'LtcVolumeLiquidityReboundV1.py').read_text() and candidate.profile==p
        c.rollback()
    assert len(list((ROOT/'search').rglob('*.zip')))==1
    assert not (ROOT/'development/pilot-spec.json').exists()
    ledger=Path('/Users/shenjianpeng/Documents/freqtrade-lab-local/search-research-supervision-20260902/global-research-ledger.jsonl')
    ledger_before=json.loads((ROOT/'ledger-source-qc-receipt.json').read_text())
    assert sha(ledger)==ledger_before['after_sha256'] and ledger.stat().st_size==ledger_before['after_bytes']
    with (ROOT/'search-http-terminal-context.json').open('x') as f:json.dump(http,f,indent=2)
    mapping={'planned_campaign_id':frozen['planned_campaign_id'],'actual_campaign_id':state['campaign_id'],
        'original_intent_preserved':True,'planned_intent_sha256':sha(ROOT/'search-plan-intent.json'),
        'actual_origin':'single authorized Console POST /api/search-campaigns','candidate_id':frozen['candidate_id']}
    with (ROOT/'campaign-identity-mapping.json').open('x') as f:json.dump(mapping,f,indent=2)
    names=['search/search-terminal.json','search/trials.jsonl','search-economic-audit.json','search-http-terminal-context.json','campaign-identity-mapping.json','search-authorization.json','start_search_once.py','audit_search_terminal.py','accounting_semantics.py','verify_terminal.py']
    result={'status':'TERMINAL_IDENTITIES_VERIFIED','actual_campaign_id':state['campaign_id'],'planned_campaign_id':frozen['planned_campaign_id'],'database_generation_projection_equals_native_terminal':True,'http_terminal_agrees':True,'raw_zip_report_and_metrics_agree':True,'counts':counts,'budget':{'used':1,'remaining':0,'maximum':1},'native_backtests':1,'freeze_and_source_and_source_ready_hashes_preserved':True,'raw_zip_sha256':sha(archive),'files_sha256':{n:sha(ROOT/n) for n in names},'ledger_unchanged_after_source_qc':True,'global_terminal_consumption_appended':False,'issue_closed':False,'D':'PRODUCER_QC_ONLY_NOT_RUN','H':'NOT_ACQUIRED_SEALED_UNREAD','Stress':'SEALED_UNREAD_NOT_RUN','source_acquisitions':1,'source_HTTP_attempts':15}
    with (ROOT/'terminal-identity-verification.json').open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps(result))

if __name__=='__main__':main()
