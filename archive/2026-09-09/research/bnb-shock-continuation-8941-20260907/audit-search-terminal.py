"""Review the single existing native artifact; never execute a strategy."""
from pathlib import Path
from datetime import datetime, timezone
import json, zipfile, hashlib, math, urllib.request, sys
sys.path.insert(0, '/Users/shenjianpeng/.codex/worktrees/8941/freqtrade-lab')
from lab.database import get_connection
from lab.bounded_research import canonical
from lab.futures_costs import validate_audit

r = Path(__file__).parent
campaign = r/'search-campaign'
context = json.load(urllib.request.urlopen('http://127.0.0.1:8801/api/search/context'))
assert context['state']['status'] in ('SEARCH_FINALIST_FROZEN','SEARCH_TERMINATED_NO_FINALIST')
assert context['state']['budget']['consumed_total'] == 1
attempt = context['generation_run']['evidence']['attempts'][0]
sha = lambda b: hashlib.sha256(b).hexdigest()
archive = campaign/attempt['evidence']['archive']['path']
assert sha(archive.read_bytes()) == attempt['evidence']['archive']['sha256']
result_path = campaign/attempt['evidence']['result']['path']
assert sha(result_path.read_bytes()) == attempt['evidence']['result']['sha256']
result = json.loads(result_path.read_bytes())
assert result['technical_status'] == 'VALID'
with zipfile.ZipFile(archive) as z:
    names = [n for n in z.namelist() if n.endswith('.json') and not n.endswith('_config.json')]
    assert len(names) == 1
    report = json.loads(z.read(names[0]))['strategy']['BnbDailyShockContinuation48H']
    embedded = [n for n in z.namelist() if n.endswith('_BnbDailyShockContinuation48H.py')]
    assert len(embedded) == 1 and sha(z.read(embedded[0])) == sha((r/'BnbDailyShockContinuation48H.py').read_bytes())
trades = report['trades']
audit = validate_audit(result['funding_audit'],report['profit_total']*100,1000,len(trades))
effective = [t for t in trades if t['trade_duration']>=1440 and t['exit_reason'] in ('exit_signal','stop_loss')]
blocks = ['2023-11-06','2024-02-05','2024-05-06','2024-08-05','2024-11-04']
block_report=[]
details=[]
for t,a in zip(trades,audit['trade_adjustments'],strict=True):
    assert t['open_date']==a['open_date'] and t['close_date']==a['close_date']
    assert t['leverage']==1 and t['fee_open']==.001 and t['fee_close']==.001
    price = t['amount']*(t['close_rate']-t['open_rate'])*(-1 if t['is_short'] else 1)
    fee = t['amount']*(t['open_rate']*t['fee_open']+t['close_rate']*t['fee_close'])
    predicted = price-fee+t['funding_fees']
    assert math.isclose(predicted,t['profit_abs'],abs_tol=1e-7)
    details.append({'open_date':t['open_date'],'close_date':t['close_date'],'direction':'SHORT' if t['is_short'] else 'LONG',
                    'duration_minutes':t['trade_duration'],'exit_reason':t['exit_reason'],'effective_natural_sample':t in effective,
                    'price_gross_usdt':price,'native_fee_usdt':fee,'fee_assumption_usdt':fee/2,'slippage_proxy_usdt':fee/2,
                    'native_funding_usdt':t['funding_fees'],'native_net_usdt':t['profit_abs'],
                    'additional_funding_deduction_usdt':a['funding_deduction_abs'],'conservative_net_usdt':a['conservative_profit_abs']})
for lo,hi in zip(blocks,blocks[1:]):
    rows=[d for d in details if lo<=d['open_date'][:10]<hi]
    block_report.append({'start':lo,'end_exclusive':hi,'trades_by_entry':len(rows),'effective_natural_trades':sum(d['effective_natural_sample'] for d in rows),
                         'conservative_realized_trade_sum_usdt':math.fsum(d['conservative_net_usdt'] for d in rows),'interpretation':'Entry-assigned trade PnL, not block MTM return'})
totals={k:math.fsum(d[k] for d in details) for k in ['price_gross_usdt','native_fee_usdt','fee_assumption_usdt','slippage_proxy_usdt','native_funding_usdt','native_net_usdt','additional_funding_deduction_usdt','conservative_net_usdt']}
assert math.isclose(totals['native_net_usdt'],report['profit_total_abs'],abs_tol=1e-7)
assert math.isclose(totals['conservative_net_usdt'],audit['conservative_final_balance']-1000,abs_tol=1e-7)
without_best = totals['conservative_net_usdt']-max(0,max((d['conservative_net_usdt'] for d in details),default=0))
natural_longs=sum(not t['is_short'] for t in effective);natural_shorts=sum(t['is_short'] for t in effective)
checks=[]
def check(name,actual,threshold,passed):
    checks.append({'gate':name,'actual':actual,'frozen_requirement':threshold,'status':'PASSED' if passed else 'FAILED'})
