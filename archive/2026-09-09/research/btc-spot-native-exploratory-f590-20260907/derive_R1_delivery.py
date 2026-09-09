import hashlib
import http.client
import json
import zipfile
from collections import Counter
from initialize_and_synthetic_once import ROOT, append, put
from lab.database import get_connection

api=json.loads((ROOT/'R1-final-api.json').read_text())
assert api['research_mode']=='EXPLORATORY' and api['validation_status']=='NOT_INDEPENDENTLY_VALIDATED'
assert len(api['attempts'])==1
attempt=api['attempts'][0]
archive=ROOT/'search-data-01'/attempt['evidence']['archive']['path']
digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
assert digest(archive)==attempt['evidence']['archive']['sha256']
with zipfile.ZipFile(archive) as z:
    name=next(n for n in z.namelist() if n.endswith('.json') and '_config' not in n)
    result=json.loads(z.read(name))['strategy']['BtcWeeklyMomentumFixedStake']
trades=result['trades']
assert len(trades)==7
assert all(t['pair']=='BTC/USDT' and not t['is_short'] and t['leverage']==1 and t['fee_open']==t['fee_close']==0.0012 for t in trades)
fees=sum(t['amount']*(t['open_rate']*t['fee_open']+t['close_rate']*t['fee_close']) for t in trades)
gross=sum(t['amount']*(t['close_rate']-t['open_rate']) for t in trades)
net=sum(t['profit_abs'] for t in trades)
assert abs(gross-fees-net)<1e-5
assert abs(result['final_balance']-1000-net)<1e-5
blocks=[]
for lo,hi in [('2024-01-30','2024-04-01'),('2024-04-01','2024-07-01'),('2024-07-01','2024-10-01'),('2024-10-01','2024-12-31')]:
    selected=[t for t in trades if lo<=t['close_date'][:10]<hi]
    blocks.append({'start_utc_date':lo,'end_exclusive_utc_date':hi,'closed_trade_count':len(selected),'realized_net_usdt':sum(t['profit_abs'] for t in selected)})
assert abs(sum(b['realized_net_usdt'] for b in blocks)-net)<1e-5
exits=Counter(t['exit_reason'] for t in trades)
native_dd=result['max_drawdown_account']*100
gates={'minimum_6_trades':len(trades)>=6,'minimum_net_1_usdt':net>=1,'minimum_pf_1_05':result['profit_factor']>=1.05,'native_dd_maximum_10_pct':native_dd<=10,'roi_exits_zero':exits.get('roi',0)==0,'long_only_1x_fee_binding':True}
economic={'gross_price_profit_usdt':gross,'proxy_fee_cost_usdt':fees,'net_profit_usdt':net,'starting_wallet_usdt':1000,'ending_wallet_usdt':result['final_balance'],
    'wallet_net_pct':net/1000*100,'configured_fixed_stake_usdt':250,'net_divided_by_configured_stake_pct':net/250*100,
    'stake_ratio_warning':'Nominal fixed-stake denominator only, not compounded/annualized/investor return',
    'actual_stake_min':min(t['stake_amount'] for t in trades),'actual_stake_max':max(t['stake_amount'] for t in trades),
    'trades':len(trades),'native_profit_factor':result['profit_factor'],'native_project_summary_DD_pct':native_dd,
    'native_wallet_daily_open_snapshot_DD_pct':result['wallet_stats']['max_drawdown_account']*100,
    'wallet_DD_semantics':'Native pre-trade wallet snapshots: quote at rate 1, BTC at daily open; rate*balance grouped by date. Not independent daily-close or intraday worst-case MTM.',
    'independently_verified_MTM_DD_pct':None,'independent_MTM_status':'UNKNOWN_NOT_COMPUTED',
    'average_holding_minutes':sum(t['trade_duration'] for t in trades)/len(trades),
    'exit_signal_count':exits.get('exit_signal',0),'stop_loss_count':exits.get('stop_loss',0),'force_exit_count':exits.get('force_exit',0),'roi_exit_count':exits.get('roi',0),
    'rejected_signals':result['rejected_signals'],'first_entry_utc':trades[0]['open_date'],'last_exit_utc':trades[-1]['close_date'],
    'quarterly_close_date_realized_blocks':blocks,'block_warning':'NOT_MTM. Zero realized closes in first block does not mean zero portfolio return or no exposure.',
    'frozen_exploratory_continuation_gates':gates,'all_frozen_gates_passed':all(gates.values()),'qualification':'NOT_INDEPENDENTLY_VALIDATED'}
