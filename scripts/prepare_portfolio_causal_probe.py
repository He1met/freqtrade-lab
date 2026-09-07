#!/usr/bin/env python3
"""Prepare synthetic/6 binding. This CLI has no execution or reservation mode."""
from pathlib import Path
from datetime import timedelta
import argparse
import hashlib
import json
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from lab.portfolio_budget import canonical, LockedBudget, RUNTIME_ROOT, verify_anchor
from lab.portfolio_causal import BASE_SHA, SEMANTICS_SHA, verify_binding
from lab.portfolio_causal_fixture import input_sha, expand
from scripts.run_portfolio_synthetic import verify_environment, SOURCE_COMMIT, sha

REPO=Path(__file__).resolve().parents[1]
CODE_FILES=("lab/portfolio_causal.py","lab/portfolio_causal_audit.py","lab/portfolio_causal_account.py","lab/portfolio_causal_fixture.py",
            "lab/portfolio_causal_strategy.py","lab/portfolio_causal_native.py","lab/portfolio_execution.py",
            "lab/portfolio_budget.py","lab/portfolio_preflight.py","lab/bounded_research.py",
            "scripts/prepare_portfolio_causal_probe.py","scripts/run_portfolio_synthetic.py")
ASSERTIONS=("daily_decision_real_indicators","opposing_families_then_short_stop",
            "actual_short_close_then_long_next_hour","gap_exit_real_fill",
            "halt_then_no_new_entry","fee_and_slippage_in_net_risk",
            "recent_cycle_flat_only","both_pairs_shared_wallet","native_fill_equity_reconciliation")


def prepare(source):
    verify_binding(BASE_SHA,SEMANTICS_SHA)
    verify_anchor()
    tree=verify_environment(source)
    # Read only; do not even create writer.lock or a new output directory.
    budget=LockedBudget(RUNTIME_ROOT)
    if budget.pending() or any(e["key"]=="synthetic/6" for e in budget.events):
        raise ValueError("synthetic/6 is not a fresh available slot")
    code={p:sha(REPO/p) for p in CODE_FILES}
    spec,start,hourly,daily=expand()
    return dict(status="PREPARED_NOT_EXECUTION_AUTHORIZED",key="synthetic/6",
        base_protocol_sha256=BASE_SHA,semantics_sha256=SEMANTICS_SHA,input_sha256=input_sha(),
        code=code,code_sha256=hashlib.sha256(canonical(code)).hexdigest(),
        source_commit=SOURCE_COMMIT,source_tree=tree,source_sha256=hashlib.sha256(tree.encode()).hexdigest(),
        budget_prefix_sha256=sha(RUNTIME_ROOT/"calls.jsonl"),
        existing_reserved_slots=sum(e["event"]=="RESERVED" for e in budget.events),
        start=start.isoformat(),hourly_rows_per_pair=len(hourly[next(iter(hourly))]),
        assertions=ASSERTIONS,cash_insufficiency="NOT_COVERED_NATIVE; PURE_FUNCTION_TESTED",
        funding_settlement="UNVERIFIED",market_execution_allowed=False,native_calls_this_preparation=0)


