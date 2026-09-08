"""Issue139-only public spot collector. No strategy, native or database imports."""
import json
import math
import time
import urllib.parse
import urllib.request
from pathlib import Path
from lab.portfolio_source import Budget, SourceError, NoRedirect, request_deadline, digest, write_json, finite

START, TRAIN, END = 1585785600000, 1609459200000, 1672531200000
SYMBOLS = ('BTCUSDT', 'ETHUSDT')
LIMITS = dict(gets=39, total_bytes=16*1024*1024, response_bytes=1024*1024, seconds=900)


def encoded(obj):
    return (json.dumps(obj, sort_keys=True, separators=(',', ':'))+'\n').encode()


class SpotBudget(Budget):
    def __init__(self, path, root, parent, now=time.time):
        if len(parent['attempts']) != 73 or parent['charged_bytes'] != 14603929:
            raise SourceError('unexpected historical acquisition counters')
        super().__init__(path, root, LIMITS.copy(), now)
        self.state.update(historical_attempts=parent['attempts'], historical_bytes=parent['charged_bytes'],
                          historical_seconds=130+parent['active_seconds_new'], native_calls=0)
        write_json(self.path, self.state)

    def reserve(self, endpoint, params):
        if self.state['status'] != 'STARTED':
            raise SourceError('terminal budget cannot continue')
        return super().reserve(endpoint, params)


def request_url(endpoint, params):
    if endpoint == 'exchangeInfo':
        if params != {'symbols':json.dumps(list(SYMBOLS), separators=(',', ':'))}:
            raise SourceError('metadata identity')
    elif endpoint == 'klines':
        if set(params) != {'symbol','interval','startTime','endTime','limit'} or params['symbol'] not in SYMBOLS or params['limit'] != 1000:
            raise SourceError('kline identity')
        interval=params['interval']; start=params['startTime']; end=params['endTime']
        if interval == '1d': valid = start == START and end == TRAIN-1
        elif interval == '1h': valid = TRAIN <= start < END and start % 3600000 == 0 and end == END-1
        else: valid = False
        if not valid: raise SourceError('request outside exact window')
    else: raise SourceError('endpoint rejected')
    return 'https://api.binance.com/api/v3/'+endpoint+'?'+urllib.parse.urlencode(params)


class SpotFetcher:
    def __init__(self, budget, root, verify=lambda:None):
        self.budget=budget;self.root=Path(root);self.verify=verify;self.last=None
        self.opener=urllib.request.build_opener(NoRedirect)

    def get(self, endpoint, params):
        url=request_url(endpoint,params)
        if self.last is not None: time.sleep(max(0,1-(time.monotonic()-self.last)))
        self.verify()
        row=self.budget.reserve(endpoint,params);self.last=time.monotonic()
        body=bytearray();deadline=time.monotonic()+min(20,self.budget.remaining_time())
        try:
            req=urllib.request.Request(url,headers={'Accept-Encoding':'identity','User-Agent':'freqtrade-lab-spot139/1'})
            with request_deadline(max(.001,deadline-time.monotonic())), self.opener.open(req,timeout=max(.001,deadline-time.monotonic())) as response:
                if response.status!=200 or response.headers.get('Content-Encoding','identity')!='identity':
                    raise SourceError('HTTP status/encoding')
                while True:
                    if len(body)>=LIMITS['response_bytes']: raise SourceError('response ceiling')
                    chunk=response.read1(min(65536,LIMITS['response_bytes']-len(body)))
                    body.extend(chunk)
                    if not chunk: break
            raw=bytes(body)
            (self.root/'raw'/f'{row["number"]:03d}-{endpoint}.json').write_bytes(raw)
            value=json.loads(raw)
            self.verify()
            self.budget.finish(row,size=len(raw),status=200,sha256=digest(raw))
            return value
        except BaseException as exc:
            self.budget.finish(row,size=max(row['charged_bytes'],len(body)),status=getattr(exc,'code','FAILED'),error=type(exc).__name__)
            self.budget.terminal('BLOCKED_DATA')
            raise


