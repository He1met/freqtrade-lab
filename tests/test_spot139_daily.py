"""Only generated artificial bars and temporary roots; never native or market data."""
import dataclasses
import json
from decimal import Decimal as D
from pathlib import Path
import pytest
from lab import spot139_daily as daily
from scripts.spot139_daily import synthetic_fixture


def state(first=85):
    r=daily.Rule(D('.001'),D('.001'),D(5),D(1000),D('.000001'),D('.000001'),D('.01'))
    h={s:{d:(D(100)+D(d)/5,D(101)+D(d)/5,D(99)+D(d)/5,D(100)+D(d)/5) for d in range(first)} for s in daily.SYMBOLS}
    return daily.initial_state({s:r for s in daily.SYMBOLS},first,h,0)


def clone(s):return daily.unpack(json.loads(daily.canonical(daily.pack(s))))


def test_continuous_equals_daily_restart_all_fields_orders_and_missing_calendar(tmp_path):
    a=state(); b=clone(a); root=tmp_path/'run'; daily.initialize(root,daily.pack(b)); all_rows=[]
    packets=[synthetic_fixture(d,p) for d,p in [(85,'117'),(86,'85'),(87,'119'),(88,'120'),(89,'121'),(90,'120')]]
    packets[4]['bars']={s:[] for s in daily.SYMBOLS}
    for packet in packets:
        result=daily.apply_day(a,packet);before=daily.pack(b)
        out=daily.commit_day(root,before,packet);b=daily.unpack(daily.committed(root))
        saved=daily.decode(json.loads((Path(out['path'])/'result.json').read_bytes()))
        assert daily.encode(result)==daily.encode(saved)
        assert daily.pack(a)==daily.pack(b)
        all_rows.extend(result['costs']['base']['orders'])
    assert [r['hour'] for r in all_rows if r['side']=='buy']==[85*24+1,85*24+1,88*24+1,88*24+1]
    assert any(m.residual for m in a['models'].values()) or any(m.wallet.inventory for m in a['models'].values())
    assert 89 not in a['daily']['BTC/USDT']  # no compaction/fill of missing calendar day
    assert len([r for r in daily.events(root/'attempts.jsonl') if r['event']=='COST_STARTED'])==12


def test_state_tags_cover_every_field_and_preserve_pending_exits_latches():
    s=state();daily.apply_day(s,synthetic_fixture(85))
    for m in s['models'].values():
        m.exits.add('BTC/USDT');m.pending['ETH/USDT']={'hour':86*24+1,'units':D('.01'),'distance':D(6)}
        m.episodes['BTC/USDT'].armed=False;m.warning_pending.add('BTC/USDT');m.wallet.warned=True;m.wallet.halted=True
        m.block_reasons['BTC/USDT']='STALE_INVENTORY';m.seen_nonpositive.add('ETH/USDT')
    restored=clone(s)
    for c in daily.COSTS:
        assert {f.name for f in dataclasses.fields(s['models'][c])}==set(s['models'][c].__dict__)
        assert s['models'][c].__dict__==restored['models'][c].__dict__
    packet=synthetic_fixture(86,'117',missing=(86*24,))
    assert daily.encode(daily.apply_day(s,packet))==daily.encode(daily.apply_day(restored,packet))
    assert any(f['side']=='sell' and f['hour']==86*24+1 for f in s['models']['base'].fills)
    assert s['models']['base'].wallet.halted and s['models']['base'].wallet.warned


@pytest.mark.parametrize('peak,warned,halted', [('1120',True,False),('1180',True,True)])
def test_ten_fifteen_latches_survive_restart(peak,warned,halted):
    s=state()
    for m in s['models'].values():m.wallet.peak=D(peak)
    daily.apply_day(s,synthetic_fixture(85));r=clone(s)
    for m in r['models'].values():assert (m.wallet.warned,m.wallet.halted)==(warned,halted)
    assert daily.encode(daily.apply_day(s,synthetic_fixture(86)))==daily.encode(daily.apply_day(r,synthetic_fixture(86)))


