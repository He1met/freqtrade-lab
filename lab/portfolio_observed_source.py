"""SHA-bound observed API source; expose only the approved exploration prefix."""
from dataclasses import dataclass
from datetime import datetime,timedelta,timezone
from pathlib import Path
import hashlib
import json
from lab.portfolio_source import SourceError,validate_rows,ms
from lab.portfolio_causal import PriceBar,PAIRS

ROOT=Path(__file__).resolve().parents[1]
RAW_ROOT=Path('/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue119-btc-eth-source/continuation-v2/raw')
RECEIPT=ROOT/'docs/issue123-capture-terminal.json'
RECEIPT_SHA='36687a2d8ab37856b1ba8951bb3f75976ecb181e5fb39199d65304248237b098'
START=datetime(2024,8,1,tzinfo=timezone.utc)
END=datetime(2024,11,1,tzinfo=timezone.utc)
SYMBOLS=dict(zip(('BTCUSDT','ETHUSDT'),PAIRS))


def stamp(value):return datetime.fromtimestamp(value/1000,timezone.utc)


@dataclass
class ObservedView:
    hourly:dict
    marks:dict
    daily:dict
    funding:list
    source_sha:str
    start:datetime=START
    end:datetime=END
    kind:str='OBSERVED_API_COMPLETE_FOR_EXPLORATORY_MODEL'
    volumes:dict=None
    metadata:dict=None

    def known(self,at):
        if not self.start-timedelta(hours=3)<=at<self.end:raise SourceError('outside approved execution view')
        completed={p:self.hourly[p][at-timedelta(hours=1)] for p in PAIRS}
        opens={p:self.hourly[p][at].open for p in PAIRS}
        marks={p:self.marks[p][at-timedelta(hours=1)].close for p in PAIRS}
        return completed,opens,marks


def load_view(*,role='explore',raw_root=RAW_ROOT,receipt_path=RECEIPT):
    if role!='explore':raise SourceError('reserved process-check view is sealed')
    receipt_raw=Path(receipt_path).read_bytes()
    if hashlib.sha256(receipt_raw).hexdigest()!=RECEIPT_SHA:raise SourceError('unapproved source receipt')
    receipt=json.loads(receipt_raw)
    if receipt.get('schema')!='issue123-sanitized-v2-terminal-v1' or receipt.get('structure')!='PASS':
        raise SourceError('real observed source receipt required; synthetic rejected')
    series={s:{'klines':[],'markPriceKlines':[],'fundingRate':[]} for s in SYMBOLS}
    for item in receipt['source_files']:
        raw=(Path(raw_root)/item['name']).read_bytes()
        if len(raw)!=item['bytes'] or hashlib.sha256(raw).hexdigest()!=item['sha256']:
            raise SourceError('source raw SHA/length drift')
        kind=item['name'].split('-',1)[1][:-5]
        if kind not in ('klines','markPriceKlines','fundingRate'):continue
        # Frozen request order: funding 040-045, BTC hourly046-059, ETH060-073.
        n=int(item['name'][:3])
        symbol=('BTCUSDT' if n<=42 else 'ETHUSDT') if kind=='fundingRate' else ('BTCUSDT' if n<=59 else 'ETHUSDT')
        rows=json.loads(raw)
        series[symbol][kind].extend(rows)
    hourly={};marks={};daily={};events=[];volumes={}
    metadata=json.loads((Path(raw_root)/'038-exchangeInfo.json').read_bytes())
    metadata={SYMBOLS[r['symbol']]:r for r in metadata['symbols'] if r['symbol'] in SYMBOLS}
    source_start=ms('2023-11-01T00:00:00Z');source_end=ms('2025-01-01T00:00:00Z')
    for symbol,pair in SYMBOLS.items():
        for kind in ('klines','markPriceKlines'):
            rows=series[symbol][kind];validate_rows(rows,kind,source_start,source_end)
            if [r[0] for r in rows]!=list(range(source_start,source_end,3600000)):
                raise SourceError('hourly source coverage changed')
            target={stamp(r[0]):PriceBar(stamp(r[0])+timedelta(hours=1),*[float(v) for v in r[1:5]]) for r in rows if stamp(r[0])<END}
            if kind=='klines':
                hourly[pair]=target
                volumes[pair]={stamp(r[0]):float(r[5]) for r in rows if stamp(r[0])<END}
            else:marks[pair]=target
        day=[];values=list(hourly[pair].values())
        for i in range(0,len(values),24):
            chunk=values[i:i+24]
            if len(chunk)!=24:raise SourceError('incomplete daily aggregation')
            day.append(PriceBar(chunk[-1].closed_at,chunk[0].open,max(x.high for x in chunk),min(x.low for x in chunk),chunk[-1].close))
        daily[pair]=day
        funding=series[symbol]['fundingRate'];validate_rows(funding,'fundingRate',source_start,source_end)
        if len(funding)!=1281 or len({(r['fundingTime']-source_start)//28800000 for r in funding})!=1281:
            raise SourceError('nominal 8h slots incomplete')
        for r in funding:
            t=stamp(r['fundingTime']);hour=t.replace(minute=0,second=0,microsecond=0)
            if t.hour not in (0,8,16) or r.get('rateType')!='Regular' or r['symbol']!=symbol:
                raise SourceError('event outside fixed 8h model')
            if START-timedelta(hours=3)<=t<END:
                events.append(dict(pair=pair,time=t,nominal=hour,rate=r['fundingRate'],mark=r['markPrice']))
    return ObservedView(hourly,marks,daily,sorted(events,key=lambda e:(e['time'],e['pair'])),hashlib.sha256(Path(receipt_path).read_bytes()).hexdigest(),volumes=volumes,metadata=metadata)


def funding_records(view,pair):
    """Pure exact event table; no time-grid join or eligibility inference."""
    return [dict(date=e["time"],open_fund=e["rate"],open_mark=e["mark"]) for e in view.funding if e["pair"]==pair]
