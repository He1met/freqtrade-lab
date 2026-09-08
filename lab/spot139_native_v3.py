"""V3 entry adapter: represent a requested gross lot without float underflow.

One upward float ULP in the *stake proposal* avoids losing a lot on stake/rate.
The native order's final amount and price still require exact equality. This
never changes a requested quantity, a fill, or the modeled fee/cash ledger.
"""
from decimal import Decimal as D
import math
import pandas as pd
from freqtrade.persistence import LocalTrade
from lab.spot139_native_bridge import execute_order as execute_v2


def execute_order(engine,fill,allowed):
    if fill['side']!='buy':return execute_v2(engine,fill,allowed)
    s=fill['symbol'];hour=fill['hour'];q=D(fill['quantity']);p=D(fill['price'])
    if (s,hour) not in allowed:raise ValueError('no original tradable open')
    stamp=pd.Timestamp(hour*3600,unit='s',tz='UTC')
    row=[stamp,float(p),float(p),float(p),float(p),0,0,0,0,'spot139-v3','spot139-v3']
    stake=math.nextafter(float(q*p),math.inf)
    if not math.isfinite(stake) or D(str(stake/float(p)))<q:raise ValueError('unrepresentable native stake')
    existing=LocalTrade.bt_trades_open_pp.get(s,[])
    if len(existing)>1:raise ValueError('multiple native cycles for one asset')
    engine.strategy.frozen_stake=stake
    trade=engine._enter_trade(s,row,'long',stake_amount=stake,trade=existing[0] if existing else None,entry_tag1='spot139-v3')
    if trade is None or not trade.orders or trade.orders[-1].safe_filled<=0:raise ValueError('native rejected or unfilled entry')
    order=trade.orders[-1]
    if D(str(order.safe_filled))!=q or D(str(order.safe_price))!=p:raise ValueError('native exact gross quantity/price mismatch')
    engine.wallets.update()
    return dict(symbol=s,hour=hour,side='buy',gross_amount=str(order.safe_filled),price=str(order.safe_price),native_order_cost=str(order.cost),native_ft_fee_base=order.ft_fee_base,native_trade_amount=str(trade.amount),native_cash=str(engine.wallets.get_free('USDT')),native_realized=str(trade.realized_profit),native_entry_price=str(trade.open_rate),native_orders=len(trade.orders),reference_fee_base=str(fill['fee_base']),reference_fee_quote='0',stake_proposal_float_hex=stake.hex(),classification='NATIVE_GROSS_WITH_SEPARATE_V3_BASE_FEE_MODEL')
