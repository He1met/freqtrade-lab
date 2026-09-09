"""Pure event-clock and callback tests; no native engine, prices, returns or HTTP."""
from pathlib import Path
import subprocess

PYTHON = Path('/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue-43-profile-driven-v1/venv/bin/python')


def test_funding_change_pure_contract():
    if not PYTHON.exists():
        import pytest
        pytest.skip('pinned native environment unavailable')
    result = subprocess.run([str(PYTHON), str(Path(__file__).resolve())], capture_output=True, text=True, timeout=40)
    assert result.returncode == 0, result.stdout + '\n' + result.stderr


if __name__ == '__main__':
    import sys
    import tempfile
    import unittest
    from types import SimpleNamespace
    from unittest.mock import patch
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from lab.perp_baseline_runner import native_environment, native_config, sha
    native_environment()
    import pandas as pd
    from freqtrade.enums import RunMode
    from freqtrade.persistence import LocalTrade
    from freqtrade.strategy.strategy_wrapper import strategy_safe_wrapper
    from lab import perp_funding_change as change
    from lab.perp_baseline import PAIRS

    def fixture(jitter=True):
        at = pd.date_range('2025-01-01', periods=5, freq='8h', tz='UTC')
        if jitter: at += pd.to_timedelta([15, 3, 0, 5, 1], unit='ms')
        data = pd.DataFrame(dict(event_at=at, available_at=at+pd.Timedelta(hours=1),
            rate=[.0002, .0001, .0001, 0., -.0001]))
        dates = pd.date_range('2025-01-01', periods=60, freq='1h', tz='UTC')
        return dates, data

    def strategy(root, variant='change_contrarian'):
        dates, funding = fixture()
        schedule = change.build_event_schedule(dates, funding)
        config = native_config('persistence', 1.)
        config.update(runmode=RunMode.BACKTEST, perp_change_variant=variant, perp_change_files={})
        for pair in PAIRS:
            path = root/(pair.split('/')[0]+'.json')
            schedule.to_json(path, orient='table', date_format='iso', date_unit='us')
            config['perp_change_files'][pair] = dict(path=str(path), sha256=sha(path))
        result = change.PerpFundingChange(config)
        result.bot_start()
        result.wallets = SimpleNamespace(get_total_stake_amount=lambda: 1000.)
        return result, schedule, dates

    def stake(strategy, at, side='long'):
        return strategy.custom_stake_amount(PAIRS[0], at, 100., 1000., 10., 350., 1.,
            strategy.config['perp_change_variant'], side)

    def confirm(strategy, at, side='long'):
        return strategy.confirm_trade_entry(PAIRS[0], 'market', 3.5, 100., 'GTC', at,
            strategy.config['perp_change_variant'], side)

    class ChangeTests(unittest.TestCase):
        def test_strict_hour_with_exact_boundary_and_millisecond_jitter(self):
            for jitter in (False, True):
                dates, funding = fixture(jitter)
                table = change.build_event_schedule(dates, funding)
                self.assertEqual(table.execution_at.iloc[0], pd.Timestamp('2025-01-01T10Z'))
                self.assertEqual(table.date.iloc[0], pd.Timestamp('2025-01-01T09Z'))
                self.assertEqual(table.event_at.iloc[0], funding.event_at.iloc[1])
                self.assertTrue((table.execution_at > table.available_at).all())
                self.assertEqual(len(table), len(funding)-1)

        def test_previous_availability_is_also_required(self):
            dates, funding = fixture()
            funding.loc[0, 'available_at'] = pd.Timestamp('2025-01-01T11Z')
            table = change.build_event_schedule(dates, funding)
            self.assertEqual(table.execution_at.iloc[0], pd.Timestamp('2025-01-01T12Z'))

        def test_fixed_signs_zero_and_prefix_causality(self):
            dates, funding = fixture()
            table = change.build_event_schedule(dates, funding)
            self.assertEqual(table.level_direction.tolist(), [-1, -1, 0, 1])
            self.assertEqual(table.change_direction.tolist(), [1, 0, 1, 1])
            self.assertAlmostEqual(table.delta.iloc[0], -.0001)
            prefix = change.build_event_schedule(dates, funding.iloc[:3])
            pd.testing.assert_frame_equal(prefix, table.iloc[:2])
            funding.loc[4, 'rate'] = .0123
            pd.testing.assert_frame_equal(change.build_event_schedule(dates, funding).iloc[:2], prefix)

        def test_changed_cycle_gap_duplicate_and_early_availability_block(self):
            dates, funding = fixture()
            for mode in ('gap', 'duplicate', '4h', 'early'):
                value = funding.copy()
                if mode == 'gap': value = value.drop(2)
                if mode == 'duplicate': value.loc[2, 'event_at'] = value.event_at.iloc[1]
                if mode == '4h': value.loc[2, 'event_at'] = value.event_at.iloc[1] + pd.Timedelta(hours=4)
                if mode == 'early': value.loc[1, 'available_at'] = value.event_at.iloc[1]
                with self.assertRaises(ValueError): change.build_event_schedule(dates, value)

        def test_tail_admission_requires_full_eight_hours_before_native_last_bar(self):
            dates, funding = fixture()
            table = change.build_event_schedule(dates, funding)
            self.assertEqual(len(change.filter_schedule(table, pd.Timestamp('2025-01-01T00Z'), pd.Timestamp('2025-01-01T19Z'))), 1)
            self.assertEqual(len(change.filter_schedule(table, pd.Timestamp('2025-01-01T00Z'), pd.Timestamp('2025-01-01T18Z'))), 0)

        def test_no_extra_strategy_shift_or_price_condition(self):
            with tempfile.TemporaryDirectory(prefix='funding-change-pure-') as tmp:
                s, schedule, dates = strategy(Path(tmp))
                frame = s.populate_indicators(pd.DataFrame(dict(date=dates)), {'pair': PAIRS[0]})
                frame = s.populate_entry_trend(frame, {})
                pulses = frame.loc[frame.enter_long == 1, 'date'].tolist()
                expected = schedule.loc[schedule.change_direction == 1, 'execution_at'] - pd.Timedelta(hours=1)
                self.assertEqual(pulses, expected.tolist())
                exits = s.populate_exit_trend(frame, {})
                self.assertFalse(exits[['exit_long', 'exit_short']].to_numpy().any())

        def test_skip_open_event_cannot_resurrect_on_same_bar_exit(self):
            with tempfile.TemporaryDirectory(prefix='funding-change-pure-') as tmp:
                s, schedule, _ = strategy(Path(tmp)); at = schedule.execution_at.iloc[0]
                opened = {PAIRS[0]: [SimpleNamespace()], PAIRS[1]: []}
                with patch.object(LocalTrade, 'bt_trades_open_pp', opened):
                    s.bot_loop_start(at)
                    opened[PAIRS[0]] = []
                    s.bot_loop_start(at)
                    self.assertEqual(stake(s, at), 0.)
                    self.assertFalse(confirm(s, at))
                statuses = [r['status'] for r in s.event_audit if r['pair']==PAIRS[0]]
                self.assertEqual(statuses, ['SKIPPED_OPEN'])

        def test_event_entered_once_native_stake_clamp_and_eight_hour_exit(self):
            with tempfile.TemporaryDirectory(prefix='funding-change-pure-') as tmp:
                s, schedule, _ = strategy(Path(tmp)); at = schedule.execution_at.iloc[0]
                with patch.object(LocalTrade, 'bt_trades_open_pp', {}):
                    s.bot_loop_start(at)
                    self.assertEqual(stake(s, at), 350.)
                    self.assertTrue(confirm(s, at))
                    self.assertEqual(stake(s, at), 0.)
                    self.assertFalse(confirm(s, at))
                self.assertEqual(len(s.entry_audit), 1)
                self.assertTrue(s.entry_audit[0]['entry_confirmed'])
                self.assertEqual(s.entry_audit[0]['event_id'], schedule.event_id.iloc[0])
                trade = SimpleNamespace(open_date_utc=at)
                self.assertIsNone(s.custom_exit(PAIRS[0], trade, at+pd.Timedelta(hours=8)-pd.Timedelta(seconds=1), 0, 0))
                self.assertEqual(s.custom_exit(PAIRS[0], trade, at+pd.Timedelta(hours=8), 0, 0), 'holding_8h')
                self.assertEqual(s.stoploss, -.2)
                self.assertEqual(s.leverage(), 1.)

        def test_zero_direction_and_failed_native_entry_are_not_deferred(self):
            with tempfile.TemporaryDirectory(prefix='funding-change-pure-') as tmp:
                s, schedule, _ = strategy(Path(tmp))
                with patch.object(LocalTrade, 'bt_trades_open_pp', {}):
                    s.bot_loop_start(schedule.execution_at.iloc[0])
                    s.bot_loop_start(schedule.execution_at.iloc[0]+pd.Timedelta(hours=1))
                    s.bot_loop_start(schedule.execution_at.iloc[1])
                statuses = [r['status'] for r in s.event_audit if r['pair']==PAIRS[0]]
                self.assertEqual(statuses, ['READY', 'EXPIRED_NO_ENTRY', 'FLAT_ZERO'])

        def test_callback_causal_failure_escapes_native_default_stake_recovery(self):
            with tempfile.TemporaryDirectory(prefix='funding-change-pure-') as tmp:
                s, schedule, _ = strategy(Path(tmp)); at = schedule.execution_at.iloc[0]
                self.assertFalse(issubclass(change.FundingChangeFailure, Exception))
                with self.assertRaises(change.FundingChangeFailure):
                    strategy_safe_wrapper(lambda: stake(s, at), default_retval=999.)()
                with patch.object(LocalTrade, 'bt_trades_open_pp', {}): s.bot_loop_start(at)
                with self.assertRaises(change.FundingChangeFailure): stake(s, at, side='short')
                with self.assertRaises(change.FundingChangeFailure): stake(s, at-pd.Timedelta(hours=1))

    unittest.main()
