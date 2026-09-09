"""Pure bookkeeping primitives for this single-entry long-only protocol."""
from math import isfinite


def gap_supplement(*, quantity, native_exit, candle_open, held_before_candle, stop_exit):
    """Only the unreflected worse-open part; never debit a gap already in native."""
    assert all(isfinite(x) and x > 0 for x in (quantity, native_exit, candle_open))
    if not held_before_candle or not stop_exit:
        return 0.0
    return quantity * max(0.0, native_exit - candle_open)


def liquidation_mtm(*, cash, quantity, close, fee, slippage):
    """Reserve reduces valuation only. Caller updates cash only on real legs."""
    assert quantity >= 0 and fee >= 0 and slippage >= 0
    reserve = quantity * close * (fee + slippage)
    return {"cash": cash, "reserve": reserve, "equity": cash + quantity * close - reserve}


def ordered_legs(events):
    """Single-entry trades: older trade first; each trade's buy precedes its sell.

    Native trade/order identities remain attached. This is not a generic DCA,
    partial fill, position-stacking, short, or exchange matching engine.
    """
    for event in events:
        assert event["side"] in {"buy", "sell"}
        assert event["trade_id"] is not None and event["order_id"] is not None
        assert event["trade_open_time"] <= event["time"]
    return sorted(events, key=lambda e: (
        e["time"], e["trade_open_time"], str(e["trade_id"]),
        0 if e["side"] == "buy" else 1, str(e["order_id"]),
    ))
