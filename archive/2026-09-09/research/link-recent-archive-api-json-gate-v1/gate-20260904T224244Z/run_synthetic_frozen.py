"""Frozen separate JSON Gate SYNTHETIC_TEST_ONLY native cases. No real dataset access or matching patches."""
import copy
import hashlib
import json
import sys
import traceback
from pathlib import Path

import pandas as pd
from pandas.testing import assert_frame_equal
from freqtrade.configuration import TimeRange
from freqtrade.data.btanalysis import get_tick_size_over_time
from freqtrade.data.converter.orderflow import populate_dataframe_with_trades
from freqtrade.data.converter.trade_converter import trades_list_to_df
from freqtrade.data.history import get_datahandler
from freqtrade.enums import RunMode, TradingMode, MarginMode, CandleType
from freqtrade.exchange import timeframe_to_seconds
from freqtrade.exchange.okx import Okx
from freqtrade.optimize.backtesting import Backtesting

ROOT = Path(__file__).parent
SPEC = json.loads((ROOT / 'synthetic-cases.json').read_text())
NAME = sys.argv[1]
OUT = ROOT / ('synthetic-' + NAME + '.json')
WORK = ROOT / ('synthetic-' + NAME)
WORK.mkdir(exist_ok=False)
network_attempts = []


def no_network(event, args):
    if event in {'socket.connect', 'socket.getaddrinfo', 'socket.sendto'}:
        network_attempts.append(event)
        raise RuntimeError('Synthetic process network is forbidden')


