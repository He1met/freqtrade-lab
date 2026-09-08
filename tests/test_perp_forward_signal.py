"""No market execution: public-shape synthetic vintages and original feature functions."""
from pathlib import Path
import subprocess

PYTHON=Path('/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue-43-profile-driven-v1/venv/bin/python')


def test_forward_observer_contract():
    run=subprocess.run([str(PYTHON),str(Path(__file__).resolve())],capture_output=True,text=True,timeout=60)
    assert run.returncode==0,run.stdout+'\n'+run.stderr


if __name__=='__main__':
    import sys,json,tempfile,math,unittest,fcntl
    from datetime import datetime,timedelta,timezone
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
    from lab import perp_forward_signal as s
    from lab.perp_baseline_runner import native_environment
    native_environment()
    NOW=datetime(2026,9,8,16,30,tzinfo=timezone.utc)
    SOURCE=NOW.replace(hour=15,minute=0)

    class ObserverTests(unittest.TestCase):
        def setUp(self):
            self.tmp=tempfile.TemporaryDirectory(prefix='perp-forward-test-');self.base=Path(self.tmp.name)
            self.seed=self.base/'seed';self.seed.mkdir();self.incremental=self.base/'incremental';self.incremental.mkdir()
            self.root=self.base/'signals';self.policy=s.REPO/'docs/protocols/perp-autonomous-policy-v2.json'
            self.protocol=s.REPO/'docs/protocols/perp-independent-confirmation-v2.json'
            self.registration=s.REPO/'docs/research/perp-carry-nonpaying-registration-v1.json'
            self.binding=self.base/'binding.json';s.atomic(self.binding,dict(registration_sha256=s.sha(self.registration.read_bytes()),
                confirmation_protocol_sha256=s.sha(self.protocol.read_bytes()),code_bindings={p:s.sha((s.REPO/p).read_bytes()) for p in s.OBSERVER_FILES}))
            receipt=dict(exchange='binance',window_start=s.iso(SOURCE-168*s.HOUR),window_end_exclusive=s.iso(SOURCE+s.HOUR),datasets={})
            for pair in s.PAIRS:
                for kind in ('ohlcv','premium','funding'):
                    dates=[SOURCE-168*s.HOUR+i*s.HOUR for i in range(169)] if kind=='ohlcv' else [SOURCE] if kind=='premium' else [SOURCE-7*s.HOUR]
                    rows=[]
                    for i,event in enumerate(dates):
                        declared=event+s.HOUR+(timedelta(seconds=60) if kind!='funding' else timedelta())
                        fetched=NOW-timedelta(minutes=10);price=100+i*.1+math.sin(i/3)*.01
                        row=dict(event_time=s.iso(event),available_at=s.iso(max(declared,fetched)),historical_available_at_assumption=s.iso(declared),
                            fetched_at=s.iso(fetched),quality='FIRST_OBSERVATION_FLOOR',source_version='SYNTHETIC_PUBLIC_SHAPE',vintage=s.iso(fetched))
                        if kind=='funding':row.update(rate='-0.0001',mark_price='100')
                        else:row.update(open=str(price),high=str(price+.001),low=str(price-.001),close=str(price if kind=='ohlcv' else .01),volume='1000')
                        rows.append(row)
                    name=pair.split('/')[0]+'USDT-'+kind;path=self.seed/(name+'.jsonl');path.write_bytes(b''.join(s.encoded(r) for r in rows))
                    receipt['datasets'][name]=dict(path=path.name,sha256=s.sha(path.read_bytes()),rows=len(rows))
            s.atomic(self.seed/'receipt.json',receipt)
        def tearDown(self):self.tmp.cleanup()
        def run_observer(self,command='tick',when=NOW,**kwargs):
            return s.run(self.root,self.registration,self.protocol,self.binding,self.seed,self.incremental,command,
                         clock_fn=lambda:when,runtime_policy_path=self.policy,**kwargs)
        def latest(self):return s.read(self.root/'hours/20260908T1700Z.receipt.json')
        def test_late_fetch_before_planned_entry_is_causal_and_idempotent(self):
            check=self.run_observer('check');self.assertEqual(check['pairs'][s.PAIRS[0]]['intent'],'long')
            self.assertFalse(self.root.exists())
            self.run_observer();first=(self.root/'hours/20260908T1700Z.intent.json').read_bytes()
            receipt=self.latest();self.assertEqual(receipt['phase'],'PRE_CONFIRMATION')
            self.assertTrue(all(r['status']=='TIMELY_SIGNAL' for r in receipt['pairs'].values()))
            self.run_observer(when=NOW+timedelta(minutes=5));self.assertEqual(first,(self.root/'hours/20260908T1700Z.intent.json').read_bytes())
        def test_future_fetch_and_missing_premium_are_not_no_trade(self):
            pools,_=s.observed_rows(self.seed,self.incremental,SOURCE,NOW-timedelta(minutes=20))
            self.assertEqual(s.intent(s.PAIRS[0],pools,SOURCE)['status'],'MISSING_INPUT')
            pools,_=s.observed_rows(self.seed,self.incremental,SOURCE,NOW);pools[s.PAIRS[0],'premium'].clear()
            self.assertEqual(s.intent(s.PAIRS[0],pools,SOURCE)['status'],'MISSING_INPUT')
        def test_exact_funding_sign_premium_sign_unused_and_no_lookahead(self):
            pools,_=s.observed_rows(self.seed,self.incremental,SOURCE,NOW)
            a=s.intent(s.PAIRS[0],pools,SOURCE);self.assertEqual(a['intent'],'long')
            event=next(iter(pools[s.PAIRS[0],'funding'].values()));event['rate']='0.01'
            self.assertEqual(s.intent(s.PAIRS[0],pools,SOURCE)['intent'],'NO_TRADE')
            event['rate']='-0.0001';event['declared']=SOURCE+2*s.HOUR
            self.assertEqual(s.intent(s.PAIRS[0],pools,SOURCE)['status'],'MISSING_INPUT')
        def test_publication_at_entry_is_late(self):
            # Initial computation before entry, durable publication observed at boundary.
            calls=iter([NOW,NOW,NOW.replace(hour=17,minute=0)])
            result=s.run(self.root,self.registration,self.protocol,self.binding,self.seed,self.incremental,
                clock_fn=lambda:next(calls),runtime_policy_path=self.policy)
            self.assertEqual(result['orders'],0)
            self.assertTrue(all(r['status']=='LATE' for r in self.latest()['pairs'].values()))
        def test_skipped_hour_is_late_without_replay(self):
            self.run_observer();self.run_observer(when=NOW+3*s.HOUR)
            receipt=s.read(self.root/'hours/20260908T1800Z.receipt.json')
            self.assertTrue(all(r['status']=='LATE' and r['intent'] is None for r in receipt['pairs'].values()))
        def test_code_drift_and_signal_tamper_fail_closed(self):
            original=s.read(self.binding);wrong=dict(original);wrong['code_bindings']=dict(original['code_bindings']);wrong['code_bindings'][s.OBSERVER_FILES[0]]='0'*64
            s.atomic(self.binding,wrong)
            with self.assertRaisesRegex(ValueError,'code SHA drift'):self.run_observer()
            self.assertFalse(self.root.exists());s.atomic(self.binding,original);self.run_observer()
            (self.root/'hours/20260908T1700Z.intent.json').write_text('{}')
            with self.assertRaisesRegex(ValueError,'signal evidence drift'):self.run_observer()
        def test_activation_requires_native_acceptance_and_single_writer(self):
            self.run_observer()
            with self.assertRaisesRegex(ValueError,'native acceptance'):self.run_observer('activate')
            with (self.root/'writer.lock').open('a') as lock:
                fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                with self.assertRaises(BlockingIOError):self.run_observer()
            self.assertFalse(s.read(self.root/'state.json')['active'])

    unittest.main()
