"""Issue93-only execution protection around the unchanged Profile producer.

--self-test never calls a network endpoint. --acquire requires separate explicit
supervisor authorization; the preparation task does not invoke that action.
"""
import hashlib
import json
import os
import signal
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

import requests

ROOT = Path(__file__).resolve().parent
PROJECT = Path('/Users/shenjianpeng/.codex/worktrees/3c7c/freqtrade-lab')
MAX_ATTEMPTS = 24
MAX_SECONDS = 1800


class BudgetStop(BaseException):
    pass


def persist(handle, record):
    handle.write((json.dumps(record, sort_keys=True, separators=(',', ':')) + '\n').encode())
    handle.flush()
    os.fsync(handle.fileno())


@contextmanager
def bounded_requests(log, *, seconds=MAX_SECONDS):
    original = requests.Session.request
    old_handler = signal.getsignal(signal.SIGALRM)
    if signal.getitimer(signal.ITIMER_REAL) != (0.0, 0.0):
        raise RuntimeError('An existing process timer prevents safe acquisition')
    state = {'attempts': 0, 'timed_out': False}

    def alarm(_signum, _frame):
        state['timed_out'] = True
        raise BudgetStop('SOURCE_DEADLINE_EXCEEDED')

    def guarded(session, method, url, *args, **kwargs):
        endpoint = urlsplit(url)
        if method.upper() != 'GET' or endpoint.scheme != 'https' or endpoint.hostname != 'www.okx.com' or endpoint.port not in (None, 443) or endpoint.path not in {'/api/v5/public/instruments', '/api/v5/market/history-candles'}:
            raise BudgetStop('SOURCE_ENDPOINT_REJECTED')
        query = parse_qs(endpoint.query)
        if kwargs.get('params'):
            raise BudgetStop('SOURCE_EXTERNAL_QUERY_REJECTED')
        if endpoint.path == '/api/v5/public/instruments':
            if query != {'instType':['SPOT'],'instId':['LTC-USDT']}:
                raise BudgetStop('SOURCE_INSTRUMENT_REJECTED')
        else:
            if set(query) != {'instId','bar','limit','before','after'} or query['instId'] != ['LTC-USDT'] or query['bar'] != ['1Dutc']:
                raise BudgetStop('SOURCE_CANDLE_IDENTITY_REJECTED')
            try:
                assert all(len(query[k]) == 1 for k in ('limit','before','after'))
                count, lower, upper = (int(query[k][0]) for k in ('limit','before','after'))
                start = int(datetime(2021,3,22,tzinfo=timezone.utc).timestamp()*1000)
                stop = int(datetime(2025,1,1,tzinfo=timezone.utc).timestamp()*1000)
                assert 1 <= count <= 100 and start-1 <= lower < upper <= stop
                assert (lower+1-start) % 86400000 == 0 and (upper-start) % 86400000 == 0
                assert upper-(lower+1) == count*86400000
            except (AssertionError, ValueError):
                raise BudgetStop('SOURCE_WINDOW_REJECTED')
        if kwargs.get('allow_redirects') is not False:
            raise BudgetStop('SOURCE_REDIRECT_POLICY_MISSING')
        retry = session.get_adapter(url).max_retries
        if retry.total != 0:
            raise BudgetStop('HIDDEN_HTTP_RETRY_REJECTED')
        if state['attempts'] >= MAX_ATTEMPTS:
            persist(log, {'event': 'REJECTED_BEFORE_NETWORK', 'attempt': state['attempts'] + 1})
            raise BudgetStop('SOURCE_REQUEST_BUDGET_EXCEEDED')
        state['attempts'] += 1
        record = {'event': 'ATTEMPT_BEFORE_NETWORK', 'attempt': state['attempts'],
                  'utc': datetime.now(timezone.utc).isoformat(), 'method': 'GET',
                  'endpoint': endpoint.scheme + '://' + endpoint.hostname + endpoint.path, 'query': query}
        # A failed write/fsync raises before original request, so fail closed.
        persist(log, record)
        try:
            response = original(session, method, url, *args, **kwargs)
        except BaseException:
            persist(log, {'event': 'ATTEMPT_FAILED', 'attempt': state['attempts']})
            raise
        persist(log, {'event': 'ATTEMPT_RETURNED', 'attempt': state['attempts'],
                      'status_code': response.status_code})
        return response

    requests.Session.request = guarded
    signal.signal(signal.SIGALRM, alarm)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield state
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old_handler)
        requests.Session.request = original


