import json
from datetime import datetime,timedelta,timezone
from pathlib import Path
import pytest
from lab import perp_schedule as s

NOW=datetime(2026,9,8,17,tzinfo=timezone.utc)
SOURCE=Path(__file__).parents[1]/'docs/protocols/perp-autonomous-policy-v3.json'

@pytest.fixture
def env(tmp_path):
    policy=tmp_path/'policy.json';policy.write_bytes(SOURCE.read_bytes())
    bindings={}
    for name in ('strategy.py','cost.json','economic-protocol.json'):
        path=tmp_path/name;path.write_text('frozen fixture '+name);bindings[str(path)]=s.digest(path.read_bytes())
    path=tmp_path/'economic-protocol.json';path.write_bytes(s.canonical(dict(parent_protocol=str(tmp_path/'cost.json'))));bindings[str(path)]=s.digest(path.read_bytes())
    registration=tmp_path/'registration.json';confirmation=tmp_path/'confirmation.json';contract=tmp_path/'contract.json'
    confirmation.write_bytes(s.canonical(dict(protocol_id='PERP_INDEPENDENT_CONFIRMATION_V_TEST',
        candidate_selection=dict(selection_for_this_version=dict(candidate_id='fixture-candidate',variant='fixed-variant',
          strategy_path=str(tmp_path/'strategy.py'),strategy_sha256=bindings[str(tmp_path/'strategy.py')],
          candidate_protocol_path=str(tmp_path/'economic-protocol.json'),candidate_protocol_sha256=bindings[str(tmp_path/'economic-protocol.json')])),
        candidate_registration_path=str(registration),window=dict(kind='GENUINELY_FUTURE',
        start_inclusive='2026-09-08T10:00:00Z',end_exclusive='2026-09-08T16:00:00Z'))))
    registration.write_bytes(s.canonical(dict(candidate_id='fixture-candidate',variant='fixed-variant',
        strategy_sha256=bindings[str(tmp_path/'strategy.py')],cost_sha256=bindings[str(tmp_path/'cost.json')],
        candidate_protocol_sha256=bindings[str(tmp_path/'economic-protocol.json')],code_bindings=bindings,
        confirmation_protocol_sha256=s.digest(confirmation.read_bytes()),window=json.loads(confirmation.read_bytes())['window'])))
    contract.write_bytes(s.canonical(dict(kind='acceptance',candidate_id='fixture-candidate',variant='fixed-variant',
        registration_path=str(registration),registration_sha256=s.digest(registration.read_bytes()),
        confirmation_protocol_path=str(confirmation),confirmation_protocol_sha256=s.digest(confirmation.read_bytes()),
        score_economics=False,window_start='2026-09-08T10:00:00Z',window_end_exclusive='2026-09-08T16:00:00Z',earliest_ready_at='2026-09-08T16:10:00Z')))
    return tmp_path/'runtime',policy,contract

def task(env,name,kind='research',variants=1,**updates):
    root,policy,contract=env
    bindings={str(policy.parent/'strategy.py'):s.digest((policy.parent/'strategy.py').read_bytes())}
    value=dict(id=name,kind=kind,mechanism='test-'+kind,code_sha256=s.digest(json.dumps(bindings,sort_keys=True,default=str).encode()),
      data_sha256=s.digest(name.encode()),policy_sha256=s.digest(policy.read_bytes()),
      hypothesis='One frozen comparison',variants=variants,max_seconds=100)
    if kind in {'acceptance','confirmation'}:
        if kind=='confirmation':contract=policy.parent/'confirmation.json'
        value.update(variants=0,native_calls=1,economic_selection=False,changes_economic_rules=False,
          fixed_candidate=True,candidate_sha256=s.digest((policy.parent/'registration.json').read_bytes()),frozen_contract_path=str(contract),
          frozen_contract_sha256=s.digest(contract.read_bytes()),
          fixed_input_window=dict(start='2026-09-08T10:00:00Z',end_exclusive='2026-09-08T16:00:00Z'))
    value.update(updates);return value

