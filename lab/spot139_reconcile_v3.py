"""V3 native gross reserve mapping; ideal average is rational, not tick-rounded display."""
from decimal import Decimal as D,localcontext
from fractions import Fraction as F
from freqtrade.persistence import LocalTrade
from lab.spot139_native_v3 import execute_order
from lab.spot139_precision_v3 import rejection_bound,check_residual
from lab.spot139_model import floor_grid


def decimal(value):
    with localcontext() as ctx:
        ctx.prec=50
        return str(D(value.numerator)/D(value.denominator)) if isinstance(value,F) else str(value)


class ReconcilerV3:
    def __init__(self,engine,fee,rules):
        self.engine=engine;self.rules=rules;self.fee=D(fee);self.cash=D(1000);self.inventory={};self.basis={};self.realized=D(0)
        self.base_fees={};self.gross={};self.stake={};self.ideal_profit=F(0);self.turnover=F(0);self.units=F(0);self.sells=0;self.rows=[]

    def apply(self,fill,allowed):
        s=fill['symbol'];q=D(fill['quantity']);p=D(fill['price']);fq=F(q);fp=F(p);fee=F(self.fee)
        # A bridge reject terminates the synthetic/diagnostic; never continue a
        # controller which already applied an intent rejected by native.
        row=execute_order(self.engine,fill,allowed)
        if fill['side']=='buy':
            base=D(fill['fee_base']);self.cash-=q*p;self.inventory[s]=self.inventory.get(s,D(0))+q-base
            self.basis[s]=self.basis.get(s,D(0))+q*p;self.base_fees[s]=self.base_fees.get(s,D(0))+base
            self.gross[s]=self.gross.get(s,F(0))+fq;self.stake[s]=self.stake.get(s,F(0))+fq*fp
        else:
            held=self.inventory[s];released=self.basis[s] if q==held else floor_grid(self.basis[s]*q/held,self.rules[s].quote_fee_step)
            proceeds=q*p-D(fill['fee_quote']);self.cash+=proceeds;self.inventory[s]-=q;self.basis[s]-=released;self.realized+=proceeds-released
            average=self.stake[s]/self.gross[s]
            self.ideal_profit+=fq*(fp-average)-fq*(fp+average)*fee
            self.stake[s]-=fq*average;self.gross[s]-=fq;self.sells+=1
        self.turnover+=fq*fp*(1+fee);self.units+=fq
        if self.cash<0 or any(q<0 for q in self.inventory.values()):raise ValueError('modeled borrowing')
        actual={s:sum((D(str(t.amount)) for t in xs),D(0)) for s,xs in LocalTrade.bt_trades_open_pp.items()}
        for s,q in self.inventory.items():
            if actual.get(s,D(0))-q!=self.base_fees[s] or F(actual.get(s,D(0)))!=self.gross[s]:raise ValueError('gross/base reserve conservation failure')
        expected_cash=F(1000)+self.ideal_profit-sum(self.stake.values(),F(0))
        observed_profit=LocalTrade.bt_total_profit+sum(t.realized_profit for t in LocalTrade.bt_trades_open)
        bound=rejection_bound(len(self.rows)+1,self.sells,self.turnover,self.units)
        cash_residual=check_residual(row['native_cash'],expected_cash,bound)
        profit_residual=check_residual(observed_profit,self.ideal_profit,bound)
        native_stake=sum(t.stake_amount for t in LocalTrade.bt_trades_open)
        if self.engine.wallets.get_free('USDT')!=1000.+observed_profit-native_stake:raise ValueError('native wallet component failure')
        row.update(model_cash=str(self.cash),model_inventory={s:str(q) for s,q in self.inventory.items()},model_basis={s:str(v) for s,v in self.basis.items()},model_realized=str(self.realized),native_inventory={s:str(q) for s,q in actual.items()},cumulative_base_fee={s:str(q) for s,q in self.base_fees.items()},ideal_native_cash=decimal(expected_cash),ideal_native_profit=decimal(self.ideal_profit),native_cash_residual=decimal(cash_residual),native_profit_residual=decimal(profit_residual),precision_rejection_bound=decimal(bound),model_minus_ideal_native_cash=decimal(F(self.cash)-expected_cash),residual_gate='PASS',gross_inventory_gate='EXACT_PASS')
        self.rows.append(row);return row

    def compare_model(self,model):
        if (self.cash,self.inventory,self.basis,self.realized)!=(model.wallet.cash,model.wallet.inventory,model.basis,model.realized):raise ValueError('independent modeled cash/inventory/basis mismatch')
