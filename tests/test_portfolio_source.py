import json
from pathlib import Path
import pytest
from lab.portfolio_source import (Budget, SourceError, check_scope, collect, digest,
                                  qc_summary, register, validate_rows)


LIMITS = dict(gets=2, response_bytes=100, total_bytes=150, seconds=30)


def test_budget_reserves_before_io_and_cannot_reset_new_root(tmp_path):
    path=tmp_path/'budget.json'
    b=Budget(path,tmp_path/'a',LIMITS,now=lambda:10)
    row=b.reserve('klines',{})
    assert json.loads(path.read_text())['charged_bytes']==100
    with pytest.raises(SourceError,match='byte budget'): b.reserve('klines',{})
    with pytest.raises(SourceError,match='already started'): Budget(path,tmp_path/'b',LIMITS)
    b.finish(row,size=30,status=200)
    b.reserve('klines',{})
    with pytest.raises(SourceError,match='GET budget'): b.reserve('klines',{})


def test_time_budget(tmp_path):
    now=[0]
    b=Budget(tmp_path/'b',tmp_path/'r',LIMITS,now=lambda:now[0])
    now[0]=30
    with pytest.raises(SourceError,match='wall-clock'):b.reserve('klines',{})
    assert b.state['attempts']==[]


def scope_fixture():
    c=dict(start='2020-04-02T00:00:00Z',end_exclusive='2023-01-01T00:00:00Z',
           exchange='binance',instrument_type='USDT_PERPETUAL',symbols=['BTCUSDT','ETHUSDT'])
    r=dict(scope='EXACT_DOMAIN',exchange='okx',instrument_type='SPOT',symbols=['BTCUSDT'],
           start='2021-01-01T00:00:00Z',end_exclusive='2022-01-01T00:00:00Z',record_lines=[63])
    raw=b'{}\n'
    s=dict(ledger_sha256=digest(raw),protections=[r],unresolved_candidate_overlap=False)
    return c,s,raw


def test_scope_source_local_not_cross_domain_and_global_blocks_warmup():
    c,s,raw=scope_fixture()
    check_scope(c,s,raw)
    s['protections'][0].update(scope='GLOBAL',start='2020-12-01T00:00:00Z',end_exclusive='2021-01-01T00:00:00Z')
    with pytest.raises(SourceError,match='collision'):check_scope(c,s,raw)
    s['protections'][0]['end_exclusive']=c['start']
    check_scope(c,s,raw)
    with pytest.raises(SourceError,match='changed'):check_scope(c,s,raw+b'{}\n')
    s['unresolved_candidate_overlap']=True
    with pytest.raises(SourceError,match='unresolved'):check_scope(c,s,raw)


def test_registration_pre_network_one_time(tmp_path):
    c,s,raw=scope_fixture();c.update(training_start='2021-01-01T00:00:00Z',authorization='review')
    ledger=tmp_path/'ledger';ledger.write_bytes(raw)
    register(c,s,ledger,'a'*64)
    records=[json.loads(x) for x in ledger.read_text().splitlines()]
    assert records[-1]['purpose']=='EXPLORATORY_TRAINING'
    with pytest.raises(SourceError,match='changed'):register(c,s,ledger,'a'*64)


def candle(t):return [t,'10','12','9','11','1',t+3599999]


class Pages:
    def __init__(self,pages):self.pages=iter(pages);self.calls=[]
    def get(self,kind,params):self.calls.append(params);return next(self.pages)


def test_pagination_inclusive_end_and_monotonic_cursor():
    rows=[candle(x*3600000) for x in range(1501)]
    f=Pages([rows[:1500],rows[1500:]])
    assert collect(f,'klines','BTCUSDT',0,1501*3600000)==rows
    assert f.calls[1]['startTime']==rows[1499][0]+1
    assert f.calls[0]['endTime']==1501*3600000-1


@pytest.mark.parametrize('rows',[[candle(3600000)],[candle(0),candle(0)],[candle(7200000)],[]])
def test_gap_duplicate_outside_or_empty_refuses_partial(rows):
    with pytest.raises(SourceError):collect(Pages([rows]),'klines','BTCUSDT',0,7200000)


def test_missing_associated_mark_and_invalid_ohlc():
    with pytest.raises(SourceError,match='associated mark'):
        validate_rows([dict(fundingTime=0,fundingRate='0.1')],'fundingRate',0,3600000)
    x=candle(0);x[2]='8'
    with pytest.raises(SourceError,match='OHLC'):validate_rows([x],'klines',0,3600000)


