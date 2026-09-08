from decimal import Decimal as D
from lab.spot139_model import Episode, Wallet


def test_first_positive_next_hour_and_stop_reentry():
    e=Episode();e.decision(0,True)
    assert not e.activate(0) and e.activate(1)
    e.stopped_or_expired();e.decision(24,True);assert not e.activate(25)
    e.decision(48,False);e.decision(72,True);assert e.activate(73)


def test_end_pending_never_filled_and_inventory_not_liquidated():
    e=Episode();e.decision(24,True);assert not e.active
    w=Wallet();w.inventory={'BTCUSDT':D('.01')}
    t=w.terminal_mark({'BTCUSDT':D('20000')},D('.001'),D('.0006'))
    assert t['equity']==1200 and t['estimated_exit_cost']==D('.32')
    assert w.inventory['BTCUSDT']==D('.01') and not t['synthetic_exit_executed']


def test_shared_cash_base_fee_once_and_dust():
    w=Wallet();assert w.buy('BTC',D('4'),D('100'),D('.001'),D('.001'),D('5'),D('.001'))==4
    assert w.cash==600 and w.inventory['BTC']==D('3.996')
    assert w.buy('ETH',D('8'),D('100'),D('.001'),D('.001'),D('5'),D('.001'))==6
    assert w.cash==0
    sold=w.sell('BTC',D('100'),D('.01'),D('.01'),D('5'),D('.001'))
    assert sold==D('3.99') and w.inventory['BTC']==D('.006')
    assert w.cash==D('398.601')
    assert w.sell('BTC',D('100'),D('.01'),D('.01'),D('5'),D('.001'))==0


def test_no_upsize_and_latches_no_peak_reset():
    w=Wallet();assert w.buy('BTC',D('.01'),D('100'),D('.01'),D('.01'),D('5'),D('.001'))==0
    w.cash=D('899');w.observe({});assert w.warned and not w.halted
    w.cash=D('849');w.observe({});assert w.halted
    w.cash=D('1000');w.observe({});assert w.warned and w.halted and w.peak==1000
    assert w.buy('BTC',D('1'),D('100'),D('.01'),D('.01'),D('5'),D('.001'))==0

from lab.spot139_model import SpotReference, Rule, signal
RULE=Rule(D('.001'),D('.001'),D('5'),D('1000'),D('.00001'),D('.00001'))

def days(end,missing=None):
    return {d:(D(100+d)/10,D(103+d)/10,D(97+d)/10,D(100+d)/10) for d in range(end-272,end+1) if d!=missing}

def model(mode='B'):return SpotReference(mode,{'BTC':RULE,'ETH':RULE})


def test_dual_cash_joint_scaling_and_base_fee_rounded_once():
    m=model();m.pending={s:dict(hour=1,units=D(10),distance=D(5),multiplier=D(1)) for s in m.rules}
    m.on_hour(1,{'BTC':D(100),'ETH':D(100)})
    assert len(m.fills)==2 and m.fills[0]['quantity']==m.fills[1]['quantity']
    assert m.wallet.cash>=200
    for f in m.fills:
        assert m.wallet.inventory[f['symbol']]==f['quantity']-f['fee_base']
    assert m.wallet.cash==1000-sum(f['quantity']*f['price'] for f in m.fills)


def test_missing_activation_has_no_delayed_fill():
    m=model();m.pending={'BTC':dict(hour=1,units=D(1),distance=D(5),multiplier=D(1))}
    m.on_hour(1,{});m.on_hour(2,{'BTC':D(100)})
    assert not m.fills


def test_gap_inventory_stale_then_jump_and_exit_no_foreknowledge():
    m=model();m.pending={'BTC':dict(hour=1,units=D(2),distance=D(5),multiplier=D(1))}
    m.on_hour(1,{'BTC':D(100)})
    assert m.on_hour(2,{})['stale'] and len(m.fills)==1
    m.on_hour(3,{'BTC':D(1)})
    assert m.wallet.halted and m.wallet.warned
    assert m.fills[-1]['side']=='buy'  # min notional rejects sale; inventory retained
    assert m.wallet.inventory['BTC']>0 and m.blocked
    t=m.terminal(4);assert t['mark_age_hours']['BTC']==1 and not t['synthetic_exit_executed']


