import fcntl
import json
from datetime import date, timedelta
from decimal import Decimal as D
from pathlib import Path
import sys
import pytest
sys.path.insert(0, str(Path(__file__).parents[1]/'scripts'))
import issue155_forward as p


def fixture(slot):
    if slot['kind'] == 'supply':
        first, last = map(date.fromisoformat, [slot['first'], slot['last']])
        return {'data': [dict(asset='usdc_eth', time=(first+timedelta(days=i)).isoformat()+'T00:00:00Z',
                             SplyCur=str(100+(first+timedelta(days=i)).month)) for i in range((last-first).days+1)]}
    begin, end = [int(p.dt(slot[k]).timestamp()*1000) for k in ('entry', 'exit')]
    return [[t, '100', '101', '99', '100', '1', t+3599999, '100', 1, '0', '0', '0'] for t in range(begin, end+1, 3600000)]


class Harness:
    def __init__(self, root):
        self.root, self.calls, self.t = root, [], p.dt('2026-09-08T00:00:00Z')
    def transport(self, slot, target):
        self.calls.append(slot['id'])
        p.save(target/'response.json', fixture(slot))
        return dict(returncode=0, http_status='200', stderr='')
    def run(self, t=None):
        if t is not None:
            self.t = p.dt(t)
        return p.tick(self.root, 'freeze-test', lambda: self.t, self.transport)


def test_calendar_and_full_six_slot_lifecycle_no_replay(tmp_path):
    h = Harness(tmp_path/'run')
    assert h.run()['get_slots_claimed'] == 0 and not h.calls
    assert len(p.slots()) == 6
    for s in p.slots():
        h.run(s['start']); h.run()
    assert len(h.calls) == 6 and len(set(h.calls)) == 6
    final = p.read(h.root/'analysis-2026-12/report.json')
    assert final['authorized_batch_complete'] and final['verdict'] == 'UNDERPOWERED'
    assert final['groups'] == {'EXPAND': 3, 'OTHER': 0}
    assert len(final['cumulative_events']) == 3 and final['drawdown'] is None
    event = final['cumulative_events'][0]
    assert event['entry'] == '2026-10-08T01:00:00+00:00'
    assert event['supply_growth'] == str(D(109)/D(108)-1)
    f, s = p.COSTS['base']
    assert abs(D(event['costs']['base']['net'])-((1-s)/(1+s)*(1-f)**2-1)) < D('1e-48')
    h.run('2028-10-09T00:00:00Z')
    assert len(h.calls) == 6 and len(list(h.root.glob('analysis-*'))) == 3


def test_missed_all_windows_do_not_fetch_or_rescue(tmp_path):
    h = Harness(tmp_path/'run')
    result = h.run('2027-02-01T00:00:00Z')
    assert not h.calls
    assert all(t['reason'] == 'MISSED_WINDOW' for t in result['slots'].values())
    final = p.read(h.root/'analysis-2026-12/report.json')
    assert final['groups'] == {'EXPAND': 0, 'OTHER': 0}
    assert all(e['status'] == 'UNKNOWN' and e['costs'] is None for e in final['cumulative_events'])


def test_process_interruption_consumes_claim_without_retry(tmp_path):
    h = Harness(tmp_path/'run'); h.run()
    s = p.slots()[0]; p.claim(h.root/s['id'])
    h.run(s['start'])
    assert not h.calls
    assert p.read(h.root/s['id']/'terminal.json')['reason'] == 'INTERRUPTED_NO_RETRY'


def test_failed_http_and_late_persistence_never_retry(tmp_path):
    h = Harness(tmp_path/'run'); s = p.slots()[0]
    def late(slot, target):
        result = Harness.transport(h, slot, target)
        h.t = p.dt(slot['stop'])
        return result
    h.transport = late
    h.run(s['start']); h.run()
    assert len(h.calls) == 1
    assert p.read(h.root/s['id']/'terminal.json')['status'] == 'UNKNOWN'
    assert not (h.root/s['id']/'check.json').exists()


def test_http_failure_and_byte_cap_are_terminal(tmp_path):
    h = Harness(tmp_path/'run'); s = p.slots()[0]
    def fail(slot, target):
        result = Harness.transport(h, slot, target)
        result['http_status'] = '429'
        return result
    h.transport = fail; h.run(s['start']); h.run()
    assert len(h.calls) == 1 and p.read(h.root/s['id']/'terminal.json')['status'] == 'UNKNOWN'
    h2 = Harness(tmp_path/'large')
    def large(slot, target):
        h2.calls.append(slot['id']); (target/'response.json').write_bytes(b' '*(1048576+1))
        return dict(returncode=0, http_status='200', stderr='')
    h2.transport = large; h2.run(s['start']); h2.run()
    assert len(h2.calls) == 1 and p.read(h2.root/s['id']/'terminal.json')['status'] == 'UNKNOWN'


