"""Isolated V2 execution tests: old parent tests/market calls are not rerun."""
from pathlib import Path
import subprocess

PYTHON=Path('/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue-43-profile-driven-v1/venv/bin/python')


def test_v2_native_contract():
    if not PYTHON.exists():
        import pytest
        pytest.skip('pinned native environment unavailable')
    run=subprocess.run([str(PYTHON),str(Path(__file__).resolve())],capture_output=True,text=True,timeout=45)
    assert run.returncode==0,run.stdout+'\n'+run.stderr


if __name__=='__main__':
    import sys,tempfile,unittest
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
    from lab.perp_baseline_runner import native_environment,audit_native
    native_environment()
    import pandas as pd
    import numpy as np
    from lab.perp_baseline import PAIRS,PerpBaseline,features
    from lab.perp_variant_v2 import PerpTurnoverV2,run_native_v2

    def fixture():
        dates=pd.date_range('2020-01-01',periods=24*35,freq='1h',tz='UTC')
        frames={};events={};metadata=[]
        for pair,price in zip(PAIRS,(60000.,3000.)):
            close=np.round(price*np.exp(.10*np.sin(np.arange(len(dates))/35)),1 if price==60000 else 2)
            op=np.r_[close[0],close[:-1]]
            frames[pair]=pd.DataFrame(dict(date=dates,open=op,high=np.maximum(op,close)*1.00001,low=np.minimum(op,close)*.99999,close=close,volume=1000.))
            d=dates[::8]+pd.to_timedelta(np.where(np.arange(len(dates[::8]))%2,5,0),unit='ms')
            events[pair]=pd.DataFrame(dict(date=d,open_fund=np.where(np.arange(len(d))%2,.0001,-.0002),open_mark=close[::8]))
            base=pair.split('/')[0]
            metadata.append(dict(symbol=base+'USDT',baseAsset=base,filters=[
                dict(filterType='MARKET_LOT_SIZE',minQty='.001',maxQty='1000',stepSize='.001'),
                dict(filterType='LOT_SIZE',minQty='.001',maxQty='1000',stepSize='.001'),
                dict(filterType='PRICE_FILTER',minPrice='.01',maxPrice='1000000',tickSize='.1' if base=='BTC' else '.01'),
                dict(filterType='MIN_NOTIONAL',notional='100' if base=='BTC' else '20')]))
        return frames,events,metadata

    class V2Tests(unittest.TestCase):
        def test_exactly_exit_changes_and_prefix_causal(self):
            frames,_,_=fixture();frame=features(frames[PAIRS[0]])
            parent=PerpBaseline({'perp_variant':'persistence'})
            expected=parent.populate_entry_trend(frame.copy(),{})
            for hours in (24,48):
                s=PerpTurnoverV2({'perp_variant':'persistence','perp_exit_hours':hours})
                pd.testing.assert_frame_equal(s.populate_entry_trend(frame.copy(),{}),expected)
                full=s.populate_exit_trend(frame.copy(),{})
                prefix=s.populate_exit_trend(frame.iloc[:500].copy(),{})
                pd.testing.assert_frame_equal(prefix,full.iloc[:500])
                direct=(frame.close<frame.low.shift(1).rolling(hours).min()).shift(1,fill_value=False).astype(int)
                pd.testing.assert_series_equal(full.exit_long,direct,check_names=False)
                self.assertEqual(s.stoploss,parent.stoploss)
                self.assertEqual(s.custom_stake_amount.__func__,parent.custom_stake_amount.__func__)
                self.assertEqual(s.custom_exit.__func__,parent.custom_exit.__func__)
            with self.assertRaises(ValueError):
                PerpTurnoverV2({'perp_variant':'persistence','perp_exit_hours':96}).populate_exit_trend(frame,{})

        def test_both_native_variants_exact_funding_and_actual_exit_rule(self):
            frames,events,metadata=fixture();start=pd.Timestamp('2020-01-08T00Z');end=pd.Timestamp('2020-02-05T00Z')
            for hours in (24,48):
                with tempfile.TemporaryDirectory(prefix=f'perp-v2-{hours}-') as tmp:
                    result,archive=run_native_v2(tmp,frames,events,metadata,hours,start,end)
                    audit,points=audit_native(result,frames,events,start,end)
                    self.assertEqual(audit['accounting_reconciliation'],'PASS')
                    self.assertEqual({t['is_short'] for t in result['trades']},{True,False})
                    self.assertEqual({t['pair'] for t in result['trades']},set(PAIRS))
                    self.assertTrue(all(t['trade_duration']<=72*60 for t in result['trades']))
                    self.assertTrue(archive)
                    for trade in result['trades']:
                        if trade['exit_reason']!='exit_signal':continue
                        close=pd.to_datetime(trade['close_timestamp'],unit='ms',utc=True)
                        frame=frames[trade['pair']].set_index('date');source=close-pd.Timedelta(hours=2)
                        prior=frame.loc[:source].iloc[-hours-1:-1]
                        self.assertTrue(frame.loc[source,'close']>prior.high.max() if trade['is_short'] else frame.loc[source,'close']<prior.low.min())

    unittest.main()
