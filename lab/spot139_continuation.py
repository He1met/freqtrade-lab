"""Single gap-aware source continuation. No strategy or scoring imports."""
import json
import time
from pathlib import Path
from lab.portfolio_source import Budget, SourceError, digest, write_json, finite
from lab.spot139_source import TRAIN, END, SYMBOLS, metadata, validate_page
from lab.spot139_gap_proposal import HOUR, KNOWN_START, KNOWN_END


class GapStream:
    def __init__(self):
        self.cursor=TRAIN;self.rows=0;self.affected=set();self.anomalies=[];self.saw_recovery=False
        self.incomplete_days=set()

    def affect(self,kind,t):
        self.anomalies.append({'kind':kind,'open_ms':t})
        if not KNOWN_START<=t<KNOWN_END:raise SourceError('QUARANTINE_UNKNOWN_GAP_STOP')
        self.affected.add(t);self.incomplete_days.add(t//86400000)
        if len(self.affected)>2:raise SourceError('exception cap exceeded')

    def consume(self,page):
        if not isinstance(page,list) or not page or len(page)>1000:raise SourceError('empty/oversized page')
        page_cursor=self.cursor
        nominal_remaining=(END-page_cursor)//HOUR
        for r in page:
            if not isinstance(r,list) or len(r)!=12 or type(r[0]) is not int or type(r[6]) is not int:
                raise SourceError('row schema')
            opened,closed=r[0],r[6]
            if opened%HOUR or opened<self.cursor or opened>=END or not opened<=closed<opened+HOUR:
                raise SourceError('unordered/duplicate/outside candle')
            for missing in range(self.cursor,opened,HOUR):self.affect('MISSING',missing)
            if closed!=opened+HOUR-1:self.affect('SHORT',opened)
            o,h,lo,c=[finite(v,positive=True) for v in r[1:5]]
            if not lo<=min(o,c)<=max(o,c)<=h or finite(r[5])<0 or finite(r[7])<0:raise SourceError('OHLC/volume invalid')
            if opened==KNOWN_END:self.saw_recovery=True
            self.cursor=opened+HOUR;self.rows+=1
        if len(page)<1000 and (nominal_remaining>1000 or self.cursor!=END):raise SourceError('premature short tail')
        if self.cursor>KNOWN_END and self.affected and not self.saw_recovery:raise SourceError('missing 05 recovery')

    def finish(self):
        if self.cursor!=END or (self.affected and not self.saw_recovery):raise SourceError('end/recovery incomplete')
        # Count decision dates affected by conservative t-84..t dependency.
        start_day=TRAIN//86400000;end_day=END//86400000
        lost=sum(any(day-84<=bad<=day for bad in self.incomplete_days) for day in range(start_day,end_day))
        return dict(hourly_rows=self.rows,affected_slots=sorted(self.affected),anomalies=self.anomalies,
                    incomplete_daily_days=sorted(self.incomplete_days),signal_days_unavailable_due_to_85_day_rule=lost,
                    rule_is_conservative_design_not_mathematical_requirement=True)


class ContinuationBudget(Budget):
    def __init__(self,path,root,parent,now=time.time):
        if len(parent['attempts'])!=4 or parent['charged_bytes']!=290928 or parent['status']!='BLOCKED_DATA':
            raise SourceError('v1 counters/terminal changed')
        super().__init__(path,root,dict(gets=39,total_bytes=16777216,response_bytes=1048576,seconds=896),now)
        self.state.update(attempts=parent['attempts'],charged_bytes=parent['charged_bytes'],
            historical_attempts=parent['historical_attempts'],historical_bytes=14603929,
            prior_spot_bytes=290928,prior_spot_seconds=3.4234702587127686,native_calls=0)
        write_json(self.path,self.state)

    def reserve(self,endpoint,params):
        if self.state['status']!='STARTED':raise SourceError('terminal no restart')
        return super().reserve(endpoint,params)


def reuse(root,hashes):
    out={}
    for name,expected in hashes.items():
        raw=(Path(root)/'raw'/name).read_bytes()
        if digest(raw)!=expected:raise SourceError('reused response hash mismatch')
        out[name]=json.loads(raw)
    if len(out)!=4:raise SourceError('exact four retained responses required')
    metadata(out['001-exchangeInfo.json'])
    for name in ['002-klines.json','003-klines.json']:validate_page(out[name],1585785600000,86400000,274)
    return out


def collect_continuation(fetch,retained):
    result={};streams={s:GapStream() for s in SYMBOLS}
    streams['BTCUSDT'].consume(retained['004-klines.json'])
    if streams['BTCUSDT'].cursor!=1613062800000:raise SourceError('retained BTC cursor changed')
    for symbol,cap in [('BTCUSDT',17),('ETHUSDT',18)]:
        stream=streams[symbol];requests=0
        while stream.cursor<END:
            if requests>=cap:raise SourceError('asset page budget')
            page=fetch.get('klines',dict(symbol=symbol,interval='1h',startTime=stream.cursor,endTime=END-1,limit=1000))
            requests+=1
            stream.consume(page)
        result[symbol]=dict(warmup_daily_rows=274,requests_new=requests,**stream.finish())
    return dict(status='EXPLORATORY_SOURCE_WITH_UNOBSERVED_INTERVALS',symbols=result,
                full_data_pass=False,real_max_drawdown='UNKNOWN',economic_result=None,native_calls=0)
