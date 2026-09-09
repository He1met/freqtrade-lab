"""Pure synthetic checks only. No native runner, market reads, network or SQLite."""
import ast
import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
from lab.bounded_strategy import analyze_bounded_causal_strategy
from accounting_semantics import gap_supplement, liquidation_mtm, ordered_legs

ROOT = Path(__file__).resolve().parent
NATIVE = Path('/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue-43-profile-driven-v1/freqtrade')


def extracted_function(source, name, namespace):
    tree = ast.parse(source)
    method = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name)
    method.returns = None
    for arg in [*method.args.posonlyargs, *method.args.args, *method.args.kwonlyargs]:
        arg.annotation = None
    module = ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[]))
    exec(compile(module, '<extracted-pure-function>', 'exec'), namespace)
    return namespace[name]


def frame(shocks=(50,), low_liquidity=False):
    close, volume, prior = [], [], 100.0
    for i in range(130):
        prior *= .97 if i in shocks else (1.001 if i % 2 else .999)
        close.append(prior)
        volume.append(80000.0 if i in shocks else 10000.0)
    x = pd.DataFrame({'date': pd.date_range('2001-01-01', periods=130, tz='UTC'),
                      'open': close, 'high': np.array(close)*1.005,
                      'low': np.array(close)*.995, 'close': close, 'volume': volume})
    if low_liquidity:
        x.loc[30, 'volume'] = 1.0
    return x


