from pathlib import Path
import pandas as pd,json,hashlib,os,fcntl,sqlite3
from datetime import datetime,timezone
r=Path(__file__).parent;os.umask(0o077)
h=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def put(n,v):
 with (r/n).open('x') as f:json.dump(v,f,sort_keys=True,indent=2)
 return h(r/n)
frozen=json.loads((r/'freeze-package-receipt.json').read_bytes())
for name,v in frozen['files'].items():assert h(r/name)==v['sha256']
phaseinfo={}
for phase,folder in [('S',r/'search-campaign/acquisition'),('D',r/'development-pilot/development-isolation')]:
 p=folder/'retained-data-provenance.json';meta=json.loads(p.read_bytes());info=[]
 for f in sorted(folder.rglob('*.feather')):
  assert not f.is_symlink();d=pd.read_feather(f);dates=pd.to_datetime(d.date,utc=True)
  expected=378 if '1d-futures' in f.name else 9072 if 'mark' in f.name else 1092
  assert len(d)==expected and not dates.duplicated().any() and dates.is_monotonic_increasing
  info.append(dict(path=str(f),rows=len(d),first_utc=dates.iloc[0].isoformat(),last_utc=dates.iloc[-1].isoformat(),sha256=h(f)))
 phaseinfo[phase]=dict(provenance_sha256=h(p),files=info,source_events=len(meta['source']['funding_events']))
put('phase-isolation-qc.json',dict(status='PASS',phases=phaseinfo,D_values_accidentally_exposed=True,D_signals_computed=False,market_native_calls=0))
sfile=r/'search-campaign/acquisition/data/binance/futures/XRP_USDT_USDT-1d-futures.feather'
df=pd.read_feather(sfile);dates=pd.to_datetime(df.date,utc=True);mom=df.close/df.close.shift(7)-1;execute=dates+pd.Timedelta(days=1)
mask=(dates.dt.dayofweek==6)&(dates>=pd.Timestamp('2023-11-06',tz='UTC'))&(execute<pd.Timestamp('2024-11-03',tz='UTC'))
selected=[dict(execution_utc=t.isoformat(),target=1 if m>0 else -1 if m<0 else 0) for t,m in zip(execute[mask],mom[mask])]
assert len(selected)==51 and selected[0]['execution_utc'].startswith('2023-11-13') and selected[-1]['execution_utc'].startswith('2024-10-28')
complete=[];current=None
for item in selected:
 side=item['target']
 if current is not None and side!=current['direction']:
  complete.append({**current,'end_exclusive_utc':item['execution_utc']});current=None
 if side and current is None:current=dict(direction=side,start_utc=item['execution_utc'],weeks=0)
 if current is not None:current['weeks']+=1
long=sum(x['direction']==1 for x in complete);short=sum(x['direction']==-1 for x in complete);active=sum(x['target']!=0 for x in selected)
checks=dict(completed_episodes=len(complete)>=12,completed_long=long>=4,completed_short=short>=4,active_weeks=active>=26)
receipt=dict(status='CAPACITY_NOT_DISPROVED' if all(checks.values()) else 'UNDERPOWERED',scope='S_TARGET_SEQUENCE_UPPER_BOUNDS_ONLY',window='20231106-20241104',strategy_sha256=h(r/'strategies/XrpWeeklyPersistentDirection.py'),protocol_sha256=h(r/'final-protocol.json'),source_provenance_sha256=phaseinfo['S']['provenance_sha256'],daily_feather_sha256=h(sfile),daily_rows=378,executable_decisions=51,targets_long=sum(x['target']==1 for x in selected),targets_short=sum(x['target']==-1 for x in selected),targets_zero=sum(x['target']==0 for x in selected),completed_episode_upper_bound=len(complete),completed_long_upper_bound=long,completed_short_upper_bound=short,censored_episode_upper_bound=int(current is not None),active_week_upper_bound=active,thresholds=dict(completed_episodes=12,completed_long=4,completed_short=4,active_weeks=26),checks=checks,market_native_calls=0,economic_results_computed=False,D_signals_computed=False,D_values_accidentally_exposed=True,H_source_acquired=False,actual_trade_counts=None,pnl=None,database_attachment='NOT_ATTACHED_EXISTING_PREFILTER_SEMANTICS_INCOMPATIBLE',recorded_at_utc=datetime.now(timezone.utc).isoformat())
put('s-target-calendar.json',dict(targets=selected,completed_signal_regimes=complete,censored_signal_regime=current))
receiptsha=put('signal-capacity.json',receipt)
l=Path('/Users/shenjianpeng/Documents/freqtrade-lab-local/search-research-supervision-20260902/global-research-ledger.jsonl')
with Path(str(l)+'.lock').open('r+') as lock:
 fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);before=l.read_bytes();bs=hashlib.sha256(before).hexdigest()
 record={**receipt,'record_type':'S_SIGNAL_CAPACITY_EXPOSURE','exposure':'S_SIGNAL_EXPOSED','cohort_id':r.name,'receipt_path':str(r/'signal-capacity.json'),'receipt_sha256':receiptsha,'previous_prefix_sha256':bs,'erratum_sha256':h(r/'funding-row-count-erratum.json'),'incident_receipt_sha256':h(r/'unintended-exposure-receipt.json')}
 with l.open('ab') as f:
  if before and not before.endswith(b'\n'):f.write(b'\n')
  f.write(json.dumps(record,sort_keys=True,separators=(',',':')).encode()+b'\n');f.flush();os.fsync(f.fileno())
 after=l.read_bytes();assert after.startswith(before)
 put('capacity-ledger-receipt.json',dict(before_sha256=bs,after_sha256=hashlib.sha256(after).hexdigest(),old_prefix_preserved=True))
con=sqlite3.connect('file:'+str(r/'lab.sqlite')+'?mode=ro',uri=True)
tables=[x[0] for x in con.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%'")];assert len(tables)==6
counts={t:con.execute('SELECT COUNT(*) FROM "'+t+'"').fetchone()[0] for t in tables};con.close();put('database-counts-receipt.json',counts)
print(json.dumps(dict(capacity=receipt,database_counts=counts,ledger_sha256=hashlib.sha256(after).hexdigest()),sort_keys=True))
