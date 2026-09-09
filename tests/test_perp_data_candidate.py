"""Candidate required streams win the same transport budget; no real HTTP."""
from pathlib import Path
from urllib.parse import urlparse,parse_qs
from urllib.error import HTTPError
import hashlib
import io
import json
import pytest

from lab import perp_data as legacy
from lab.perp_data_candidate import REQUIRED,candidate_complete,collect,update

START=legacy.millis('2026-09-08T00:00:00Z')


class Reply:
    status=200
    def __init__(self,value):self.raw=json.dumps(value).encode()
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def read(self,size):return self.raw[:size]


def public_fixture(monkeypatch,fail_mark=False,empty_funding=False):
    calls=[]
    def fake(request,timeout):
        parts=urlparse(request.full_url);q=parse_qs(parts.query);endpoint=parts.path.rsplit('/',1)[-1]
        symbol=q.get('symbol',q.get('pair',['']))[0];calls.append((endpoint,symbol))
        if endpoint=='exchangeInfo':
            return Reply({'symbols':[dict(symbol=s,contractType='PERPETUAL',quoteAsset='USDT',marginAsset='USDT') for s in legacy.SYMBOLS]})
        if endpoint=='markPriceKlines' and symbol=='BTCUSDT' and fail_mark:
            raise HTTPError(request.full_url,403,'blocked',{},io.BytesIO(b'{}'))
        if endpoint=='fundingRate':
            if empty_funding:return Reply([])
            event=int(q['endTime'][0])+1-legacy.HOUR+5
            return Reply([dict(symbol=symbol,fundingTime=event,fundingRate='0.0001',markPrice='100')] if int(q['startTime'][0])<=event else [])
        if endpoint.endswith('Klines') or endpoint=='klines':
            start=int(q['startTime'][0]);end=int(q['endTime'][0])+1
            return Reply([[at,'100','110','90','105','2',at+legacy.HOUR-1,'200',3,'1','100','0'] for at in range(start,end,legacy.HOUR)])
        raise AssertionError('optional request unexpectedly consumed the tight core budget: '+request.full_url)
    monkeypatch.setattr(legacy,'public_open',fake)
    monkeypatch.setattr(legacy,'utcnow',lambda:'2026-09-08T01:20:00Z')
    return calls


def test_eleven_gets_finish_required_before_optional_can_spend(monkeypatch,tmp_path):
    calls=public_fixture(monkeypatch)
    result=collect(tmp_path/'capture',START,START+legacy.HOUR,11,incremental=True,candidate_required=True)
    assert result['candidate_core_complete'] is True
    assert len(calls)==result['requests']==11
    assert [endpoint for endpoint,_ in calls]==['exchangeInfo','klines','klines','markPriceKlines','markPriceKlines','fundingRate','fundingRate','fundingRate','fundingRate','premiumIndexKlines','premiumIndexKlines']
    assert set(result['datasets'])=={f'{s}-{k}' for s in legacy.SYMBOLS for k in REQUIRED}
    assert set(result['deferred'].values())=={'ACQUISITION_BUDGET_STOP'}
    budget=json.loads((tmp_path/'capture/budget.json').read_text())
    assert (budget['max_requests'],budget['max_total_response_bytes'],budget['max_seconds'])==(11,20*1024*1024,300)
    assert budget['limits_unchanged'] is True
    assert budget['collector_sha256']==hashlib.sha256(Path(legacy.__file__).read_bytes()).hexdigest()


def test_insufficient_budget_keeps_core_blocker_and_defers_all_optional(monkeypatch,tmp_path):
    calls=public_fixture(monkeypatch)
    result=collect(tmp_path/'capture',START,START+legacy.HOUR,10,incremental=True,candidate_required=True)
    assert len(calls)==result['requests']==10
    assert result['status']=='BLOCKED_DATA' and result['candidate_core_complete'] is False
    assert result['errors']['ETHUSDT-premium']=='ACQUISITION_BUDGET_STOP'
    assert set(result['deferred'].values())=={'REQUIRED_DATA_INCOMPLETE'}
    assert not any(endpoint in ('indexPriceKlines','openInterestHist','asset-metrics') for endpoint,_ in calls)


def test_required_permanent_failure_never_spends_remaining_budget_on_optional(monkeypatch,tmp_path):
    calls=public_fixture(monkeypatch,fail_mark=True)
    result=collect(tmp_path/'capture',START,START+legacy.HOUR,24,incremental=True,candidate_required=True)
    assert result['candidate_core_complete'] is False and result['errors']['BTCUSDT-mark']=='HTTP_403'
    assert len(calls)==11 and set(result['deferred'].values())=={'REQUIRED_DATA_INCOMPLETE'}


def test_http_200_empty_funding_is_explicitly_incomplete(monkeypatch,tmp_path):
    calls=public_fixture(monkeypatch,empty_funding=True)
    result=collect(tmp_path/'capture',START,START+legacy.HOUR,24,incremental=True,candidate_required=True)
    assert len(calls)==9
    assert result['datasets']['BTCUSDT-funding']['rows']==0
    assert result['candidate_core_complete'] is False and result['status']=='BLOCKED_DATA'
    assert result['errors']['candidate_required']=='REQUIRED_DATA_INCOMPLETE_OR_NO_ELIGIBLE_RECENT_SETTLEMENT'
    assert set(result['deferred'].values())=={'REQUIRED_DATA_INCOMPLETE'}