def test_calendar_gate_future_rejection_and_modes():
    end=400;history=days(end)
    assert signal(end,history,'B')['positive']
    assert signal(end,days(end,end-50),'B') is None
    assert signal(end,days(end,end-100),'B') is not None
    assert signal(end,days(end,end-100),'C') is None
    import pytest
    with pytest.raises(ValueError):signal(end-1,history,'B')
    assert model('A-BTC').selected('BTC') and not model('A-BTC').selected('ETH')


def test_first_signal_next_hour_and_expiry_queues_during_missing_price():
    m=model();hour=401*24
    m.on_hour(hour,{'BTC':D(50),'ETH':D(50)}, {'BTC':days(400),'ETH':days(400)})
    assert not m.fills
    m.on_hour(hour+1,{'BTC':D(50),'ETH':D(50)})
    assert len(m.fills)==2
    # Aging is independent of a new daily signal. Synthetic clock moved to expiry.
    m.last_hour=hour+1+84*24-1
    m.on_hour(hour+1+84*24,{})
    assert m.exits=={'BTC','ETH'} and len(m.fills)==2
    m.on_hour(hour+2+84*24,{'BTC':D(50),'ETH':D(50)})
    assert any(f['side']=='sell' for f in m.fills)


def test_C_new_daily_multiplier_never_fills_at_decision_hour(monkeypatch):
    import lab.spot139_model as module
    m=model('C');m.wallet.inventory={'BTC':D(2)};m.wallet.cash=D(800);m.basis={'BTC':D(200)}
    m.episodes['BTC'].active=True;m.episodes['BTC'].armed=False;m.started={'BTC':1};m.stop_prices={'BTC':D(50)};m.c_baseline={'BTC':D(2)}
    monkeypatch.setattr(module,'signal',lambda *a:dict(positive=True,multiplier=D('.5'),stop_distance=D(10)))
    m.on_hour(24,{'BTC':D(100),'ETH':D(100)})
    assert not m.fills and m.c_pending['BTC']['hour']==25
    m.on_hour(25,{'BTC':D(100),'ETH':D(100)})
    assert m.fills[0]['hour']==25 and m.fills[0]['side']=='sell'


def test_negative_exit_preserves_rearm_then_positive_reenters(monkeypatch):
    import lab.spot139_model as module
    m=model();m.fee=D(0);m.slip=D(0)
    m.pending={'BTC':dict(hour=1,units=D(1),distance=D(5),multiplier=D(1))};m.on_hour(1,{'BTC':D(100)})
    monkeypatch.setattr(module,'signal',lambda *a:dict(positive=False,multiplier=D(1),stop_distance=D(5)))
    m.last_hour=23;m.on_hour(24,{'BTC':D(100)});m.on_hour(25,{'BTC':D(100)})
    assert m.episodes['BTC'].armed and not m.episodes['BTC'].active
    monkeypatch.setattr(module,'signal',lambda *a:dict(positive=True,multiplier=D(1),stop_distance=D(5)))
    m.last_hour=47;m.on_hour(48,{'BTC':D(100)});m.on_hour(49,{'BTC':D(100)})
    assert m.fills[-1]['side']=='buy' and m.fills[-1]['hour']==49


def test_C_missing_next_open_cancels_reduction_without_catchup(monkeypatch):
    import lab.spot139_model as module
    m=model('C');m.wallet.inventory={'BTC':D(2)};m.wallet.cash=D(800);m.basis={'BTC':D(200)}
    m.episodes['BTC'].active=True;m.started={'BTC':1};m.stop_prices={'BTC':D(50)};m.c_baseline={'BTC':D(2)}
    monkeypatch.setattr(module,'signal',lambda *a:dict(positive=True,multiplier=D('.5'),stop_distance=D(10)))
    m.on_hour(24,{'BTC':D(100)});m.on_hour(25,{});m.on_hour(26,{'BTC':D(100)})
    assert not m.fills and not m.c_pending


def test_execution_price_rounds_against_wallet_on_tick_grid():
    r=Rule(D('.001'),D('.001'),D(5),D(1000),D('.00001'),D('.00001'),D('.01'))
    m=SpotReference('B',{'BTC':r});m.pending={'BTC':dict(hour=1,units=D(1),distance=D(5),multiplier=D(1))}
    m.on_hour(1,{'BTC':D('100.01')});assert m.fills[0]['price']==D('100.08')
    m.exits.add('BTC');m.on_hour(2,{'BTC':D('100.01')});assert m.fills[-1]['price']==D('99.94')
