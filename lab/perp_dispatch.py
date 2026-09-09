"""Append-only dispatch admission over the unchanged V3 coordinator and writer lock."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
from lab import perp_schedule as s

UTC = timezone.utc
FILES = ('lab/perp_dispatch.py', 'scripts/perp_dispatch.py', 'lab/perp_schedule.py', 'lab/perp_data_candidate.py')
PAIRS = {'BTC/USDT:USDT', 'ETH/USDT:USDT'}


def load(dispatch_policy, budget_policy):
    raw = Path(dispatch_policy).read_bytes(); p = json.loads(raw)
    if (p.get('protocol_id') != 'PERP_DISPATCH_V1' or p.get('market_workers') != 1 or
            [p.get(k) for k in ('max_open_confirmation','max_open_research','max_active_mechanisms')] != [1,1,2] or
            p.get('maintenance_buffer_seconds') != 300 or p.get('runtime_policy_change') is not False):
        raise ValueError('invalid bounded dispatch policy')
    if s.digest(Path(budget_policy).read_bytes()) != p['budget_policy_sha256']:
        raise ValueError('frozen V3 budget policy drift')
    s.bound_file('lab/perp_schedule.py', p['legacy_scheduler_sha256'])
    protocol = json.loads(s.bound_file(p['confirmation_protocol_path'], p['confirmation_protocol_sha256']).read_bytes())
    if p.get('allowed_development_roots') != ['first-capture-v1','cm-supplement-v1']:
        raise ValueError('development root scope drift')
    if s.window(p['development_window']['start'],p['development_window']['end_exclusive']) != s.window('2025-01-01T00:00:00Z','2026-07-01T00:00:00Z'):
        raise ValueError('frozen exposed development window drift')
    p['confirmation_window'] = s.window(protocol['window']['start_inclusive'],protocol['window']['end_exclusive'])
    return p, s.digest(raw)


def code_bindings():
    return {name:s.digest((s.REPO/name).read_bytes()) for name in FILES}


def idle(state):
    if any(t['status'] in {'RUNNING','UNKNOWN_INTERRUPTED'} for t in state['tasks']):
        raise ValueError('writer active or UNKNOWN; reconcile without replay')


def lanes(tasks):
    pending = [t for t in tasks if t['status'] in s.OPEN]
    if (any(t['kind'] not in {'research','confirmation'} for t in pending) or
            any(sum(t['kind']==kind for t in pending)>1 for kind in ('research','confirmation')) or
            len({t['mechanism'] for t in pending})>2):
        raise ValueError('only one confirmation plus one priority research task permitted')
    return pending


def verify_binding(state, dispatch_sha):
    ref = state.get('dispatch_binding', {})
    binding = json.loads(s.bound_file(ref.get('path',''),ref.get('sha256')).read_bytes())
    if binding['dispatch_policy_sha256'] != dispatch_sha or binding['budget_policy_sha256'] != state['policy_sha256']:
        raise ValueError('runtime dispatch binding drift')
    for path, expected in binding['code_bindings'].items(): s.bound_file(path,expected)
    s.bound_file(binding['dispatch_policy_path'],dispatch_sha)
    s.bound_file(binding['before_state'],binding['before_state_sha256'])
    lanes(state['tasks'])
    return ref['sha256']


def install(root, budget_policy, dispatch_policy, now=None):
    now = now or datetime.now(UTC); _, sha = load(dispatch_policy,budget_policy)
    with s.locked(root,budget_policy) as (root,_,state):
        idle(state); lanes(state['tasks'])
        if state.get('dispatch_binding'):
            return dict(status='NO_OP_ALREADY_INSTALLED',binding_sha256=verify_binding(state,sha))
        before = s.canonical(state); folder=root/'dispatch-bindings'/sha; folder.mkdir(parents=True,exist_ok=True)
        snapshot=folder/'before-state.json'; binding_path=folder/'binding.json'
        # A partial installation can be resumed only against the exact original state.
        if snapshot.exists() and snapshot.read_bytes()!=before: raise ValueError('dispatch installation snapshot conflict')
        s.atomic(snapshot,before)
        binding=dict(version=1,installed_at=s.stamp(now),dispatch_policy_path=str(Path(dispatch_policy).resolve()),
            dispatch_policy_sha256=sha,budget_policy_sha256=state['policy_sha256'],code_bindings=code_bindings(),
            before_state=str(snapshot),before_state_sha256=s.digest(before),
            preserved_tasks_sha256=s.digest(s.canonical(state['tasks'])),economic_rules_changed=False)
        if binding_path.exists():
            prior=json.loads(binding_path.read_bytes())
            if {k:v for k,v in prior.items() if k!='installed_at'} != {k:v for k,v in binding.items() if k!='installed_at'}:
                raise ValueError('dispatch installation binding conflict')
            binding=prior
        else: s.atomic(binding_path,s.canonical(binding))
        state['dispatch_binding']=dict(path=str(binding_path),sha256=s.digest(s.canonical(binding)))
        return dict(status='DISPATCH_INSTALLED',**state['dispatch_binding'],preserved_tasks_sha256=binding['preserved_tasks_sha256'])


def development_inputs(root, task, policy):
    path=s.bound_file(task.get('development_manifest_path',''),task.get('development_manifest_sha256'))
    if not path.is_absolute() or task['data_sha256']!=s.digest(path.read_bytes()):
        raise ValueError('research data must bind the actual development manifest')
    m=json.loads(path.read_bytes())
    if Path(m.get('runtime_root','')).resolve()!=Path(root).resolve().parent:
        raise ValueError('development manifest runtime root mismatch')
    allowed=s.window(policy['development_window']['start'],policy['development_window']['end_exclusive'])
    if m.get('schema')!='perp-development-inputs-v1' or m.get('use')!='EXPOSED_DEVELOPMENT_ONLY' or m.get('window')!=allowed:
        raise ValueError('fixed development input window/use required')
    sources=m.get('files',[])
    if not sources or not any(i.get('role')=='market' for i in sources): raise ValueError('actual market input files required')
    start,end=map(s.utc,(allowed['start'],allowed['end_exclusive']))
    fs,fe=map(s.utc,(policy['confirmation_window']['start'],policy['confirmation_window']['end_exclusive']))
    permitted=[(Path(root).parent/'data'/n).resolve() for n in policy['allowed_development_roots']]
    observed={}; market_count=0
    for item in sources:
        source=Path(item.get('path',''))
        if not source.is_absolute(): raise ValueError('absolute development source required')
        source=source.resolve()
        if str(source) in observed: raise ValueError('duplicate development source')
        data_root=next((r for r in permitted if source.is_relative_to(r)),None)
        metadata=item.get('role')=='metadata'
        if not data_root: raise ValueError('source outside fixed development roots')
        raw=s.bound_file(source,item.get('sha256')).read_bytes(); observed[str(source)]=s.digest(raw)
        if metadata:
            if source.parent!=data_root or source.name not in {'receipt.json','instrument-rules.json'}:
                raise ValueError('market values cannot be relabelled as metadata')
            d=json.loads(raw)
            if source.name=='instrument-rules.json':
                if ({r['symbol'] for r in d.get('symbols',[])}!={'BTCUSDT','ETHUSDT'} or
                        any(r.get('contractType')!='PERPETUAL' or r.get('quoteAsset')!='USDT' or r.get('marginAsset')!='USDT' for r in d['symbols'])):
                    raise ValueError('instrument metadata scope drift')
            elif d.get('root') and Path(d['root']).resolve()!=data_root: raise ValueError('development receipt root drift')
            continue
        if item.get('role')!='market' or item.get('time_field') not in {'event_time','time'}:
            raise ValueError('explicit economic timestamp parser required')
        if source.suffix=='.jsonl': rows=[json.loads(line) for line in raw.splitlines() if line.strip()]
        else:
            payload=json.loads(raw); rows=payload.get('data') if item.get('rows_key')=='data' and isinstance(payload,dict) else payload
        if not isinstance(rows,list) or not rows: raise ValueError('nonempty actual market rows required')
        for row in rows:
            if not isinstance(row,dict): raise ValueError('unsupported market row shape')
            # Check every recognized economic time, so choosing an innocent alias cannot hide future rows.
            field=item['time_field']; at=s.utc(row[field])
            times=[s.utc(row[k]) for k in ('event_time','time','cost_time') if k in row]
            if any(not start<=v<end or fs<=v<fe for v in [at,*times]):
                raise ValueError('actual market timestamp outside development / overlaps confirmation')
        market_count+=len(rows)
    return dict(source_files=observed,market_rows=market_count,
                source_identity_sha256=s.digest(s.canonical(observed)))


def validate_development_manifest(path,expected_sha256,dispatch_policy):
    """Preparation-only input check; installation and queue writes are not required."""
    manifest=json.loads(s.bound_file(path,expected_sha256).read_bytes())
    raw=json.loads(Path(dispatch_policy).read_bytes())
    policy,_=load(dispatch_policy,s.REPO/raw['budget_policy_path'])
    runtime=Path(manifest.get('runtime_root',''))
    if not runtime.is_absolute() or any((p/'.git').exists() for p in [runtime,*runtime.parents]):
        raise ValueError('absolute development runtime outside Git required')
    return development_inputs(runtime/'scheduler',dict(development_manifest_path=str(path),
        development_manifest_sha256=expected_sha256,data_sha256=expected_sha256),policy)


def maintenance(root, policy, task, now, state=None):
    """Read canonical committed receipts, never caller-declared freshness."""
    from lab.perp_data_candidate import candidate_complete
    from lab.perp_forward_signal import control
    base=Path(root).parent; delay=timedelta(minutes=policy['market_available_delay_minutes'])
    end=(now-delay).replace(minute=0,second=0,microsecond=0)
    folder=base/'data'/'incremental'/end.strftime('%Y%m%dT%H%M%SZ')
    capture=folder/'receipt.json'; update=folder/'update-receipt.json'
    receipt=json.loads(capture.read_bytes()); committed=json.loads(update.read_bytes())
    if (committed.get('status')!='DATA_CAPTURED' or committed.get('core_complete') is not True or
            s.utc(receipt['window_end_exclusive'])!=end or not candidate_complete(receipt,folder)):
        raise ValueError('required candidate acquisition must complete before research')
    protocol_path=s.REPO/'docs/protocols/perp-independent-confirmation-v2.json'
    protocol=json.loads(protocol_path.read_bytes())
    needs_observer=(now<s.utc(protocol['window']['end_exclusive']) or state is None or
        any(t['kind']=='confirmation' and t['status'] in s.OPEN for t in state['tasks']))
    files={str(p):s.digest(p.read_bytes()) for p in (capture,update)}
    if needs_observer:
        signal_root=base/'forward-signals'; observer=json.loads((signal_root/'state.json').read_bytes())
        registration_path=s.REPO/protocol['candidate_registration_path']
        _,_,_,identity=control(registration_path,protocol_path,signal_root/'observer-binding.json')
        if (observer.get('identity')!=identity or observer.get('active') is not True or
                s.utc(observer['activated_at'])>=s.utc(protocol['window']['start_inclusive'])):
            raise ValueError('unchanged activated candidate identity required')
        entry=end+timedelta(hours=1); key=entry.strftime('%Y%m%dT%H00Z')
        rp=signal_root/'hours'/(key+'.receipt.json'); ip=signal_root/'hours'/(key+'.intent.json')
        record=observer['records'][key]; sr=json.loads(s.bound_file(rp,record['receipt_sha256']).read_bytes())
        intent=json.loads(s.bound_file(ip,record['intent_sha256']).read_bytes())
        if (sr['intent_sha256']!=record['intent_sha256'] or sr['identity']!=observer['identity'] or
                intent['identity']!=observer['identity'] or s.utc(intent['planned_entry'])!=entry or
                not s.utc(sr['published_observed_at'])<entry or s.utc(sr['published_observed_at'])>now or
                set(sr['pairs'])!=PAIRS or any(v['status'] not in {'TIMELY_SIGNAL','TIMELY_NO_TRADE'} for v in sr['pairs'].values())):
            raise ValueError('timely committed candidate intents required before research')
        files.update({str(p):s.digest(p.read_bytes()) for p in (rp,ip)})
    deadline=end+timedelta(hours=1)+delay
    if now+timedelta(seconds=task['max_seconds']+300)>=deadline:
        raise ValueError('research would cross next required maintenance deadline')
    return dict(observed_at=s.stamp(now),next_maintenance_at=s.stamp(deadline),receipt_files=files,observer_required=needs_observer)


def check_task(task, state, policy, dispatch, root):
    required={'id','kind','mechanism','code_sha256','data_sha256','policy_sha256','hypothesis','variants','max_seconds'}
    if (not required<=task.keys() or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',task['id']) or
            task['kind'] not in {'research','confirmation'} or not task['mechanism'] or not task['hypothesis']):
        raise ValueError('dispatch task schema')
    if task.get('status','QUEUED') not in {'QUEUED','WAITING_DATA'}: raise ValueError('unstarted queue status required')
    if (task['policy_sha256']!=state['policy_sha256'] or
            any(not re.fullmatch(r'[0-9a-f]{64}',str(task[k])) for k in ('code_sha256','data_sha256','policy_sha256'))):
        raise ValueError('task SHA binding drift')
    if task['kind']=='confirmation':
        if task.get('frozen_contract_sha256')!=dispatch['confirmation_protocol_sha256']:
            raise ValueError('only the unchanged frozen confirmation permitted')
        task.update(s.validate_execution_class(task,policy)); return None
    if (type(task['variants']) is not int or not 1<=task['variants']<=policy['daily_variants'] or
            type(task['max_seconds']) is not int or not 1<=task['max_seconds']<=policy['native_round_budget_seconds']):
        raise ValueError('bounded exploration variants/runtime required')
    bindings=task.get('code_bindings',{})
    if not bindings or s.digest(json.dumps(bindings,sort_keys=True,default=str).encode())!=task['code_sha256']:
        raise ValueError('actual research executor code bundle required')
    for name,expected in bindings.items(): s.bound_file(name,expected)
    return development_inputs(root,task,dispatch)


def enqueue(root,budget_policy,dispatch_policy,task,now=None):
    now=now or datetime.now(UTC); dispatch,sha=load(dispatch_policy,budget_policy); task=dict(task)
    with s.locked(root,budget_policy) as (_,policy,state):
        binding=verify_binding(state,sha); idle(state)
        inputs=check_task(task,state,policy,dispatch,root)
        bound={k:task[k] for k in ('kind','mechanism','code_sha256','data_sha256','policy_sha256','variants')}
        fingerprint=s.digest(s.canonical(bound))
        identity=dict(bound); identity.pop('policy_sha256')
        if inputs: identity['data_sha256']=inputs['source_identity_sha256']
        stable=s.digest(s.canonical(identity))
        if any(t['id']==task['id'] or t['fingerprint']==fingerprint or t.get('dispatch_experiment_key')==stable for t in state['tasks']):
            raise ValueError('task/experiment already consumed; renaming is not a new experiment')
        task.update(status=task.get('status','QUEUED'),queued_at=s.stamp(now),fingerprint=fingerprint,
                    dispatch_experiment_key=stable,dispatch_binding_sha256=binding)
        lanes([*state['tasks'],task]); state['tasks'].append(task)
        return task


def claim(root,budget_policy,dispatch_policy,task_id,now=None):
    now=now or datetime.now(UTC); dispatch,sha=load(dispatch_policy,budget_policy)
    with s.locked(root,budget_policy) as (_,policy,state):
        binding=verify_binding(state,sha); idle(state); task=s.task_by_id(state,task_id)
        if task['status']!='QUEUED' or task.get('data_binding_role')=='FUTURE_INPUT_CONTRACT_PENDING':
            raise ValueError('task not claimable; future inputs require materialization')
        check_task(task,state,policy,dispatch,root)
        if task.get('budget_not_before') and now<s.utc(task['budget_not_before']): raise ValueError('task budget not-before')
        if task['kind']=='research':
            for pending in lanes(state['tasks']):
                if pending['kind']=='confirmation':
                    execution=s.validate_execution_class(pending,policy)
                    if now+timedelta(seconds=task['max_seconds']+300)>=s.utc(execution['contract_ready_at']):
                        raise ValueError('due or approaching confirmation has priority')
            started=[t for t in state['tasks'] if t.get('started_at') and t['kind']=='research']
            for period,fmt in [('daily','%Y-%m-%d'),('weekly','%G-W%V')]:
                used=[t for t in started if s.utc(t['started_at']).strftime(fmt)==now.astimezone(UTC).strftime(fmt)]
                if sum(t['variants'] for t in used)+task['variants']>policy[period+'_variants']:
                    raise ValueError(period+' budget exhausted')
            ended=[t for t in started if t['status'] in s.TERMINAL]
            if ended and len(ended)%policy['research_review_every_rounds']==0:
                last=ended[-1]; review=task.get('review_checkpoint',{})
                if (review.get('previous_task_id')!=last['id'] or review.get('previous_summary_sha256')!=last.get('summary_sha256') or
                        review.get('previous_wall_seconds')!=last.get('claimed_to_report_seconds') or
                        not review.get('information_value') or not review.get('stop_condition')):
                    raise ValueError('research evidence/resource review checkpoint required')
            evidence=maintenance(root,policy,task,now,state)
        else:
            execution=s.validate_execution_class(task,policy)
            if task.get('candidate_budget_key')!=execution['candidate_budget_key']: raise ValueError('candidate identity drift')
            if now<s.utc(execution['contract_ready_at']): raise ValueError('WAIT_FORWARD: preserve natural confirmation wait')
            if any(t.get('started_at') and t['kind']=='confirmation' and t.get('candidate_budget_key')==task['candidate_budget_key'] and
                   t.get('fixed_input_window')==task['fixed_input_window'] for t in state['tasks']):
                raise ValueError('confirmation already consumed; no replay')
            if task.get('data_binding_role')!='ACTUAL_PREFLIGHT_SOURCES': raise ValueError('actual confirmation preflight required')
            preflight=json.loads(s.bound_file(task['preflight_path'],task['preflight_sha256']).read_bytes())
            if any(task[k]!=preflight.get(k) for k in ('code_sha256','data_sha256','policy_sha256')): raise ValueError('preflight binding drift')
            s.verify_preflight(preflight,task); evidence={'priority':'FROZEN_CONFIRMATION'}
        task.update(status='RUNNING',started_at=s.stamp(now),dispatch_claim_binding_sha256=binding,
                    dispatch_maintenance=evidence,queue_wait_seconds=max(0,(now-s.utc(task['queued_at'])).total_seconds()))
        return task


def status(root,budget_policy,dispatch_policy):
    _,sha=load(dispatch_policy,budget_policy); state=s.read_status(root,budget_policy)
    binding=verify_binding(state,sha)
    return dict(status='DISPATCH_READY',dispatch_binding_sha256=binding,
                open_tasks=lanes(state['tasks']),state=state)


def validate_running_admission(root,state,task,budget_policy,dispatch_policy,now=None):
    """Read-only admission recheck. Caller MUST already hold the legacy writer lock."""
    now=now or datetime.now(UTC); dispatch,sha=load(dispatch_policy,budget_policy)
    policy,_=s.load_policy(budget_policy); binding=verify_binding(state,sha)
    if (task!=s.task_by_id(state,task['id']) or task['status']!='RUNNING' or
            [t['id'] for t in state['tasks'] if t['status'] in {'RUNNING','UNKNOWN_INTERRUPTED'}]!=[task['id']] or
            task.get('dispatch_claim_binding_sha256')!=binding):
        raise ValueError('actual exclusive dispatch RUNNING admission required')
    if not s.utc(task['started_at'])<=now<s.utc(task['started_at'])+timedelta(seconds=task['max_seconds']):
        raise ValueError('claimed execution time expired or clock reversed')
    if task['kind']!='research': raise ValueError('this execution recheck is for development research only')
    inputs=check_task(dict(task,status='QUEUED'),state,policy,dispatch,root)
    for pending in lanes(state['tasks']):
        if pending['kind']=='confirmation':
            execution=s.validate_execution_class(pending,policy)
            if now+timedelta(seconds=task['max_seconds']+300)>=s.utc(execution['contract_ready_at']):
                raise ValueError('due or approaching confirmation has priority')
    return dict(status='RUNNING_ADMISSION_VERIFIED',dispatch_binding_sha256=binding,
                development_inputs=inputs,maintenance=maintenance(root,policy,task,now,state))
