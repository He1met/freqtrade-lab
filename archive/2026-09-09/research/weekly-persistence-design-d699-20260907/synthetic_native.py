"""Two invented price sequences; official native matcher, no network or DB.

This is a disposable synthetic harness, not a research runner/source publisher.
No functions computing signals, fills, fees, funding or wallets are replaced.
"""
import hashlib
import json
import os
from pathlib import Path
import signal
import socket
import sys
import time

ROOT = Path(__file__).resolve().parent
NATIVE = Path('/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue-43-profile-driven-v1/freqtrade')
REPO = Path('/Users/shenjianpeng/.codex/worktrees/d699/freqtrade-lab')
sys.path[:0] = [str(NATIVE), str(REPO)]
signal.alarm(590)
started = time.monotonic()
network_attempts = []
def denied(*args, **kwargs):
    network_attempts.append('BLOCKED_NETWORK_CALL')
    raise RuntimeError('NETWORK_FORBIDDEN_SYNTHETIC_ONLY')
socket.create_connection = denied
socket.socket.connect = denied
socket.socket.connect_ex = denied
socket.getaddrinfo = denied

import pandas as pd
from freqtrade import __version__
from freqtrade.enums import RunMode, TradingMode, MarginMode, CandleType
from freqtrade.exchange.binance import Binance
from freqtrade.optimize.backtesting import Backtesting
from freqtrade.persistence import LocalTrade
from lab.bounded_strategy import validate_bounded_causal_strategy
from lab.futures_costs import audit_native_trades

PAIR = 'XRP/USDT:USDT'
source = (ROOT / 'XrpWeeklyPersistentDirection.py').read_text()
analysis = validate_bounded_causal_strategy(source, 'XrpWeeklyPersistentDirection', expected_timeframe='1d')
assert __version__ == '2026.7'
core = NATIVE / 'freqtrade/optimize/backtesting.py'
core_before = hashlib.sha256(core.read_bytes()).hexdigest()
report = {'label': 'SYNTHETIC_ONLY_NOT_MARKET_EVIDENCE', 'native_version': __version__,
          'core_sha256': core_before, 'strategy_sha256': hashlib.sha256(source.encode()).hexdigest(),
          'fixtures': [], 'network_attempts': network_attempts,
          'bounded_ast_validation': 'PASSED', 'native_matching_calls': 0}

market = {'id': 'XRPUSDT', 'symbol': PAIR, 'base': 'XRP', 'quote': 'USDT', 'settle': 'USDT',
          'baseId': 'XRP', 'quoteId': 'USDT', 'settleId': 'USDT', 'type': 'swap',
          'spot': False, 'margin': False, 'swap': True, 'future': False, 'option': False,
          'active': True, 'contract': True, 'linear': True, 'inverse': False,
          'contractSize': 1.0, 'maker': .0005, 'taker': .0005, 'percentage': True,
          'precision': {'amount': .000001, 'price': .000001},
          'limits': {'amount': {'min': .000001, 'max': 1000000},
                     'price': {'min': .000001, 'max': 1000000},
                     'cost': {'min': 1, 'max': 100000000}, 'leverage': {'min': 1, 'max': 1}},
          'info': {'synthetic': True, 'status': 'TRADING', 'contractType': 'PERPETUAL'}}

