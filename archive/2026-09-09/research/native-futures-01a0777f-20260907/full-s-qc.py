import json
from pathlib import Path
from urllib.parse import urlsplit,parse_qs
import pandas as pd
from freqtrade.exchange import Exchange

root=Path(__file__).resolve().parent
start,end=1688342400000,1721001600000
series={}
receipts=[json.loads(l) for l in (root/'native-full-s-http-receipts.jsonl').read_text().splitlines()]
for r in receipts:
    p=urlsplit(r['url']); q=parse_qs(p.query)
    if p.path.endswith('exchangeInfo'): continue
    assert q['symbol']==['BCHUSDT'] and start<=int(q['startTime'][0])<=int(q['endTime'][0])<end
    rows=json.loads((root/'native-full-s-raw'/r['body_file']).read_text())
    key='funding' if p.path.endswith('fundingRate') else ('mark' if p.path.endswith('markPriceKlines') else 'futures')
    target=series.setdefault(key,{})
    for row in rows:
        t=row['fundingTime'] if key=='funding' else row[0]
        assert start<=t<end
        if key=='funding': assert row['symbol']=='BCHUSDT' and row.get('rateType','Regular')=='Regular'
        if t in target: assert target[t]==row
        target[t]=row
for key,step in [('mark',3600000),('futures',86400000)]:
    assert sorted(series[key])==list(range(start,end,step))
fund=series['funding'];mark=series['mark']
assert sorted(t//28800000*28800000 for t in fund)==list(range(start,end,28800000))
associated_count=0; outside=0; equal_open=0; relative=[]; fee_diff=[]; envelopes=[]; months={}
for t,a in sorted(fund.items()):
    r=mark[t//3600000*3600000]
    o,h,l=map(float,r[1:4]); rate=abs(float(a['fundingRate']))
    assert l<=o<=h
    envelopes.append(rate*max(h-o,o-l)/o*10000)
    month=pd.Timestamp(t,unit='ms',tz='UTC').strftime('%Y-%m')
    rec=months.setdefault(month,{'events':0,'associated_present':0,'outside_event_hour_mark':0})
    rec['events']+=1
    if a['markPrice']:
        m=float(a['markPrice']);associated_count+=1;rec['associated_present']+=1
        outside+=not l<=m<=h;rec['outside_event_hour_mark']+=not l<=m<=h
        equal_open+=m==o
        relative.append(abs(m-o)/o*10000);fee_diff.append(rate*abs(m-o)/o*10000)
f=pd.read_feather(root/'native-full-s/futures/BCH_USDT_USDT-1h-funding_rate.feather')
m=pd.read_feather(root/'native-full-s/futures/BCH_USDT_USDT-1h-mark.feather')
assert len(Exchange.combine_funding_and_mark(f,m))==len(fund)
result={'classification':'DATA_QC_ONLY','window':['2023-07-03T00:00:00Z','2024-07-15T00:00:00Z'],'raw_rows':{k:len(v) for k,v in series.items()},'identity_and_half_open_range_verified':True,'funding_unique_eight_hour_buckets_complete':True,'funding_offsets_ms':sorted(set(t%28800000 for t in fund)),'native_funding_rows':len(f),'native_join_rows':len(fund),'native_last_complete_candle_dropped':True,'associated_mark':{'present':associated_count,'missing':len(fund)-associated_count,'equal_mark_open':equal_open,'outside_event_hour_low_high':outside,'maximum_mark_relative_difference_bps':max(relative),'maximum_fee_difference_bps_event_notional':max(fee_diff),'sum_fee_difference_bps_full_window_unit_exposure':sum(fee_diff)},'conditional_mark_envelope':{'maximum_fee_difference_bps_event_notional':max(envelopes),'sum_fee_difference_bps_full_window_unit_exposure':sum(envelopes),'assumption':'Settlement mark lies within observed event-hour low/high; empirical check only for API nonempty subset, not proof for missing rows or actual account settlement.'},'months':months,'strategy_runs':0,'D_H_read':False,'http_fetch_calls':len(receipts),'decoded_response_bytes':sum(r['bytes'] for r in receipts)}
(root/'full-s-qc.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
