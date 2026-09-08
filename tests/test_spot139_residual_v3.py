from decimal import Decimal as D
from fractions import Fraction as F
import pytest
from lab.spot139_model import Rule,signal
from lab.spot139_residual_v3 import SpotResidualV3
from lab.spot139_precision_v3 import rejection_bound,check_residual

R=Rule(D('.001'),D('.001'),D(5),D(1000),D('.000001'),D('.000001'),D('.01'))


def history(day):
    closes={d:D(100) for d in range(-300,0)}
    closes.update({d:D(101 if d%2==0 else 99) for d in range(day+1)})
    return {d:(p,p+1,p-1,p) for d,p in closes.items() if d<=day}


def run_two_cycles(model,callback=None):
    for hour in range(24,98):
        price=D(100 if hour<72 else 102)
        daily={s:history(hour//24-1) for s in model.rules} if hour%24==0 else None
        n=len(model.fills);model.on_hour(hour,{s:price for s in model.rules},daily)
        if callback:
            for fill in model.fills[n:]:callback(fill)
        assert model.wallet.cash==1000-model.cost_added+model.sale_proceeds
        assert sum(model.basis.values(),D(0))==model.cost_added-model.cost_released
    return model


def test_two_cycles_preserve_residual_cash_basis_and_rearm():
    m=run_two_cycles(SpotResidualV3({'BTC':R,'ETH':R}))
    assert len(m.fills)==8 and len(m.events)==4 and not m.blocked
    assert all(not e.active for e in m.episodes.values()) and m.residual=={'BTC','ETH'}
    for s in m.rules:
        buys=[f for f in m.fills if f['symbol']==s and f['side']=='buy']
        sold=sum(f['quantity'] for f in m.fills if f['symbol']==s and f['side']=='sell')
        assert m.wallet.inventory[s]==sum(f['quantity']-f['fee_base'] for f in buys)-sold
        assert m.wallet.inventory[s]>0 and m.basis[s]>0
    assert [f['hour'] for f in m.fills if f['side']=='buy']==[25,25,73,73]


def residual_model(q,rule=R):
    m=SpotResidualV3({'BTC':rule,'ETH':rule});m.wallet.inventory={'BTC':D(q)};m.basis={'BTC':D(q)*100};m.cost_added=m.basis['BTC'];m.wallet.cash-=m.cost_added
    m.residual.add('BTC');return m


def test_lot_dust_accumulates_then_merges_in_normal_buy_not_fee_reserve():
    m=run_two_cycles(SpotResidualV3({'BTC':R}))
    # Four orders and every sale floors modeled received base including old dust.
    held=D(0)
    for f in m.fills:
        if f['side']=='buy':held+=f['quantity']-f['fee_base']
        else:
            assert f['quantity']==(held/R.step).to_integral_value(rounding='ROUND_DOWN')*R.step
            held-=f['quantity']
    assert held==m.wallet.inventory['BTC']


def test_dust_price_rise_sells_at_first_real_open_before_new_signals():
    m=residual_model('.02');m.on_hour(1,{'BTC':D(100),'ETH':D(100)})
    assert not m.blocked and not m.fills
    m.on_hour(2,{})
    assert m.blocked and not m.fills
    m.on_hour(3,{'BTC':D(300),'ETH':D(100)})
    assert len(m.fills)==1 and m.fills[0]['reason']=='RESIDUAL_BECAME_SELLABLE'
    assert m.fills[0]['side']=='sell' and m.wallet.inventory['BTC']==0 and not m.blocked


def test_significant_unsellable_risk_blocks_all_new_risk():
    r=Rule(R.step,R.min_qty,D(1000),R.max_qty,R.base_fee_step,R.quote_fee_step,R.price_tick)
    m=residual_model('1',r);m.residual.clear();m.episodes['BTC'].active=True;m.started['BTC']=0;m.stops['BTC']=D(110)
    m.pending={'ETH':dict(hour=1,units=D(100),distance=D('.01'))}
    m.on_hour(1,{'BTC':D(100),'ETH':D(100)})
    assert m.blocked and 'UNSELLABLE_ACTIVE_RISK' in m.block_reasons['BTC'] and not m.fills
    assert m.episodes['BTC'].active and m.wallet.inventory['BTC']==1


def test_joint_cash_caps_include_existing_dust_and_no_topping_up_to_clear_it():
    m=residual_model('.0008');m.pending={s:dict(hour=1,units=D(1000),distance=D('.001')) for s in m.rules}
    m.on_hour(1,{'BTC':D(100),'ETH':D(100)})
    assert len(m.fills)==2
    eq=m.equity();held=sum(q*100 for q in m.wallet.inventory.values())
    assert held<=D('.8')*eq and all(q*100<=D('.4')*eq for q in m.wallet.inventory.values())
    n=residual_model('.0008');n.on_hour(24,{'BTC':D(100),'ETH':D(100)})
    assert not n.fills  # no complete signal; no dust-cleaning buy


def test_missing_85_days_prevents_reentry_and_existing_stop_survives():
    m=SpotResidualV3({'BTC':R});m.on_hour(24,{'BTC':D(100)},{'BTC':history(0)})
    m.on_hour(25,{'BTC':D(100)})
    for h in range(26,49):m.on_hour(h,{'BTC':D(100)}, {'BTC':{}} if h==48 else None)
    assert m.episodes['BTC'].active
    m.on_hour(49,{'BTC':D(90)},{'BTC':{}})
    assert any(f['side']=='sell' for f in m.fills)
    assert signal(0,{d:v for d,v in history(0).items() if d!=-84},'B') is None
    assert signal(0,{d:v for d,v in history(0).items() if d!=-200},'C') is None


def test_ten_fifteen_latches_and_high_value_lot_dust_stay_blocking():
    m=residual_model('.0008');m.wallet.cash=D(899);m.on_hour(1,{'BTC':D(100),'ETH':D(100)})
    assert m.wallet.warned and m.risk_cell()==D('.0025')
    m.wallet.cash=D(849);m.on_hour(2,{'BTC':D(100),'ETH':D(100)})
    assert m.wallet.halted
    m.wallet.cash=D(1000);m.pending={'ETH':dict(hour=3,units=D(1),distance=D(1))}
    m.on_hour(3,{'BTC':D(100),'ETH':D(100)})
    assert m.wallet.halted and m.wallet.warned and not m.fills
    n=residual_model('.0008');n.on_hour(1,{'BTC':D(100000),'ETH':D(100)})
    assert n.blocked and n.block_reasons['BTC']=='RESIDUAL_TOTAL_LOSS_EXCEEDS_RISK_CELL'


def test_stop_requires_nonpositive_before_positive_and_execution_error_latches():
    m=SpotResidualV3({'BTC':R});m.on_hour(24,{'BTC':D(100)},{'BTC':history(0)})
    m.on_hour(25,{'BTC':D(100)});m.on_hour(26,{'BTC':D(90)})
    assert not m.episodes['BTC'].armed
    for h in range(27,49):m.on_hour(h,{'BTC':D(100)},{'BTC':history(0)} if h==48 else None)
    assert 'BTC' not in m.pending
    m.execution_error=True;m.on_hour(49,{'BTC':D(100)})
    assert m.blocked


def test_precision_envelope_is_operation_based_and_rejects_corruption():
    b=rejection_bound(4,2,F(1000),F(10))
    assert b>=F(1,100000000) and b<F(1,1000000)
    assert check_residual('1000',F(1000),b)==0
    with pytest.raises(ValueError,match='ACCOUNTING_UNRESOLVED'):check_residual('1000.0001',F(1000),b)


def test_warning_actually_reduces_existing_exposure_and_halt_prevents_other_buy():
    m=SpotResidualV3({'BTC':R,'ETH':R});m.wallet.cash=D(700);m.wallet.inventory={'BTC':D(3)};m.basis={'BTC':D(300)};m.cost_added=D(300)
    m.episodes['BTC'].active=True;m.started['BTC']=1;m.stops['BTC']=D(0)
    m.on_hour(1,{'BTC':D(100),'ETH':D(100)})
    m.on_hour(2,{'BTC':D(60),'ETH':D(100)})
    assert m.wallet.warned and m.wallet.inventory['BTC']<=D('1.5')
    m.pending={'ETH':dict(hour=3,units=D(1),distance=D(1))}
    m.on_hour(3,{'BTC':D(20),'ETH':D(100)})
    assert m.wallet.halted and not any(f['symbol']=='ETH' for f in m.fills)


def test_positive_after_stop_does_not_skip_nonpositive_transition():
    m=SpotResidualV3({'BTC':R});m.on_hour(24,{'BTC':D(100)},{'BTC':history(0)})
    m.on_hour(25,{'BTC':D(100)});m.on_hour(26,{'BTC':D(90)})
    positive=history(1);positive[1]=(D(101),D(102),D(100),D(101))
    assert signal(1,positive,'B')['positive']
    for h in range(27,50):m.on_hour(h,{'BTC':D(100)},{'BTC':positive} if h==48 else None)
    assert len([f for f in m.fills if f['side']=='buy'])==1
    negative=history(2);negative[2]=(D(99),D(100),D(98),D(99))
    for h in range(50,74):m.on_hour(h,{'BTC':D(100)},{'BTC':negative} if h==72 else None)
    assert m.episodes['BTC'].armed
    positive=history(3);positive[3]=(D(101),D(102),D(100),D(101))
    for h in range(74,98):m.on_hour(h,{'BTC':D(100)},{'BTC':positive} if h==96 else None)
    assert len([f for f in m.fills if f['side']=='buy'])==2


def test_reported_twenty_percent_gate_includes_current_exit_fee():
    m=SpotResidualV3({'BTC':R},slip=D(0));m.wallet.cash=D('700.05');m.wallet.inventory={'BTC':D(1)};m.basis={'BTC':D(100)}
    m.episodes['BTC'].active=True;m.started['BTC']=0;m.stops['BTC']=D(110)
    result=m.on_hour(1,{'BTC':D(100)})
    assert m.wallet.cash==D('799.95') and m.wallet.halted
    assert result['observed_dd']>D('.20') and not result['risk_pass_observed']
