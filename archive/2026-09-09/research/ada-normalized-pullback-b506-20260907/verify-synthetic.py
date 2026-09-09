import importlib.util,json,hashlib,math,sys
from pathlib import Path
from datetime import timedelta
import numpy as np
import pandas as pd
from freqtrade.strategy import IStrategy
R=Path(__file__).parent
spec=importlib.util.spec_from_file_location('fixed',R/'AdaNormalizedTrendPullback3D.py');mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
strategy=mod.AdaNormalizedTrendPullback3D({})
columns=['enter_long','enter_short','exit_long','exit_short']
def run(df):
 x=strategy.populate_indicators(df.copy(),{})
 return strategy.ft_advise_signals(x,{'pair':'ADA/USDT:USDT'})
def oracle(df):
 c=df.close.to_list();low=df.low.to_list();vol=df.volume.to_list();n=len(df)
 r=[float('nan')]+[c[i]/c[i-1]-1 for i in range(1,n)]
 m=[float('nan') if i<59 else sum(c[i-59:i+1])/60 for i in range(n)]
 q=[0]*n;e=[0]*n
 for t in range(65,n):
  v=sum(a*a for a in r[t-20:t])/20
  liquid=min(low[j]*vol[j] for j in range(t-30,t))>=500000 and vol[t]>0
  up=c[t-1]>m[t-1] and m[t-1]>m[t-6]
  down=c[t-1]<m[t-1] and m[t-1]<m[t-6]
  common=v>0 and r[t]*r[t]>=2.25*v and liquid
  q[t]=1 if up and r[t]<=-.0125 and common else -1 if down and r[t]>=.0125 and common else 0
  e[t]=q[t] if not any(q[t-3:t]) else 0
 rows=np.zeros((n,4),dtype=int)
 for t in range(n):
  rows[t,0]=int(e[t]==1);rows[t,1]=int(e[t]==-1)
  rows[t,2:]=int(t>=3 and bool(e[t-3]))
 return rows,q,e
reports=[]
for side in (1,-1):
 n=300;c=[100.]
 shock_days=[85,87,90,94,130,170,210,250]
 for t in range(1,n): c.append(c[-1]*(1+(-.04*side if t in shock_days else .006*side)))
 df=pd.DataFrame({'date':pd.date_range('2000-01-01',periods=n,tz='UTC',freq='D'),'open':c,'high':np.array(c)*1.01,'low':np.array(c)*.99,'close':c,'volume':np.full(n,100000.)})
 df.loc[130,'volume']=0
 df.loc[160,'volume']=1
 got=run(df)[columns].fillna(0).astype(int).to_numpy();expected,q,e=oracle(df)
 assert np.array_equal(got,expected),np.where(got!=expected)
 raw=[i for i,x in enumerate(q) if x];events=[i for i,x in enumerate(e) if x]
 assert 85 in events and 87 in raw and 87 not in events and 90 in raw and 90 not in events and 94 in events,(raw,events)
 assert 130 not in raw and 170 not in raw
 assert not ((got[:,0]==1)&(got[:,1]==1)).any()
 for end in [73,86,88,91,95,132,175,211,251,299]:
  prefix=run(df.iloc[:end].copy())[columns].fillna(0).astype(int).to_numpy()
  assert np.array_equal(prefix,got[:end])
 # Pure shift/time arithmetic, NOT matching engine or backtest.
 schedules=[]
 for t in events:
  assert got[t+3,2]==got[t+3,3]==1
  assert not any(got[t+1:t+4,0]) and not any(got[t+1:t+4,1])
  entry=df.date.iloc[t+1];exit=df.date.iloc[t+4]
  assert (exit-entry)==timedelta(hours=72)
  schedules.append({'event_row':t,'entry_row':t+1,'exit_signal_row':t+3,'exit_open_row':t+4,'holding_hours':72})
 reports.append({'side':side,'rows':n,'raw_Q_rows':raw,'admitted_E_rows':events,'oracle_equal':True,'prefix_checks':10,'schedules':schedules})
# Additional no-signal artificial flat history: v=0 must reject despite zero thresholds.
flat=pd.DataFrame({'date':pd.date_range('2001-01-01',periods=120,tz='UTC',freq='D'),'open':100.,'high':101.,'low':99.,'close':100.,'volume':100000.})
assert run(flat)[columns].fillna(0).to_numpy().sum()==0
report={'status':'PASS','scope':'SYNTHETIC_ONLY_NO_MARKET_DATA_NO_MATCHING_ENGINE_NO_PNL','strategy_sha256':hashlib.sha256((R/'AdaNormalizedTrendPullback3D.py').read_bytes()).hexdigest(),'checks':reports,'flat_v_zero_rejected':True,'actual_native_dispatch':'IStrategy.ft_advise_signals invokes entry then exit','natural_sample_rule':{'minimum_minutes':1440,'allowed_exit_reasons':['exit_signal','stop_loss'],'all_other_exits_count_in_pnl_risk':True}}
(R/'synthetic-equivalence.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
