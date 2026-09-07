"""Synthetic-only native consumer of the real causal family core."""
from datetime import timedelta
from decimal import Decimal
from freqtrade.strategy import IStrategy
from freqtrade.persistence import Trade
from lab.portfolio_causal import State, daily_decision, advance, PAIRS, BASE_SHA, SEMANTICS_SHA
from lab.portfolio_causal_fixture import expand, known_hour, mark_at, input_sha
from lab.portfolio_causal_account import account_snapshot


class PortfolioCausalProbe(IStrategy):
    INTERFACE_VERSION=3
    timeframe="1h"
    can_short=True
    startup_candle_count=1
    minimal_roi={}
    stoploss=-.99
    position_adjustment_enable=True
    max_entry_position_adjustment=-1
    process_only_new_candles=True
    use_exit_signal=True

    def bot_start(self, **kwargs):
        if self.config.get("dry_run") is not True or self.config.get("causal_input_sha256")!=input_sha():
            raise ValueError("fixed synthetic input required")
        self.spec,self.start,self.hourly,self.daily=expand()
        self.state=State("B")
        self.trace=[]
        self.targets={p:Decimal(0) for p in PAIRS}
        self.failed=False
        self.target_time=None

    def populate_indicators(self,dataframe,metadata): return dataframe

    def populate_entry_trend(self,dataframe,metadata):
        # Backtesting.validate_row bridge sets only entry bits after the
        # current hour's causal control snapshot; no precomputed target table.
        dataframe["enter_long"]=0
        dataframe["enter_short"]=0
        return dataframe

    def populate_exit_trend(self,dataframe,metadata):
        dataframe["exit_long"]=0
        dataframe["exit_short"]=0
        return dataframe

    def _account(self,current_time,marks):
        trades=Trade.get_trades_proxy()
        orders=[]
        for trade in trades:
            for order in trade.orders:
                if order.safe_filled>0 and order.order_filled_utc is not None:
                    orders.append(dict(id=f"{trade.id}:{order.order_id}",pair=trade.pair,
                        side=order.ft_order_side,amount=order.safe_filled,price=order.safe_price,
                        filled_at=order.order_filled_utc))
        # Native accrual observed so far. None is its initial no-accrual state,
        # never a substitution for missing source funding: fixture events fixed.
        funding=sum(t.funding_fees if t.funding_fees is not None else 0 for t in trades)
        return account_snapshot(orders,at=current_time,marks=marks,funding=funding)

    def bot_loop_start(self,current_time,**kwargs):
        self.targets={p:Decimal(0) for p in PAIRS}
        self.target_time=None
        if self.failed or current_time<self.start: return
        try:
            completed,opens=known_hour(self.hourly,current_time)
            marks=mark_at(self.spec,self.start,current_time,completed)
            account=self._account(current_time,marks)
            decision=None
            if current_time.hour==0:
                decision=daily_decision(self.daily,current_time,account["equity"],mode="B",
                    selection=self.spec["selection"],base_protocol_sha256=BASE_SHA,semantics_sha256=SEMANTICS_SHA)
            self.wallets.update()
            native_free=self.wallets.get_free("USDT")
            free=max(Decimal(0),Decimal(str(native_free))-account["slippage_paid"])
            rules={p:dict(step="0.001",min_qty="0.001",min_notional="50" if p==PAIRS[0] else "20",max_qty="120" if p==PAIRS[0] else "2000") for p in PAIRS}
            self.state,out=advance(self.state,at=current_time,opens=opens,completed=completed,
                actual_quantities=account["actual_quantities"],equity=account["equity"],free_cash=free,
                rules=rules,flat_confirmed_at=account["flat_confirmed_at"],decision=decision,
                base_protocol_sha256=BASE_SHA,semantics_sha256=SEMANTICS_SHA)
            self.targets=out["target_quantities"]
            self.target_time=current_time
            self.trace.append(dict(time=current_time.isoformat(),equity=str(account["equity"]),
                costs=str(account["costs"]),slippage_paid=str(account["slippage_paid"]),
                native_free=native_free,confirmed_free=str(free),wallet_total=self.wallets.get_total("USDT"),
                halted=self.state.halted,max_drawdown=str(self.state.max_drawdown),
                inventory={p:str(q) for p,q in account["actual_quantities"].items()},
                targets={p:str(q) for p,q in self.targets.items()},
                flat_receipts={p:t.isoformat() for p,t in account["flat_confirmed_at"].items()},
                family_exits=out["family_exits"],unexecutable_reductions=out["unexecutable_reductions"],
                episodes=[dict(pair=e.entry.pair,family=e.entry.family,direction=e.entry.direction,
                    started=e.started.isoformat(),units=str(e.entry.units)) for e in self.state.episodes],
                daily_decision=decision is not None,actual_order_count=account["actual_order_count"]))
        except Exception as exc:
            # Native safe-wrapper suppresses callback exceptions: latch and keep
            # the error in evidence so no callback can silently resume entries.
            self.failed=True
            self.trace.append(dict(time=current_time.isoformat(),fatal_error=type(exc).__name__,reason=str(exc)))
            raise

    def _target(self,pair,current_time):
        return float(self.targets[pair]) if not self.failed and self.target_time==current_time else 0.

    def custom_stake_amount(self,pair,current_time,current_rate,proposed_stake,min_stake,max_stake,leverage,entry_tag,side,**kwargs):
        q=self._target(pair,current_time)
        if not q or (q>0)!=(side=="long"): return 0.
        stake=min(abs(q)*current_rate,max_stake)
        return stake if stake>=(min_stake or 0) else 0.

    def confirm_trade_entry(self,pair,order_type,amount,rate,time_in_force,current_time,entry_tag,side,**kwargs):
        q=self._target(pair,current_time)
        if not q or (q>0)!=(side=="long"): return False
        closed=Trade.get_trades_proxy(pair=pair,is_open=False)
        if any(t.close_date_utc>=current_time for t in closed): return False
        existing=sum(t.amount for t in Trade.get_trades_proxy(pair=pair,is_open=True))
        return amount+existing<=abs(q)+1e-9

    def custom_exit(self,pair,trade,current_time,current_rate,current_profit,**kwargs):
        q=self._target(pair,current_time)
        if q==0 or (q<0)!=trade.is_short: return "causal_target_close"
        return None

    def adjust_trade_position(self,trade,current_time,current_rate,current_profit,min_stake,max_stake,**kwargs):
        q=self._target(trade.pair,current_time)
        if not q or (q<0)!=trade.is_short: return None
        change=abs(q)-trade.amount
        if abs(change)<.001: return None
        if change<0: return change/trade.amount*trade.stake_amount,"causal_reduce"
        stake=change*current_rate
        return (stake,"causal_increase") if (min_stake or 0)<=stake<=max_stake else None

    def leverage(self,**kwargs): return 1.
