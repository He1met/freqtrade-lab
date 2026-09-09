"""Compile retained native Binance responses into the existing Profile format."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import parse_qs, urlsplit

from lab.futures_costs import CONTRACT, validate_events, FuturesCostError


def phase_source(source: Mapping[str, Any], start: datetime, stop: datetime) -> dict[str, Any]:
    result = dict(source)
    if source.get("exchange") == "binance":
        if source.get("funding_model") != CONTRACT or not isinstance(source.get("funding_events"), list):
            raise FuturesCostError("Binance funding contract is missing")
        lo, hi = int(start.timestamp()*1000), int(stop.timestamp()*1000)
        result["funding_events"] = [dict(r) for r in source["funding_events"] if lo <= r["fundingTime"] < hi]
    return result


def source_fields(exchange: str) -> set[str]:
    base = {"host", "authentication", "pair", "instrument_id", "pair_family"}
    return base | ({"exchange", "funding_model", "funding_events"} if exchange == "binance" else set())


def validate_source(source: Mapping[str, Any], data_dir: Path, pair: str,
                    start: datetime, stop: datetime) -> None:
    if source.get("exchange") != "binance":
        return
    if source.get("funding_model") != CONTRACT or pair != "BCH/USDT:USDT":
        raise FuturesCostError("Binance funding identity/model invalid")
    import pandas as pd
    frame = pd.read_feather(data_dir/'futures/BCH_USDT_USDT-1h-mark.feather')
    marks = [[int(r.date.value//1_000_000),r.open,r.high,r.low,r.close] for r in frame.itertuples()]
    validate_events(source.get("funding_events", []), marks, symbol="BCHUSDT",
                    start_ms=int(start.timestamp()*1000),end_ms=int(stop.timestamp()*1000))


def retained_responses(receipts_path: Path, raw_dir: Path) -> tuple[dict[str, dict[int, Any]], dict[str, Any]]:
    """Verify decoded-response receipts before reading numeric candle values."""
    series: dict[str, dict[int, Any]] = {"futures":{},"mark":{},"funding":{}}
    market = None
    records = [json.loads(line) for line in receipts_path.read_text().splitlines()]
    for rec in records:
        p=urlsplit(rec["url"])
        if p.scheme != "https" or p.hostname != "fapi.binance.com" or rec.get("error_class") is not None:
            raise FuturesCostError("retained request is not successful public Binance data")
        name=rec["body_file"]
        if not isinstance(name,str) or Path(name).name!=name:
            raise FuturesCostError("retained response path is unsafe")
        path=raw_dir/name
        if path.is_symlink() or not path.is_file():
            raise FuturesCostError("retained response is not a regular file")
        data=path.read_bytes()
        if len(data)!=rec["bytes"] or hashlib.sha256(data).hexdigest()!=rec["sha256"]:
            raise FuturesCostError("retained response digest mismatch")
        rows=json.loads(data)
        if p.path=="/fapi/v1/exchangeInfo":
            selected=[m for m in rows["symbols"] if m["symbol"]=="BCHUSDT"]
            if len(selected)!=1:raise FuturesCostError("BCH market metadata missing")
            market=selected[0]
            continue
        q=parse_qs(p.query)
        if q.get("symbol")!=["BCHUSDT"] or not {"startTime","endTime"}<=q.keys():
            raise FuturesCostError("retained request lacks bounded identity")
        lo,hi=int(q["startTime"][0]),int(q["endTime"][0])
        key={"/fapi/v1/klines":"futures","/fapi/v1/markPriceKlines":"mark","/fapi/v1/fundingRate":"funding"}.get(p.path)
        if key is None:raise FuturesCostError("retained endpoint unsupported")
        if key!='funding' and q.get('interval')!=[{'futures':'1d','mark':'1h'}[key]]:
            raise FuturesCostError("retained timeframe unsupported")
        for row in rows:
            t=row['fundingTime'] if key=='funding' else row[0]
            if isinstance(t,bool) or not isinstance(t,int) or not lo<=t<=hi:
                raise FuturesCostError("response escapes requested window")
            if key=='funding' and row.get('symbol')!='BCHUSDT':
                raise FuturesCostError("funding response identity mismatch")
            if t in series[key] and row!=series[key][t]:
                raise FuturesCostError("conflicting paginated response")
            series[key][t]=row
    if market is None:raise FuturesCostError("market metadata absent")
    return series,market


def compile_source(output: Path, receipts_path: Path, raw_dir: Path,
                   contract: Mapping[str, Any]) -> dict[str, str]:
    """No network, DB writes, strategy runs, or invented source candles."""
    from lab import bounded_research as pilot
    from freqtrade.data.converter import ohlcv_to_dataframe
    import freqtrade.exchange.binance
    import ccxt
    from scripts.fetch_okx_profile_data import validate_runtime
    runtime=validate_runtime()
    profile=contract['profile_snapshot']
    pilot.validate_profile_runtime_contract(profile)
    if profile['exchange']!='binance':raise FuturesCostError('Binance Profile required')
    start,split=pilot.timerange(contract['search_timerange'],'Search')
    stop=split if contract['development_timerange'] is None else pilot.timerange(contract['development_timerange'],'Development')[1]
    pre=int(contract['pre_roll_candles'])
    from datetime import timedelta
    lower=start-timedelta(days=pre)
    lo,score,hi=map(lambda d:int(d.timestamp()*1000),(lower,start,stop))
    rows,raw_market=retained_responses(receipts_path,raw_dir)
    candles={}
    for key,step in [('futures',86400000),('mark',3600000)]:
        selected=[row for t,row in sorted(rows[key].items()) if lo<=t<hi]
        if [r[0] for r in selected]!=list(range(lo,hi,step)):
            raise FuturesCostError(f'{key} source window incomplete')
        candles[key]=selected
    funding=[r for t,r in sorted(rows['funding'].items()) if score<=t<hi]
    validate_events(funding,candles['mark'],symbol='BCHUSDT',start_ms=score,end_ms=hi)
    if output.exists() or output.is_symlink():raise FuturesCostError('output exists; replay forbidden')
    # All source/schema checks above precede output creation.
    output.mkdir(mode=0o700)
    data_dir=output/'data/binance/futures';data_dir.mkdir(parents=True)
    def write(name,value):
        (output/name).write_bytes(pilot.canonical(value))
    def receipt(path,role=None):
        b=(output/path).read_bytes()
        return {**({'role':role} if role else {}),'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()}
    # Native conversion with no imputation and no arbitrary last-bar drop.
    for key,tf,kind in [('futures','1d','futures'),('mark','1h','mark'),('funding','1h','funding_rate')]:
        values=([[r['fundingTime'],r['fundingRate'],0,0,0,0] for r in funding] if key=='funding'
                else [[r[0],*r[1:6]] for r in candles[key]])
        frame=ohlcv_to_dataframe(values,tf,'BCH/USDT:USDT',fill_missing=False,drop_incomplete=False)
        if len(frame)!=len(values):raise FuturesCostError('native conversion collapsed events')
        frame.to_feather(data_dir/f'BCH_USDT_USDT-{tf}-{kind}.feather')
    market=ccxt.binance().parse_market(raw_market)
    if market['symbol']!='BCH/USDT:USDT':raise FuturesCostError('parsed market identity changed')
    write('market_snapshot.json',market)
    tiers_path=Path(freqtrade.exchange.binance.__file__).parent/'binance_leverage_tiers.json'
    tiers=json.loads(tiers_path.read_bytes())['BCH/USDT:USDT']
    write('isolated_tiers_snapshot.json',tiers)
    write('config.json',pilot.profile_search_config(profile))
    source={'host':'fapi.binance.com','authentication':'none','exchange':'binance','instrument_id':'BCHUSDT',
            'pair':'BCH/USDT:USDT','pair_family':'BCH-USDT','retrieval_receipt':'retrieval_receipt.json',
            'funding_model':CONTRACT,'funding_events':funding}
    retrieval={'host':'fapi.binance.com','authentication':'none','pair':'BCH/USDT:USDT','instrument_id':'BCHUSDT',
               'data_window':{'start_utc':lower.isoformat(),'end_exclusive_utc':stop.isoformat(),
                              'fully_closed_at_fetch':True,'development_start_utc':start.isoformat(),
                              'holdout_start_utc':split.isoformat(),'startup_candles_required':pre},
               'retained_response_receipts_sha256':hashlib.sha256(receipts_path.read_bytes()).hexdigest(),
               'tiers_origin':{'kind':'locked_native_dry_run_snapshot','sha256':hashlib.sha256(tiers_path.read_bytes()).hexdigest(),
                               'historical_exchange_tiers':'UNKNOWN'},
               'conversion':'native converter fill_missing=False/drop_incomplete=False; original downloader files retained separately'}
    write('retrieval_receipt.json',retrieval)
    implementations={'producer/fetch_binance_profile_data.py':Path(__file__).parents[1]/'scripts/fetch_binance_profile_data.py',
                     'producer/binance_source.py':Path(__file__),
                     'producer/futures_costs.py':Path(__file__).parent/'futures_costs.py'}
    (output/'producer').mkdir()
    files={'config.json':receipt('config.json','profile_bound_search_config'),
           'retrieval_receipt.json':receipt('retrieval_receipt.json','local_public_retrieval_receipt')}
    for name,path in implementations.items():
        (output/name).write_bytes(path.read_bytes());files[name]=receipt(name,'profile_acquisition_and_validation')
    local={p.relative_to(output).as_posix():receipt(p.relative_to(output)) for p in data_dir.iterdir()}
    for name in ['market_snapshot.json','isolated_tiers_snapshot.json']:local[name]=receipt(name)
    provenance={'schema':'freqtrade-lab-retained-okx-data-v1','portable_retained_fixture':False,'source':source,
                'freqtrade':{'version':'2026.7','tag':runtime['freqtrade_tag'],'commit':runtime['freqtrade_commit'],
                             'dependencies':{k:runtime['versions'][k] for k in ('ccxt','pandas','pyarrow','python')}},
                'contract':{'data_dir':'data/binance','market_snapshot':'market_snapshot.json','leverage_tiers':'isolated_tiers_snapshot.json',
                            'config':'config.json','development_timerange':contract['search_timerange'],
                            'holdout_timerange':contract['development_timerange'],'timeframe':'1d',
                            'profile_acquisition':{k:contract[k] for k in pilot._profile_acquisition_contract_fields(contract)}},
                'files':files,'local_only_files':local}
    write('retained-data-provenance.json',provenance)
    return {'provenance_sha256':receipt('retained-data-provenance.json')['sha256'],
            'retrieval_receipt_sha256':receipt('retrieval_receipt.json')['sha256']}