def complete(env,item,now=NOW,status='COMPLETED'):
    root,policy,_=env
    s.enqueue(root,policy,item,now);s.claim(root,policy,item['id'],now)
    return finish(env,item,now,status)

def finish(env,item,now,status):
    root,policy,_=env
    summary=policy.parent/(item['id']+'.json');report=policy.parent/(item['id']+'.md')
    summary.write_bytes(s.canonical(dict(status=status,conclusion='Observed technical result',
      task_binding=dict(task_id=item['id'],**{k:item[k] for k in ['code_sha256','data_sha256','policy_sha256']}))))
    report.write_text('Actual scoped fixture report\n')
    return s.finish(root,policy,item['id'],summary,report,now=now+timedelta(seconds=1))

def review(previous):
    return dict(previous_task_id=previous['id'],previous_summary_sha256=previous['summary_sha256'],
      previous_wall_seconds=previous['claimed_to_report_seconds'],information_value='One distinct fixed falsifiable contrast',stop_condition='Stop on unsupported result')

def test_round_four_requires_review_but_is_not_hard_block(env):
    root,policy,_=env
    for i in range(3):previous=complete(env,task(env,'r'+str(i)),NOW+timedelta(minutes=i))
    item=task(env,'fourth');s.enqueue(root,policy,item,NOW+timedelta(minutes=4))
    before=(root/'state.json').read_bytes()
    with pytest.raises(ValueError,match='review checkpoint'):s.claim(root,policy,'fourth',NOW+timedelta(minutes=4))
    assert before==(root/'state.json').read_bytes()
    with s.locked(root,policy) as (_,_,state):state['tasks'][-1]['review_checkpoint']=review(previous)
    assert s.claim(root,policy,'fourth',NOW+timedelta(minutes=4))['status']=='RUNNING'

def test_daily_eight_remains_and_acceptance_does_not_spend_exploration(env):
    root,policy,_=env
    complete(env,task(env,'eight',variants=8))
    a=complete(env,task(env,'accept',kind='acceptance'))
    assert a['variants']==0
    s.enqueue(root,policy,task(env,'ninth'),NOW+timedelta(minutes=1))
    with pytest.raises(ValueError,match='daily budget'):s.claim(root,policy,'ninth',NOW+timedelta(minutes=1))
    assert sum(t['variants'] for t in s.read_status(root,policy)['tasks'] if t.get('started_at') and t['kind']=='research')==8

def test_weekly_28_preserved_without_weekly_round_block(env):
    root,policy,_=env
    for day,count in enumerate([8,8,8,4]):
        previous=complete(env,task(env,'day'+str(day),variants=count,**(dict(review_checkpoint=review(previous)) if day==3 else {})),NOW+timedelta(days=day))
    s.enqueue(root,policy,task(env,'twentyninth'),NOW+timedelta(days=3,minutes=1))
    with pytest.raises(ValueError,match='weekly budget'):s.claim(root,policy,'twentyninth',NOW+timedelta(days=3,minutes=1))

def test_economic_selection_and_large_acceptance_rejected(env):
    root,policy,_=env
    for updates in [dict(economic_selection=True),dict(changes_economic_rules=True),dict(fixed_candidate=False),dict(native_calls=2)]:
        with pytest.raises(ValueError,match='economic selection'):s.enqueue(root,policy,task(env,'bad','acceptance',**updates),NOW)
    with pytest.raises(ValueError,match='wall-time'):s.enqueue(root,policy,task(env,'long','acceptance',max_seconds=1801),NOW)
    assert s.read_status(root,policy).get('tasks',[])==[]