def test_one_cost_risk_breach_stops_both_and_no_terminal_liquidation(tmp_path):
    s=state();s['models']['base'].wallet.peak=D(1300)
    root=tmp_path/'run';daily.initialize(root,daily.pack(s))
    daily.commit_day(root,daily.pack(s),synthetic_fixture(85))
    out=daily.unpack(daily.committed(root));assert out['stopped']=='RISK_LIMIT_BREACHED'
    assert all(m.last_hour==85*24 for m in out['models'].values())
    with pytest.raises(ValueError,match='stopped'):daily.commit_day(root,daily.pack(out),synthetic_fixture(86))
    assert len([r for r in daily.events(root/'attempts.jsonl') if r['event']=='RESERVED'])==1


def test_atomic_commit_both_sides_and_immutable_noop(tmp_path,monkeypatch):
    root=tmp_path/'run';s=daily.pack(state());p=synthetic_fixture(85);daily.initialize(root,s)
    def before(point):
        if point=='before_commit':raise RuntimeError('power loss before rename')
    with pytest.raises(RuntimeError):daily.commit_day(root,s,p,before)
    assert daily.committed(root)==s and not list((root/'commits').iterdir())
    changed=json.loads(json.dumps(p));changed['received_at_hour']+=1
    with pytest.raises(ValueError,match='same input'):daily.commit_day(root,s,changed)
    def after(point):
        if point=='after_commit':raise RuntimeError('power loss after rename')
    with pytest.raises(RuntimeError):daily.commit_day(root,s,p,after)
    assert daily.committed(root)!=s
    history=(root/'attempts.jsonl').read_bytes()
    monkeypatch.setattr(daily,'apply_day',lambda *a,**k:pytest.fail('no-op recomputed'))
    assert daily.commit_day(root,s,p)['status']=='NO_OP_COMMITTED'
    assert (root/'attempts.jsonl').read_bytes()==history
    with pytest.raises(ValueError,match='revision'):daily.commit_day(root,s,changed)
    rows=daily.events(root/'attempts.jsonl')
    assert [r['bucket'] for r in rows if r['event']=='RESERVED']==['normal','recovery']


def test_recovery_cost_budget_and_same_state_binding(tmp_path):
    root=tmp_path/'run';s=daily.pack(state());p=synthetic_fixture(85);daily.initialize(root,s)
    def fail(point):
        if point=='after_hour':raise RuntimeError('incomplete batch')
    for i in range(4):
        with pytest.raises(RuntimeError):daily.commit_day(root,s,p,fail)
    with pytest.raises(ValueError,match='six recovery'):daily.commit_day(root,s,p,fail)
    rows=daily.events(root/'attempts.jsonl')
    assert sum(r['cost_slots'] for r in rows if r['event']=='RESERVED' and r['bucket']=='recovery')==6
    assert len([r for r in rows if r['event']=='COST_STARTED'])==8
    assert daily.committed(root)==s


def test_version_candidate_missing_field_and_bad_input_reject_before_writes(tmp_path):
    s=daily.pack(state())
    for key in ('version','candidate_sha256','kind'):
        bad=json.loads(json.dumps(s));bad[key]='bad'
        with pytest.raises(ValueError):daily.initialize(tmp_path/key,bad)
        assert not (tmp_path/key).exists()
    bad=json.loads(json.dumps(s))
    # Tagged encoding is explicit and field-exact, not dataclass defaults.
    def damage(x):
        if isinstance(x,dict):
            if x.get('$class')=='SpotResidualV3':x['fields'].pop('pending');return True
            return any(damage(v) for v in x.values())
        if isinstance(x,list):return any(damage(v) for v in x)
        return False
    assert damage(bad)
    with pytest.raises(ValueError,match='incomplete'):daily.unpack(bad)
    p=synthetic_fixture(86)
    with pytest.raises(ValueError,match='calendar jump'):daily.validate_day(p,daily.unpack(s))
    p=synthetic_fixture(85);p['received_at_hour']=85*24+1
    with pytest.raises(ValueError,match='unclosed'):daily.validate_day(p,daily.unpack(s))
    p=synthetic_fixture(85);p['bars']['BTC/USDT'].append(p['bars']['BTC/USDT'][0])
    with pytest.raises(ValueError,match='duplicate'):daily.validate_day(p,daily.unpack(s))


