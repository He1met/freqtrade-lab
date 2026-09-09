"""Read-only attribution and per-trade audit of two existing native exports; no simulation."""
from pathlib import Path
import json,hashlib,zipfile,math
from collections import Counter
import pandas as pd
R=Path(__file__).resolve().parent
D=R/'source-acquisition/data/okx/futures'
price=pd.read_feather(D/'LINK_USDT_USDT-5m-futures.feather').set_index('date')
mark=pd.read_feather(D/'LINK_USDT_USDT-1h-mark.feather').set_index('date')
fund=pd.read_feather(D/'LINK_USDT_USDT-1h-funding_rate.feather').set_index('date')
H=pd.Timedelta(hours=1);M=pd.Timedelta(minutes=1)
slots=[]
for d in pd.date_range('2024-03-03','2024-07-30',freq='D',tz='UTC'):
 window=price.loc[d-24*H:d];lags=[d-48*H,d-40*H,d-32*H]
 mean=float(fund.loc[lags,'open'].mean());ret=float(price.loc[d,'close']/price.loc[d-24*H,'close']-1)
 guards=len(window)==289 and (window[['open','high','low','close','volume']]>0).all().all() and (window.index.to_series().diff().iloc[1:]==5*M).all() and all(t in fund.index for t in lags) and math.isfinite(mean)
 slots.append({'decision_bar_utc':d.isoformat(),'return_24h':ret,'lagged_funding_mean':mean,'common_guards':bool(guards),'r1_signal':bool(guards and ret<=-0.02),'r2_signal':bool(guards and ret<=-0.02 and mean>0.0001)})