def metadata(info):
    if not isinstance(info,dict) or not isinstance(info.get('symbols'),list): raise SourceError('metadata shape')
    out={}
    known={'PRICE_FILTER','PERCENT_PRICE','PERCENT_PRICE_BY_SIDE','LOT_SIZE','MIN_NOTIONAL','NOTIONAL','MARKET_LOT_SIZE',
           'ICEBERG_PARTS','MAX_NUM_ORDERS','MAX_NUM_ALGO_ORDERS','MAX_NUM_ICEBERG_ORDERS','MAX_POSITION',
           'TRAILING_DELTA','MAX_NUM_ORDER_AMENDS','MAX_NUM_ORDER_LISTS'}
    for symbol in SYMBOLS:
        rows=[r for r in info['symbols'] if r.get('symbol')==symbol]
        if len(rows)!=1:raise SourceError('symbol missing/duplicate')
        r=rows[0]
        if r.get('status')!='TRADING' or r.get('quoteAsset')!='USDT' or r.get('baseAsset')!=symbol[:-4] or r.get('isSpotTradingAllowed') is not True:
            raise SourceError('not exact spot identity')
        filters=r.get('filters',[]); types=[f.get('filterType') for f in filters]
        if not {'LOT_SIZE','PRICE_FILTER'}.issubset(types) or not ({'MIN_NOTIONAL','NOTIONAL'}&set(types)) or len(types)!=len(set(types)):
            raise SourceError('required order filters missing/duplicate')
        for f in filters:
            if f['filterType'] not in known: raise SourceError('unknown order filter semantics: '+str(f['filterType']))
            for k in ['minQty','maxQty','stepSize','minPrice','maxPrice','tickSize','minNotional','maxNotional']:
                if k in f and finite(f[k])<0: raise SourceError('negative filter value')
        # Unknown ordinary response fields are retained/ignored, never treated as filters.
        out[symbol]={k:r.get(k) for k in ['symbol','status','baseAsset','quoteAsset','isSpotTradingAllowed','baseAssetPrecision','quoteAssetPrecision','baseCommissionPrecision','quoteCommissionPrecision','filters','orderTypes']}
    return out


def validate_page(page, cursor, step, expected):
    if not isinstance(page,list) or len(page)!=expected: raise SourceError('short/extra page')
    for i,row in enumerate(page):
        if not isinstance(row,list) or len(row)!=12 or type(row[0]) is not int or row[0]!=cursor+i*step or row[6]!=row[0]+step-1:
            raise SourceError('UTC coverage/gap/duplicate/schema')
        o,h,lo,c=[finite(v,positive=True) for v in row[1:5]]
        if not lo<=min(o,c)<=max(o,c)<=h:raise SourceError('invalid OHLC')
        if finite(row[5])<0 or finite(row[7])<0:raise SourceError('negative volume')


def series(fetch, symbol, interval):
    start,end,step=(START,TRAIN,86400000) if interval=='1d' else (TRAIN,END,3600000)
    count=(end-start)//step;cursor=start;result=[]
    for _ in range(math.ceil(count/1000)):
        expected=min(1000,(end-cursor)//step)
        page=fetch.get('klines',dict(symbol=symbol,interval=interval,startTime=cursor,endTime=end-1,limit=1000))
        validate_page(page,cursor,step,expected);result.extend(page);cursor+=expected*step
    if cursor!=end:raise SourceError('incomplete source')
    return result


def collect(fetch):
    rules=metadata(fetch.get('exchangeInfo',{'symbols':json.dumps(list(SYMBOLS),separators=(',',':'))}))
    counts={s:{} for s in SYMBOLS}
    for s in SYMBOLS: counts[s]['warmup_daily_rows']=len(series(fetch,s,'1d'))
    for s in SYMBOLS: counts[s]['training_hourly_rows']=len(series(fetch,s,'1h'))
    return dict(status='STRUCTURE_PASS_NOT_MARKET_APPROVAL',symbols=counts,filters=rules,
                historical_rules='UNKNOWN',funding='NOT_APPLICABLE_SPOT_NO_BORROW',native_calls=0,economic_result=None)