def fake_capture(root,start,end,max_requests,*,premium=True,**kwargs):
    root.mkdir();result=dict(status='CAPTURED_WITH_LIMITATIONS',requests=9,errors={},datasets={},
        instrument_rules='CURRENT_RULES_VERIFIED_HISTORICAL_RULES_UNPROVEN',root=str(root),
        window_start=legacy.iso(start),window_end_exclusive=legacy.iso(end))
    for symbol in legacy.SYMBOLS:
        for kind in (REQUIRED if premium else REQUIRED[:-1]):
            name=f'{symbol}-{kind}';path=root/(name+'.jsonl')
            row=dict(event_time=legacy.iso(end-2*legacy.HOUR),available_at=legacy.iso(end-legacy.HOUR),rate='0.0001',mark_price='100') if kind=='funding' else {}
            path.write_text(json.dumps(row)+'\n')
            result['datasets'][name]=dict(path=path.name,sha256=hashlib.sha256(path.read_bytes()).hexdigest(),rows=1,missing_rows=0)
    (root/'receipt.json').write_text(json.dumps(result));return result


def test_funding_age_uses_latest_nominally_available_event_not_unpublished_tail(tmp_path):
    root=tmp_path/'capture';receipt=fake_capture(root,START,START+legacy.HOUR,24)
    path=root/'BTCUSDT-funding.jsonl';end=START+legacy.HOUR
    def replace(events):
        rows=[dict(event_time=legacy.iso(event),available_at=legacy.iso(event+legacy.HOUR),rate='0.0001',mark_price='100') for event in events]
        path.write_text(''.join(json.dumps(row)+'\n' for row in rows))
        receipt['datasets']['BTCUSDT-funding'].update(rows=len(rows),sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    replace([end-2*legacy.HOUR,end-10*60_000])
    assert candidate_complete(receipt,root) is True  # Recent prior event is known; newest tail is not yet published.
    replace([end-10*60_000])
    assert candidate_complete(receipt,root) is False
    replace([end-13*legacy.HOUR,end-10*60_000])
    assert candidate_complete(receipt,root) is False  # An unpublished tail cannot rescue the stale known event.


def test_candidate_update_reuses_same_budget_and_committed_hour_idempotently(tmp_path):
    calls=[]
    def collector(*args,**kwargs):
        calls.append((args,kwargs));assert kwargs['candidate_required'] is True
        return fake_capture(*args,**kwargs)
    one=update(tmp_path,'2026-09-08T01:15:00Z',collector=collector,candidate_required=True)
    assert one['core_complete'] is True and one['candidate_required'] is True
    assert calls[0][0][3]==24
    two=update(tmp_path,'2026-09-08T01:30:00Z',collector=collector,candidate_required=True)
    assert two['status']=='NO_OP_ALREADY_CAPTURED' and two['requests']==0 and len(calls)==1
    state=json.loads((tmp_path/'state.json').read_text())
    assert state['daily_requests']['2026-09-08']==9


def test_missing_premium_cannot_advance_candidate_core_or_be_replayed(tmp_path):
    def missing(*args,**kwargs):return fake_capture(*args,premium=False,**kwargs)
    one=update(tmp_path,'2026-09-08T01:15:00Z',collector=missing,candidate_required=True)
    assert one['status']=='BLOCKED_DATA' and one['core_complete'] is False
    assert 'last_complete_end' not in json.loads((tmp_path/'state.json').read_text())
    two=update(tmp_path,'2026-09-08T01:30:00Z',candidate_required=True)
    assert two['status']=='NO_OP_BLOCKED_DATA' and two['requests']==0


def test_legacy_committed_core_flag_is_not_candidate_premium_evidence(tmp_path):
    def missing(*args,**kwargs):return fake_capture(*args,premium=False,**kwargs)
    old=legacy.update(tmp_path,'2026-09-08T01:15:00Z',collector=missing)
    assert old['core_complete'] is True
    original=(Path(old['receipt']).read_bytes(),(tmp_path/'state.json').read_bytes())
    new=update(tmp_path,'2026-09-08T01:30:00Z',candidate_required=True)
    assert new['core_complete'] is False and new['status']=='NO_OP_BLOCKED_DATA' and new['requests']==0
    assert original==(Path(old['receipt']).read_bytes(),(tmp_path/'state.json').read_bytes())


def test_default_false_delegates_legacy_behavior(monkeypatch,tmp_path):
    calls=[]
    monkeypatch.setattr(legacy,'collect',lambda *a,**k:calls.append((a,k)) or {'legacy':True})
    assert collect(tmp_path,START,START+legacy.HOUR)=={'legacy':True}
    assert 'candidate_required' not in calls[0][1]


def test_unknown_interruption_retains_the_full_reservation(tmp_path):
    def stop(root,*args,**kwargs):root.mkdir();raise KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):update(tmp_path,'2026-09-08T01:15:00Z',collector=stop,candidate_required=True)
    assert json.loads((tmp_path/'state.json').read_text())['daily_requests']['2026-09-08']==24
    assert update(tmp_path,'2026-09-08T01:30:00Z',candidate_required=True)['status']=='INTERRUPTED_CAPTURE_RETAINED'
