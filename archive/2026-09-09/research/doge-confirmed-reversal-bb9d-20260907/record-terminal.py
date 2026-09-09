from pathlib import Path
from datetime import datetime, timezone
import json, hashlib, fcntl, os
r=Path(__file__).parent
sha=lambda b:hashlib.sha256(b).hexdigest()
review=json.loads((r/'search-protocol-review.json').read_bytes())
record={'record_type':'SEARCH_TERMINAL_IMPORTED','cohort_id':'issue98-doge-confirmed-reversal-single-v1','issue':98,
        'recorded_at_utc':datetime.now(timezone.utc).isoformat(),'status':review['project_status'],
        'economic_classification':review['economic_classification'],'sample_classification':review['sample_classification'],
        'all_protocol_gates':review['all_protocol_gates'],'pair':'DOGE/USDT:USDT','exchange':'binance','search_window':['2023-11-06','2024-11-04'],
        'actual_Search_attempts':1,'campaign_id':review['campaign_id'],'candidate_id':review['candidate_id'],
        'generation_id':'080e6bd1-f3db-42fe-8a06-fdd21017e82f','root':str(r),'database':str(r/'lab.sqlite'),
        'protocol_sha256':review['protocol_sha256'],'strategy_sha256':review['strategy_sha256'],
        'archive':review['archive'],'archive_sha256':review['archive_sha256'],
        'review_path':str(r/'search-protocol-review.json'),'review_sha256':sha((r/'search-protocol-review.json').read_bytes()),
        'project_terminal_sha256':sha((r/'search-campaign/search-terminal.json').read_bytes()),
        'project_trials_sha256':sha((r/'search-campaign/trials.jsonl').read_bytes()),
        'ui_verification_sha256':sha((r/'ui-verification.json').read_bytes()),
        'six_table_counts':review['six_table_counts'],'native_metrics':review['native_metrics'],
        'cost_decomposition':review['cost_decomposition'],
        'conservative_MTM_DD_pct':review['conservative_audit']['conservative_mtm_drawdown_pct'],
        'conservative_PF':review['conservative_audit']['conservative_profit_factor'],
        'effective_natural_trades':32,'D_status':'MECHANICAL_QC_ONLY_NOT_EXECUTED','H_Stress':'SEALED_UNREAD_UNACQUIRED',
        'ResearchRun_id':None,'disposition':'SEARCH_ONLY_PASS_AWAITING_SUPERVISOR_DEVELOPMENT_DECISION','retry_authorized':False,'search_consumed':True}
ledger=Path('/Users/shenjianpeng/Documents/freqtrade-lab-local/search-research-supervision-20260902/global-research-ledger.jsonl')
with ledger.with_suffix(ledger.suffix+'.lock').open('a+b') as lock:
    fcntl.flock(lock.fileno(),fcntl.LOCK_EX)
    before=ledger.read_bytes()
    assert sha(before)==json.loads((r/'ledger-search-pre-run-receipt.json').read_bytes())['after_sha256']
    record['previous_prefix_sha256']=sha(before)
    addition=(json.dumps(record,sort_keys=True)+'\n').encode()
    with ledger.open('ab') as f:
        f.write(addition);f.flush();os.fsync(f.fileno())
    after=ledger.read_bytes();assert after==before+addition
    receipt={'before_bytes':len(before),'after_bytes':len(after),'before_sha256':sha(before),'after_sha256':sha(after),'prefix_preserved':True,'appended_record_sha256':sha(addition)}
    (r/'terminal-ledger-record.json').write_text(json.dumps(record,indent=2)+'\n')
    (r/'terminal-ledger-receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps(receipt))

