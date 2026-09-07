"""Account evidence helpers. Orders supplied by native consumer, never invented."""
from datetime import datetime, timezone
from decimal import Decimal
from lab.portfolio_causal import PAIRS, utc
from lab.portfolio_execution import dec, fill_equity


def account_snapshot(orders, *, at, marks, funding, fee="0.0006", slippage="0.0006"):
    utc(at)
    # Stable order identity prevents counting revised order snapshots twice.
    seen=set(); fills=[]; signed={p:Decimal(0) for p in PAIRS}
    flat={p:datetime(1970,1,1,tzinfo=timezone.utc) for p in PAIRS}
    latest_open={}
    for order in sorted(orders,key=lambda o:(utc(o["filled_at"]),str(o["id"]))):
        if order["filled_at"]>at: continue
        if order["id"] in seen: raise ValueError("duplicate native order identity")
        seen.add(order["id"])
        pair=order["pair"]
        if pair not in PAIRS or order["side"] not in ("buy","sell"): raise ValueError("invalid actual order")
        amount=dec(order["amount"])
        if amount<=0: raise ValueError("nonpositive actual fill")
        delta=amount*(1 if order["side"]=="buy" else -1)
        before=signed[pair]; signed[pair]+=delta
        if before==0 or before*signed[pair]<0:
            latest_open[pair]=order["filled_at"]
            flat.pop(pair,None)
        if signed[pair]==0:
            flat[pair]=order["filled_at"]
        fills.append({k:order[k] for k in ("pair","side","amount","price")})
    result=fill_equity(fills,marks,funding=funding,fee=fee,slippage=slippage)
    slip=sum(dec(o["amount"])*dec(o["price"])*dec(slippage) for o in fills)
    # Flat is absent while inventory exists, regardless of an earlier close.
    flat={p:t for p,t in flat.items() if signed[p]==0 and t>=latest_open.get(p,t)}
    return {**result,"actual_quantities":signed,"flat_confirmed_at":flat,
            "slippage_paid":slip,"actual_order_count":len(fills),
            "funding_boundary":"NATIVE_IMPLEMENTATION_ONLY_UNVERIFIED_SETTLEMENT"}
