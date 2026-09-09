"""Read-only assertions over the two saved native runs; never rematches."""
import hashlib
import json
import math
from datetime import datetime
from pathlib import Path

root = Path(__file__).resolve().parent
report = json.loads((root/'synthetic-native-report.json').read_text())
assert report['native_matching_calls'] == 2 and report['fixture_count'] == 2
assert report['network_attempts'] == [] and report['native_core_unchanged']
checks = []
def check(label, condition):
    assert condition, label
    checks.append({'check': label, 'status': 'PASSED'})

expected = {
 'direction_zero_boundary': [
  ('2030-01-28','2030-02-11',False,'exit_signal'),
  ('2030-02-11','2030-02-25',True,'exit_signal'),
  ('2030-02-25','2030-03-04',False,'exit_signal'),
  ('2030-03-11','2030-03-31',False,'force_exit')],
 'intrawEEK_stops': [
  ('2030-01-28','2030-01-30',False,'stop_loss'),
  ('2030-02-04','2030-02-11',False,'exit_signal'),
  ('2030-02-11','2030-02-13',True,'stop_loss'),
  ('2030-02-18','2030-02-25',True,'exit_signal'),
  ('2030-02-25','2030-03-04',False,'exit_signal'),
  ('2030-03-11','2030-03-31',False,'force_exit')]
}
for fixture in report['fixtures']:
    name = fixture['name']
    trades = json.loads((root/name/'native-trades.json').read_text())
    trace = json.loads((root/name/'native-wallet-trace.json').read_text())
    audit = json.loads((root/name/'conservative-audit.json').read_text())
    observed = [(t['open_date'][:10],t['close_date'][:10],t['is_short'],t['exit_reason']) for t in trades]
    check(name+':exact_dates_directions_and_exit_reasons', observed == expected[name])
    check(name+':all_entries_Monday_midnight', all(datetime.fromisoformat(t['open_date']).weekday()==0
        and t['open_date'][11:19]=='00:00:00' for t in trades))
    check(name+':same_direction_no_extra_roundtrips',len(trades)==len(expected[name]))
    check(name+':zero_signal_cash_week',all(not (t['open_date'][:10]<'2030-03-11'
        and t['close_date'][:10]>'2030-03-04') for t in trades))
    check(name+':prefix_causality_five_lengths',fixture['prefix_checks']==5)
    for date, old, new in [('2030-02-11',False,True),('2030-02-25',True,False)]:
        events=[e for e in trace if e['date'].startswith(date)]
        check(name+':'+date+':exit_then_entry_same_timestamp',len(events)==2
              and events[0]['before']['open'][0][1]==old and events[0]['after']['open']==[]
              and events[1]['before']==events[0]['after'] and events[1]['after']['open'][0][1]==new)
        closed=next(t for t in trades if t['close_date'].startswith(date))
        check(name+':'+date+':realized_costs_and_funding_before_new_margin',math.isclose(
            events[0]['after']['total'],events[0]['before']['total']+closed['profit_abs'],abs_tol=1e-7)
            and math.isclose(events[1]['after']['free'],events[1]['before']['free']-
            events[1]['after']['open'][0][2],abs_tol=1e-7))
    for i,t in enumerate(trades):
        side=-1 if t['is_short'] else 1
        expected_profit=side*(t['close_rate']-t['open_rate'])*t['amount']-t['amount']*(
            t['open_rate']*t['fee_open']+t['close_rate']*t['fee_close'])+t['funding_fees']
        check(name+':trade_'+str(i)+':fees_funding_price_reconcile',math.isclose(
            expected_profit,t['profit_abs'],abs_tol=2e-6))
        check(name+':trade_'+str(i)+':fixed_250_with_precision_only',249.999<=t['stake_amount']<=250
              and t['leverage']==1 and t['fee_open']==.001 and t['fee_close']==.001)
    check(name+':final_wallet_reconciles',math.isclose(1000+sum(t['profit_abs'] for t in trades),
                                                   fixture['native_final_balance'],abs_tol=1e-7))
    check(name+':native_and_conservative_cash_nonnegative',fixture['minimum_native_free_cash']>=0
          and audit['minimum_free_cash']>=0 and audit['cash_executable'])
    check(name+':last_row_force_at_open_not_end_close',trades[-1]['close_date']=='2030-03-31T00:00:00.000Z'
          and trades[-1]['exit_reason']=='force_exit' and math.isclose(trades[-1]['close_rate'],121.428571,abs_tol=1e-7)
          and all(t['open_date'][:10]<'2030-03-31' for t in trades))
    if name=='intrawEEK_stops':
        check(name+':long_stop_waits_until_next_Monday',trades[0]['close_date'][:10]=='2030-01-30'
              and trades[1]['open_date'][:10]=='2030-02-04')
        check(name+':short_stop_waits_until_next_Monday',trades[2]['close_date'][:10]=='2030-02-13'
              and trades[3]['open_date'][:10]=='2030-02-18')

core = Path('/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue-43-profile-driven-v1/freqtrade/freqtrade/optimize/backtesting.py')
core_text=core.read_text()
check('native_core_sha_unchanged',hashlib.sha256(core.read_bytes()).hexdigest()==report['core_sha256'])
check('last_row_no_entry_source_guard','trade_dir, not is_last_row' in core_text
      and 'can_enter\n            and trade_dir is not None' in core_text)
result={'label':'SYNTHETIC_ASSERTIONS_NO_MARKET_EVIDENCE','assertion_count':len(checks),'checks':checks,
        'additional_matching_calls':0,'source_report_sha256':hashlib.sha256((root/'synthetic-native-report.json').read_bytes()).hexdigest(),
        'limitations':['No forced stress on the final candle; only source review proves its exit/stop ordering.',
                       'Native free wallet defers costs to settlement; conservative cash audit is the cash eligibility check.',
                       'Synthetic harness is not proof of Candidate/Generation/Console or real-source readiness.']}
(root/'synthetic-assertions.json').write_text(json.dumps(result,indent=2))
print(json.dumps({'assertion_count':len(checks),'status':'PASSED','additional_matching_calls':0}))
