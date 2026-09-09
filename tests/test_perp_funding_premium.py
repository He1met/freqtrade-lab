"""Causal sign-gate checks and one synthetic native wallet, no market replay."""
from pathlib import Path
import subprocess

PYTHON = Path('/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue-43-profile-driven-v1/venv/bin/python')


def test_funding_premium_native_contract():
    if not PYTHON.exists():
        import pytest
        pytest.skip('pinned native environment unavailable')
    run = subprocess.run([str(PYTHON), str(Path(__file__).resolve())], capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stdout+'\n'+run.stderr


if __name__ == '__main__':
    import sys, tempfile, unittest
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from lab.perp_baseline_runner import native_environment, audit_native
    native_environment()
    import numpy as np
    import pandas as pd
    from lab.perp_baseline import PAIRS, PerpBaseline, features
    from lab.perp_funding_premium import align_factors, gate_masks, PerpFundingPremiumV1, run_native_factor

    def fixture():
        dates = pd.date_range('2020-01-01', periods=24*35, freq='1h', tz='UTC')
        frames={}; events={}; factors={}; metadata=[]
        for pair, price in zip(PAIRS, (60000., 3000.)):
            close = np.round(price*np.exp(.10*np.sin(np.arange(len(dates))/35)), 1 if price==60000 else 2)
            op = np.r_[close[0], close[:-1]]
            frames[pair] = pd.DataFrame(dict(date=dates, open=op, high=np.maximum(op, close)*1.00001,
                low=np.minimum(op, close)*.99999, close=close, volume=1000.))
            event_at = dates[::8]+pd.Timedelta(milliseconds=5)
            rate = -.0001*np.sign(np.cos(np.arange(len(dates))[::8]/35))
            events[pair] = pd.DataFrame(dict(date=event_at, open_fund=rate, open_mark=close[::8]))
            funding = pd.DataFrame(dict(funding_event_at=event_at, funding_available_at=event_at+pd.Timedelta(hours=1), funding_rate=rate))
            premium = pd.DataFrame(dict(date=dates, premium_available_at=dates+pd.Timedelta(hours=1, seconds=60),
                premium_close=-.0001*np.sign(np.cos(np.arange(len(dates))/35))))
            factors[pair] = align_factors(dates, funding, premium)
            base = pair.split('/')[0]
            metadata.append(dict(symbol=base+'USDT', baseAsset=base, filters=[
                dict(filterType='MARKET_LOT_SIZE', minQty='.001', maxQty='1000', stepSize='.001'),
                dict(filterType='LOT_SIZE', minQty='.001', maxQty='1000', stepSize='.001'),
                dict(filterType='PRICE_FILTER', minPrice='.01', maxPrice='1000000', tickSize='.1' if base=='BTC' else '.01'),
                dict(filterType='MIN_NOTIONAL', notional='100' if base=='BTC' else '20')]))
        return frames, events, factors, metadata

    class FactorTests(unittest.TestCase):
        def test_exact_available_asof_and_unknown_gate(self):
            dates = pd.date_range('2020-01-01', periods=4, freq='1h', tz='UTC')
            funding = pd.DataFrame(dict(funding_event_at=[dates[0]],
                funding_available_at=[dates[1]+pd.Timedelta(seconds=61)], funding_rate=[-.1]))
            premium = pd.DataFrame(dict(date=dates, premium_available_at=dates+pd.Timedelta(hours=1, seconds=60), premium_close=[-.2]*4))
            result = align_factors(dates, funding, premium)
            self.assertFalse(result.iloc[0].factor_valid)
            self.assertTrue(result.iloc[1].factor_valid)
            long, short = gate_masks(result, 'carry_premium_agree')
            self.assertEqual(long.tolist(), [False, True, True, True]); self.assertFalse(short.any())
            later = funding.copy(); later.loc[0, 'funding_available_at'] = dates[-1]+pd.Timedelta(days=1)
            self.assertFalse(align_factors(dates, later, premium).factor_valid.any())
            with self.assertRaises(ValueError): gate_masks(result, 'optimize_threshold')

        def test_future_changes_do_not_change_prefix_and_parent_rules_preserved(self):
            frames, _, factors, _ = fixture(); pair = PAIRS[0]
            frame = features(frames[pair]).merge(factors[pair], on='date', validate='one_to_one')
            for variant in ('carry_nonpaying', 'carry_premium_agree'):
                strategy = PerpFundingPremiumV1({'perp_variant':'persistence', 'perp_factor_variant':variant})
                full = strategy.populate_entry_trend(frame.copy(), {})
                prefix = strategy.populate_entry_trend(frame.iloc[:500].copy(), {})
                pd.testing.assert_frame_equal(prefix, full.iloc[:500])
                changed = frame.copy(); changed.loc[500:, ['funding_rate', 'premium_close']] *= -100
                pd.testing.assert_frame_equal(strategy.populate_entry_trend(changed, {}).iloc[:500], full.iloc[:500])
                parent = PerpBaseline({'perp_variant':'persistence'}).populate_entry_trend(frame.copy(), {})
                self.assertTrue((full.enter_long <= parent.enter_long).all())
                self.assertTrue((full.enter_short <= parent.enter_short).all())
                self.assertEqual(strategy.populate_exit_trend.__func__, PerpBaseline.populate_exit_trend)
                self.assertEqual(strategy.custom_exit.__func__, PerpBaseline.custom_exit)

        def test_one_native_consumer_both_sides_fees_and_signal_audit(self):
            frames, events, factors, metadata = fixture()
            start = pd.Timestamp('2020-01-08T00Z'); end = pd.Timestamp('2020-02-05T00Z')
            with tempfile.TemporaryDirectory(prefix='perp-factor-synthetic-') as tmp:
                result, archives = run_native_factor(tmp, frames, events, metadata, factors, 'carry_premium_agree', start, end)
                audit, _ = audit_native(result, frames, events, start, end)
                self.assertEqual(audit['accounting_reconciliation'], 'PASS')
                self.assertEqual({t['is_short'] for t in result['trades']}, {True, False})
                self.assertEqual({t['pair'] for t in result['trades']}, set(PAIRS))
                self.assertTrue(archives)
                import json
                entries = json.loads((Path(tmp)/'entry-audit.json').read_text())
                self.assertTrue(entries)
                for row in entries:
                    self.assertLessEqual(pd.Timestamp(row['funding_available_at']), pd.Timestamp(row['decision_at']))
                    self.assertLessEqual(pd.Timestamp(row['premium_available_at']), pd.Timestamp(row['decision_at']))
                    self.assertLessEqual(pd.Timestamp(row['decision_at']), pd.Timestamp(row['at']))
                    self.assertEqual(pd.Timestamp(row['at'])-pd.Timestamp(row['signal_candle']), pd.Timedelta(hours=2))

    unittest.main()
