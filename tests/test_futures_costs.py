from datetime import datetime, timezone

import pytest

from lab.futures_costs import FuturesCostError, audit_native_trades, validate_events

START = 1699228800000  # 2023-11-06 UTC
HOUR = 3_600_000
END = START + 24 * HOUR


def iso(ms):
    return datetime.fromtimestamp(ms/1000, timezone.utc).isoformat()


def inputs():
    marks = [[START+i*HOUR, 100, 102, 98, 100] for i in range(24)]
    events = [{"symbol":"BCHUSDT", "fundingTime":START+i*8*HOUR,
               "fundingRate":"0.01", "markPrice":"110"} for i in range(3)]
    return events, marks


def trade(short=False, opened=START, closed=START+2*HOUR):
    return {"pair":"BCH/USDT:USDT", "open_date":iso(opened),"close_date":iso(closed),
            "is_short":short,"leverage":1,"amount":1,"stake_amount":100,
            "open_rate":100,"close_rate":100,"fee_open":0,"fee_close":0,
            "funding_fees":1 if short else -1,"profit_abs":1 if short else -1}


def audit(trades, events=None, marks=None, balance=1000):
    e,m=inputs()
    return audit_native_trades(trades, e if events is None else events,
                              m if marks is None else marks, symbol="BCHUSDT",
                              start_ms=START,end_ms=END,starting_balance=balance)


@pytest.mark.parametrize("short,penalty,profit",[(False,0.1,-1.1),(True,1,0)])
def test_boundary_debit_included_credit_excluded_both_directions(short,penalty,profit):
    result=audit([trade(short)])
    assert result["funding_deduction_abs"]==pytest.approx(penalty)
    assert result["conservative_final_balance"]==pytest.approx(1000+profit)
    assert result["trade_adjustments"][0]["native_profit_abs"]==(-1 if not short else 1)


def test_interior_exact_mark_improvement_never_credited():
    t=trade(True,START+HOUR,START+10*HOUR)
    # Exact short receipt 1.1 exceeds native 1; keep the native lower result.
    assert audit([t])["funding_deduction_abs"]==0
    e,m=inputs();e[1]["markPrice"]="90"
    assert audit([t],e,m)["funding_deduction_abs"]==pytest.approx(0.1)


def test_adjustment_affects_cash_and_drawdown_not_just_profit():
    t=trade(False)
    result=audit([t],balance=101)
    assert result["minimum_free_cash"]==pytest.approx(-0.1)
    assert not result["cash_executable"]
    assert result["conservative_mtm_drawdown_pct"]==pytest.approx(1.1/101*100)
    assert result["intrahour_ordering_stress_drawdown_pct"]>2


def test_native_positive_can_be_conservatively_negative():
    t=trade(False);t.update(close_rate=101.05,profit_abs=0.05)
    assert audit([t])["conservative_final_balance"]<1000


def test_close_boundary_checks_cash_before_releasing_margin():
    t=trade(False,START+HOUR,START+8*HOUR)
    result=audit([t],balance=101)
    assert result["minimum_free_cash"]==pytest.approx(-0.1)
    assert result["conservative_final_balance"]==pytest.approx(99.9)


def test_legal_same_bar_stop_preserves_native_zero_funding():
    t=trade(False,START,START)
    t.update(close_rate=99,fee_open=0.001,fee_close=0.001,
             funding_fees=0,profit_abs=-1.199)
    result=audit([t])
    assert result["funding_deduction_abs"]==pytest.approx(1.1)
    assert result["conservative_final_balance"]==pytest.approx(997.701)


def test_exit_at_half_open_source_end_needs_boundary_data():
    t=trade(False,START+17*HOUR,END)
    with pytest.raises(FuturesCostError,match="scoring window"):
        audit([t])


def test_missing_associated_mark_fails_before_metrics_even_without_trades():
    e,m=inputs();e[1]["markPrice"]=""
    with pytest.raises(FuturesCostError,match="associated"):
        audit([],e,m)


def test_indicator_prehistory_does_not_need_associated_mark():
    e,m=inputs()
    e.insert(0,{"symbol":"BCHUSDT","fundingTime":START-8*HOUR,"fundingRate":"0.01","markPrice":""})
    assert audit([],e,m)["conservative_final_balance"]==1000


@pytest.mark.parametrize("mutation",["wrong_symbol","missing_event","duplicate","wrong_native_fee","overlap"])
def test_source_and_native_mismatch_fail_closed(mutation):
    e,m=inputs();trades=[trade()]
    if mutation=="wrong_symbol":e[0]["symbol"]="ETHUSDT"
    elif mutation=="missing_event":e.pop(1)
    elif mutation=="duplicate":e.insert(1,dict(e[0]))
    elif mutation=="wrong_native_fee":trades[0]["funding_fees"]=0
    else:trades.append(trade())
    with pytest.raises(FuturesCostError):audit(trades,e,m)
