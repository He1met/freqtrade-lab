"""Read existing native archives and reconcile costs/timing; never run backtests."""
import hashlib
import json
import statistics
import subprocess
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pandas as pd
from lab.bounded_strategy import analyze_bounded_causal_strategy
from lab.database import get_connection

ROOT = Path(__file__).resolve().parent
SEARCH = ROOT / "search-campaign"
SOURCE = Path('/Users/shenjianpeng/.codex/runs/freqtrade-lab/exploratory-session-research-v1-13fd/source-acquisition')
state = json.loads((ROOT / "search-terminal-context.json").read_text())["state"]
frame = pd.read_feather(SEARCH / "acquisition/data/okx/futures/LINK_USDT_USDT-5m-futures.feather")
raw = frame.set_index("date")
records = []
D = Decimal


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


for attempt in state["attempts"]:
    archive = SEARCH / attempt["evidence"]["archive"]["path"]
    assert sha(archive) == attempt["evidence"]["archive"]["sha256"]
    with zipfile.ZipFile(archive) as z:
        member = next(n for n in z.namelist() if n.endswith('.json') and not n.endswith('_config.json'))
        native = json.loads(z.read(member), parse_float=D)["strategy"][attempt["class_name"]]
    trades = native['trades']
    source = (ROOT / (attempt['class_name'] + '.py')).read_text()
    assert hashlib.sha256(source.encode()).hexdigest() == attempt['strategy_sha256']
    analysis = analyze_bounded_causal_strategy(source, attempt['class_name'], expected_timeframe='5m')
    namespace = {}
    exec(compile(source, attempt['class_name'], 'exec'), namespace)
    strategy = namespace[attempt['class_name']]({})
    signals = frame.copy()
    for col in ('enter_long', 'enter_short', 'exit_long', 'exit_short'):
        signals[col] = 0
    for method in ('populate_indicators', 'populate_entry_trend', 'populate_exit_trend'):
        signals = getattr(strategy, method)(signals, {'pair': 'LINK/USDT:USDT'})
    signals = signals.set_index('date')
    fees = D(0)
    impact = D(0)
    funding = D(0)
    price_pnl = D(0)
    reported_net = D(0)
    residuals = []
    mismatches = Counter()
    exit_reasons = Counter()
    monthly = defaultdict(lambda: {'trades': 0, 'net_usdt': D(0), 'funding_usdt': D(0)})
    for t in trades:
        amount, opened, closed = D(t['amount']), D(t['open_rate']), D(t['close_rate'])
        fee = amount * (opened * D(t['fee_open']) + closed * D(t['fee_close']))
        haircut = amount * (opened + closed) * D('0.0002')
        f = t.get('funding_fees')
        if f is None:
            raise ValueError('Missing native funding_fees; cannot impute zero')
        f = D(f)
        gross = (opened - closed if t['is_short'] else closed - opened) * amount
        net = D(t['profit_abs'])
        fees += fee
        impact += haircut
        funding += f
        price_pnl += gross
        reported_net += net
        residuals.append(abs(net - (gross - fee + f)))
        entry = pd.Timestamp(t['open_date'])
        exit_ = pd.Timestamp(t['close_date'])
        direction = 'short' if t['is_short'] else 'long'
        prev_entry = entry - pd.Timedelta(minutes=5)
        if prev_entry not in signals.index or signals.loc[prev_entry, 'enter_' + direction] != 1:
            mismatches['entry_signal_prior_closed_bar'] += 1
        if entry not in raw.index or abs(D(str(raw.loc[entry, 'open'])) - opened) > D('0.00000001'):
            mismatches['entry_at_next_open_rate'] += 1
        reason = t['exit_reason']
        exit_reasons[reason] += 1
        if reason == 'exit_signal':
            prev_exit = exit_ - pd.Timedelta(minutes=5)
            if prev_exit not in signals.index or signals.loc[prev_exit, 'exit_' + direction] != 1:
                mismatches['exit_signal_prior_closed_bar'] += 1
            if exit_ not in raw.index or abs(D(str(raw.loc[exit_, 'open'])) - closed) > D('0.00000001'):
                mismatches['exit_at_next_open_rate'] += 1
        if not (pd.Timestamp('2024-02-01T00:00Z') <= entry <= exit_ < pd.Timestamp('2024-07-31T00:00Z')):
            mismatches['outside_frozen_window'] += 1
        month = exit_.strftime('%Y-%m')
        monthly[month]['trades'] += 1
        monthly[month]['net_usdt'] += net
        monthly[month]['funding_usdt'] += f
    durations = [t['trade_duration'] for t in trades]
    record = {
        'round': attempt['round'], 'class_name': attempt['class_name'],
        'candidate_id': attempt['candidate_id'], 'source_sha256': attempt['strategy_sha256'],
        'native_archive': str(archive), 'native_archive_sha256': sha(archive),
        'technical_status': attempt['technical_status'], 'trades': len(trades),
        'native_net_usdt': reported_net, 'native_report_net_usdt': native['profit_total_abs'],
        'native_net_pct_initial_wallet': reported_net / D(2000) * 100,
        'charged_fee_reconstructed_from_native_fills_and_rates_usdt': fees,
        'fee_open_cost_and_fee_close_cost_fields': 'NOT_EXPORTED',
        'funding_native_sum_usdt_positive_is_credit': funding,
        'funding_nonzero_trades': sum(t['funding_fees'] != 0 for t in trades),
        'price_only_gross_before_fees_and_funding_usdt': price_pnl,
        'maximum_trade_accounting_residual_usdt': max(residuals),
        'accounting_matches_export_rounding': max(residuals) < D('0.0000001'),
        'explanatory_2bps_per_side_deduction_usdt': impact,
        'explanatory_deducted_net_usdt': reported_net - impact,
        'explanatory_deducted_net_pct_initial_wallet': (reported_net - impact) / D(2000) * 100,
        'native_profit_factor': native['profit_factor'],
        'native_peak_drawdown_pct': native['max_drawdown_account'] * 100,
        'long_count': native['trade_count_long'], 'short_count': native['trade_count_short'],
        'average_holding_minutes': statistics.mean(durations),
        'median_holding_minutes': statistics.median(durations),
        'minimum_holding_minutes': min(durations), 'maximum_holding_minutes': max(durations),
        'exit_reason_counts': dict(exit_reasons),
        'monthly_by_close_date': dict(sorted(monthly.items())),
        'leverage_values': sorted(set(t['leverage'] for t in trades)),
        'fee_open_values': sorted(set(t['fee_open'] for t in trades)),
        'fee_close_values': sorted(set(t['fee_close'] for t in trades)),
        'max_open_trades': native['max_open_trades_setting'],
        'stoploss': native['stoploss'], 'minimal_roi': native['minimal_roi'],
        'first_entry_utc': min(t['open_date'] for t in trades),
        'last_exit_utc': max(t['close_date'] for t in trades),
        'native_backtest_start': native['backtest_start'], 'native_backtest_end': native['backtest_end'],
        'timing_or_window_mismatches': dict(mismatches), 'maximum_lookback': analysis.max_lookback,
        'native_gate_passed': len(trades) >= 12 and reported_net >= D(25)
            and native['profit_factor'] >= D('1.1') and native['max_drawdown_account'] <= D('0.15'),
    }
    records.append(record)

