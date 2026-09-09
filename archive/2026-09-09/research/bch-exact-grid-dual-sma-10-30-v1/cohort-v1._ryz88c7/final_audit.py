"""Read-only reconciliation of this authorized cohort's three actual engine outputs."""
import hashlib,json,math,zipfile,subprocess
from pathlib import Path
from collections import Counter
from lab.database import get_connection
from lab.bounded_research import verify_search_terminal_projection
r=Path(__file__).resolve().parent;s=r/'search-data'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def load(p):return json.loads(p.read_text())
api=load(r/'search-terminal-api.json')['body'];dev=load(r/'development-terminal-api.json')['body'];terminal=load(s/'search-terminal.json')
assert api['status']==terminal['status']=='SEARCH_FINALIST_FROZEN'
assert api['search_finalist']==terminal['search_finalist']
assert len(api['attempts'])==api['budget']['consumed_total']==2
assert terminal['trials_sha256']==sha(s/'trials.jsonl') and terminal['campaign_sha256']==sha(s/'campaign.json')
expected={'research_profiles':1,'generation_runs':3,'candidates':2,'research_runs':1,'backtest_executions':1,'releases':0}
with get_connection(r/'lab.sqlite',read_only=True) as con:
 tables={x[0] for x in con.execute("SELECT name FROM sqlite_master WHERE type='table'")};assert tables==set(expected)
 counts={n:con.execute('SELECT COUNT(*) FROM '+n).fetchone()[0] for n in sorted(tables)};assert counts==expected
 g=dict(con.execute('SELECT * FROM generation_runs WHERE id=?',(terminal['campaign_id'],)).fetchone())
 assert g['source']=='MANUAL' and g['status']=='COMPLETED' and json.loads(g['response_json'])==terminal
 projection=json.loads(g['parse_report_json']);assert projection['evidence']['attempts']==api['attempts']
 assert projection['evidence']['terminal']['sha256']==sha(s/'search-terminal.json')
 verify_search_terminal_projection(json.loads(g['request_json']),terminal,projection['evidence'])
 candidates={row['id']:dict(row) for row in con.execute('SELECT * FROM candidates')}
 generations=[dict(row) for row in con.execute('SELECT id,source,status,returned_strategy_count FROM generation_runs')]
 assert sum(x['source']=='CODEX' and x['status']=='COMPLETED' and x['returned_strategy_count']==1 for x in generations)==2
 rr=dict(con.execute('SELECT * FROM research_runs').fetchone());ex=dict(con.execute('SELECT * FROM backtest_executions').fetchone())
 assert not con.execute('PRAGMA foreign_key_check').fetchall()

# Compare actual Freqtrade ZIP reports to API/DB and retained source; never substitute values.
def zipcheck(path,code,class_name,m):
 with zipfile.ZipFile(path) as z:
  reports=[n for n in z.namelist() if n.endswith('.json') and not n.endswith('_config.json')]
  report=next(json.loads(z.read(n)) for n in reports if 'strategy' in json.loads(z.read(n)))
  strategy=report['strategy'][class_name]
  py=[n for n in z.namelist() if n.endswith('.py')];assert len(py)==1 and z.read(py[0]).decode()==code
  trades=strategy['trades'];assert len(trades)==strategy['total_trades']==m['total_trades']
  assert math.isclose(strategy['profit_total']*100,m['net_profit_after_base_fees_pct'],abs_tol=1e-8)
  assert math.isclose(strategy['profit_factor'],m['profit_factor'],abs_tol=1e-8)
  assert math.isclose(strategy['max_drawdown_account']*100,m['max_drawdown_pct'],abs_tol=1e-8)
  assert math.isclose(sum(t['trade_duration'] for t in trades)/len(trades),m['average_holding_period_minutes'])
  assert all(math.isfinite(t['funding_fees']) and t['fee_open']==.0005 and t['fee_close']==.0005 and t['leverage']==1 and t['is_short'] is False for t in trades)
  assert all(t['pair']=='BCH/USDT:USDT' for t in trades)
  exits=dict(Counter(t['exit_reason'] for t in trades));assert exits.get('roi',0)==m['roi_exit_count']==0
  return {'archive_path':str(path),'archive_sha256':sha(path),'funding_fees_sum':sum(t['funding_fees'] for t in trades),'exit_reasons':exits,'fee_open':.0005,'fee_close':.0005,'leverage':1,'long_only':True,'all_trade_funding_finite':True}

def gates(m):
 return {'trades_gte_5':m['total_trades']>=5,'net_strictly_positive':m['net_profit_after_base_fees_pct']>0,'net_gte_1_25_pct':m['net_profit_after_base_fees_pct']>=1.25,'profit_factor_gte_1_10':m['profit_factor']>=1.10,'drawdown_lte_15_pct':m['max_drawdown_pct']<=15,'average_holding_gte_10080_minutes':m['average_holding_period_minutes']>=10080,'roi_exit_count_zero':m['roi_exit_count']==0}
results=[]
for a in api['attempts']:
 assert a['technical_status']=='VALID' and a['failure_reason'] is None
 c=candidates[a['candidate_id']];assert json.loads(c['metadata_json'])['review']['status']=='APPROVED'
 assert hashlib.sha256(c['code_text'].encode()).hexdigest()==c['code_sha256']==a['strategy_sha256']
 for key in ('archive','result'):
  e=a['evidence'][key];assert sha(s/e['path'])==e['sha256']
 result=load(s/a['evidence']['result']['path']);m=a['search_metrics'];assert result['exit_code']==0
 for k,v in m.items():assert result['net_profit_after_fees_pct' if k=='net_profit_after_base_fees_pct' else k]==v
 check=zipcheck(s/a['evidence']['archive']['path'],c['code_text'],a['class_name'],m);gg=gates(m);assert all(gg.values())
 results.append({'candidate_id':a['candidate_id'],'generation_id':c['generation_run_id'],'class_name':a['class_name'],'strategy_sha256':a['strategy_sha256'],'metrics':m,'gates':gg,'result_sha256':a['evidence']['result']['sha256'],**check})
