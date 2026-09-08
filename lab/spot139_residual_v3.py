"""B-only development controller V3. V2 and its exposed results remain immutable."""
from dataclasses import dataclass,field
from decimal import Decimal as D
from lab.spot139_model import Wallet,Rule,Episode,signal,floor_grid,ceil_grid


@dataclass
class SpotResidualV3:
    rules:dict
    fee:D=D('.001')
    slip:D=D('.0006')
    wallet:Wallet=field(default_factory=Wallet)
    episodes:dict=field(default_factory=dict)
    residual:set=field(default_factory=set)
    exits:set=field(default_factory=set)
    pending:dict=field(default_factory=dict)
    seen_nonpositive:set=field(default_factory=set)
    marks:dict=field(default_factory=dict)
    marked_at:dict=field(default_factory=dict)
    started:dict=field(default_factory=dict)
    stops:dict=field(default_factory=dict)
    basis:dict=field(default_factory=dict)
    fills:list=field(default_factory=list)
    events:list=field(default_factory=list)
    block_reasons:dict=field(default_factory=dict)
    warning_pending:set=field(default_factory=set)
    last_hour:int|None=None
    realized:D=D(0)
    cost_added:D=D(0)
    cost_released:D=D(0)
    sale_proceeds:D=D(0)
    execution_error:bool=False

    def __post_init__(self):
        if not 1<=len(self.rules)<=2:raise ValueError('B supports at most two fixed assets')
        self.episodes={s:Episode() for s in self.rules}

    def equity(self):return self.wallet.cash+sum((q*self.marks[s] for s,q in self.wallet.inventory.items()),D(0))
    def risk_cell(self):return D('.0025') if self.wallet.warned else D('.005')
    @property
    def blocked(self):return bool(self.block_reasons) or self.execution_error

    def quote(self,s,price,requested=None):
        r=self.rules[s];held=self.wallet.inventory.get(s,D(0))
        q=floor_grid(min(held,r.max_qty,held if requested is None else requested),r.step)
        p=floor_grid(price*(1-self.slip),r.price_tick)
        reason='SELLABLE'
        if p<=0:reason='INVALID_EXECUTION_PRICE'
        elif q<r.min_qty or q==0:reason='MIN_QTY_OR_LOT'
        elif q*p<r.min_notional:reason='MIN_NOTIONAL'
        return q,p,reason

    def observe(self,hour):
        warned=self.wallet.warned
        eq,dd,risk_pass=self.wallet.observe(self.marks)
        if self.wallet.warned and not warned:self.warning_pending.update(s for s,q in self.wallet.inventory.items() if q>0)
        return dict(equity=eq,observed_dd=dd,risk_pass_observed=risk_pass,real_dd='UNKNOWN')

    def finish_episode(self,s,hour,reason):
        e=self.episodes[s]
        if e.active:self.events.append(dict(hour=hour,symbol=s,event='ACTIVE_EPISODE_ENDED_WITH_INVENTORY',reason=reason,remaining=self.wallet.inventory.get(s,D(0))))
        e.stopped_or_expired();e.armed=s in self.seen_nonpositive
        self.exits.discard(s);self.warning_pending.discard(s)
        if self.wallet.inventory.get(s,D(0))>0:self.residual.add(s)
        else:self.residual.discard(s)

    def classify_exit_remainder(self,s,hour):
        held=self.wallet.inventory.get(s,D(0))
        if held==0:self.finish_episode(s,hour,'FLAT');return
        q,p,reason=self.quote(s,self.marks[s])
        # No observed-result threshold: an unsellable remainder's total-loss risk
        # must fit this B asset's original (possibly halved) stop-risk cell.
        residual_risk=held*self.marks[s]
        if reason in ('MIN_QTY_OR_LOT','MIN_NOTIONAL') and residual_risk<=max(D(0),self.equity())*self.risk_cell():
            self.finish_episode(s,hour,reason)
        elif reason!='SELLABLE':self.block_reasons[s]='UNSELLABLE_ACTIVE_RISK:'+reason
        # A sellable remainder is still a pending active exit (e.g. maxQty chunk).

    def sell(self,s,hour,requested=None,reason='EXIT'):
        q,p,rejection=self.quote(s,self.marks[s],requested)
        if rejection!='SELLABLE':
            if requested is None:self.classify_exit_remainder(s,hour)
            return False
        held=self.wallet.inventory[s];old_basis=self.basis[s]
        fee=ceil_grid(q*p*self.fee,self.rules[s].quote_fee_step);proceeds=q*p-fee
        if proceeds<0:self.execution_error=True;raise ValueError('fee exceeds proceeds')
        released=old_basis if q==held else floor_grid(old_basis*q/held,self.rules[s].quote_fee_step)
        self.wallet.inventory[s]-=q;self.wallet.cash+=proceeds;self.basis[s]-=released
        self.realized+=proceeds-released;self.cost_released+=released;self.sale_proceeds+=proceeds
        self.wallet.fees_quote_equivalent+=fee
        self.fills.append(dict(hour=hour,symbol=s,side='sell',quantity=q,price=p,fee_quote=fee,basis_released=released,reason=reason))
        if requested is None or self.wallet.inventory[s]==0:self.classify_exit_remainder(s,hour)
        return True

    def refresh_blocks(self,hour):
        self.block_reasons={}
        eq=self.equity();total=sum((q*self.marks[s] for s,q in self.wallet.inventory.items()),D(0))
        for s,q in self.wallet.inventory.items():
            if q<=0:continue
            if self.marked_at[s]!=hour:self.block_reasons[s]='STALE_INVENTORY';continue
            if q*self.marks[s]>D('.4')*eq:self.block_reasons[s]='ASSET_NOTIONAL_CAP'
            if s in self.exits:
                rejection=self.quote(s,self.marks[s])[2]
                self.block_reasons[s]='UNRESOLVED_ACTIVE_EXIT' if rejection=='SELLABLE' else 'UNSELLABLE_ACTIVE_RISK:'+rejection
            if s in self.residual and q*self.marks[s]>max(D(0),eq)*self.risk_cell():self.block_reasons[s]='RESIDUAL_TOTAL_LOSS_EXCEEDS_RISK_CELL'
        if total>D('.8')*eq:self.block_reasons['portfolio']='TOTAL_NOTIONAL_CAP'

    def on_hour(self,hour,opens,closed_daily=None,completed_lows=None):
        if self.last_hour is not None and hour!=self.last_hour+1:raise ValueError('clock must include missing hours')
        if set(opens)-set(self.rules):raise ValueError('unbound asset')
        self.last_hour=hour
        for s,p in opens.items():
            if p<=0:raise ValueError('invalid original open')
            self.marks[s]=p;self.marked_at[s]=hour
        self.block_reasons={};state=self.observe(hour)
        # Cleanup is unconditional, before signals, with a real current open.
        # Never buy to clear residuals. No future/absent open can execute.
        for s in sorted(self.residual):
            if s in opens and self.quote(s,opens[s])[2]=='SELLABLE':self.sell(s,hour,reason='RESIDUAL_BECAME_SELLABLE')
        for s,e in self.episodes.items():
            if not e.active:continue
            if hour-self.started[s]>=84*24:self.exits.add(s)
            low=(completed_lows or {}).get(s)
            if (low is not None and low<=self.stops[s]) or (s in opens and opens[s]<=self.stops[s]):self.exits.add(s)
            if s in self.exits and s in opens:self.sell(s,hour,reason='ACTIVE_EXIT')
        eq=self.equity();total=sum((q*self.marks[s] for s,q in self.wallet.inventory.items()),D(0))
        factor=min(D(1),D('.8')*eq/total) if total else D(1)
        for s,q in list(self.wallet.inventory.items()):
            if q<=0 or s not in opens or s in self.exits:continue
            target=min(q*factor,D('.4')*eq/opens[s])
            if s in self.warning_pending:target=min(target,q/2)
            if target<q:
                reduction=ceil_grid(q-target,self.rules[s].step)
                if not self.sell(s,hour,reduction,'RISK_REDUCTION'):
                    self.exits.add(s);self.sell(s,hour,reason='FULL_EXIT_IF_REDUCTION_UNSELLABLE')
                self.warning_pending.discard(s)
        state=self.observe(hour);self.refresh_blocks(hour)
        if hour%24==0:
            for s,e in self.episodes.items():
                self.pending.pop(s,None)
                sig=signal(hour//24-1,(closed_daily or {}).get(s,{}),'B')
                if sig is None:continue
                if not sig['positive']:
                    self.seen_nonpositive.add(s);e.armed=True
                    if e.active:self.exits.add(s)
                elif e.armed and not e.active:
                    self.pending[s]=dict(hour=hour+1,units=self.equity()*self.risk_cell()/sig['stop_distance'],distance=sig['stop_distance'])
        due={s:v for s,v in self.pending.items() if v['hour']==hour and s in opens}
        self.pending={s:v for s,v in self.pending.items() if v['hour']>hour}
        if self.blocked or self.wallet.halted:return self.status(state)
        eq=self.equity();desired={};prices={}
        for s,v in due.items():
            if self.episodes[s].active or not self.episodes[s].armed:continue
            held=self.wallet.inventory.get(s,D(0));r=self.rules[s]
            p=ceil_grid(opens[s]*(1+self.slip),r.price_tick);prices[s]=p
            # Residual can be lost entirely; deduct that risk and its notional
            # before sizing a genuine signal-driven buy.
            old_value=held*opens[s]
            risk_units=max(D(0),eq*self.risk_cell()-old_value)/v['distance']
            desired[s]=max(D(0),min(v['units'],risk_units,(D('.4')*eq-old_value)/p,r.max_qty))
        requested=sum((q*prices[s] for s,q in desired.items()),D(0))
        held_value=sum((q*self.marks[s] for s,q in self.wallet.inventory.items()),D(0))
        free=max(D(0),min(self.wallet.cash,D('.8')*eq-held_value));scale=min(D(1),free/requested) if requested else D(1)
        for s in sorted(desired):
            r=self.rules[s];p=prices[s];q=floor_grid(desired[s]*scale,r.step)
            if q<r.min_qty or q*p<r.min_notional:continue
            fee=ceil_grid(q*self.fee,r.base_fee_step)
            if fee>=q:continue
            self.wallet.cash-=q*p;self.wallet.inventory[s]=self.wallet.inventory.get(s,D(0))+q-fee
            self.basis[s]=self.basis.get(s,D(0))+q*p;self.cost_added+=q*p
            self.wallet.fees_quote_equivalent+=fee*p
            self.episodes[s].active=True;self.episodes[s].armed=False;self.seen_nonpositive.discard(s)
            self.residual.discard(s);self.stops[s]=p-due[s]['distance'];self.started[s]=hour
            self.fills.append(dict(hour=hour,symbol=s,side='buy',quantity=q,price=p,fee_base=fee,reason='NORMAL_SIGNAL'))
        if self.wallet.cash<0:self.execution_error=True;raise ValueError('borrowed cash')
        state=self.observe(hour);self.refresh_blocks(hour)
        return self.status(state)

    def status(self,state):
        return dict(**state,blocked=self.blocked,reasons=dict(self.block_reasons),residual=sorted(self.residual))

    def terminal(self,hour):
        out=self.wallet.terminal_mark(self.marks,self.fee,self.slip)
        out.update(realized_pnl=self.realized,unrealized_pnl=out['marked_inventory']-sum(self.basis.values(),D(0)),basis=dict(self.basis),cost_added=self.cost_added,cost_released=self.cost_released,sale_proceeds=self.sale_proceeds,residual=sorted(self.residual),active={s:e.active for s,e in self.episodes.items()},blocked=self.blocked,block_reasons=self.block_reasons,mark_age_hours={s:hour-self.marked_at[s] for s,q in self.wallet.inventory.items() if q>0},real_drawdown='UNKNOWN',version='B_RESIDUAL_V3_DEVELOPMENT_ONLY')
        return out
