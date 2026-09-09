"""Deterministic cash/spot audit; no network, native runner or business records."""
import math
from datetime import datetime, timedelta
from freqtrade.exchange.exchange_utils import amount_to_precision

CONVENTION = {
    'version': 1,
    'entry': 'First Monday strictly after score start, OPEN; S=2021-03-08',
    'exit': 'Last score candle OPEN; S=2022-01-31; native handle_left_open OPEN',
    'quantity': 'Pinned Freqtrade amount_to_precision(250 / entry_open, snapshot amount precision, snapshot precisionMode); TRUNCATE, spot contracts not applicable',
    'cash': '1000 initially; subtract quantity*entry_open*(1+fee), add quantity*exit_open*(1-fee). Nominal250; precision remainder stays cash.',
    'snapshots': 'Exact same dates as main native pre-trade wallet Feather. Mark at day OPEN before any entry/exit. Initial wallet is included only on native dates before entry. No extra synthetic initial/final point in gate DD.',
    'final_wallet': 'After terminal sale and fee, separately reported for return; not appended to pre-trade gate snapshots. Supplemental endpoints-inclusive DD reported separately, never substituted for gate DD.',
    'drawdown': 'Per date value, running maximum of that same snapshot series; max((peak-value)/peak)*100. No intraday/close MTM claim.',
    'risk_ratio': 'net_pct / max(pre_trade_daily_open_DD_pct, 1.0)',
    'fee_per_side': 0.0012,
    'independent_sample': False,
}

def drawdown(values):
    assert values and all(math.isfinite(v) and v > 0 for v in values)
    peak = values[0]
    result = 0.0
    for value in values:
        peak = max(peak, value)
        result = max(result, (peak - value) / peak * 100)
    return result

def audit(opens, snapshot_dates, entry, exit, precision, precision_mode, fee=0.0012):
    assert snapshot_dates == sorted(set(snapshot_dates)) and entry < exit
    assert entry in snapshot_dates and exit in snapshot_dates
    assert all(d in opens and math.isfinite(opens[d]) and opens[d] > 0 for d in snapshot_dates)
    quantity = amount_to_precision(250.0 / opens[entry], precision, precision_mode)
    assert math.isfinite(quantity) and quantity > 0
    actual_notional = quantity * opens[entry]
    assert actual_notional <= 250.0 + 1e-10
    cash, held = 1000.0, 0.0
    values = []
    for day in snapshot_dates:
        values.append(cash + held * opens[day])
        if day == entry:
            cash -= actual_notional * (1 + fee)
            held = quantity
        if day == exit:
            cash += held * opens[day] * (1 - fee)
            held = 0.0
    assert held == 0
    gross = quantity * (opens[exit] - opens[entry])
    fees = quantity * (opens[entry] + opens[exit]) * fee
    net = cash - 1000.0
    assert abs(gross - fees - net) < 1e-8
    dd = drawdown(values)
    return {'quantity': quantity, 'actual_notional': actual_notional,
            'precision_remainder': 250.0 - actual_notional,
            'gross_usdt': gross, 'fees_usdt': fees, 'net_usdt': net,
            'final_wallet_usdt': cash, 'net_pct': net / 10,
            'daily_open_pretrade_DD_pct': dd,
            'endpoints_inclusive_DD_pct_diagnostic': drawdown([1000.0] + values + [cash]),
            'risk_ratio': (net / 10) / max(dd, 1.0),
            'snapshot_dates': snapshot_dates, 'snapshot_values': values,
            'entry': entry, 'exit': exit, 'fee_per_side': fee,
            'cash_baseline': {'net_usdt': 0.0, 'DD_pct': 0.0}}

def artificial_tests():
    from ccxt import TICK_SIZE
    dates = ['2021-03-07', '2021-03-08', '2021-03-09', '2021-03-10']
    cases = {}
    for label, prices in [('constant', [100, 100, 100, 100]),
                           ('up', [100, 100, 120, 120]),
                           ('down', [100, 100, 80, 80]),
                           ('precision', [101, 101, 101, 101]),
                           ('peak', [100, 100, 200, 100])]:
        cases[label] = audit(dict(zip(dates, prices)), dates, dates[1], dates[-1], 0.1, TICK_SIZE)
    assert abs(cases['constant']['net_usdt'] + 0.6) < 1e-9
    assert abs(cases['up']['net_usdt'] - 49.34) < 1e-9
    assert abs(cases['down']['net_usdt'] + 50.54) < 1e-9
    assert cases['precision']['quantity'] == 2.4
    assert abs(cases['precision']['precision_remainder'] - 7.6) < 1e-9
    assert abs(cases['precision']['net_usdt'] + 0.58176) < 1e-9
    assert cases['constant']['snapshot_values'][:2] == [1000, 1000]
    assert abs(cases['constant']['snapshot_values'][-1] - 999.7) < 1e-9
    assert abs(cases['constant']['daily_open_pretrade_DD_pct'] - 0.03) < 1e-9
    assert abs(cases['constant']['endpoints_inclusive_DD_pct_diagnostic'] - 0.06) < 1e-9
    assert abs(cases['peak']['daily_open_pretrade_DD_pct'] - 250 / 1249.7 * 100) < 1e-9
    try:
        audit(dict(zip(dates, [100]*4)), dates, '2021-03-06', dates[-1], 0.1, TICK_SIZE)
    except AssertionError:
        pass
    else:
        raise AssertionError('missing entry must fail')
    return cases

if __name__ == '__main__':
    from runtime_control import put, ROOT, sha
    put('benchmark-convention.json', CONVENTION)
    cases = artificial_tests()
    put('benchmark-artificial-receipt.json', {
        'status': 'PASS', 'source_prices': 'ARTIFICIAL_ONLY',
        'native_calls': 0, 'network_calls': 0,
        'source_sha256': sha((ROOT / 'benchmark_audit.py').read_bytes()),
        'convention_sha256': sha((ROOT / 'benchmark-convention.json').read_bytes()),
        'cases': cases,
    })
    print('Artificial benchmark checks PASS; convention fixed before market acquisition.')

