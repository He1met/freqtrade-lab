import fcntl
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import subprocess
import sys

import pytest
from lab import perp_schedule as s

UTC=timezone.utc
NOW=datetime(2026,9,8,12,10,tzinfo=UTC)


@pytest.fixture
def env(tmp_path):
    policy=dict(product='USDT_LINEAR_PERPETUAL',market_workers=1,display_timezone='Asia/Shanghai',
                daily_report_local='20:00',weekly_review_local='SUN 17:00',health_minutes=30,
                market_available_delay_minutes=10,daily_rounds=1,daily_variants=4,
                weekly_rounds=7,weekly_variants=28,native_round_budget_seconds=1800)
    path=tmp_path/'policy.json'; path.write_bytes(s.canonical(policy))
    return tmp_path/'runtime',path


def task(env, identity='round-1', **updates):
    value=dict(id=identity,kind='research',mechanism='continuation',code_sha256='a'*64,
               data_sha256='b'*64,policy_sha256=s.digest(env[1].read_bytes()),
               hypothesis='方向持续性是否增加成本后收益',variants=4,max_seconds=100)
    value.update(updates)
    return value


def terminal(tmp_path, status='COMPLETED', **updates):
    summary=tmp_path/'result.json'; report=tmp_path/'result.md'
    binding=dict(task_id='round-1',code_sha256='a'*64,data_sha256='b'*64,
                 policy_sha256=s.digest((tmp_path/'policy.json').read_bytes()))
    summary.write_bytes(s.canonical(dict(status=status,conclusion='开发结果，独立资格未知',task_binding=binding,**updates)))
    report.write_text('# 真实结果\n\n仅检查交付绑定；指标未知。\n')
    return summary,report


def test_read_only_and_bad_paths(env):
    root,policy=env
    assert s.read_status(root,policy)['status']=='NOT_INITIALIZED'
    assert not root.exists()
    with pytest.raises(FileNotFoundError): s.tick(root,policy.parent/'missing.json',NOW)
    assert not root.exists()


def test_hour_close_delay_daily_and_weekly_timezone(env):
    root,policy=env
    early=NOW.replace(hour=11,minute=9)
    first=s.tick(root,policy,early)
    assert first['due']['hourly_data']['key']=='hourly_data:20260908T1000Z'
    assert 'daily-20260908' not in first['reports']
    second=s.tick(root,policy,NOW)
    assert second['due']['hourly_data']['key']=='hourly_data:20260908T1200Z'
    assert 'daily-20260908' in second['reports']
    sun=datetime(2026,9,13,9,tzinfo=UTC)
    assert 'weekly-2026-W37' in s.tick(root,policy,sun)['reports']


def test_same_tick_idempotence_and_late_checkpoint(env):
    root,policy=env
    s.tick(root,policy,NOW); first=(root/'state.json').read_bytes()
    s.tick(root,policy,NOW)
    assert (root/'state.json').read_bytes()==first
    state=s.tick(root,policy,NOW+timedelta(days=1))
    assert state['due']['hourly_data']['late_recovery'] is True
    assert state['due']['hourly_data']['status']=='DUE'
    assert not state['tasks']  # Calendar does not invent an executed experiment.


