"""One-off S-only arithmetic from the sole native ZIP; never runs a backtest."""
import hashlib
import json
import zipfile
from decimal import Decimal
from pathlib import Path
from datetime import datetime, timedelta, timezone

ROOT = Path(__file__).resolve().parent
D = lambda value: Decimal(str(value))
archive = ROOT / 'search/search-results-round-1/d41d96ff-81df-4fdf-8d97-404a42d00f01/raw/backtest-result-2026-09-06_03-32-57.zip'
assert hashlib.sha256(archive.read_bytes()).hexdigest() == '5dc143f4f192c33d38de26de9f037b1018a0381f288671eaa7858822b5c86008'
with zipfile.ZipFile(archive) as z:
    report = json.loads(z.read(archive.stem + '.json'))['strategy']['XlmSpotSma90']
    config = json.loads(z.read(archive.stem + '_config.json'))
assert report['timerange'] == '20210501-20230101'
assert report['stake_amount'] == 500 and report['starting_balance'] == 1000
assert report['trading_mode'] == 'spot' and report['timeframe'] == '1d'
assert report['minimal_roi'] == {} and report['stoploss'] == -.2
assert config.get('amend_last_stake_amount', False) is False
trades = sorted(report['trades'], key=lambda t:(t['open_timestamp'],t['close_timestamp']))
stop = datetime(2023,1,1,tzinfo=timezone.utc)
native_total = sum((D(t['profit_abs']) for t in trades), D(0))
legs_total = D(0)
audited = []
cash = dict(native=D(1000), base=D(1000), sensitivity=D(1000))
violations = dict(native=[], base=[], sensitivity=[])
previous_exit = 0
rounding_difference = D(0)
for index,t in enumerate(trades,1):
    assert t['open_timestamp'] >= previous_exit
    previous_exit = t['close_timestamp']
    assert not t['is_short'] and t['leverage'] == 1 and not t['is_open']
    assert t['fee_open'] == t['fee_close'] == .001
    orders = t['orders']
    assert len(orders) == 2 and orders[0]['ft_is_entry'] and not orders[1]['ft_is_entry']
    assert orders[0]['ft_order_side'] == 'buy' and orders[1]['ft_order_side'] == 'sell'
    entry = D(orders[0]['amount'])*D(orders[0]['safe_price'])
    exit_value = D(orders[1]['amount'])*D(orders[1]['safe_price'])
    assert D(orders[0]['amount']) == D(orders[1]['amount']) == D(t['amount'])
    assert abs(entry-D(500)) < D('.001')
    legs = entry + exit_value
    legs_total += legs
    computed = exit_value-entry-legs*D('.001')
    rounding_difference += computed-D(t['profit_abs'])
    row = {'number':index,'entry_timestamp':t['open_timestamp'],'exit_timestamp':t['close_timestamp'],
           'exit_reason':t['exit_reason'],'entry_notional':str(entry),'exit_notional':str(exit_value),
           'native_profit':str(D(t['profit_abs'])),'base_profit':str(D(t['profit_abs'])-legs*D('.001')),
           'sensitivity_path_estimate_profit':str(D(t['profit_abs'])-legs*D('.003'))}
    for scenario,rate in [('native',D('.001')),('base',D('.002')),('sensitivity',D('.004'))]:
        if cash[scenario]*D('.99') < D(500) or cash[scenario] < entry*(1+rate):
            violations[scenario].append({'trade_number':index,'cash_before':str(cash[scenario])})
        cash[scenario] -= entry*(1+rate)
        cash[scenario] += exit_value*(1-rate)
    audited.append(row)
assert abs(rounding_difference) < D('.000001')
assert abs(native_total-D(report['profit_total_abs'])) < D('.000001')

groups=[]
for t,row in zip(trades,audited):
    entry=datetime.fromtimestamp(t['open_timestamp']/1000,timezone.utc)
    exit_time=datetime.fromtimestamp(t['close_timestamp']/1000,timezone.utc)
    natural=t['exit_reason']!='force_exit' and exit_time<stop
    if not groups or entry>=groups[-1]['end']:
        groups.append({'start':entry,'end':entry+timedelta(days=90),'natural':0,'trades':[],
                       'base':D(0),'sensitivity':D(0)})
    g=groups[-1];g['end']=max(g['end'],exit_time);g['natural']+=int(natural);g['trades'].append(row['number'])
    g['base']+=D(row['base_profit']);g['sensitivity']+=D(row['sensitivity_path_estimate_profit'])
complete=sum(g['end']<=stop and g['natural']>0 for g in groups)
base = native_total-legs_total*D('.001')
sensitivity = native_total-legs_total*D('.003')
result={'schema':'issue90-s-only-economic-audit-v1','actual_campaign_id':'d381227c-eb46-4e14-8fb4-4fb45241924b',
    'archive_sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),
    'technical_status':'VALID','decision':'SEARCH_TERMINATED_NO_FINALIST',
    'hard_failures':['NEGATIVE_NATIVE_NET','NEGATIVE_BASE_COST_NET','NEGATIVE_SENSITIVITY_PATH_ESTIMATE','NATIVE_DRAWDOWN_ABOVE_20_PERCENT'],
    'native_profit_usdt':str(native_total),'native_profit_pct':report['profit_total']*100,
    'native_max_drawdown_pct':report['max_drawdown_account']*100,'native_profit_factor':report['profit_factor'],
    'total_leg_notional':str(legs_total),'base_additional_slippage':str(legs_total*D('.001')),
    'base_net_usdt':str(base),'sensitivity_extra_fee_plus_slippage':str(legs_total*D('.003')),
    'sensitivity_same_path_net_estimate_usdt':str(sensitivity),
    'native_fee_not_double_counted':True,'rounding_reconciliation_error':str(rounding_difference),
    'final_cash_by_cost_scenario':{k:str(v) for k,v in cash.items()},'entry_cash_violations':violations,
    'fixed_stake_no_resize_verified':True,'native_rejected_signals':report['rejected_signals'],
    'cash_interpretation':'Sensitivity is a fixed-native-path arithmetic estimate, not a new native run. If entry_cash_violations is nonempty that scenario cannot claim executable path returns.',
    'natural_completed_trades':sum(g['natural'] for g in groups),'complete_90d_groups':complete,
    'required_natural_trades':6,'required_groups':4,
    'base_after_removing_best_group':str(base-max(g['base'] for g in groups)),
    'sensitivity_after_removing_best_group':str(sensitivity-max(g['sensitivity'] for g in groups)),
    'groups':[dict(start=g['start'].isoformat(),end=g['end'].isoformat(),natural=g['natural'],trades=g['trades'],base_profit=str(g['base']),sensitivity_profit=str(g['sensitivity'])) for g in groups],
    'daily_cost_adjusted_mtm_drawdown':None,'daily_mtm_status':'NOT_COMPUTED_AFTER_DECISIVE_ECONOMIC_AND_NATIVE_RISK_FAILURE',
    'buy_hold_benchmark':None,'benchmark_status':'NOT_COMPUTED_DIAGNOSTIC_ONLY_NO_PROMOTION_GATE',
    'development':'SEALED_UNREAD','holdout':'SEALED_UNREAD','holdout_stress':'SEALED_UNREAD',
    'native_search_calls':1,'replay_calls':0,'trade_audit':audited}
with (ROOT/'search-economic-audit.json').open('x') as f:
    json.dump(result,f,indent=2,sort_keys=True)
print(json.dumps({k:v for k,v in result.items() if k not in {'groups','trade_audit'}},sort_keys=True))
