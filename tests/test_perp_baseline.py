"""Run native causal checks in the existing pinned runtime, without changing it."""
from pathlib import Path
import subprocess
import sys

PYTHON=Path('/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue-43-profile-driven-v1/venv/bin/python')


def test_pinned_native_perpetual_contract():
    if not PYTHON.exists():
        import pytest
        pytest.skip('pinned native environment unavailable')
    subprocess.run([str(PYTHON),str(Path(__file__).resolve())],check=True,timeout=45,
        stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)


if __name__ == '__main__':
    """Meaningful causal and full native behavior checks with synthetic prices only."""
    from pathlib import Path
    import sys
    import tempfile
    import unittest
    from types import SimpleNamespace

    ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
    from lab.perp_baseline_runner import native_environment
    native_environment()
    import pandas as pd
    import numpy as np
    from lab.perp_baseline import features,calibrate_fixed,PerpBaseline,PAIRS
    from lab.perp_baseline_runner import run_native,audit_native


    def fixture():
        dates=pd.date_range('2020-01-01',periods=24*45,freq='1h',tz='UTC')
        frames={};events={};metadata=[]
        for pair,price in zip(PAIRS,(60000.,3000.)):
            # Smooth persistent up/down segments with volatility changes, rounded
            # to real instrument ticks; no hand-authored entry/fill schedule.
            close=np.round(price*np.exp(.10*np.sin(np.arange(len(dates))/35)),1 if price==60000 else 2)
            op=np.r_[close[0],close[:-1]]
            frames[pair]=pd.DataFrame(dict(date=dates,open=op,high=np.maximum(op,close)*1.00001,
                low=np.minimum(op,close)*.99999,close=close,volume=1000.))
            event_dates=dates[::8]+pd.to_timedelta(np.where(np.arange(len(dates[::8]))%2,5,0),unit='ms')
            # Sign changes and non-zero ms ensure no grid join or zero-fill can pass.
            events[pair]=pd.DataFrame(dict(date=event_dates,open_fund=np.where(np.arange(len(event_dates))%2,.0001,-.0002),
                open_mark=close[::8]))
            base=pair.split('/')[0]
            metadata.append(dict(symbol=base+'USDT',baseAsset=base,filters=[
                dict(filterType='MARKET_LOT_SIZE',minQty='.001',maxQty='1000',stepSize='.001'),
                dict(filterType='LOT_SIZE',minQty='.001',maxQty='1000',stepSize='.001'),
                dict(filterType='PRICE_FILTER',minPrice='.01',maxPrice='1000000',tickSize='.1' if base=='BTC' else '.01'),
                dict(filterType='MIN_NOTIONAL',notional='100' if base=='BTC' else '20')]))
        return frames,events,metadata


    class PerpTests(unittest.TestCase):
        def test_features_and_calibration_never_read_future(self):
            frames,_,_=fixture();original=frames[PAIRS[0]]
            pd.testing.assert_frame_equal(features(original.iloc[:500]),features(original).iloc[:500])
            end=original.date.iloc[500]
            a=calibrate_fixed(frames,original.date.iloc[170],end)
            changed={p:f.copy() for p,f in frames.items()}
            for frame in changed.values():
                frame.loc[frame.date>=end,['open','high','low','close']]*=100
            self.assertEqual(a,calibrate_fixed(changed,original.date.iloc[170],end))
            self.assertTrue(.25<=a[0]<=1)

        def test_signal_availability_extra_lag(self):
            frames,_,_=fixture();f=features(frames[PAIRS[0]])
            s=PerpBaseline({'perp_variant':'baseline'})
            got=s.populate_entry_trend(f.copy(),{'pair':PAIRS[0]})
            expected=(f.baseline_long & f.risk_multiplier.notna()).shift(1,fill_value=False).astype(int)
            pd.testing.assert_series_equal(got.enter_long,expected,check_names=False)

        def test_dynamic_risk_and_minimum_cannot_inflate_order(self):
            frames,_,_=fixture();frame=features(frames[PAIRS[0]]).iloc[:300].copy()
            frame['risk_multiplier']=.5
            strategy=PerpBaseline({'perp_variant':'volatility','perp_fixed_multiplier':.8})
            strategy.dp=SimpleNamespace(get_analyzed_dataframe=lambda *a:(frame,None))
            strategy.wallets=SimpleNamespace(get_total_stake_amount=lambda:1000.)
            strategy.entry_audit=[]
            args=dict(pair=PAIRS[0],current_time=frame.iloc[-1].date+pd.Timedelta(hours=1),
                current_rate=60000.,proposed_stake=400.,max_stake=1000.,leverage=1.,entry_tag='test',side='long')
            self.assertEqual(strategy.custom_stake_amount(min_stake=100.,**args),200.)
            self.assertEqual(strategy.custom_stake_amount(min_stake=250.,**args),0.)

        def test_native_full_signals_long_short_shared_wallet_and_exact_funding(self):
            frames,events,metadata=fixture()
            start=pd.Timestamp('2020-01-08T00:00:00Z');end=pd.Timestamp('2020-02-15T00:00:00Z')
            with tempfile.TemporaryDirectory(prefix='perp-native-synthetic-') as tmp:
                result,artifact=run_native(Path(tmp),frames,events,metadata,'baseline',.8,start,end)
                audit,points=audit_native(result,frames,events,start,end)
                self.assertEqual(audit['accounting_reconciliation'],'PASS')
                self.assertTrue(artifact)
                self.assertEqual({t['pair'] for t in result['trades']},set(PAIRS))
                self.assertEqual({t['is_short'] for t in result['trades']},{True,False})
                self.assertTrue(any(p['gross_exposure']>500 for p in points))
                self.assertTrue(all(t['trade_duration']<=72*60 for t in result['trades']))
                for t in result['trades']:
                    first=pd.to_datetime(t['open_timestamp'],unit='ms',utc=True)
                    f=features(frames[t['pair']]);source=f.loc[f.date==first-pd.Timedelta(hours=2)].iloc[0]
                    self.assertTrue(source.baseline_short if t['is_short'] else source.baseline_long)


    if __name__=='__main__':unittest.main()
