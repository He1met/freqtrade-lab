"""Deterministic quantities and mark equity from actual fills, not a matcher."""
from decimal import Decimal, ROUND_DOWN

SYNTHETIC_VECTOR = {
    "schema": "portfolio-synthetic-vector-v1", "start": "2020-01-02T00:00:00+00:00",
    "prices": [100, 50], "trend": [[2, 4], [3, 4], [-3, 4], [0, 0], [.45, .35]],
    "reversal": [[-2, 2], [1, -2], [-1, 0], [0, 0], [0, 0]],
    "C_multiplier": [.5, .3, .4, .5, .6], "risk_target": [40, 80],
    "risk_marks_after_hours": [[12, .9], [36, .7]], "funding_rate": "0.0001",
    "funding_interval_hours": 8, "fee": "0.0006", "wallet": "1000",
}


def dec(value):
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError("nonfinite execution value")
    return result


def capped_targets(families, prices, equity, multiplier=1):
    """Net same-asset signals first; cap each at 40%, total at 80% of MTM.

    Inputs are desired signed quantities, not hypothetical fills. No internal
    trade/fee/funding is created for opposing logical contributions.
    """
    eq, mult = max(dec(equity), Decimal(0)), dec(multiplier)
    if not 0 <= mult <= 1:
        raise ValueError("risk multiplier outside [0,1]")
    targets = {p: sum((dec(f.get(p, 0)) for f in families), Decimal(0))*mult for p in prices}
    for pair in targets:
        price = dec(prices[pair])
        if price <= 0: raise ValueError("nonpositive price")
        limit = eq*Decimal("0.4")/price
        targets[pair] = max(-limit, min(limit, targets[pair]))
    total = sum(abs(q)*dec(prices[p]) for p, q in targets.items())
    if total > eq*Decimal("0.8"):
        scale = eq*Decimal("0.8")/total
        targets = {p: q*scale for p, q in targets.items()}
    return targets


def executable_quantity(target, price, *, step, min_qty, min_notional, max_qty):
    """Floor and skip; never inflate a small requested order to its minimum."""
    q, p, s = abs(dec(target)), dec(price), dec(step)
    if p <= 0 or s <= 0: raise ValueError("nonpositive price/step")
    q = (q/s).to_integral_value(rounding=ROUND_DOWN)*s
    if q < dec(min_qty) or q*p < dec(min_notional) or q > dec(max_qty):
        return Decimal(0)
    return q if dec(target) >= 0 else -q


def fill_equity(fills, marks, *, initial="1000", funding="0", fee="0.0006", slippage="0"):
    """Project an actual fill stream to net linear 1x marked equity.

    This does not create prices/fills. Signed purchase/sale cash-flow plus marked
    inventory is the linear futures PnL identity; margin cash is separate.
    Caller supplies only fills already observed at the decision timestamp.
    """
    cash, costs, inventory = dec(initial)+dec(funding), Decimal(0), {}
    for fill in fills:
        if fill["side"] not in {"buy", "sell"}: raise ValueError("invalid fill side")
        amount, price = dec(fill["amount"]), dec(fill["price"])
        if amount <= 0 or price <= 0: raise ValueError("invalid fill")
        signed = amount if fill["side"] == "buy" else -amount
        cost = amount*price*(dec(fee)+dec(slippage))
        cash -= signed*price+cost
        inventory[fill["pair"]] = inventory.get(fill["pair"], Decimal(0))+signed
        costs += cost
    equity = cash
    for pair, amount in inventory.items():
        if amount and pair not in marks: raise ValueError("held inventory missing mark")
        if amount: equity += amount*dec(marks[pair])
    return {"equity": equity, "costs": costs, "inventory": inventory}
