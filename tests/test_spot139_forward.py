"""Real contract path exercised with artificial OHLC and injected offline HTTP only."""
import io
import json
import time
from pathlib import Path
from datetime import datetime,timezone
from decimal import Decimal as D
import pytest
from lab import spot139_forward as f
from lab import spot139_daily as d


class Response(io.BytesIO):
    def __init__(self,value,status=200,headers=None):
        super().__init__(value if isinstance(value,bytes) else json.dumps(value).encode())
        self.status=status;self.headers=headers or {}


class HTTP:
    def __init__(self,m,now):self.m=m;self.clock=now;self.calls=[];self.mode=None;self.baseline_seen=[]
    def now(self):return self.clock
    def sleep(self,n):self.clock+=n
    def __call__(self,request,timeout):
        assert timeout==20
        self.calls.append((request,self.clock))
        if self.mode=='timeout':raise TimeoutError('injected timeout')
        if isinstance(self.mode,int):return Response({},status=self.mode)
        if self.mode=='oversize':return Response(b'X'*(256*1024+1),headers={'Content-Length':str(256*1024+1)})
        if request['kind']=='metadata':
            rows=json.loads(json.dumps([dict(x,filters=list(x['filters'].values())) for x in self.m['expected_metadata'].values()]))
            value={'symbols':rows,'serverTime':int(self.clock*1000)}
            if self.mode=='metadata_change':value['symbols'][0]['filters'][0]['extraRule']=1
            return Response(value)
        self.baseline_seen.append((Path(self.m['run_root'])/'metadata-baseline.json').exists())
        if self.mode=='missing_eth' and request['params']['symbol']=='ETHUSDT':raise TimeoutError('second asset unavailable')
        day=request['day'];bars=[]
        for h in range(day*24,(day+1)*24):
            bars.append([h*3600000,'100','101','99','100','1',h*3600000+3599999,'100',1,'0','0','0'])
        return Response(bars)


def setup(tmp_path,days=7):
    m=json.loads(Path('docs/issue139-forward-v1-manifest.json').read_bytes());m['run_root']=str(tmp_path/'real-fixture-root')
    w=m['window']['W'];reg=tmp_path/'registration.jsonl'
    row=dict(record_type='ISSUE139_REAL_FORWARD_REGISTERED',campaign=m['campaign'],manifest_sha256=d.digest(d.canonical(m)),window=m['window'],candidate_sha256=m['candidate_sha256'],rules_sha256=m['rules_sha256'],registered_at_utc=datetime.fromtimestamp((w-1)*86400,timezone.utc).isoformat())
    reg.write_text(json.dumps(row)+'\n')
    g=json.loads(Path('docs/issue139-forward-first7-grant-template.json').read_bytes())
    g.update(authorized=True,authorization_reference='https://github.com/He1met/freqtrade-lab/issues/139#issuecomment-1',authorized_at_utc=row['registered_at_utc'],manifest_sha256=row['manifest_sha256'],run_root=m['run_root'],registration_path=str(reg),registration_sha256=d.digest(reg.read_bytes()))
    f.check_grant(m,g)
    return m,g,HTTP(m,(w+1)*86400+600)


def init(m,g):
    return f.initialize(m,g,now=lambda:m['window']['W']*86400-1)


def run(m,g,http,target=None):
    target=m['window']['W'] if target is None else target
    return f.run_daily(m,g,target,http,http.now,http.sleep)


def test_init_no_http_then_warmup_source_baseline_and_noop(tmp_path):
    m,g,h=setup(tmp_path);init(m,g);assert not h.calls
    result=run(m,g,h);assert result['status']=='DAYS_COMMITTED' and len(h.calls)==3 and all(h.baseline_seen)
    assert all(b[1]-a[1]>=1 for a,b in zip(h.calls,h.calls[1:]))
    root=Path(m['run_root']);s=d.unpack(d.committed(root,m),m)
    assert s['score_start'] is None and all(not x.fills and x.wallet.cash==1000 for x in s['models'].values())
    assert not any(r['event']=='COST_STARTED' for r in d.events(root/'attempts.jsonl'))
    before={p.name:d.digest(p.read_bytes()) for p in root.iterdir() if p.is_file()}
    assert run(m,g,h)['status']=='NO_OP_COMMITTED' and len(h.calls)==3
    assert before=={p.name:d.digest(p.read_bytes()) for p in root.iterdir() if p.is_file()}


