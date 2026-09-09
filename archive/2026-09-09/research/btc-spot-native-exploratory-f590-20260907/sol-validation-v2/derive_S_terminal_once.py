import http.client
import io
import json
import math
import zipfile
from collections import Counter
from urllib.parse import urlparse
import pandas as pd
from runtime_control import ROOT, put, append, sha, verify_freeze
from benchmark_audit import drawdown
from lab.database import get_connection

verify_freeze()
api = json.loads((ROOT / 'S-final-api.json').read_text())
assert api['status'] == 'SEARCH_FINALIST_FROZEN'
assert api['single_baseline']['maximum_attempts'] == 1
assert api['budget']['consumed_total'] == 1 and api['budget']['remaining'] == 0
assert len(api['attempts']) == 1
attempt = api['attempts'][0]
archive = ROOT / 'search-data-01' / attempt['evidence']['archive']['path']
assert sha(archive.read_bytes()) == attempt['evidence']['archive']['sha256']
with zipfile.ZipFile(archive) as z:
    name = next(n for n in z.namelist() if n.endswith('.json') and '_config' not in n)
    result = json.loads(z.read(name))['strategy']['BtcWeeklyMomentumFixedStake']
    wallet_name = next(n for n in z.namelist() if n.endswith('_wallet.feather'))
    wallet_bytes = z.read(wallet_name)
    wallet = pd.read_feather(io.BytesIO(wallet_bytes))
    code_name = next(n for n in z.namelist() if n.endswith('_BtcWeeklyMomentumFixedStake.py'))
    assert sha(z.read(code_name)) == 'e1ab5c109eded7a6bd0e4e5d7b07f6c8e3082640530129ea9a390a2f89944611'
trades = result['trades']
assert len(trades) == result['total_trades'] == 6
assert all(t['pair'] == 'SOL/USDT' and not t['is_short'] and t['leverage'] == 1 and t['fee_open'] == t['fee_close'] == 0.0012 for t in trades)
assert all(0 < t['stake_amount'] <= 250.000001 for t in trades)
gross = sum(t['amount'] * (t['close_rate'] - t['open_rate']) for t in trades)
fees = sum(t['amount'] * (t['open_rate'] * t['fee_open'] + t['close_rate'] * t['fee_close']) for t in trades)
net = sum(t['profit_abs'] for t in trades)
assert abs(gross - fees - net) < 1e-5
assert abs(result['final_balance'] - 1000 - net) < 1e-5
wins = sum(t['profit_abs'] for t in trades if t['profit_abs'] > 0)
losses = -sum(t['profit_abs'] for t in trades if t['profit_abs'] < 0)
pf = wins / losses if losses > 0 else None
assert pf is not None and abs(pf - result['profit_factor']) < 1e-8
assert set(wallet['currency']) <= {'USDT', 'SOL'}
assert wallet[['rate','balance']].notna().all().all()
assert ((wallet['rate'] * wallet['balance'] - wallet['total_quote']).abs() < 1e-7).all()
series = (wallet['rate'] * wallet['balance']).groupby(wallet['date']).sum().sort_index()
assert all(math.isfinite(v) and v > 0 for v in series.tolist())
daily_dd = drawdown(series.tolist())
assert abs(daily_dd - result['wallet_stats']['max_drawdown_account'] * 100) < 1e-8
dd_path = (series.cummax() - series) / series.cummax() * 100
trough_date = dd_path.idxmax()
peak_date = series.loc[:trough_date].idxmax()
largest = max(t['profit_abs'] for t in trades)
exits = Counter(t['exit_reason'] for t in trades)
summary_dd = result['max_drawdown_account'] * 100
gates = {'core_native_passed': True, 'minimum_6_trades': len(trades) >= 6,
         'net_strictly_positive': net > 0, 'PF_at_least_1_10': pf >= 1.10,
         'summary_DD_at_most_10_pct': summary_dd <= 10,
         'daily_open_wallet_DD_at_most_10_pct': daily_dd <= 10,
         'remove_largest_winner_net_strictly_positive': net - largest > 0,
         'ROI_exit_count_zero': exits.get('roi', 0) == 0,
         'frozen_identity_fee_stake_binding': True}
