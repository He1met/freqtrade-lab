#!/usr/bin/env python3
"""Frozen three-event USDC observation; one-shot acquisition, no trading."""
import argparse
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal as D, InvalidOperation
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
from urllib.parse import urlencode
from issue147_diagnostic import COSTS, deadline, event_return, sha, stats

REPO = Path(__file__).resolve().parents[1]
ROOT = Path('/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue155-forward-v2')
BINDINGS = ['scripts/issue155_forward.py', 'scripts/issue147_diagnostic.py',
            'docs/protocols/issue155-usdc-observation-v2.md']
CAPS = dict(gets=6, bytes=6*1048576, per_get_bytes=1048576, per_get_seconds=20,
            retries=0, per_collection_seconds=60, analyses=3, per_analysis_seconds=180,
            total_analysis_seconds=540, total_task_seconds=900)


def now():
    return datetime.now(timezone.utc)


def dt(s):
    return datetime.fromisoformat(s.replace('Z', '+00:00'))


def stamp(t):
    return t.isoformat()


def month(d, n):
    y, m = divmod(d.year*12+d.month-1+n, 12)
    return date(y, m+1, 1)


def at(d, hour=0, minute=0):
    return datetime(d.year, d.month, d.day, hour, minute, tzinfo=timezone.utc)


def slots():
    result = []
    for i in range(3):
        m = month(date(2026, 10, 1), i)
        entry, end = at(m.replace(day=8), 1), at(month(m, 1).replace(day=8), 1)
        first, last = month(m, -2 if i == 0 else -1), m-timedelta(days=1)
        q = dict(assets='usdc_eth', metrics='SplyCur', frequency='1d',
                 start_time=first.isoformat(), end_time=last.isoformat(), page_size=10000)
        result.append(dict(id='supply-'+m.strftime('%Y-%m'), kind='supply',
                           start=stamp(at(m.replace(day=7))), stop=stamp(at(m.replace(day=8))),
                           first=first.isoformat(), last=last.isoformat(),
                           url='https://community-api.coinmetrics.io/v4/timeseries/asset-metrics?'+urlencode(q)))
        start = end.replace(hour=2, minute=10)
        q = dict(symbol='ETHUSDT', interval='1h', startTime=int(entry.timestamp()*1000),
                 endTime=int(end.timestamp()*1000), limit=1000)
        result.append(dict(id='price-'+m.strftime('%Y-%m'), kind='price',
                           start=stamp(start), stop=stamp(start+timedelta(days=1)),
                           entry=stamp(entry), exit=stamp(end),
                           url='https://api.binance.com/api/v3/klines?'+urlencode(q)))
    return sorted(result, key=lambda s: (s['start'], s['id']))


def save(path, data):
    """Atomic terminal/control publication; callers hold the root lock."""
    path = Path(path)
    if path.exists():
        raise FileExistsError(path)
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, prefix='.'+path.name, delete=False) as f:
        json.dump(data, f, indent=2, default=str, allow_nan=False)
        f.write('\n'); f.flush(); os.fsync(f.fileno())
        name = f.name
    os.replace(name, path)
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def read(path):
    return json.loads(Path(path).read_text(), parse_float=D)


def claim(path):
    path.mkdir()
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def check(path, digest):
    if sha(path) != digest:
        raise ValueError('freeze SHA mismatch')
    m = read(path)
    if set(m) != {'version', 'root', 'caps', 'slots', 'bindings', 'authorization'}:
        raise ValueError('manifest schema')
    if m['version'] != 2 or m['root'] != str(ROOT) or m['caps'] != CAPS or m['slots'] != slots():
        raise ValueError('frozen scope mismatch')
    if set(m['bindings']) != set(BINDINGS):
        raise ValueError('binding scope mismatch')
    for p, h in m['bindings'].items():
        if sha(REPO/p) != h:
            raise ValueError('binding drift: '+p)
    return m


