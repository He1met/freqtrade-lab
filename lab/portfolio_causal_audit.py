"""Post-native assertions; absence of evidence fails, never fills gaps with zero."""
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from lab.portfolio_causal import PAIRS
from lab.portfolio_execution import fill_equity, dec


class HaltLiquidationError(ValueError):
    def __init__(self,message,receipt):
        super().__init__(message)
        self.receipt=receipt


def audit_halt_liquidation(fills,trace):
    """Completed mark is observed before matching at this same hour's open.

    Only actual fills at that timestamp discharge the pre-order inventory.
    A later force-exit cannot satisfy the earliest-execution assertion.
    """
    halted=[p for p in trace if p.get("halted")]
    if not halted: raise ValueError("no actual marked-equity halt")
    first=halted[0]
    at=datetime.fromisoformat(first["time"])
    stamp=int(at.timestamp()*1000)
    inventory={p:dec(first["inventory"][p]) for p in PAIRS}
    before={p:Decimal(0) for p in PAIRS}
    residual=dict(inventory)
    executed={p:Decimal(0) for p in PAIRS}
    for order in fills:
        delta=dec(order["amount"])*(1 if order["side"]=="buy" else -1)
        if order["time"]<stamp: before[order["pair"]]+=delta
        if order["time"]==stamp:
            residual[order["pair"]]+=delta
            executed[order["pair"]]+=delta
    receipt=dict(halt_time=at.isoformat(),earliest_execution_time=at.isoformat(),
                 inventory_before={p:str(q) for p,q in inventory.items()},
                 actual_delta_at_earliest_time={p:str(q) for p,q in executed.items()},
                 residual_at_earliest_time={p:str(q) for p,q in residual.items()})
    def require(condition,message):
        if not condition: raise HaltLiquidationError(message,receipt)
    tolerance=Decimal("0.00000001")  # reconciliation tolerance, not a tradable dust waiver
    require(any(abs(q)>tolerance for q in inventory.values()),"halt has no actual inventory to liquidate")
    require(all(abs(before[p]-inventory[p])<=tolerance for p in PAIRS),"halt inventory differs from actual earlier fills")
    require(not any(o["is_entry"] and o["time"]>=stamp for o in fills),"entry after halt")
    require(all(abs(q)<=tolerance for q in residual.values()),"halt liquidation delayed or incomplete at earliest execution time")
    following=next((p for p in trace if datetime.fromisoformat(p["time"])==at+timedelta(hours=1)),None)
    require(following is not None,"next-hour actual inventory receipt missing")
    receipt["next_hour_inventory"]={p:str(dec(following["inventory"][p])) for p in PAIRS}
    require(all(abs(dec(following["inventory"][p]))<=tolerance for p in PAIRS),"actual inventory remains after halt execution")
    return receipt


def audit_causal(result,trace,start):
    def require(condition,message):
        if not condition: raise ValueError(message)
    require(trace and not any("fatal_error" in p for p in trace),"missing/failed causal trace")
    require(trace[0]["time"]==start.isoformat(),"first closed daily boundary missed")
    trades=result["trades"]
    require(trades and {t["pair"] for t in trades}==set(PAIRS),"both pairs must actually trade")
    fills=[]
    for trade in trades:
        require(trade["leverage"]==1 and trade["fee_open"]==trade["fee_close"]==.0006,"native leverage/fee mismatch")
        for o in trade["orders"]:
            fills.append(dict(pair=trade["pair"],side=o["ft_order_side"],amount=o["amount"],price=o["safe_price"],
                              time=o["order_filled_timestamp"],is_entry=o["ft_is_entry"]))
    require(all(t["funding_fees"] is not None for t in trades),"missing native funding accrual")
    funding=sum(t["funding_fees"] for t in trades)
    # Final native force exits must leave no inventory; marks then irrelevant.
    reconciled=fill_equity(fills,{p:1 for p in PAIRS},funding=funding,slippage="0.0006")
    require(all(abs(q)<Decimal("0.00000001") for q in reconciled["inventory"].values()),"final inventory remains")
    slip=sum(dec(o["amount"])*dec(o["price"])*Decimal("0.0006") for o in fills)
    expected=Decimal(1000)+sum((dec(t["profit_abs"]) for t in trades),Decimal(0))-slip
    require(abs(reconciled["equity"]-expected)<Decimal("0.00001"),"native net equity minus actual-fill slippage reconciliation")
    require(any(p["daily_decision"] and len(p["episodes"])==4 for p in trace),"real family decision absent")
    require(any(any(f=="reversal" and why=="stop" for _,f,why in p["family_exits"]) and
                any(e["family"]=="trend" for e in p["episodes"]) for p in trace),"short family stop with surviving trend absent")
    gap_time=(start+timedelta(hours=5)).isoformat()
    require(any(p["time"]==gap_time and any(f=="trend" and why=="stop" for _,f,why in p["family_exits"]) for p in trace),"gap logical exit absent")
    for pair in PAIRS:
        early_short=[t for t in trades if t["pair"]==pair and t["is_short"] and t["open_timestamp"]<int((start+timedelta(hours=2)).timestamp()*1000)]
        early_long=[t for t in trades if t["pair"]==pair and not t["is_short"] and t["open_timestamp"]<int((start+timedelta(hours=5)).timestamp()*1000)]
        require(early_short and early_long,"actual short to long cycle absent")
        require(min(t["open_timestamp"] for t in early_long)>=max(t["close_timestamp"] for t in early_short)+3600000,"flip lacks one-hour real flat wait")
        require(any(t["close_timestamp"]==int((start+timedelta(hours=5)).timestamp()*1000) for t in early_long),"gap did not actually close long")
    halt_receipt=audit_halt_liquidation(fills,trace)
    require(any(dec(p["slippage_paid"])>0 and dec(p["costs"])>dec(p["slippage_paid"]) for p in trace),"costs absent from control account")
    require(all(not p["unexecutable_reductions"] for p in trace),"unexecuted risk reduction requires explicit review")
    return dict(status="SYNTHETIC_CONTROL_PASS",actual_orders=len(fills),
                halt_liquidation=halt_receipt,
                fee_and_slippage=str(reconciled["costs"]),slippage=str(slip),
                final_net_equity_synthetic_only=str(reconciled["equity"]),
                max_drawdown=max((p["max_drawdown"] for p in trace),key=Decimal),
                risk_limit_satisfied=max(Decimal(p["max_drawdown"]) for p in trace)<=Decimal("0.20"),
                cash_insufficiency="NOT_COVERED_NATIVE",funding_settlement="UNVERIFIED",
                market_execution_allowed=False,economic_result=None)
