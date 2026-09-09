"""Read only reconciliation of this cohort's executed Search evidence."""
import hashlib,json,math,zipfile,subprocess
from pathlib import Path
from collections import Counter
from lab.database import get_connection
from lab.bounded_research import verify_search_terminal_projection

r=Path(__file__).resolve().parent;s=r/'search-data'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
api=json.loads((r/'search-terminal-api.json').read_text())['body']
terminal=json.loads((s/'search-terminal.json').read_text())
assert api['status']==terminal['status']=='SEARCH_TERMINATED_NO_FINALIST'
assert api['search_finalist'] is terminal['search_finalist'] is None
assert len(api['attempts'])==api['budget']['consumed_total']==2
assert terminal['trials_sha256']==sha(s/'trials.jsonl')
assert terminal['campaign_sha256']==sha(s/'campaign.json')
expected_tables={'research_profiles','generation_runs','candidates','research_runs','backtest_executions','releases'}
with get_connection(r/'lab.sqlite',read_only=True) as con:
    tables={x[0] for x in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert tables==expected_tables
    counts={name:con.execute('SELECT COUNT(*) FROM '+name).fetchone()[0] for name in sorted(tables)}
    assert counts=={'research_profiles':1,'generation_runs':3,'candidates':2,'research_runs':0,'backtest_executions':0,'releases':0}
    g=dict(con.execute('SELECT * FROM generation_runs WHERE id=?',(terminal['campaign_id'],)).fetchone())
    assert g['source']=='MANUAL' and g['status']=='COMPLETED'
    assert json.loads(g['response_json'])==terminal
    projection=json.loads(g['parse_report_json']);assert projection['finalist_binding'] is None
    assert projection['evidence']['attempts']==api['attempts']
    assert projection['evidence']['terminal']['sha256']==sha(s/'search-terminal.json')
    verify_search_terminal_projection(json.loads(g['request_json']),terminal,projection['evidence'])
    candidates={row['id']:dict(row) for row in con.execute('SELECT * FROM candidates')}
    generations=[dict(row) for row in con.execute('SELECT id,source,status,returned_strategy_count FROM generation_runs')]
    assert not con.execute('PRAGMA foreign_key_check').fetchall()
results=[]
for attempt in api['attempts']:
    assert attempt['technical_status']=='VALID' and attempt['failure_reason'] is None
    candidate=candidates[attempt['candidate_id']]
    assert hashlib.sha256(candidate['code_text'].encode()).hexdigest()==candidate['code_sha256']==attempt['strategy_sha256']
    for key in ('archive','result'):
        evidence=attempt['evidence'][key];assert sha(s/evidence['path'])==evidence['sha256']
    result=json.loads((s/attempt['evidence']['result']['path']).read_text())
    metrics=attempt['search_metrics']
    assert result['exit_code']==0
    for key,value in metrics.items():
        result_key='net_profit_after_fees_pct' if key=='net_profit_after_base_fees_pct' else key
        assert result[result_key]==value
    with zipfile.ZipFile(s/attempt['evidence']['archive']['path']) as z:
        report_name=[name for name in z.namelist() if name.endswith('.json') and not name.endswith('_config.json')][0]
        strategy=json.loads(z.read(report_name))['strategy'][attempt['class_name']]
        py_name=[name for name in z.namelist() if name.endswith('.py')][0]
        assert z.read(py_name).decode()==candidate['code_text']
        trades=strategy['trades']
        assert len(trades)==strategy['total_trades']==metrics['total_trades']
        assert math.isclose(strategy['profit_total']*100,metrics['net_profit_after_base_fees_pct'],abs_tol=1e-8)
        assert math.isclose(strategy['profit_factor'],metrics['profit_factor'],abs_tol=1e-8)
        assert math.isclose(strategy['max_drawdown_account']*100,metrics['max_drawdown_pct'],abs_tol=1e-8)
        assert math.isclose(sum(t['trade_duration'] for t in trades)/len(trades),metrics['average_holding_period_minutes'])
        assert all(math.isfinite(t['funding_fees']) and t['fee_open']==.0005 and t['fee_close']==.0005 and t['leverage']==1 and t['is_short'] is False for t in trades)
        funding=sum(t['funding_fees'] for t in trades)
        exits=dict(Counter(t['exit_reason'] for t in trades))
        assert exits.get('roi',0)==metrics['roi_exit_count']==0
    gates={'trades_gte_5':metrics['total_trades']>=5,'net_strictly_positive':metrics['net_profit_after_base_fees_pct']>0,'net_gte_1_25_pct':metrics['net_profit_after_base_fees_pct']>=1.25,'profit_factor_gte_1_10':metrics['profit_factor']>=1.10,'drawdown_lte_15_pct':metrics['max_drawdown_pct']<=15,'average_holding_gte_10080_minutes':metrics['average_holding_period_minutes']>=10080,'roi_exit_count_zero':metrics['roi_exit_count']==0}
    assert [k for k,v in gates.items() if not v]==['trades_gte_5']
    results.append({'candidate_id':attempt['candidate_id'],'generation_id':candidate['generation_run_id'],'class_name':attempt['class_name'],'strategy_sha256':attempt['strategy_sha256'],'metrics':metrics,'gates':gates,'failure_attribution':'INSUFFICIENT_TRADE_SAMPLE_NOT_ECONOMIC_LOSS','funding_fees_sum':funding,'exit_reasons':exits,'archive_sha256':attempt['evidence']['archive']['sha256'],'result_sha256':attempt['evidence']['result']['sha256']})
head=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
dirty=subprocess.check_output(['git','status','--porcelain=v1'],text=True).strip()
remote=subprocess.check_output(['git','ls-remote','origin','refs/heads/main'],text=True).split()[0]
assert not dirty and head==remote=='dc82c61fe8a27a654977344755c088412518d858'
report={'status':terminal['status'],'attribution':'INSUFFICIENT_TRADE_SAMPLE_NOT_ECONOMIC_LOSS','issue':63,'root':str(r),'root_mode':oct(r.stat().st_mode&0o777),'head':head,'live_main':remote,'dirty':False,'profile_id':'ltc-exact-grid-dual-sma-28-84-v1','campaign_id':terminal['campaign_id'],'generations':generations,'table_counts':counts,'results':results,'terminal_sha256':sha(s/'search-terminal.json'),'trials_sha256':sha(s/'trials.jsonl'),'research_run_id':None,'development_status':'NOT_EXECUTED_NO_LEGAL_FINALIST','development_metrics':None,'holdout_status':'SEALED_UNREAD','holdout_stress_status':'SEALED_UNREAD','slippage':'UNKNOWN','service_tier':'UNKNOWN','live_page_observed':{'url':'http://127.0.0.1:64601/console','status':'SEARCH_TERMINATED_NO_FINALIST','attempts':2,'finalist':None,'round_1_button_disabled':True,'round_2_button_disabled':True,'development_result':'暂无数据','generic_development_ready':'PRESENT_NOT_FINALIST_EVIDENCE','frequi':'UNAVAILABLE'},'verification':'DB projection/API/terminal/trials/results/ZIP source and metrics consistent; fees/funding present; schema remains six tables; no downstream rows'}
(r/'final-audit.json').write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n')
print(json.dumps({'status':report['status'],'tables':counts,'results':[{'class_name':x['class_name'],'metrics':x['metrics'],'failed_gates':[k for k,v in x['gates'].items() if not v],'funding_fees_sum':x['funding_fees_sum']} for x in results],'head':head,'live_main':remote},ensure_ascii=False))