def self_test():
    import tempfile
    from types import SimpleNamespace
    original = requests.Session.request
    calls = []
    def offline(_session, *_args, **_kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise requests.ConnectionError('synthetic failure')
        return SimpleNamespace(status_code=200)
    requests.Session.request = offline
    try:
        with tempfile.TemporaryFile() as log, requests.Session() as session:
            with bounded_requests(log) as state:
                for _ in range(24):
                    try:
                        session.request('GET', 'https://www.okx.com/api/v5/public/instruments?instType=SPOT&instId=LTC-USDT', allow_redirects=False)
                    except requests.ConnectionError:
                        pass
                assert len(calls) == state['attempts'] == 24
                try:
                    session.request('GET', 'https://www.okx.com/api/v5/public/instruments?instType=SPOT&instId=LTC-USDT', allow_redirects=False)
                except BudgetStop as error:
                    assert str(error) == 'SOURCE_REQUEST_BUDGET_EXCEEDED'
                else:
                    raise AssertionError('25th request was not rejected')
                assert len(calls) == 24
            log.seek(0)
            records = [json.loads(line) for line in log]
            assert sum(row['event'] == 'ATTEMPT_BEFORE_NETWORK' for row in records) == 24
            assert any(row['event'] == 'ATTEMPT_FAILED' for row in records)
        started = time.monotonic()
        with tempfile.TemporaryFile() as log:
            try:
                with bounded_requests(log, seconds=.03) as state:
                    time.sleep(1)
                    raise AssertionError('deadline did not stop execution')
            except BudgetStop as error:
                assert str(error) == 'SOURCE_DEADLINE_EXCEEDED'
            assert state['timed_out'] and state['attempts'] == 0
        assert time.monotonic() - started < .8
        assert signal.getitimer(signal.ITIMER_REAL) == (0.0, 0.0)
        assert requests.Session.request is offline
        result = {'tests_passed':2,'network_requests':0,'original_stub_calls':24,
                          'failed_attempt_counted':True,'attempt_25_rejected_before_original':True,
                          'deadline_triggered':True,'timer_and_patch_restored':True}
        (ROOT/'guard-self-test.json').write_text(json.dumps(result,sort_keys=True)+'\n')
        print(json.dumps(result))
    finally:
        requests.Session.request = original


def acquire():
    from scripts import fetch_okx_profile_data as producer
    frozen = json.loads((ROOT / 'freeze-receipt.json').read_bytes())
    for name, expected in frozen['files_sha256'].items():
        assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest() == expected
    from binding import logical_snapshot
    assert frozen['approvals']['source'] is True and frozen['approvals']['search'] is False
    assert logical_snapshot(ROOT/'research.sqlite', frozen['profile_id'], frozen['candidate_id']) == json.loads((ROOT/'database-logical-snapshot.json').read_text())
    assert not (ROOT/'source').exists()
    for original_path, expected in frozen['producer_files_sha256'].items():
        assert hashlib.sha256(Path(original_path).read_bytes()).hexdigest() == expected
    assert producer.validate_runtime() == frozen['native_identity']
    original_guard = producer.install_request_guard
    def guard(exchange):
        assert exchange.options.get('maxRetriesOnFailure', 0) == 0
        assert all(adapter.max_retries.total == 0 for adapter in exchange.session.adapters.values())
        original_guard(exchange)
    producer.install_request_guard = guard
    sys.argv = ['fetch_okx_profile_data.py', '--output-root', str(ROOT/'source'),
                '--profile-database', frozen['database'], '--profile-id', frozen['profile_id'],
                '--window-spec', str(ROOT/'window-spec.json'), '--pre-roll-candles', '40',
                '--single-baseline', str(ROOT/'single-baseline.json'),
                '--economic-gate', str(ROOT/'economic-gate.json')]
    with (ROOT/'source-attempts.jsonl').open('xb') as log:
        try:
            with bounded_requests(log) as state:
                producer.main()
            persist(log, {'event':'SOURCE_COMPLETED','attempts':state['attempts']})
        except BaseException as error:
            persist(log, {'event':'SOURCE_STOPPED','response_body_logged':False,
                          'error_type':type(error).__name__})
            raise SystemExit('SOURCE_STOPPED; inspect metadata-only attempt ledger; no automatic retry') from None
        finally:
            producer.install_request_guard = original_guard


if __name__ == '__main__':
    if sys.argv[1:] == ['--self-test']:
        self_test()
    elif sys.argv[1:] == ['--acquire']:
        acquire()
    else:
        raise SystemExit('Choose --self-test or separately authorized --acquire')
