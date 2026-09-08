"""Synthetic-only spot semantics; not wired to native or market data.

Closed UTC daily decisions at t activate no earlier than t+1h. The first
positive eligible signal may enter. Stop/84-day expiry locks reentry until a
nonpositive daily signal is observed, followed by a positive one. A source end
never creates a fill: inventory is marked separately from hypothetical exit
cost. Decimal arithmetic is a model, not certified historic fee rounding.
"""
from dataclasses import dataclass, field
from decimal import Decimal as D, ROUND_DOWN


@dataclass
class Episode:
    armed: bool = True
    active: bool = False
    pending_hour: int | None = None

    def decision(self, closed_hour, positive):
        if closed_hour % 24: raise ValueError('daily UTC close required')
        if not positive:
            self.armed=True
            self.pending_hour=None
            return 'EXIT_NEXT_HOUR' if self.active else 'CASH'
        if self.armed and not self.active:
            self.pending_hour=closed_hour+1
        return 'HOLD_OR_PENDING'

    def activate(self, hour):
        if self.pending_hour is None or hour!=self.pending_hour: return False
        self.active=True;self.armed=False;self.pending_hour=None
        return True

    def stopped_or_expired(self):
        self.active=False;self.armed=False;self.pending_hour=None


def floor_grid(value, step):
    if step<=0 or value<0:raise ValueError('invalid grid')
    return (value/step).to_integral_value(rounding=ROUND_DOWN)*step


@dataclass
class Wallet:
    cash: D = D('1000')
    inventory: dict = field(default_factory=dict)
    peak: D = D('1000')
    warned: bool = False
    halted: bool = False
    fees_quote_equivalent: D = D('0')

    def observe(self, prices):
        equity=self.cash+sum((q*prices[s] for s,q in self.inventory.items()),D(0))
        self.peak=max(self.peak,equity)
        dd=(self.peak-equity)/self.peak
        self.warned |= dd>=D('.10');self.halted |= dd>=D('.15')
        return equity,dd,dd<=D('.20')

    def buy(self,symbol,requested,price,step,min_qty,min_notional,fee):
        if self.halted:return D(0)
        q=floor_grid(min(requested,self.cash/price),step)
        if q<min_qty or q*price<min_notional:return D(0)
        self.cash-=q*price
        # Fee charged in received base; do not also deduct its quote value.
        self.inventory[symbol]=self.inventory.get(symbol,D(0))+q*(1-fee)
        self.fees_quote_equivalent+=q*price*fee
        return q

    def sell(self,symbol,price,step,min_qty,min_notional,fee):
        q=floor_grid(self.inventory.get(symbol,D(0)),step)
        if q<min_qty or q*price<min_notional:return D(0)
        self.inventory[symbol]-=q
        self.cash+=q*price*(1-fee)
        self.fees_quote_equivalent+=q*price*fee
        return q

    def terminal_mark(self,prices,exit_fee,exit_slip):
        marked=sum((q*prices[s] for s,q in self.inventory.items()),D(0))
        return dict(cash=self.cash,marked_inventory=marked,equity=self.cash+marked,
                    estimated_exit_cost=marked*(exit_fee+exit_slip),
                    inventory=dict(self.inventory),synthetic_exit_executed=False)

# Reviewed extensions below remain a reference model, never a native fill source.
from decimal import ROUND_UP, localcontext
from statistics import median


def ceil_grid(value, step):
    if step<=0 or value<0:raise ValueError('invalid conservative rounding')
    return (value/step).to_integral_value(rounding=ROUND_UP)*step


@dataclass(frozen=True)
class Rule:
    step: D
    min_qty: D
    min_notional: D
    max_qty: D
    base_fee_step: D
    quote_fee_step: D


def signal(closed_day, daily, mode):
    """daily keys are UTC calendar day numbers, values closed complete OHLC.

    closed_day is the last day ending at the current UTC midnight. The caller
    cannot supply a future key. Missing entries are not compacted or filled.
    """
    if any(day>closed_day for day in daily):raise ValueError('future daily value supplied')
    n=273 if mode=='C' else 85
    if not all(closed_day-i in daily for i in range(n)):return None
    closes={day:D(str(bar[3])) for day,bar in daily.items()}
    atr=sum((max(D(str(daily[j][1]))-D(str(daily[j][2])),abs(D(str(daily[j][1]))-closes[j-1]),abs(D(str(daily[j][2]))-closes[j-1])) for j in range(closed_day-19,closed_day+1)),D(0))/20
    if atr<=0:return None
    multiplier=D(1)
    if mode=='C':
        with localcontext() as ctx:
            ctx.prec=50
            def sigma(end):
                xs=[(closes[j]/closes[j-1]).ln() for j in range(end-19,end+1)]
                avg=sum(xs,D(0))/20
                return (sum(((x-avg)**2 for x in xs),D(0))/19).sqrt()
            current=sigma(closed_day)
            if current<=0:return None
            multiplier=min(D(1),median([sigma(j) for j in range(closed_day-252,closed_day)])/current)
    return dict(positive=closes[closed_day]>closes[closed_day-84],stop_distance=3*atr,multiplier=multiplier)


