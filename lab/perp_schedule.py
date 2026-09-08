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
REPO = Path(__file__).resolve().parents[1]
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
    for key in ('daily_rounds','daily_variants','weekly_rounds','weekly_variants',
                'health_minutes','market_available_delay_minutes','native_round_budget_seconds'):
        if type(policy.get(key)) is not int or policy[key] < 1:
            raise ValueError('positive integer policy field required: '+key)
    for key in ('heartbeat_minutes','disk_soft_cap_bytes','research_review_every_rounds'):
        if key in policy and (type(policy[key]) is not int or policy[key]<1):
            raise ValueError('positive integer policy field required: '+key)
    if policy['market_available_delay_minutes']>=60:
        raise ValueError('market delay must be within an hour')
    if 'round_limits_enforced' in policy and type(policy['round_limits_enforced']) is not bool:
        raise ValueError('round enforcement flag must be boolean')
    for group in ('acceptance_budget','confirmation_budget'):
        for key,value in policy.get(group,{}).items():
            if key.startswith(('normal_calls','technical_retries','native_calls','max_')) and (type(value) is not int or value<1):
                raise ValueError('positive bounded class budget required: '+group+' '+key)
    return policy, digest(raw)


def utc(value):
    try:
        at=datetime.fromisoformat(value.replace('Z','+00:00'))
        if at.tzinfo is None: raise ValueError('timezone missing')
        return at.astimezone(UTC)
    except (AttributeError,TypeError,ValueError):
        raise ValueError('explicit UTC-compatible timestamp required') from None


def window(start, end):
    start,end=utc(start),utc(end)
    if start>=end: raise ValueError('nonempty fixed input window required')
    return dict(start=stamp(start),end_exclusive=stamp(end))


def bound_file(name, expected):
    path=Path(name)
    if not path.is_absolute(): path=REPO/path
    if not re.fullmatch(r'[0-9a-f]{64}',str(expected)) or not path.is_file() or digest(path.read_bytes())!=expected:
        raise ValueError('frozen file SHA drift: '+str(path))
    return path


