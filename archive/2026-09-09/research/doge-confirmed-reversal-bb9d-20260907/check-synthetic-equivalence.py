"""Pure artificial series and locked populate order; no market data or backtest."""
import hashlib, importlib.util, json
from pathlib import Path
from dataclasses import asdict
import pandas as pd
from lab.bounded_strategy import analyze_bounded_causal_strategy_file

r=Path(__file__).parent;path=r/'DogeConfirmedShockReversal3D-v2.py'
analysis=analyze_bounded_causal_strategy_file(path,'DogeConfirmedShockReversal3D',expected_timeframe='1d')
spec=importlib.util.spec_from_file_location('synthetic_strategy',path)
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
strategy=module.DogeConfirmedShockReversal3D({})
closes=[100.0]*180
for i,v in {50:94,51:95,52:103,53:101,54:94,55:96,100:107,101:105,130:96,131:98,150:104,151:102}.items():closes[i]=v
base=pd.DataFrame({'date':pd.date_range('2000-01-01',periods=180,tz='UTC'),
    'open':closes,'high':[x*1.01 for x in closes],'low':[x*.99 for x in closes],
    'close':closes,'volume':[1000000.0]*180})
def actual(frame):
    result=strategy.populate_indicators(frame.copy(),{})
    return strategy.ft_advise_signals(result,{'pair':'DOGE/USDT:USDT'})
def reference(frame):
    c=frame.close.tolist();lo=frame.low.tolist();v=frame.volume.tolist();raw=[0]*len(c);events=[0]*len(c)
    for t in range(31,len(c)):
        prior=c[t-1]/c[t-2]-1;current=c[t]/c[t-1]-1
        liquid=min(lo[j]*v[j] for j in range(t-30,t))>=500000 and v[t]>0
        if liquid and prior<=-.04 and current>0 and c[t]<=.98*c[t-2]:raw[t]=1
        if liquid and prior>=.04 and current<0 and c[t]>=1.02*c[t-2]:raw[t]=-1
        if raw[t] and not any(raw[max(0,t-3):t]):events[t]=raw[t]
    return raw,events
results=[]
for name,frame in [('plain',base.copy()),('liquidity_and_volume_fail',base.copy())]:
    if name!='plain':frame.loc[80,'volume']=0;frame.loc[131,'volume']=0
    raw,e=reference(frame);out=actual(frame)
    long=out.enter_long.fillna(0).eq(1).tolist();short=out.enter_short.fillna(0).eq(1).tolist()
    exits=[False]*3+[bool(x) for x in e[:-3]]
    assert long==[x==1 for x in e] and short==[x==-1 for x in e]
    assert out.exit_long.fillna(0).eq(1).tolist()==exits==out.exit_short.fillna(0).eq(1).tolist()
    assert not any(a and b for a,b in zip(long,short))
    prefix=actual(frame.iloc[:100].copy())
    pd.testing.assert_frame_equal(out.iloc[:100],prefix)
    if name=='plain':assert raw[51] and e[51] and raw[53] and not e[53] and raw[55] and not e[55]
    entry_rows=[t+1 for t,x in enumerate(e) if x];exit_rows=[t+4 for t,x in enumerate(e) if x]
    assert all(b-a==3 for a,b in zip(entry_rows,exit_rows))
    results.append({'scenario':name,'rows':len(frame),'raw_events':sum(bool(x) for x in raw),
        'admitted_events':sum(bool(x) for x in e),'definition_equal_every_row':True,'prefix_causal':True,
        'directions_mutually_exclusive':True,'entry_exit_signal_shift_days':3})
report={'status':'SYNTHETIC_EQUIVALENCE_PASS','market_rows':0,'native_backtests':0,
 'strategy_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'static_analysis':asdict(analysis),
 'populate_order':'Locked IStrategy.ft_advise_signals calls advise_entry then advise_exit',
 'execution_timing_evidence':'Locked backtesting.py trims startup then shifts all entry/exit signals +1 bar; no matching-engine execution in this check',
 'timing':'E[t] entry signal -> t+1 open; E[t] exit signal at t+3 -> t+4 open, barring stop/force_exit',
 'scenarios':results}
with (r/'synthetic-equivalence.json').open('x') as f:json.dump(report,f,sort_keys=True,indent=2)
print(json.dumps(report,indent=2))