def test_warmup_no_pnl_and_finite_terminal_never_forces_sale():
    s=state(0)
    out=daily.apply_day(s,synthetic_fixture(0))
    assert out['score_start'] is None and all(x['terminal'] is None for x in out['costs'].values())
    s=state(264)
    out=daily.apply_day(s,synthetic_fixture(264,'154'))
    assert s['stopped']=='FINITE_CALENDAR_END' and s['next_day']==265
    for m in s['models'].values():assert m.wallet.inventory and all(f['side']=='buy' for f in m.fills)
    assert clone(s)['models']==s['models']


class Transport:
    offline=True
    def __init__(self,fail=False):self.calls=0;self.fail=fail
    def __call__(self,request):
        self.calls+=1
        if self.fail:raise TimeoutError('synthetic timeout')
        return b'{"kind":"SYNTHETIC_TRANSPORT"}'


def test_offline_plan_exclusive_attempt_buckets_failure_and_cached_noop(tmp_path):
    root=tmp_path/'run';daily.initialize(root,daily.pack(state()))
    plan=daily.request_plan(85,87);assert len(plan)==7
    t=Transport(True);old=plan[1]
    with pytest.raises(TimeoutError):daily.offline_request(root,old,85,87,t)
    assert daily.events(root/'requests.jsonl')[0]['bucket']=='recovery'
    t.fail=False;daily.offline_request(root,old,85,87,t)
    before=(root/'requests.jsonl').read_bytes();calls=t.calls
    daily.offline_request(root,old,85,87,t)
    assert t.calls==calls and (root/'requests.jsonl').read_bytes()==before
    current=plan[-1];t.fail=True
    with pytest.raises(TimeoutError):daily.offline_request(root,current,85,87,t)
    t.fail=False;daily.offline_request(root,current,85,87,t)
    attempts=[r for r in daily.events(root/'requests.jsonl') if r['event']=='ATTEMPT']
    assert [r['bucket'] for r in attempts]==['recovery','recovery','normal','recovery']
    assert len(attempts)==t.calls  # success/failure status is not a second charge
    with pytest.raises(ValueError,match='three pending'):daily.request_plan(85,88)
    with pytest.raises(ValueError,match='offline'):daily.offline_request(root,current,85,87,lambda r:b'')


def test_transport_recovery_limit_and_corrupt_cache_stop(tmp_path):
    root=tmp_path/'run';daily.initialize(root,daily.pack(state()));r=daily.request_plan(85,86)[1];t=Transport(True)
    for _ in range(12):
        with pytest.raises(TimeoutError):daily.offline_request(root,r,85,86,t)
    with pytest.raises(ValueError,match='budget'):daily.offline_request(root,r,85,86,t)
    assert t.calls==12
    root2=tmp_path/'second';daily.initialize(root2,daily.pack(state()));t=Transport();daily.offline_request(root2,r,85,86,t)
    next(root2.glob('source-*.json')).write_bytes(b'changed')
    with pytest.raises(ValueError,match='drift'):daily.offline_request(root2,r,85,86,t)
    assert t.calls==1


def test_last_hour_low_is_carried_into_midnight_exit():
    s=state();p=synthetic_fixture(85)
    for rows in p['bars'].values():rows[-1]['ohlc'][2]='70'
    daily.apply_day(s,p)
    assert all(m.episodes['BTC/USDT'].active for m in s['models'].values())
    resumed=clone(s);out=daily.apply_day(resumed,synthetic_fixture(86))
    for r in out['costs'].values():assert r['orders'][0]['side']=='sell' and r['orders'][0]['hour']==86*24