def validate_execution_class(task, policy):
    if task['kind'] not in {'acceptance','confirmation'}:
        return {}
    budget=policy.get(task['kind']+'_budget')
    if not budget:
        raise ValueError('separate execution class not authorized by policy')
    if (task.get('economic_selection') is not False or task.get('changes_economic_rules') is not False or
            task.get('fixed_candidate') is not True or type(task.get('native_calls')) is not int or
            task['native_calls']!=1 or task['variants']!=0):
        raise ValueError('economic selection cannot be classified as fixed acceptance/confirmation')
    for key in ('candidate_sha256','frozen_contract_sha256'):
        if not re.fullmatch(r'[0-9a-f]{64}',str(task.get(key,''))):
            raise ValueError('frozen candidate and purpose contract required')
    contract=json.loads(bound_file(task.get('frozen_contract_path',''),task['frozen_contract_sha256']).read_bytes())
    if task['kind']=='acceptance':
        if (contract.get('kind')!='acceptance' or contract.get('score_economics') is not False or
                contract.get('execution_class','acceptance')!='acceptance' or
                contract.get('economic_selection',False) is not False or contract.get('changes_economic_rules',False) is not False):
            raise ValueError('contract does not authorize fixed non-economic acceptance')
        candidate_sha=contract.get('registration_sha256')
        registration=json.loads(bound_file(contract.get('registration_path',''),candidate_sha).read_bytes())
        frozen_window=window(contract.get('window_start'),contract.get('window_end_exclusive'))
        if ('candidate_registration_sha256' in contract and contract['candidate_registration_sha256']!=candidate_sha or
                'candidate_registration_path' in contract and Path(contract['candidate_registration_path'])!=Path(contract['registration_path'])):
            raise ValueError('acceptance contract registration aliases disagree')
        if 'fixed_input_window' in contract:
            fixed=contract['fixed_input_window']
            if (window(fixed.get('start'),fixed.get('end_exclusive',fixed.get('end')))!=frozen_window or
                    'end' in fixed and utc(fixed['end'])!=utc(frozen_window['end_exclusive'])):
                raise ValueError('acceptance contract window aliases disagree')
        earliest=utc(contract.get('earliest_ready_at'))
        if (contract.get('candidate_id')!=registration.get('candidate_id') or
                contract.get('variant')!=registration.get('variant') or
                contract.get('confirmation_protocol_sha256')!=registration.get('confirmation_protocol_sha256')):
            raise ValueError('acceptance candidate/purpose contract mismatch')
        confirmation=json.loads(bound_file(contract.get('confirmation_protocol_path',''),contract.get('confirmation_protocol_sha256')).read_bytes())
    else:
        if (not str(contract.get('protocol_id','')).startswith('PERP_INDEPENDENT_CONFIRMATION_V') or
                contract.get('window',{}).get('kind')!='GENUINELY_FUTURE'):
            raise ValueError('contract does not authorize future independent confirmation')
        candidate_sha=task['candidate_sha256']
        registration=json.loads(bound_file(contract.get('candidate_registration_path',''),candidate_sha).read_bytes())
        if registration.get('confirmation_protocol_sha256')!=task['frozen_contract_sha256']:
            raise ValueError('confirmation registration/protocol mismatch')
        confirmation=contract
        frozen_window=window(contract['window'].get('start_inclusive'),contract['window'].get('end_exclusive'))
        if window(registration.get('window',{}).get('start_inclusive'),registration.get('window',{}).get('end_exclusive'))!=frozen_window:
            raise ValueError('confirmation registration/window mismatch')
        earliest=utc(frozen_window['end_exclusive'])
    if task['candidate_sha256']!=candidate_sha:
        raise ValueError('candidate SHA does not match frozen registration')
    supplied=task.get('fixed_input_window',{})
    if window(supplied.get('start'),supplied.get('end_exclusive'))!=frozen_window:
        raise ValueError('task window differs from frozen contract')
    bindings=registration.get('code_bindings',{})
    if not isinstance(bindings,dict) or not bindings:
        raise ValueError('complete candidate code bindings required')
    for name,expected in bindings.items(): bound_file(name,expected)
    economic={key:registration.get(key) for key in ('variant','strategy_sha256','candidate_protocol_sha256','cost_sha256')}
    if not isinstance(economic['variant'],str) or not economic['variant']:
        raise ValueError('fixed economic variant required')
    if any(not re.fullmatch(r'[0-9a-f]{64}',str(economic[k])) or economic[k] not in bindings.values() for k in economic if k!='variant'):
        raise ValueError('economic candidate identity lacks verified code bindings')
    selected=confirmation.get('candidate_selection',{}).get('selection_for_this_version',{})
    if (selected.get('candidate_id')!=registration.get('candidate_id') or
            any(selected.get(k)!=economic[k] for k in ('variant','strategy_sha256','candidate_protocol_sha256'))):
        raise ValueError('economic identity differs from frozen candidate selection')
    bound_file(selected.get('strategy_path',''),economic['strategy_sha256'])
    candidate_protocol=json.loads(bound_file(selected.get('candidate_protocol_path',''),economic['candidate_protocol_sha256']).read_bytes())
    bound_file(candidate_protocol.get('parent_protocol',''),economic['cost_sha256'])
    if type(task['max_seconds']) is not int or not 1<=task['max_seconds']<=budget['max_wall_seconds_per_call']:
        raise ValueError('separate execution wall-time budget')
    return dict(candidate_budget_key=digest(canonical(economic)),fixed_input_window=frozen_window,
                contract_ready_at=stamp(max(earliest,utc(frozen_window['end_exclusive']))))


def same_acceptance(task, prior):
    return (task.get('retry_of')==prior['id'] and prior['status']=='BLOCKED_RUNTIME' and
            isinstance(task.get('technical_retry_reason'),str) and bool(task['technical_retry_reason'].strip()) and
            all(task.get(k)==prior.get(k) for k in ('candidate_budget_key','frozen_contract_sha256','data_sha256','fixed_input_window')))


def verify_preflight(preflight, task):
    """A claim binds actual immutable inputs, not a caller's invented digest."""
    source=preflight.get('source_manifest',{})
    if preflight.get('status')!='READY_NATIVE_ACCEPTANCE' or not isinstance(source,dict) or not source.get('source_files'):
        raise ValueError('ready actual-source manifest required')
    path=Path(preflight.get('input_manifest_path',''))
    if not path.is_absolute() or json.loads(bound_file(path,preflight.get('data_sha256')).read_bytes())!=source:
        raise ValueError('actual input manifest differs from preflight')
    if window(source.get('start'),source.get('end'))!=task['fixed_input_window']:
        raise ValueError('actual input manifest window mismatch')
    if source.get('identity',{}).get('registration_sha256')!=task['candidate_sha256']:
        raise ValueError('actual input manifest candidate mismatch')
    for name,expected in source['source_files'].items():
        if not Path(name).is_absolute(): raise ValueError('absolute actual source path required')
        bound_file(name,expected)
    bound_file(source.get('intent_snapshot_path',''),source.get('intent_snapshot_sha256'))
    bindings=preflight.get('code_bindings',{})
    if not bindings or digest(json.dumps(bindings,sort_keys=True,default=str).encode())!=preflight.get('code_sha256'):
        raise ValueError('actual preflight code bundle mismatch')
    for name,expected in bindings.items(): bound_file(name,expected)