assert not gates['daily_open_wallet_DD_at_most_10_pct']
economic = {'gross_price_profit_usdt': gross, 'fee_slippage_proxy_usdt': fees,
    'fee_semantics': '.0012 per side already includes .0002 slippage proxy; no second slippage charge',
    'net_usdt': net, 'wallet_start': 1000, 'wallet_final': result['final_balance'], 'wallet_return_pct': net / 10,
    'nominal_stake': 250, 'net_divided_by_stake_pct': net / 250 * 100,
    'stake_ratio_warning': 'Nominal denominator, not compounded/annualized return',
    'actual_stake_min': min(t['stake_amount'] for t in trades), 'actual_stake_max': max(t['stake_amount'] for t in trades),
    'trades': len(trades), 'profit_factor': pf, 'summary_realized_close_date_DD_pct': summary_dd,
    'independently_recomputed_daily_open_wallet_DD_pct': daily_dd,
    'wallet_snapshot_rows': len(wallet), 'wallet_snapshot_dates': len(series),
    'wallet_first_snapshot': str(series.index[0]), 'wallet_last_snapshot': str(series.index[-1]),
    'wallet_DD_peak_date': str(peak_date), 'wallet_DD_peak_balance': float(series.loc[peak_date]),
    'wallet_DD_trough_date': str(trough_date), 'wallet_DD_trough_balance': float(series.loc[trough_date]),
    'wallet_DD_semantics': 'Native pre-trade daily-open wallet rate*balance grouped by date; no added synthetic initial/final point. Not daily-close/intraday worst MTM.',
    'independent_intraday_worst_MTM_DD_pct': None,
    'largest_winning_trade_net_usdt': largest,
    'largest_winner_share_of_net_pct': largest / net * 100,
    'largest_winner_share_of_positive_profits_pct': largest / wins * 100,
    'net_after_arithmetic_removal_of_largest_winner_usdt': net - largest,
    'removal_warning': 'Arithmetic diagnostic only, not replay or recomputed path/DD',
    'exit_counts': dict(exits), 'force_exit_end_censored_count': exits.get('force_exit', 0),
    'average_holding_minutes': sum(t['trade_duration'] for t in trades) / len(trades),
    'first_entry': min(t['open_date'] for t in trades), 'last_exit': max(t['close_date'] for t in trades),
    'calendar_Mondays': 49, 'first_score_Monday_not_executable': '2021-03-01',
    'calendar_later_Monday_slots': 48, 'sample_warning': 'Exactly minimum6. Neither6 nor full18 establishes statistical robustness.',
    'gates': gates, 'full_S_status': 'REJECTED_WALLET_DRAWDOWN',
    'market_benchmark_status': 'SKIPPED_MAIN_EXTERNAL_GATE_FAILED', 'market_benchmark_values': None,
    'cash_baseline': {'net_usdt': 0, 'DD_pct': 0},
    'full_three_stage_minimum_18_status': 'NOT_EVALUATED_D_H_UNOPENED',
}
put('S-economic-audit.json', economic)
put('S-benchmark-disposition.json', {'status': 'SKIPPED_MAIN_EXTERNAL_GATE_FAILED',
    'reason': 'Independently verified main wallet DD exceeds10%; root explicitly requires skipping market benchmark on main failure',
    'market_diagnostic_calls': 0, 'native_calls': 0, 'artificial_validation': 'PASS',
    'convention_sha256': sha((ROOT / 'benchmark-convention.json').read_bytes()),
    'benchmark_market_values': None, 'comparison_table_attachment': 'NOT_APPLICABLE_NOT_WRITTEN'})
con = get_connection(ROOT / 'lab.sqlite', read_only=True, must_exist=True)
try:
    counts = {t: con.execute('SELECT COUNT(*) FROM ' + t).fetchone()[0] for t in ['research_profiles','generation_runs','candidates','research_runs','backtest_executions','releases']}
finally:
    con.close()
ids = json.loads((ROOT / 'S-identities.json').read_text())
entry = json.loads((ROOT / 'console-entrypoint.json').read_text())
address = urlparse(entry['base_url'])
checks = []
for path in ['/console', '/api/generations/' + ids['generation_id'], '/api/search-campaigns/' + ids['search_campaign_id']]:
    c = http.client.HTTPConnection(address.hostname, address.port, timeout=10)
    c.request('GET', path)
    response = c.getresponse()
    raw = response.read()
    checks.append({'path': path, 'http_status': response.status, 'response_sha256': sha(raw)})
    c.close()