def test_acceptance_one_normal_and_one_specific_technical_retry(env):
    root,policy,_=env
    first=task(env,'first','acceptance');complete(env,first,status='BLOCKED_RUNTIME')
    retry=task(env,'retry','acceptance',data_sha256=first['data_sha256'],retry_of='first',technical_retry_reason='Fixed documented export-directory failure')
    complete(env,retry,NOW+timedelta(minutes=1),status='BLOCKED_RUNTIME')
    third=task(env,'third','acceptance',code_sha256='b'*64,retry_of='retry',technical_retry_reason='another patch')
    s.enqueue(root,policy,third,NOW+timedelta(minutes=2))
    with pytest.raises(ValueError,match='call budget'):s.claim(root,policy,'third',NOW+timedelta(minutes=2))

def test_successful_acceptance_cannot_be_relabelled_as_another_normal_run(env):
    root,policy,_=env
    complete(env,task(env,'first','acceptance'))
    s.enqueue(root,policy,task(env,'renamed','acceptance',code_sha256='b'*64),NOW+timedelta(minutes=1))
    with pytest.raises(ValueError,match='specific technical retry'):s.claim(root,policy,'renamed',NOW+timedelta(minutes=1))

def test_acceptance_cumulative_wall_reservation(env):
    root,policy,_=env
    p=json.loads(policy.read_bytes());p['acceptance_budget']['max_reserved_wall_seconds_per_candidate']=2000;policy.write_bytes(s.canonical(p))
    complete(env,task(env,'first','acceptance',max_seconds=1200),status='BLOCKED_RUNTIME')
    retry=task(env,'retry','acceptance',max_seconds=1200,retry_of='first',technical_retry_reason='specific fix')
    s.enqueue(root,policy,retry,NOW+timedelta(minutes=1))
    with pytest.raises(ValueError,match='cumulative wall-time'):s.claim(root,policy,'retry',NOW+timedelta(minutes=1))

def test_confirmation_one_time_and_never_before_fixed_window_end(env):
    root,policy,_=env
    complete(env,task(env,'eight',variants=8))
    fixed=dict(start='2026-09-08T10:00:00Z',end_exclusive='2026-09-09T00:00:00Z')
    path=policy.parent/'confirmation.json';contract=json.loads(path.read_bytes());contract['window']['end_exclusive']=fixed['end_exclusive'];path.write_bytes(s.canonical(contract))
    path=policy.parent/'registration.json';reg=json.loads(path.read_bytes());reg['window']=contract['window'];reg['confirmation_protocol_sha256']=s.digest((policy.parent/'confirmation.json').read_bytes());path.write_bytes(s.canonical(reg))
    future=task(env,'confirm','confirmation',fixed_input_window=fixed)
    s.enqueue(root,policy,future,NOW)
    with pytest.raises(ValueError,match='natural wait'):s.claim(root,policy,'confirm',NOW)
    later=NOW+timedelta(days=1);s.claim(root,policy,'confirm',later);finish(env,future,later,'COMPLETED')
    repeated=task(env,'confirm-again','confirmation',code_sha256='b'*64,fixed_input_window=future['fixed_input_window'])
    s.enqueue(root,policy,repeated,later+timedelta(minutes=1))
    with pytest.raises(ValueError,match='already consumed'):s.claim(root,policy,repeated['id'],later+timedelta(minutes=1))

def test_future_contract_cannot_be_claimed_without_actual_preflight(env):
    root,policy,_=env
    item=task(env,'future','acceptance',status='WAITING_DATA',data_binding_role='FUTURE_INPUT_CONTRACT_PENDING')
    s.enqueue(root,policy,item,NOW)
    with pytest.raises(ValueError,match='materialize'):s.ready(root,policy,'future')
    pre=actual_preflight(env,item)
    actual=s.materialize(root,policy,'future',pre,NOW)
    assert actual['preparation_binding']['data_sha256']==item['data_sha256'] and actual['data_sha256']==json.loads(pre.read_bytes())['data_sha256']
    assert s.claim(root,policy,'future',NOW)['status']=='RUNNING'


