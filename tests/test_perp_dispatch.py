import copy
import fcntl
import json
from datetime import datetime,timedelta,timezone
from pathlib import Path
import pytest
from lab import perp_dispatch as d, perp_schedule as s

NOW=datetime(2026,9,9,0,38,tzinfo=timezone.utc)
REPO=Path(__file__).resolve().parents[1]
BP=REPO/'docs/protocols/perp-autonomous-policy-v3.json'
DP=REPO/'docs/protocols/perp-dispatch-policy-v1.json'

def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(s.canonical(value));return path

def digest(path):return s.digest(path.read_bytes())

@pytest.fixture
def env(tmp_path):
    root=tmp_path/'runtime'/'scheduler';source=root.parent/'data'/'first-capture-v1'
    market=write(source/'BTCUSDT-ohlcv.jsonl',dict(event_time='2025-01-01T00:00:00Z',close='100'))
    # JSONL must have one compact row, not pretty-printed JSON.
    market.write_text(json.dumps(dict(event_time='2025-01-01T00:00:00Z',close='100'))+'\n')
    receipt=write(source/'receipt.json',dict(root=str(source),datasets={}))
    manifest=write(root.parent/'experiments'/'development.json',dict(schema='perp-development-inputs-v1',
        use='EXPOSED_DEVELOPMENT_ONLY',runtime_root=str(root.parent),
        window=s.window('2025-01-01T00:00:00Z','2026-07-01T00:00:00Z'),files=[
        dict(path=str(market),sha256=digest(market),role='market',time_field='event_time'),
        dict(path=str(receipt),sha256=digest(receipt),role='metadata')]))
    code=tmp_path/'strategy.py';code.write_text('# frozen synthetic executor\n');bindings={str(code):digest(code)}
    task=dict(id='research-one',kind='research',mechanism='distinct-development',code_bindings=bindings,
        code_sha256=s.digest(json.dumps(bindings,sort_keys=True,default=str).encode()),
        data_sha256=digest(manifest),development_manifest_path=str(manifest),development_manifest_sha256=digest(manifest),
        policy_sha256=digest(BP),variants=2,max_seconds=900,hypothesis='One frozen synthetic comparison')
    d.install(root,BP,DP,NOW)
    return root,task,market,manifest


def confirmation():
    contract=REPO/'docs/protocols/perp-independent-confirmation-v2.json';p=json.loads(contract.read_bytes())
    reg=REPO/p['candidate_registration_path']
    return dict(id='confirmation-one',kind='confirmation',mechanism='frozen-carry',code_sha256='a'*64,
        data_sha256=digest(contract),policy_sha256=digest(BP),hypothesis='Fixed genuinely future confirmation',
        variants=0,max_seconds=2400,native_calls=1,economic_selection=False,changes_economic_rules=False,fixed_candidate=True,
        candidate_sha256=digest(reg),frozen_contract_path=str(contract),frozen_contract_sha256=digest(contract),
        fixed_input_window=s.window(p['window']['start_inclusive'],p['window']['end_exclusive']),
        status='WAITING_DATA',data_binding_role='FUTURE_INPUT_CONTRACT_PENDING')