assert len(slots)==150
summary={};all_trades={}
for round_ in (1,2):
 name=f'LaggedFundingR{round_}';archive=next((R/f'search/search-results-round-{round_}').rglob('*.zip'))
 with zipfile.ZipFile(archive) as z:
  report=json.loads(z.read(next(n for n in z.namelist() if n.endswith('.json') and 'config' not in n)))['strategy'][name]
  cfg=json.loads(z.read(next(n for n in z.namelist() if n.endswith('_config.json'))))
  assert z.read(next(n for n in z.namelist() if n.endswith('.py')))==(R/(name+'.py')).read_bytes()
 assert cfg['fee']==0.0005 and cfg['max_open_trades']==1 and cfg['stake_amount']==400
 assert report['minimal_roi']=={} and report['stoploss']==-0.03 and report['margin_mode']=='isolated'
 out=[]
 for t in report['trades']:
  opened=pd.Timestamp(t['open_date']);closed=pd.Timestamp(t['close_date']);d=opened-5*M
  assert opened.hour==0 and opened.minute==5 and opened.second==0
  assert t['is_short'] and t['leverage']==1 and not t['is_open']
  assert pd.Timestamp('2024-03-03',tz='UTC')<=opened<closed<pd.Timestamp('2024-07-31',tz='UTC')
  assert math.isclose(t['open_rate'],float(price.loc[opened,'open']),abs_tol=1e-12)
  assert t['fee_open']==t['fee_close']==0.0005 and len(t['orders'])==2
  for index,o in enumerate(t['orders']):
   assert o['ft_is_entry']==(index==0) and o['amount']==t['amount']
   assert o['order_filled_timestamp']==t['open_timestamp' if index==0 else 'close_timestamp']
  if t['exit_reason']=='exit_signal':
   assert closed==d+8*H+5*M and t['trade_duration']==480
   assert math.isclose(t['close_rate'],float(price.loc[closed,'open']),abs_tol=1e-12)
  else:
   assert t['exit_reason']=='stop_loss' and closed<=d+8*H+5*M
   assert t['close_rate']==t['stop_loss_abs']
   assert price.loc[closed,'high']>=t['close_rate']
   assert (price.loc[opened:closed-5*M,'high']<t['close_rate']).all()
   assert abs(t['stop_loss_abs']/t['open_rate']-1.03)<0.0001
  events=fund.loc[(fund.index>=opened)&(fund.index<=closed),'open']
  signed=float(sum(float(rate)*float(mark.loc[ts,'open'])*t['amount'] for ts,rate in events.items()))
  assert math.isclose(signed,t['funding_fees'],abs_tol=1e-8)
  legs=[o['amount']*o['safe_price'] for o in t['orders']]
  price_gross=t['amount']*(t['open_rate']-t['close_rate']);fees=sum(legs)*0.0005;extra=sum(legs)*0.0002
  assert abs(price_gross-fees+signed-t['profit_abs'])<6e-8
  out.append({'open_utc':opened.isoformat(),'close_utc':closed.isoformat(),'return_24h':float(price.loc[d,'close']/price.loc[d-24*H,'close']-1),'lagged_funding_mean':float(fund.loc[[d-48*H,d-40*H,d-32*H],'open'].mean()),'duration_minutes':t['trade_duration'],'exit_reason':t['exit_reason'],'amount':t['amount'],'open_notional':legs[0],'close_notional':legs[1],'price_gross_usdt':price_gross,'fees_usdt':fees,'signed_funding_usdt':signed,'native_net_usdt':t['profit_abs'],'extra_2bps_each_leg_usdt':extra,'adjusted_net_usdt':t['profit_abs']-extra,'funding_events_utc':[ts.isoformat() for ts in events.index],'timing_and_accounting_audit':'PASS'})
 expected=[(pd.Timestamp(x['decision_bar_utc'])+5*M).isoformat() for x in slots if x[f'r{round_}_signal']]
 assert [t['open_utc'] for t in out]==expected
 assert len(set(t['open_utc'] for t in out))==len(out)
 assert all(pd.Timestamp(out[i]['close_utc'])<pd.Timestamp(out[i+1]['open_utc']) for i in range(len(out)-1))
 totals={key:sum(t[key] for t in out) for key in ('price_gross_usdt','fees_usdt','signed_funding_usdt','native_net_usdt','extra_2bps_each_leg_usdt','adjusted_net_usdt')}
 assert abs(totals['native_net_usdt']-report['profit_total_abs'])<1e-7
 pf=sum(max(t['native_net_usdt'],0) for t in out)/-sum(min(t['native_net_usdt'],0) for t in out)
 assert abs(pf-report['profit_factor'])<1e-10
 months={month:{'trades':sum(t['open_utc'].startswith(month) for t in out),**{key:sum(t[key] for t in out if t['open_utc'].startswith(month)) for key in totals}} for month in ('2024-03','2024-04','2024-05','2024-06','2024-07')}
 maxwin=max(out,key=lambda x:x['native_net_usdt']);maxloss=min(out,key=lambda x:x['native_net_usdt'])
 gates={'trades_at_least_20':len(out)>=20,'native_net_at_least_25':totals['native_net_usdt']>=25,'adjusted_net_at_least_25':totals['adjusted_net_usdt']>=25,'native_pf_at_least_1_10':pf>=1.1,'native_dd_at_most_15':report['max_drawdown_account']*100<=15,'roi_exit_zero':all(t['exit_reason']!='roi' for t in out),'holding_nonzero_minimum':sum(t['duration_minutes'] for t in out)/len(out)>=1}
 summary[name]={'archive':str(archive.relative_to(R)),'archive_sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'trades':len(out),**totals,'native_profit_factor':pf,'native_max_drawdown_pct':report['max_drawdown_account']*100,'holding_min_minutes':min(t['duration_minutes'] for t in out),'holding_max_minutes':max(t['duration_minutes'] for t in out),'holding_average_minutes':sum(t['duration_minutes'] for t in out)/len(out),'exit_reasons':dict(Counter(t['exit_reason'] for t in out)),'funding_settlements_count':sum(len(t['funding_events_utc']) for t in out),'gates':gates,'self_pass':all(gates.values()),'months':months,'maximum_trade_contribution':maxwin,'maximum_loss_trade':maxloss,'max_winner_share_of_positive_trade_profits':maxwin['native_net_usdt']/sum(max(t['native_net_usdt'],0) for t in out),'tail_trade':out[-1],'full_daily_slot_reconciliation':'PASS'}
 all_trades[name]=out
r1=summary['LaggedFundingR1'];r2=summary['LaggedFundingR2']
# Matched trades are an exact subset, not statistically independent samples.
a={t['open_utc']:t for t in all_trades['LaggedFundingR1']};assert all(a[t['open_utc']]==t for t in all_trades['LaggedFundingR2'])
increment={'native_net_r2_minus_r1':r2['native_net_usdt']-r1['native_net_usdt'],'adjusted_net_r2_minus_r1':r2['adjusted_net_usdt']-r1['adjusted_net_usdt'],'r2_is_exact_r1_trade_subset':True,'removed_trades':r1['trades']-r2['trades'],'funding_gain_candidate':r2['self_pass'] and r2['native_net_usdt']>r1['native_net_usdt'] and r2['adjusted_net_usdt']>r1['adjusted_net_usdt']}
assert not r1['self_pass'] and not r2['self_pass']
result={'status':'SEARCH_TERMINATED_NO_FINALIST','scope':'EXPLORATORY_ONLY / NOT_INDEPENDENTLY_VALIDATED','source':'Only existing native ZIP and frozen acquired Feather; no backtest rerun','native_pf_dd_extra_cost_included':False,'historical_publication_time':'UNKNOWN','real_slippage':'UNKNOWN','effective_independent_sample_size':'UNKNOWN','rounds':summary,'increment':increment,'selection':'NONE','decision_slots':slots,'trade_audit':all_trades}
(R/'result-audit.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
print(json.dumps({'rounds':{k:{x:v[x] for x in ('trades','price_gross_usdt','fees_usdt','signed_funding_usdt','native_net_usdt','extra_2bps_each_leg_usdt','adjusted_net_usdt','native_profit_factor','native_max_drawdown_pct','holding_average_minutes','exit_reasons','self_pass','months')} for k,v in summary.items()},'increment':increment},indent=2))