def test_lock_conflict_and_policy_drift(env):
    root,policy=env; root.mkdir()
    with (root/'writer.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        with pytest.raises(BlockingIOError): s.tick(root,policy,NOW)
    s.tick(root,policy,NOW)
    policy.write_text(policy.read_text()+'\n')
    with pytest.raises(ValueError,match='policy SHA drift'): s.tick(root,policy,NOW)


def test_waiting_data_and_duplicate_task(env):
    root,policy=env
    s.enqueue(root,policy,task(env,status='WAITING_DATA'),NOW)
    with pytest.raises(ValueError,match='not claimable'): s.claim(root,policy,'round-1',NOW)
    with pytest.raises(ValueError,match='already registered'):
        s.enqueue(root,policy,task(env,'renamed',hypothesis='改名不成为新实验'),NOW)
    s.ready(root,policy,'round-1'); s.claim(root,policy,'round-1',NOW)
    with pytest.raises(ValueError,match='not claimable'): s.claim(root,policy,'round-1',NOW)


def test_single_priority_and_budget_stays_spent(env,tmp_path):
    root,policy=env
    s.enqueue(root,policy,task(env),NOW)
    next_task=task(env,'round-2',data_sha256='c'*64)
    with pytest.raises(ValueError,match='one prioritized'): s.enqueue(root,policy,next_task,NOW)
    s.claim(root,policy,'round-1',NOW)
    s.finish(root,policy,'round-1',*terminal(tmp_path,'BLOCKED_DATA'),now=NOW)
    s.enqueue(root,policy,next_task,NOW)
    with pytest.raises(ValueError,match='daily budget'): s.claim(root,policy,'round-2',NOW)
    assert s.claim(root,policy,'round-2',NOW+timedelta(days=1))['status']=='RUNNING'


def test_stale_writer_blocks_until_reconciled(env,tmp_path):
    root,policy=env
    s.enqueue(root,policy,task(env),NOW); s.claim(root,policy,'round-1',NOW)
    state=s.tick(root,policy,NOW+timedelta(seconds=101))
    assert state['tasks'][0]['status']=='UNKNOWN_INTERRUPTED'
    with pytest.raises(ValueError,match='one prioritized'):
        s.enqueue(root,policy,task(env,'round-2',data_sha256='c'*64),NOW)
    with pytest.raises(ValueError,match='stopped-process evidence'):
        s.finish(root,policy,'round-1',*terminal(tmp_path,'BLOCKED_RUNTIME'),now=NOW)
    s.finish(root,policy,'round-1',*terminal(tmp_path,'BLOCKED_RUNTIME',verified_process_stopped=True),now=NOW)
    with pytest.raises(ValueError,match='already registered'): s.enqueue(root,policy,task(env,'renamed'),NOW)


def test_finish_requires_reports_and_marks_exact_due(env,tmp_path):
    root,policy=env
    state=s.tick(root,policy,NOW)
    key=state['due']['hourly_data']['key']
    s.enqueue(root,policy,task(env,kind='data',variants=0,due_keys={'hourly_data':key}),NOW)
    s.claim(root,policy,'round-1',NOW)
    with pytest.raises(FileNotFoundError): s.finish(root,policy,'round-1',tmp_path/'missing',tmp_path/'missing')
    done=s.finish(root,policy,'round-1',*terminal(tmp_path),now=NOW)
    assert Path(done['report']).read_text().startswith('# 真实结果')
    assert s.read_status(root,policy)['due']['hourly_data']['status']=='COMPLETED'


def test_variant_limit_clock_reversal_and_no_cli_fake_time(env):
    root,policy=env
    with pytest.raises(ValueError,match='variant budget'): s.enqueue(root,policy,task(env,variants=5),NOW)
    s.tick(root,policy,NOW)
    with pytest.raises(ValueError,match='backwards'): s.tick(root,policy,NOW-timedelta(seconds=1))
    script=Path(__file__).parents[1]/'scripts/perp_schedule.py'
    run=subprocess.run([sys.executable,str(script),'--root',str(root),'--policy',str(policy),'tick','--now','2020-01-01'],capture_output=True)
    assert run.returncode != 0 and b'unrecognized arguments' in run.stderr


def test_weekly_budget_and_runtime_cannot_live_in_git(env,tmp_path):
    root,policy=env
    config=json.loads(policy.read_bytes());config['weekly_rounds']=1
    policy.write_bytes(s.canonical(config))
    s.enqueue(root,policy,task(env),NOW);s.claim(root,policy,'round-1',NOW)
    s.finish(root,policy,'round-1',*terminal(tmp_path),now=NOW)
    s.enqueue(root,policy,task(env,'round-2',data_sha256='c'*64),NOW)
    with pytest.raises(ValueError,match='weekly budget'):
        s.claim(root,policy,'round-2',NOW+timedelta(days=1))
    git=tmp_path/'repo';git.mkdir();(git/'.git').mkdir()
    with pytest.raises(ValueError,match='outside Git'): s.tick(git/'runtime',policy,NOW)
    assert not (git/'runtime').exists()


def test_interrupted_state_commit_reuses_exact_reports(env,tmp_path,monkeypatch):
    root,policy=env
    s.enqueue(root,policy,task(env),NOW);s.claim(root,policy,'round-1',NOW)
    summary,report=terminal(tmp_path)
    original=s.atomic
    def interrupted(path,raw):
        if Path(path).name=='state.json': raise OSError('injected commit interruption')
        return original(path,raw)
    monkeypatch.setattr(s,'atomic',interrupted)
    with pytest.raises(OSError,match='commit interruption'):
        s.finish(root,policy,'round-1',summary,report,now=NOW)
    assert s.read_status(root,policy)['tasks'][0]['status']=='RUNNING'
    assert (root/'reports'/'round-1.md').read_bytes()==report.read_bytes()
    monkeypatch.setattr(s,'atomic',original)
    assert s.finish(root,policy,'round-1',summary,report,now=NOW)['status']=='COMPLETED'


def test_wrong_experiment_summary_cannot_finish(env,tmp_path):
    root,policy=env
    s.enqueue(root,policy,task(env),NOW);s.claim(root,policy,'round-1',NOW)
    summary,report=terminal(tmp_path)
    payload=json.loads(summary.read_bytes());payload['task_binding']['data_sha256']='c'*64
    summary.write_bytes(s.canonical(payload))
    with pytest.raises(ValueError,match='binding mismatch'):
        s.finish(root,policy,'round-1',summary,report,now=NOW)
    assert s.read_status(root,policy)['tasks'][0]['status']=='RUNNING'
    assert not (root/'reports').exists()
