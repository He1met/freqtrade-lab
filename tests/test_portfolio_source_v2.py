import json
from pathlib import Path
import pytest
from lab.portfolio_source import SourceError,digest,write_json,exclusive
from scripts import capture_portfolio_source_v2 as cli


def setup(tmp_path,monkeypatch):
    old=tmp_path/'old';old.mkdir()
    parent=dict(status='BLOCKED_DATA',attempts=[{'number':n} for n in range(1,38)],charged_bytes=7697705,root=str(old))
    bp=tmp_path/'acquisition-budget.json';write_json(bp,parent)
    ledger=tmp_path/'ledger';ledger.write_text('{}\n')
    c=dict(exchange='binance',instrument_type='USDT_PERPETUAL',symbols=['BTCUSDT','ETHUSDT'],
           start='2023-11-01T00:00:00Z',training_start='2024-08-01T00:00:00Z',end_exclusive='2025-01-01T00:00:00Z',
           registry=str(ledger),parent_budget_path=str(bp),parent_budget_sha256=digest(bp.read_bytes()),
           parent_seconds_charged=130,preparation_authorization='prepare',authorization='specific-approved-v2',
           output_root=str(old/'continuation-v2'),budget_path=str(tmp_path/'acquisition-continuation-v2.json'))
    cp=tmp_path/'contract';sp=tmp_path/'scope';write_json(cp,c)
    write_json(sp,dict(ledger_sha256=digest(ledger.read_bytes()),protections=[],unresolved_candidate_overlap=False))
    monkeypatch.setattr(cli,'CONTRACT',cp);monkeypatch.setattr(cli,'SCOPE',sp)
    manifest=tmp_path/'manifest';cli.prepare(manifest)
    return c,bp,ledger,manifest


@pytest.mark.parametrize('drift',[False,True])
def test_full_capture_lock_funding_first_stop_parent_unchanged(tmp_path,monkeypatch,capsys,drift):
    c,bp,ledger,manifest=setup(tmp_path,monkeypatch);before=bp.read_bytes();calls=[]
    class Fake:
        def __init__(self,budget,root):self.budget=budget
        def get(self,kind,params):
            # The full capture, not just activation, owns the V1 acquisition lock.
            with pytest.raises(SourceError,match='lock held'):
                with exclusive(str(bp)+'.lock'):pass
            assert json.loads(ledger.read_text().splitlines()[-1])['issue']==123
            calls.append(kind);row=self.budget.reserve(kind,params);self.budget.finish(row,size=1,status=200)
            if kind=='exchangeInfo':return {'symbols':[{'symbol':s,'contractType':'PERPETUAL','onboardDate':0} for s in c['symbols']]}
            if kind=='fundingInfo':return []
            assert kind=='fundingRate'
            if drift:manifest.write_text(manifest.read_text()+'\n')
            return [{'symbol':'BTCUSDT','fundingTime':params['startTime'],'fundingRate':'.01','markPrice':''}]
    monkeypatch.setattr(cli,'Fetcher',Fake)
    assert cli.capture(manifest)==2
    assert calls==['exchangeInfo','fundingInfo','fundingRate']
    q=json.loads((Path(c['output_root'])/'qc-v2-receipt.json').read_text())
    assert q['status']==('CONTROL_INTEGRITY' if drift else 'BLOCKED_DATA')
    assert q['requests_new']==3 and q['requests_cumulative']==40
    assert q['charged_bytes_cumulative']==7697708 and not q['executable_source_published']
    assert bp.read_bytes()==before
    cumulative=json.loads(Path(c['budget_path']).read_text())
    assert cumulative['attempts'][:37]==json.loads(before)['attempts']
    with pytest.raises(SourceError):cli.capture(manifest)


def test_other_capture_worker_lock_prevents_any_activation_or_get(tmp_path,monkeypatch,capsys):
    c,bp,ledger,manifest=setup(tmp_path,monkeypatch);before=ledger.read_bytes()
    def forbidden(*a):pytest.fail('second worker got to network')
    monkeypatch.setattr(cli,'Fetcher',forbidden)
    with exclusive(str(bp)+'.lock'):
        with pytest.raises(SourceError,match='lock held'):cli.capture(manifest)
    assert not Path(c['budget_path']).exists() and not Path(c['output_root']).exists()
    assert ledger.read_bytes()==before


def test_parent_drift_before_capture_prevents_registration(tmp_path,monkeypatch,capsys):
    c,bp,ledger,manifest=setup(tmp_path,monkeypatch);before=ledger.read_bytes();bp.write_text(bp.read_text()+'\n')
    with pytest.raises(SourceError,match='parent budget'):cli.capture(manifest)
    assert ledger.read_bytes()==before and not Path(c['budget_path']).exists()