@pytest.mark.parametrize('mode',[301,429,418,500,'oversize','metadata_change'])
def test_source_failure_counts_and_stops_before_prices(tmp_path,mode):
    m,g,h=setup(tmp_path);init(m,g);h.mode=mode
    with pytest.raises(f.Stop):run(m,g,h)
    root=Path(m['run_root']);rows=d.events(root/'source-attempts.jsonl')
    assert len([r for r in rows if r['event']=='ATTEMPT'])==1
    assert not list((root/'commits').iterdir()) and len(h.calls)==1
    assert (root/'source-stop.json').exists()
    with pytest.raises(f.Stop,match='stopped'):run(m,g,h)
    assert len(h.calls)==1


def test_301_redirect_handler_never_follows():
    with pytest.raises(f.Stop,match='redirect'):f.NoRedirect().redirect_request(None,None,301,'x',{},'https://evil.invalid')


def test_missing_second_asset_never_commits_either_cost(tmp_path):
    m,g,h=setup(tmp_path);init(m,g);h.mode='missing_eth'
    with pytest.raises(TimeoutError):run(m,g,h)
    root=Path(m['run_root']);assert not list((root/'commits').iterdir()) and not (root/'attempts.jsonl').exists()
    assert len([r for r in d.events(root/'source-attempts.jsonl') if r['event']=='ATTEMPT'])==3
    # Cached metadata/BTC survive; ETH repeat would consume recovery, not normal.
    h.mode=None
    assert run(m,g,h)['status']=='NO_OP_ALREADY_ATTEMPTED_TODAY' and len(h.calls)==3
    h.clock=(m['window']['W']+2)*86400+600
    with pytest.raises(f.Stop,match='budget'):run(m,g,h,m['window']['W']+1)
    assert len(h.calls)==4


def test_check_only_and_unauthorized_or_late_init_no_root(tmp_path):
    m,g,h=setup(tmp_path);f.check_manifest(m);f.check_grant(m,g)
    assert not Path(m['run_root']).exists() and not h.calls
    g['authorized']=False
    with pytest.raises(f.Stop,match='grant'):init(m,g)
    g['authorized']=True;g['authorized_at_utc']=datetime.fromtimestamp((m['window']['W']+1)*86400,timezone.utc).isoformat()
    with pytest.raises(f.Stop,match='backdate'):init(m,g)
    assert not Path(m['run_root']).exists()


def test_boundaries_no_get_and_real_synthetic_cannot_mix(tmp_path):
    m,g,h=setup(tmp_path);init(m,g)
    for target in [m['window']['W']-1,m['window']['E'],m['window']['W']+7]:
        with pytest.raises(f.Stop):run(m,g,h,target)
    assert not h.calls
    envelope=json.loads((Path(m['run_root'])/'initial.json').read_bytes())
    with pytest.raises(ValueError,match='synthetic'):d.unpack(envelope)
    fake=d.pack(d.unpack(envelope,m))
    with pytest.raises(ValueError,match='real source'):d.unpack(fake,m)


def test_real_context_85_warmup_days_no_model_calls_then_score(tmp_path):
    m,g,h=setup(tmp_path);w=m['window']['W'];s=d.initial_state(f.rules_from_semantic(m['expected_metadata']),w,contract=m)
    def packet(day):
        price=D(100)+D(day-w)/5
        return dict(kind='REAL_FORWARD',candidate_sha256=d.candidate_sha(),source_contract_sha256=d.digest(d.canonical(m)),day=day,received_at_hour=(day+1)*24,
                    source_receipts={x:{} for x in ('metadata',*d.SYMBOLS)},bars={x:[dict(hour=hour,ohlc=[str(price),str(price+1),str(price-1),str(price)],full=True) for hour in range(day*24,(day+1)*24)] for x in d.SYMBOLS})
    for day in range(w,w+85):
        out=d.apply_day(s,packet(day),lambda c:pytest.fail('warmup called trading'),contract=m)
        assert out['score_start'] is None
        s=d.unpack(d.pack(s,m),m)
    assert all(x.wallet.cash==1000 and not x.fills and x.last_hour is None for x in s['models'].values())
    starts=[];d.apply_day(s,packet(w+85),starts.append,contract=m)
    assert starts==['base','stress'] and s['score_start']==w+85
    assert all(x.fills and x.fills[0]['hour']==(w+85)*24+1 for x in s['models'].values())


def test_real_alarm_interrupts_and_predeadline_does_not_enter():
    entered=[]
    with pytest.raises(TimeoutError):
        with f.deadline(.01):time.sleep(.15)
    with pytest.raises(TimeoutError):
        with f.deadline(0):entered.append(True)
    assert not entered


