"""Separate frozen synthetic/7 input. Original synthetic/6 bytes unchanged."""
from pathlib import Path
from hashlib import sha256
import json
from datetime import datetime,timedelta
from lab.portfolio_causal import PAIRS,PriceBar
INPUT_PATH=Path(__file__).resolve().parents[1]/'tests/fixtures/portfolio-causal-probe-v2.json'


def input_sha(): return sha256(INPUT_PATH.read_bytes()).hexdigest()


def expand():
    spec=json.loads(INPUT_PATH.read_bytes())
    first=datetime.fromisoformat(spec['first_daily_close'])
    start=first+timedelta(days=spec['execution_start_day'])
    hourly={p:[] for p in PAIRS};daily={p:[] for p in PAIRS}
    previous=spec['daily_closes'][0]
    for day,close in enumerate(spec['daily_closes']):
        boundary=first+timedelta(days=day);chunk=[]
        for hour in range(24):
            opened=boundary-timedelta(hours=24-hour)
            op=previous+(close-previous)*hour/24;cp=previous+(close-previous)*(hour+1)/24
            values=dict(open=op,high=max(op,cp)+.01,low=min(op,cp)-.01,close=cp)
            override=spec['hour_overrides'].get(str(int((opened-start).total_seconds()/3600)),{})
            values.update({k:v for k,v in override.items() if k!='high_add'})
            values['high']+=override.get('high_add',0)
            chunk.append(PriceBar(opened+timedelta(hours=1),**values))
        bar=PriceBar(boundary,chunk[0].open,max(b.high for b in chunk),min(b.low for b in chunk),chunk[-1].close)
        for p in PAIRS: hourly[p].extend(chunk);daily[p].append(bar)
        previous=close
    return spec,start,hourly,daily
