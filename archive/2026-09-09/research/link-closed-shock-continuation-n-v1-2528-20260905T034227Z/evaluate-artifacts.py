"""Read-only M accounting of the two native Search artifacts. No backtest or DB mutation."""
from pathlib import Path
from decimal import Decimal as D
from datetime import datetime,timezone,timedelta
import json,zipfile,hashlib
import pandas as pd
ROOT=Path(__file__).resolve().parent
START=datetime(2024,8,1,tzinfo=timezone.utc);END=datetime(2025,1,31,tzinfo=timezone.utc)
START_MS=int(START.timestamp()*1000);END_MS=int(END.timestamp()*1000);WEEK_MS=604800000
FIELDS=('E','X','G','F','fee','N','N2bps','N5bps')
def dec(x):
 assert x is not None and not isinstance(x,bool)
 v=D(str(x));assert v.is_finite();return v
def dump(path,value):path.write_text(json.dumps(value,indent=2,default=str)+'\n')
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
data=ROOT/'search/acquisition/data/okx/futures'
def read_series(name):
 df=pd.read_feather(data/name);return {int(t.timestamp()*1000):{k:dec(v) for k,v in row.items() if k in ('open','close')} for t,row in zip(df['date'],df.to_dict('records'))}
futures=read_series('LINK_USDT_USDT-5m-futures.feather');mark=read_series('LINK_USDT_USDT-1h-mark.feather');fund=read_series('LINK_USDT_USDT-1h-funding_rate.feather')
assert len(futures)==52722 and len(mark)==4394 and len(fund)==549
assert max(futures)<END_MS and max(mark)<END_MS and max(fund)<END_MS
out={'protocol':'M unchanged','native_net_rounding_tolerance_usdt':'0.00000001','funding_recompute_tolerance_usdt':'0.00000001','only_search_data_read':True,'orders_funding_field':'native minified orders omit individual funding_fee; full per-trade funding recomputed from S funding/mark; one entry and one exit','rounds':{}}
for rnd in [1,2]:
 cl=f'ClosedShockContinuationR{rnd}';arc=next((ROOT/f'search/search-results-round-{rnd}').rglob('*.zip'))
 with zipfile.ZipFile(arc) as z:
  name=next(n for n in z.namelist() if n.endswith('.json') and not n.endswith('_config.json'));s=json.loads(z.read(name),parse_float=D)['strategy'][cl]
  native_source=z.read(next(n for n in z.namelist() if n.endswith('.py')));assert native_source==(ROOT/f'frozen/{cl}.py').read_bytes()
  config=json.loads(z.read(next(n for n in z.namelist() if n.endswith('_config.json'))),parse_float=D)
 assert s['timerange']=='20240801-20250131' and s['timeframe']=='5m' and s['starting_balance']==1000 and s['stake_amount']==100 and s['max_open_trades']==1
 assert s['minimal_roi']=={'180':-1} and s['ignore_roi_if_entry_signal'] is False and s['stoploss']==D('-.02') and s['margin_mode']=='isolated'
 rows=[];weekly=[dict(week=i,start=(START+timedelta(days=i*7)).isoformat(),end=min(START+timedelta(days=(i+1)*7) if i<25 else END,END).isoformat(),trades=0,**{f:D(0) for f in FIELDS}) for i in range(26)]
 for idx,t in enumerate(s['trades']):
  q,eprice,xprice=map(dec,[t['amount'],t['open_rate'],t['close_rate']]);entry,exit=t['open_timestamp'],t['close_timestamp'];direction=-1 if t['is_short'] else 1
  assert START_MS<=entry<END_MS and entry%3600000==1800000 and entry<=exit<END_MS
  assert t['is_open'] is False and t['leverage']==1 and t['fee_open']==D('.0005') and t['fee_close']==D('.0005')
  assert 0<=t['trade_duration']<=180 and exit-entry==t['trade_duration']*60000
  assert t['exit_reason'] in ('roi','stop_loss','force_exit')
  assert t['exit_reason']!='roi' or t['trade_duration']==180
  assert t['trade_duration']!=0 or t['exit_reason']=='stop_loss'
  assert len(t['orders'])==2 and q>0
  for order,price,ts,is_entry in [(t['orders'][0],eprice,entry,True),(t['orders'][1],xprice,exit,False)]:
   assert dec(order['amount'])==q and dec(order['safe_price'])==price and order['order_filled_timestamp']==ts and order['ft_is_entry']==is_entry
   assert abs(dec(order['cost'])-q*price*D('1.0005'))<D('0.00000001')
  assert abs(eprice-futures[entry]['open'])<D('0.00000001')
  if t['exit_reason']=='roi':assert abs(xprice-futures[exit]['open'])<D('0.00000001')
  shock=futures[entry-2100000]['close']/futures[entry-5400000]['open']-1
  assert (shock>=D('.01') if direction==1 else shock<=D('-.01'))
  confirmation=futures[entry-300000]['close']/futures[entry-1800000]['open']-1
  if rnd==2:assert direction*confirmation>0
  fdates=[ts for ts in fund if entry<=ts<=exit]
  fcash=sum((-direction*q*mark[ts]['open']*fund[ts]['open'] for ts in fdates),D(0));f=dec(t['funding_fees'])
  assert abs(f-fcash)<D('0.00000001'),(idx,'funding',f,fcash)
  e=q*eprice;x=q*xprice;g=direction*(x-e);fee=D('.0005')*(e+x);n=g+f-fee
  assert abs(n-dec(t['profit_abs']))<=D('0.00000001'),(idx,'native-net')
  w=min((entry-START_MS)//WEEK_MS,25);row={'trade_index':idx,'entry_utc':datetime.fromtimestamp(entry/1000,timezone.utc).isoformat(),'exit_utc':datetime.fromtimestamp(exit/1000,timezone.utc).isoformat(),'is_short':t['is_short'],'quantity':q,'entry_price':eprice,'exit_price':xprice,'duration_minutes':t['trade_duration'],'exit_reason':t['exit_reason'],'week':w,'E':e,'X':x,'G':g,'F':f,'fee':fee,'N':n,'N2bps':n-D('.0002')*(e+x),'N5bps':n-D('.0005')*(e+x),'native_profit_abs':t['profit_abs'],'native_net_abs_difference':abs(n-dec(t['profit_abs'])),'funding_recomputed':fcash,'funding_abs_difference':abs(f-fcash),'funding_timestamps_utc':[datetime.fromtimestamp(ts/1000,timezone.utc).isoformat() for ts in fdates]}
  rows.append(row);weekly[w]['trades']+=1
  for fld in FIELDS:weekly[w][fld]+=row[fld]
 total={fld:sum((row[fld] for row in rows),D(0)) for fld in FIELDS};longs=sum(not row['is_short'] for row in rows);shorts=len(rows)-longs;active=sum(w['trades']>0 for w in weekly)
 best=max(range(26),key=lambda i:(weekly[i]['N2bps'],-i));remaining={fld:total[fld]-weekly[best][fld] for fld in FIELDS}
 gates={'total_ge_52':len(rows)>=52,'long_ge_13':longs>=13,'short_ge_13':shorts>=13,'active_weeks_ge_20':active>=20,'G_positive':total['G']>0,'N2bps_positive':total['N2bps']>0,'N5bps_positive':total['N5bps']>0,'drop_best_week_G_positive':remaining['G']>0,'drop_best_week_N2bps_positive':remaining['N2bps']>0,'native_pf_ge_1_10':dec(s['profit_factor'])>=D('1.10'),'native_dd_le_5pct':dec(s['max_drawdown_account'])*100<=5,'native_net_positive':dec(s['profit_total_abs'])>0}
 result={'archive':str(arc),'archive_sha256':sha(arc),'trades':len(rows),'long':longs,'short':shorts,'active_weeks':active,'totals':total,'G_per_E':total['G']/total['E'],'N2bps_per_E':total['N2bps']/total['E'],'native_net_pct':dec(s['profit_total'])*100,'native_profit_factor':s['profit_factor'],'native_drawdown_pct':dec(s['max_drawdown_account'])*100,'best_N2bps_week':best,'after_drop_best_week':remaining,'gates':gates,'all_own_gates_pass':all(gates.values()),'technical_accounting_timing_verified':True,'max_native_net_difference':max(row['native_net_abs_difference'] for row in rows),'max_funding_difference':max(row['funding_abs_difference'] for row in rows),'zero_duration_stop_count':sum(row['duration_minutes']==0 for row in rows),'weekly':weekly}
 out['rounds'][str(rnd)]=result;dump(ROOT/f'accounting-r{rnd}-trades.json',rows)
a,b=out['rounds']['1'],out['rounds']['2'];delta=[{'week':i,'G':b['weekly'][i]['G']-a['weekly'][i]['G'],'N2bps':b['weekly'][i]['N2bps']-a['weekly'][i]['N2bps']} for i in range(26)];best=max(range(26),key=lambda i:(delta[i]['N2bps'],-i));dg=b['totals']['G']-a['totals']['G'];dn=b['totals']['N2bps']-a['totals']['N2bps']
out['r2_increment']={'delta_G':dg,'delta_N2bps':dn,'drop_max_delta_N2bps_week':best,'remaining_delta_G':dg-delta[best]['G'],'remaining_delta_N2bps':dn-delta[best]['N2bps'],'gates':{'G2_gt_G1':dg>0,'G2_per_E_gt_G1_per_E':b['G_per_E']>a['G_per_E'],'N2bps2_gt_N2bps1':dn>0,'N2bps2_per_E_gt_N2bps1_per_E':b['N2bps_per_E']>a['N2bps_per_E'],'remaining_delta_G_positive':dg-delta[best]['G']>0,'remaining_delta_N2bps_positive':dn-delta[best]['N2bps']>0},'weekly_deltas':delta}
terminal=json.loads((ROOT/'search/search-terminal.json').read_text());out['native_terminal']=terminal['status'];out['protocol_status']='SEARCH_TERMINATED_NO_FINALIST';out['interpretation']='S coverage passed; native and net-after-extra-cost gates failed. No finalist, no D, no hand replacement. Economic negative within this exact protocol, not universal invalidity.'
dump(ROOT/'accounting-summary.json',out)
print(json.dumps({k:out[k] for k in ['native_terminal','protocol_status','r2_increment']},default=str))
for n,r in out['rounds'].items():print(n,json.dumps({k:v for k,v in r.items() if k not in ['weekly']},default=str))
