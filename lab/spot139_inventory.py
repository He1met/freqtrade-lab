"""SOURCE_INVENTORY_V3: retain unexplained time anomalies; no execution admission."""
from pathlib import Path
import json
import time
from lab.portfolio_source import Budget, SourceError, digest, write_json
from lab.spot139_source import TRAIN, END, SYMBOLS, validate_page, metadata
from lab.spot139_continuation import GapStream


class InventoryStream(GapStream):
    def __init__(self):
        super().__init__()
        self.saw_recovery=True  # V3 does not claim or require a certified recovery.

    def affect(self,kind,t):
        self.anomalies.append({'kind':kind,'open_ms':t,'cause':'UNKNOWN'})
        self.affected.add(t);self.incomplete_days.add(t//86400000)

    def consume(self,page):
        try:super().consume(page)
        except SourceError as exc:
            # V3 permits a short final response when real missing slots reduce
            # the row count, but still requires the exact endpoint open.
            if str(exc)!='premature short tail' or self.cursor!=END:raise

    def finish(self):
        if self.cursor!=END:raise SourceError('inventory endpoint incomplete')
        start_day=TRAIN//86400000;end_day=END//86400000
        available={str(n):sum(not any(day-(n-1)<=bad<=day for bad in self.incomplete_days) for day in range(start_day,end_day)) for n in (85,273)}
        missing=sorted(a['open_ms'] for a in self.anomalies if a['kind']=='MISSING')
        spans=[]
        for t in missing:
            if spans and spans[-1]['end_exclusive_ms']==t:spans[-1]['end_exclusive_ms']=t+3600000
            else:spans.append(dict(start_ms=t,end_exclusive_ms=t+3600000))
        return dict(hourly_rows=self.rows,missing_hours=len(missing),gap_spans=spans,
            longest_missing_hours=max([(s['end_exclusive_ms']-s['start_ms'])//3600000 for s in spans] or [0]),
            short_candles=sum(a['kind']=='SHORT' for a in self.anomalies),anomalies=self.anomalies,
            incomplete_days=sorted(self.incomplete_days),complete_training_days=730-len(self.incomplete_days),
            available_training_decision_days_by_dependency=available,dependency_rule='CONSERVATIVE_DATA_AVAILABILITY_NOT_PROFIT_OR_QUALIFICATION',
            end_covered=True,all_anomaly_causes='UNKNOWN',execution_admitted=False)


class InventoryBudget(Budget):
    def __init__(self,path,root,parent,now=time.time):
        if len(parent['attempts'])!=5 or parent['charged_bytes']!=472114 or parent['status']!='BLOCKED_DATA':raise SourceError('old inventory counters')
        super().__init__(path,root,dict(gets=39,total_bytes=16777216,response_bytes=1048576,seconds=895),now)
        self.state.update(attempts=parent['attempts'],charged_bytes=472114,historical_attempts=parent['historical_attempts'],
            historical_bytes=14603929,prior_spot_seconds=3.841052293777466,native_calls=0)
        write_json(self.path,self.state)

    def reserve(self,endpoint,params):
        if self.state['status']!='STARTED':raise SourceError('inventory terminal no restart')
        return super().reserve(endpoint,params)


def reuse(paths):
    out={}
    for key,entry in paths.items():
        raw=Path(entry['path']).read_bytes()
        if digest(raw)!=entry['sha256']:raise SourceError('retained source SHA mismatch')
        out[key]=json.loads(raw)
    if set(out)!={'metadata','warmup_BTC','warmup_ETH','BTC_page1','BTC_page2'}:raise SourceError('exact five inputs required')
    metadata(out['metadata'])
    for k in ['warmup_BTC','warmup_ETH']:validate_page(out[k],1585785600000,86400000,274)
    return out


def collect_inventory(fetch,retained,btc_cursor):
    streams={s:InventoryStream() for s in SYMBOLS}
    streams['BTCUSDT'].consume(retained['BTC_page1']);streams['BTCUSDT'].consume(retained['BTC_page2'])
    if streams['BTCUSDT'].cursor!=btc_cursor:raise SourceError('manifest BTC cursor mismatch')
    result={}
    for symbol,cap in [('BTCUSDT',16),('ETHUSDT',18)]:
        stream=streams[symbol];calls=0
        while stream.cursor<END:
            if calls>=cap:raise SourceError('inventory page budget')
            page=fetch.get('klines',dict(symbol=symbol,interval='1h',startTime=stream.cursor,endTime=END-1,limit=1000));calls+=1
            stream.consume(page)
        result[symbol]=dict(warmup_daily_rows=274,new_requests=calls,**stream.finish())
    return dict(status='SOURCE_INVENTORY_COMPLETE_NOT_EXECUTION_ADMITTED',symbols=result,complete_data_pass=False,
                native_calls=0,economic_result=None,independent_qualification=False)