def maintenance(env,at=NOW):
    root,*_=env;base=root.parent;end=(at-timedelta(minutes=10)).replace(minute=0,second=0,microsecond=0)
    folder=base/'data'/'incremental'/end.strftime('%Y%m%dT%H%M%SZ'); datasets={}
    for symbol in ('BTCUSDT','ETHUSDT'):
        for kind in ('ohlcv','mark','premium','funding'):
            event=end-timedelta(hours=8 if kind=='funding' else 1)
            row=dict(event_time=s.stamp(event),available_at=s.stamp(event+timedelta(hours=1)),rate='0',mark_price='100')
            path=folder/(symbol+'-'+kind+'.jsonl');path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(row)+'\n')
            datasets[symbol+'-'+kind]=dict(path=path.name,sha256=digest(path),rows=1,missing_rows=0)
    write(folder/'receipt.json',dict(instrument_rules='CURRENT_RULES_VERIFIED_HISTORICAL_RULES_UNPROVEN',
        window_end_exclusive=s.stamp(end),datasets=datasets,errors={}))
    write(folder/'update-receipt.json',dict(status='DATA_CAPTURED',core_complete=True))
    signal=base/'forward-signals';protocol=REPO/'docs/protocols/perp-independent-confirmation-v2.json'
    reg=REPO/json.loads(protocol.read_bytes())['candidate_registration_path']
    observer_files=('lab/perp_forward_signal.py','scripts/perp_forward_signal.py','lab/perp_schedule.py')
    binding=write(signal/'observer-binding.json',dict(registration_sha256=digest(reg),confirmation_protocol_sha256=digest(protocol),
        code_bindings={name:digest(REPO/name) for name in observer_files}))
    from lab.perp_forward_signal import control
    *_,identity=control(reg,protocol,binding)
    entry=end+timedelta(hours=1);key=entry.strftime('%Y%m%dT%H00Z')
    intent=write(signal/'hours'/(key+'.intent.json'),dict(identity=identity,planned_entry=s.stamp(entry)))
    receipt=write(signal/'hours'/(key+'.receipt.json'),dict(identity=identity,intent_sha256=digest(intent),
        published_observed_at=s.stamp(end+timedelta(minutes=11)),pairs={p:dict(status='TIMELY_NO_TRADE') for p in d.PAIRS}))
    write(signal/'state.json',dict(identity=identity,active=True,activated_at='2026-09-09T00:19:00Z',
        records={key:dict(receipt_sha256=digest(receipt),intent_sha256=digest(intent))}))
    return receipt


def test_append_only_install_preserves_budget_policy_and_every_task(env):
    root,task,*_=env
    binding=json.loads(Path(s.read_status(root,BP)['dispatch_binding']['path']).read_bytes())
    before=json.loads(Path(binding['before_state']).read_bytes());state=s.read_status(root,BP)
    assert state['tasks']==before['tasks'] and state['policy_sha256']==before['policy_sha256']==digest(BP)
    assert d.install(root,BP,DP,NOW)['status']=='NO_OP_ALREADY_INSTALLED'
    assert digest(REPO/'lab/perp_schedule.py')==json.loads(DP.read_bytes())['legacy_scheduler_sha256']


def test_waiting_confirmation_plus_one_research_and_no_second_lane(env):
    root,task,*_=env;d.enqueue(root,BP,DP,confirmation(),NOW);d.enqueue(root,BP,DP,task,NOW)
    assert len(d.status(root,BP,DP)['open_tasks'])==2
    for extra in [dict(task,id='second',mechanism='other'),dict(confirmation(),id='second-confirm')]:
        before=(root/'state.json').read_bytes()
        with pytest.raises(ValueError):d.enqueue(root,BP,DP,extra,NOW)
        assert (root/'state.json').read_bytes()==before


@pytest.mark.parametrize('state_value',['RUNNING','UNKNOWN_INTERRUPTED'])
def test_unknown_and_running_block_old_and_new_writers(env,state_value):
    root,task,*_=env;d.enqueue(root,BP,DP,task,NOW)
    with s.locked(root,BP) as (_,_,state):state['tasks'][0].update(status=state_value,started_at=s.stamp(NOW))
    before=(root/'state.json').read_bytes()
    for fn in [lambda:d.claim(root,BP,DP,task['id'],NOW),lambda:d.install(root,BP,DP,NOW),lambda:s.claim(root,BP,task['id'],NOW)]:
        with pytest.raises(ValueError):fn()
    assert before==(root/'state.json').read_bytes()


def test_old_lock_blocks_new_install_and_claim(env):
    root,task,*_=env
    with s.locked(root,BP):
        with pytest.raises(BlockingIOError):d.enqueue(root,BP,DP,task,NOW)


