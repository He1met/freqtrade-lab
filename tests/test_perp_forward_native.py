"""One synthetic native call; no public fetches or historical market replay."""
from pathlib import Path
import subprocess

PYTHON=Path('/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue-43-profile-driven-v1/venv/bin/python')


def test_forward_native_acceptance_contract():
    if not PYTHON.exists():
        import pytest
        pytest.skip('pinned native environment unavailable')
    run=subprocess.run([str(PYTHON),str(Path(__file__).resolve())],capture_output=True,text=True,timeout=60)
    assert run.returncode==0,run.stdout+'\n'+run.stderr


if __name__=='__main__':
    import sys,json,tempfile,unittest
    from datetime import timedelta
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
    from lab.perp_baseline_runner import native_environment,audit_native,write
    native_environment()
    import numpy as np
    import pandas as pd
    from lab.perp_forward_native import PAIRS,decode,source_pools,mask_signals,run_native_acceptance,sha
    from lab.perp_forward_signal import intent,encoded

    def fixture(root):
        root=root.resolve()
        start=pd.Timestamp('2026-09-08T17Z');end=pd.Timestamp('2026-09-09T00Z')
        dates=pd.date_range(start-pd.Timedelta(days=8),end,freq='1h',inclusive='left')
        files={};metadata=[]
        for pair,price in zip(PAIRS,(60000.,3000.)):
            close=np.round(price*np.exp(np.cumsum(.0005+.0001*np.sin(np.arange(len(dates))/7))),1 if price==60000 else 2)
            op=np.r_[close[0],close[:-1]]
            for kind in ('ohlcv','mark','premium','funding'):
                rows=[]
                for i,at in enumerate(dates):
                    if kind=='funding' and at.hour%8:continue
                    event=at+pd.Timedelta(milliseconds=5) if kind=='funding' else at
                    declared=event+pd.Timedelta(hours=1,seconds=0 if kind=='funding' else 60)
                    fetched=event+pd.Timedelta(hours=1,minutes=10)
                    row=dict(event_time=event.isoformat(),available_at=fetched.isoformat(),historical_available_at_assumption=declared.isoformat(),fetched_at=fetched.isoformat())
                    if kind=='funding':row.update(rate='-0.0002',mark_price=str(close[i]))
                    elif kind=='premium':row.update(open='0.0001',high='0.0002',low='0',close='0.0001',volume=None)
                    else:row.update(open=str(op[i]),high=str(max(op[i],close[i])*1.00001),low=str(min(op[i],close[i])*.99999),close=str(close[i]),volume='1000' if kind=='ohlcv' else None)
                    rows.append(row)
                path=root/(pair.split('/')[0]+'USDT-'+kind+'.jsonl')
                path.write_bytes(b''.join(encoded(r) for r in rows));files[str(path)]=sha(path)
            base=pair.split('/')[0]
            metadata.append(dict(symbol=base+'USDT',baseAsset=base,filters=[
                dict(filterType='MARKET_LOT_SIZE',minQty='.001',maxQty='1000',stepSize='.001'),
                dict(filterType='LOT_SIZE',minQty='.001',maxQty='1000',stepSize='.001'),
                dict(filterType='PRICE_FILTER',minPrice='.01',maxPrice='1000000',tickSize='.1' if base=='BTC' else '.01'),
                dict(filterType='MIN_NOTIONAL',notional='100' if base=='BTC' else '20')]))
        path=root/'instrument-rules.json';write(path,dict(symbols=metadata));files[str(path)]=sha(path)
        datasets={}
        for pair in PAIRS:
            name=pair.split('/')[0]+'USDT-funding';path=root/(name+'.jsonl')
            datasets[name]=dict(path=path.name,sha256=sha(path),rows=len(path.read_text().splitlines()))
        path=root/'receipt.json';write(path,dict(window_start=(start-pd.Timedelta(days=8)).isoformat(),window_end_exclusive=end.isoformat(),datasets=datasets,errors={}))
        files[str(path)]=sha(path)
        records=[]
        for planned in pd.date_range(start,end,freq='1h',inclusive='left'):
            if planned.hour==19:
                records.append(dict(planned_entry=planned.isoformat(),missing=True));continue
            source=planned-pd.Timedelta(hours=2);observed=planned-pd.Timedelta(minutes=40)
            pools=source_pools(files,source,observed)
            pairs={p:intent(p,pools,source) for p in PAIRS}
            raw=dict(source_candle=source.isoformat(),planned_entry=planned.isoformat(),nominal_cutoff=(source+pd.Timedelta(hours=1,seconds=60)).isoformat(),observed_at=observed.isoformat(),pairs=pairs,source_bindings=files.copy(),source_bundle_sha256=__import__('hashlib').sha256(encoded(files)).hexdigest())
            receipt=dict(published_observed_at=(observed+pd.Timedelta(seconds=1)).isoformat(),pairs={p:dict(r,status='TIMELY_SIGNAL' if r['intent']!='NO_TRADE' else 'TIMELY_NO_TRADE') for p,r in pairs.items()})
            records.append(dict(planned_entry=planned.isoformat(),intent=raw,receipt=receipt))
        return dict(start=start.isoformat(),end=end.isoformat(),frozen_observed_at=(end+pd.Timedelta(minutes=15)).isoformat(),capture_roots=[str(root)],source_files=files,records=records)

    class AcceptanceTests(unittest.TestCase):
        def test_query_coverage_and_late_receipt_without_native(self):
            with tempfile.TemporaryDirectory(prefix='perp-query-coverage-') as tmp:
                root=Path(tmp).resolve();snap=fixture(root)
                self.assertEqual(decode(snap)[-1]['complete_two_pair_hours'],6)
                record=snap['records'][0];record['receipt']['published_observed_at']=record['planned_entry']
                self.assertEqual(decode(snap)[-1]['complete_two_pair_hours'],5)
                receipt=root/'receipt.json';value=json.loads(receipt.read_text());value['errors']['BTCUSDT-funding']='BUDGET_STOP';write(receipt,value)
                snap['source_files'][str(receipt)]=sha(receipt)
                with self.assertRaisesRegex(ValueError,'funding query coverage incomplete'):decode(snap)

        def test_mask_missing_and_mismatched_natural_signals(self):
            frame=pd.DataFrame(dict(date=pd.to_datetime(['2026-09-08T16Z','2026-09-08T17Z']),enter_long=[1,1],enter_short=[0,0]))
            intended={'2026-09-08T17:00:00+00:00':{PAIRS[0]:dict(intent='long')}}
            output=mask_signals(frame.copy(),intended,PAIRS[0],('enter_long','enter_short'))
            self.assertEqual(output.enter_long.tolist(),[1,0])
            intended['2026-09-08T17:00:00+00:00'][PAIRS[0]]['intent']='short'
            with self.assertRaisesRegex(ValueError,'natural native signal'):
                mask_signals(frame,intended,PAIRS[0],('enter_long','enter_short'))

        def test_one_native_call_first_slot_fee_funding_and_receipt_drift(self):
            with tempfile.TemporaryDirectory(prefix='perp-observed-native-') as tmp:
                root=Path(tmp);source=root/'source';source.mkdir();snap=fixture(source)
                frames,marks,events,metadata,factors,intents,coverage=decode(snap)
                self.assertEqual(coverage['complete_two_pair_hours'],6)
                self.assertEqual(coverage['scheduled_hours'],7)
                self.assertEqual(len(coverage['omitted']),1)
                self.assertEqual(intents['2026-09-08T19:00:00+00:00'],{})
                start=pd.Timestamp(snap['start']);end=pd.Timestamp(snap['end'])
                for pair in PAIRS:
                    event=pd.Timestamp('2026-09-08T20:00:00.005Z')
                    mark=float(marks[pair].loc[marks[pair].date==event.floor('h'),'close'].iloc[0])
                    events[pair]=pd.concat([events[pair],pd.DataFrame([dict(date=event,open_fund=-.0002,open_mark=mark)])],ignore_index=True).sort_values('date')
                result,archives=run_native_acceptance(root/'native',frames,events,metadata,factors,intents,start-pd.Timedelta(hours=3),end)
                audit,_=audit_native(result,marks,events,start,end)
                self.assertEqual(audit['accounting_reconciliation'],'PASS')
                self.assertEqual(len(result['trades']),2)
                self.assertGreater(audit['funding_usdt'],0.)
                self.assertGreater(audit['taker_fee_usdt'],0.)
                self.assertEqual({t['pair'] for t in result['trades']},set(PAIRS))
                for trade in result['trades']:
                    self.assertEqual(pd.to_datetime(trade['open_timestamp'],unit='ms',utc=True),start)
                    self.assertEqual(trade['leverage'],1.)
                    self.assertFalse(trade['is_short'])
                    self.assertEqual(trade['exit_reason'],'force_exit')
                    self.assertEqual(pd.to_datetime(trade['close_timestamp'],unit='ms',utc=True),end-pd.Timedelta(hours=1))
                self.assertTrue(archives)
                first=next(iter(snap['source_files']));Path(first).write_text('tampered')
                with self.assertRaisesRegex(ValueError,'frozen source/intent changed'):decode(snap)

    unittest.main()