for name in ['direction_zero_boundary', 'intrawEEK_stops']:
    directory = ROOT / name
    directory.mkdir(exist_ok=False)
    cfg = {'max_open_trades': 1, 'stake_currency': 'USDT', 'stake_amount': 250,
           'fiat_display_currency': '', 'timeframe': '1d', 'dry_run': True,
           'dry_run_wallet': 1000, 'tradable_balance_ratio': .99, 'fee': .001,
           'cancel_open_orders_on_exit': False,
           'unfilledtimeout': {'entry': 10, 'exit': 10, 'unit': 'minutes'},
           'entry_pricing': {'use_order_book': False, 'price_side': 'other', 'order_book_top': 1},
           'exit_pricing': {'use_order_book': False, 'price_side': 'other', 'order_book_top': 1},
           'exchange': {'name': 'binance', 'enable_ws': False, 'pair_whitelist': [PAIR], 'pair_blacklist': []},
           'pairlists': [{'method': 'StaticPairList'}], 'datadir': directory,
           'user_data_dir': directory, 'strategy_path': str(ROOT),
           'strategy': 'XrpWeeklyPersistentDirection', 'disableparamexport': True,
           'internals': {}, 'export': 'none', 'dataformat_ohlcv': 'feather',
           'dataformat_trades': 'feather', 'runmode': RunMode.BACKTEST,
           'trading_mode': TradingMode.FUTURES, 'margin_mode': MarginMode.ISOLATED,
           'candle_type_def': CandleType.FUTURES, 'original_config': {},
           'timerange': '20300121-20300401', 'backtest_cache': 'none'}
    # Explicitly invented market metadata, never a retained exchange snapshot.
    (directory / 'config-synthetic.json').write_text(json.dumps(cfg, default=str, indent=2))
    (directory / 'market-synthetic.json').write_text(json.dumps(market, indent=2))
    exchange = Binance(cfg, validate=False, load_leverage_tiers=False)
    exchange._api.set_markets([market], {})
    exchange._api_async.set_markets([market], {})
    exchange._markets = exchange._api.markets
    exchange._leverage_tiers = {PAIR: [{'minNotional': 0, 'maxNotional': 100000000,
                                     'maintenanceMarginRate': .005, 'maxLeverage': 1,
                                     'maintAmt': 0}]}
    bt = Backtesting(cfg, exchange=exchange)
    strat = bt.strategylist[0]
    bt._set_strategy(strat)
    dates = pd.date_range('2030-01-07', periods=84, freq='D', tz='UTC')
    assert dates[0].dayofweek == 0
    sundays = [100, 100, 104, 108, 105, 101, 105, 105, 110, 114, 118, 122]
    rows, previous = [], 100.0
    for i, date in enumerate(dates):
        w, day = divmod(i, 7)
        base = sundays[w-1] if w else 100
        close = base + (sundays[w]-base)*(day+1)/7
        high, low = max(previous, close)*1.001, min(previous, close)*.999
        if name == 'intrawEEK_stops' and (w, day) == (3, 2): low = 85.0
        if name == 'intrawEEK_stops' and (w, day) == (5, 2): high = 125.0
        rows.append([date, previous, high, low, close, 1000000.0])
        previous = close
    frame = pd.DataFrame(rows, columns=['date', 'open', 'high', 'low', 'close', 'volume'])
    frame.to_feather(directory / 'invented-1d.feather')
    hours = pd.date_range(dates[0], periods=84*24, freq='h')
    marks, events = [], []
    for i, date in enumerate(hours):
        day = rows[i//24]
        op = day[1]
        marks.append([int(date.timestamp()*1000), op, day[2], day[3], op])
        if i % 8 == 0:
            events.append({'symbol': 'XRPUSDT', 'fundingTime': int(date.timestamp()*1000),
                           'fundingRate': .0001, 'markPrice': op})
    mark_df = pd.DataFrame({'date': hours, 'open': [r[1] for r in marks]})
    fund_df = pd.DataFrame({'date': [pd.Timestamp(e['fundingTime'], unit='ms', tz='UTC') for e in events],
                           'open': [.0001]*len(events)})
    bt.futures_data = {PAIR: exchange.combine_funding_and_mark(fund_df, mark_df)}
    bt.funding_fee_timeframe_secs = 3600
    (directory / 'invented-mark-funding.json').write_text(json.dumps({'marks': marks, 'events': events}))
    analyzed = strat.advise_all_indicators({PAIR: frame.copy()})[PAIR]
    signals = strat.ft_advise_signals(analyzed.copy(), {'pair': PAIR})
    columns = ['momentum', 'weekday', 'enter_long', 'enter_short', 'exit_long', 'exit_short']
    prefix_checks = 0
    for n in [21, 35, 49, 56, 70]:
        prefix = strat.advise_all_indicators({PAIR: frame.iloc[:n].copy()})[PAIR]
        prefix = strat.ft_advise_signals(prefix, {'pair': PAIR})
        pd.testing.assert_frame_equal(signals.iloc[:n][columns], prefix[columns])
        prefix_checks += 1
    signals.to_feather(directory / 'synthetic-signals.feather')
    trace = []
    # Observation only: native loop, fills and wallet implementations unchanged.
    original = bt.backtest_loop
    def observed_loop(*args, **kwargs):
        before = {'free': bt.wallets.get_free('USDT'), 'total': bt.wallets.get_total('USDT'),
                  'open': [(t.id, t.is_short, t.stake_amount) for t in LocalTrade.bt_trades_open]}
        value = original(*args, **kwargs)
        after = {'free': bt.wallets.get_free('USDT'), 'total': bt.wallets.get_total('USDT'),
                 'open': [(t.id, t.is_short, t.stake_amount) for t in LocalTrade.bt_trades_open]}
        if before != after:
            trace.append({'date': str(args[2]), 'direction': args[3], 'before': before, 'after': after})
        return value
    bt.backtest_loop = observed_loop
    report['native_matching_calls'] += 1
    result = bt.backtest({PAIR: analyzed}, start_date=dates[14].to_pydatetime(), end_date=dates[-1].to_pydatetime())
    trades = json.loads(result['results'].to_json(orient='records', date_format='iso'))
    # Preserve native fills and native trade JSON before external audit.
    (directory / 'native-trades.json').write_text(json.dumps(trades, indent=2))
    (directory / 'native-wallet-trace.json').write_text(json.dumps(trace, indent=2, default=str))
    begin, end = int(dates[14].timestamp()*1000), int((dates[-1]+pd.Timedelta(days=1)).timestamp()*1000)
    audit = audit_native_trades(trades, events, marks, symbol='XRPUSDT', start_ms=begin,
                                end_ms=end, starting_balance=1000)
    (directory / 'conservative-audit.json').write_text(json.dumps(audit, indent=2))
    item = {'name': name, 'prefix_checks': prefix_checks, 'native_final_balance': result['final_balance'],
            'native_trade_count': len(trades), 'trade_summary': [{k:t[k] for k in
              ['open_date','close_date','is_short','open_rate','close_rate','stake_amount','funding_fees','profit_abs','exit_reason']}
              for t in trades], 'minimum_native_free_cash': min([e[x]['free'] for e in trace for x in ['before','after']]),
            'conservative_cash_executable': audit.get('cash_executable')}
    report['fixtures'].append(item)
    (ROOT / 'synthetic-native-report.json').write_text(json.dumps(report, indent=2))
    exchange.close()

assert hashlib.sha256(core.read_bytes()).hexdigest() == core_before
assert not network_attempts
report['elapsed_seconds'] = time.monotonic()-started
report['native_core_unchanged'] = True
report['fixture_count'] = 2
(ROOT / 'synthetic-native-report.json').write_text(json.dumps(report, indent=2))
print(json.dumps(report, indent=2))