sys.addaudithook(no_network)
receipt = {'label': 'SYNTHETIC_TEST_ONLY', 'case': NAME, 'status': 'RUNNING',
           'real_data_read': False, 'native_matching_unmodified': True,
           'any_native_pnl': 'SYNTHETIC_ONLY_NOT_RESEARCH_EVIDENCE',
           'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}


def candles(start, count, values):
    dates = pd.date_range(start, periods=count, freq='5min')
    return pd.DataFrame({'date': dates, **{k: [float(v)] * count for k, v in values.items()}})


def trade(ts, ident, side, price, amount):
    return [int(ts), ident, None, side, float(price), float(amount), float(price * amount)]


def flow_case():
    spec = SPEC['flow']
    base = pd.Timestamp(spec['candles_start'])
    df = candles(base, spec['candle_count'], dict(zip(['open', 'high', 'low', 'close', 'volume'], spec['ohlcv'])))
    rows = [trade(base.value // 1000000 + row['offset_ms'], row['id'], row['side'], row['price'], row['amount']) for row in spec['trades']]
    native_trades = trades_list_to_df(rows)
    cfg = {'timeframe': spec['timeframe'], 'orderflow': copy.deepcopy(SPEC['execution']['native_orderflow'])}
    actual, _ = populate_dataframe_with_trades(None, cfg, df.copy(), native_trades.copy())
    expected = pd.DataFrame(spec['expected'], dtype=float)
    assert_frame_equal(actual[['bid', 'ask', 'delta']], expected)
    cfg['orderflow']['max_candles'] = spec['tail_max_candles']
    tail, _ = populate_dataframe_with_trades(None, cfg, df.copy(), native_trades.copy())
    missing = tail[['bid', 'ask', 'delta']].isna().any(axis=1)
    assert missing.tolist() == [True, False, False], 'Native tail truncation not detected'
    assert_frame_equal(tail.loc[~missing, ['bid', 'ask', 'delta']].reset_index(drop=True), expected.iloc[1:].reset_index(drop=True))
    receipt.update({'direction_and_utc_boundaries': actual[['date', 'bid', 'ask', 'delta']].to_dict('records'),
                    'truncation_missing_indices': tail.index[missing].tolist(), 'truncation_detected': True})


def execution_case():
    spec = SPEC['execution']
    case = next(c for c in spec['cases'] if c['name'] == NAME)
    base = pd.Timestamp(spec['start']); pair = spec['pair']
    data = candles(base, spec['count'], spec['default_ohlcv'])
    data.loc[spec['pulse']['index'], 'close'] = spec['pulse']['close']
    for col, value in spec['postpulse'].items():
        if col != 'from_index':
            data.loc[spec['postpulse']['from_index']:, col] = value
    if 'override' in case:
        for col, value in case['override'].items():
            if col != 'index':
                data.loc[case['override']['index'], col] = value
    rows = []
    for i, row in data.iterrows():
        ts = row['date'].value // 1000000
        rows.append(trade(ts + 1, f's{i}', 'sell', row['open'], case['sell']))
        rows.append(trade(ts + 2, f'b{i}', 'buy', row['open'], case['buy']))
    td = trades_list_to_df(rows)
    datadir = WORK / 'data'; datadir.mkdir()
    handler = get_datahandler(datadir, 'json')
    handler.trades_store(pair, td, TradingMode.FUTURES)
    assert_frame_equal(td, handler.trades_load(pair, TradingMode.FUTURES))
    strategy = 'SyntheticForceExitOnly' if NAME == 'SYNTHETIC_FORCE_EXIT' else ('LinkTakerAbsorptionR2' if case['reference'] == 'R2' else 'LinkTakerAbsorptionControlR1')
    cfg = {'runmode': RunMode.BACKTEST, 'trading_mode': TradingMode.FUTURES, 'margin_mode': MarginMode.ISOLATED,
        'candle_type_def': CandleType.FUTURES, 'dry_run': True, 'dry_run_wallet': 1000,
        'stake_currency': 'USDT', 'stake_amount': 100, 'max_open_trades': 1, 'tradable_balance_ratio': .99,
        'fee': .0005, 'timeframe': '5m', 'minimal_roi': {}, 'stoploss': -.03,
        'strategy': strategy, 'strategy_path': str(ROOT), 'user_data_dir': WORK, 'datadir': datadir,
        'dataformat_ohlcv': 'feather', 'dataformat_trades': 'json', 'export': 'none', 'backtest_cache': 'none',
        'timerange': '', 'disableparamexport': True, 'internals': {}, 'original_config': {},
        'unfilledtimeout': {'entry': 10, 'exit': 10, 'unit': 'minutes'},
        'entry_pricing': {'price_side': 'same', 'use_order_book': False, 'price_last_balance': 0},
        'exit_pricing': {'price_side': 'same', 'use_order_book': False},
        'order_types': {'entry': 'limit', 'exit': 'limit', 'stoploss': 'market', 'stoploss_on_exchange': False},
        'exchange': {'name': 'okx', 'key': '', 'secret': '', 'password': '', 'enable_ws': False,
                     'pair_whitelist': [pair], 'pair_blacklist': [], 'use_public_trades': True},
        'pairlists': [{'method': 'StaticPairList'}], 'orderflow': copy.deepcopy(spec['native_orderflow'])}
    market = {'id': 'LINK-USDT-SWAP', 'symbol': pair, 'base': 'LINK', 'quote': 'USDT', 'settle': 'USDT',
        'baseId': 'LINK', 'quoteId': 'USDT', 'settleId': 'USDT', 'type': 'swap', 'spot': False,
        'margin': False, 'swap': True, 'future': False, 'option': False, 'active': True,
        'contract': True, 'linear': True, 'inverse': False, 'contractSize': 1.0, 'expiry': None,
        'precision': {'amount': .001, 'price': .001}, 'limits': {'amount': {'min': .001, 'max': 1000000},
        'price': {'min': .001, 'max': None}, 'cost': {'min': None, 'max': None}, 'leverage': {'min': 1, 'max': 10}},
        'maker': .0005, 'taker': .0005, 'percentage': True, 'info': {'SYNTHETIC_TEST_ONLY': True}}
    tiers = [{'minNotional': 0, 'maxNotional': 1000000, 'maintenanceMarginRate': .005, 'maxLeverage': 10, 'info': {'cum': '0'}}]
    (WORK / 'synthetic-inputs.json').write_text(json.dumps({'label': 'SYNTHETIC_TEST_ONLY', 'config': cfg, 'market': market, 'tiers': tiers}, default=str, indent=2) + '\n')
    exchange = Okx(cfg, validate=False, load_leverage_tiers=False)
    exchange._api.set_markets([market], {})
    exchange._api_async.set_markets([market], {})
    exchange._markets = exchange._api.markets
    exchange._leverage_tiers = {pair: [exchange.parse_leverage_tier(t) for t in tiers]}
    bt = Backtesting(cfg, exchange=exchange)
    try:
        bt.available_pairs = [pair]
        bt.price_pair_prec[pair] = get_tick_size_over_time(data)
        bt.funding_fee_timeframe_secs = timeframe_to_seconds(exchange.get_option('funding_fee_timeframe'))
        # Tiny explicit SYNTHETIC funding/mark context; native combination/accounting retained.
        fund = pd.DataFrame({'date': data['date'], 'open': 0.0})
        mark = pd.DataFrame({'date': data['date'], 'open': data['open']})
        bt.futures_data[pair] = exchange.combine_funding_and_mark(fund, mark)
        bt._set_strategy(bt.strategylist[0])
        preprocessed = bt.strategy.advise_all_indicators({pair: data.copy()})
        enriched = preprocessed[pair]
        receipt['flow_rows'] = len(enriched)
        receipt['flow_missing_indices'] = enriched.index[enriched[['bid', 'ask', 'delta']].isna().any(axis=1)].tolist()
        receipt['tail_trade_offsets_ms'] = [1, 2]
        assert len(enriched) == 42
        assert enriched[['bid', 'ask', 'delta']].notna().all().all(), 'Native flow missing'
        assert enriched['bid'].eq(case['sell']).all() and enriched['ask'].eq(case['buy']).all()
        signals = bt.strategy.ft_advise_signals(enriched.copy(), {'pair': pair})
        entry = signals['enter_long'].fillna(0).eq(1)
        exits = signals['exit_long'].fillna(0).eq(1)
        assert not (entry & entry.shift(1, fill_value=False)).any(), 'Adjacent raw entry'
        assert not (entry & exits).any(), 'Raw entry/exit collision'
        receipt['raw_entry_indices'] = signals.index[entry].tolist()
        receipt['raw_exit_indices'] = signals.index[exits].tolist()
        receipt['native_backtest_called'] = True
        result = bt.backtest(preprocessed, data['date'].iloc[spec['startup']].to_pydatetime(), data['date'].iloc[-1].to_pydatetime())
        trades = result['results']
        trades.to_json(WORK / 'native-synthetic-trades.json', orient='records', date_format='iso')
        actual = {'count': len(trades)}
        if len(trades) == 1:
            t = trades.iloc[0]
            actual.update({'open_index': int((t['open_date'] - base).total_seconds() / 300),
                           'close_index': int((t['close_date'] - base).total_seconds() / 300),
                           'duration_minutes': int((t['close_date'] - t['open_date']).total_seconds() / 60),
                           'exit_reason': t['exit_reason']})
        receipt['expected'] = case['expect']; receipt['actual'] = actual
        for key, value in case['expect'].items():
            assert actual.get(key) == value, f'Native execution mismatch {key}: {actual.get(key)!r} != {value!r}'
        receipt['synthetic_trade_handler_roundtrip'] = 'PASS'
        receipt['strategy_source_sha256'] = hashlib.sha256((ROOT / (strategy + '.py')).read_bytes()).hexdigest()
    finally:
        bt.cleanup()
        exchange.close()


try:
    if NAME == 'FLOW':
        flow_case()
    else:
        execution_case()
    assert not network_attempts
    receipt['status'] = 'PASS_SYNTHETIC_ONLY'
except Exception as exc:
    receipt['status'] = 'FAILED_REQUIRES_CLASSIFICATION_NO_AUTO_RETRY'
    receipt['error'] = {'type': type(exc).__name__, 'message': str(exc), 'traceback': traceback.format_exc()}
    raise
finally:
    receipt['network_attempts'] = network_attempts
    OUT.write_text(json.dumps(receipt, indent=2, default=str) + '\n')
    print(json.dumps(receipt, indent=2, default=str))