assert results[1]['candidate_id']==candidates[results[1]['candidate_id']]['id'] and candidates[results[1]['candidate_id']]['parent_candidate_id']==results[0]['candidate_id']
assert api['attempts'][1]['changed_factor']=='stoploss'
finalist=terminal['search_finalist']['candidate_id'];assert finalist==results[0]['candidate_id']
assert dev['research_run_id']==rr['id']==ex['research_run_id']
assert rr['candidate_id']==dev['candidate_id']==finalist
assert rr['status']==dev['status']=='COMPLETED' and rr['verdict']==dev['verdict']=='REJECTED'
assert ex['scenario']=='DEVELOPMENT' and ex['status']==dev['development']['status']=='SUCCEEDED' and ex['return_code']==0 and ex['scenario_passed']==0
assert ex['fee_rate']==.0005 and ex['fee_multiplier']==1
snapshot=json.loads(rr['input_snapshot_json']);binding=snapshot['search_finalist_binding']
for k,v in projection['finalist_binding'].items():assert binding[k]==v
assert binding['search_generation_id']==terminal['campaign_id'] and binding['candidate_id']==finalist
assert snapshot['timerange']=='20250201-20260201' and snapshot['exclusive_stop_utc']=='2026-02-01T00:00:00Z'
assert json.loads(rr['checks_json'])==dev['checks'] and json.loads(rr['rejection_reasons_json'])==dev['rejection_reasons']
assert dev['checks']['next_phase']=='NONE_REJECTED'
assert dev['holdout']==dev['holdout_stress']=={'execution_rows':0,'status':'SEALED_UNREAD'}
for k in ('total_trades','profit_pct','profit_factor','max_drawdown_pct','win_rate'):assert ex[k]==dev['development'][k]
assert sha(Path(ex['result_archive_path']))==dev['development']['artifact_sha256']
c=candidates[finalist];check=zipcheck(Path(ex['result_archive_path']),c['code_text'],c['class_name'],dev['development']);gg=gates(dev['development'])
assert {k for k,v in gg.items() if not v}=={'net_strictly_positive','net_gte_1_25_pct','profit_factor_gte_1_10'}
for relative,h in snapshot['materialized_input_hashes'].items():assert sha(Path(rr['run_dir'])/'development-input'/relative)==h
head=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip();dirty=subprocess.check_output(['git','status','--porcelain=v1'],text=True).strip();remote=subprocess.check_output(['git','ls-remote','origin','refs/heads/main'],text=True).split()[0]
assert not dirty and head==remote=='dc82c61fe8a27a654977344755c088412518d858'
source=load(r/'source-verification.json')
assert len(source['formal_matches_precheck'])==25
assert sha(r/'source-acquisition/retained-data-provenance.json')==source['source_provenance_sha256'] and sha(r/'source-acquisition/retrieval_receipt.json')==source['source_receipt_sha256']
report={'status':'DEVELOPMENT_REJECTED','attribution':'DEVELOPMENT_ECONOMIC_GATE_FAILURE','issue':64,'root':str(r),'root_mode':oct(r.stat().st_mode&0o777),'head':head,'live_main':remote,'dirty':False,'profile_id':'bch-exact-grid-dual-sma-10-30-v1','campaign_id':terminal['campaign_id'],'search_status':terminal['status'],'finalist_candidate_id':finalist,'generations':generations,'table_counts':counts,'search_results':results,'terminal_sha256':sha(s/'search-terminal.json'),'trials_sha256':sha(s/'trials.jsonl'),'research_run_id':rr['id'],'execution_id':ex['id'],'development':{'status':'REJECTED','technical_status':'SUCCEEDED','metrics':dev['development'],'gates':gg,'rejection_reasons':dev['rejection_reasons'],**check},'source_provenance_sha256':source['source_provenance_sha256'],'source_receipt_sha256':source['source_receipt_sha256'],'holdout_status':'SEALED_UNREAD','holdout_stress_status':'SEALED_UNREAD','slippage':'UNKNOWN','service_tier':'UNKNOWN','live_page_observed':{'url':'http://127.0.0.1:49240/console','search_status':'SEARCH_FINALIST_FROZEN','attempts':2,'finalist':finalist,'round_1_button_disabled':True,'round_2_button_disabled':True,'development_verdict':'REJECTED','holdout_button_disabled':True,'generic_r2_development_ready':'PRESENT_NOT_FINALIST_EVIDENCE','frequi':'UNAVAILABLE'},'verification':'Exact six tables; CODEX generations/Candidates; native MANUAL Search projection verified; same-campaign API/terminal/trials/ZIP and finalist->Dev binding/DB/ZIP/cost fields reconcile. No H/Stress/Release executions.'}
report['attribution_detail']='交易数达到冻结门槛，但独立 Development 窗口经济表现未达标。净损益为 −4.44077628 USDT；funding_fees 合计 +1.3588392277144117，为资金费净收款，不能将失败归因为资金费拖累。退出构成为7次 exit_signal、1次 stop_loss；未证明特定市场状态或参数导致失败。'
(r/'final-audit.json').write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n')
print(json.dumps({'status':report['status'],'counts':counts,'search_funding':[x['funding_fees_sum'] for x in results],'development_funding':check['funding_fees_sum'],'development_failures':dev['rejection_reasons'],'head':head},ensure_ascii=False))