r1, r2 = records
connection = get_connection(ROOT / 'research.sqlite', read_only=True)
tables = [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
counts = {table: connection.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0] for table in tables}
reviews = [dict(row) for row in connection.execute("SELECT id,class_name,code_sha256,json_extract(metadata_json,'$.review.status') AS review FROM candidates ORDER BY created_at")]
generations = [dict(row) for row in connection.execute('SELECT id,status,source,model FROM generation_runs ORDER BY created_at')]
connection.close()
processes = subprocess.check_output(['ps', '-Ao', 'pid,args'], text=True).splitlines()
native_processes = [line for line in processes if ('screen-search' in line or 'run_freqtrade_backtest.py' in line) and not ('zsh -lc' in line or 'python3 - <<' in line)]
report = {
    'status': state['status'], 'research_mode': 'EXPLORATORY',
    'validation_status': 'NOT_INDEPENDENTLY_VALIDATED', 'campaign_id': state['campaign_id'],
    'checked_at_utc': datetime.now(timezone.utc).isoformat(),
    'public_commit': '8ae57c1ff05baa9fb6aa0dfcef83554e17890873',
    'native_commit': '52bc96f4480b1a0da6a9b455bd00b17fbb6786a5',
    'search_attempts_b': state['budget']['consumed_total'], 'max_attempts_a_plus_b': 4,
    'native_process_count_after_terminal': len(native_processes),
    'original_source_provenance_sha256': sha(SOURCE / 'retained-data-provenance.json'),
    'original_source_receipt_sha256': sha(SOURCE / 'retrieval_receipt.json'),
    'consumer_provenance_sha256': sha(SEARCH / 'acquisition/retained-data-provenance.json'),
    'terminal_sha256': sha(SEARCH / 'search-terminal.json'), 'ledger_sha256': sha(SEARCH / 'trials.jsonl'),
    'contracts_and_sources_unchanged': all(sha(ROOT / n) == expected for n, expected in json.loads((ROOT / 'preparation-metadata.json').read_text())['files_sha256'].items()),
    'database_counts': counts, 'candidates': reviews, 'generations': generations,
    'records': records,
    'r2_minus_r1_native_net_usdt': r2['native_net_usdt'] - r1['native_net_usdt'],
    'r2_minus_r1_explanatory_deducted_net_usdt': r2['explanatory_deducted_net_usdt'] - r1['explanatory_deducted_net_usdt'],
    'frozen_r2_increment_gate_passed': r1['trades'] >= 12 and r2['native_gate_passed']
        and r2['explanatory_deducted_net_usdt'] >= D(25)
        and r2['native_net_usdt'] > r1['native_net_usdt']
        and r2['explanatory_deducted_net_usdt'] > r1['explanatory_deducted_net_usdt'],
    'limitations': ['Exploratory reused historical pool, not independent validation',
        '12-trade screen and Gaussian scale illustration are not evidence of independent sample size',
        'Actual slippage UNKNOWN; 2bps per side is explanatory arithmetic only, not native PF or DD',
        'No Development/Holdout/Stress/Judge/Release or trading',
        'One rejected semantic-drift Generation plus one authorized technical retry retained; no extra real backtest'],
}


def normalize(value):
    if isinstance(value, D):
        return float(value)
    raise TypeError(type(value).__name__)


(ROOT / 'native-results-audit.json').write_text(json.dumps(report, default=normalize, indent=2) + '\n')
print(json.dumps(report, default=normalize, indent=2))