def actual_preflight(env,item):
    _,policy,_=env;folder=policy.parent;snapshot=folder/'intent-snapshot.json';snapshot.write_text('{"fixture":"no market"}\n')
    code=folder/'strategy.py';bindings={str(code):s.digest(code.read_bytes())}
    manifest=dict(identity=dict(registration_sha256=item['candidate_sha256']),
        start=item['fixed_input_window']['start'],end=item['fixed_input_window']['end_exclusive'],
        source_files={str(snapshot):s.digest(snapshot.read_bytes())},
        intent_snapshot_path=str(snapshot),intent_snapshot_sha256=s.digest(snapshot.read_bytes()))
    source=folder/'input-manifest.json';source.write_bytes(s.canonical(manifest))
    pre=folder/'preflight.json';pre.write_bytes(s.canonical(dict(status='READY_NATIVE_ACCEPTANCE',
        source_manifest=manifest,input_manifest_path=str(source),code_bindings=bindings,
        code_sha256=item['code_sha256'],data_sha256=s.digest(source.read_bytes()),policy_sha256=item['policy_sha256'])))
    return pre


@pytest.mark.parametrize('kind',['acceptance','confirmation'])
def test_task_cannot_shorten_real_contract_or_invent_candidate(env,kind):
    root,policy,_=env
    for updates in (dict(fixed_input_window=dict(start='2026-09-08T10:00:00Z',end_exclusive='2026-09-08T12:00:00Z')),
                    dict(candidate_sha256='f'*64)):
        with pytest.raises(ValueError,match='window differs|SHA'):
            s.enqueue(root,policy,task(env,'bad-'+kind,kind,**updates),NOW)
    assert s.read_status(root,policy).get('tasks',[])==[]


def test_confirmation_equivalent_timezone_does_not_reset_budget(env):
    root,policy,_=env
    complete(env,task(env,'first','confirmation'))
    item=task(env,'offset','confirmation',fixed_input_window=dict(start='2026-09-08T18:00:00+08:00',end_exclusive='2026-09-08T16:00:00+00:00'))
    queued=s.enqueue(root,policy,item,NOW)
    assert queued['fixed_input_window']==dict(start='2026-09-08T10:00:00+00:00',end_exclusive='2026-09-08T16:00:00+00:00')
    before=(root/'state.json').read_bytes()
    with pytest.raises(ValueError,match='already consumed'):s.claim(root,policy,item['id'],NOW)
    assert before==(root/'state.json').read_bytes()


def test_registration_metadata_does_not_buy_another_acceptance(env):
    root,policy,contract=env
    first=complete(env,task(env,'first','acceptance'))
    registration=policy.parent/'registration.json';reg=json.loads(registration.read_bytes());reg['annotation']='metadata-only rename';registration.write_bytes(s.canonical(reg))
    value=json.loads(contract.read_bytes());value['registration_sha256']=s.digest(registration.read_bytes());contract.write_bytes(s.canonical(value))
    queued=s.enqueue(root,policy,task(env,'renamed','acceptance'),NOW)
    assert queued['candidate_sha256']!=first['candidate_sha256'] and queued['candidate_budget_key']==first['candidate_budget_key']
    with pytest.raises(ValueError,match='specific technical retry'):s.claim(root,policy,queued['id'],NOW)


def test_retry_cannot_change_frozen_data_or_purpose(env):
    root,policy,contract=env
    first=task(env,'first','acceptance');complete(env,first,status='BLOCKED_RUNTIME')
    changed=task(env,'changed','acceptance',retry_of='first',technical_retry_reason='Documented technical fix')
    s.enqueue(root,policy,changed,NOW)
    with pytest.raises(ValueError,match='specific technical retry'):s.claim(root,policy,'changed',NOW)
    # Isolate the purpose-change attempt; retain the first consumed call.
    with s.locked(root,policy) as (_,_,state):state['tasks'].pop()
    content=json.loads(contract.read_bytes());content['purpose']='Different purpose';contract.write_bytes(s.canonical(content))
    changed=task(env,'changed-purpose','acceptance',data_sha256=first['data_sha256'],code_sha256='b'*64,retry_of='first',technical_retry_reason='Documented technical fix')
    s.enqueue(root,policy,changed,NOW)
    with pytest.raises(ValueError,match='specific technical retry'):s.claim(root,policy,changed['id'],NOW)