def main():
    source = (ROOT/'LtcVolumeLiquidityReboundV1.py').read_text()
    analysis = analyze_bounded_causal_strategy(source, 'LtcVolumeLiquidityReboundV1', expected_timeframe='1d')
    assert analysis.startup_candle_count == 40 and analysis.max_lookback <= 40
    methods = {n: extracted_function(source, n, {}) for n in (
        'populate_indicators', 'populate_entry_trend', 'populate_exit_trend')}
    def run(x):
        for method in methods.values():
            x = method(None, x, {})
        return x
    x = run(frame())
    r = x.close / x.close.shift(1) - 1
    for t in range(40, 130):
        assert np.isclose(x.loc[t,'prior_m2'], (r.iloc[t-30:t]*r.iloc[t-30:t]).mean())
        assert np.isclose(x.loc[t,'prior_volume'], x.volume.iloc[t-30:t].mean())
        assert np.isclose(x.loc[t,'prior_liquidity'], (x.volume.iloc[t-30:t]*x.low.iloc[t-30:t]).min())
    assert x.loc[40, ['ret','prior_m2','prior_volume','prior_liquidity']].notna().all()
    def shock_at(df,t):
        row=df.loc[t]
        return (row.ret <= -.02 and row.r2 >= 2.25*row.prior_m2
                and row.volume >= 2*row.prior_volume and row.prior_m2 > 0 and row.prior_volume > 0)
    for t in range(40,130):
        expected=shock_at(x,t) and not any(shock_at(x,t-k) for k in (1,2,3)) and x.loc[t,'prior_liquidity']>=500000
        assert bool(x.loc[t,'enter_long']==1)==expected
    assert x.index[x.enter_long == 1].tolist() == [50]
    assert x.index[x.exit_long == 1].tolist() == [52]
    # Mirrors the pinned native trim-then-shift signal preparation, no backtest.
    shifted = x.iloc[40:][['enter_long','exit_long']].fillna(0).shift(1).iloc[1:]
    assert shifted.index[shifted.enter_long == 1].tolist() == [51]
    assert shifted.index[shifted.exit_long == 1].tolist() == [53]
    assert (x.loc[53,'date']-x.loc[51,'date']).total_seconds() == 48*3600
    for lag in (1,2,3):
        z=run(frame((50,50+lag)))
        assert shock_at(z,50+lag) and z.loc[50+lag,'enter_long'] != 1
    z=run(frame((50,54)))
    assert shock_at(z,54) and z.loc[54,'enter_long'] == 1
    z=run(frame(low_liquidity=True))
    assert shock_at(z,50) and z.loc[50,'enter_long'] != 1
    # Future mutations cannot alter earlier signals or rolling state.
    raw=frame();raw.loc[60:, ['open','high','low','close','volume']] *= 5
    pd.testing.assert_frame_equal(run(raw).iloc[:60],x.iloc[:60])
    raw=frame();raw.loc[50,['low','volume']]=[1.0,800000.0]
    z=run(raw)
    assert z.loc[50,'prior_liquidity']==x.loc[50,'prior_liquidity']
    assert z.loc[50,'prior_volume']==x.loc[50,'prior_volume']
    assert z.loc[50,'prior_m2']==x.loc[50,'prior_m2']
    # Extract only the pure native stop-price helper, no native imports or runner.
    native_source=(NATIVE/'freqtrade/optimize/backtesting.py').read_text()
    exits=SimpleNamespace(LIQUIDATION='liquidation', TRAILING_STOP_LOSS='trailing', STOP_LOSS='stop')
    helper=extracted_function(native_source,'_get_close_rate_for_stoploss',
        {'ExitType':exits,'OPEN_IDX':0,'HIGH_IDX':1,'LOW_IDX':2})
    trade=SimpleNamespace(is_short=False,leverage=1.,stop_loss=92.,liquidation_price=None)
    exit_=SimpleNamespace(exit_type=exits.STOP_LOSS)
    assert helper(None,(100.,101.,85.),trade,exit_,0)==92.  # Same-bar new entry stop.
    assert helper(None,(85.,90.,80.),trade,exit_,1440)==85. # Native already accounts gap.
    assert helper(None,(85.,95.,80.),trade,exit_,1440)==92. # Ideal stop above open.
    loop=next(n for n in ast.walk(ast.parse(native_source)) if isinstance(n,ast.FunctionDef) and n.name=='backtest_loop')
    call_lines={}
    for n in ast.walk(loop):
        if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute):
            call_lines.setdefault(n.func.attr,[]).append(n.lineno)
    assert min(call_lines['_enter_trade']) < min(call_lines['_check_trade_exit']) < min(call_lines['_process_exit_order'])
    assert gap_supplement(quantity=5.,native_exit=85.,candle_open=85.,held_before_candle=True,stop_exit=True)==0
    assert gap_supplement(quantity=5.,native_exit=92.,candle_open=85.,held_before_candle=True,stop_exit=True)==35
    assert gap_supplement(quantity=5.,native_exit=92.,candle_open=100.,held_before_candle=False,stop_exit=True)==0
    legs=ordered_legs([
        dict(time=1,trade_open_time=1,trade_id=7,order_id='s',side='sell',q=5.,rate=92.),
        dict(time=1,trade_open_time=1,trade_id=7,order_id='b',side='buy',q=5.,rate=100.)])
    cash,quantity=1000.,0.
    for leg in legs:
        value=leg['q']*leg['rate']
        if leg['side']=='buy':
            cash-=value*(1+.001+.001);quantity+=leg['q']
        else:
            assert quantity>=leg['q'];cash+=value*(1-.001-.001);quantity-=leg['q']
    assert quantity==0 and np.isclose(cash,958.08)
    marked=liquidation_mtm(cash=499.,quantity=5.,close=100.,fee=.001,slippage=.001)
    assert marked==dict(cash=499.,reserve=1.,equity=998.)
    final=liquidation_mtm(cash=499.+500.-1.,quantity=0.,close=100.,fee=.001,slippage=.001)
    assert final==dict(cash=998.,reserve=0.,equity=998.)
    result=dict(status='PURE_SYNTHETIC_CHECKS_PASSED',strategy_analysis=asdict(analysis),
        checks=['lagged_30_day_indicators','40_candle_warmup','t1_entry_t3_exit','three_day_Q_dedup',
        'liquidity_filter','future_prefix_invariance','native_pure_stop_helper_and_source_order',
        'same_bar_buy_before_sell','no_double_gap_debit','MTM_reserve_not_cash'],
        native_backtests=0,market_rows_read=0,network_requests=0,
        strategy_sha256=hashlib.sha256(source.encode()).hexdigest(),
        native_helper_file_sha256=hashlib.sha256(native_source.encode()).hexdigest())
    (ROOT/'synthetic-checks.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))


if __name__=='__main__':
    main()
