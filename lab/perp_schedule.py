"""Small persistent research coordinator; never downloads, trades, or runs models."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from zoneinfo import ZoneInfo

UTC = timezone.utc
OPEN = {'QUEUED', 'WAITING_DATA', 'RUNNING', 'UNKNOWN_INTERRUPTED'}
TERMINAL = {'COMPLETED', 'BLOCKED_DATA', 'BLOCKED_RUNTIME', 'STOPPED', 'UNDERPOWERED'}


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False, indent=2)+'\n').encode()


def stamp(now):
    return now.astimezone(UTC).isoformat()


def atomic(path, raw):
    path = Path(path)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.'+path.name, delete=False) as f:
        f.write(raw); f.flush(); os.fsync(f.fileno()); temporary = f.name
    os.replace(temporary, path)
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def load_policy(path):
    raw = Path(path).read_bytes()
    policy = json.loads(raw)
    if not isinstance(policy, dict) or policy.get('product') != 'USDT_LINEAR_PERPETUAL':
        raise ValueError('invalid perpetual policy')
    if policy.get('market_workers') != 1 or policy.get('display_timezone') != 'Asia/Shanghai':
        raise ValueError('single worker and explicit Shanghai schedule required')
    if policy.get('daily_report_local') != '20:00' or policy.get('weekly_review_local') != 'SUN 17:00':
        raise ValueError('Tokyo to Shanghai schedule drift')
    return policy, digest(raw)


@contextmanager
def locked(root, policy_path):
    policy, policy_sha = load_policy(policy_path)  # Bad policy must not create runtime paths.
    root = Path(root)
    if not root.is_absolute():
        raise ValueError('absolute runtime root required')
    root = root.resolve()
    if any((parent/'.git').exists() for parent in [root,*root.parents]):
        raise ValueError('runtime artifacts must stay outside Git')
    root.mkdir(parents=True, exist_ok=True)
    with (root/'writer.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        path = root/'state.json'
        state = json.loads(path.read_bytes()) if path.exists() else dict(
            version=1, policy_sha256=policy_sha, tasks=[], due={}, reports={}, last_tick=None)
        if state['policy_sha256'] != policy_sha:
            raise ValueError('policy SHA drift; migrate explicitly to a versioned root')
        try:
            yield root, policy, state
            atomic(path, canonical(state))
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def read_status(root, policy_path):
    _, sha = load_policy(policy_path)
    path = Path(root)/'state.json'
    if not path.exists():
        return dict(status='NOT_INITIALIZED', policy_sha256=sha)
    state = json.loads(path.read_bytes())
    if state['policy_sha256'] != sha:
        raise ValueError('policy SHA drift')
    return state


def report(root, state, key, title, now, extra=''):
    path = root/'reports'; path.mkdir(exist_ok=True)
    summary = dict(key=key, observed_at=stamp(now), tasks=state['tasks'], due=state['due'],
                   conclusion=extra or '这里只核对持久状态；未执行的采集或研究保持待办，收益未知。')
    body = '# '+title+'\n\n核验时间：'+stamp(now)+'\n\n'+summary['conclusion']+'\n\n'
    body += '\n'.join('- '+t['id']+'：'+t['status']+'；'+t['hypothesis'] for t in state['tasks'])
    body += '\n\n定时到期不是执行证据；经济结果以各任务绑定的真实报告和摘要为准。\n'
    atomic(path/(key+'.json'), canonical(summary)); atomic(path/(key+'.md'), body.encode())
    state['reports'][key] = dict(markdown=str(path/(key+'.md')), summary=str(path/(key+'.json')))


def tick(root, policy_path, now=None):
    now = now or datetime.now(UTC)
    with locked(root, policy_path) as (root, policy, state):
        previous = state['last_tick']
        if previous and now < datetime.fromisoformat(previous):
            raise ValueError('clock moved backwards')
        for task in state['tasks']:
            if task['status'] == 'RUNNING' and now >= datetime.fromisoformat(task['started_at'])+timedelta(seconds=task['max_seconds']):
                task['status'] = 'UNKNOWN_INTERRUPTED'; task['finished_at'] = stamp(now)
                report(root, state, 'interrupted-'+task['id'], '研究执行超时检查点', now,
                       '任务已超出有界运行时间，实际结果 UNKNOWN；保留预算与指纹，不自动重跑。')
        local = now.astimezone(ZoneInfo(policy['display_timezone']))
        health = int(now.timestamp())//(policy['health_minutes']*60)
        closed = (now-timedelta(minutes=policy['market_available_delay_minutes'])).replace(minute=0, second=0, microsecond=0)
        keys = [('health', str(health)), ('hourly_data', closed.strftime('%Y%m%dT%H00Z')),
                ('daily_discovery', now.strftime('%Y%m%d'))]
        for kind, key in keys:
            identity = kind+':'+key
            if kind == 'health':
                state['due'][kind] = dict(key=identity, status='CHECKPOINT_ONLY', observed_at=stamp(now))
            elif state['due'].get(kind, {}).get('key') != identity:
                state['due'][kind] = dict(key=identity, status='DUE', observed_at=stamp(now),
                                         late_recovery=bool(previous and (now-datetime.fromisoformat(previous)).total_seconds()>3600))
        daily = local.replace(hour=20, minute=0, second=0, microsecond=0)
        if daily > local: daily -= timedelta(days=1)
        weekly = (local-timedelta(days=(local.weekday()-6)%7)).replace(hour=17,minute=0,second=0,microsecond=0)
        if weekly > local: weekly -= timedelta(days=7)
        periods = [('daily', daily.strftime('%Y%m%d')), ('weekly', weekly.strftime('%G-W%V'))]
        for kind, key in periods:
            key = kind+'-'+key
            if key not in state['reports']:
                report(root, state, key, '日终研究检查点' if kind=='daily' else '每周研究与调度复盘', now)
        state['last_tick'] = stamp(now)
        return state


def task_by_id(state, task_id):
    return next(t for t in state['tasks'] if t['id'] == task_id)


def enqueue(root, policy_path, task, now=None):
    now = now or datetime.now(UTC)
    with locked(root, policy_path) as (_, policy, state):
        required = {'id','kind','mechanism','code_sha256','data_sha256','policy_sha256','hypothesis','variants','max_seconds'}
        if not required <= task.keys() or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', task['id']):
            raise ValueError('task schema/id')
        if task['kind'] not in {'data','research'} or task.get('status','QUEUED') not in {'QUEUED','WAITING_DATA'}:
            raise ValueError('task kind/status')
        if any(not re.fullmatch(r'[0-9a-f]{64}',task[k]) for k in ['code_sha256','data_sha256','policy_sha256']):
            raise ValueError('task SHA binding required')
        if task['policy_sha256'] != state['policy_sha256'] or not task['hypothesis']:
            raise ValueError('task policy/hypothesis')
        if type(task['variants']) is not int or not 0 <= task['variants'] <= policy['daily_variants']:
            raise ValueError('variant budget')
        if task['kind']=='research' and task['variants'] < 1:
            raise ValueError('research requires variants')
        if task['kind']=='data' and task['variants'] != 0:
            raise ValueError('data tasks cannot register economic variants')
        if type(task['max_seconds']) is not int or not 1 <= task['max_seconds'] <= policy['native_round_budget_seconds']:
            raise ValueError('runtime budget')
        bound = {k:task[k] for k in ['kind','mechanism','code_sha256','data_sha256','policy_sha256','variants']}
        fingerprint = digest(canonical(bound))
        if any(t['fingerprint']==fingerprint or t['id']==task['id'] for t in state['tasks']):
            raise ValueError('task already registered; fingerprint remains consumed')
        if any(t['status'] in OPEN for t in state['tasks']):
            raise ValueError('exactly one prioritized outstanding task permitted')
        task = dict(task, fingerprint=fingerprint, status=task.get('status','QUEUED'), queued_at=stamp(now))
        state['tasks'].append(task)
        return task


def claim(root, policy_path, task_id, now=None):
    now = now or datetime.now(UTC)
    with locked(root, policy_path) as (_, policy, state):
        task = task_by_id(state, task_id)
        if task['status'] != 'QUEUED' or any(t['status'] in {'RUNNING','UNKNOWN_INTERRUPTED'} for t in state['tasks']):
            raise ValueError('task not claimable or writer active')
        if task.get('budget_not_before') and now < datetime.fromisoformat(task['budget_not_before'].replace('Z','+00:00')):
            raise ValueError('task budget not-before time has not arrived')
        started = [t for t in state['tasks'] if t.get('started_at') and t['kind']=='research']
        if task['kind']=='research':
            for period, fmt in [('daily','%Y-%m-%d'), ('weekly','%G-W%V')]:
                used = [t for t in started if datetime.fromisoformat(t['started_at']).strftime(fmt)==now.strftime(fmt)]
                if len(used)+1>policy[period+'_rounds'] or sum(t['variants'] for t in used)+task['variants']>policy[period+'_variants']:
                    raise ValueError(period+' budget exhausted')
        task.update(status='RUNNING', started_at=stamp(now))
        return task


def ready(root, policy_path, task_id):
    with locked(root, policy_path) as (_, _, state):
        task = task_by_id(state, task_id)
        if task['status'] != 'WAITING_DATA':
            raise ValueError('task is not waiting for data')
        task['status'] = 'QUEUED'
        return task


def finish(root, policy_path, task_id, summary_path, report_path, now=None):
    now = now or datetime.now(UTC)
    summary_raw, report_raw = Path(summary_path).read_bytes(), Path(report_path).read_bytes()
    summary = json.loads(summary_raw)
    if summary.get('status') not in TERMINAL or not summary.get('conclusion') or not report_raw.strip():
        raise ValueError('terminal summary and real report required')
    with locked(root, policy_path) as (root, _, state):
        task = task_by_id(state, task_id)
        expected = dict(task_id=task_id, **{k:task[k] for k in ['code_sha256','data_sha256','policy_sha256']})
        if summary.get('task_binding') != expected:
            raise ValueError('summary task/code/data/policy binding mismatch')
        if task['status']=='UNKNOWN_INTERRUPTED' and summary.get('verified_process_stopped') is not True:
            raise ValueError('uncertain writer requires explicit stopped-process evidence')
        if task['status'] not in {'RUNNING','UNKNOWN_INTERRUPTED'}:
            raise ValueError('task is not running; uncertain work must not be replayed')
        folder=root/'reports'; folder.mkdir(exist_ok=True)
        for suffix, raw in [('.json',summary_raw),('.md',report_raw)]:
            path = folder/(task_id+suffix)
            if path.exists() and path.read_bytes()!=raw:
                raise ValueError('committed report bytes changed')
            atomic(path,raw)
        task.update(status=summary['status'], finished_at=stamp(now), conclusion=summary['conclusion'],
                    summary=str(folder/(task_id+'.json')), report=str(folder/(task_id+'.md')),
                    summary_sha256=digest(summary_raw), report_sha256=digest(report_raw))
        for kind, key in task.get('due_keys',{}).items():
            if state['due'].get(kind,{}).get('key')==key:
                state['due'][kind].update(status=summary['status'], task_id=task_id)
        return task
