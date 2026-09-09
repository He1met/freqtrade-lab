"""Synthetic causal/source/native-method checks only; never load market files."""
import ast
import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent
REPO = Path('/Users/shenjianpeng/.codex/worktrees/7706/freqtrade-lab')
NATIVE = Path('/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue-43-profile-driven-v1/freqtrade')
sys.path[:0] = [str(REPO), str(NATIVE)]
import pandas as pd
from lab.bounded_strategy import analyze_bounded_causal_strategy
from lab.search_campaign import _single_factor_change, SESSION_PRE_ENTRY_AGREEMENT_V1
from lab.bounded_research import SAFE_ID, MECHANISM_ID
from freqtrade.resolvers import StrategyResolver
from freqtrade.optimize.backtesting import Backtesting, OPEN_IDX, DATE_IDX, LONG_IDX, SHORT_IDX
from freqtrade.configuration import TimeRange
from freqtrade.enums import CandleType
from decimal import Decimal
from freqtrade.persistence import LocalTrade
from freqtrade.enums import ExitType
from freqtrade.strategy.interface import ExitCheckTuple

checks = {}
def check(name, condition):
    assert condition, name
    checks[name] = True

sources = [ (ROOT / f'ClosedShockContinuationR{i}.py').read_text() for i in (1, 2) ]
snapshots = [SimpleNamespace(code_text=s, class_name=f'ClosedShockContinuationR{i}') for i,s in enumerate(sources,1)]
for s in snapshots:
    check(s.class_name + '_bounded_18', analyze_bounded_causal_strategy(s.code_text,s.class_name).max_lookback == 18)
check('strict_r2', _single_factor_change(*snapshots, SESSION_PRE_ENTRY_AGREEMENT_V1))
for old,new in [('shift(5)', 'shift(4)'), ('>= 0.01', '>= 0.02'), ('"180": -1.0','"175": -1.0'), ('stoploss = -0.02','stoploss = -0.03')]:
    bad=SimpleNamespace(code_text=sources[1].replace(old,new),class_name=snapshots[1].class_name)
    check('reject_' + new, not _single_factor_change(snapshots[0],bad,SESSION_PRE_ENTRY_AGREEMENT_V1))
check('safe_profile', SAFE_ID.fullmatch('link-closed-shock-continuation-m-v1') is not None)
check('safe_family', MECHANISM_ID.fullmatch('closed_shock_continuation_m_v1') is not None)
strategies=[]
for i in (1,2):
    config={'strategy':f'ClosedShockContinuationR{i}', 'strategy_path':str(ROOT), 'user_data_dir':ROOT, 'trading_mode':'futures', 'stake_currency':'USDT','stake_amount':100,'dry_run':True}
    strategies.append(StrategyResolver.load_strategy(config))
    check(f'R{i}_ignore_roi_false', strategies[-1].ignore_roi_if_entry_signal is False)
    check(f'R{i}_roi_exact', strategies[-1].minimal_roi == {180:-1.0})

# At row 29, candle opens 02:25, closes 02:30; shock rows 12..23
# are [01:00,02:00), confirmation rows 24..29 [02:00,02:30).
def fixture(shock, confirmation):
    df=pd.DataFrame({'date':pd.date_range('2000-01-01',periods=70,freq='5min',tz='UTC'),'open':100.0,'high':104.0,'low':96.0,'close':100.0,'volume':10.0})
    df.loc[23,'close']=100.0*(1+shock)
    df.loc[24:,'open']=100.0*(1+shock)
    df.loc[24:,'close']=100.0*(1+shock)*(1+confirmation)
    return df
def signals(strategy, df):
    out=strategy.populate_indicators(df.copy(),{})
    return strategy.populate_entry_trend(out,{})
