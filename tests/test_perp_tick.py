import importlib.util
import json
from pathlib import Path

from lab import perp_schedule as schedule

spec=importlib.util.spec_from_file_location('perp_tick',Path(__file__).parents[1]/'scripts/perp_tick.py')
pulse=importlib.util.module_from_spec(spec); spec.loader.exec_module(pulse)
POLICY=Path(__file__).parents[1]/'docs/protocols/perp-autonomous-policy-v1.json'


def test_active_research_prevents_data_calls(tmp_path):
    root=tmp_path/'runtime'
    policy_sha=schedule.load_policy(POLICY)[1]
    task=dict(id='first',kind='research',mechanism='breakout',code_sha256='a'*64,data_sha256='b'*64,
              policy_sha256=policy_sha,hypothesis='test',variants=4,max_seconds=1800)
    schedule.enqueue(root/'scheduler',POLICY,task)
    schedule.claim(root/'scheduler',POLICY,'first')
    def forbidden(_): raise AssertionError('data collector called while research writer active')
    result=pulse.run(root,POLICY,updater=forbidden)
    assert result['data']['status']=='WAIT_RESEARCH_WRITER'
    assert result['native_calls']==0


def test_real_receipt_status_and_no_signal_claim(tmp_path):
    root=tmp_path/'runtime'
    result=pulse.run(root,POLICY,updater=lambda _:dict(status='DATA_CAPTURED',requests=15,root='/captured',core_complete=True))
    assert result['data']['requests']==15
    assert result['due']['hourly_data']['status']=='DATA_CAPTURE_RECEIPT'
    state=schedule.read_status(root/'scheduler',POLICY)
    assert state['due']['hourly_data']['status']=='DATA_CAPTURE_RECEIPT'
    assert state['data_checkpoint']['result']['core_complete'] is True
    assert len(list((root/'heartbeat-receipts').glob('*.json')))==1
    assert result['native_calls']==0


def test_partial_or_unknown_capture_never_marks_data_ready(tmp_path):
    root=tmp_path/'runtime'
    result=pulse.run(root,POLICY,updater=lambda _:dict(status='NO_OP_ALREADY_CAPTURED',requests=0,root='/partial'))
    state=schedule.read_status(root/'scheduler',POLICY)
    assert state['due']['hourly_data']['status']=='DUE'
    assert result['freshness']['status']=='UNKNOWN'


def test_acquisition_holds_same_lock_as_research_claim(tmp_path):
    root=tmp_path/'runtime'
    task=dict(id='pending',kind='research',mechanism='breakout',code_sha256='a'*64,data_sha256='b'*64,
              policy_sha256=schedule.load_policy(POLICY)[1],hypothesis='test',variants=4,max_seconds=1800)
    schedule.enqueue(root/'scheduler',POLICY,task)
    def during_acquisition(_):
        import pytest
        with pytest.raises(BlockingIOError): schedule.claim(root/'scheduler',POLICY,'pending')
        return dict(status='DATA_CAPTURED',requests=0,root='/synthetic',core_complete=True)
    pulse.run(root,POLICY,updater=during_acquisition)
    assert schedule.read_status(root/'scheduler',POLICY)['tasks'][0]['status']=='QUEUED'
    assert schedule.claim(root/'scheduler',POLICY,'pending')['status']=='RUNNING'