def test_candidate_code_drift_rejects_before_claim_without_state_change(env):
    root,policy,_=env
    item=task(env,'candidate','acceptance');s.enqueue(root,policy,item,NOW)
    before=(root/'state.json').read_bytes();(policy.parent/'strategy.py').write_text('changed economic conditions')
    with pytest.raises(ValueError,match='SHA drift'):s.claim(root,policy,item['id'],NOW)
    assert before==(root/'state.json').read_bytes()


def test_registration_cannot_relabel_another_bound_hash_as_cost(env):
    root,policy,contract=env
    path=policy.parent/'registration.json';reg=json.loads(path.read_bytes());reg['cost_sha256']=reg['strategy_sha256'];path.write_bytes(s.canonical(reg))
    value=json.loads(contract.read_bytes());value['registration_sha256']=s.digest(path.read_bytes());contract.write_bytes(s.canonical(value))
    with pytest.raises(ValueError,match='SHA drift'):s.enqueue(root,policy,task(env,'mislabel-cost','acceptance'),NOW)


def test_confirmation_contract_cannot_be_classified_acceptance(env):
    root,policy,_=env;contract=policy.parent/'confirmation.json'
    item=task(env,'false-acceptance','acceptance',frozen_contract_path=str(contract),frozen_contract_sha256=s.digest(contract.read_bytes()))
    with pytest.raises(ValueError,match='non-economic acceptance'):s.enqueue(root,policy,item,NOW)


def test_review_counts_failed_rounds_across_day_boundary(env):
    root,policy,_=env
    for index,status in enumerate(('COMPLETED','BLOCKED_DATA','BLOCKED_RUNTIME')):
        previous=complete(env,task(env,'prior'+str(index)),NOW+timedelta(days=index),status)
    later=NOW+timedelta(days=3);item=task(env,'fourth');s.enqueue(root,policy,item,later)
    with pytest.raises(ValueError,match='review checkpoint'):s.claim(root,policy,item['id'],later)
    with s.locked(root,policy) as (_,_,state):state['tasks'][-1]['review_checkpoint']=review(previous)
    assert s.claim(root,policy,item['id'],later)['status']=='RUNNING'


def test_actual_preflight_source_drift_never_clears_wait_or_starts_writer(env):
    root,policy,_=env
    item=task(env,'future','acceptance',status='WAITING_DATA',data_binding_role='FUTURE_INPUT_CONTRACT_PENDING')
    s.enqueue(root,policy,item,NOW);pre=actual_preflight(env,item);before=(root/'state.json').read_bytes()
    source=policy.parent/'intent-snapshot.json';original=source.read_bytes();source.write_text('changed')
    with pytest.raises(ValueError,match='SHA drift'):s.materialize(root,policy,item['id'],pre,NOW)
    assert before==(root/'state.json').read_bytes()
    source.write_bytes(original);s.materialize(root,policy,item['id'],pre,NOW);before=(root/'state.json').read_bytes();source.write_text('changed after materialization')
    with pytest.raises(ValueError,match='SHA drift'):s.claim(root,policy,item['id'],NOW)
    assert before==(root/'state.json').read_bytes()


def test_acceptance_waits_for_contract_publication_delay(env):
    root,policy,_=env;at=NOW.replace(hour=16,minute=5);item=task(env,'waiting','acceptance')
    s.enqueue(root,policy,item,at)
    with pytest.raises(ValueError,match='natural wait'):s.claim(root,policy,item['id'],at)
