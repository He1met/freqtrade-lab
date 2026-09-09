import ast
import json
import hashlib
from pathlib import Path
from urllib.parse import urlsplit,parse_qs
import pandas as pd
from freqtrade.exchange import Exchange
from freqtrade.data.converter import ohlcv_to_dataframe

root=Path(__file__).resolve().parent
api=json.loads((root/'native-sample-raw/0002.txt').read_text())
assert all(a['symbol']=='BCHUSDT' and 1690848000000<=a['fundingTime']<1693526400000 for a in api)
ts=[a['fundingTime'] for a in api]
assert ts==sorted(set(ts))
fund=pd.read_feather(root/'native-sample/futures/BCH_USDT_USDT-1h-funding_rate.feather')
mark=pd.read_feather(root/'native-sample/futures/BCH_USDT_USDT-1h-mark.feather')
joined=Exchange.combine_funding_and_mark(fund,mark)
assert len(joined)==len(api)==93
raw_by_type={}
for r in map(json.loads,(root/'native-recovery-http-receipts.jsonl').read_text().splitlines()):
    q=parse_qs(urlsplit(r['url']).query)
    if 'interval' not in q: continue
    key=(urlsplit(r['url']).path,q['interval'][0])
    rows=json.loads((root/'native-sample-recovery-raw'/r['body_file']).read_text())
    target=raw_by_type.setdefault(key,{})
    for row in rows:
        if row[0] in target: assert row==target[row[0]]
        target[row[0]]=row
out={}
for (path,tf),rows in raw_by_type.items():
    step={'1d':86400000,'1h':3600000}[tf]
    assert sorted(rows)==list(range(1690848000000,1693526400000,step))
    out[path+'/'+tf]={'raw_rows':len(rows),'continuous':True}
raw_mark=raw_by_type[('/fapi/v1/markPriceKlines','1h')]
envelope=[]
for a in api:
    t=a['fundingTime']//3600000*3600000
    r=raw_mark[t]
    o,h,l=map(float,r[1:4])
    assert l<=o<=h
    envelope.append(abs(float(a['fundingRate']))*max(h-o,o-l)/o*10000)
# Synthetic native boundary/sign checks. No actual strategy or PnL.
date=pd.Timestamp('2023-08-01T00:00:00Z')
synthetic=pd.DataFrame({'date':[date], 'open_fund':[0.001], 'open_mark':[100.]})
long=Exchange.calculate_funding_fees(None,synthetic,2,False,date.to_pydatetime(),date.to_pydatetime())
short=Exchange.calculate_funding_fees(None,synthetic,2,True,date.to_pydatetime(),date.to_pydatetime())
assert long==-0.2 and short==0.2
after=Exchange.calculate_funding_fees(None,synthetic,2,False,(date+pd.Timedelta(milliseconds=1)).to_pydatetime(),(date+pd.Timedelta(hours=1)).to_pydatetime())
assert after==0
report={'classification':'DATA_QC_ONLY','funding_raw_count':len(api),'funding_native_count':len(fund),'native_mark_join_count':len(joined),'raw_offsets_ms':sorted(set(t%28800000 for t in ts)),'converted_timestamp_changes':sum(t!=int(d.value//1000000) for t,d in zip(ts,fund.date)),'raw_exact_mark_grid_matches':sum(t in raw_mark for t in ts),'associated_mark_missing':sum(not a['markPrice'] for a in api),'candles':out,'native_output_last_candle_dropped':{'1d':len(raw_by_type[('/fapi/v1/klines','1d')])-len(pd.read_feather(root/'native-sample/futures/BCH_USDT_USDT-1d-futures.feather')),'1h_mark':len(raw_mark)-len(mark)},'mark_approximation_conditional_error_bps_of_event_notional':{'max_per_event':max(envelope),'sum_full_sample_unit_notional_exposure':sum(envelope),'assumption':'Actual settlement mark lies within event-hour observed mark low/high; conditional model sensitivity, NOT proven exchange-level bound. Excludes position membership ambiguity at open/close.'},'synthetic_boundary_checks':{'inclusive_both_ends':True,'long_short_sign':True,'one_ms_after_excludes':True},'strategy_runs':0,'D_H_read':False}
(root/'sample-qc.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