def run_reserved(root,source,binding):
    """Future approved dispatcher only: require already durable sole reservation.

    No matching/fee/price monkeypatches. The sole subclass changes signal bits.
    This function is never called by the preparation CLI.
    """
    from lab.portfolio_budget import BudgetError
    verify_binding(binding.get("base_protocol_sha256"),binding.get("semantics_sha256"))
    if root != RUNTIME_ROOT/"runs/synthetic-6" or root.is_symlink():
        raise BudgetError("fixed synthetic/6 output root required")
    if hashlib.sha256(canonical(binding["code"])).hexdigest()!=binding["code_sha256"]:
        raise BudgetError("code manifest hash mismatch")
    verify_anchor()
    budget=LockedBudget(RUNTIME_ROOT)
    pending=budget.pending()
    if len(pending)!=1 or pending[0]["key"]!="synthetic/6":
        raise BudgetError("no sole durable synthetic/6 reservation")
    for key in ("input_sha256","code_sha256","source_sha256","semantics_sha256"):
        if pending[0].get(key)!=binding.get(key): raise BudgetError("reservation binding mismatch")
    if any(sha(REPO/p)!=value for p,value in binding["code"].items()) or input_sha()!=binding["input_sha256"]:
        raise BudgetError("prepared code/input changed")
    if verify_environment(source)!=binding["source_tree"]: raise BudgetError("source changed")
    sys.path.insert(0,str(source))
    def deny_network(event,args):
        if event in {"socket.connect","socket.getaddrinfo","socket.bind"}:
            raise RuntimeError("synthetic network denied")
    sys.addaudithook(deny_network)
    import pandas as pd
    from freqtrade.commands.optimize_commands import setup_optimize_configuration
    from freqtrade.enums import CandleType,RunMode
    from freqtrade.data.history.datahandlers import get_datahandler
    from freqtrade.exchange.binance import Binance
    from lab.portfolio_causal_native import CausalBacktesting
    from lab.portfolio_causal_fixture import mark_at
    from lab.portfolio_causal import PAIRS
    from scripts.run_portfolio_synthetic import synthetic_config
    spec,start,hourly,daily=expand()
    for name in ("data","user","exports"): (root/name).mkdir()
    handler=get_datahandler(root/"data","feather")
    markets=[];tiers={}
    for pair in PAIRS:
        bars=hourly[pair]
        frame=pd.DataFrame([dict(date=b.closed_at-pd.Timedelta(hours=1),open=b.open,high=b.high,low=b.low,close=b.close,volume=10000.) for b in bars])
        handler.ohlcv_store(pair,"1h",frame,CandleType.FUTURES)
        mark=frame.copy()
        # A stored mark row represents this completed hour; risk observes it
        # at its close. Source mark is fixed independently of strategy fills.
        for index,bar in enumerate(bars):
            value=mark_at(spec,start,bar.closed_at,{p:bar for p in PAIRS})[pair]
            for col in ("open","high","low","close"): mark.loc[index,col]=value
        handler.ohlcv_store(pair,"1h",mark,CandleType.MARK)
        funding=frame.iloc[::8].copy()
        funding[["open","high","low","close"]]=spec["funding_rate"]
        handler.ohlcv_store(pair,"1h",funding,CandleType.FUNDING_RATE)
        base=pair.split("/")[0]
        markets.append(dict(id=base+"USDT",symbol=pair,base=base,quote="USDT",settle="USDT",
            baseId=base,quoteId="USDT",settleId="USDT",active=True,contract=True,swap=True,
            spot=False,future=False,option=False,linear=True,inverse=False,type="swap",contractSize=1.,
            expiry=None,precision={"amount":.001,"price":.000001},
            limits={"amount":{"min":.001,"max":120. if pair==PAIRS[0] else 2000.},
                    "price":{"min":.000001,"max":None},"cost":{"min":50. if pair==PAIRS[0] else 20.,"max":None},
                    "leverage":{"min":1.,"max":20.}},maker=.0006,taker=.0006,info={}))
        tiers[pair]=[{"minNotional":0.,"maxNotional":1000000.,"maintenanceMarginRate":.005,"maxLeverage":20.,"maintAmt":0.}]
    config=synthetic_config("B")
    config["causal_input_sha256"]=input_sha()
    config_path=root/"config.json";config_path.write_bytes(canonical(config))
    config=setup_optimize_configuration(dict(command="backtesting",config=[str(config_path)],
        datadir=str(root/"data"),user_data_dir=str(root/"user"),strategy_path=str(REPO/"lab"),
        strategy="PortfolioCausalProbe",timerange=f"{int((start-timedelta(hours=1)).timestamp())}-{int((hourly[PAIRS[0]][-1].closed_at).timestamp())}",
        fee=.0006,export="trades",exportdirectory=str(root/"exports"),dataformat_ohlcv="feather",
        disableparamexport=True,backtest_cache="none"),RunMode.BACKTEST)
    exchange=Binance(config,validate=False,load_leverage_tiers=False)
    def deny(*a,**k): raise RuntimeError("exchange request denied")
    exchange._api.fetch=deny;exchange._api_async.fetch=deny
    exchange._api.set_markets(markets,{});exchange._api_async.set_markets(markets,{})
    exchange._markets=exchange._api.markets;exchange._leverage_tiers=tiers
    bt=None
    try:
        bt=CausalBacktesting(config,exchange=exchange)
        bt.start()
        (root/"trace.json").write_bytes(canonical(bt.strategylist[0].trace))
        import zipfile
        from lab.portfolio_causal_audit import audit_causal
        archives=list((root/"exports").glob("*.zip"))
        if len(archives)!=1: raise ValueError("one native archive required")
        results=[]
        with zipfile.ZipFile(archives[0]) as archive:
            for info in archive.infolist():
                if info.filename.endswith(".json") and info.file_size<16*1024*1024:
                    value=json.loads(archive.read(info))
                    if "PortfolioCausalProbe" in value.get("strategy",{}):
                        results.append(value["strategy"]["PortfolioCausalProbe"])
        if len(results)!=1: raise ValueError("native strategy export missing")
        (root/"native-result.json").write_bytes(canonical(results[0]))
        evidence=audit_causal(results[0],bt.strategylist[0].trace,start)
        evidence["archive_sha256"]=sha(archives[0])
        return evidence
    finally:
        if bt is not None:
            (root/"trace.json").write_bytes(canonical(bt.strategylist[0].trace))
            bt.cleanup()
        exchange.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native-source",type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(prepare(args.native_source.resolve(strict=True)),indent=2))


if __name__=="__main__": main()