def verify_reports(state):
    """Terminal status is usable only while its persisted evidence still matches."""
    for task in state['tasks']:
        if task['status'] not in TERMINAL:
            continue
        for key in ('summary','report'):
            path=Path(task[key])
            if not path.is_file() or digest(path.read_bytes())!=task[key+'_sha256']:
                raise ValueError('terminal evidence SHA drift: '+task['id']+' '+key)
        summary=json.loads(Path(task['summary']).read_bytes())
        expected=dict(task_id=task['id'],**{k:task[k] for k in ['code_sha256','data_sha256','policy_sha256']})
        if summary.get('task_binding')!=expected or summary.get('status')!=task['status']:
            raise ValueError('terminal evidence binding drift: '+task['id'])


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
        verify_reports(state)
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
    verify_reports(state)
    return state


def migrate_policy(root, old_policy_path, new_policy_path, supersede_task_id=None, now=None):
    """Explicit, crash-safe policy migration; spent tasks retain their old bindings."""
    now = now or datetime.now(UTC)
    new_policy, new_sha = load_policy(new_policy_path)
    with locked(root, old_policy_path) as (root, old_policy, state):
        if any(t['status'] in {'RUNNING','UNKNOWN_INTERRUPTED'} for t in state['tasks']):
            raise ValueError('migration requires a reconciled idle writer')
        if new_sha == state['policy_sha256']:
            raise ValueError('migration must change versioned policy')
        if new_policy.get('supersedes_policy_version') != old_policy.get('policy_version'):
            raise ValueError('explicit predecessor policy required')
        pending = [t for t in state['tasks'] if t['status'] in OPEN]
        if pending:
            if len(pending)!=1 or pending[0]['id']!=supersede_task_id:
                raise ValueError('pending task needs explicit supersession')
            task = pending[0]
            if (task['status']!='QUEUED' or task.get('started_at') or
                task.get('code_binding_role')!='PARENT_CODE_AND_PREPARATION_REFERENCE_NOT_YET_V2_EXECUTOR'):
                raise ValueError('only unused parent-bound preparation may be superseded')
        elif supersede_task_id:
            raise ValueError('supersession target is not pending')
        before = canonical(state)
        folder=root/'policy-migrations'; folder.mkdir(exist_ok=True)
        snapshot=folder/(state['policy_sha256']+'-before-'+new_sha+'.json')
        if snapshot.exists() and snapshot.read_bytes()!=before:
            raise ValueError('migration snapshot conflict')
        atomic(snapshot,before)
        for task in pending:
            task.update(status='SUPERSEDED',superseded_at=stamp(now),
                        superseded_reason='Unused parent binding replaced by actual V2 executor under new cumulative budget; no market execution.')
        receipt=dict(observed_at=stamp(now),old_policy_sha256=state['policy_sha256'],
                     new_policy_sha256=new_sha,before_state=str(snapshot),before_state_sha256=digest(before),
                     superseded_task_id=supersede_task_id,
                     spent_rounds_preserved=sum(bool(t.get('started_at')) for t in state['tasks'] if t['kind']=='research'),
                     spent_variants_preserved=sum(t['variants'] for t in state['tasks'] if t['kind']=='research' and t.get('started_at')))
        state.setdefault('policy_migrations',[]).append(receipt)
        state['policy_sha256']=new_sha
        return receipt


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
    task = dict(task)
    with locked(root, policy_path) as (_, policy, state):
        required = {'id','kind','mechanism','code_sha256','data_sha256','policy_sha256','hypothesis','variants','max_seconds'}
        if not required <= task.keys() or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', task['id']):
            raise ValueError('task schema/id')
        if task['kind'] not in {'data','research','acceptance','confirmation'} or task.get('status','QUEUED') not in {'QUEUED','WAITING_DATA'}:
            raise ValueError('task kind/status')
        if any(not re.fullmatch(r'[0-9a-f]{64}',task[k]) for k in ['code_sha256','data_sha256','policy_sha256']):
            raise ValueError('task SHA binding required')
        if task['policy_sha256'] != state['policy_sha256'] or not task['hypothesis']:
            raise ValueError('task policy/hypothesis')
        if type(task['variants']) is not int or not 0 <= task['variants'] <= policy['daily_variants']:
            raise ValueError('variant budget')
        if task['kind']=='research' and task['variants'] < 1:
            raise ValueError('research requires variants')
        if task['kind']!='research' and task['variants'] != 0:
            raise ValueError('only exploration registers economic variants')
        task.update(validate_execution_class(task,policy))
        if task['kind'] in {'research','data'} and (type(task['max_seconds']) is not int or not 1 <= task['max_seconds'] <= policy['native_round_budget_seconds']):
            raise ValueError('runtime budget')
        bound = {k:task[k] for k in ['kind','mechanism','code_sha256','data_sha256','policy_sha256','variants']}
        fingerprint = digest(canonical(bound))
        repeated=[t for t in state['tasks'] if t['fingerprint']==fingerprint]
        technical_retry=(task['kind']=='acceptance' and len(repeated)==1 and same_acceptance(task,repeated[0]))
        if any(t['id']==task['id'] for t in state['tasks']) or (repeated and not technical_retry):
            raise ValueError('task already registered; fingerprint remains consumed')
        if any(t['status'] in OPEN for t in state['tasks']):
            raise ValueError('exactly one prioritized outstanding task permitted')
        task = dict(task, fingerprint=fingerprint, status=task.get('status','QUEUED'), queued_at=stamp(now))
        state['tasks'].append(task)
        if task['kind']=='research' and 'daily_discovery' in state['due']:
            state['due']['daily_discovery'].update(next_task=task['id'],status='RESEARCH_QUEUE_UPDATED')
        return task


