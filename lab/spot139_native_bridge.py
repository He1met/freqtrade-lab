"""Fixed native spot order path; reference cash/fee mapping remains explicit."""
from decimal import Decimal as D
from pathlib import Path
from freqtrade.optimize.backtesting import Backtesting
from freqtrade.persistence import LocalTrade,Trade
from freqtrade.exchange.binance import Binance
from freqtrade.enums import RunMode,TradingMode,MarginMode
import pandas as pd


class SpotBacktesting(Backtesting):
    def handle_left_open(self,open_trades,data):
        # Deliberately retain native position. No fabricated final price/time.
        self.retained_terminal=[dict(pair=t.pair,amount=str(t.amount),is_open=t.is_open) for xs in open_trades.values() for t in xs]


def make_engine(root,markets,fee):
    root=Path(root);root.mkdir(exist_ok=True);(root/'data').mkdir(exist_ok=True)
    pairs=[m['symbol'] for m in markets]
    config=dict(max_open_trades=2,stake_currency='USDT',stake_amount='unlimited',tradable_balance_ratio=1.,fiat_display_currency='USD',
        dry_run=True,dry_run_wallet=1000.,cancel_open_orders_on_exit=False,trading_mode=TradingMode.SPOT,margin_mode=MarginMode.NONE,
        timeframe='1h',fee=float(fee),unfilledtimeout={'entry':10,'exit':30,'unit':'minutes'},
        entry_pricing={'price_side':'other','use_order_book':False},exit_pricing={'price_side':'other','use_order_book':False},
        exchange={'name':'binance','enable_ws':False,'pair_whitelist':pairs,'pair_blacklist':[]},
        pairlists=[{'method':'StaticPairList'}],strategy='Spot139Native',strategy_path=str(Path(__file__).resolve().parent),
        user_data_dir=root,datadir=root/'data',dataformat_ohlcv='feather',disableparamexport=True,backtest_cache='none',
        runmode=RunMode.BACKTEST,amend_last_stake_amount=False,last_stake_amount_min_ratio=.5)
    exchange=Binance(config,validate=False,load_leverage_tiers=False)
    def deny(*a,**k):raise ValueError('native public/private network forbidden')
    exchange._api.fetch=deny;exchange._api_async.fetch=deny
    exchange._api.set_markets(markets,{});exchange._api_async.set_markets(markets,{})
    exchange._markets=exchange._api.markets
    engine=SpotBacktesting(config,exchange=exchange)
    engine._set_strategy(engine.strategylist[0])
    if Trade.use_db:raise ValueError('native DB must be disabled')
    return engine,exchange


def execute_order(engine,fill,allowed_opens):
    """Use real native entry/exit and wallet updates; never write fake orders."""
    symbol=fill['symbol'];hour=fill['hour'];price=D(str(fill['price']));quantity=D(str(fill['quantity']))
    if (symbol,hour) not in allowed_opens:raise ValueError('no original tradable open')
    # The model's slippage-adjusted executable price is a disclosed simulation
    # overlay, not the archived OHLC. It is not used for signal/risk history.
    stamp=pd.Timestamp(hour*3600,unit='s',tz='UTC')
    row=[stamp,float(price),float(price),float(price),float(price),0,0,0,0,'spot139','spot139']
    if fill['side']=='buy':
        engine.strategy.frozen_stake=float(quantity*price)
        existing=LocalTrade.bt_trades_open_pp.get(symbol,[])
        if len(existing)>1:raise ValueError('multiple native cycles for one asset')
        trade=engine._enter_trade(symbol,row,'long',stake_amount=float(quantity*price),trade=existing[0] if existing else None,entry_tag1='spot139')
    else:
        trades=LocalTrade.bt_trades_open_pp.get(symbol,[])
        if len(trades)!=1:raise ValueError('one native cycle required')
        trade=trades[0]
        if quantity>D(str(trade.amount)):raise ValueError('native insufficient inventory')
        engine._exit_trade(trade,row,float(price),float(quantity),'spot139_reduce')
        engine._process_exit_order(trade.orders[-1],trade,stamp.to_pydatetime(),row,symbol)
    if trade is None or not trade.orders or trade.orders[-1].safe_filled<=0:raise ValueError('native rejected or unfilled order')
    order=trade.orders[-1]
    if D(str(order.safe_filled))!=quantity or D(str(order.safe_price))!=price:raise ValueError(f'native quantity/price mismatch: filled={order.safe_filled} requested={quantity} price={order.safe_price} expected={price}')
    engine.wallets.update()
    return dict(symbol=symbol,hour=hour,side=fill['side'],gross_amount=str(order.safe_filled),price=str(order.safe_price),
        native_order_cost=str(order.cost),native_ft_fee_base=order.ft_fee_base,native_trade_amount=str(trade.amount),
        native_cash=str(engine.wallets.get_free('USDT')),native_realized=str(trade.realized_profit),
        native_entry_price=str(trade.open_rate),native_orders=len(trade.orders),reference_fee_base=str(fill.get('fee_base',0)),reference_fee_quote=str(fill.get('fee_quote',0)),
        classification='NATIVE_ORDER_PLUS_EXPLICIT_BASE_FEE_MODEL_NOT_IDENTICAL_STATISTICS')


