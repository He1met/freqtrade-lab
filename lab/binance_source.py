"""Compile retained native Binance responses into the existing Profile format."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import parse_qs, urlsplit

from lab.futures_costs import CONTRACT, validate_events, FuturesCostError, binance_identity, source_identity


def validate_output_path(output: Path) -> Path:
    if output.exists() or output.is_symlink():
        raise FuturesCostError('output exists; replay forbidden')
    parent=output.parent.resolve(strict=True)
    if any((p/'.git').exists() for p in (parent,*parent.parents)):
        raise FuturesCostError('source output must stay outside Git')
    return parent/output.name


def bounded_url(url: str, method: str, lower_ms: int, upper_ms: int, *, pair: str) -> str:
    """Restrict native public transport before any network request is sent."""
    from urllib.parse import urlencode, urlunsplit
    identity = binance_identity(pair)
    p = urlsplit(url)
    if (method != 'GET' or p.scheme != 'https' or p.netloc != 'fapi.binance.com'
            or p.fragment):
        raise FuturesCostError('public Binance transport boundary rejected')
    if p.path == '/fapi/v1/exchangeInfo' and not p.query:
        return url
    paths = {'/fapi/v1/klines': '1d', '/fapi/v1/markPriceKlines': '1h',
             '/fapi/v1/fundingRate': None}
    if p.path not in paths:
        raise FuturesCostError('native endpoint outside acquisition contract')
    q = parse_qs(p.query)
    if (q.get('symbol') != [identity['instrument_id']] or len(q.get('startTime', [])) != 1
            or set(q) - {'symbol', 'startTime', 'endTime', 'interval', 'limit'}
            or (paths[p.path] is not None and q.get('interval') != [paths[p.path]])):
        raise FuturesCostError('native request identity/window invalid')
    start = int(q['startTime'][0])
    if start == 0 and paths[p.path] is not None:
        start = lower_ms
    if not lower_ms <= start < upper_ms:
        raise FuturesCostError('native request outside authorized interval')
    end = min(int(q.get('endTime', [str(upper_ms-1)])[0]), upper_ms-1)
    if end < start:
        raise FuturesCostError('native request end precedes start')
    q.update(startTime=[str(start)], endTime=[str(end)])
    return urlunsplit((p.scheme, p.netloc, p.path, urlencode(q, doseq=True), ''))


def capture_native(root: Path, contract: Mapping[str, Any]) -> tuple[Path, Path]:
    """One native download-data invocation; retain failed evidence, never retry here."""
    import asyncio
    import signal
    import ccxt
    import ccxt.async_support
    from datetime import timedelta
    from freqtrade.main import main
    from lab import bounded_research as pilot
    from scripts.fetch_okx_profile_data import validate_runtime
    validate_runtime()
    profile = contract['profile_snapshot']
    pilot.validate_profile_runtime_contract(profile)
    if profile['exchange'] != 'binance':
        raise FuturesCostError('Binance Profile required')
    pair = binance_identity(profile['pairs'][0])['pair']
    auth = contract.get('holdout_source')
    if auth is not None and auth.get('profile_snapshot') != profile:
        raise FuturesCostError('Holdout source Profile binding changed')
    start, stop = pilot.timerange(auth['holdout_timerange'] if auth else contract['search_timerange'], 'capture')
    if not auth and contract['development_timerange'] is not None:
        stop = pilot.timerange(contract['development_timerange'], 'Development')[1]
    lower = start - timedelta(days=int(contract['pre_roll_candles']))
    lo, hi = int(lower.timestamp()*1000), int(stop.timestamp()*1000)
    if stop > datetime.now(timezone.utc):
        raise FuturesCostError('source window must be fully closed')
    parent = root.parent.resolve(strict=True)
    if any((p/'.git').exists() for p in (parent, *parent.parents)):
        raise FuturesCostError('capture must stay outside Git')
    root.mkdir(mode=0o700)  # exclusive; failed evidence is never silently reused
    raw = root/'raw'; raw.mkdir()
    userdir = root/'user-data'; userdir.mkdir()
    receipts = root/'http-receipts.jsonl'
    config = {'trading_mode':'futures', 'margin_mode':'isolated', 'stake_currency':'USDT',
              'dry_run':True, 'exchange': {'name':'binance', 'key':'', 'secret':'',
                'pair_whitelist':[pair], 'pair_blacklist':[],
                **{key:{'enableRateLimit':True, 'options':{'fetchMarkets':{'types':['linear']}}}
                   for key in ('ccxt_config', 'ccxt_async_config')}}}
    (root/'config.json').write_bytes(pilot.canonical(config))
    count, total = 0, 0
    lock = asyncio.Lock()
    stopped = False
    def guard(url, method):
        nonlocal count
        if stopped or count >= 2000:
            raise FuturesCostError('capture stopped or fetch budget exhausted')
        checked = bounded_url(url, method, lo, hi, pair=pair)
        count += 1
        return checked, count
    def record(exchange, url, index, error=None):
        nonlocal total, stopped
        body = exchange.last_http_response
        data = body.encode() if isinstance(body,str) else b''
        total += len(data)
        name = f'{index:04d}.txt'
        (raw/name).write_bytes(data)
        row = {'url':url, 'body_file':name, 'bytes':len(data),
               'sha256':hashlib.sha256(data).hexdigest(), 'error_class':error,
               'body_representation':'CCXT decoded HTTP response UTF-8',
               'wire_attempt_count':'UNKNOWN', 'utc':datetime.now(timezone.utc).isoformat(),
               'headers':{k:v for k,v in (exchange.last_response_headers or {}).items()
                          if k.lower() in {'date','retry-after','x-mbx-used-weight-1m','content-type'}}}
        with receipts.open('a') as handle:handle.write(json.dumps(row)+'\n')
        disk = sum(p.stat().st_size for p in root.rglob('*') if p.is_file())
        if error or total > 2*1024**3 or disk > 5*1024**3:
            stopped = True
            raise FuturesCostError('capture failed or resource budget exhausted; evidence retained')
    original_sync, original_async = ccxt.Exchange.fetch, ccxt.async_support.Exchange.fetch
    def sync(exchange,url,method='GET',headers=None,body=None):
        url,index=guard(url,method)
        exchange.last_http_response=None;exchange.last_response_headers=None
        try:result=original_sync(exchange,url,method,headers,body)
        except Exception as exc:
            record(exchange,url,index,type(exc).__name__)
            raise
        record(exchange,url,index)
        return result
    async def asynchronous(exchange,url,method='GET',headers=None,body=None):
        async with lock:
            url,index=guard(url,method)
            await asyncio.sleep(0.5)
            exchange.last_http_response=None;exchange.last_response_headers=None
            try:result=await original_async(exchange,url,method,headers,body)
            except Exception as exc:
                record(exchange,url,index,type(exc).__name__)
                raise
            record(exchange,url,index)
            return result
    def timeout(*_):raise FuturesCostError('native acquisition time budget exhausted')
    previous_handler=signal.signal(signal.SIGALRM,timeout)
    try:
        ccxt.Exchange.fetch=sync;ccxt.async_support.Exchange.fetch=asynchronous
        signal.alarm(7200)
        try:
            main(['download-data','--config',str(root/'config.json'),'--userdir',str(userdir),
                  '--datadir',str(root/'native'),'--pairs',pair,'--timeframes','1d',
                  '--timerange',f'{lower:%Y%m%d}-{stop:%Y%m%d}','--no-parallel-download','--no-color'])
        except SystemExit as exc:
            if exc.code not in (0,None):raise FuturesCostError('native download failed') from exc
        if stopped or not receipts.exists():raise FuturesCostError('native capture incomplete')
    finally:
        signal.alarm(0);signal.signal(signal.SIGALRM,previous_handler)
        ccxt.Exchange.fetch=original_sync;ccxt.async_support.Exchange.fetch=original_async
    return receipts, raw


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
    identity = source_identity(source, pair)
    import pandas as pd
    frame = pd.read_feather(data_dir/'futures'/f"{identity['file_stem']}-1h-mark.feather")
    marks = [[int(r.date.value//1_000_000),r.open,r.high,r.low,r.close] for r in frame.itertuples()]
    validate_events(source.get("funding_events", []), marks, symbol=identity['instrument_id'],
                    start_ms=int(start.timestamp()*1000),end_ms=int(stop.timestamp()*1000))


def retained_responses(receipts_path: Path, raw_dir: Path, *, pair: str) -> tuple[dict[str, dict[int, Any]], dict[str, Any]]:
    """Verify decoded-response receipts before reading numeric candle values."""
    identity = binance_identity(pair)
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
            selected=[m for m in rows["symbols"] if m["symbol"]==identity['instrument_id']]
            if len(selected)!=1:raise FuturesCostError("frozen pair market metadata missing")
            expected = {'symbol':identity['instrument_id'], 'baseAsset':identity['base'],
                        'quoteAsset':'USDT', 'marginAsset':'USDT', 'contractType':'PERPETUAL'}
            if any(selected[0].get(k)!=v for k,v in expected.items()):
                raise FuturesCostError("market metadata disagrees with frozen pair")
            if market is not None and market != selected[0]:
                raise FuturesCostError("conflicting market metadata")
            market=selected[0]
            continue
        q=parse_qs(p.query)
        if q.get("symbol")!=[identity['instrument_id']] or not {"startTime","endTime"}<=q.keys():
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
            if key=='funding' and row.get('symbol')!=identity['instrument_id']:
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
    identity = binance_identity(profile['pairs'][0])
    pair = identity['pair']
    authorization=contract.get('holdout_source')
    if authorization is not None and authorization.get('profile_snapshot') != profile:
        raise FuturesCostError('Holdout source Profile binding changed')
    if authorization is None:
        start,split=pilot.timerange(contract['search_timerange'],'Search')
        stop=split if contract['development_timerange'] is None else pilot.timerange(contract['development_timerange'],'Development')[1]
    else:
        start,stop=pilot.timerange(authorization['holdout_timerange'],'Holdout')
        split=start
    pre=int(contract['pre_roll_candles'])
    from datetime import timedelta
    lower=start-timedelta(days=pre)
    lo,score,hi=map(lambda d:int(d.timestamp()*1000),(lower,start,stop))
    rows,raw_market=retained_responses(receipts_path,raw_dir,pair=pair)
    candles={}
    for key,step in [('futures',86400000),('mark',3600000)]:
        selected=[row for t,row in sorted(rows[key].items()) if lo<=t<hi]
        if [r[0] for r in selected]!=list(range(lo,hi,step)):
            raise FuturesCostError(f'{key} source window incomplete')
        candles[key]=selected
    funding=[r for t,r in sorted(rows['funding'].items()) if score<=t<hi]
    validate_events(funding,candles['mark'],symbol=identity['instrument_id'],start_ms=score,end_ms=hi)
    output=validate_output_path(output)
    parent=output.parent
    frames={}
    # Native conversion with no imputation and no arbitrary last-bar drop.
    for key,tf,kind in [('futures','1d','futures'),('mark','1h','mark'),('funding','1h','funding_rate')]:
        values=([[r['fundingTime'],r['fundingRate'],0,0,0,0] for r in funding] if key=='funding'
                else [[r[0],*r[1:6]] for r in candles[key]])
        frame=ohlcv_to_dataframe(values,tf,pair,fill_missing=False,drop_incomplete=False)
        if len(frame)!=len(values):raise FuturesCostError('native conversion collapsed events')
        frames[f"{identity['file_stem']}-{tf}-{kind}.feather"]=frame
    market=ccxt.binance().parse_market(raw_market)
    if (market.get('symbol')!=pair or market.get('id')!=identity['instrument_id']
            or market.get('base')!=identity['base'] or market.get('quote')!='USDT'
            or market.get('settle')!='USDT' or market.get('linear') is not True
            or market.get('swap') is not True):
        raise FuturesCostError('parsed market identity changed')
    tiers_path=Path(freqtrade.exchange.binance.__file__).parent/'binance_leverage_tiers.json'
    tiers=json.loads(tiers_path.read_bytes())[pair]
    if not isinstance(tiers,list) or not tiers or any(t.get('symbol')!=pair for t in tiers):
        raise FuturesCostError('native tiers disagree with frozen pair')
    # Conversion and identity validation precede even temporary output writes.
    import tempfile
    destination=parent/output.name
    output=Path(tempfile.mkdtemp(prefix='.binance-source-',dir=parent))
    try:
        data_dir=output/'data/binance/futures';data_dir.mkdir(parents=True)
        def write(name,value):
            (output/name).write_bytes(pilot.canonical(value))
        def receipt(path,role=None):
            b=(output/path).read_bytes()
            return {**({'role':role} if role else {}),'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()}
        for name,frame in frames.items():frame.to_feather(data_dir/name)
        write('market_snapshot.json',market)
        write('isolated_tiers_snapshot.json',tiers)
        write('config.json',pilot.profile_search_config(profile))
        source={'host':'fapi.binance.com','authentication':'none','exchange':'binance',
                **{k:identity[k] for k in ('pair','instrument_id','pair_family')},'retrieval_receipt':'retrieval_receipt.json',
                'funding_model':CONTRACT,'funding_events':funding}
        if authorization is not None:
            write('funding-events.json', source.pop('funding_events'))
            source['funding_events_receipt'] = receipt('funding-events.json')
        retrieval={'host':'fapi.binance.com','authentication':'none','pair':pair,'instrument_id':identity['instrument_id'],
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
                                'config':'config.json','development_timerange':contract.get('search_timerange', (authorization or {}).get('development_timerange')),
                                'holdout_timerange':contract.get('development_timerange', (authorization or {}).get('holdout_timerange')),'timeframe':'1d',
                                'profile_acquisition':({k:contract[k] for k in pilot._profile_acquisition_contract_fields(contract)} if authorization is None else {})},
                'files':files,'local_only_files':local}
        if authorization is not None:
            provenance['contract'].pop('profile_acquisition')
            provenance['contract']['holdout_source']=authorization
        write('retained-data-provenance.json',provenance)
        result={'provenance_sha256':receipt('retained-data-provenance.json')['sha256'],
                'retrieval_receipt_sha256':receipt('retrieval_receipt.json')['sha256']}
        pilot._publish_directory_exclusive(output,destination)
        return result
    finally:
        import shutil
        if output.exists():
            shutil.rmtree(output)