def test_subgrant_cumulative_limits_do_not_reset_after_extension(tmp_path):
    m,g,h=setup(tmp_path);init(m,g);run(m,g,h)
    g['end_day']+=1;g['cumulative_caps']['normal_gets']=3;g['cumulative_caps']['gets']=3
    h.clock=(m['window']['W']+2)*86400+600
    with pytest.raises(f.Stop,match='budget'):run(m,g,h,m['window']['W']+1)
    assert len(h.calls)==3


def test_three_sleep_days_are_delayed_and_normal_recovery_exclusive(tmp_path):
    m,g,h=setup(tmp_path);g['cumulative_caps'].update(recovery_gets=4,gets=25,bytes=7*384*1024+4*64*1024)
    init(m,g);w=m['window']['W'];h.clock=(w+3)*86400+600
    assert run(m,g,h,w+2)['days']==3 and len(h.calls)==7
    root=Path(m['run_root']);attempts=[r for r in d.events(root/'source-attempts.jsonl') if r['event']=='ATTEMPT']
    assert sum(r['bucket']=='normal_gets' for r in attempts)==3
    assert sum(r['bucket']=='recovery_gets' for r in attempts)==4
    result=d.decode(json.loads((root/'commits'/f'{w:08d}'/'result.json').read_bytes()))
    assert result['observation']=='DELAYED_OBSERVATION_REAL' and result['received_at_hour']>=(w+3)*24
    assert result['costs']['base']['terminal'] is None


def test_timeout_after_attempt_charged_and_expired_outer_before_attempt(tmp_path):
    m,g,h=setup(tmp_path);init(m,g);h.mode='timeout'
    with pytest.raises(TimeoutError):run(m,g,h)
    rows=d.events(Path(m['run_root'])/'source-attempts.jsonl')
    assert [r['event'] for r in rows]==['ATTEMPT','FAILED']
    assert rows[0]['byte_cap']==256*1024
    with pytest.raises(TimeoutError):
        with f.deadline(0):run(m,g,h)
    assert len(h.calls)==1


def test_stream_ceiling_counts_bytes_and_does_not_commit(tmp_path):
    m,g,h=setup(tmp_path);init(m,g)
    def stream(request,timeout):return Response(b'X'*(256*1024+10))
    with pytest.raises(f.Stop,match='stream'):f.run_daily(m,g,m['window']['W'],stream,h.now,h.sleep)
    root=Path(m['run_root']);rows=d.events(root/'source-attempts.jsonl')
    assert rows[-1]['event']=='FAILED' and rows[-1]['bytes']==256*1024
    assert not list((root/'commits').iterdir())


def test_registration_late_or_changed_and_grant_subslice_limits(tmp_path):
    m,g,h=setup(tmp_path);reg=Path(g['registration_path']);r=json.loads(reg.read_text())
    r['registered_at_utc']=datetime.fromtimestamp((m['window']['W']+1)*86400,timezone.utc).isoformat()
    reg.write_text(json.dumps(r)+'\n');g['registration_sha256']=d.digest(reg.read_bytes())
    with pytest.raises(f.Stop,match='pre-window'):f.check_grant(m,g)
    assert not Path(m['run_root']).exists()


def test_missed_actual_start_cannot_initialize_even_with_early_grant(tmp_path):
    m,g,h=setup(tmp_path)
    with pytest.raises(f.Stop,match='backdate'):f.initialize(m,g,now=lambda:m['window']['W']*86400+1)
    assert not Path(m['run_root']).exists()


def test_actual_request_alarm_is_charged_and_missing_metadata_fields_stop(tmp_path,monkeypatch):
    m,g,h=setup(tmp_path);init(m,g);real_deadline=f.deadline
    def fast(seconds):return real_deadline(.01 if seconds==20 else .2)
    monkeypatch.setattr(f,'deadline',fast)
    def blocked(request,timeout):time.sleep(.1);return Response({})
    with pytest.raises(TimeoutError):f.run_daily(m,g,m['window']['W'],blocked,h.now,h.sleep)
    assert [r['event'] for r in d.events(Path(m['run_root'])/'source-attempts.jsonl')]==['ATTEMPT','FAILED']
    with pytest.raises(f.Stop,match='fields missing'):f.semantic({'symbols':[{'symbol':'BTCUSDT'},{'symbol':'ETHUSDT'}]})


def test_four_pending_days_stop_before_attempt(tmp_path):
    m,g,h=setup(tmp_path);init(m,g);h.clock=(m['window']['W']+4)*86400+600
    with pytest.raises(ValueError,match='three pending'):run(m,g,h,m['window']['W']+3)
    assert not h.calls and not (Path(m['run_root'])/'source-attempts.jsonl').exists()
