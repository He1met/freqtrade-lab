"""Pure actual-fill provenance cases; no native matching or market inputs."""
from pathlib import Path
import subprocess

PYTHON = Path('/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue-43-profile-driven-v1/venv/bin/python')


def test_funding_change_runner_contract():
    if not PYTHON.exists():
        import pytest
        pytest.skip('pinned native environment unavailable')
    result = subprocess.run([str(PYTHON), str(Path(__file__).resolve())],
                            capture_output=True, text=True, timeout=40)
    assert result.returncode == 0, result.stdout + '\n' + result.stderr


if __name__ == '__main__':
    import sys
    import unittest
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from lab.perp_baseline_runner import native_environment
    native_environment()  # Import/check only; no Backtesting object is constructed.
    import pandas as pd
    from lab.perp_baseline import PAIRS
    from lab.perp_funding_change import build_event_schedule
    from scripts import run_perp_funding_change_v1 as runner

    def fixture(variant='change_contrarian', sign=1, indices=(0,)):
        dates = pd.date_range('2025-01-08', periods=80, freq='1h', tz='UTC')
        event_at = pd.to_datetime(['2025-01-08T00:00:00.015Z', '2025-01-08T08:00:00.005Z',
                                  '2025-01-08T16:00:00.009Z', '2025-01-09T00:00:00.013Z'], utc=True)
        funding = pd.DataFrame(dict(event_at=event_at, available_at=event_at + pd.Timedelta(hours=1),
                                    rate=[sign * r for r in (-.0002, .0001, .0002, .0003)]))
        schedule = build_event_schedule(dates, funding)
        trades, records = [], []
        for index in indices:
            row = schedule.iloc[index]
            at = row.execution_at
            short = row.rate > 0 if variant == 'level_contrarian' else row.delta > 0
            trades.append(dict(pair=PAIRS[0], open_timestamp=int(at.timestamp() * 1000),
                               close_timestamp=int((at + pd.Timedelta(hours=8)).timestamp() * 1000),
                               is_short=bool(short), leverage=1, enter_tag=variant, exit_reason='holding_8h'))
            record = {key: value.isoformat() if hasattr(value, 'isoformat') else value
                      for key, value in row.items()}
            record.update(pair=PAIRS[0], at=at.isoformat(), signal_candle=row.date.isoformat(),
                          side='short' if short else 'long', variant=variant, accepted_stake=400.,
                          multiplier=1., entry_confirmed=True)
            records.append(record)
        return dict(result={'trades': trades}, records=records, variant=variant,
                    schedules={pair: schedule.copy(deep=True) for pair in PAIRS},
                    start=dates[0], end=dates[-1] + pd.Timedelta(hours=1))

    class FundingChangeRunnerTests(unittest.TestCase):
        def test_complete_long_short_controls_keep_real_millisecond_sources(self):
            for variant in ('level_contrarian', 'change_contrarian'):
                for sign in (-1, 1):
                    with self.subTest(variant=variant, sign=sign):
                        data = fixture(variant, sign)
                        record = data['records'][0]
                        self.assertEqual(pd.Timestamp(record['execution_at']), pd.Timestamp('2025-01-08T10Z'))
                        self.assertEqual(pd.Timestamp(record['event_at']).microsecond, 5000)
                        self.assertEqual(pd.Timestamp(record['previous_event_at']).microsecond, 15000)
                        result = runner.verify_entries(**data)
                        self.assertEqual(result['actual_position_cycles'], 1)
                        self.assertTrue(result['event_unique'])
                        self.assertFalse(result['occupied_hour_replay'])

        def test_equal_or_later_availability_cannot_validate_early_entry(self):
            for column in ('available_at', 'previous_available_at'):
                for seconds in (0, 1):
                    with self.subTest(column=column, seconds=seconds):
                        data = fixture()
                        at = pd.Timestamp(data['records'][0]['execution_at'])
                        data['schedules'][PAIRS[0]].loc[0, column] = at + pd.Timedelta(seconds=seconds)
                        data['records'][0][column] = (at + pd.Timedelta(seconds=seconds)).isoformat()
                        with self.assertRaisesRegex(ValueError, 'strictly later boundary'):
                            runner.verify_entries(**data)

        def test_one_event_cannot_be_reused_at_a_later_nonoverlapping_hour(self):
            data = fixture(indices=(0, 2))
            event_id = data['schedules'][PAIRS[0]].loc[0, 'event_id']
            data['schedules'][PAIRS[0]].loc[2, 'event_id'] = event_id
            data['records'][1]['event_id'] = event_id
            with self.assertRaisesRegex(ValueError, 'same funding event entered twice'):
                runner.verify_entries(**data)

        def test_same_hour_exit_cannot_revive_entry_but_earlier_stop_can(self):
            data = fixture(indices=(0, 1))
            with self.assertRaisesRegex(ValueError, 'occupied-hour'):
                runner.verify_entries(**data)
            data['result']['trades'][0]['close_timestamp'] -= 3600000
            data['result']['trades'][0]['exit_reason'] = 'stop_loss'
            result = runner.verify_entries(**data)
            self.assertEqual(result['actual_position_cycles'], 2)

        def test_nonstop_holds_must_finish_eight_hours_and_not_cross_native_tail(self):
            for mutation in ('shortened', 'too_long', 'force_exit', 'tail'):
                with self.subTest(mutation=mutation):
                    data = fixture()
                    trade = data['result']['trades'][0]
                    if mutation == 'shortened':
                        trade['close_timestamp'] -= 3600000
                    elif mutation == 'too_long':
                        trade['close_timestamp'] += 1000
                    elif mutation == 'force_exit':
                        trade['exit_reason'] = 'force_exit'
                    else:
                        data['end'] = pd.to_datetime(trade['close_timestamp'], unit='ms', utc=True)
                    with self.assertRaises(ValueError):
                        runner.verify_entries(**data)

        def test_missing_unconfirmed_wrong_side_tag_or_event_audit_is_rejected(self):
            for mutation in ('missing', 'unconfirmed', 'side', 'tag', 'audit_variant', 'event', 'multiplier'):
                with self.subTest(mutation=mutation):
                    data = fixture()
                    record = data['records'][0]
                    if mutation == 'missing':
                        data['records'] = []
                    elif mutation == 'unconfirmed':
                        record['entry_confirmed'] = False
                    elif mutation == 'side':
                        record['side'] = 'long'
                    elif mutation == 'tag':
                        data['result']['trades'][0]['enter_tag'] = 'level_contrarian'
                    elif mutation == 'audit_variant':
                        record['variant'] = 'level_contrarian'
                    elif mutation == 'event':
                        record['event_id'] = 'different-event'
                    else:
                        record['multiplier'] = 2
                    with self.assertRaises(ValueError):
                        runner.verify_entries(**data)

        def test_wrong_direction_zero_rate_or_unknown_variant_is_rejected(self):
            for mutation in ('direction', 'zero', 'variant'):
                with self.subTest(mutation=mutation):
                    data = fixture()
                    if mutation == 'direction':
                        data['result']['trades'][0]['is_short'] = False
                    elif mutation == 'zero':
                        data['schedules'][PAIRS[0]].loc[0, 'delta'] = 0.
                    else:
                        data['variant'] = 'posthoc_variant'
                        data['result']['trades'][0]['enter_tag'] = 'posthoc_variant'
                        data['records'][0]['variant'] = 'posthoc_variant'
                    with self.assertRaises(ValueError):
                        runner.verify_entries(**data)

        def test_rounded_funding_timestamp_or_changed_value_is_rejected(self):
            for field in ('event_at', 'previous_event_at', 'rate', 'previous_rate', 'delta', 'signal_candle'):
                with self.subTest(field=field):
                    data = fixture()
                    record = data['records'][0]
                    if field.endswith('_at'):
                        record[field] = pd.Timestamp(record[field]).floor('1s').isoformat()
                    elif field == 'signal_candle':
                        record[field] = (pd.Timestamp(record[field]) - pd.Timedelta(hours=1)).isoformat()
                    else:
                        record[field] += .00001
                    with self.assertRaises(ValueError):
                        runner.verify_entries(**data)

    unittest.main(verbosity=2)
