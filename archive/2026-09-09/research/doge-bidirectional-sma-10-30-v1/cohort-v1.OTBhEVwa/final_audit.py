"""Reconcile this cohort's actual native outputs; no experiments or market acquisition."""
import ast,hashlib,json,math,zipfile,subprocess
from pathlib import Path
from collections import Counter
from lab.database import get_connection
from lab.bounded_research import verify_search_terminal_projection
r=Path(__file__).resolve().parent;s=r/'search-data'
def load(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def same(a,b):assert math.isclose(a,b,rel_tol=1e-8,abs_tol=1e-6),(a,b)
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
def gates(m):
 return {'trades_gte_5':m['total_trades']>=5,'net_strictly_positive':m['net_profit_after_base_fees_pct']>0,'net_gte_1_25_pct':m['net_profit_after_base_fees_pct']>=1.25,'profit_factor_gte_1_10':m['profit_factor']>=1.10,'drawdown_lte_15_pct':m['max_drawdown_pct']<=15,'average_holding_gte_10080_minutes':m['average_holding_period_minutes']>=10080,'roi_exit_count_zero':m['roi_exit_count']==0}
def zipcheck(path,c,m,phase):
 with zipfile.ZipFile(path) as z:
  docs=[json.loads(z.read(n)) for n in z.namelist() if n.endswith('.json') and not n.endswith('_config.json')]
  report=next(x for x in docs if 'strategy' in x);strategy=report['strategy'][c['class_name']]
  py=[n for n in z.namelist() if n.endswith('.py')];assert len(py)==1 and z.read(py[0]).decode()==c['code_text']
  trades=strategy['trades'];assert len(trades)==strategy['total_trades']==m['total_trades']
  same(strategy['profit_total']*100,m['net_profit_after_base_fees_pct']);same(strategy['profit_factor'],m['profit_factor']);same(strategy['max_drawdown_account']*100,m['max_drawdown_pct'])
  same(sum(t['trade_duration'] for t in trades)/len(trades),m['average_holding_period_minutes'])
  start,end=(1706745600000,1738368000000) if phase=='Search' else (1738368000000,1769904000000)
  for t in trades:
   assert math.isfinite(t['funding_fees']) and t['fee_open']==t['fee_close']==.0005 and t['leverage']==1 and isinstance(t['is_short'],bool)
   assert t['pair']=='DOGE/USDT:USDT' and not t['is_open']
   assert start<=t['open_timestamp']<t['close_timestamp']<end
   same((t['close_timestamp']-t['open_timestamp'])/60000,t['trade_duration'])
   fee=t['amount']*(t['open_rate']*t['fee_open']+t['close_rate']*t['fee_close'])
   gross=t['amount']*(t['open_rate']-t['close_rate'] if t['is_short'] else t['close_rate']-t['open_rate'])
   same(gross-fee+t['funding_fees'],t['profit_abs'])
  total_fee=sum(t['amount']*(t['open_rate']*t['fee_open']+t['close_rate']*t['fee_close']) for t in trades)
  same(sum(t['profit_abs'] for t in trades),strategy['profit_total_abs'])
  if 'configured_fee_cost_pct' in m:same(total_fee/1000*100,m['configured_fee_cost_pct'])
  directions={}
  for short,label in [(False,'long'),(True,'short')]:
   group=[t for t in trades if t['is_short']==short]
   n=len(group);pnl=sum(t['profit_abs'] for t in group)
   assert n==strategy['trade_count_'+label];same(pnl,strategy['profit_total_'+label+'_abs'])
   directions[label]={'trades':n,'net_pnl_usdt':pnl,'funding_usdt':sum(t['funding_fees'] for t in group),'fees_usdt':sum(t['amount']*(t['open_rate']*t['fee_open']+t['close_rate']*t['fee_close']) for t in group)}
  exits=dict(Counter(t['exit_reason'] for t in trades));assert exits.get('roi',0)==m['roi_exit_count']==0
  return {'archive_path':str(path),'archive_sha256':sha(path),'total_net_pnl_usdt':strategy['profit_total_abs'],'funding_net_usdt':sum(t['funding_fees'] for t in trades),'configured_fees_usdt':total_fee,'directions':directions,'exit_reasons':exits,'fee_each_side':.0005,'leverage':1,'pnl_equation_checked':'directional_price_pnl - configured_fees + signed_funding = net_pnl','slippage':'UNKNOWN'}
results=[]
for a in api['attempts']:
 assert a['technical_status']=='VALID' and a['failure_reason'] is None
 c=candidates[a['candidate_id']];assert json.loads(c['metadata_json'])['review']['status']=='APPROVED'
 assert hashlib.sha256(c['code_text'].encode()).hexdigest()==c['code_sha256']==a['strategy_sha256']
 for key in ('archive','result'):
  e=a['evidence'][key];assert sha(s/e['path'])==e['sha256']
 result=load(s/a['evidence']['result']['path']);m=a['search_metrics'];assert result['exit_code']==0
 for k,v in m.items():assert result['net_profit_after_fees_pct' if k=='net_profit_after_base_fees_pct' else k]==v
 check=zipcheck(s/a['evidence']['archive']['path'],c,m,'Search');gg=gates(m);assert all(gg.values())
 results.append({'candidate_id':c['id'],'generation_id':c['generation_run_id'],'class_name':c['class_name'],'strategy_sha256':c['code_sha256'],'technical_status':'VALID','metrics':m,'gates':gg,'failures':[],**check})
assert candidates[results[1]['candidate_id']]['parent_candidate_id']==results[0]['candidate_id'] and api['attempts'][1]['changed_factor']=='stoploss'
finalist=terminal['search_finalist']['candidate_id'];assert finalist==results[1]['candidate_id']
assert dev['research_run_id']==rr['id']==ex['research_run_id'] and rr['candidate_id']==dev['candidate_id']==finalist
assert rr['status']==dev['status']=='COMPLETED'
assert ex['scenario']=='DEVELOPMENT' and ex['status']==dev['development']['status']=='SUCCEEDED' and ex['return_code']==0
assert ex['fee_rate']==.0005 and ex['fee_multiplier']==1
snapshot=json.loads(rr['input_snapshot_json']);binding=snapshot['search_finalist_binding']
for k,v in projection['finalist_binding'].items():assert binding[k]==v
assert binding['search_generation_id']==terminal['campaign_id'] and binding['candidate_id']==finalist
assert snapshot['timerange']=='20250201-20260201' and snapshot['exclusive_stop_utc']=='2026-02-01T00:00:00Z'
assert json.loads(rr['checks_json'])==dev['checks'] and json.loads(rr['rejection_reasons_json'])==dev['rejection_reasons']
assert dev['holdout']==dev['holdout_stress']=={'execution_rows':0,'status':'SEALED_UNREAD'}
for k in ('total_trades','profit_pct','profit_factor','max_drawdown_pct','win_rate'):assert ex[k]==dev['development'][k]
assert sha(Path(ex['result_archive_path']))==dev['development']['artifact_sha256']
dc=zipcheck(Path(ex['result_archive_path']),candidates[finalist],dev['development'],'Development');dg=gates(dev['development']);passed=all(dg.values());assert bool(ex['scenario_passed'])==passed
if not passed:assert dev['verdict']==rr['verdict']=='REJECTED' and dev['checks']['next_phase']=='NONE_REJECTED'
for relative,h in snapshot['materialized_input_hashes'].items():assert sha(Path(rr['run_dir'])/'development-input'/relative)==h
head=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip();dirty=subprocess.check_output(['git','status','--porcelain=v1'],text=True).strip();remote=subprocess.check_output(['git','ls-remote','origin','refs/heads/main'],text=True).split()[0]
assert not dirty and head==remote=='dc82c61fe8a27a654977344755c088412518d858'
source=load(r/'source-verification.json');assert len(source['formal_matches_precheck'])==25
assert sha(r/'source-acquisition/retained-data-provenance.json')==source['source_provenance_sha256'] and sha(r/'source-acquisition/retrieval_receipt.json')==source['source_receipt_sha256']
report={'status':'HOLDOUT_AUTHORIZATION_REQUIRED' if passed else 'DEVELOPMENT_REJECTED','issue':65,'root':str(r),'head':head,'live_main':remote,'dirty':False,'profile_id':'doge-bidirectional-sma-10-30-v1','campaign_id':terminal['campaign_id'],'search_status':terminal['status'],'finalist_candidate_id':finalist,'generations':generations,'table_counts':counts,'actual_search_trials':2,'actual_development_trials':1,'search_results':results,'terminal_sha256':sha(s/'search-terminal.json'),'trials_sha256':sha(s/'trials.jsonl'),'research_run_id':rr['id'],'execution_id':ex['id'],'development':{'verdict':dev['verdict'],'technical_status':'SUCCEEDED','metrics':dev['development'],'gates':dg,'rejection_reasons':dev['rejection_reasons'],**dc},'source_provenance_sha256':source['source_provenance_sha256'],'source_receipt_sha256':source['source_receipt_sha256'],'holdout':'SEALED_UNREAD','stress':'SEALED_UNREAD','holdout_executions':0,'stress_executions':0,'service_tier':'UNKNOWN','frequi':'UNAVAILABLE','protocol_exception':(r/'protocol-exception.md').read_text(),'route_action':'Await separate one-shot H/Stress authorization' if passed else 'RETIRE_SIMPLE_DUAL_SMA_ROUTE; supervisor chooses different mechanism','selection_risk':'Same calendar cross-asset samples correlated, not statistical independence. At least six Search trials across LTC/BCH/DOGE route; prior broader cumulative trials not fully enumerated. No BCH repair/superiority or causal direction comparison established.'}
(r/'final-audit.json').write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n')
print(json.dumps(report,ensure_ascii=False))
