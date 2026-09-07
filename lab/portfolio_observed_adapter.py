"""Native callbacks share one observed source, exact model ledger and V3 control."""
from datetime import datetime,timedelta,timezone
from decimal import Decimal,ROUND_HALF_UP
from fractions import Fraction
from functools import wraps
from lab.portfolio_causal import PAIRS,State
from lab.portfolio_risk_v2 import RiskState
from lab.portfolio_observed_source import load_view,RECEIPT_SHA
from lab.portfolio_observed_money import EventAccount,decimal,number,inventory
from lab.portfolio_observed_control import ObservedState,advance_observed
from lab.portfolio_short import configuration
from lab.portfolio_source import SourceError

INVALID_EXITS={'liquidation','stop_loss','trailing_stop_loss','force_exit'}
TAGS={'observed_open','observed_target_close','observed_reduce','observed_increase'}


def audit_order_source(view,orders):
    for o in orders:
        t=o['filled_at'];p=o['pair']
        if o.get('exit_reason') in INVALID_EXITS:raise SourceError('MODEL_INVALID native non-open exit')
        if o.get('tag') not in TAGS:raise SourceError('MODEL_INVALID unknown order provenance')
        if t.minute or t.second or t.microsecond or not view.start<=t<view.end:
            raise SourceError('MODEL_INVALID fill timestamp outside hourly model')
        tick=Decimal(next(r['tickSize'] for r in view.metadata[p]['filters'] if r['filterType']=='PRICE_FILTER'))
        expected=(Decimal(str(view.hourly[p][t].open))/tick).to_integral_value(rounding=ROUND_HALF_UP)*tick
        if number(o['price'])!=number(expected):raise SourceError('MODEL_INVALID non-open/tick fill price')


def episode_id(ep):
    e=ep.entry
    return f'{e.pair}/{e.family}/{e.direction}/{ep.started.isoformat()}'


def family_intents(risk):
    scale=(Decimal('.5') if risk.mode=='half-risk-B' else Decimal(1))*(Decimal('.5') if risk.warning else Decimal(1))
    multipliers=dict(risk.multipliers)
    return [dict(id=episode_id(ep),pair=ep.entry.pair,family=ep.entry.family,direction=ep.entry.direction,
                 raw_signed_units=ep.entry.direction*ep.entry.units,risk_scale=scale,
                 C_multiplier=multipliers.get(ep.entry.pair,Decimal(0)) if risk.mode=='C' else Decimal(1),
                 status='LOGICAL_INTENT_NOT_ACTUAL_FILL_OR_SAMPLE') for ep in risk.episodes]


def fail_closed(method):
    @wraps(method)
    def call(self,*args,**kwargs):
        self.raise_if_invalid()
        try:
            return method(self,*args,**kwargs)
        except Exception as exc:
            self.observed_failure=f'{type(exc).__name__}: {exc}'
            raise
    return call


