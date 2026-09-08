"""Observe the single V3 loop; reporting never creates a second strategy pass."""
from collections import Counter,defaultdict
from decimal import Decimal as D
from datetime import datetime,timezone
from lab.spot139_model import signal
from lab.spot139_feed import history_at
from lab.spot139_residual_v3 import SpotResidualV3


def create_model(rules,job):
    if job['mode']!='B':raise ValueError('V3 B only')
    return SpotResidualV3(rules,fee=D(job['fee_each_side']),slip=D(job['slippage_each_side']))


class RunReport:
    def __init__(self,model):
        self.model=model;self.orders=[];self.episodes=[];self.cycle=Counter();self.active_ids={}
        self.realized=defaultdict(lambda:D(0));self.month_profit=defaultdict(lambda:D(0));self.episode_profit=defaultdict(lambda:D(0))
        self.gate_days=Counter();self.no_positive=Counter();self.block_hours=Counter();self.block_any=0
        self.stale_hours=Counter();self.stale_any=0;self.max_age=Counter();self.max_dd=D(0);self.latches={}
        self.first_hour=None;self.last_hour=None;self.negative_pending=set()

    def before(self,hour,daily,opens,lows):
        m=self.model;causes={}
        for s,e in m.episodes.items():
            reasons=[]
            if s in self.negative_pending:reasons.append('NONPOSITIVE_SIGNAL')
            if e.active:
                if hour-m.started[s]>=84*24:reasons.append('EXPIRY_84_DAYS')
                if s in lows and lows[s]<=m.stops[s]:reasons.append('STOP_COMPLETED_LOW')
                if s in opens and opens[s]<=m.stops[s]:reasons.append('STOP_CURRENT_OPEN')
            causes[s]=reasons
        if hour%24==0:
            for s in m.rules:
                sig=signal(hour//24-1,(daily or {}).get(s,{}),'B')
                if sig is None:self.gate_days[s]+=1
                elif not sig['positive']:self.no_positive[s]+=1
        return causes

    def after(self,hour,fills,events,causes,mapper,snapshot):
        m=self.model;self.first_hour=hour if self.first_hour is None else self.first_hour;self.last_hour=hour
        for fill in fills:
            s=fill['symbol']
            if fill['side']=='buy':
                self.cycle[s]+=1;self.active_ids[s]=f'{s}/{self.cycle[s]}'
                self.episodes.append(dict(hour=hour,symbol=s,episode=self.active_ids[s],event='START',remaining_inventory=m.wallet.inventory[s]))
                self.negative_pending.discard(s)
            key=self.active_ids.get(s,f'{s}/residual-before-first-episode')
            reason=causes[s] if fill['reason']=='ACTIVE_EXIT' else [fill['reason']]
            self.orders.append(dict(**fill,episode=key,exit_causes=reason if fill['side']=='sell' else []))
            if fill['side']=='sell':
                profit=fill['quantity']*fill['price']-fill['fee_quote']-fill['basis_released']
                self.realized[s]+=profit;self.episode_profit[key]+=profit
                month=datetime.fromtimestamp(hour*3600,timezone.utc).strftime('%Y-%m')
                self.month_profit[month]+=profit
        for event in events:
            s=event['symbol'];self.episodes.append(dict(**event,episode=self.active_ids.get(s),exit_causes=causes[s] or ['RISK_OR_RESIDUAL_EXIT']))
            self.negative_pending.discard(s)
        for s in m.exits:
            if s in m.seen_nonpositive:self.negative_pending.add(s)
        stale=False;positions={}
        for s in m.rules:
            q=m.wallet.inventory.get(s,D(0));age=hour-m.marked_at[s] if s in m.marked_at else None
            if q>0 and age:
                stale=True;self.stale_hours[s]+=1;self.max_age[s]=max(self.max_age[s],age)
            positions[s]=dict(inventory=q,basis=m.basis.get(s,D(0)),active_quantity=q if m.episodes[s].active else D(0),residual_quantity=q if s in m.residual else D(0),active=m.episodes[s].active,mark=m.marks.get(s),mark_age_hours=age)
        self.stale_any+=int(stale)
        reasons=set(m.block_reasons.values())
        if m.wallet.halted:reasons.add('DRAWDOWN_15_HALT')
        if m.execution_error:reasons.add('EXECUTION_ACCOUNTING_ERROR')
        if reasons:self.block_any+=1
        self.block_hours.update(reasons)
        equity=m.equity();dd=(m.wallet.peak-equity)/m.wallet.peak;self.max_dd=max(self.max_dd,dd)
        for name,value in [('warning10',m.wallet.warned),('halt15',m.wallet.halted),('observed20_breach',dd>D('.20'))]:
            if value:self.latches.setdefault(name,hour)
        snapshot(dict(hour=hour,cash=m.wallet.cash,equity=equity,peak=m.wallet.peak,observed_drawdown=dd,positions=positions,blocked=bool(reasons),block_reasons=sorted(reasons),warning10=m.wallet.warned,halt15=m.wallet.halted,real_drawdown='UNKNOWN'))

    def result(self):
        m=self.model;assets={}
        for s in m.rules:
            q=m.wallet.inventory.get(s,D(0));marked=q*m.marks.get(s,D(0));basis=m.basis.get(s,D(0))
            assets[s]=dict(buys=sum(x['symbol']==s and x['side']=='buy' for x in self.orders),sells=sum(x['symbol']==s and x['side']=='sell' for x in self.orders),episode_starts=self.cycle[s],episode_ends=sum(x['symbol']==s and x['event']!='START' for x in self.episodes),realized=self.realized[s],unrealized=marked-basis,net=self.realized[s]+marked-basis,remaining_inventory=q,remaining_basis=basis)
        def concentration(values):
            positives=[v for v in values.values() if v>0];total=sum(positives,D(0))
            return dict(values=dict(values),largest_positive_share=max(positives)/total if total else None,denominator='sum of positive realized contributions; not independent samples')
        return dict(modeled_terminal=m.terminal(self.last_hour),orders=self.orders,episode_events=self.episodes,assets=assets,realized_by_month=concentration(self.month_profit),realized_by_episode=concentration(self.episode_profit),observed_open_drawdown=self.max_dd,real_drawdown='UNKNOWN',risk_latch_first_hour=self.latches,gate_ineligible_calendar_days={s:self.gate_days[s] for s in m.rules},gate_note='85-calendar dependency failure, not a count of actual positive signals denied',nonpositive_signal_days=dict(self.no_positive),global_new_risk_block_hours=self.block_any,block_hours_by_reason=dict(self.block_hours),stale_hours_any_asset=self.stale_any,stale_hours_by_asset=dict(self.stale_hours),maximum_mark_age_hours=dict(self.max_age),hours_observed=0 if self.first_hour is None else self.last_hour-self.first_hour+1,independent_qualification=False,native_matching_statistics_identical=False)


def run_loop(model,mapper,hourly,daily,start,end,report,snapshot):
    allowed={(s,h):bar[0][0] for s,bars in hourly.items() for h,bar in bars.items()}
    for hour in range(start,end):
        opens={s:bars[hour][0][0] for s,bars in hourly.items() if hour in bars}
        lows={s:bars[hour-1][0][2] for s,bars in hourly.items() if hour-1 in bars}
        history=history_at(hour,hourly,daily) if hour%24==0 else None
        causes=report.before(hour,history,opens,lows);n=len(model.fills);e=len(model.events)
        model.on_hour(hour,opens,history,lows)
        for fill in model.fills[n:]:mapper.apply(fill,allowed)
        mapper.compare_model(model)
        report.after(hour,model.fills[n:],model.events[e:],causes,mapper,snapshot)
    return report.result()