def test_supply_calendar_null_and_strict_schema():
    s = p.slots()[0]; x = fixture(s)
    x['data'].pop(0); x['data'].append(dict(x['data'][-1]))
    out = p.supply_check(x, s)
    assert all(v['value'] is None for v in out['months'].values())
    x = fixture(s); x['data'][0]['SplyCur'] = False
    assert p.supply_check(x, s)['months']['2026-08']['value'] is None
    x = fixture(s); x['data'][0]['SplyCur'] = 'NaN'
    assert p.supply_check(x, s)['months']['2026-08']['value'] is None
    for edit in [lambda x: x.update(next_page_url='https://example.invalid'),
                 lambda x: x['data'][0].update(asset='usdc'),
                 lambda x: x['data'][0].update(time='2026-08-01T01:00:00Z')]:
        x = fixture(s); edit(x)
        with pytest.raises(ValueError): p.supply_check(x, s)


def test_price_complete_held_hours_exit_open_and_invalid_boundaries():
    s = next(s for s in p.slots() if s['kind'] == 'price'); x = fixture(s)
    assert len(x) == 745
    assert p.price_check(x, s)['bad_held_hours'] == 0
    x[-1][6] -= 10  # Exit needs open only.
    x[-1][2:6] = [None]*4
    assert p.price_check(x, s)['bad_held_hours'] == 0
    x.pop(1)
    assert p.price_check(x, s)['bad_held_hours'] == 1
    x = fixture(s); x[0][6] -= 1
    assert p.price_check(x, s)['bad_held_hours'] == 1
    x = fixture(s); x.append(x[0])
    with pytest.raises(ValueError): p.price_check(x, s)
    x = fixture(s); x[0][0] -= 3600000
    with pytest.raises(ValueError): p.price_check(x, s)


def test_receipt_tampering_fails_analysis_no_retry(tmp_path):
    h = Harness(tmp_path/'run')
    h.run(p.slots()[0]['start'])
    response = h.root/p.slots()[0]['id']/'response.json'
    response.write_text('{}')
    for s in p.slots()[1:]: h.run(s['start'])
    assert p.read(h.root/'analysis-2026-10/terminal.json')['status'] == 'UNKNOWN'
    h.run(); assert len(h.calls) == 6


def test_partial_analysis_does_not_repeat_or_block_later_reports(tmp_path):
    h = Harness(tmp_path/'run'); h.run()
    p.claim(h.root/'analysis-2026-10')
    for s in p.slots(): h.run(s['start'])
    final = p.read(h.root/'analysis-2026-12/report.json')
    assert final['cumulative_events'][0]['reasons'] == ['PRIOR_ANALYSIS_FAILED_NO_RETRY']
    assert len(h.calls) == 6


def test_lock_freeze_and_nonempty_root_fail_before_network(tmp_path):
    h = Harness(tmp_path/'run'); h.run()
    with (h.root/'lock').open('a') as f:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(BlockingIOError): h.run(p.slots()[0]['start'])
    with pytest.raises(ValueError): p.tick(h.root, 'wrong', lambda: h.t, h.transport)
    assert not h.calls
    unbound = tmp_path/'unbound'; unbound.mkdir(); (unbound/'unexpected').touch()
    with pytest.raises(ValueError): p.tick(unbound, 'test', lambda: h.t, h.transport)


def test_download_has_exact_limits_no_user_curlrc_or_redirects(tmp_path, monkeypatch):
    calls = []
    def run(args, **kw):
        calls.append((args, kw))
        return type('Response', (), dict(returncode=0, stdout='200', stderr=''))()
    monkeypatch.setattr(p.subprocess, 'run', run)
    p.download(p.slots()[0], tmp_path)
    args, kw = calls[0]
    assert args[:2] == ['curl', '-q'] and '-L' not in args and '--location' not in args
    assert args[args.index('--retry')+1] == '0' and kw['timeout'] == 22
    assert args[args.index('--max-time')+1] == '20'
    assert args[args.index('--max-filesize')+1] == '1048576'


def test_control_binding_and_budget_drift_before_runtime(tmp_path, monkeypatch):
    monkeypatch.setattr(p, 'REPO', tmp_path)
    for f in p.BINDINGS:
        path = tmp_path/f; path.parent.mkdir(exist_ok=True, parents=True); path.write_text('fixture')
    m = dict(version=2, root=str(p.ROOT), caps=p.CAPS, slots=p.slots(), authorization='synthetic',
             bindings={f: p.sha(tmp_path/f) for f in p.BINDINGS})
    path = tmp_path/'manifest.json'; p.save(path, m)
    assert p.check(path, p.sha(path)) == m
    with pytest.raises(ValueError): p.check(path, 'wrong')
    m['caps'] = dict(p.CAPS, gets=7); path.write_text(json.dumps(m))
    with pytest.raises(ValueError): p.check(path, p.sha(path))
    m['caps'] = p.CAPS; path.write_text(json.dumps(m))
    (tmp_path/p.BINDINGS[0]).write_text('drift')
    with pytest.raises(ValueError): p.check(path, p.sha(path))