put('R1-economic-audit.json',economic)
con=get_connection(ROOT/'lab.sqlite',read_only=True)
try:
    counts={t:con.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in ['research_profiles','generation_runs','candidates','research_runs','backtest_executions','releases']}
finally:
    con.close()
checks=[]
for path in ['/console','/api/generations/deb82d87-e88c-41c0-8ad1-0900b308ddaa','/api/search-campaigns/4e5bbbca-0f16-4205-9827-6795a27521f9']:
    c=http.client.HTTPConnection('127.0.0.1',53251,timeout=10);c.request('GET',path);response=c.getresponse();raw=response.read()
    checks.append({'path':path,'http_status':response.status,'response_sha256':hashlib.sha256(raw).hexdigest()});c.close()
delivery={'status':'EXPLORATORY_R1_PARENT_READY_NOT_FINALIST','project_status':api['status'],'validation_status':api['validation_status'],
    'generation_id':'deb82d87-e88c-41c0-8ad1-0900b308ddaa','candidate_id':'f23f7e42-4975-4607-aa37-770fc9139503','search_campaign_id':api['campaign_id'],
    'database':str(ROOT/'lab.sqlite'),'profile_id':'btc-spot-native-exploratory-f590-v1','database_counts':counts,
    'source_provenance_sha256':digest(ROOT/'source-2024-01/retained-data-provenance.json'),
    'source_receipt_sha256':digest(ROOT/'source-2024-01/retrieval_receipt.json'),
    'prepared_search_provenance_sha256':digest(ROOT/'search-data-01/acquisition/retained-data-provenance.json'),
    'candidate_derived_provenance_sha256':digest(archive.parent.parent/'retained-data-provenance.json'),
    'archive':str(archive),'archive_sha256':digest(archive),'result_sha256':digest(archive.parent.parent/'result.json'),
    'economic_audit_sha256':digest(ROOT/'R1-economic-audit.json'),
    'calls':{'synthetic_process_invocations':2,'synthetic_slots_consumed':2,'synthetic_actual_Backtesting_start':1,'capture_invocations':1,'market_HTTP_GETs':5,'Generation_invocations':1,'R1_market_native':1,'R2':0,'benchmark':0,'market_smoke':0,'D':0,'H':0,'Stress':0},
    'remaining_authorized_market_calls':0,'framework_budget_remaining_not_authorization':api['budget']['remaining'],
    'search_finalist':api['search_finalist'],'page':'http://127.0.0.1:53251/console','http_checks':checks,
    'no_independent_validation_claim':True,'economic_summary':economic,
    'operational_note':'Workflow stopped; Console remains running for read-only review. Initial orchestration path assertion corrected before Console/Generation; no extra market call.'}
put('R1-final-delivery-receipt.json',delivery)
ledger=append({'record_type':'OBSERVED_EXPLORATORY_R1_DELIVERY','status':delivery['status'],'project_status':api['status'],
    'generation_id':delivery['generation_id'],'candidate_id':delivery['candidate_id'],'search_campaign_id':api['campaign_id'],
    'final_receipt_path':str(ROOT/'R1-final-delivery-receipt.json'),'final_receipt_sha256':digest(ROOT/'R1-final-delivery-receipt.json'),
    'source_sha256':delivery['prepared_search_provenance_sha256'],'archive_sha256':delivery['archive_sha256'],
    'economic_result':{'gross_usdt':gross,'proxy_cost_usdt':fees,'net_usdt':net,'trades':len(trades),'native_DD_pct':native_dd,'native_daily_open_wallet_DD_pct':economic['native_wallet_daily_open_snapshot_DD_pct']},
    'calls':delivery['calls'],'remaining_authorized_market_calls':0,'R1_not_independent':True},'5c138aa9e6328ad968f90c56dbfb5c20484f7881edc799456d1b17f9c01fa553')
put('R1-final-ledger-receipt.json',ledger)
print(json.dumps({'delivery_sha256':digest(ROOT/'R1-final-delivery-receipt.json'),'economic_audit_sha256':digest(ROOT/'R1-economic-audit.json'),'ledger':ledger,'economic':economic},indent=2))
