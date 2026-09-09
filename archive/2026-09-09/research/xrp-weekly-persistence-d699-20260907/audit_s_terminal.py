from pathlib import Path
import json,hashlib,zipfile,math,sys
import pandas as pd
from lab.futures_costs import validate_events,audit_native_trades,BOUNDARY_MS,HOUR_MS
r=Path(__file__).parent;s=r/'search-campaign/acquisition';sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
api=json.loads((r/'s-terminal-api.json').read_bytes());attempt=api['attempts'][0];archive=r/'search-campaign'/attempt['evidence']['archive']['path'];assert sha(archive)==attempt['evidence']['archive']['sha256']
with zipfile.ZipFile(archive) as z:
 name=next(n for n in z.namelist() if n.endswith('.json') and not n.endswith('.meta.json') and '_config' not in n);native=json.loads(z.read(name))['strategy']['XrpWeeklyPersistentDirection']
trades=native['trades'];assert len(trades)==30
source=json.loads((s/'retained-data-provenance.json').read_bytes());assert sha(s/'retained-data-provenance.json')=='f029356471dcd818aa88a5e22c4b96f44f080a79d21aa39323e54d29e396f6a8'
mp=s/'data/binance/futures/XRP_USDT_USDT-1h-mark.feather';assert sha(mp)=='ba70182545770a63178bd7a01f36909de7f14696a752e51952b4f9f49c6ad534';df=pd.read_feather(mp)
ms=lambda t:int(pd.Timestamp(t).timestamp()*1000)
start=ms('2023-11-06T00:00:00Z');end=ms('2024-11-04T00:00:00Z')
marks=[[ms(t),o,h,l,c] for t,o,h,l,c in df[['date','open','high','low','close']].itertuples(index=False,name=None)]
funding,candles=validate_events(source['source']['funding_events'],marks,symbol='XRPUSDT',start_ms=start,end_ms=end)
audit=audit_native_trades(trades,source['source']['funding_events'],marks,symbol='XRPUSDT',start_ms=start,end_ms=end,starting_balance=1000)
for k in ['conservative_final_balance','funding_deduction_abs','conservative_mtm_drawdown_pct']:assert math.isclose(audit[k],attempt['search_metrics']['funding_audit'][k],abs_tol=1e-9)
calendar=json.loads((r/'s-target-calendar.json').read_bytes());groups=[{**g,'censored':False} for g in calendar['completed_signal_regimes']]+[{**calendar['censored_signal_regime'],'end_exclusive_utc':'2024-11-04T00:00:00+00:00','censored':True}]
for g in groups:g.update(trade_indices=[],holding_minutes=0,conservative_profit_abs=0)
feesopen=feesclose=gross=nfunding=0;flowsbytrade=[];tradeout=[]
for i,(t,adj) in enumerate(zip(trades,audit['trade_adjustments'])):
 opened,closed=ms(t['open_date']),ms(t['close_date']);side=-1 if t['is_short'] else 1;amount=t['amount'];op=t['open_rate'];cp=t['close_rate'];eo=amount*op*t['fee_open'];ec=amount*cp*t['fee_close']
 gross+=side*(cp-op)*amount;feesopen+=eo;feesclose+=ec;nfunding+=t['funding_fees']
 g=next(g for g in groups if ms(g['start_utc'])<=opened<ms(g['end_exclusive_utc']));assert g['direction']==side
 g['trade_indices'].append(i);g['holding_minutes']+=(closed-opened)/60000;g['conservative_profit_abs']+=adj['conservative_profit_abs']
 flows=[];ns=0
 for event in funding:
  tt,b=event['time_ms'],event['native_time_ms'];n=-side*event['rate']*event['native_mark']*amount if opened<=b<=closed else 0.;ns+=n
  if not opened-BOUNDARY_MS<=tt<=closed+BOUNDARY_MS:continue
  exact=-side*event['rate']*event['associated_mark']*amount;boundary=abs(tt-opened)<=BOUNDARY_MS or abs(tt-closed)<=BOUNDARY_MS;c=min(n,exact,0.) if boundary else min(n,exact);flows.append((min(max(b,opened),closed),n,n-c))
 if opened==closed and t['funding_fees']==0 and ns!=0:flows=[(tt,0.,max(0.,d-n)) for tt,n,d in flows]
 assert math.isclose(sum(d for _,_,d in flows),adj['funding_deduction_abs'],abs_tol=1e-9)
 flowsbytrade.append(flows);tradeout.append(dict(index=i,open_date=t['open_date'],close_date=t['close_date'],direction=side,holding_minutes=(closed-opened)/60000,exit_reason=t['exit_reason'],pure_price_gross=side*(cp-op)*amount,entry_fee=eo,exit_fee=ec,native_funding=t['funding_fees'],native_net=t['profit_abs'],conservative_net=adj['conservative_profit_abs']))
completed=[g for g in groups if not g['censored'] and g['trade_indices']];censored=[g for g in groups if g['censored'] and g['trade_indices']]
active=[]
for w in range(52):
 lo=start+w*7*86400000;hi=lo+7*86400000
 if any(max(ms(t['open_date']),lo)<min(ms(t['close_date']),hi) for t in trades):active.append(w)
