"""Pure synthetic causality, input-binding and callback checks; no Backtesting."""
from pathlib import Path
import subprocess

PYTHON = Path('/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue-43-profile-driven-v1/venv/bin/python')


def test_flow_pure_contract():
    if not PYTHON.exists():
        import pytest
        pytest.skip('pinned native environment unavailable')
    run = subprocess.run([str(PYTHON), str(Path(__file__).resolve())], capture_output=True, text=True, timeout=40)
    assert run.returncode == 0, run.stdout + '\n' + run.stderr


if __name__ == '__main__':
    import json
    import sys
    import tempfile
    import unittest
    from types import SimpleNamespace
    from unittest.mock import patch
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from lab.perp_baseline_runner import native_environment, sha
    native_environment()
    import pandas as pd
    import numpy as np
    from lab import perp_flow_reversal as flow
    from lab.perp_baseline import PerpBaseline, PAIRS

    def fixture(sign=-1, count=220):
        dates = pd.date_range('2025-01-01', periods=count, freq='1h', tz='UTC')
        returns = np.where(np.arange(count) % 2, -.001, .001)
        returns[0] = 0.
        returns[194:200] = sign * .01
        returns[200] = -sign * .005
        close = 100 * np.exp(np.cumsum(returns))
        buy = np.full(count, 50.)
        buy[194:200] = 25. if sign < 0 else 75.
        buy[200] = 75. if sign < 0 else 25.
        return pd.DataFrame(dict(date=dates, open=close, high=close * 1.001, low=close * .999,
            close=close, volume=100., taker_buy_base_volume=buy,
            flow_available_at=dates + pd.Timedelta(hours=1, seconds=60)))

    def source_fixture(root):
        raw = fixture()
        columns = ['date', 'open', 'high', 'low', 'close', 'volume']
        frames = {p: raw[columns].copy() for p in PAIRS}
        protocol = json.loads(flow.PROTOCOL.read_bytes())
        protocol.update(source_root=str(root), score_end_exclusive=(raw.date.iloc[-1] + pd.Timedelta(hours=1)).isoformat())
        receipt = dict(historical_use='EXPOSED_DEVELOPMENT_NO_INDEPENDENT_CONFIRMATION',
            window_start=protocol['source_start'], window_end_exclusive=protocol['score_end_exclusive'], datasets={})
        for pair in PAIRS:
            name = pair.split('/')[0] + 'USDT-ohlcv'
            path = root / (name + '.jsonl')
            rows = [dict(event_time=row.date.isoformat(), available_at=row.flow_available_at.isoformat(),
                fetched_at='2026-09-08T15:07:34Z', quality='HISTORICAL_CLOSED_BAR_CONSERVATIVE_60S_LAG',
                **{c: str(getattr(row, c)) for c in ('open', 'high', 'low', 'close', 'volume', 'taker_buy_base_volume')})
                for row in raw.itertuples()]
            path.write_text(''.join(json.dumps(r) + '\n' for r in rows))
            receipt['datasets'][name] = dict(path=path.name, sha256=sha(path), rows=len(rows))
            protocol['ohlcv_sha256'][name] = sha(path)
        (root / 'receipt.json').write_text(json.dumps(receipt))
        protocol['source_receipt_sha256'] = sha(root / 'receipt.json')
        (root / 'protocol.json').write_text(json.dumps(protocol))
        return frames

    class FlowTests(unittest.TestCase):
        def test_frozen_formula_and_long_short_mirror(self):
            for sign in (-1, 1):
                raw = fixture(sign)
                value = flow.flow_features(raw)
                r = np.log(raw.close / raw.close.shift(1))
                expected = r.iloc[194:200].sum() / (r.iloc[32:200].std(ddof=0) * np.sqrt(6))
                self.assertAlmostEqual(value.shock_z.iloc[200], expected)
                self.assertAlmostEqual(value.pressure_prior.iloc[200], sign * .5)
                self.assertAlmostEqual(value.pressure_current.iloc[200], -sign * .5)
                for variant in flow.VARIANTS:
                    long, short = flow.flow_masks(value, variant)
                    self.assertEqual(bool(long.iloc[200]), sign < 0)
                    self.assertEqual(bool(short.iloc[200]), sign > 0)

        def test_future_changes_do_not_change_prefix(self):
            raw = fixture()
            expected = flow.flow_features(raw).iloc[:205]
            raw.loc[205:, 'close'] *= 10.
            raw.loc[205:, 'taker_buy_base_volume'] = 99.
            pd.testing.assert_frame_equal(flow.flow_features(raw).iloc[:205], expected)
            pd.testing.assert_frame_equal(flow.flow_features(raw.iloc[:205]), expected)

        def test_current_change_cannot_enter_prior_shock_or_pressure(self):
            raw = fixture()
            before = flow.flow_features(raw).iloc[200]
            raw.loc[200:, 'close'] *= 1.02
            raw.loc[200, 'taker_buy_base_volume'] = 100.
            after = flow.flow_features(raw).iloc[200]
            for key in ('shock_z', 'pressure_prior'):
                self.assertEqual(before[key], after[key])
            self.assertNotEqual(before.source_return, after.source_return)
            self.assertNotEqual(before.pressure_current, after.pressure_current)

        def test_gate_is_subset_and_equal_zero_fails(self):
            raw = fixture()
            raw.loc[200, 'taker_buy_base_volume'] = 50.
            value = flow.flow_features(raw)
            base = flow.flow_masks(value, 'shock_rebound')
            gate = flow.flow_masks(value, 'flow_turn')
            self.assertTrue(base[0].iloc[200])
            self.assertFalse(gate[0].iloc[200])
            for b, g in zip(base, gate):
                self.assertTrue((~g | b).all())
            with self.assertRaises(ValueError):
                flow.flow_masks(value, 'adaptive_threshold')

        def test_missing_zero_and_late_data_do_not_create_entry(self):
            for kind in ('flat', 'volume', 'late'):
                raw = fixture()
                if kind == 'flat': raw['close'] = 100.
                if kind == 'volume': raw.loc[200, ['volume', 'taker_buy_base_volume']] = 0.
                if kind == 'late': raw.loc[200, 'flow_available_at'] += pd.Timedelta(seconds=1)
                value = flow.flow_features(raw)
                self.assertFalse(value.flow_valid.iloc[200])
                self.assertFalse(any(bool(m.iloc[200]) for m in flow.flow_masks(value, 'flow_turn')))

        def test_extra_shift_and_fixed_holding_callback(self):
            strategy = flow.PerpFlowReversal({'perp_variant': 'persistence', 'perp_flow_variant': 'flow_turn'})
            value = flow.flow_features(fixture())
            entered = strategy.populate_entry_trend(value.copy(), {})
            expected = flow.flow_masks(value, 'flow_turn')[0].shift(1, fill_value=False).astype(int)
            pd.testing.assert_series_equal(entered.enter_long, expected, check_names=False)
            self.assertEqual(entered.enter_long.iloc[201], 1)
            exited = strategy.populate_exit_trend(value.copy(), {})
            self.assertFalse(exited[['exit_long', 'exit_short']].to_numpy().any())
            opened = pd.Timestamp('2025-01-09T10Z')
            trade = SimpleNamespace(open_date_utc=opened)
            self.assertIsNone(strategy.custom_exit(PAIRS[0], trade, opened + pd.Timedelta(hours=12) - pd.Timedelta(seconds=1), 100, 0))
            self.assertEqual(strategy.custom_exit(PAIRS[0], trade, opened + pd.Timedelta(hours=12), 100, 0), 'holding_12h')
            self.assertEqual(strategy.minimal_roi, {})
            self.assertTrue(strategy.use_exit_signal)
            self.assertEqual(strategy.stoploss, PerpBaseline.stoploss)
            self.assertEqual(strategy.leverage(), 1.)

        def test_stake_uses_source_two_hours_back_and_native_clamp(self):
            strategy = flow.PerpFlowReversal({'perp_variant': 'persistence', 'perp_flow_variant': 'flow_turn'})
            frame = flow.flow_features(fixture()).iloc[:202]
            strategy.dp = SimpleNamespace(get_analyzed_dataframe=lambda *a: (frame, None))
            strategy.wallets = SimpleNamespace(get_total_stake_amount=lambda: 1000.)
            strategy.entry_audit = []
            now = frame.date.iloc[-2] + pd.Timedelta(hours=2)
            kwargs = dict(current_rate=100., proposed_stake=1000., min_stake=10., max_stake=250.,
                leverage=1., entry_tag='flow_turn', side='long')
            self.assertEqual(strategy.custom_stake_amount(PAIRS[0], now, **kwargs), 250.)
            self.assertEqual(strategy.entry_audit[-1]['signal_candle'], frame.date.iloc[-2].isoformat())
            with self.assertRaises(flow.FlowAuditFailure):
                strategy.custom_stake_amount(PAIRS[0], now - pd.Timedelta(hours=1), **kwargs)

        def test_fatal_causal_failure_cannot_be_default_stake(self):
            from freqtrade.strategy.strategy_wrapper import strategy_safe_wrapper
            def reject():
                raise flow.FlowAuditFailure('causal failure')
            self.assertFalse(issubclass(flow.FlowAuditFailure, Exception))
            with self.assertRaises(flow.FlowAuditFailure):
                strategy_safe_wrapper(reject, default_retval=999.)()

        def test_loader_binding_and_no_feature_calculation(self):
            with tempfile.TemporaryDirectory(prefix='flow-pure-') as tmp:
                root = Path(tmp)
                frames = source_fixture(root)
                with patch.object(flow, 'SOURCE_ROOT', root), patch.object(flow, 'PROTOCOL', root / 'protocol.json'), \
                        patch.object(flow, 'flow_features', side_effect=AssertionError('loader must not compute signals')):
                    tables, binding = flow.load_flow_source(root, frames)
                    self.assertEqual(set(tables), set(PAIRS))
                    self.assertEqual(binding['BTCUSDT-ohlcv']['sha256'], sha(root / 'BTCUSDT-ohlcv.jsonl'))
                    self.assertEqual(list(tables[PAIRS[0]]), ['date', 'taker_buy_base_volume', 'flow_available_at'])
                    changed = {p: f.copy() for p, f in frames.items()}
                    changed[PAIRS[0]].loc[0, 'close'] *= 1.01
                    with self.assertRaisesRegex(ValueError, 'frame OHLCV mismatch'):
                        flow.load_flow_source(root, changed)
                    with (root / 'BTCUSDT-ohlcv.jsonl').open('a') as f: f.write('\n')
                    with self.assertRaisesRegex(ValueError, 'SHA mismatch'):
                        flow.load_flow_source(root, frames)

        def test_nonhistorical_root_is_rejected_before_reading(self):
            with self.assertRaisesRegex(ValueError, 'only frozen first-capture'):
                flow.load_flow_source(Path('/does-not-exist/forward-signals'), {})

    unittest.main()