@dataclass
class SpotReference:
    """Bounded intent/account state machine for synthetic correctness checks.

    No data reader, price filling, scheduler, strategy search or native engine.
    on_hour receives only source-confirmed current opens and completed history.
    """
    mode: str
    rules: dict
    fee: D = D('.001')
    slip: D = D('.0006')
    wallet: Wallet = field(default_factory=Wallet)
    episodes: dict = field(default_factory=dict)
    pending: dict = field(default_factory=dict)
    exits: set = field(default_factory=set)
    marks: dict = field(default_factory=dict)
    marked_at: dict = field(default_factory=dict)
    stop_prices: dict = field(default_factory=dict)
    started: dict = field(default_factory=dict)
    blocked: bool = False
    fills: list = field(default_factory=list)
    last_hour: int | None = None
    realized: D = D(0)
    basis: dict = field(default_factory=dict)
    warning_pending: set = field(default_factory=set)
    c_baseline: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.mode not in ('B','A-BTC','A-ETH','C','half-B'):raise ValueError('unfrozen mode')
        self.episodes={s:Episode() for s in self.rules}

    def selected(self,s):return self.mode not in ('A-BTC','A-ETH') or s.startswith(self.mode[2:])

    def equity(self):return self.wallet.cash+sum((q*self.marks[s] for s,q in self.wallet.inventory.items()),D(0))

    def _sell(self,s,price,hour,requested=None):
        rule=self.rules[s];held=self.wallet.inventory.get(s,D(0))
        q=floor_grid(min(held,held if requested is None else requested,rule.max_qty),rule.step)
        p=price*(1-self.slip)
        if q<rule.min_qty or q*p<rule.min_notional:
            self.blocked=True;return
        fee=ceil_grid(q*p*self.fee,rule.quote_fee_step)
        proceeds=q*p-fee
        if proceeds<0:raise ValueError('fee exceeds proceeds')
        fraction=q/held;basis=self.basis.get(s,D(0))*fraction
        self.realized+=proceeds-basis;self.basis[s]=self.basis.get(s,D(0))-basis
        self.wallet.inventory[s]=held-q;self.wallet.cash+=proceeds
        self.wallet.fees_quote_equivalent+=fee
        self.fills.append(dict(hour=hour,symbol=s,side='sell',quantity=q,price=p,fee_quote=fee))
        if requested is None:
            self.episodes[s].stopped_or_expired()
            if self.wallet.inventory[s]>0:self.blocked=True  # dust remains explicit
            else:self.exits.discard(s)

    def on_hour(self,hour,opens,closed_daily=None,completed_lows=None):
        if self.last_hour is not None and hour!=self.last_hour+1:raise ValueError('clock must visit missing hours without prices')
        self.last_hour=hour
        if set(opens)-set(self.rules):raise ValueError('unbound asset')
        for s,p in opens.items():
            if p<=0:raise ValueError('invalid source open')
            self.marks[s]=p;self.marked_at[s]=hour
        if not set(self.wallet.inventory).issubset(self.marks):raise ValueError('unmarked inventory')
        was_warned=self.wallet.warned
        eq,dd,risk_pass=self.wallet.observe(self.marks)
        if self.wallet.warned and not was_warned:self.warning_pending.update(s for s,q in self.wallet.inventory.items() if q>0)
        stale=any(q>0 and self.marked_at.get(s)!=hour for s,q in self.wallet.inventory.items())
        # Recovery marks and latches precede any action. Missing opens cannot fill.
        for s,q in list(self.wallet.inventory.items()):
            if not q:continue
            if hour-self.started[s]>=84*24:self.exits.add(s)
            low=(completed_lows or {}).get(s)
            if (low is not None and low<=self.stop_prices[s]) or (s in opens and opens[s]<=self.stop_prices[s]):self.exits.add(s)
            if s in opens and s in self.exits:self._sell(s,opens[s],hour)
        # Hard caps and warning only reduce existing quantities, never rescale up.
        eq=self.equity();total=sum((q*self.marks[s] for s,q in self.wallet.inventory.items()),D(0))
        total_factor=min(D(1),D('.8')*eq/total) if total else D(1)
        for s,q in list(self.wallet.inventory.items()):
            if q<=0 or s not in opens or s in self.exits:continue
            target=min(q*total_factor,D('.4')*eq/opens[s])
            if s in self.warning_pending:target=min(target,q/D(2))
            if target<q:
                reduction=q-target
                if floor_grid(reduction,self.rules[s].step)==0:self._sell(s,opens[s],hour)
                else:self._sell(s,opens[s],hour,ceil_grid(reduction,self.rules[s].step))
                self.warning_pending.discard(s)
        if hour%24==0:
            for s in self.rules:
                if not self.selected(s):continue
                daily=(closed_daily or {}).get(s,{})
                sig=signal(hour//24-1,daily,self.mode)
                self.pending.pop(s,None)
                if sig is None:continue
                e=self.episodes[s]
                if not sig['positive']:
                    e.armed=True
                    if self.wallet.inventory.get(s,D(0))>0:self.exits.add(s)
                    continue
                if self.mode=='C' and self.wallet.inventory.get(s,D(0))>0 and s in opens:
                    # At most reduce by current factor; never restore old size.
                    target=min(self.wallet.inventory[s],self.c_baseline[s]*sig['multiplier']*(D('.5') if self.wallet.warned else D(1)))
                    if target<self.wallet.inventory[s]:self._sell(s,opens[s],hour,ceil_grid(self.wallet.inventory[s]-target,self.rules[s].step))
                if e.armed and not e.active and not self.wallet.inventory.get(s,D(0)):
                    mult=(D('.5') if self.mode=='half-B' else D(1))*sig['multiplier']*(D('.5') if self.wallet.warned else D(1))
                    cell=D('.01') if self.mode.startswith('A-') else D('.005')
                    self.pending[s]=dict(hour=hour+1,units=eq*cell*mult/sig['stop_distance'],distance=sig['stop_distance'],multiplier=sig['multiplier'])
        eligible={s:v for s,v in self.pending.items() if v['hour']==hour and s in opens}
        # No delayed catch-up entry after a missing activation open.
        self.pending={s:v for s,v in self.pending.items() if v['hour']>hour}
        if stale or self.blocked or self.wallet.halted:return dict(stale=stale,risk_pass_observed=risk_pass,real_dd='UNKNOWN')
        equity=self.equity();desired={}
        for s,v in eligible.items():
            p=opens[s]*(1+self.slip);desired[s]=min(v['units'],D('.4')*equity/p,self.rules[s].max_qty)
        requested=sum((q*opens[s]*(1+self.slip) for s,q in desired.items()),D(0))
        held=sum((q*self.marks[s] for s,q in self.wallet.inventory.items()),D(0))
        free=max(D(0),min(self.wallet.cash,D('.8')*equity-held))
        scale=min(D(1),free/requested) if requested else D(1)
        for s in sorted(desired):
            rule=self.rules[s];p=opens[s]*(1+self.slip);q=floor_grid(desired[s]*scale,rule.step)
            if q<rule.min_qty or q*p<rule.min_notional:continue
            fee_base=ceil_grid(q*self.fee,rule.base_fee_step)
            if fee_base>=q:continue
            self.wallet.cash-=q*p;self.wallet.inventory[s]=q-fee_base;self.basis[s]=q*p
            self.wallet.fees_quote_equivalent+=fee_base*p
            self.episodes[s].active=True;self.episodes[s].armed=False
            self.stop_prices[s]=p-eligible[s]['distance'];self.started[s]=hour
            self.c_baseline[s]=(q-fee_base)/(eligible[s]['multiplier'] or D(1))
            self.fills.append(dict(hour=hour,symbol=s,side='buy',quantity=q,price=p,fee_base=fee_base))
        if self.wallet.cash<0:raise ValueError('borrowed cash')
        return dict(stale=stale,risk_pass_observed=risk_pass,real_dd='UNKNOWN')

    def terminal(self,hour):
        out=self.wallet.terminal_mark(self.marks,self.fee,self.slip)
        out.update(realized_pnl=self.realized,unrealized_pnl=out['marked_inventory']-sum(self.basis.values(),D(0)),
                   mark_age_hours={s:hour-self.marked_at[s] for s in self.wallet.inventory if self.wallet.inventory[s]>0},
                   real_max_drawdown='UNKNOWN',engine='REFERENCE_MODEL_NOT_FREQTRADE_MATCHING')
        return out