assert all(item['http_status'] == 200 for item in checks)
qc = json.loads((ROOT / 'source-qc-receipt.json').read_text())
generation = json.loads((ROOT / 'generation-final-api.json').read_text())
delivery = {'status': 'S_REJECTED_WALLET_DRAWDOWN_NO_DEVELOPMENT', 'project_core_status': api['status'],
    'core_finalist_is_not_full_protocol_pass': True, 'full_protocol_qualified_finalist': False,
    **ids, 'profile_id': 'sol-spot-fixed-rule-validation-f590-v2', 'database': str(ROOT / 'lab.sqlite'),
    'database_counts': counts, 'generation_status': generation['status'],
    'generation_tool_event_count': generation.get('tool_event_count'),
    'generation_preturn_diagnostic_count': generation.get('preturn_diagnostic_count'),
    'generation_code_sha256': generation['candidate']['code_sha256'],
    'source_qc': qc, 'archive': str(archive), 'archive_sha256': sha(archive.read_bytes()),
    'native_wallet_feather_sha256': sha(wallet_bytes),
    'candidate_derived_provenance_sha256': sha((archive.parent.parent / 'retained-data-provenance.json').read_bytes()),
    'result_sha256': sha((archive.parent.parent / 'result.json').read_bytes()),
    'protocol_sha256': sha((ROOT / 'protocol.json').read_bytes()),
    'economic_audit_sha256': sha((ROOT / 'S-economic-audit.json').read_bytes()),
    'economic': economic, 'page': entry['page'], 'http_checks': checks,
    'calls': {'original_metadata_GET': 1, 'capture_invocations': 1, 'capture_GETs': 9,
              'capture_retries': 0, 'prepare_S_total': 2, 'prepare_S_initial_control_failure': 1,
              'prepare_S_recovery': 1, 'prepare_D_machine_QC': 1, 'Generation': 1,
              'S_main_native': 1, 'market_benchmark_diagnostic': 0, 'benchmark_native': 0,
              'D_signal_or_native': 0, 'H_capture': 0, 'H_native': 0, 'Stress_native': 0,
              'BTC_R2': 0, 'market_smoke': 0},
    'remaining_authorized_native_calls': 0, 'unused_market_benchmark_slot': 'SKIPPED_NOT_REUSABLE_AFTER_FAILURE',
    'D_status': 'MACHINE_QC_PHYSICALLY_ISOLATED_RESEARCHER_VALUES_SIGNALS_RESULTS_UNREAD',
    'H_Stress': 'SEALED_UNREAD_UNACQUIRED', 'interpretation': 'Cross-asset conditional test, not independent macro sample',
    'source_command_failure_and_authorized_recovery_preserved': True,
    'disposition': 'Stop this protocol; no D, no recapture, no variants or relaxed risk gates. Console remains read-only for root review.',
}
put('S-final-delivery-receipt.json', delivery)
previous = json.loads((ROOT / 'S-controller-ledger.json').read_text())['after_sha256']
ledger = append({'record_type': 'SEARCH_PROTOCOL_REVIEW', 'status': delivery['status'],
    'core_status': api['status'], 'qualified_finalist': False, **ids,
    'failed_gates': ['wallet_daily_open_drawdown_pct_maximum_10'],
    'receipt_path': str(ROOT / 'S-final-delivery-receipt.json'),
    'receipt_sha256': sha((ROOT / 'S-final-delivery-receipt.json').read_bytes()),
    'archive_sha256': sha(archive.read_bytes()), 'economic': economic,
    'calls': delivery['calls'], 'S_consumed': True, 'D': delivery['D_status'],
    'H_Stress': delivery['H_Stress'], 'remaining_authorized_Search_runs': 0}, previous)
put('S-final-ledger-receipt.json', ledger)
print(json.dumps({'status': delivery['status'], 'delivery_sha256': sha((ROOT / 'S-final-delivery-receipt.json').read_bytes()),
    'economic_audit_sha256': sha((ROOT / 'S-economic-audit.json').read_bytes()),
    'economic': economic, 'counts': counts, 'ledger': ledger}, indent=2))
