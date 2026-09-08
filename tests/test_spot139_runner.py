"""Parent authorization/reservation checks; real native integration is separate."""
import importlib.util,json,sys,subprocess
from pathlib import Path
import pytest
from lab.spot139_binding import sha,BindingError


def runner(tmp_path,monkeypatch):
    spec=importlib.util.spec_from_file_location('spot_runner',Path(__file__).parents[1]/'scripts/run_spot139_native.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    monkeypatch.setattr(module,'BUDGET',tmp_path/'budget')
    monkeypatch.setattr(module,'validate_sources',lambda m:True)
    monkeypatch.setattr(module.subprocess,'check_output',lambda args,**kw:'native\n' if 'rev-parse' in args else '')
    manifest=tmp_path/'manifest.json';manifest.write_text(json.dumps(dict(protocol='ISSUE139_SPOT_NATIVE_MAPPING_V2',native_commit='native')))
    argv=['runner',str(manifest),'--manifest-sha256',sha(manifest),'--cost','base']
    monkeypatch.setattr(sys,'argv',argv)
    return module,argv,manifest


def test_execute_without_grant_and_worker_bypass_have_no_reservation(tmp_path,monkeypatch):
    module,argv,_=runner(tmp_path,monkeypatch)
    argv.append('--execute')
    with pytest.raises(BindingError,match='grant required'):module.main()
    assert not module.BUDGET.exists()
    argv.extend(['--worker-output',str(tmp_path/'out')])
    monkeypatch.delenv('SPOT139_RESERVATION_FD',raising=False)
    with pytest.raises(BindingError,match='no parent reservation'):module.main()
    assert not module.BUDGET.exists()


def test_native_timeout_consumes_slot_and_prevents_retry(tmp_path,monkeypatch):
    module,argv,manifest=runner(tmp_path,monkeypatch)
    grant=tmp_path/'grant';grant.write_text(json.dumps(dict(market_execution_authorized=True,manifest_sha256=sha(manifest),costs=['base','stress'],authorization_reference='SYNTHETIC TEST GRANT')))
    argv.extend(['--execute','--grant',str(grant),'--grant-sha256',sha(grant)])
    calls=[]
    def timeout(cmd,**kw):
        calls.append(kw)
        rows=[json.loads(x) for x in (module.BUDGET/'calls.jsonl').read_text().splitlines()]
        assert rows[-1]['event']=='RESERVED' and kw['timeout']==180 and kw['pass_fds']
        raise subprocess.TimeoutExpired(cmd,180)
    monkeypatch.setattr(module.subprocess,'run',timeout)
    with pytest.raises(subprocess.TimeoutExpired):module.main()
    rows=[json.loads(x) for x in (module.BUDGET/'calls.jsonl').read_text().splitlines()]
    assert [x['event'] for x in rows]==['RESERVED','FAILED'] and rows[-1]['economic_result'] is None
    with pytest.raises(BindingError,match='duplicate'):module.main()
    assert len(calls)==1
