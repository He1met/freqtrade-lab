import json,hashlib
from pathlib import Path
import pandas as pd
r=Path(__file__).resolve().parent
result={}
for name,sub,counts,end in [('source','source-acquisition',[851,20424,2193],'2026-02-01'),('search','search-data/acquisition',[486,11664,1098],'2025-02-01'),('development','development-pilot/development-isolation',[485,11640,1095],'2026-02-01')]:
 out={}
 for suffix,count,hours in zip(['1d-futures','1h-mark','1h-funding_rate'],counts,[24,1,8]):
  p=r/sub/'data/okx/futures'/('DOGE_USDT_USDT-'+suffix+'.feather');d=pd.read_feather(p);ts=d.date
  assert len(d)==count and ts.is_unique and ts.is_monotonic_increasing and str(ts.dt.tz)=='UTC'
  assert (ts.diff().dropna()==pd.Timedelta(hours=hours)).all()
  assert ts.iloc[-1]+pd.Timedelta(hours=hours)==pd.Timestamp(end,tz='UTC')
  assert not d.drop(columns=['volume'] if suffix=='1h-mark' else []).isna().any().any()
  out[suffix]={'rows':len(d),'first_utc':str(ts.iloc[0]),'last_utc':str(ts.iloc[-1]),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'volume_null_rows':int(d.volume.isna().sum())}
 result[name]=out
result['note']='Native mark volume is optional and remains NULL. An initial extra blanket no-NULL assertion was incorrect; no data changed. Native producer and consumer passed their actual contract.'
(r/'data-grid-audit.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result))
