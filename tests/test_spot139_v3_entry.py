"""Synthetic-only parent/observer tests. No Freqtrade engine is imported or started."""
import importlib.util,json,sys,subprocess,fcntl
from pathlib import Path
from decimal import Decimal as D
import pytest
from lab.spot139_binding import sha,BindingError
from lab.spot139_report_v3 import create_model,RunReport,run_loop
from lab.spot139_model import Rule


def setup(tmp_path,monkeypatch):
    spec=importlib.util.spec_from_file_location('v3entry',Path(__file__).parents[1]/'scripts/run_spot139_v3.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    for name in ['OLD','V2','BUDGET']:monkeypatch.setattr(module,name,tmp_path/name)
    monkeypatch.setattr(module,'GLOBAL',tmp_path/'global.jsonl')
    for root in [module.OLD,module.V2]:root.mkdir();(root/'writer.lock').touch()
    Path(str(module.GLOBAL)+'.lock').touch()
    def ledger(path,count,key):path.write_text(''.join(json.dumps(dict(event=e,**{key:str(i)}))+'\n' for i in range(count) for e in ['RESERVED','SUCCEEDED']))
    ledger(module.OLD/'calls.jsonl',28,'key');ledger(module.V2/'calls.jsonl',2,'cost')
    checkpoint=dict(record_type='ISSUE139_SPOT_NATIVE_FIRST_BATCH_CHECKPOINT',historical_calls_sha256=sha(module.OLD/'calls.jsonl'),issue139_calls_sha256=sha(module.V2/'calls.jsonl'),old_consumed=28,new_reserved=2,total_consumed=30,global_limit=96)
    module.GLOBAL.write_text('\n'+json.dumps(checkpoint)+'\n\n')
    monkeypatch.setattr(module,'validate_sources',lambda m:True)
    monkeypatch.setattr(module.subprocess,'check_output',lambda args,**kw:'native\n' if 'rev-parse' in args else '')
    manifest=dict(protocol='ISSUE139_B_RESIDUAL_V3_EXECUTION',model='SpotResidualV3',mapper='ReconcilerV3',jobs=module.JOBS,native_commit='native',window=dict(start_hour=447072,end_hour_exclusive=464592),ancestor_sha256={str(p):sha(p) for p in [module.OLD/'calls.jsonl',module.V2/'calls.jsonl',module.GLOBAL]})
    path=tmp_path/'manifest.json';path.write_text(json.dumps(manifest))
    argv=['runner',str(path),'--manifest-sha256',sha(path),'--cost','base'];monkeypatch.setattr(sys,'argv',argv)
    return module,manifest,path,argv


def grant(module,path,argv):
    p=path.parent/'grant.json';p.write_text(json.dumps(dict(market_execution_authorized=True,manifest_sha256=sha(path),keys=module.KEYS,costs=['base','stress'],authorization_reference='SYNTHETIC TEST ONLY')))
    argv.extend(['--execute','--grant',str(p),'--grant-sha256',sha(p)])


def test_checkonly_and_grant_failure_do_not_create_budget(tmp_path,monkeypatch,capsys):
    m,_,path,argv=setup(tmp_path,monkeypatch);m.main()
    result=json.loads(capsys.readouterr().out);assert result['global_consumed']==30 and result['model']=='SpotResidualV3'
    assert not m.BUDGET.exists()
    argv.append('--execute')
    with pytest.raises(BindingError,match='grant'):m.main()
    assert not m.BUDGET.exists()


def test_cost_model_and_ancestor_drift_reject(tmp_path,monkeypatch):
    m,manifest,path,argv=setup(tmp_path,monkeypatch)
    changed=json.loads(json.dumps(manifest));changed['jobs'][1]['fee_each_side']='0.001'
    with pytest.raises(BindingError,match='binding'):m.preflight(changed)
    changed=json.loads(json.dumps(manifest));changed['model']='SpotReference'
    with pytest.raises(BindingError,match='binding'):m.preflight(changed)
    with (m.OLD/'calls.jsonl').open('a') as stream:stream.write(json.dumps(dict(event='RESERVED',key='unknown'))+'\n')
    with pytest.raises(BindingError,match='drift'):m.preflight(manifest)
    # Even when a fixture manifest accepts the new bytes, unresolved history rejects.
    manifest['ancestor_sha256'][str(m.OLD/'calls.jsonl')]=sha(m.OLD/'calls.jsonl')
    with pytest.raises(BindingError,match='unresolved'):m.preflight(manifest)


def test_cross_writer_lock_blocks_before_reservation(tmp_path,monkeypatch):
    m,_,path,argv=setup(tmp_path,monkeypatch);grant(m,path,argv)
    with (m.OLD/'writer.lock').open('r') as held:
        fcntl.flock(held,fcntl.LOCK_EX|fcntl.LOCK_NB)
        with pytest.raises(BlockingIOError):m.main()
    assert not (m.BUDGET/'calls.jsonl').exists()


def test_timeout_is_durable_consumed_and_stress_stops(tmp_path,monkeypatch):
    m,_,path,argv=setup(tmp_path,monkeypatch);grant(m,path,argv)
    calls=[]
    def timeout(cmd,**kw):
        calls.append(cmd);rows=m.events(m.BUDGET/'calls.jsonl')
        assert rows[-1]['event']=='RESERVED' and rows[-1]['total_consumed_after']==31
        assert len(kw['pass_fds'])==4 and kw['timeout']==180
        raise subprocess.TimeoutExpired(cmd,180)
    monkeypatch.setattr(m.subprocess,'run',timeout)
    with pytest.raises(subprocess.TimeoutExpired):m.main()
    assert [r['event'] for r in m.events(m.BUDGET/'calls.jsonl')]==['RESERVED','FAILED']
    with pytest.raises(BindingError,match='no retry'):m.main()
    argv[argv.index('--cost')+1]='stress'
    with pytest.raises(BindingError,match='no retry'):m.main()
    assert len(calls)==1


def test_pair_success_and_result_tampering_checked(tmp_path,monkeypatch):
    m,_,path,argv=setup(tmp_path,monkeypatch);grant(m,path,argv)
    argv[argv.index('--cost')+1]='stress'
    with pytest.raises(BindingError,match='base must succeed'):m.main()
    argv[argv.index('--cost')+1]='base'
    def success(cmd,**kw):
        cost=cmd[cmd.index('--cost')+1];key=m.KEYS[['base','stress'].index(cost)]
        m.dump(m.BUDGET/(cost+'-result.json'),dict(status='COMPLETED_V3_DEVELOPMENT_DIAGNOSTIC',key=key,modeled_net='-1'))
        return subprocess.CompletedProcess(cmd,0,'','')
    monkeypatch.setattr(m.subprocess,'run',success);m.main()
    assert m.events(m.BUDGET/'calls.jsonl')[-1]['event']=='SUCCEEDED'  # loss is not technical failure
    base=m.BUDGET/'base-result.json';raw=base.read_text();base.write_text('tampered')
    argv[argv.index('--cost')+1]='stress'
    with pytest.raises(BindingError,match='result changed'):m.main()
    base.write_text(raw);m.main()
    rows=m.events(m.BUDGET/'calls.jsonl');assert len(rows)==4 and rows[2]['total_consumed_after']==32
    with pytest.raises(BindingError,match='no retry'):m.main()


def test_public_worker_flag_has_no_native_access(tmp_path,monkeypatch):
    m,_,_,argv=setup(tmp_path,monkeypatch);argv.append('--worker');monkeypatch.delenv('SPOT139_V3_LOCK_FDS',raising=False)
    with pytest.raises(BindingError,match='no parent'):m.main()
    assert not m.BUDGET.exists()


def test_single_loop_collects_gates_snapshots_and_selects_model_without_native():
    r=Rule(D('.001'),D('.001'),D(5),D(1000),D('.000001'),D('.000001'),D('.01'))
    model=create_model({'BTC':r},dict(mode='B',fee_each_side='0.002',slippage_each_side='0.0012'))
    assert model.__class__.__name__=='SpotResidualV3' and model.fee==D('.002')
    bar=(D(100),D(101),D(99),D(100));hourly={'BTC':{h:(bar,True) for h in range(24,50) if h!=26}}
    class ObserverOnly:
        def apply(self,*args):raise AssertionError('ineligible synthetic history must not produce orders')
        def compare_model(self,model):pass
    report=RunReport(model);snapshots=[];result=run_loop(model,ObserverOnly(),hourly,{'BTC':{}},24,50,report,snapshots.append)
    assert len(snapshots)==26 and result['gate_ineligible_calendar_days']['BTC']==2
    assert result['orders']==[] and result['hours_observed']==26


def test_stale_grant_rejected_without_reservation(tmp_path,monkeypatch):
    m,_,path,argv=setup(tmp_path,monkeypatch);grant(m,path,argv)
    gp=Path(argv[argv.index('--grant')+1]);g=json.loads(gp.read_text());g['manifest_sha256']='0'*64;gp.write_text(json.dumps(g))
    argv[argv.index('--grant-sha256')+1]=sha(gp)
    with pytest.raises(BindingError,match='does not authorize'):m.main()
    assert not m.BUDGET.exists()


def test_controller_only_reporting_has_episodes_exit_causes_and_contributions():
    r=Rule(D('.001'),D('.001'),D(5),D(1000),D('.000001'),D('.000001'),D('.01'))
    model=create_model({'BTC':r,'ETH':r},dict(mode='B',fee_each_side='0.001',slippage_each_side='0.0006'))
    daily={s:{d:(D(100),D(101),D(99),D(100)) for d in range(-84,0)} for s in model.rules}
    for s in daily:daily[s][0]=(D(101),D(102),D(100),D(101))
    hourly={s:{} for s in model.rules}
    for s in hourly:
        for h in range(24,98):
            close=D(99 if h//24%2 else 101);hourly[s][h]=((D(100),D(102),D(98),close),True)
    class ControllerObserver:
        def apply(self,fill,allowed):assert (fill['symbol'],fill['hour']) in allowed
        def compare_model(self,model):pass
    report=RunReport(model);snapshots=[];result=run_loop(model,ControllerObserver(),hourly,daily,24,98,report,snapshots.append)
    assert len(result['orders'])==8 and len(result['episode_events'])==8 and len(snapshots)==74
    assert all('NONPOSITIVE_SIGNAL' in o['exit_causes'] for o in result['orders'] if o['side']=='sell')
    assert sum(v['realized'] for v in result['assets'].values())==model.realized
    assert sum(result['realized_by_month']['values'].values())==model.realized
    assert all(v['episode_starts']==2 and v['episode_ends']==2 for v in result['assets'].values())
    assert not result['independent_qualification']


def test_unresolved_suffix_and_missing_ledger_with_artifact_reject(tmp_path,monkeypatch):
    m,_,path,argv=setup(tmp_path,monkeypatch);m.BUDGET.mkdir();(m.BUDGET/'writer.lock').touch()
    row=dict(event='RESERVED',key=m.KEYS[0],cost='base',manifest_sha256=sha(path),grant_sha256='1'*64,previous_sha256='0'*64)
    (m.BUDGET/'calls.jsonl').write_text(json.dumps(row,sort_keys=True,separators=(',',':'))+'\n')
    with pytest.raises(BindingError,match='unresolved V3'):m.main()
    (m.BUDGET/'calls.jsonl').unlink();(m.BUDGET/'base-hourly.jsonl').write_text('{}\n')
    with pytest.raises(BindingError,match='no reset'):m.main()
