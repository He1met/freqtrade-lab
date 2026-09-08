"""Synthetic accounting checks only; no historical source or native engine."""
from decimal import Decimal as D
import pytest
from scripts.analyze_spot139_attribution import summarize, buyhold
from lab.spot139_model import Rule


def test_midnight_mark_belongs_to_previous_month_fee_to_next():
    # 2021-01-31 00 UTC. Inventory appreciated at Feb01 00, then sold for a fee.
    start=447792
    rows=[]
    for offset in range(48):
        cash=D(900) if offset<24 else D(1099)
        qty=D(1) if offset<24 else D(0)
        mark=D(100) if offset<24 else D(200)
        rows.append(dict(hour=start+offset,cash=cash,equity=cash+qty*mark,positions={'X':dict(inventory=qty,mark=mark,mark_age_hours=0,active=qty>0)}))
    result=summarize(rows,end=start+48)
    assert result['months']['2021-01']['change']==100
    assert result['months']['2021-02']['change']==-1
    assert result['years']['2021']['change']==result['net']==99
    assert result['daily']['2021-02-01']['terminal_carry_hours']==1
    assert result['daily']['2021-02-01']['stale_valuation']
    with pytest.raises(ValueError,match='contiguous'):
        summarize(rows[:-1],end=start+48)


@pytest.mark.parametrize('cost,fee', [('base',D('.001')),('stress',D('.002'))])
def test_fixed_once_buy_basefee_cash_and_unrestricted_benchmark_drawdown(cost,fee):
    rule=Rule(D('.1'),D('.1'),D(5),D(10000),D('.0001'),D('.0001'),D('.01'))
    rules={'BTC/USDT':rule,'ETH/USDT':rule}
    hourly={s:{h:((D(100) if h<24 else D(20),)*4,True) for h in range(48)} for s in rules}
    rows,terminal=buyhold(hourly,rules,cost,start=0,entry=1,end=48)
    assert len(terminal['buys'])==2
    for buy in terminal['buys']:
        assert buy['gross_quantity']==D('3.9')
        assert buy['base_fee']==D('3.9')*fee
        assert buy['cost_basis']<=400
        assert rows[-1]['positions'][buy['symbol']]['inventory']==buy['net_quantity']
    assert terminal['cash']==1000-sum(b['cost_basis'] for b in terminal['buys'])
    assert terminal['cash']>200
    assert not terminal['rebalanced'] and not terminal['forced_exit']
    result=summarize(rows,end=48)
    assert result['observed_open_max_drawdown']>D('.20')
    assert result['active_hours']==47
    del hourly['BTC/USDT'][1]
    with pytest.raises(ValueError,match='entry'):
        buyhold(hourly,rules,cost,start=0,entry=1,end=48)