def test_future_wait_unchanged_and_due_confirmation_preempts_exploration(env):
    root,task,*_=env;d.enqueue(root,BP,DP,confirmation(),NOW);d.enqueue(root,BP,DP,task,NOW)
    original=copy.deepcopy(s.read_status(root,BP)['tasks'][0])
    for moment in [datetime(2026,12,8,23,50,tzinfo=timezone.utc),datetime(2026,12,9,1,tzinfo=timezone.utc)]:
        with pytest.raises(ValueError,match='confirmation has priority'):d.claim(root,BP,DP,task['id'],moment)
    assert s.read_status(root,BP)['tasks'][0]==original
    with pytest.raises(ValueError,match='materialization'):d.claim(root,BP,DP,original['id'],NOW)


def test_missing_or_late_intent_blocks_and_deadline_cannot_be_crossed(env):
    root,task,*_=env;d.enqueue(root,BP,DP,task,NOW)
    with pytest.raises(FileNotFoundError):d.claim(root,BP,DP,task['id'],NOW)
    maintenance(env)
    with pytest.raises(ValueError,match='maintenance deadline'):d.claim(root,BP,DP,task['id'],NOW.replace(minute=50))
    receipt=maintenance(env);r=json.loads(receipt.read_bytes());r['pairs']['BTC/USDT:USDT']['status']='LATE';write(receipt,r)
    state_path=root.parent/'forward-signals/state.json';state=json.loads(state_path.read_bytes());next(iter(state['records'].values()))['receipt_sha256']=digest(receipt);write(state_path,state)
    with pytest.raises(ValueError,match='timely committed'):d.claim(root,BP,DP,task['id'],NOW)


def test_actual_timestamp_alias_future_and_source_relabelling_cannot_bypass(env):
    root,task,market,manifest=env
    for row in [dict(event_time='2026-09-10T00:00:00Z'),dict(event_time='2025-01-01T00:00:00Z',time='2026-09-10T00:00:00Z')]:
        market.write_text(json.dumps(row)+'\n');m=json.loads(manifest.read_bytes());m['files'][0]['sha256']=digest(market);write(manifest,m)
        task.update(data_sha256=digest(manifest),development_manifest_sha256=digest(manifest))
        with pytest.raises(ValueError,match='actual market timestamp'):d.enqueue(root,BP,DP,task,NOW)
    m=json.loads(manifest.read_bytes());m['files'][0]['role']='metadata';write(manifest,m);task.update(data_sha256=digest(manifest),development_manifest_sha256=digest(manifest))
    with pytest.raises(ValueError,match='actual market input'):d.enqueue(root,BP,DP,task,NOW)


def test_forward_paths_and_symlink_escape_rejected(env):
    root,task,market,manifest=env
    outside=write(root.parent/'data/incremental/future.json',dict(event_time='2025-01-01T00:00:00Z'))
    link=market.parent/'escape.json';link.symlink_to(outside)
    for name in [outside,link]:
        m=json.loads(manifest.read_bytes());m['files'][0].update(path=str(name),sha256=digest(name));write(manifest,m)
        task.update(data_sha256=digest(manifest),development_manifest_sha256=digest(manifest))
        with pytest.raises(ValueError,match='outside fixed development'):d.enqueue(root,BP,DP,task,NOW)


def test_claim_rechecks_source_sha_and_running_recheck_catches_drift(env):
    root,task,market,_=env;d.enqueue(root,BP,DP,task,NOW);maintenance(env)
    original=market.read_bytes();market.write_text(original.decode()+'\n')
    with pytest.raises(ValueError,match='SHA drift'):d.claim(root,BP,DP,task['id'],NOW)
    market.write_bytes(original);d.claim(root,BP,DP,task['id'],NOW)
    with s.locked(root,BP) as (_,_,state):
        actual=state['tasks'][0]
        assert d.validate_running_admission(root,state,actual,BP,DP,NOW)['status']=='RUNNING_ADMISSION_VERIFIED'
        with pytest.raises(ValueError,match='expired'):d.validate_running_admission(root,state,actual,BP,DP,NOW+timedelta(seconds=901))
        market.write_text('tampered')
        with pytest.raises(ValueError,match='SHA drift'):d.validate_running_admission(root,state,actual,BP,DP,NOW)


