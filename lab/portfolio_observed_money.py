"""Exact model money at hour and funding-event observation points; no matcher."""
from itertools import groupby
from fractions import Fraction
from decimal import Decimal,localcontext
from datetime import timedelta
from lab.portfolio_causal import PAIRS
from lab.portfolio_source import SourceError


def number(value):return Fraction(str(value))


def decimal(value):
    with localcontext() as context:
        context.prec=60
        return Decimal(value.numerator)/Decimal(value.denominator)


def validate_orders(orders):
    seen=set()
    for o in orders:
        t=o['filled_at']
        if t.minute or t.second or t.microsecond:raise SourceError('non-hour-open fill invalidates model')
        if o['id'] in seen:raise SourceError('duplicate actual order')
        seen.add(o['id'])
        if o['pair'] not in PAIRS or o['side'] not in ('buy','sell') or number(o['amount'])<=0 or number(o['price'])<=0:
            raise SourceError('invalid actual fill')


def inventory(orders,at,*,inclusive=True):
    q={p:Fraction(0) for p in PAIRS}
    for o in orders:
        if o['filled_at']<at or (inclusive and o['filled_at']==at):
            q[o['pair']]+=number(o['amount'])*(1 if o['side']=='buy' else -1)
    return q


def event_cash(event,orders):
    # Caller processes an event only after its timestamp; no future orders read.
    h=event['nominal'];t=event['time'];p=event['pair']
    prior=inventory(orders,h,inclusive=False)[p]
    after=inventory(orders,t)[p]
    r,m=number(event['rate']),number(event['mark'])
    if m<=0:raise SourceError('missing or invalid associated mark')
    values=(-prior*r*m,-after*r*m)
    return (values[1] if prior==after else min(Fraction(0),*values)),prior,after


def money(orders,marks,fee,slip,funding):
    cash=Fraction(1000);q={p:Fraction(0) for p in PAIRS};cost=Fraction(0)
    for o in orders:
        signed=number(o['amount'])*(1 if o['side']=='buy' else -1)
        notional=abs(signed)*number(o['price'])
        c=notional*(number(fee)+number(slip));cost+=c
        cash-=signed*number(o['price'])+c;q[o['pair']]+=signed
    equity=cash+funding+sum(q[p]*number(marks[p]) for p in PAIRS)
    return dict(equity=equity,cash=cash+funding,inventory=q,cost=cost,funding=funding)


class EventAccount:
    def __init__(self,view,fee,slip):
        self.view=view;self.fee=fee;self.slip=slip;self.points=[];self.done=set();self.funding=Fraction(0)
        self.peak=Fraction(1000);self.max_drawdown=Fraction(0);self.halted=False;self.warning=False;self.last=None

    def observe(self,orders,at,marks,*,native_funding=0):
        if self.last is not None and at<=self.last:raise SourceError('nonincreasing risk observation')
        available=[o for o in orders if o['filled_at']<at]
        validate_orders(available)
        due=[e for e in self.view.funding if e['time']<at and (e['pair'],e['time']) not in self.done]
        for event_time,group in groupby(due,key=lambda e:e['time']):
            group=list(group);event=group[0]
            occurred=[o for o in available if o['filled_at']<=event_time]
            flows={};before={};after={}
            for e in group:
                key=(e['pair'],e['time'])
                if key in self.done:raise SourceError('duplicate funding event')
                flow,b,a=event_cash(e,occurred);self.funding+=flow;self.done.add(key)
                flows[e['pair']]=flow;before[e['pair']]=b;after[e['pair']]=a
            event_marks={p:self.view.marks[p][event['nominal']-timedelta(hours=1)].close for p in PAIRS}
            for known in self.view.funding:
                if known['time']>event_time:break
                if known['nominal']==event['nominal']:event_marks[known['pair']]=known['mark']
            point=money(occurred,event_marks,self.fee,self.slip,self.funding)
            self._risk(event_time,point,'FUNDING_EVENT',flows,before,after)
        current=money(available,marks,self.fee,self.slip,self.funding)
        self._risk(at,current,'HOUR_PRE_ACTION')
        self.last=at
        current['native_funding_delta']=self.funding-number(native_funding)
        return current

    def _risk(self,at,point,kind,flow=Fraction(0),before=None,after=None):
        self.peak=max(self.peak,point['equity'])
        dd=(self.peak-point['equity'])/self.peak
        self.max_drawdown=max(self.max_drawdown,dd)
        self.warning|=dd>=Fraction(1,10);self.halted|=dd>=Fraction(3,20)
        self.points.append(dict(time=at,kind=kind,**point,flow=flow,before=before,after=after,
                               max_drawdown=self.max_drawdown,risk_pass=self.max_drawdown<=Fraction(1,5)))
