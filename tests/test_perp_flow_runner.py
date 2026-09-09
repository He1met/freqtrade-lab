"""Synthetic replay and actual-entry audit checks; never run a native backtest."""
from pathlib import Path
import subprocess

PYTHON = Path('/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue-43-profile-driven-v1/venv/bin/python')


def test_flow_runner_synthetic_contract():
    if not PYTHON.exists():
        import pytest
        pytest.skip('pinned native environment unavailable')
    run = subprocess.run([str(PYTHON), str(Path(__file__).resolve())], capture_output=True,
                         text=True, timeout=40)
    assert run.returncode == 0, run.stdout + '\n' + run.stderr


if __name__ == '__main__':
    import copy
    import json
    import sys
    import tempfile
    import unittest

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from lab.perp_baseline_runner import native_environment
    native_environment()  # Check/import the pinned library; no engine or market data.
    import numpy as np
    import pandas as pd
    from lab.perp_baseline import PAIRS
    from lab.perp_flow_reversal import flow_features
    from scripts import run_perp_flow_reversal_v1 as runner

    def fixture(sign=-1, variant='flow_turn'):
        dates = pd.date_range('2025-01-01', periods=220, freq='1h', tz='UTC')
        returns = np.where(np.arange(len(dates)) % 2, -.001, .001)
        returns[0] = 0.
        returns[194:200] = sign * .01
        returns[200] = -sign * .005
        close = 100 * np.exp(np.cumsum(returns))
        buy = np.full(len(dates), 50.)
        buy[194:200] = 25. if sign < 0 else 75.
        buy[200] = 75. if sign < 0 else 25.
        frame = pd.DataFrame(dict(date=dates, open=close, high=close * 1.001,
                                  low=close * .999, close=close, volume=100.))
        factor = pd.DataFrame(dict(date=dates, taker_buy_base_volume=buy,
                                   flow_available_at=dates + pd.Timedelta(hours=1, seconds=60)))
        frames = {pair: frame.copy() for pair in PAIRS}
        factors = {pair: factor.copy() for pair in PAIRS}
        source = flow_features(frame.merge(factor, on='date')).iloc[200]
        at = dates[202]
        trade = dict(pair=PAIRS[0], open_timestamp=int(at.timestamp() * 1000),
                     close_timestamp=int((at + pd.Timedelta(hours=12)).timestamp() * 1000),
                     is_short=sign > 0, leverage=1, enter_tag=variant)
        audit = dict(pair=PAIRS[0], at=at.isoformat(), accepted_stake=400.,
                     signal_candle=source.date.isoformat(),
                     flow_available_at=source.flow_available_at.isoformat(), multiplier=1.,
                     side='short' if sign > 0 else 'long', variant=variant,
                     **{name: float(source[name]) for name in
                        ('shock_z', 'source_return', 'pressure_prior', 'pressure_current')})
        return dict(result={'trades': [trade]}, records=[audit], variant=variant,
                    frames=frames, factors=factors, start=dates[176], end=dates[-1])

    class FlowRunnerTests(unittest.TestCase):
        def test_global_reservation_is_durable_and_directory_change_is_not_a_retry(self):
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                scheduler = root / 'scheduler'
                scheduler.mkdir()
                out = root / 'first-output'
                claim = root / 'claim.json'
                claim.write_text('{"id": "flow-1"}')
                current = dict(id='flow-1', dispatch_experiment_key='a' * 64,
                               expected_output_root=str(out))
                check = dict(code_sha256='b' * 64, data_sha256='c' * 64)
                global_path = runner.reserve_once(scheduler, current, claim, out, check)
                global_before = global_path.read_bytes()
                self.assertEqual(json.loads(global_before), json.loads((out / 'reservation.json').read_bytes()))
                alternate = root / 'alternate-output'
                with self.assertRaisesRegex(ValueError, 'registered experiment'):
                    runner.reserve_once(scheduler, current, claim, alternate, check)
                self.assertFalse(alternate.exists())
                # Even relabelling the task/output cannot reset a stable consumed experiment.
                renamed = dict(current, id='renamed-flow', expected_output_root=str(alternate))
                with self.assertRaises(FileExistsError):
                    runner.reserve_once(scheduler, renamed, claim, alternate, check)
                self.assertEqual(global_path.read_bytes(), global_before)
                self.assertFalse((alternate / 'reservation.json').exists())
                with self.assertRaisesRegex(ValueError, 'existing experiment artifacts'):
                    runner.reserve_once(scheduler, current, claim, out, check)

        def test_partial_output_is_preserved_without_allocating_another_reservation(self):
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                scheduler = root / 'scheduler'
                scheduler.mkdir()
                out = root / 'output'
                out.mkdir()
                manifest = out / 'manifest.json'
                manifest.write_text('{"partial": true}')
                claim = root / 'claim.json'
                claim.write_text('{}')
                current = dict(id='flow-1', dispatch_experiment_key='a' * 64,
                               expected_output_root=str(out))
                with self.assertRaisesRegex(ValueError, 'existing experiment artifacts'):
                    runner.reserve_once(scheduler, current, claim, out,
                                        dict(code_sha256='b' * 64, data_sha256='c' * 64))
                self.assertEqual(manifest.read_text(), '{"partial": true}')
                self.assertFalse((scheduler / 'development-reservations').exists())

        def test_deadline_cannot_be_swallowed_by_an_exception_fallback(self):
            def callback_wrapper():
                try:
                    raise runner.NativeDeadline('bounded timeout')
                except Exception:
                    return 'unsafe proposed-stake fallback'
            with self.assertRaises(runner.NativeDeadline):
                callback_wrapper()

        def test_complete_causal_long_short_and_both_registered_variants_pass(self):
            for sign in (-1, 1):
                for variant in ('shock_rebound', 'flow_turn'):
                    with self.subTest(sign=sign, variant=variant):
                        result = runner.verify_entries(**fixture(sign, variant))
                        self.assertEqual(result['status'], 'PASS')
                        self.assertEqual(result['actual_position_cycles'], 1)
                        self.assertFalse(result['callback_fallback_permitted'])

        def test_missing_rejected_and_duplicate_accepted_audit_are_rejected(self):
            for kind in ('missing', 'rejected', 'duplicate'):
                with self.subTest(kind=kind):
                    data = fixture()
                    if kind == 'missing':
                        data['records'] = []
                    elif kind == 'rejected':
                        data['records'][0]['accepted_stake'] = 0.
                    else:
                        data['records'].append(copy.deepcopy(data['records'][0]))
                    with self.assertRaisesRegex(ValueError, 'unique accepted audit'):
                        runner.verify_entries(**data)

        def test_audit_from_the_wrong_source_hour_is_rejected(self):
            data = fixture()
            record = data['records'][0]
            record['signal_candle'] = (pd.Timestamp(record['signal_candle']) - pd.Timedelta(hours=1)).isoformat()
            with self.assertRaises(ValueError):
                runner.verify_entries(**data)

        def test_audit_with_wrong_side_is_rejected(self):
            data = fixture()
            data['records'][0]['side'] = 'short'
            with self.assertRaises(ValueError):
                runner.verify_entries(**data)

        def test_wrong_audit_variant_and_native_entry_tag_are_rejected(self):
            for target in ('audit', 'trade'):
                with self.subTest(target=target):
                    data = fixture()
                    if target == 'audit':
                        data['records'][0]['variant'] = 'shock_rebound'
                    else:
                        data['result']['trades'][0]['enter_tag'] = 'shock_rebound'
                    with self.assertRaises(ValueError):
                        runner.verify_entries(**data)

        def test_fill_on_wrong_direction_or_unregistered_variant_is_rejected(self):
            data = fixture()
            data['result']['trades'][0]['is_short'] = True
            with self.assertRaises(ValueError):
                runner.verify_entries(**data)
            data = fixture()
            data['variant'] = 'posthoc_variant'
            with self.assertRaises(ValueError):
                runner.verify_entries(**data)

        def test_fabricated_factor_or_availability_audit_is_rejected(self):
            for field in ('shock_z', 'source_return', 'pressure_prior', 'pressure_current', 'flow_available_at'):
                with self.subTest(field=field):
                    data = fixture()
                    record = data['records'][0]
                    if field == 'flow_available_at':
                        record[field] = (pd.Timestamp(record[field]) + pd.Timedelta(seconds=1)).isoformat()
                    else:
                        record[field] += .1
                    with self.assertRaises(ValueError):
                        runner.verify_entries(**data)

        def test_time_holding_and_leverage_bounds_are_enforced_on_actual_trades(self):
            for field in ('early_entry', 'holding', 'leverage', 'close_after_window'):
                with self.subTest(field=field):
                    data = fixture()
                    trade = data['result']['trades'][0]
                    if field == 'early_entry':
                        trade['open_timestamp'] -= 3600000
                    elif field == 'holding':
                        trade['close_timestamp'] += 1000
                    elif field == 'leverage':
                        trade['leverage'] = 2
                    else:
                        data['end'] = pd.to_datetime(trade['close_timestamp'], unit='ms', utc=True) - pd.Timedelta(seconds=1)
                    with self.assertRaises(ValueError):
                        runner.verify_entries(**data)

        def test_absent_source_and_late_source_cannot_validate_a_fill(self):
            for kind in ('absent', 'late'):
                with self.subTest(kind=kind):
                    data = fixture()
                    if kind == 'absent':
                        data['frames'][PAIRS[0]] = data['frames'][PAIRS[0]].drop(index=200)
                        data['factors'][PAIRS[0]] = data['factors'][PAIRS[0]].drop(index=200)
                    else:
                        data['factors'][PAIRS[0]].loc[200, 'flow_available_at'] += pd.Timedelta(hours=1)
                    with self.assertRaises(ValueError):
                        runner.verify_entries(**data)

    unittest.main(verbosity=2)
