"""Frozen Issue 85 same-artifact Search review; never executes a strategy."""
from pathlib import Path
import hashlib
import json
import math
import zipfile
import numpy as np
import pandas as pd

R = Path(__file__).resolve().parent
campaign = R / 'search-campaign'
state = json.loads((R / 'search-console-receipt.json').read_text())['state']
attempt = state['attempts'][0]
archive = campaign / attempt['evidence']['archive']['path']
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
assert sha(archive) == attempt['evidence']['archive']['sha256']
assert sha(R / 'proposal.md') == '7fe54097e1126c4f31ebc1cb76500a8e34bc45eec98eee1803829c19394052e2'
with zipfile.ZipFile(archive) as z:
    report = json.loads(z.read(next(n for n in z.namelist() if n.endswith('.json') and not n.endswith('_config.json'))))['strategy']['WeeklySpotMomentum']
trades = sorted(report['trades'], key=lambda t: t['open_timestamp'])
start, end = pd.Timestamp('2024-01-01T00:00Z'), pd.Timestamp('2025-01-01T00:00Z')
data = campaign / 'acquisition/data/okx/ETC_USDT-1d.feather'
frame = pd.read_feather(data).set_index('date')
frame = frame.loc[(frame.index >= start) & (frame.index < end)]
assert len(frame) == 366 and len(trades) == report['total_trades']
assert frame.index.is_unique and frame.index.to_series().diff().dropna().eq(pd.Timedelta(days=1)).all()
events, profits, active_months = [], [], set()
previous_close = start
for t in trades:
    opened, closed = pd.Timestamp(t['open_date']), pd.Timestamp(t['close_date'])
    assert start <= opened <= closed < end and opened >= previous_close
    assert opened.dayofweek == 1 and opened.hour == opened.minute == opened.second == 0
    assert t['pair'] == 'ETC/USDT' and t['is_short'] is False and t['leverage'] == 1 and not t['is_open']
    assert t['funding_fees'] in (None, 0) and t['fee_open'] == t['fee_close'] == .001
    assert t['exit_reason'] in ('exit_signal', 'stop_loss', 'force_exit')
    if t['exit_reason'] == 'exit_signal':
        assert closed.dayofweek == 5 and closed - opened == pd.Timedelta(days=4)
    quantity, entry, exit_ = t['amount'], t['open_rate'], t['close_rate']
    assert all(math.isfinite(x) and x > 0 for x in (quantity, entry, exit_))
    gross = quantity * (exit_ - entry)
    notional = quantity * (entry + exit_)
    assert abs(t['profit_abs'] - (gross - notional * .001)) < 1e-5
    profits.append({'gross': gross, 'base_fee': notional*.001, 'normal': gross-notional*.0015, 'sensitive': gross-notional*.003})
    events.extend([(opened, 1, quantity, entry), (closed, -1, quantity, exit_)])
    for date in pd.date_range(opened.normalize(), closed.normalize(), freq='D'):
        if date < closed or opened == closed:
            active_months.add(date.strftime('%Y-%m'))
    previous_close = closed
# Python's stable sort preserves entry before exit for same-trade same-time stops,
# and preceding trade exit before a later entry at the same timestamp.
events.sort(key=lambda e: e[0])
def equity_curve(cost):
    cash, quantity, i, equity, minimum_cash = 1000., 0., 0, [], 1000.
    for date, row in frame.iterrows():
        while i < len(events) and events[i][0] < date + pd.Timedelta(days=1):
            _, side, amount, price = events[i]
            cash += (-amount*price*(1+cost) if side == 1 else amount*price*(1-cost))
            quantity += side*amount
            assert quantity >= -1e-8
            minimum_cash = min(minimum_cash, cash)
            i += 1
        equity.append(cash + quantity*row['close'])
    assert i == len(events) and abs(quantity) < 1e-8 and minimum_cash >= 0
    return pd.Series(equity, index=frame.index), minimum_cash
normal, minimum_cash = equity_curve(.0015)
sensitive, _ = equity_curve(.003)
native, _ = equity_curve(.001)
assert abs(native.iloc[-1] - report['final_balance']) < 1e-5
assert abs(normal.iloc[-1]-1000-sum(p['normal'] for p in profits)) < 1e-5
assert abs(sensitive.iloc[-1]-1000-sum(p['sensitive'] for p in profits)) < 1e-5
daily_dd = float(np.max((np.maximum.accumulate(np.r_[1000., normal.values])-np.r_[1000., normal.values]) / np.maximum.accumulate(np.r_[1000., normal.values]))*100)
def at_boundary(date):
    return 1000. if date == start else float(normal.loc[date-pd.Timedelta(days=1)])
