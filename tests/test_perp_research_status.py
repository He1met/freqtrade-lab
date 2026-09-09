from datetime import timedelta
import json
from pathlib import Path
import importlib.util
import pytest
from test_perp_dispatch import env,confirmation,maintenance,NOW,BP,DP,d,s

SPEC=importlib.util.spec_from_file_location('research_status',Path(__file__).parents[1]/'scripts/perp_research_status.py')
status=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(status)


def unchanged(root):return {str(p):p.read_bytes() for p in root.parent.rglob('*') if p.is_file()}


def test_long_confirmation_wait_is_not_whole_system_blocked(env):
    root,task,*_=env;d.enqueue(root,BP,DP,confirmation(),NOW);maintenance(env)
    before=unchanged(root);result=status.build(root,BP,DP,now=NOW)
    assert result['actual_compute']['status']=='IDLE'
    assert result['confirmation']['reason']=='WAIT_FORWARD' and result['confirmation']['blocks_entire_system'] is False
    assert result['exploration']['status']=='NONE' and result['exploration']['reason']=='WAITING_FOR_REPORT_SUCCESSOR_REVIEW'
    assert result['observer']['status']=='ACTIVATED' and result['market_values_exposed'] is False
    assert unchanged(root)==before
    review_path=root.parent/'next-review.json'
    review=dict(status='RESEARCH_PREPARATION_REQUIRED',reason='Review completed; the fixed successor executor still needs preparation.')
    review_path.write_bytes(s.canonical(review));before=unchanged(root)
    result=status.build(root,BP,DP,next_review_path=review_path,now=NOW)
    assert result['exploration']['status']=='NONE'
    assert result['exploration']['reason']==review['status']
    assert result['exploration']['explanation']==review['reason']
    assert result['exploration']['successor_review']['status']==review['status']
    assert result['execution_performed'] is False and unchanged(root)==before


def test_queued_research_ready_then_maintenance_wait_without_claim(env):
    root,task,*_=env;d.enqueue(root,BP,DP,confirmation(),NOW);d.enqueue(root,BP,DP,task,NOW);maintenance(env)
    before=unchanged(root)
    assert status.build(root,BP,DP,now=NOW)['exploration']['reason']=='READY_FOR_CLAIM'
    result=status.build(root,BP,DP,now=NOW.replace(minute=50))
    assert result['exploration']['reason']=='WAIT_MAINTENANCE'
    assert result['exploration']['next_maintenance_at']=='2026-09-09T01:10:00+00:00'
    assert unchanged(root)==before


@pytest.mark.parametrize('writer_status',['RUNNING','UNKNOWN_INTERRUPTED'])
def test_actual_writer_and_confirmation_priority_are_separate(env,writer_status):
    root,task,*_=env;d.enqueue(root,BP,DP,confirmation(),NOW);d.enqueue(root,BP,DP,task,NOW)
    with s.locked(root,BP) as (_,_,state):state['tasks'][0].update(status=writer_status,started_at=s.stamp(NOW))
    before=unchanged(root);result=status.build(root,BP,DP,now=NOW)
    assert result['actual_compute']['status']==writer_status and result['exploration']['reason']=='WAIT_WRITER'
    assert unchanged(root)==before
    with s.locked(root,BP) as (_,_,state):state['tasks'][0].update(status='WAITING_DATA');state['tasks'][0].pop('started_at')
    due=s.utc(confirmation()['fixed_input_window']['end_exclusive'])-timedelta(minutes=10)
    assert status.build(root,BP,DP,now=due)['exploration']['reason']=='WAIT_CONFIRMATION_PRIORITY'


def test_input_drift_is_visible_and_does_not_mutate_state(env):
    root,task,market,*_=env;d.enqueue(root,BP,DP,task,NOW);market.write_text('changed source')
    before=unchanged(root);result=status.build(root,BP,DP,now=NOW)
    assert result['exploration']['reason']=='BLOCKED_INPUT_OR_CODE_INTEGRITY'
    assert unchanged(root)==before


def test_missing_due_maintenance_can_be_serviced_now(env):
    root,task,*_=env;d.enqueue(root,BP,DP,task,NOW)
    result=status.build(root,BP,DP,now=NOW)
    assert result['exploration']['reason']=='WAIT_REQUIRED_CAPTURE_OR_INTENT'
    assert result['exploration']['earliest_recheck_at']==s.stamp(NOW)