def claim(root, policy_path, task_id, now=None):
    now = now or datetime.now(UTC)
    with locked(root, policy_path) as (_, policy, state):
        task = task_by_id(state, task_id)
        if task['status'] != 'QUEUED' or any(t['status'] in {'RUNNING','UNKNOWN_INTERRUPTED'} for t in state['tasks']):
            raise ValueError('task not claimable or writer active')
        if task.get('data_binding_role')=='FUTURE_INPUT_CONTRACT_PENDING':
            raise ValueError('future data must be materialized before claim')
        if task.get('budget_not_before') and now < datetime.fromisoformat(task['budget_not_before'].replace('Z','+00:00')):
            raise ValueError('task budget not-before time has not arrived')
        execution=validate_execution_class(task,policy)
        if task.get('candidate_budget_key')!=execution.get('candidate_budget_key'):
            raise ValueError('frozen economic candidate identity drift')
        task.update(execution)
        if task.get('data_binding_role')=='ACTUAL_PREFLIGHT_SOURCES':
            preflight=json.loads(bound_file(task['preflight_path'],task['preflight_sha256']).read_bytes())
            if any(task[k]!=preflight.get(k) for k in ('code_sha256','data_sha256','policy_sha256')):
                raise ValueError('materialized preflight binding drift')
            verify_preflight(preflight,task)
        started = [t for t in state['tasks'] if t.get('started_at') and t['kind']=='research']
        if task['kind']=='research':
            for period, fmt in [('daily','%Y-%m-%d'), ('weekly','%G-W%V')]:
                used = [t for t in started if datetime.fromisoformat(t['started_at']).strftime(fmt)==now.strftime(fmt)]
                if ((policy.get('round_limits_enforced',True) and len(used)+1>policy[period+'_rounds']) or
                        sum(t['variants'] for t in used)+task['variants']>policy[period+'_variants']):
                    raise ValueError(period+' budget exhausted')
            ended=[t for t in started if t['status'] in TERMINAL]
            cadence=policy.get('research_review_every_rounds',3)
            if not policy.get('round_limits_enforced',True) and ended and len(ended)%cadence==0:
                previous=ended[-1];review=task.get('review_checkpoint',{})
                if (review.get('previous_task_id')!=previous['id'] or
                        review.get('previous_summary_sha256')!=previous.get('summary_sha256') or
                        not review.get('information_value') or not review.get('stop_condition') or
                        review.get('previous_wall_seconds')!=previous.get('claimed_to_report_seconds')):
                    raise ValueError('research resource/information review checkpoint required')
        if task['kind'] in {'acceptance','confirmation'}:
            if now < utc(task['contract_ready_at']):
                raise ValueError('fixed input window has not ended; preserve natural wait')
            used=[t for t in state['tasks'] if t.get('started_at') and t['kind']==task['kind'] and
                  t.get('candidate_budget_key')==task['candidate_budget_key']]
            budget=policy[task['kind']+'_budget']
            if task['kind']=='confirmation':
                used=[t for t in used if t['fixed_input_window']==task['fixed_input_window']]
                if used: raise ValueError('confirmation already consumed; never replay or select best run')
            else:
                if len(used)>=budget['normal_calls_per_candidate']+budget['technical_retries_per_candidate']:
                    raise ValueError('acceptance call budget exhausted')
                if sum(t['max_seconds'] for t in used)+task['max_seconds']>budget['max_reserved_wall_seconds_per_candidate']:
                    raise ValueError('acceptance cumulative wall-time budget exhausted')
                if used:
                    prior=used[-1]
                    if not same_acceptance(task,prior):
                        raise ValueError('only a specific technical retry of same frozen acceptance is allowed')
                elif task.get('retry_of'):
                    raise ValueError('acceptance retry has no original consumed call')
        task.update(status='RUNNING', started_at=stamp(now),
                    queue_wait_seconds=max(0,(now-datetime.fromisoformat(task['queued_at'])).total_seconds()))
        if task['kind']=='research' and 'daily_discovery' in state['due']:
            state['due']['daily_discovery'].update(next_task=task['id'],status='RESEARCH_RUNNING')
        return task