class Reconciler:
    """Independent fill accounting. Native fields are never replaced by model values."""
    def __init__(self,engine,fee):
        self.engine=engine;self.fee=D(fee);self.cash=D(1000)
        self.inventory={};self.entry_base_fees={};self.native_entry_fee_realized=D(0)
        self.quote_rounding=D(0);self.rows=[];self.ideal_native_profit=D(0)

    def apply(self,fill,allowed_opens):
        row=execute_order(self.engine,fill,allowed_opens)
        s=fill['symbol'];q=D(fill['quantity']);p=D(fill['price'])
        if fill['side']=='buy':
            base=D(fill['fee_base']);self.cash-=q*p
            self.inventory[s]=self.inventory.get(s,D(0))+q-base
            self.entry_base_fees[s]=self.entry_base_fees.get(s,D(0))+base
        else:
            fee=D(fill['fee_quote']);self.cash+=q*p-fee;self.inventory[s]-=q
            # Single-entry cycles: native charges entry quote fee for each sold unit.
            self.native_entry_fee_realized+=q*D(row['native_entry_price'])*self.fee
            self.quote_rounding+=fee-q*p*self.fee
            entry=D(row['native_entry_price'])
            self.ideal_native_profit+=q*(p-entry)-q*(p+entry)*self.fee
        if self.cash<0 or any(q<0 for q in self.inventory.values()):raise ValueError('modeled borrowing')
        native_inventory={s:sum((D(str(t.amount)) for t in xs),D(0)) for s,xs in LocalTrade.bt_trades_open_pp.items()}
        inventory_delta={s:native_inventory.get(s,D(0))-q for s,q in self.inventory.items()}
        # Exact quantity-grid conservation is mandatory; no numerical tolerance.
        if inventory_delta!=self.entry_base_fees:raise ValueError('unexplained native/model inventory difference')
        native_profit=LocalTrade.bt_total_profit+sum(t.realized_profit for t in LocalTrade.bt_trades_open)
        native_stake=sum(t.stake_amount for t in LocalTrade.bt_trades_open)
        recomputed_native_cash=1000.+native_profit-native_stake
        if self.engine.wallets.get_free('USDT')!=recomputed_native_cash:
            raise ValueError('native wallet cash component mismatch')
        predicted_delta=self.native_entry_fee_realized-self.quote_rounding
        observed_delta=self.cash-D(row['native_cash'])
        row.update(model_cash=str(self.cash),model_inventory={s:str(q) for s,q in self.inventory.items()},
            native_inventory={s:str(q) for s,q in native_inventory.items()},
            native_minus_model_inventory={s:str(q) for s,q in inventory_delta.items()},
            cumulative_entry_base_fee={s:str(q) for s,q in self.entry_base_fees.items()},
            model_minus_native_cash=str(observed_delta),expected_cash_difference=str(predicted_delta),
            native_profit_rounding_residual=str(D(str(native_profit))-self.ideal_native_profit),
            native_wallet_components=dict(initial=1000,realized=native_profit,stake=native_stake,recomputed_cash=recomputed_native_cash),
            native_rounding_cash_residual=str(observed_delta-predicted_delta),
            cash_formula='model-native = native entry quote fee realized - modeled sell quote rounding + reported native arithmetic/rounding residual')
        self.rows.append(row);return row

    def compare_model(self,model):
        if self.cash!=model.wallet.cash or self.inventory!=model.wallet.inventory:
            raise ValueError('controller and independent fill accounting disagree')