def equity(boundary):
 if boundary==start:return 1000.
 if boundary==end:return audit['conservative_final_balance']
 wallet=1000.
 for t,adj,flows in zip(trades,audit['trade_adjustments'],flowsbytrade):
  op,cl=ms(t['open_date']),ms(t['close_date'])
  if cl<boundary:wallet+=adj['conservative_profit_abs'];continue
  if op>=boundary:continue
  side=-1 if t['is_short'] else 1;amount=t['amount'];price=candles[boundary-HOUR_MS][3]
  wallet-=amount*t['open_rate']*t['fee_open'];wallet+=sum(n-d for time,n,d in flows if time<boundary)
  wallet+=side*(price-t['open_rate'])*amount-price*amount*t['fee_close']
 return wallet
bounds=[start+i*91*86400000 for i in range(5)];eq=[equity(b) for b in bounds];blocks=[eq[i+1]-eq[i] for i in range(4)];assert math.isclose(sum(blocks),audit['conservative_final_balance']-1000,abs_tol=1e-6)
positive=[b for b in blocks if b>0];share=None if not positive else max(positive)/sum(positive)
winners=[g for g in completed if g['conservative_profit_abs']>0];best=None if not winners else max(winners,key=lambda g:(g['conservative_profit_abs'],-ms(g['start_utc'])))
net=audit['conservative_final_balance']-1000;removed=None if best is None else net-best['conservative_profit_abs']
avg=sum(g['holding_minutes'] for g in completed)/len(completed) if completed else None
cp=sum(max(0,g['conservative_profit_abs']) for g in completed);cn=-sum(min(0,g['conservative_profit_abs']) for g in completed)
metrics=dict(pure_price_gross_usdt=gross,entry_fees_usdt=feesopen,exit_fees_usdt=feesclose,native_funding_usdt=nfunding,native_net_usdt=sum(t['profit_abs'] for t in trades),conservative_deduction_usdt=audit['funding_deduction_abs'],conservative_net_usdt=net,native_pf=native['profit_factor'],conservative_pf=audit['conservative_profit_factor'],native_dd_pct=attempt['search_metrics']['max_drawdown_pct'],hourly_mtm_dd_pct=audit['conservative_mtm_drawdown_pct'],supplemental_intrahour_dd_pct=audit['intrahour_ordering_stress_drawdown_pct'],native_trade_count=len(trades),completed_episode_count=len(completed),completed_long=sum(g['direction']==1 for g in completed),completed_short=sum(g['direction']==-1 for g in completed),censored_episode_count=len(censored),completed_episode_pf=cp/cn if cn else None,native_average_holding_minutes=sum(t['trade_duration'] for t in trades)/len(trades),episode_average_active_minutes=avg,active_weeks=len(active),block_equities=eq,block_net_usdt=blocks,positive_blocks=len(positive),maximum_positive_block_share=share,remove_largest_completed_profitable_episode_net=removed,minimum_free_cash=audit['minimum_free_cash'],roi_exit_count=sum(t['exit_reason']=='roi' for t in trades),liquidation_count=sum(t['exit_reason']=='liquidation' for t in trades),longest_regime_calendar_days=max((ms(g['end_exclusive_utc'])-ms(g['start_utc']))/86400000 for g in groups))
assert math.isclose(gross-feesopen-feesclose+nfunding,metrics['native_net_usdt'],abs_tol=1e-6)
gates=dict(core=False,conservative_net=net>=10,pure_price_gross=gross>0,native_pf=metrics['native_pf']>=1.1,conservative_pf=metrics['conservative_pf']>=1.1,native_dd=metrics['native_dd_pct']<=10,hourly_mtm_dd=metrics['hourly_mtm_dd_pct']<=10,completed_episodes=len(completed)>=12,long_episodes=metrics['completed_long']>=4,short_episodes=metrics['completed_short']>=4,native_average=metrics['native_average_holding_minutes']>=4320,episode_average=avg is not None and avg>=4320,active_weeks=len(active)>=26,fixed_blocks=len(positive)>=3 and share is not None and share<=.6,remove_largest=removed is not None and removed>0,no_roi=metrics['roi_exit_count']==0,no_liquidation=metrics['liquidation_count']==0,nonnegative_cash=audit['cash_executable'],accounting_reconciles=True,benchmark=None)
out=dict(status='SEARCH_TERMINATED_NO_FINALIST',campaign_id=api['campaign_id'],candidate_id=attempt['candidate_id'],market_native_calls=1,benchmark_status='SKIPPED_MAIN_CORE_FAILED',benchmark_calls=0,D_H_STRESS_calls=0,D_values_accidentally_exposed=True,archive_path=str(archive),archive_sha256=sha(archive),source_sha256=sha(s/'retained-data-provenance.json'),protocol_sha256=sha(r/'final-protocol.json'),metrics=metrics,gates=gates,trades=tradeout,episodes=groups,block_exposed_weeks=[sum(i*13<=w<(i+1)*13 for w in active) for i in range(4)],boundaries_utc=[pd.Timestamp(b,unit='ms',tz='UTC').isoformat() for b in bounds],analysis_only=True,new_native_calls=0)
with (r/'s-economic-audit.json').open('x') as f:json.dump(out,f,sort_keys=True,indent=2,allow_nan=False)
print(json.dumps(dict(metrics=metrics,gates=gates,receipt_sha256=sha(r/'s-economic-audit.json')),sort_keys=True))
