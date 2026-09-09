"""S-only transport guard/receipt around unchanged native download-data entrypoint."""
import asyncio
import hashlib
import json
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit, parse_qs, urlencode

import ccxt
import ccxt.async_support
from freqtrade.main import main

assert ccxt.__version__ == '4.5.68'
ROOT = Path(__file__).resolve().parent
START, END = 1688342400000, 1721001600000
RAW = ROOT/'native-full-s-raw'
RAW.mkdir(exist_ok=True)
assert not list(RAW.iterdir()), 'sample recovery must preserve prior raw evidence'
(ROOT/'user-data').mkdir(exist_ok=True)
prior = [json.loads(line) for p in ROOT.glob('*http-receipts.jsonl') for line in p.read_text().splitlines()]
count = len(prior)
total = sum(r['bytes'] for r in prior)
lock = asyncio.Lock()

def guard(url, method):
    global count
    p = urlsplit(url)
    if method != 'GET' or p.scheme != 'https' or p.hostname not in {'fapi.binance.com','dapi.binance.com','api.binance.com'}:
        raise RuntimeError('public endpoint boundary rejected')
    allowed = {'/api/v3/exchangeInfo','/fapi/v1/exchangeInfo','/dapi/v1/exchangeInfo','/fapi/v1/fundingRate','/fapi/v1/markPriceKlines','/fapi/v1/klines'}
    if p.path not in allowed:
        raise RuntimeError('unexpected endpoint: '+p.path)
    if not p.path.endswith('exchangeInfo'):
        q = parse_qs(p.query)
        if q.get('symbol') != ['BCHUSDT'] or 'startTime' not in q:
            raise RuntimeError('identity/startTime missing')
        start = int(q['startTime'][0])
        # Native Binance new-pair discovery asks since=0. Restrict discovery to
        # the registered interval as well; this does not assert listing date.
        if start == 0 and p.path in {'/fapi/v1/klines','/fapi/v1/markPriceKlines'}:
            start = START
            q['startTime'] = [str(START)]
        if start < START or start >= END:
            raise RuntimeError('request outside registered sample')
        q['endTime'] = [str(min(int(q.get('endTime',[END-1])[0]), END-1))]
        url = urlunsplit((p.scheme,p.netloc,p.path,urlencode(q,doseq=True),''))
    count += 1
    if count > 2000:
        raise RuntimeError('HTTP budget exceeded')
    return url, count

def receipt(ex, url, number, error=None):
    global total
    body = ex.last_http_response
    raw = body.encode() if isinstance(body,str) else b''
    total += len(raw)
    if total > 2*1024**3:
        raise RuntimeError('byte budget exceeded')
    name = f'{number:04d}.txt'
    (RAW/name).write_bytes(raw)
    r = {'url':url,'body_file':name,'body_representation':'CCXT decoded HTTP response UTF-8','sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),'utc':datetime.now(timezone.utc).isoformat(),'error_class':error,'headers':{k:v for k,v in (ex.last_response_headers or {}).items() if k.lower() in {'content-type','retry-after','date','x-mbx-used-weight-1m'}}}
    with (ROOT/'native-full-s-http-receipts.jsonl').open('a') as f:
        f.write(json.dumps(r)+'\n')
    return r

original_async = ccxt.async_support.Exchange.fetch
async def wrapped_async(self, url, method='GET', headers=None, body=None):
    async with lock:
        url, n = guard(url,method)
        await asyncio.sleep(0.5)
        self.last_http_response = None
        self.last_response_headers = None
        try:
            result = await original_async(self,url,method,headers,body)
        except Exception as exc:
            r = receipt(self,url,n,type(exc).__name__)
            # Stop access denials here; no unbounded native retry loop.
            if isinstance(exc,(ccxt.RateLimitExceeded,ccxt.DDoSProtection)):
                raise RuntimeError('rate limited; inspect Retry-After before bounded recovery') from exc
            raise
        receipt(self,url,n)
        return result

original_sync = ccxt.Exchange.fetch
def wrapped_sync(self,url,method='GET',headers=None,body=None):
    url,n = guard(url,method)
    self.last_http_response = None
    self.last_response_headers = None
    try:
        result = original_sync(self,url,method,headers,body)
    except Exception as exc:
        receipt(self,url,n,type(exc).__name__)
        raise
    receipt(self,url,n)
    return result

ccxt.async_support.Exchange.fetch = wrapped_async
ccxt.Exchange.fetch = wrapped_sync
signal.signal(signal.SIGALRM,lambda *_: (_ for _ in ()).throw(RuntimeError('native time budget exceeded')))
signal.alarm(7200)
main(['download-data','--config',str(ROOT/'download-config.json'),'--userdir',str(ROOT/'user-data'),'--datadir',str(ROOT/'native-full-s'),'--pairs','BCH/USDT:USDT','--timeframes','1d','--timerange','20230703-20240715','--no-parallel-download','--no-color'])