@contextmanager
def locked(root):
    root.mkdir(parents=True, exist_ok=True)
    with (root/'lock').open('a') as f:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def supply_check(payload, slot):
    if not isinstance(payload, dict) or set(payload)-{'data', 'next_page_token', 'next_page_url'} or not isinstance(payload.get('data'), list) or not payload['data']:
        raise ValueError('supply envelope/empty')
    if payload.get('next_page_token') or payload.get('next_page_url'):
        raise ValueError('pagination forbidden')
    first, last = date.fromisoformat(slot['first']), date.fromisoformat(slot['last'])
    records, bad, seen = {}, {}, set()
    for row in payload['data']:
        if not isinstance(row, dict) or set(row) != {'asset', 'time', 'SplyCur'} or row['asset'] != 'usdc_eth':
            raise ValueError('supply identity/schema')
        label = row['time']
        if not isinstance(label, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T00:00:00(?:\.0{1,9})?(?:Z|\+00:00)', label):
            raise ValueError('UTC daily label')
        day = date.fromisoformat(label[:10])
        if not first <= day <= last:
            raise ValueError('supply out of range')
        key = day.strftime('%Y-%m')
        if day in seen:
            bad.setdefault(key, []).append('DUPLICATE_DATE')
        seen.add(day)
        try:
            if isinstance(row['SplyCur'], bool):
                raise ValueError('bool')
            value = D(str(row['SplyCur']))
            if not value.is_finite() or value <= 0:
                raise ValueError('invalid value')
            records[day] = value
        except (ValueError, InvalidOperation):
            bad.setdefault(key, []).append('INVALID_SUPPLY')
    for n in range((last-first).days+1):
        day = first+timedelta(days=n)
        if day not in seen:
            bad.setdefault(day.strftime('%Y-%m'), []).append('MISSING_DATE')
    months = {}
    m = first
    while m <= last:
        key = m.strftime('%Y-%m')
        end = month(m, 1)-timedelta(days=1)
        months[key] = dict(value=None if key in bad else records[end], issues=sorted(set(bad.get(key, []))))
        m = month(m, 1)
    return dict(grade='AS_OBSERVED_NOT_FIRST_PUBLISHED', months=months)


def price_check(payload, slot):
    if not isinstance(payload, list) or not payload:
        raise ValueError('price envelope/empty')
    begin, end = [int(dt(slot[k]).timestamp()*1000) for k in ('entry', 'exit')]
    bars = {}
    for row in payload:
        if not isinstance(row, list) or len(row) != 12 or type(row[0]) is not int or type(row[6]) is not int:
            raise ValueError('kline schema')
        t = row[0]
        if not begin <= t <= end or t % 3600000 or t in bars or not t <= row[6] < t+3600000:
            raise ValueError('kline boundary/duplicate')
        if isinstance(row[1], bool):
            raise ValueError('boolean price')
        o = D(str(row[1]))
        if not o.is_finite() or o <= 0:
            raise ValueError('invalid open')
        if t < end:
            if any(isinstance(v, bool) for v in row[2:6]):
                raise ValueError('boolean OHLCV')
            h, l, c, v = map(lambda v: D(str(v)), row[2:6])
            if not all(x.is_finite() and x > 0 for x in (h, l, c)) or not v.is_finite() or v < 0 or not l <= min(o, c) <= max(o, c) <= h:
                raise ValueError('invalid OHLCV')
        bars[t] = dict(open=o, full=row[6] == t+3599999)
    bad = sum(t not in bars or not bars[t]['full'] for t in range(begin, end, 3600000))
    return dict(bad_held_hours=bad, entry_open=bars.get(begin, {}).get('open'),
                exit_open=bars.get(end, {}).get('open'), expected_held_hours=(end-begin)//3600000)


def download(slot, target):
    """The only network boundary. No curlrc, retries, redirects or pagination."""
    p = subprocess.run(['curl', '-q', '--silent', '--show-error', '--fail', '--max-time', '20',
                        '--max-filesize', '1048576', '--retry', '0', '--proto', '=https',
                        '--dump-header', str(target/'headers.txt'), '--output', str(target/'response.json'),
                        '--write-out', '%{http_code}', slot['url']], capture_output=True, text=True, timeout=22)
    return dict(returncode=p.returncode, http_status=p.stdout.strip(), stderr=p.stderr)


def acquire(root, slot, digest, clock, transport):
    r = root/slot['id']
    claim(r)  # Durable claim consumes this slot even if the process dies before HTTP.
    save(r/'attempt.json', dict(at=stamp(clock()), freeze_sha256=digest, slot=slot, get_reserved=1))
    try:
        with deadline(CAPS['per_collection_seconds']):
            if not dt(slot['start']) <= clock() < dt(slot['stop']):
                raise ValueError('window closed before HTTP')
            info = transport(slot, r)
            done = clock()
            raw = r/'response.json'
            info.update(at=stamp(done), bytes=raw.stat().st_size if raw.exists() else 0,
                        response_sha256=sha(raw) if raw.exists() else None)
            save(r/'receipt.json', info)
            if info['returncode'] or info['http_status'] != '200' or info['bytes'] > CAPS['per_get_bytes']:
                raise ValueError('HTTP/status/byte cap')
            if not dt(slot['start']) <= done < dt(slot['stop']):
                raise ValueError('LATE_SNAPSHOT_OR_PRICE')
            parsed = read(raw)
            result = supply_check(parsed, slot) if slot['kind'] == 'supply' else price_check(parsed, slot)
            save(r/'check.json', result)
            if clock() >= dt(slot['stop']):
                raise ValueError('check persisted after cutoff')
            save(r/'terminal.json', dict(status='CHECKED', at=stamp(clock()),
                 receipt_sha256=sha(r/'receipt.json'), check_sha256=sha(r/'check.json')))
    except Exception as e:
        save(r/'terminal.json', dict(status='UNKNOWN', reason=type(e).__name__+': '+str(e)))


def checked(root, slot, digest):
    r = root/slot['id']
    terminal = read(r/'terminal.json')
    if terminal['status'] != 'CHECKED':
        return None
    attempt, receipt = read(r/'attempt.json'), read(r/'receipt.json')
    if attempt['freeze_sha256'] != digest or attempt['slot'] != slot or not dt(slot['start']) <= dt(attempt['at']) < dt(slot['stop']):
        raise ValueError('attempt identity/time drift')
    if not dt(slot['start']) <= dt(receipt['at']) <= dt(terminal['at']) < dt(slot['stop']):
        raise ValueError('receipt cutoff drift')
    for name, expected in [('response.json', receipt['response_sha256']), ('receipt.json', terminal['receipt_sha256']), ('check.json', terminal['check_sha256'])]:
        if sha(r/name) != expected:
            raise ValueError('captured source drift: '+name)
    return read(r/'check.json')


def score_event(root, slot, digest):
    m = date.fromisoformat(slot['id'][6:]+'-01')
    keys = [month(m, k).strftime('%Y-%m') for k in (-2, -1)]
    inputs, evidence = {}, {}
    for s in slots():
        if s['kind'] != 'supply' or dt(s['stop']) > at(m.replace(day=8)) or not any(s['first'][:7] <= k <= s['last'][:7] for k in keys):
            continue
        c = checked(root, s, digest)
        evidence[s['id']] = sha(root/s['id']/'terminal.json')
        if c:
            inputs.update(c['months'])
    a, b = [inputs.get(k, {}).get('value') for k in keys]
    growth = None if a is None or b is None else D(str(b))/D(str(a))-1
    price = checked(root, slot, digest)
    evidence[slot['id']] = sha(root/slot['id']/'terminal.json')
    reasons = []
    if growth is None:
        reasons.append('SUPPLY_MONTH_UNKNOWN')
    if price is None or price['bad_held_hours'] or price['entry_open'] is None or price['exit_open'] is None:
        reasons.append('PRICE_UNKNOWN')
    return dict(month=m.strftime('%Y-%m'), entry=slot['entry'], exit=slot['exit'],
                decision=stamp(at(m.replace(day=8))), supply_growth=growth,
                group=None if growth is None else 'EXPAND' if growth > 0 else 'OTHER',
                status='UNKNOWN' if reasons else 'SCORED', reasons=reasons, evidence=evidence,
                costs=None if reasons else {c: event_return(D(str(price['entry_open'])), D(str(price['exit_open'])), c) for c in COSTS})


def score_once(root, slot, digest, clock):
    r = root/('analysis-'+slot['id'][6:]); claim(r)
    save(r/'attempt.json', dict(at=stamp(clock()), freeze_sha256=digest, seconds=180))
    started = time.monotonic()
    try:
        with deadline(180):
            event = score_event(root, slot, digest)
            events = []
            for s in slots():
                if s['kind'] == 'price' and s['id'] < slot['id']:
                    prior = root/('analysis-'+s['id'][6:])
                    t = read(prior/'terminal.json')
                    if t['status'] == 'REPORTED':
                        if sha(prior/'report.json') != t['report_sha256']:
                            raise ValueError('prior report drift')
                        events.append(read(prior/'report.json')['event'])
                    else:
                        events.append(dict(month=s['id'][6:], status='UNKNOWN', group=None, costs=None,
                                           reasons=['PRIOR_ANALYSIS_FAILED_NO_RETRY']))
            events.append(event)
            groups = {g: sum(e['status'] == 'SCORED' and e['group'] == g for e in events) for g in ('EXPAND', 'OTHER')}
            summary = {c: {g: stats([(e['month'], D(str(e['costs'][c]['net']))) for e in events if e['status'] == 'SCORED' and e['group'] == g]) for g in groups} for c in COSTS}
            for c in summary:
                a, b = [summary[c][g]['mean'] for g in ('EXPAND', 'OTHER')]
                summary[c]['expand_minus_other'] = None if a is None or b is None else a-b
            report = dict(event=event, cumulative_events=events, groups=groups, costs=summary,
                          verdict='UNDERPOWERED', monthly_report_not_significance_test=True,
                          period_coverage=[e['month'] for e in events],
                          wallet=False, drawdown=None, risk_qualified=False,
                          authorized_batch_complete=slot['id'] == 'price-2026-12')
            save(r/'report.json', report)
            save(r/'terminal.json', dict(status='REPORTED', verdict='UNDERPOWERED',
                 elapsed_seconds=time.monotonic()-started, report_sha256=sha(r/'report.json')))
    except Exception as e:
        save(r/'terminal.json', dict(status='UNKNOWN', reason=type(e).__name__+': '+str(e)))


def tick(root, digest, clock=now, transport=download):
    if root.is_symlink() or (root.exists() and any(p.is_symlink() for p in root.iterdir())):
        raise ValueError('runtime symlink forbidden')
    with locked(root):
        identity = dict(freeze_sha256=digest, version=2)
        if not (root/'freeze.json').exists():
            if set(p.name for p in root.iterdir())-{'lock'}:
                raise ValueError('unbound nonempty runtime')
            save(root/'freeze.json', identity)
        elif read(root/'freeze.json') != identity:
            raise ValueError('runtime freeze drift')
        # Existing incomplete claims cannot retry a possibly issued HTTP or analysis.
        for name in [s['id'] for s in slots()]+['analysis-'+s['id'][6:] for s in slots() if s['kind'] == 'price']:
            r = root/name
            if r.exists() and not (r/'terminal.json').exists():
                save(r/'terminal.json', dict(status='UNKNOWN', reason='INTERRUPTED_NO_RETRY'))
        for s in slots():
            r = root/s['id']
            if r.exists():
                continue
            t = clock()
            if t >= dt(s['stop']):
                claim(r); save(r/'terminal.json', dict(status='UNKNOWN', reason='MISSED_WINDOW', at=stamp(t)))
            elif t >= dt(s['start']):
                acquire(root, s, digest, clock, transport)
        for s in slots():
            if s['kind'] == 'price' and clock() >= dt(s['start']) and (root/s['id']/'terminal.json').exists() and not (root/('analysis-'+s['id'][6:])).exists():
                score_once(root, s, digest, clock)
        return status(root)


def status(root):
    records = {}
    for s in slots():
        p = root/s['id']/'terminal.json'
        records[s['id']] = read(p) if p.exists() else {'status': 'PENDING'}
    analyses = {}
    for s in slots():
        if s['kind'] == 'price':
            p = root/('analysis-'+s['id'][6:])/'terminal.json'
            analyses[s['id'][6:]] = read(p) if p.exists() else {'status': 'PENDING'}
            if p.exists() and analyses[s['id'][6:]]['status'] == 'REPORTED':
                analyses[s['id'][6:]]['report_path'] = str(p.parent/'report.json')
    return dict(slots=records, analyses=analyses, get_slots_claimed=sum((root/s['id']).exists() for s in slots()),
                note='claims include missed/uncertain slots; no retry or budget rollover', verdict='UNDERPOWERED')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=['check', 'status', 'tick'])
    p.add_argument('--manifest', required=True); p.add_argument('--sha256', required=True)
    a = p.parse_args(); check(a.manifest, a.sha256)
    if a.command == 'status' and (ROOT/'freeze.json').exists() and read(ROOT/'freeze.json') != dict(freeze_sha256=a.sha256, version=2):
        raise ValueError('runtime freeze drift')
    result = {'status': 'CONTROL_PASS_NO_HTTP'} if a.command == 'check' else status(ROOT) if a.command == 'status' else tick(ROOT, a.sha256)
    print(json.dumps(result, indent=2, default=str))


if __name__ == '__main__':
    main()
