from pathlib import Path
import fcntl
import json
import pytest
from lab.perp_data import HOUR, NoRedirect, millis, normalize_klines, quality_times, update

START=millis('2026-09-08T00:00:00Z')

def test_nanosecond_timestamp_and_causal_closed_bar():
    assert millis('2025-01-01T00:00:00.000000000Z')==millis('2025-01-01T00:00:00Z')
    bar=[START,'100','110','90','105','2',START+HOUR-1,'200',3,'1','100','0']
    assert normalize_klines([bar],'ohlcv','2026-09-08T00:59:59Z',START,START+HOUR)==[]
    rows=normalize_klines([bar],'ohlcv','2026-09-08T01:10:00Z',START,START+HOUR)
    assert rows[0]['available_at']=='2026-09-08T01:01:00Z'

@pytest.mark.parametrize('field,value,error',[(2,'99','INVALID_OHLC_RANGE'),(3,'106','INVALID_OHLC_RANGE'),(5,'-1','NEGATIVE_VOLUME'),(1,'NaN','NONFINITE_PRICE')])
def test_bad_prices_cannot_publish(field,value,error):
    bar=[START,'100','110','90','105','2',START+HOUR-1,'200',3,'1','100','0'];bar[field]=value
    with pytest.raises(ValueError,match=error):normalize_klines([bar],'ohlcv','2026-09-08T01:10:00Z',START,START+HOUR)

def test_gap_duplicate_and_outside_window_are_distinct():
    q=quality_times([START,START,START+3*HOUR],START,START+3*HOUR)
    assert (q['duplicates'],q['missing_rows'],q['out_of_window'])==(1,2,1)

def test_no_redirect_does_not_follow_external_destination():
    assert NoRedirect().redirect_request(None,None,302,'',{},'https://elsewhere.example/') is None


def fake_capture(root,start,end,max_requests,**kwargs):
    root.mkdir();value={'status':'CAPTURED_WITH_LIMITATIONS','requests':14,'errors':{},'datasets':{}}
    for s in ('BTCUSDT','ETHUSDT'):
        for k in ('ohlcv','mark','funding'):value['datasets'][f'{s}-{k}']={'missing_rows':0}
    (root/'receipt.json').write_text(json.dumps(value));return value

def test_update_publication_buffer_hour_dedup_and_no_historical_bootstrap(tmp_path):
    called=[]
    def capture(*args,**kwargs):called.append((args,kwargs));return fake_capture(*args,**kwargs)
    assert update(tmp_path,'2026-09-08T01:09:00Z',collector=capture)['status']=='WAIT_CLOSED_HOUR_PUBLICATION'
    first=update(tmp_path,'2026-09-08T01:10:00Z',collector=capture)
    assert first['core_complete'] and first['decision_replay'] is False
    assert called[0][0][1:3]==(START,START+HOUR)
    assert update(tmp_path,'2026-09-08T01:45:00Z',collector=capture)['status']=='NO_OP_ALREADY_CAPTURED'
    assert len(called)==1
    assert json.loads((tmp_path/'state.json').read_text())['daily_requests']['2026-09-08']==14

def test_lock_conflict_makes_zero_requests(tmp_path):
    with (tmp_path/'writer.lock').open('w') as stream:
        fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
        assert update(tmp_path,'2026-09-08T01:15:00Z')['status']=='LOCK_CONFLICT'

def test_permanent_endpoint_circuit_and_recovery_preserves_old_capture(tmp_path):
    def fail(root,*args,**kwargs):
        r=fake_capture(root,*args,**kwargs);r['errors']={'BTCUSDT-mark':'HTTP_403'};return r
    assert update(tmp_path,'2026-09-08T01:15:00Z',collector=fail)['status']=='BLOCKED_DATA'
    state=json.loads((tmp_path/'state.json').read_text())
    assert 'BTCUSDT-mark' in state['circuits']
    assert 'last_complete_end' not in state
    def inspect(root,*args,**kwargs):
        assert 'BTCUSDT-mark' in kwargs['circuits'];return fake_capture(root,*args,**kwargs)
    update(tmp_path,'2026-09-08T02:15:00Z',collector=inspect)
    assert (tmp_path/'20260908T010000Z'/'receipt.json').exists()

def test_interrupted_capture_keeps_reservation_and_is_not_replayed(tmp_path):
    def die(root,*args,**kwargs):root.mkdir();raise KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):update(tmp_path,'2026-09-08T01:15:00Z',collector=die)
    assert json.loads((tmp_path/'state.json').read_text())['daily_requests']['2026-09-08']==24
    assert update(tmp_path,'2026-09-08T01:30:00Z')['status']=='INTERRUPTED_CAPTURE_RETAINED'