quarters = {f'2024Q{i+1}': at_boundary(b)-at_boundary(a) for i,(a,b) in enumerate(zip(pd.date_range(start,end,freq='QS'),pd.date_range(start,end,freq='QS')[1:]))}
positive = [p['normal'] for p in profits if p['normal'] > 0]
positive_quarters = [x for x in quarters.values() if x > 0]
trade_share = max(positive)/sum(positive) if positive else None
quarter_share = max(positive_quarters)/sum(positive_quarters) if positive_quarters else None
net = float(normal.iloc[-1]-1000)
without_best = net-max(positive) if positive else net
weekly = []
for monday in pd.date_range(start,end,freq='W-MON'):
    stop = monday+pd.Timedelta(days=7)
    if monday >= start and stop <= end:
        weekly.append((at_boundary(stop)-at_boundary(monday))/1000.)
weekly = np.asarray(weekly)
rng = np.random.default_rng(85)
means = []
for _ in range(2000):
    starts = rng.integers(0,len(weekly)-3,size=math.ceil(len(weekly)/4))
    sample = np.concatenate([weekly[i:i+4] for i in starts])[:len(weekly)]
    means.append(float(sample.mean()))
ci = np.quantile(means,[.025,.975],method='linear').tolist()
def bh(budget,cost):
    qty=budget/(float(frame.iloc[0]['open'])*(1+cost))
    return qty*float(frame.iloc[-1]['close'])*(1-cost)-budget
gates = {
 'normal_net_positive': net > 0,
 'sensitive_net_positive': float(sensitive.iloc[-1]) > 1000,
 'native_drawdown_at_most_15pct': report['max_drawdown_account']*100 <= 15,
 'daily_mtm_drawdown_at_most_15pct': daily_dd <= 15,
 'completed_non_force_exit_at_least_18': sum(t['exit_reason']!='force_exit' for t in trades) >= 18,
 'active_months_at_least_9': len(active_months) >= 9,
 'best_positive_trade_share_at_most_35pct': trade_share is not None and trade_share <= .35,
 'best_positive_quarter_share_at_most_70pct': quarter_share is not None and quarter_share <= .70,
 'net_without_best_trade_positive': without_best > 0,
 'auxiliary_profit_factor_at_least_1': report['profit_factor'] >= 1,
 'trade_accounting_timing_identity': True,
}
review = {'status':'SEARCH_TERMINATED_NO_FINALIST','all_protocol_gates':'PASSED' if all(gates.values()) else 'FAILED',
 'phase':'Search','candidate_id':attempt['candidate_id'],'protocol_sha256':sha(R/'proposal.md'),
 'archive':str(archive),'archive_sha256':sha(archive),'search_data_sha256':sha(data),'evaluation_script_sha256':sha(Path(__file__)),
 'real_search_attempts':1,'native_reruns':0,'development':'NOT_EXECUTED','holdout':'SEALED_UNREAD','stress':'SEALED_UNREAD',
 'gross_usdt':sum(p['gross'] for p in profits),'base_fee_usdt':sum(p['base_fee'] for p in profits),
 'native_net_usdt':float(native.iloc[-1]-1000),'normal_slippage_usdt':sum(p['base_fee']*.5 for p in profits),
 'normal_net_usdt':net,'sensitive_net_usdt':float(sensitive.iloc[-1]-1000),'native_drawdown_pct':report['max_drawdown_account']*100,
 'daily_mtm_drawdown_pct':daily_dd,'minimum_cash_usdt':minimum_cash,'profit_factor_native':report['profit_factor'],
 'total_trades':len(trades),'non_force_exit_trades':sum(t['exit_reason']!='force_exit' for t in trades),'active_months':sorted(active_months),
 'quarterly_mtm_net_usdt':quarters,'best_positive_trade_share':trade_share,'best_positive_quarter_share':quarter_share,'net_without_best_trade_usdt':without_best,
 'weekly_bootstrap':{'complete_weeks':len(weekly),'block_weeks':4,'replicates':2000,'seed':85,'mean_weekly_E0_return':float(weekly.mean()),'ci95_mean_weekly_E0_return':ci,'diagnostic_only_for_Search':True},
 'benchmarks_net_usdt':{'cash':0.,'bh_250_normal':bh(250,.0015),'bh_1000_normal':bh(1000,.0015),'bh_250_sensitive':bh(250,.003),'bh_1000_sensitive':bh(1000,.003)},
 'gates':gates,'limitations':['fixed historical fill path; costs do not bound real execution impact','bootstrap weeks are not independent; finite sample','daily close MTM misses intraday equity extremes','no Development or Holdout economic evidence']}
(R/'search-protocol-review.json').write_text(json.dumps(review,indent=2,allow_nan=False)+'\n')
print(json.dumps(review,indent=2,allow_nan=False))
