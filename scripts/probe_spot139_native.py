#!/usr/bin/env python3
"""Real Freqtrade synthetic integration only. No source manifest or market data."""
import sys,json,tempfile
from pathlib import Path
from decimal import Decimal as D
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
SOURCE=Path('/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue-43-profile-driven-v1/freqtrade');sys.path.insert(0,str(SOURCE))
from lab.spot139_binding import deny_network
sys.addaudithook(deny_network)
from lab.spot139_native_bridge import make_engine,execute_order,Reconciler
from freqtrade.persistence import LocalTrade
from lab.spot139_model import SpotReference,Rule


def market(base):
    return dict(id=base+'USDT',symbol=base+'/USDT',base=base,quote='USDT',baseId=base,quoteId='USDT',active=True,spot=True,contract=False,swap=False,future=False,option=False,type='spot',
        contractSize=1.,precision={'amount':.001,'price':.00001},limits={'amount':{'min':.001,'max':1000},'price':{'min':.00001,'max':1000000},'cost':{'min':5,'max':None},'leverage':{'min':1,'max':1}},maker=.001,taker=.001,info={})


def main():
    results=[]
    for cost,fee,slip in [('base',D('.001'),D('.0006')),('stress',D('.002'),D('.0012'))]:
        with tempfile.TemporaryDirectory(prefix='spot139-native-synthetic-') as tmp:
            engine,exchange=make_engine(tmp,[market('BTC'),market('ETH')],fee)
            try:
                allowed={(p,h):D(100) for p in ['BTC/USDT','ETH/USDT'] for h in [1,2,3]}
                mapper=Reconciler(engine,fee)
                rule=Rule(D('.001'),D('.001'),D(5),D(1000),D('.000001'),D('.000001'),D('.00001'))
                model=SpotReference('B',{p:rule for p in ['BTC/USDT','ETH/USDT']},fee=fee,slip=slip)
                model.pending={p:dict(hour=1,units=D('1.234'),distance=D(10),multiplier=D(1)) for p in model.rules}
                model.on_hour(1,{p:D(100) for p in model.rules})
                for fill in model.fills:mapper.apply(fill,allowed)
                mapper.compare_model(model)
                n=len(model.fills);model.exits.add('BTC/USDT');model.on_hour(2,{p:D(100) for p in model.rules})
                for fill in model.fills[n:]:mapper.apply(fill,allowed)
                mapper.compare_model(model)
                assert model.blocked and 0<model.wallet.inventory['BTC/USDT']<rule.step
                # A later entry remains blocked by BTC dust globally.
                n=len(model.fills);model.pending={'ETH/USDT':dict(hour=3,units=D(1),distance=D(10),multiplier=D(1))}
                model.on_hour(3,{p:D(100) for p in model.rules});assert len(model.fills)==n
                count=sum(len(t.orders) for t in LocalTrade.bt_trades_open)
                try:execute_order(engine,dict(symbol='ETH/USDT',hour=4,side='sell',quantity=D('.1'),price=D(100)),allowed)
                except ValueError as error:assert str(error)=='no original tradable open'
                else:raise AssertionError('missing original open was accepted')
                engine.handle_left_open(LocalTrade.bt_trades_open_pp,{})
                assert sum(len(t.orders) for t in LocalTrade.bt_trades_open)==count
                assert all(t['is_open'] for t in engine.retained_terminal)
                results.append(dict(cost=cost,orders=mapper.rows,terminal=engine.retained_terminal,model_terminal=model.terminal(3),global_dust_block=True,missing_open_rejected=True,no_terminal_order=True))
            finally:engine.cleanup();exchange.close()
    # Accounting-only replay: modeled exact-lot flat leaves a native fee reserve.
    # This checks next-cycle aggregation, without overriding the model dust block.
    with tempfile.TemporaryDirectory(prefix='spot139-native-reentry-') as tmp:
        engine,exchange=make_engine(tmp,[market('BTC'),market('ETH')],D('.001'))
        try:
            mapper=Reconciler(engine,D('.001'));allowed={('BTC/USDT',h):D(100) for h in [1,2,3,4]}
            for h,side,q,p in [(1,'buy','1','100'),(2,'sell','.999','100'),(3,'buy','1','200'),(4,'sell','.999','200')]:
                fill=dict(symbol='BTC/USDT',hour=h,side=side,quantity=D(q),price=D(p))
                fill['fee_base' if side=='buy' else 'fee_quote']=D(q)*D('.001')*(1 if side=='buy' else D(p))
                mapper.apply(fill,allowed)
            assert mapper.inventory['BTC/USDT']==0
            assert len(LocalTrade.bt_trades_open_pp['BTC/USDT'])==1
            results.append(dict(cost='base_accounting_exact_lot_reentry',orders=mapper.rows,model_flat_native_fee_reserve=True))
        finally:engine.cleanup();exchange.close()
    print(json.dumps(dict(status='NATIVE_SYNTHETIC_MAPPING_PASS',cases=results,native_synthetic_instances=3,market_native_calls=0),default=str))
if __name__=='__main__':main()
