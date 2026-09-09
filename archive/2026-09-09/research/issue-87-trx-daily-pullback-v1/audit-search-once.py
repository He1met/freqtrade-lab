"""Read only the sole S ZIP and its S-only candles; no strategy execution."""
from pathlib import Path
import json,hashlib,zipfile
import numpy as np
import pandas as pd
R=Path('/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue-87-trx-daily-pullback-v1')
Z=R/'search-data/search-results-round-1/abe16b74-12e4-48bf-867a-20e0d290c115/raw/backtest-result-2026-09-06_01-38-57.zip'
assert hashlib.sha256(Z.read_bytes()).hexdigest()=='432d36bb343e32d3a7829155abb0057187f83592415344b537eea7d6333136d2'
with zipfile.ZipFile(Z) as z:
 name=next(n for n in z.namelist() if n.endswith('.json') and not n.endswith('_config.json'))
 s=json.loads(z.read(name))['strategy']['TrxDailyPullbackV1']
 source=next(n for n in z.namelist() if n.endswith('_TrxDailyPullbackV1.py'))
 assert hashlib.sha256(z.read(source)).hexdigest()=='0ca82cbc0f395ff3bb650702b3e70d2be5fc74a3df0376376abf5964d0f3a1d8'
t=s['trades'];assert s['timerange']=='20240101-20250101' and s['trading_mode']=='spot'
f=R/'search-data/acquisition/data/okx/TRX_USDT-1d.feather'
allbars=pd.read_feather(f);allbars['date']=pd.to_datetime(allbars['date'],utc=True)
assert allbars.date.max()<pd.Timestamp('2025-01-01',tz='UTC')
bars=allbars[(allbars.date>=pd.Timestamp('2024-01-01',tz='UTC'))].copy();assert len(bars)==366
E0=1000.0
base=np.array([x['profit_abs'] for x in t],dtype=float)
notional=np.array([x['amount']*(x['open_rate']+x['close_rate']) for x in t],dtype=float)
normal=base-notional*.0005;high=base-notional*.0015
assert abs(base.sum()-s['profit_total_abs'])<1e-5
for x in t:
 x['open_dt']=pd.Timestamp(x['open_date']);x['close_dt']=pd.Timestamp(x['close_date'])
assert all(x['pair']=='TRX/USDT' and not x['is_short'] and x['leverage']==1 for x in t)
equity=[];cashvals=[]
for row in bars.itertuples():
 end=row.date+pd.Timedelta(days=1);cash=E0;mark=0
 for i,x in enumerate(t):
  if x['open_dt']>=end:continue
  if x['close_dt']<end:cash+=normal[i]
  else:
   cash-=x['amount']*x['open_rate']*(1+x['fee_open']+.0005)
   mark+=x['amount']*row.close
 cashvals.append(cash);equity.append(cash+mark)