def test_funding_times_unchanged_tail_confirmation_and_unknown_schedule():
    row=dict(fundingTime=123,fundingRate='-0.01',markPrice='10',symbol='BTCUSDT')
    f=Pages([[row],[]]);fund=collect(f,'fundingRate','BTCUSDT',0,3600000)
    assert f.calls[1]['startTime']==124
    q=qc_summary({'BTCUSDT':dict(klines=[candle(0)],markPriceKlines=[candle(0)],fundingRate=fund)},0,3600000)
    assert q['status']=='BLOCKED_DATA' and not q['executable_source_published']
    assert q['economic_result'] is None
    with pytest.raises(SourceError,match='tail'):
        collect(Pages([[row],[dict(row,fundingTime=456)]]),'fundingRate','BTCUSDT',0,3600000)


def test_http429_retains_reservation_and_never_retries(tmp_path):
    import urllib.error
    from lab.portfolio_source import Fetcher
    root=tmp_path/'root';root.mkdir();(root/'raw').mkdir()
    b=Budget(tmp_path/'budget',root,LIMITS)
    class Fail:
        calls=0
        def open(self,*a,**k):
            self.calls+=1
            raise urllib.error.HTTPError('public',429,'limited',{'Retry-After':'60'},None)
    f=Fetcher(b,root);f.opener=Fail()
    with pytest.raises(SourceError):f.get('klines',{})
    assert f.opener.calls==1
    state=json.loads(b.path.read_text())
    assert state['attempts'][0]['status']==429 and state['attempts'][0]['retry_after']=='60'
    assert state['charged_bytes']==100
    assert list((root/'raw').iterdir())==[]


def test_response_ceiling_not_overread_and_no_publication(tmp_path):
    from lab.portfolio_source import Fetcher
    root=tmp_path/'root';root.mkdir();(root/'raw').mkdir()
    b=Budget(tmp_path/'budget',root,LIMITS)
    class Response:
        status=200;headers={};read_bytes=0
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def read1(self,n):self.read_bytes+=n;return b'x'*n
    response=Response()
    class Open:
        def open(self,*a,**k):return response
    f=Fetcher(b,root);f.opener=Open()
    with pytest.raises(SourceError):f.get('klines',{})
    assert response.read_bytes==100
    assert list((root/'raw').iterdir())==[]


def test_redirect_cannot_create_hidden_request():
    from lab.portfolio_source import NoRedirect
    with pytest.raises(SourceError,match='redirect'):
        NoRedirect().redirect_request(None,None,302,'',{},'https://other.example')


def test_cli_manifest_drift_blocks_before_budget_or_get(tmp_path,monkeypatch):
    from scripts import capture_portfolio_source as cli
    from lab.portfolio_source import write_json
    path=tmp_path/'manifest.json'
    write_json(path,dict(files={f:'0'*64 for f in cli.FILES}))
    with pytest.raises(SourceError,match='drift'):cli.capture(path)


def test_request_deadline_covers_non_socket_wait():
    import time
    from lab.portfolio_source import request_deadline
    with pytest.raises(SourceError,match='deadline'):
        with request_deadline(.01):time.sleep(.1)


def test_actual_entrypoint_registers_before_get_and_failure_never_publishes(tmp_path,monkeypatch,capsys):
    from scripts import capture_portfolio_source as cli
    from lab.portfolio_source import write_json
    c,s,raw=scope_fixture()
    ledger=tmp_path/'ledger';ledger.write_bytes(raw)
    c.update(training_start='2021-01-01T00:00:00Z',authorization='review',registry=str(ledger),
             output_root=str(tmp_path/'source'),budget_path=str(tmp_path/'budget'),limits=LIMITS)
    cp=tmp_path/'contract';sp=tmp_path/'scope'
    write_json(cp,c);write_json(sp,s)
    monkeypatch.setattr(cli,'CONTRACT',cp);monkeypatch.setattr(cli,'SCOPE',sp)
    class FailingFetcher:
        def __init__(self,budget,root):self.budget=budget
        def get(self,endpoint,params):
            assert json.loads(ledger.read_text().splitlines()[-1])['purpose']=='EXPLORATORY_TRAINING'
            row=self.budget.reserve(endpoint,params)
            self.budget.finish(row,size=100,status=418)
            raise SourceError('HTTP 418')
    monkeypatch.setattr(cli,'Fetcher',FailingFetcher)
    manifest=tmp_path/'manifest';cli.prepare(manifest)
    assert cli.capture(manifest)==2
    root=Path(c['output_root']);receipt=json.loads((root/'qc-receipt.json').read_text())
    assert receipt['requests']==1 and receipt['status']=='BLOCKED_DATA'
    assert not receipt['executable_source_published']
    assert not (root/'source-ready.json').exists()
    with pytest.raises(SourceError):cli.capture(manifest)