def test_wait_for_85_consecutive_days_no_automatic_start_or_extension():
    s=state();s['daily']['BTC/USDT'].pop(0)
    out=daily.apply_day(s,synthetic_fixture(85))
    assert out['score_start'] is None and not s['models']['base'].fills
    # The next calendar day now has an intact consecutive 85-day dependency.
    daily.apply_day(s,synthetic_fixture(86));assert s['score_start']==86 and s['end_day']==265


def test_tampered_previous_calendar_and_committed_output_fail_closed(tmp_path):
    s=state();s['previous']['BTC/USDT'][85*24]=((D(1),)*4,True)
    with pytest.raises(ValueError,match='future previous'):daily.unpack(daily.pack(s))
    s=daily.pack(state());root=tmp_path/'run';daily.initialize(root,s);p=synthetic_fixture(85)
    out=daily.commit_day(root,s,p);(Path(out['path'])/'result.json').write_bytes(b'changed')
    with pytest.raises(ValueError,match='bytes changed'):daily.commit_day(root,s,p)


def test_accounting_failure_stops_joint_recovery_and_writer_lock_precedes_attempt(tmp_path,monkeypatch):
    import fcntl
    root=tmp_path/'run';s=daily.pack(state());p=synthetic_fixture(85);daily.initialize(root,s)
    with (root/'writer.lock').open('r') as held:
        fcntl.flock(held,fcntl.LOCK_EX|fcntl.LOCK_NB)
        with pytest.raises(BlockingIOError):daily.commit_day(root,s,p)
    assert not (root/'attempts.jsonl').exists()
    real=daily.apply_day
    def broken(state,packet,*args):
        out=real(state,packet,*args);state['models']['base'].wallet.cash+=1
        return out
    monkeypatch.setattr(daily,'apply_day',broken)
    with pytest.raises(ValueError,match='accounting'):daily.commit_day(root,s,p)
    assert daily.events(root/'attempts.jsonl')[-1]['event']=='FATAL'
    with pytest.raises(ValueError,match='joint observation stopped'):daily.commit_day(root,s,p)


def test_day_adapter_matches_original_uninterrupted_hour_loop():
    from lab.spot139_feed import history_at
    s=state();reference=clone(s)
    packets=[synthetic_fixture(d,p) for d,p in [(85,'117'),(86,'85'),(87,'119'),(88,'120'),(89,'121'),(90,'120')]]
    packets[-2]['bars']={x:[] for x in daily.SYMBOLS}
    hourly={x:{} for x in daily.SYMBOLS}
    for packet in packets:
        # Construction only; no reference price reader or native mapper.
        for symbol,rows in packet['bars'].items():
            hourly[symbol].update({r['hour']:(tuple(map(D,r['ohlc'])),r['full']) for r in rows})
        daily.apply_day(s,packet);s=clone(s)
    for hour in range(85*24,91*24):
        opens={x:bars[hour][0][0] for x,bars in hourly.items() if hour in bars}
        lows={x:bars[hour-1][0][2] for x,bars in hourly.items() if hour-1 in bars}
        history=history_at(hour,hourly,reference['daily']) if hour%24==0 else None
        for m in reference['models'].values():m.on_hour(hour,opens,history,lows)
    assert daily.encode(s['models'])==daily.encode(reference['models'])


def test_crash_after_durable_reservation_before_stage_files_is_recoverable(tmp_path):
    root=tmp_path/'run';s=daily.pack(state());p=synthetic_fixture(85);daily.initialize(root,s)
    def fail(point):
        if point=='after_reservation_before_files':raise RuntimeError('crash before files')
    with pytest.raises(RuntimeError):daily.commit_day(root,s,p,fail)
    assert not list((root/'attempts').iterdir())
    assert not any(r['event']=='COST_STARTED' for r in daily.events(root/'attempts.jsonl'))
    assert daily.commit_day(root,s,p)['status']=='COMMITTED'
    assert [r['bucket'] for r in daily.events(root/'attempts.jsonl') if r['event']=='RESERVED']==['normal','recovery']