class ObservedCallbacks:
    INTERFACE_VERSION=3
    timeframe='1h';can_short=True;startup_candle_count=1;process_only_new_candles=True
    minimal_roi={};stoploss=-.99;position_adjustment_enable=True;max_entry_position_adjustment=-1;use_exit_signal=True

    def raise_if_invalid(self):
        if getattr(self,'observed_failure',None):
            raise SourceError('MODEL_INVALID sticky callback failure: '+self.observed_failure)

    @fail_closed
    def bot_start(self,**kwargs):
        if self.config.get('observed_source_sha256')!=RECEIPT_SHA or self.config.get('dry_run') is not True:
            raise SourceError('real observed input binding required')
        from lab.portfolio_observed_prepare import verify_semantics,SEMANTICS_SHA
        verify_semantics()
        if self.config.get('observed_semantics_sha256')!=SEMANTICS_SHA:raise SourceError('semantics binding mismatch')
        self.view=load_view();self.job=configuration(self.config['observed_mode'],self.config['observed_cost'])
        self.state=ObservedState(RiskState(State(self.job['mode'])))
        self.book=EventAccount(self.view,self.job['fee'],self.job['slippage'])
        self.targets={p:Decimal(0) for p in PAIRS};self.target_time=None;self.trace=[];self.order_identities={};self.episode_events=[];self.last_orders=[];self.position_cycles=[]
        self.rules={}
        for p in PAIRS:
            fs={f['filterType']:f for f in self.view.metadata[p]['filters']};lot=fs['MARKET_LOT_SIZE']
            self.rules[p]=dict(step=lot['stepSize'],min_qty=lot['minQty'],max_qty=lot['maxQty'],min_notional=fs['MIN_NOTIONAL']['notional'])

    def _actual(self):
        from freqtrade.persistence import Trade
        if Trade.use_db:raise SourceError('observed adapter requires in-memory native backtesting; database prohibited')
        orders=[];native_funding=Fraction(0);cycles=[]
        for trade in Trade.get_trades_proxy():
            cycles.append(dict(id=str(trade.id),pair=trade.pair,is_short=trade.is_short,is_open=trade.is_open,
                               opened_at=trade.open_date_utc,closed_at=trade.close_date_utc,
                               definition="native actual account position cycle; not family or independent sample"))
            if trade.funding_fees is not None:native_funding+=number(trade.funding_fees)
            for o in trade.orders:
                if o.safe_filled<=0 or o.order_filled_utc is None:continue
                row=dict(id=f'{trade.id}:{o.order_id}',pair=trade.pair,side=o.ft_order_side,amount=str(o.safe_filled),
                         price=str(o.safe_price),native_order_amount=str(o.amount),filled_at=o.order_filled_utc,tag=o.ft_order_tag,
                         exit_reason=trade.exit_reason if not trade.is_open else None,
                         native_fee_rate=str(trade.fee_open if o.ft_order_side==trade.entry_side else trade.fee_close),
                         modeled_execution_fee=number(o.safe_filled)*number(o.safe_price)*number(self.job['fee']))
                orders.append(row);self.last_orders=orders;self.position_cycles=cycles
                if o.safe_filled!=o.amount:raise SourceError('MODEL_INVALID partial-hour order')
                stable={k:v for k,v in row.items() if k!='exit_reason'}
                if row['id'] in self.order_identities and self.order_identities[row['id']]!=stable:
                    raise SourceError('MODEL_INVALID past order mutated')
                self.order_identities[row['id']]=stable
        orders.sort(key=lambda o:(o['filled_at'],o['id']))
        self.last_orders=orders;self.position_cycles=cycles
        audit_order_source(self.view,orders)
        return orders,native_funding

    @fail_closed
    def bot_loop_start(self,current_time,**kwargs):
        if current_time<self.view.start-timedelta(hours=3):return
        if current_time>=self.view.end:raise SourceError('native entered sealed view')
        orders,native_funding=self._actual();completed,opens,marks=self.view.known(current_time)
        point=self.book.observe(orders,current_time,marks,native_funding=native_funding)
        actual={p:decimal(q) for p,q in point['inventory'].items()}
        flat={p:datetime(1970,1,1,tzinfo=timezone.utc) for p in PAIRS};q={p:Fraction(0) for p in PAIRS}
        for o in orders:
            if o['filled_at']>=current_time:continue
            q[o['pair']]+=number(o['amount'])*(1 if o['side']=='buy' else -1)
            if q[o['pair']]==0:flat[o['pair']]=o['filled_at']
            else:flat.pop(o['pair'],None)
        self.wallets.update()
        # Model funding replaces, rather than adds to, native funding. Clamp by
        # model net equity minus open notional as well as adjusted native free.
        shadow_slip=sum(number(o['amount'])*number(o['price'])*number(self.job['slippage']) for o in orders if o['filled_at']<current_time)
        corrected_free=number(self.wallets.get_free('USDT'))+point['native_funding_delta']-shadow_slip
        model_margin_free=point['equity']-sum(abs(point['inventory'][p])*number(opens[p]) for p in PAIRS)
        free=max(Fraction(0),min(corrected_free,model_margin_free))
        previous={episode_id(e):e for e in self.state.risk.episodes}
        self.state,out=advance_observed(self.state,self.view,current_time,decimal(point['equity']),decimal(free),
                                         actual,self.rules,flat,self.job,self.book)
        current={episode_id(e):e for e in self.state.risk.episodes}
        reasons={(p,f):reason for p,f,reason in out['family_exits']}
        for identity,ep in previous.items():
            if identity not in current:
                self.episode_events.append(dict(id=identity,event='EXIT',at=current_time,episode=ep,
                    reason=reasons.get((ep.entry.pair,ep.entry.family),'RISK_OR_CONTROL_REMOVAL')))
        for identity,ep in current.items():
            if identity not in previous:self.episode_events.append(dict(id=identity,event='ACTIVATED',at=current_time,episode=ep))
        intents=family_intents(self.state.risk)
        self.targets=out['target_quantities'];self.target_time=current_time
        self.trace.append(dict(time=current_time,targets=self.targets.copy(),equity=point['equity'],
                               model_funding=point['funding'],native_funding=native_funding,
                               funding_delta=point['native_funding_delta'],model_free=free,control=out,
                               actual_inventory=actual,family_intents=intents,episodes=current))
        if out['blocked_final_exit']:raise SourceError('MODEL_INVALID final exit unexecutable; inventory retained')

    def populate_indicators(self,dataframe,metadata):return dataframe
    def populate_entry_trend(self,dataframe,metadata):
        dataframe['enter_long']=0;dataframe['enter_short']=0;dataframe['enter_tag']='observed_open';return dataframe
    def populate_exit_trend(self,dataframe,metadata):
        dataframe['exit_long']=0;dataframe['exit_short']=0;return dataframe
    def _target(self,pair,current_time):return float(self.targets[pair]) if self.target_time==current_time else 0.
    @fail_closed
    def custom_stake_amount(self,pair,current_time,current_rate,proposed_stake,min_stake,max_stake,leverage,entry_tag,side,**kwargs):
        q=self._target(pair,current_time)
        if not q or (q>0)!=(side=='long'):return 0.
        stake=min(abs(q)*current_rate,max_stake);return stake if stake>=(min_stake or 0) else 0.
    @fail_closed
    def confirm_trade_entry(self,pair,order_type,amount,rate,time_in_force,current_time,entry_tag,side,**kwargs):
        from freqtrade.persistence import Trade
        if Trade.use_db:raise SourceError('observed adapter requires in-memory native backtesting; database prohibited')
        q=self.targets[pair]
        if self.target_time!=current_time or current_time.hour in (0,8,16) or not q or (q>0)!=(side=='long'):return False
        if any(t.close_date_utc>=current_time for t in Trade.get_trades_proxy(pair=pair,is_open=False)):return False
        existing=sum(number(t.amount) for t in Trade.get_trades_proxy(pair=pair,is_open=True))
        return number(amount)+existing<=number(abs(q))
    @fail_closed
    def custom_exit(self,pair,trade,current_time,current_rate,current_profit,**kwargs):
        q=self._target(pair,current_time)
        return 'observed_target_close' if q==0 or (q<0)!=trade.is_short else None
    @fail_closed
    def adjust_trade_position(self,trade,current_time,current_rate,current_profit,min_stake,max_stake,**kwargs):
        q=self._target(trade.pair,current_time)
        if not q or (q<0)!=trade.is_short:return None
        change=Decimal(str(abs(q)))-Decimal(str(trade.amount))
        if not change:return None
        if change<0:return float(change/Decimal(str(trade.amount))*Decimal(str(trade.stake_amount))),'observed_reduce'
        if current_time.hour in (0,8,16):return None
        stake=float(change*Decimal(str(current_rate)))
        return (stake,'observed_increase') if (min_stake or 0)<=stake<=max_stake else None
    def leverage(self,**kwargs):return 1.

    @fail_closed
    def finalize_model(self):
        orders,native=self._actual()
        marks={p:self.view.marks[p][self.view.end-timedelta(hours=1)].close for p in PAIRS}
        final=self.book.observe(orders,self.view.end,marks,native_funding=native)
        if any(final['inventory'].values()):raise SourceError('MODEL_INVALID final inventory not flat')
        for ep in self.state.risk.episodes:
            self.episode_events.append(dict(id=episode_id(ep),event='BOUNDARY_TRUNCATED',at=self.view.end,episode=ep,reason='PHASE_END_NOT_NATURAL_EXIT'))
        return dict(actual_closed_position_cycles=sum(not c['is_open'] for c in self.position_cycles),
                    position_cycles_are_independent_samples=False,label='SIMULATED_UNDER_ASSUMPTIONS',economic_qualification='NO_REAL_ECONOMIC_QUALIFICATION',
                    modeled_net=final['equity']-1000,modeled_max_drawdown=self.book.max_drawdown,
                    modeled_net_gate=final['equity']>=1000,modeled_risk_gate=self.book.max_drawdown<=Fraction(1,5),
                    native_funding=native,model_funding=final['funding'],native_funding_delta=final['native_funding_delta'])