check('core_total_trades',len(trades),'>=24',len(trades)>=24)
check('conservative_net_pct',audit['conservative_net_profit_pct'],'>=1.0',audit['conservative_net_profit_pct']>=1)
check('conservative_PF',audit['conservative_profit_factor'],'>=1.10',audit['conservative_profit_factor'] is not None and audit['conservative_profit_factor']>=1.1)
check('conservative_MTM_DD_pct',audit['conservative_mtm_drawdown_pct'],'<=10',audit['conservative_mtm_drawdown_pct']<=10)
check('native_DD_pct',result['max_drawdown_pct'],'<=10',result['max_drawdown_pct']<=10)
check('mean_holding_minutes',result['average_holding_period_minutes'],'>=1440',result['average_holding_period_minutes']>=1440)
check('ROI_exit_count',result['roi_exit_count'],'=0',result['roi_exit_count']==0)
check('cash',{'executable':audit['cash_executable'],'minimum_free_cash':audit['minimum_free_cash']},'executable and cash>=0',audit['cash_executable'] and audit['minimum_free_cash']>=0)
check('effective_natural_samples',len(effective),'>=24',len(effective)>=24)
check('effective_long_samples',natural_longs,'>=8',natural_longs>=8)
check('effective_short_samples',natural_shorts,'>=8',natural_shorts>=8)
active_blocks=sum(b['effective_natural_trades']>0 for b in block_report)
check('blocks_with_natural_sample',active_blocks,'=4 of4',active_blocks==4)
check('net_without_best_winner_usdt',without_best,'>0',without_best>0)
check('price_gross_usdt',totals['price_gross_usdt'],'>0',totals['price_gross_usdt']>0)
positive_blocks=[b['conservative_realized_trade_sum_usdt'] for b in block_report if b['conservative_realized_trade_sum_usdt']>0]
check('positive_blocks',len(positive_blocks),'>=3 of4',len(positive_blocks)>=3)
share=max(positive_blocks)/math.fsum(positive_blocks) if positive_blocks else None
check('maximum_positive_block_share',share,'<=0.60',share is not None and share<=.60)
c=get_connection(r/'lab.sqlite',read_only=True)
counts={t:c.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in ['research_profiles','generation_runs','candidates','research_runs','backtest_executions','releases']}
generation_rows=[dict(x) for x in c.execute('SELECT id,source,status,returned_strategy_count FROM generation_runs')]
c.close();assert counts=={'research_profiles':1,'generation_runs':2,'candidates':1,'research_runs':0,'backtest_executions':0,'releases':0}
out={'schema':'issue104-search-protocol-review-v1','reviewed_at_utc':datetime.now(timezone.utc).isoformat(),'project_status':context['state']['status'],
     'economic_classification':'SEARCH_POSITIVE_ONLY' if all(c['status']=='PASSED' for c in checks) else 'OUTER_PROTOCOL_REJECTED_NO_DEVELOPMENT','sample_classification':'MEETS_FROZEN_SAMPLE_GATE' if len(effective)>=24 and natural_longs>=8 and natural_shorts>=8 else 'UNDERPOWERED',
     'all_protocol_gates':'PASSED' if all(c['status']=='PASSED' for c in checks) else 'FAILED','actual_Search_attempts':1,'campaign_id':context['state']['campaign_id'],
     'candidate_id':attempt['candidate_id'],'protocol_sha256':sha((r/'final-protocol.md').read_bytes()),'strategy_sha256':attempt['strategy_sha256'],
     'archive':str(archive),'archive_sha256':sha(archive.read_bytes()),'native_metrics':{k:result[k] for k in ['total_trades','profit_pct','profit_factor','max_drawdown_pct','average_holding_period_minutes','roi_exit_count']},
     'conservative_audit':audit,'cost_decomposition':totals,'gates':checks,'blocks':block_report,'trade_details':details,'six_table_counts':counts,'generation_rows':generation_rows,
     'ResearchRun_id':None,'D':'QC_ONLY_NOT_EXECUTED','H_Stress':'OHLCV_SEALED_LIMITED_FUNDING_METADATA_QC','D_authorization':'NOT_GRANTED', 'no_further_Search_attempt':True,
     'configured_gross_label_note':'Project gross_profit_before_fees includes native funding; price_gross_usdt isolates price movement.',
     'supplemental_intrahour_stress_is_not_Holdout_Stress':True}
(r/'search-protocol-review.json').write_bytes(canonical(out))
(r/'search-context-terminal.json').write_bytes(canonical(context))
print(json.dumps({'cost_decomposition':totals,'gates':checks,'blocks':block_report,'six_table_counts':counts,'generation_rows':generation_rows},ensure_ascii=False))
