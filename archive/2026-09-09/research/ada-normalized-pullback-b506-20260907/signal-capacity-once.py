from pathlib import Path
import hashlib,json,importlib.util,fcntl,os
from datetime import datetime,timezone
import pandas as pd
R=Path(__file__).parent
assert not (R/'signal-capacity.json').exists()
sha=lambda b:hashlib.sha256(b).hexdigest()
assert json.loads((R/'source-aggregation-qc.json').read_text())['status']=='SOURCE_QC_PASS'
assert sha((R/'AdaNormalizedTrendPullback3D.py').read_bytes())=='eb1f551464519f52b6f29469843dfe0acc880b53a6e86b778b94f09a88eda4b8'
spec=importlib.util.spec_from_file_location('fixed',R/'AdaNormalizedTrendPullback3D.py');mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
st=mod.AdaNormalizedTrendPullback3D({})
path=R/'search-campaign/acquisition/data/binance/futures/ADA_USDT_USDT-1d-futures.feather'
df=pd.read_feather(path)
assert df.date.min()==pd.Timestamp('2023-08-26',tz='UTC') and df.date.max()<pd.Timestamp('2024-11-04',tz='UTC')
x=st.populate_indicators(df.copy(),{'pair':'ADA/USDT:USDT'})
q=(x.trend_activity>0)&(x.shock_alignment<0)&(x.r_squared>=.00015625)&(x.normalized_excess>=0)&(x.liquidity_floor>=500000)
x=st.ft_advise_signals(x,{'pair':'ADA/USDT:USDT'})
bounds=pd.to_datetime(['2023-11-06','2024-02-05','2024-05-06','2024-08-05','2024-11-04'],utc=True)
# Count all scoring E as an optimistic upper bound, including any unusable tail.
# No forward return, order simulation, holding profitability, or D/H input access.
rows=[]
for a,b in zip(bounds[:-1],bounds[1:]):
 mask=(x.date>=a)&(x.date<b)
 rows.append({'start':a.isoformat(),'end_exclusive':b.isoformat(),'raw_Q':int(q[mask].sum()),'E_long':int((x.loc[mask,'enter_long']==1).sum()),'E_short':int((x.loc[mask,'enter_short']==1).sum())})
long=sum(d['E_long'] for d in rows);short=sum(d['E_short'] for d in rows)
passed=long+short>=24 and long>=8 and short>=8 and all(d['E_long']+d['E_short']>0 for d in rows)
out={'status':'CAPACITY_UPPER_BOUND_POSSIBLE' if passed else 'UNDERPOWERED','exposure':'S_SIGNAL_EXPOSED','all_E_is_optimistic_natural_upper_bound':True,'E_total':long+short,'E_long':long,'E_short':short,'blocks':rows,'thresholds':{'natural_total':24,'long':8,'short':8,'each_block_nonzero':True},'PnL_or_future_returns_computed':False,'native_backtests':0,'D':'MECHANICAL_QC_ONLY_NO_SIGNALS','H_Stress':'SEALED_UNREAD_UNACQUIRED','source_sha256':sha(path.read_bytes()),'strategy_sha256':sha((R/'AdaNormalizedTrendPullback3D.py').read_bytes())}
(R/'signal-capacity.json').write_text(json.dumps(out,indent=2))
l=Path('/Users/shenjianpeng/Documents/freqtrade-lab-local/search-research-supervision-20260902/global-research-ledger.jsonl')
with l.with_suffix(l.suffix+'.lock').open('a+b') as lock:
 fcntl.flock(lock.fileno(),fcntl.LOCK_EX);before=l.read_bytes()
 assert sha(before)==json.loads((R/'ledger-preregistration-receipt.json').read_text())['after_sha256']
 rec={'record_type':'S_SIGNAL_CAPACITY_TERMINAL','issue':101,'cohort_id':'issue101-ada-normalized-pullback-single-v1','root':str(R),'pair':'ADA/USDT:USDT','search_window':['2023-11-06','2024-11-04'],'recorded_at_utc':datetime.now(timezone.utc).isoformat(),'status':out['status'],'exposure':'S_SIGNAL_EXPOSED','search_consumed':True,'actual_native_Search_runs':0,'report_sha256':sha((R/'signal-capacity.json').read_bytes()),'previous_prefix_sha256':sha(before),'next_gate':'UNIQUE_NATIVE_SEARCH' if passed else 'STOP_UNDERPOWERED_NO_REPLAY','D':'MECHANICAL_QC_ONLY_NO_SIGNALS','H_Stress':'SEALED_UNREAD_UNACQUIRED'}
 addition=(json.dumps(rec,sort_keys=True)+'\n').encode()
 with l.open('ab') as f:f.write(addition);f.flush();os.fsync(f.fileno())
 after=l.read_bytes();assert after==before+addition
 (R/'ledger-capacity-receipt.json').write_text(json.dumps({'before_sha256':sha(before),'after_sha256':sha(after),'after_bytes':len(after),'prefix_preserved':True,'record':rec},indent=2))
print(json.dumps(out))