def terminal(root,task,now,status='COMPLETED'):
    with s.locked(root,BP) as (_,_,state):state['tasks'][-1].update(status='RUNNING',started_at=s.stamp(now))
    summary=write(root.parent/(task['id']+'.json'),dict(status=status,conclusion='Synthetic terminal, no market',
        task_binding=dict(task_id=task['id'],**{k:task[k] for k in ('code_sha256','data_sha256','policy_sha256')})))
    report=root.parent/(task['id']+'.md');report.write_text('Synthetic test evidence only\n')
    return s.finish(root,BP,task['id'],summary,report,now+timedelta(seconds=1))


def test_cumulative_daily_budget_and_terminal_evidence_unchanged(env):
    root,task,*_=env;spent=dict(task,id='prior',variants=8);d.enqueue(root,BP,DP,spent,NOW);terminal(root,spent,NOW)
    next_task=dict(task,id='next',variants=1);d.enqueue(root,BP,DP,next_task,NOW)
    before=(root/'state.json').read_bytes()
    with pytest.raises(ValueError,match='daily budget'):d.claim(root,BP,DP,next_task['id'],NOW)
    assert (root/'state.json').read_bytes()==before
    state=s.read_status(root,BP);Path(state['tasks'][0]['report']).write_text('changed')
    with pytest.raises(ValueError,match='terminal evidence SHA'):d.status(root,BP,DP)


def test_manifest_repack_and_rename_cannot_reset_experiment(env):
    root,task,_,manifest=env;d.enqueue(root,BP,DP,task,NOW);terminal(root,task,NOW)
    m=json.loads(manifest.read_bytes());m['unimportant_label']='renamed';other=write(manifest.parent/'renamed.json',m)
    repeat=dict(task,id='renamed',development_manifest_path=str(other),development_manifest_sha256=digest(other),data_sha256=digest(other))
    with pytest.raises(ValueError,match='already consumed'):d.enqueue(root,BP,DP,repeat,NOW)


def test_prepare_manifest_has_no_installation_requirement(env):
    root,task,*_=env
    assert d.validate_development_manifest(task['development_manifest_path'],task['data_sha256'],DP)['market_rows']==1


def test_completed_window_does_not_require_an_invented_new_observer_slot(env):
    root,task,*_=env;later=datetime(2026,12,10,0,38,tzinfo=timezone.utc)
    maintenance(env,later)
    (root.parent/'forward-signals/state.json').unlink()
    policy,_=s.load_policy(BP)
    proof=d.maintenance(root,policy,task,later,{'tasks':[]})
    assert proof['observer_required'] is False and len(proof['receipt_files'])==2
    with pytest.raises(FileNotFoundError):d.maintenance(root,policy,task,later,{'tasks':[dict(kind='confirmation',status='WAITING_DATA')]})


def test_metadata_cannot_point_at_repo_reports(env):
    root,task,_,manifest=env;m=json.loads(manifest.read_bytes())
    m['files'].append(dict(path=str(DP),sha256=digest(DP),role='metadata'));write(manifest,m)
    task.update(data_sha256=digest(manifest),development_manifest_sha256=digest(manifest))
    with pytest.raises(ValueError,match='outside fixed development'):d.enqueue(root,BP,DP,task,NOW)


def test_weekly_budget_and_every_third_terminal_review_survive(env):
    root,task,*_=env
    # Seed already-spent synthetic history under unchanged coordinator semantics.
    for index,count in enumerate((8,8,8,4)):
        prior=dict(task,id='spent-'+str(index),variants=count,mechanism='prior-'+str(index))
        d.enqueue(root,BP,DP,prior,NOW);previous=terminal(root,prior,NOW-timedelta(days=2)+timedelta(hours=index),status='BLOCKED_RUNTIME')
    upcoming=dict(task,id='after-history',variants=1)
    d.enqueue(root,BP,DP,upcoming,NOW)
    with pytest.raises(ValueError,match='weekly budget'):d.claim(root,BP,DP,upcoming['id'],NOW)
    # A separate state with three terminal failures also needs the review checkpoint.
    with s.locked(root,BP) as (_,_,state):
        state['tasks']=state['tasks'][:3]+state['tasks'][-1:]
    with pytest.raises(ValueError,match='review checkpoint'):d.claim(root,BP,DP,upcoming['id'],NOW)
