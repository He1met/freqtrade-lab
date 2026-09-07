"""One synthetic input, expanded deterministically; never reads market data."""
from datetime import datetime, timedelta
from pathlib import Path
import hashlib
import json
from lab.portfolio_causal import PriceBar, PAIRS

INPUT_PATH=Path(__file__).resolve().parents[1]/"tests/fixtures/portfolio-causal-probe-v1.json"


def expand():
    spec=json.loads(INPUT_PATH.read_bytes())
    first=datetime.fromisoformat(spec["first_daily_close"])
    start=first+timedelta(days=spec["execution_start_day"])
    hourly={p:[] for p in PAIRS}
    daily={p:[] for p in PAIRS}
    previous=spec["daily_closes"][0]
    for day,close in enumerate(spec["daily_closes"]):
        boundary=first+timedelta(days=day)
        chunk=[]
        for hour in range(24):
            opened=boundary-timedelta(hours=24-hour)
            op=previous+(close-previous)*hour/24
            cp=previous+(close-previous)*(hour+1)/24
            values=dict(open=op,high=max(op,cp)+.01,low=min(op,cp)-.01,close=cp)
            override=spec["hour_overrides"].get(str(int((opened-start).total_seconds()/3600)),{})
            values.update({k:v for k,v in override.items() if k!="high_add"})
            values["high"]+=override.get("high_add",0)
            bar=PriceBar(opened+timedelta(hours=1),**values)
            chunk.append(bar)
        daily_bar=PriceBar(boundary,chunk[0].open,max(b.high for b in chunk),min(b.low for b in chunk),chunk[-1].close)
        for pair in PAIRS:
            hourly[pair].extend(chunk)
            daily[pair].append(daily_bar)
        previous=close
    return spec,start,hourly,daily


def input_sha():
    return hashlib.sha256(INPUT_PATH.read_bytes()).hexdigest()


def known_hour(hourly, at):
    completed=next(b for b in hourly[PAIRS[0]] if b.closed_at==at)
    current=next(b for b in hourly[PAIRS[0]] if b.closed_at==at+timedelta(hours=1))
    return {p:completed for p in PAIRS},{p:current.open for p in PAIRS}


def mark_at(spec,start,at,completed):
    factor=1.
    for hours,value in spec["mark_factors_after_hours"]:
        if at>=start+timedelta(hours=hours): factor=value
    return {p:completed[p].close*factor for p in PAIRS}