for sign in (1,-1):
    sig='enter_long' if sign==1 else 'enter_short'
    for agree in (True,False):
        df=fixture(sign*.02, sign*.003*(1 if agree else -1))
        r1,r2=[signals(st,df) for st in strategies]
        check(f'{sign}_{agree}_r1_signal',r1.loc[29,sig]==1)
        check(f'{sign}_{agree}_r2_filter', bool(r2.loc[29,sig]==1)==agree)
        check(f'{sign}_{agree}_shock_unchanged',abs(r1.loc[29,'closed_shock']-sign*.02)<1e-12)
        for k,st in enumerate(strategies):
            full=signals(st,df); prefix=signals(st,df.iloc[:30])
            check(f'{sign}_{agree}_{k}_prefix',full.loc[:29,['closed_shock','enter_long','enter_short']].equals(prefix[['closed_shock','enter_long','enter_short']]))
            mutated=df.copy(); mutated.loc[30:,['open','high','low','close']]=200.0
            check(f'{sign}_{agree}_{k}_future',full.loc[:29,['closed_shock','enter_long','enter_short']].equals(signals(st,mutated).loc[:29,['closed_shock','enter_long','enter_short']]))
        check(f'{sign}_{agree}_no_early_or_adjacent_signal',r1.loc[24:28,['enter_long','enter_short']].isna().all().all())

start=datetime(2000,1,1,2,30,tzinfo=timezone.utc)
for index,strategy in enumerate(strategies,1):
    bt=object.__new__(Backtesting)
    bt.strategy=strategy; bt.timeframe='5m'; bt.required_startup=18
    bt.timerange=TimeRange(); bt.config={'candle_type_def':CandleType.FUTURES}
    bt._set_progress_step=lambda *args: None
    bt.check_abort=lambda: None
    bt._increment_progress=lambda: None
    bt.dataprovider=SimpleNamespace(_set_cached_df=lambda *args: None)
    df=strategy.populate_indicators(fixture(.02,.003),{})
    rows=bt._get_ohlcv_as_lists({'LINK/USDT:USDT':df})['LINK/USDT:USDT']
    event=[r for r in rows if r[DATE_IDX]==start]
    check(f'R{index}_native_signal_on_next_open',len(event)==1 and event[0][LONG_IDX]==1)
    previous=[r for r in rows if r[DATE_IDX]==start-timedelta(minutes=5)]
    check(f'R{index}_not_on_signal_candle_open',len(previous)==1 and previous[0][LONG_IDX]==0)
check('flat_100_notional_14bps_cost', (Decimal('0.0005')+Decimal('0.0002'))*(Decimal(100)+Decimal(100))==Decimal('0.14'))
for short in (False,True):
    trade=LocalTrade(pair='LINK/USDT:USDT',open_rate=100,amount=1,stake_amount=100,open_date=start,is_short=short,fee_open=.0005,fee_close=.0005,exchange='okx',leverage=1)
    strategy=strategies[0]
    check(f'{short}_179_no_roi',not strategy.min_roi_reached(trade,.03,start+timedelta(minutes=179)))
    for profit in (-.01,0,.01):
        check(f'{short}_{profit}_180_roi',strategy.min_roi_reached(trade,profit,start+timedelta(minutes=180)))
    bt=object.__new__(Backtesting); bt.strategy=strategy; bt.timeframe_min=5
    row=[None]*12; row[OPEN_IDX]=99.0 if not short else 101.0
    check(f'{short}_time_exit_uses_open',bt._get_close_rate_for_roi(row,trade,start+timedelta(minutes=180),ExitCheckTuple(ExitType.ROI),180)==row[OPEN_IDX])
    exits=strategy.should_exit(trade,row[OPEN_IDX],start+timedelta(minutes=180),enter=True,exit_=False,low=row[OPEN_IDX],high=row[OPEN_IDX])
    check(f'{short}_entry_signal_does_not_suppress_roi',any(x.exit_type==ExitType.ROI for x in exits))

print(json.dumps({'label':'SYNTHETIC_TEST_ONLY_NOT_BACKTEST','checks':checks,'passed':len(checks),'source_sha256':{s.class_name:hashlib.sha256(s.code_text.encode()).hexdigest() for s in snapshots},'real_market_reads':0,'native_backtests':0,'native_limitations':'Native method and resolver checks; full order lifecycle/funding/force exit integration not executed.'},indent=2))
