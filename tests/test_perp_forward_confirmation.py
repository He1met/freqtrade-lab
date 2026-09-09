"""Synthetic endpoint, immutable evidence and one-call guards; no native calls."""
import copy
from datetime import datetime,timedelta,timezone
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO=Path(__file__).resolve().parents[1];sys.path.insert(0,str(REPO))
from lab.perp_baseline_runner import native_environment
native_environment()  # Import/version setup only. Never instantiate Backtesting.
from lab import perp_forward_confirmation as c
spec=importlib.util.spec_from_file_location('confirmation_cli',REPO/'scripts/perp_forward_confirmation.py')
cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)
PROTOCOL=json.loads((REPO/'docs/protocols/perp-independent-confirmation-v2.json').read_bytes())
START=c.dt(PROTOCOL['window']['start_inclusive']);END=c.dt(PROTOCOL['window']['end_exclusive'])


class ConfirmationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='perp-confirmation-synthetic-');self.root=Path(self.temp.name).resolve()
    def tearDown(self):self.temp.cleanup()

    def snapshot(self):
        signal=self.root/'signal';signal.mkdir();(signal/'hours').mkdir()
        identity=dict(candidate_id='synthetic');state=dict(identity=identity,active=True,activated_at=c.iso(START-timedelta(days=1)),records={})
        cli.atomic(signal/'state.json',state)
        return dict(identity=identity,signal_root=str(signal),activation_at=state['activated_at'],
            source_files={str(signal/'state.json'):c.sha(signal/'state.json')},
            records=[dict(planned_entry=c.iso(START+timedelta(hours=i)),missing=True) for i in range(2160)])

    def first_record(self,snap):
        signal=Path(snap['signal_root']);state=cli.read(signal/'state.json');key=START.strftime('%Y%m%dT%H00Z')
        raw=signal/'hours'/(key+'.intent.json');receipt=signal/'hours'/(key+'.receipt.json')
        intent=dict(identity=snap['identity'],planned_entry=c.iso(START),fixture='synthetic only')
        cli.atomic(raw,intent);rec=dict(identity=snap['identity'],phase='CONFIRMATION',intent_sha256=c.sha(raw))
        cli.atomic(receipt,rec);state['records'][key]=dict(intent_sha256=c.sha(raw),receipt_sha256=c.sha(receipt));cli.atomic(signal/'state.json',state)
        for path in (signal/'state.json',raw,receipt):snap['source_files'][str(path)]=c.sha(path)
        snap['records'][0]=dict(planned_entry=c.iso(START),intent=intent,receipt=rec)

    def test_real_window_wait_includes_publication_buffer(self):
        self.assertEqual(cli.endpoint(PROTOCOL,END+timedelta(minutes=9,seconds=59))['status'],'WAIT_FORWARD')
        self.assertEqual(cli.endpoint(PROTOCOL,END+timedelta(minutes=10))['status'],'CHECK_INPUT_READINESS')

    def test_window_cannot_be_substituted_with_acceptance_or_shortened_history(self):
        wrong=copy.deepcopy(PROTOCOL);wrong['window']['end_exclusive']=c.iso(END-timedelta(hours=1))
        with self.assertRaisesRegex(ValueError,'unchanged frozen'):cli.endpoint(wrong,END)

    def test_confirmation_reservation_survives_output_and_task_rename(self):
        claim=dict(id='synthetic-one',candidate_budget_key='c'*64,fixed_input_window=dict(start=c.iso(START),end_exclusive=c.iso(END)))
        pre={k:'a'*64 for k in ('code_sha256','data_sha256','policy_sha256')}
        cli.reserve_once(self.root,claim,pre,self.root/'first',END)
        claim['id']='synthetic-renamed'
        with self.assertRaisesRegex(ValueError,'already reserved'):cli.reserve_once(self.root,claim,pre,self.root/'different-output',END)

    def test_missing_slots_are_retained_and_no_trade_cannot_be_invented(self):
        snap=self.snapshot();c.validate_snapshot_records(snap,START,END)
        self.assertEqual(len(snap['records']),2160)
        snap['records'].pop()
        with self.assertRaisesRegex(ValueError,'2160'):c.validate_snapshot_records(snap,START,END)

    def test_inactive_state_cannot_be_relabelled_confirmation(self):
        snap=self.snapshot();path=Path(snap['signal_root'])/'state.json';state=cli.read(path);state['active']=False;cli.atomic(path,state);snap['source_files'][str(path)]=c.sha(path)
        with self.assertRaisesRegex(ValueError,'activation proof'):c.validate_snapshot_records(snap,START,END)

    def test_embedded_intent_must_equal_durable_original(self):
        snap=self.snapshot();self.first_record(snap);c.validate_snapshot_records(snap,START,END)
        snap['records'][0]['intent']['fixture']='fabricated replacement'
        with self.assertRaisesRegex(ValueError,'durable original'):c.validate_snapshot_records(snap,START,END)

    def test_existing_intent_cannot_be_removed_from_confirmation(self):
        snap=self.snapshot();self.first_record(snap);snap['records'][0]=dict(planned_entry=c.iso(START),missing=True)
        with self.assertRaisesRegex(ValueError,'selectively omitted'):c.validate_snapshot_records(snap,START,END)

    def test_absent_funding_query_coverage_never_becomes_zero_funding(self):
        snap=self.snapshot();snap.update(start=c.iso(START),end=c.iso(END),frozen_observed_at=c.iso(END+timedelta(minutes=10)),capture_roots=[])
        with self.assertRaisesRegex(ValueError,'funding query coverage incomplete'):c.decode(snap)

    def test_twenty_one_percent_and_natural_sample_floor_are_separate(self):
        metrics=dict(observed_hourly_mtm_drawdown=.21,common_72h_entry_clusters=12,gross_price_effect_usdt=10,net_usdt=2,conditional_same_fill_stress_net_usdt=-1)
        decision=c.primary_verdict(metrics,dict(timely_fraction=1),PROTOCOL)
        self.assertEqual(decision['verdict'],'CONFIRMATION_POSITIVE_LIMITED');self.assertEqual(decision['risk_classification'],'ABOVE_TARGET_REVIEW')
        self.assertFalse(decision['economic_qualification']);metrics['common_72h_entry_clusters']=11
        self.assertEqual(c.primary_verdict(metrics,dict(timely_fraction=1),PROTOCOL)['verdict'],'UNDERPOWERED')

    def test_tail_no_trade_is_valid_after_frozen_entry_cutoff(self):
        import pandas as pd
        cutoff=c.dt(PROTOCOL['window']['last_new_entry_exclusive'])
        frame=pd.DataFrame(dict(date=pd.to_datetime([cutoff-timedelta(hours=2),cutoff-timedelta(hours=1)],utc=True),enter_long=[1,1],enter_short=[0,0]))
        strategy=object.__new__(c.PerpForwardConfirmation);pair=c.PAIRS[0]
        strategy.acceptance_intents={c.iso(cutoff-timedelta(hours=1)):{pair:dict(intent='long')},c.iso(cutoff):{pair:dict(intent='NO_TRADE')}}
        with patch.object(c.PerpFundingPremiumV1,'populate_entry_trend',return_value=frame):
            result=strategy.populate_entry_trend(frame,dict(pair=pair))
        self.assertEqual(list(result.enter_long),[1,0])

    def test_frozen_block_bootstrap_retains_zero_exposure_blocks_and_initial_fee(self):
        points=[dict(at=c.iso(START+timedelta(hours=i)),equity=1000.) for i in range(2161)]
        result=c.block_interval(points,START,END,PROTOCOL)
        self.assertEqual(result['status'],'COMPUTED_CONDITIONAL_PATH_ONLY');self.assertEqual(result['complete_blocks'],30)
        self.assertEqual((result['lower_return_fraction'],result['upper_return_fraction']),(0.,0.))
        for point in points:point['equity']=999.
        result=c.block_interval(points,START,END,PROTOCOL)
        self.assertLess(result['lower_return_fraction'],0.)
        self.assertEqual(result,c.block_interval(points,START,END,PROTOCOL))

    def test_block_bootstrap_missing_or_nonpositive_equity_stays_unknown(self):
        points=[dict(at=c.iso(START+timedelta(hours=i)),equity=1000.) for i in range(2161)]
        self.assertEqual(c.block_interval(points[:-1],START,END,PROTOCOL)['status'],'UNKNOWN')
        points[100]['equity']=0.
        self.assertIsNone(c.block_interval(points,START,END,PROTOCOL)['lower_return_fraction'])

    def test_output_success_requires_unchanged_final_sources(self):
        paths=[self.root/name for name in ('policy.json','manifest.json','snapshot.json','source.json')]
        for path in paths:path.write_text('synthetic frozen content')
        expected=[c.sha(path) for path in paths]
        args=({}, {str(paths[3]):expected[3]},paths[0],expected[0],paths[1],expected[1],paths[2],expected[2],{})
        cli.verify_final_bindings(*args);paths[3].write_text('changed while native would run')
        with self.assertRaisesRegex(ValueError,'changed during execution'):cli.verify_final_bindings(*args)


if __name__=='__main__':unittest.main()