def test_existing_checkpoint_writer_shared_lock_blocks_register_without_append(tmp_path):
    import fcntl
    c,s,raw=scope_fixture();c.update(training_start='2021-01-01T00:00:00Z',authorization='review')
    ledger=tmp_path/'ledger';ledger.write_bytes(raw)
    # Same lock name/protocol as portfolio_budget.checkpoint_budget.
    with Path(str(ledger)+'.lock').open('a') as existing_writer:
        fcntl.flock(existing_writer,fcntl.LOCK_EX)
        with pytest.raises(SourceError,match='lock held'):register(c,s,ledger,'a'*64)
        assert ledger.read_bytes()==raw


@pytest.mark.parametrize('data_failure',[False,True])
def test_terminal_manifest_drift_classified_integrity_not_data(tmp_path,monkeypatch,capsys,data_failure):
    from scripts import capture_portfolio_source as cli
    from lab.portfolio_source import write_json
    c,s,raw=scope_fixture();ledger=tmp_path/'ledger';ledger.write_bytes(raw)
    c.update(training_start='2021-01-01T00:00:00Z',authorization='review',registry=str(ledger),
             output_root=str(tmp_path/'source'),budget_path=str(tmp_path/'budget'),limits=LIMITS)
    cp=tmp_path/'contract';sp=tmp_path/'scope';write_json(cp,c);write_json(sp,s)
    monkeypatch.setattr(cli,'CONTRACT',cp);monkeypatch.setattr(cli,'SCOPE',sp)
    manifest=tmp_path/'manifest';cli.prepare(manifest)
    class Fake:
        def __init__(self,*a):pass
        def get(self,endpoint,params):
            manifest.write_text(manifest.read_text()+'\n')
            if data_failure:raise SourceError('source failure')
            if endpoint=='exchangeInfo':
                return {'symbols':[{'symbol':x,'contractType':'PERPETUAL','onboardDate':0} for x in c['symbols']]}
            return []
    monkeypatch.setattr(cli,'Fetcher',Fake)
    monkeypatch.setattr(cli,'collect',lambda *a:[])
    monkeypatch.setattr(cli,'qc_summary',lambda *a:dict(status='PASS',executable_source_published=False))
    assert cli.capture(manifest)==2
    receipt=json.loads((tmp_path/'source/qc-receipt.json').read_text())
    assert receipt['status']=='CONTROL_INTEGRITY' and receipt['terminal_binding_check']=='FAIL'
    assert not receipt['executable_source_published']


def test_shared_writer_lock_cli_failure_has_zero_gets(tmp_path,monkeypatch,capsys):
    import fcntl
    from scripts import capture_portfolio_source as cli
    from lab.portfolio_source import write_json
    c,s,raw=scope_fixture();ledger=tmp_path/'ledger';ledger.write_bytes(raw)
    c.update(training_start='2021-01-01T00:00:00Z',authorization='review',registry=str(ledger),
             output_root=str(tmp_path/'source'),budget_path=str(tmp_path/'budget'),limits=LIMITS)
    cp=tmp_path/'contract';sp=tmp_path/'scope';write_json(cp,c);write_json(sp,s)
    monkeypatch.setattr(cli,'CONTRACT',cp);monkeypatch.setattr(cli,'SCOPE',sp)
    def forbidden(*a):pytest.fail('GET attempted while global writer lock held')
    monkeypatch.setattr(cli,'Fetcher',forbidden)
    manifest=tmp_path/'manifest';cli.prepare(manifest)
    with Path(str(ledger)+'.lock').open('a') as writer:
        fcntl.flock(writer,fcntl.LOCK_EX)
        assert cli.capture(manifest)==2
    assert ledger.read_bytes()==raw
    r=json.loads((tmp_path/'source/qc-receipt.json').read_text())
    assert r['status']=='BLOCKED_CONTROL' and r['requests']==0