equity=np.array(equity);assert abs(equity[-1]-(E0+normal.sum()))<1e-7
peaks=np.maximum.accumulate(np.r_[E0,equity]);dd=float(np.max(1-np.r_[E0,equity]/peaks)*100)
delta=np.diff(np.r_[E0,equity]);returns=delta/E0
rng=np.random.default_rng(20260906);N=len(returns);starts=rng.integers(0,N-10+1,size=(10000,(N+9)//10));sample=returns[(starts[:,:,None]+np.arange(10)).reshape(10000,-1)[:,:N]].mean(axis=1)
ci=np.quantile(sample,[.05,.95],method='linear').tolist()
q={str(k):float(v) for k,v in pd.Series(delta,index=bars.date).groupby(bars.date.dt.quarter.to_numpy()).sum().items()}
full=[i for i,x in enumerate(t) if x['exit_reason']!='force_exit'];counts={str(k):sum(t[i]['close_dt'].quarter==k for i in full) for k in range(1,5)}
positive=normal[normal>0];negative=normal[normal<0];pf=float(positive.sum()/-negative.sum()) if len(negative) else None
bestshare=float(positive.max()/positive.sum()) if len(positive) else None
qpos=[v for v in q.values() if v>0];qshare=max(qpos)/sum(qpos) if qpos else None
withoutbest=float(normal.sum()-max(0,float(normal.max())));withoutforce=float(sum(normal[i] for i in full))
complete_durations=[t[i]['trade_duration'] for i in full]
# BH uses total 500 entry budget, fixed quantity and no fee/slippage cross terms.
buy=float(bars.iloc[0]['open']);qty=500/(buy*(1+.001+.0005));bh_equity=500+qty*bars.close.to_numpy();bh_equity[-1]=500+qty*float(bars.iloc[-1]['close'])*(1-.001-.0005)
bhnet=float(bh_equity[-1]-1000);bhpeaks=np.maximum.accumulate(np.r_[1000,bh_equity]);bhdd=float(np.max(1-np.r_[1000,bh_equity]/bhpeaks)*100)
bhgate=bool(normal.sum()>=bhnet or (dd>0 and bhdd>0 and dd<=bhdd*.75 and normal.sum()/dd>=bhnet/bhdd))
# Verify close-signal causality on the immutable S-only context, never reconstruct trades.
bydate=allbars.set_index('date');mean=bydate.close.rolling(5).mean();ret=bydate.close/bydate.close.shift(3)-1
entry_ok=all(ret.loc[x['open_dt']-pd.Timedelta(days=1)]<=-.03 and bydate.close.loc[x['open_dt']-pd.Timedelta(days=1)]<mean.loc[x['open_dt']-pd.Timedelta(days=1)] for x in t)
exit_ok=all(bydate.close.loc[x['close_dt']-pd.Timedelta(days=1)]>=mean.loc[x['close_dt']-pd.Timedelta(days=1)] for x in t if x['exit_reason']=='exit_signal')
gates={'net_base_strict_positive':bool(base.sum()>0),'net_normal_strict_positive':bool(normal.sum()>0),'normal_pf_gte_1_15':pf is not None and pf>=1.15,'high_cost_net_strict_positive':bool(high.sum()>0),'native_dd_lte_10':s['max_drawdown_account']*100<=10,'close_dd_lte_10':dd<=10,'complete_trades_gte_12':len(full)>=12,'complete_quarters_gte_3_each_gte2':sum(v>=2 for v in counts.values())>=3,'positive_quarters_gte2':sum(v>0 for v in q.values())>=2,'mean_hold_gte_1d':float(np.mean([x['trade_duration'] for x in t]))>=1440,'complete_hold_1d_fraction_gte_80pct':sum(v>=1440 for v in complete_durations)/len(full)>=.8,'trades_lte60':len(t)<=60,'without_best_positive':withoutbest>0,'best_positive_share_lte35pct':bestshare is not None and bestshare<=.35,'best_quarter_share_lte70pct':qshare is not None and qshare<=.70,'without_force_exit_positive':withoutforce>0,'cash_nonnegative':min(cashvals)>=0,'bh_comparison':bhgate,'entry_signal_causal':entry_ok,'exit_signal_causal':exit_ok,'roi_exit_zero':all(x['exit_reason']!='roi' for x in t)}
gates={k:bool(v) for k,v in gates.items()}
report={'schema':'issue87-frozen-search-audit-v1','status':'SEARCH_TERMINATED_NO_FINALIST','archive':str(Z),'archive_sha256':hashlib.sha256(Z.read_bytes()).hexdigest(),'source_candles':str(f),'source_candles_sha256':hashlib.sha256(f.read_bytes()).hexdigest(),'profit_usdt':{'base':float(base.sum()),'normal':float(normal.sum()),'high_cost':float(high.sum()),'normal_without_best':withoutbest,'normal_without_force_exit':withoutforce},'normal_pf':pf,'native_dd_pct':s['max_drawdown_account']*100,'normal_close_dd_pct':dd,'complete_trades':len(full),'total_trades':len(t),'exit_reasons':{k:sum(x['exit_reason']==k for x in t) for k in sorted(set(x['exit_reason'] for x in t))},'quarter_complete_counts':counts,'quarter_pnl_equity_differences':q,'best_winner_share':bestshare,'best_positive_quarter_share':qshare,'mean_holding_minutes':float(np.mean([x['trade_duration'] for x in t])),'minimum_daily_close_cash':min(cashvals),'daily_mean_fixed_E0_return':float(returns.mean()),'bootstrap_90pct_mean_daily_return':ci,'bootstrap_contract':{'seed':20260906,'block':10,'circular':False,'replications':10000,'quantile_method':'linear'},'bh':{'total_entry_budget':500,'quantity':qty,'entry_notional':qty*buy,'strategy_stake_nominal':500,'normal_profit_usdt':bhnet,'close_dd_pct':bhdd},'hard_gates':gates,'all_gates_pass':all(gates.values()),'low_pressure_diagnostic':{'status':'INTRADAY_SEQUENCE_NOT_IDENTIFIED','hard_gate':False,'numeric_value':None,'reason':'Daily OHLC cannot locate low within a stopped position lifetime. Open exits excluded from later low; no double deduction of stop. No numeric path estimate manufactured.'},'development_started':False,'holdout_acquired':False,'market_requests_in_audit':0,'backtest_calls_in_audit':0}
(R/'search-economic-audit.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
(R/'search-daily-equity.json').write_text(json.dumps([{'date':d.isoformat(),'normal_close_equity':float(e),'delta_over_E0':float(v)} for d,e,v in zip(bars.date,equity,returns)],indent=2)+'\n')
print(json.dumps(report,indent=2,allow_nan=False))