def ready(root, policy_path, task_id):
    with locked(root, policy_path) as (_, _, state):
        task = task_by_id(state, task_id)
        if task['status'] != 'WAITING_DATA':
            raise ValueError('task is not waiting for data')
        if task.get('data_binding_role')=='FUTURE_INPUT_CONTRACT_PENDING':
            raise ValueError('future data requires materialize with actual preflight')
        task['status'] = 'QUEUED'
        return task


def materialize(root, policy_path, task_id, preflight_path, now=None):
    """Bind future inputs once they exist, without consuming research budget."""
    now=now or datetime.now(UTC)
    raw=Path(preflight_path).read_bytes();preflight=json.loads(raw)
    if any(not re.fullmatch(r'[0-9a-f]{64}',str(preflight.get(k,''))) for k in ['code_sha256','data_sha256','policy_sha256']):
        raise ValueError('actual preflight SHA required')
    with locked(root,policy_path) as (root,policy,state):
        task=task_by_id(state,task_id)
        if task['status']!='WAITING_DATA' or task.get('started_at') or task.get('data_binding_role')!='FUTURE_INPUT_CONTRACT_PENDING':
            raise ValueError('only unstarted future-input wait can materialize')
        if any(task[k]!=preflight[k] for k in ['code_sha256','policy_sha256']):
            raise ValueError('future executor/policy drift')
        task.update(validate_execution_class(task,policy))
        if now<utc(task['contract_ready_at']):
            raise ValueError('fixed input window has not ended; preserve natural wait')
        verify_preflight(preflight,task)
        bound={k:task[k] for k in ['kind','mechanism','code_sha256','data_sha256','policy_sha256','variants']}
        bound['data_sha256']=preflight['data_sha256'];fingerprint=digest(canonical(bound))
        if any(t['id']!=task_id and (t['fingerprint']==fingerprint or fingerprint in t.get('preparation_fingerprints',[])) for t in state['tasks']):
            raise ValueError('materialized fingerprint already consumed')
        folder=root/'preflights';folder.mkdir(exist_ok=True);path=folder/(task_id+'.json')
        if path.exists() and path.read_bytes()!=raw:
            raise ValueError('materialized preflight already frozen differently')
        atomic(path,raw)
        task['preparation_binding']={k:task[k] for k in ['code_sha256','data_sha256','policy_sha256','fingerprint','data_binding_role']}
        task.setdefault('preparation_fingerprints',[]).append(task['fingerprint'])
        task.update(status='QUEUED',data_sha256=preflight['data_sha256'],fingerprint=fingerprint,
                    data_binding_role='ACTUAL_PREFLIGHT_SOURCES',materialized_at=stamp(now),
                    preflight_path=str(path),preflight_sha256=digest(raw))
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
        task['claimed_to_report_seconds']=(now-datetime.fromisoformat(task['started_at'])).total_seconds()
        if task['kind']=='research' and 'daily_discovery' in state['due']:
            state['due']['daily_discovery'].update(completed_task=task['id'],next_task=None,status='RESEARCH_COMPLETED_NEXT_PENDING')
        for kind, key in task.get('due_keys',{}).items():
            if state['due'].get(kind,{}).get('key')==key:
                state['due'][kind].update(status=summary['status'], task_id=task_id)
        return task
