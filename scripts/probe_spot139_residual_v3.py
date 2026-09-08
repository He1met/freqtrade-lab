#!/usr/bin/env python3
"""Bounded real native synthetic integration; never reads a source/market manifest."""
import sys,json,hashlib,traceback
from pathlib import Path
from decimal import Decimal as D
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.probe_spot139_native import market
from lab.spot139_native_bridge import make_engine
from lab.spot139_residual_v3 import SpotResidualV3
from lab.spot139_reconcile_v3 import ReconcilerV3
from lab.spot139_model import Rule
from lab.spot139_precision_v3 import check_residual
from fractions import Fraction as F
from freqtrade.persistence import LocalTrade
import tempfile
RUNTIME=Path('/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue139-residual-v3-synthetic')


def history(day):
    closes={d:D(100) for d in range(-300,0)}
    closes.update({d:D(101 if d%2==0 else 99) for d in range(day+1)})
    return {d:(p,p+1,p-1,p) for d,p in closes.items() if d<=day}


def main():
    RUNTIME.mkdir(exist_ok=True)
    for cost,fee,slip in [('base',D('.001'),D('.0006')),('stress',D('.002'),D('.0012'))]:
        index=len(list(RUNTIME.glob('attempt-*.json')))+1
        if index>4:raise ValueError('synthetic slice exhausted; no new instance')
        path=RUNTIME/f'attempt-{index:03}.json'
        receipt=dict(status='RESERVED_SYNTHETIC_INSTANCE',cost=cost,instance=index,market_calls=0,source_gets=0,code_sha256={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in ['lab/spot139_residual_v3.py','lab/spot139_reconcile_v3.py','lab/spot139_precision_v3.py','lab/spot139_native_v3.py','docs/protocols/issue139-controlled-residual-v3.md','scripts/probe_spot139_residual_v3.py']})
        path.write_text(json.dumps(receipt,indent=2)+'\n')
        engine=None;exchange=None
        try:
            with tempfile.TemporaryDirectory(prefix='spot139-v3-native-') as tmp:
                engine,exchange=make_engine(tmp,[market('BTC'),market('ETH')],fee)
                r=Rule(D('.001'),D('.001'),D(5),D(1000),D('.000001'),D('.000001'),D('.01'))
                model=SpotResidualV3({s:r for s in ['BTC/USDT','ETH/USDT']},fee=fee,slip=slip)
                mapper=ReconcilerV3(engine,fee,model.rules)
                allowed={(s,h):D(100 if h<72 else 102) for s in model.rules for h in range(24,98)}
                for hour in range(24,98):
                    daily={s:history(hour//24-1) for s in model.rules} if hour%24==0 else None
                    n=len(model.fills);model.on_hour(hour,{s:allowed[s,hour] for s in model.rules},daily)
                    for fill in model.fills[n:]:mapper.apply(fill,allowed)
                    mapper.compare_model(model)
                    assert model.wallet.cash==1000-model.cost_added+model.sale_proceeds
                    assert sum(model.basis.values(),D(0))==model.cost_added-model.cost_released
                assert len(model.fills)==8 and len(model.events)==4 and not model.blocked
                assert all(not e.active for e in model.episodes.values())
                assert len(LocalTrade.bt_trades_open)==2  # same native gross reserve across cycles
                for row in mapper.rows:
                    try:check_residual(D(row['ideal_native_cash'])+D('.01'),F(row['ideal_native_cash']),F(row['precision_rejection_bound']))
                    except ValueError:pass
                    else:raise AssertionError('corrupt cash accepted')
                count=sum(len(t.orders) for t in LocalTrade.bt_trades_open)
                engine.handle_left_open(LocalTrade.bt_trades_open_pp,{})
                assert sum(len(t.orders) for t in LocalTrade.bt_trades_open)==count
                receipt.update(status='PASS_SYNTHETIC_TWO_CYCLES',orders=mapper.rows,model_terminal=model.terminal(97),events=model.events,native_terminal=engine.retained_terminal,corrupt_cash_rejected=True)
        except BaseException as error:
            receipt.update(status='FAILED_SYNTHETIC_INSTANCE',error=str(error),traceback=traceback.format_exc());raise
        finally:
            if engine is not None:engine.cleanup()
            if exchange is not None:exchange.close()
            path.write_text(json.dumps(receipt,indent=2,default=str)+'\n')
            print(json.dumps(dict(instance=index,cost=cost,status=receipt['status'],receipt=str(path))),flush=True)
if __name__=='__main__':main()