def test_late_incremental_observation_cannot_create_a_past_signal():
    from lab.perp_data import observed_availability
    rows=[{'available_at':'2026-09-08T01:01:00Z','fetched_at':'2026-09-08T01:15:00Z','quality':'ASSUMPTION'}]
    assert observed_availability(rows)[0]['available_at']=='2026-09-08T01:15:00Z'
    assert rows[0]['historical_available_at_assumption']=='2026-09-08T01:01:00Z'

def test_transient_http_retries_once_and_records_actual_calls(tmp_path,monkeypatch):
    import io
    from urllib.error import HTTPError
    import lab.perp_data as module
    attempts=[]
    def bad(req,timeout):
        attempts.append(req.full_url)
        raise HTTPError(req.full_url,503,'temporary',{},io.BytesIO(b'{}'))
    monkeypatch.setattr(module,'public_open',bad);monkeypatch.setattr(module.time,'sleep',lambda _:None)
    cap=module.Capture(tmp_path/'capture',START,START+HOUR,max_requests=2)
    with pytest.raises(RuntimeError,match='HTTP_503'):cap.get('test',module.BINANCE+'/fapi/v1/time')
    assert cap.calls==2 and len(attempts)==2
    assert len((cap.root/'requests.jsonl').read_text().splitlines())==2

def test_permanent_http_error_has_no_retry(tmp_path,monkeypatch):
    import io
    from urllib.error import HTTPError
    import lab.perp_data as module
    def bad(req,timeout):raise HTTPError(req.full_url,403,'denied',{},io.BytesIO(b'{}'))
    monkeypatch.setattr(module,'public_open',bad)
    cap=module.Capture(tmp_path/'capture',START,START+HOUR,max_requests=2)
    with pytest.raises(RuntimeError,match='HTTP_403'):cap.get('test',module.BINANCE+'/fapi/v1/time')
    assert cap.calls==1

def test_raw_captures_cannot_be_written_under_a_git_checkout(tmp_path):
    from lab.perp_data import Capture
    (tmp_path/'.git').mkdir()
    with pytest.raises(ValueError,match='RUNTIME_MUST_BE_OUTSIDE_GIT'):
        Capture(tmp_path/'raw-data',START,START+HOUR)
    assert not (tmp_path/'raw-data').exists()

def test_committed_success_dedup_returns_explicit_core_evidence(tmp_path):
    update(tmp_path,'2026-09-08T01:15:00Z',collector=fake_capture)
    result=update(tmp_path,'2026-09-08T01:30:00Z')
    assert result['status']=='NO_OP_ALREADY_CAPTURED'
    assert result['core_complete'] is True and result['requests']==0
    assert Path(result['receipt']).name=='update-receipt.json'


def test_intermediate_endpoint_receipt_is_not_committed_data_readiness(tmp_path):
    def interrupt_after_partial_receipt(root,*args,**kwargs):
        root.mkdir()
        (root/'receipt.json').write_text(json.dumps({'status':'CAPTURED_WITH_LIMITATIONS','datasets':{'BTCUSDT-ohlcv':{'rows':1}}}))
        raise KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        update(tmp_path,'2026-09-08T01:15:00Z',collector=interrupt_after_partial_receipt)
    result=update(tmp_path,'2026-09-08T01:30:00Z')
    assert result['status']=='INTERRUPTED_CAPTURE_RETAINED'
    assert result['core_complete'] is False and result['requests']==0 and result['receipt'] is None
    assert json.loads((tmp_path/'state.json').read_text())['daily_requests']['2026-09-08']==24


def test_committed_failed_capture_dedup_keeps_failure_and_does_not_retry(tmp_path):
    def fail(root,*args,**kwargs):
        r=fake_capture(root,*args,**kwargs)
        r['errors']={'BTCUSDT-mark':'HTTP_403'}
        return r
    update(tmp_path,'2026-09-08T01:15:00Z',collector=fail)
    result=update(tmp_path,'2026-09-08T01:30:00Z')
    assert result['status']=='NO_OP_BLOCKED_DATA'
    assert result['core_complete'] is False and result['requests']==0
    assert result['errors']=={'BTCUSDT-mark':'HTTP_403'}
    assert Path(result['receipt']).is_file()


def test_instrument_circuit_prevents_exchange_info_request(tmp_path,monkeypatch):
    import lab.perp_data as module
    def no_request(*args,**kwargs):raise AssertionError('circuit made a request')
    monkeypatch.setattr(module.Capture,'get',no_request)
    result=module.collect(tmp_path/'capture',START,START+HOUR,24,incremental=True,
                          circuits={'instrument_rules':{'reason':'HTTP_403'}})
    assert result['status']=='BLOCKED_DATA' and result['requests']==0
    assert result['errors']=={'instrument_rules':'CIRCUIT_OPEN'}
