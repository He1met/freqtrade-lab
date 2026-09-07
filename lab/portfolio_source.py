"""Bounded, public-only portfolio source capture. No native imports or scoring."""
import contextlib
import datetime as dt
from decimal import Decimal, InvalidOperation
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import time
import urllib.error
import urllib.parse
import urllib.request


class SourceError(ValueError):
    pass


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text())


def write_json(path, obj):
    path = Path(path)
    tmp = path.with_suffix(path.suffix + '.tmp')
    with tmp.open('w') as f:
        json.dump(obj, f, indent=2, sort_keys=True)
        f.write('\n')
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def ms(value):
    return int(dt.datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp() * 1000)


def check_scope(contract, snapshot, ledger_raw):
    if digest(ledger_raw) != snapshot['ledger_sha256']:
        raise SourceError('registry changed: full metadata re-review required')
    start, end = ms(contract['start']), ms(contract['end_exclusive'])
    for rule in snapshot['protections']:
        scope = rule['scope']
        if scope == 'GLOBAL':
            matches = True
        elif scope == 'EXACT_ASSET':
            matches = bool(set(rule['symbols']) & set(contract['symbols']))
        elif scope == 'EXACT_DOMAIN':
            matches = (rule['exchange'] == contract['exchange'] and
                       rule['instrument_type'] == contract['instrument_type'] and
                       bool(set(rule['symbols']) & set(contract['symbols'])))
        else:
            raise SourceError('unresolved registry scope')
        if matches and start < ms(rule['end_exclusive']) and ms(rule['start']) < end:
            raise SourceError('protected window collision: ' + str(rule['record_lines']))
    if snapshot['unresolved_candidate_overlap']:
        raise SourceError('unresolved overlapping protection')


@contextlib.contextmanager
def exclusive(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a') as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise SourceError('single worker lock held') from exc
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


class Budget:
    """Fixed global state: root and every attempt survive interruption.

    A request reserves the whole response ceiling before network I/O. A crash
    retains that charge; success reconciles to bytes actually read. No retries.
    """
    def __init__(self, path, root, limits, now=time.time):
        self.path, self.now, self.limits = Path(path), now, limits
        if self.path.exists():
            raise SourceError('acquisition already started; no reset/resume/new root')
        self.state = dict(root=str(Path(root).resolve()), started=now(), attempts=[],
                          charged_bytes=0, status='STARTED')
        write_json(self.path, self.state)

    def remaining_time(self):
        return self.limits['seconds'] - (self.now() - self.state['started'])

    def reserve(self, endpoint, params):
        if self.remaining_time() <= 0:
            raise SourceError('wall-clock budget exhausted')
        if len(self.state['attempts']) >= self.limits['gets']:
            raise SourceError('GET budget exhausted')
        cap = self.limits['response_bytes']
        if self.state['charged_bytes'] + cap > self.limits['total_bytes']:
            raise SourceError('decoded byte budget cannot cover next response')
        row = dict(number=len(self.state['attempts']) + 1, endpoint=endpoint,
                   params=params, status='RESERVED', reserved_at=self.now(), charged_bytes=cap)
        self.state['attempts'].append(row)
        self.state['charged_bytes'] += cap
        write_json(self.path, self.state)
        return row

    def finish(self, row, *, size, status, sha256=None, error=None, retry_after=None):
        self.state['charged_bytes'] += size - row['charged_bytes']
        row.update(charged_bytes=size, status=status, sha256=sha256,
                   error=error, retry_after=retry_after, finished_at=self.now())
        write_json(self.path, self.state)

    def terminal(self, status):
        self.state['status'] = status
        write_json(self.path, self.state)


@contextlib.contextmanager
def request_deadline(seconds):
    def expired(signum, frame):
        raise SourceError('request wall-clock deadline')
    previous = signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise SourceError('redirect forbidden; no unbudgeted GET')


class Fetcher:
    def __init__(self, budget, root):
        self.budget, self.root = budget, Path(root)
        self.last = None
        self.opener = urllib.request.build_opener(NoRedirect)

    def get(self, endpoint, params):
        if endpoint not in {'exchangeInfo', 'fundingInfo', 'klines', 'markPriceKlines', 'fundingRate'}:
            raise SourceError('endpoint outside contract')
        if self.last is not None:
            time.sleep(max(0, 1 - (time.monotonic() - self.last)))
        row = self.budget.reserve(endpoint, params)
        self.last = time.monotonic()
        deadline = time.monotonic() + min(20, self.budget.remaining_time())
        url = 'https://fapi.binance.com/fapi/v1/' + endpoint
        if params:
            url += '?' + urllib.parse.urlencode(params)
        request = urllib.request.Request(url, headers={'Accept-Encoding': 'identity',
                                                       'User-Agent': 'freqtrade-lab-bounded-source/1'})
        body = bytearray()
        try:
            with request_deadline(max(.001, deadline-time.monotonic())), self.opener.open(request, timeout=max(.001, deadline-time.monotonic())) as response:
                if response.status != 200:
                    raise SourceError('unexpected HTTP status')
                if response.headers.get('Content-Encoding', 'identity') != 'identity':
                    raise SourceError('unexpected encoding; decoded size unproven')
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise SourceError('20-second request deadline')
                    # SIGALRM covers DNS, headers and all reads as one deadline.
                    if len(body) >= self.budget.limits['response_bytes']:
                        raise SourceError('response ceiling reached; no extra byte read')
                    chunk = response.read1(min(65536, self.budget.limits['response_bytes'] - len(body)))
                    body.extend(chunk)
                    if len(body) > self.budget.limits['response_bytes']:
                        raise SourceError('single response limit exceeded')
                    if not chunk:
                        break
            raw = bytes(body)
            path = self.root / 'raw' / f'{row["number"]:03d}-{endpoint}.json'
            path.write_bytes(raw)
            self.budget.finish(row, size=len(raw), status=200, sha256=digest(raw))
            return json.loads(raw)
        except Exception as exc:
            # Unknown/incomplete response retains full reservation; never refunds
            # on failure, including a decoded-byte overflow.
            self.budget.finish(row, size=max(row['charged_bytes'], len(body)),
                               status=getattr(exc, 'code', 'FAILED'), error=type(exc).__name__,
                               retry_after=getattr(exc, 'headers', {}).get('Retry-After')
                               if getattr(exc, 'headers', None) else None)
            raise SourceError('request failed: ' + type(exc).__name__) from exc


def finite(value, positive=False):
    try:
        number = Decimal(str(value))
    except InvalidOperation as exc:
        raise SourceError('invalid decimal') from exc
    if not number.is_finite() or (positive and number <= 0):
        raise SourceError('nonfinite/nonpositive source value')
    return number


def validate_rows(rows, kind, cursor, end):
    previous = None
    for row in rows:
        timestamp = row['fundingTime'] if kind == 'fundingRate' else row[0]
        if type(timestamp) is not int or not cursor <= timestamp < end:
            raise SourceError('out of range timestamp')
        if previous is not None and timestamp <= previous:
            raise SourceError('duplicate or unordered timestamp')
        previous = timestamp
        if kind == 'fundingRate':
            finite(row['fundingRate'])
            if not row.get('markPrice'):
                raise SourceError('missing associated mark')
            finite(row['markPrice'], positive=True)
        else:
            if timestamp % 3600000 or row[6] != timestamp + 3599999:
                raise SourceError('invalid hourly candle bounds')
            o, h, low, c = [finite(x, positive=True) for x in row[1:5]]
            if not low <= min(o, c) <= max(o, c) <= h:
                raise SourceError('invalid OHLC')
    return previous


def collect(fetch, kind, symbol, start, end):
    limit = 1000 if kind == 'fundingRate' else 1500
    max_pages = math.ceil((end-start) / 3600000 / limit)
    rows, cursor = [], start
    for _ in range(max_pages):
        params = dict(symbol=symbol, startTime=cursor, endTime=end-1, limit=limit)
        if kind != 'fundingRate':
            params['interval'] = '1h'
        page = fetch.get(kind, params)
        if not isinstance(page, list) or len(page) > limit:
            raise SourceError('invalid page shape/size')
        if not page:
            break
        last = validate_rows(page, kind, cursor, end)
        if kind == 'fundingRate' and any(x.get('symbol') != symbol for x in page):
            raise SourceError('funding symbol mismatch')
        rows.extend(page)
        cursor = last + 1
        if cursor >= end or len(page) < limit:
            break
    if kind == 'fundingRate':
        # Always bounded: same authorized range, no next-day probe.
        if cursor < end:
            tail = fetch.get(kind, dict(symbol=symbol, startTime=cursor, endTime=end-1, limit=1000))
            if tail != []:
                raise SourceError('unexpected funding tail; no extra pages authorized')
    else:
        expected = list(range(start, end, 3600000))
        if [x[0] for x in rows] != expected:
            raise SourceError('incomplete hourly coverage')
    return rows


def qc_summary(data, start, end):
    result = {}
    for symbol, series in data.items():
        fund = series['fundingRate']
        times = [r['fundingTime'] for r in fund]
        if not times:
            raise SourceError('empty funding history')
        intervals = {}
        for a, b in zip(times, times[1:]):
            key = str(b-a)
            intervals[key] = intervals.get(key, 0) + 1
        result[symbol] = dict(hourly_trade_rows=len(series['klines']),
                              hourly_mark_rows=len(series['markPriceKlines']),
                              complete_days=(end-start)//86400000,
                              funding_events=len(times), first_funding_ms=times[0],
                              last_funding_ms=times[-1], interval_ms_counts=intervals,
                              associated_mark_complete=True)
    return dict(status='BLOCKED_DATA', structure='PASS', symbols=result,
                historical_interval_evidence='UNKNOWN', executable_source_published=False,
                reason='Observed event spacing and current fundingInfo do not prove historical schedule completeness',
                market_native_calls=0, economic_result=None)


def register(contract, snapshot, ledger_path, manifest_sha):
    with exclusive(str(ledger_path) + '.portfolio-source.lock'):
        raw = Path(ledger_path).read_bytes()
        check_scope(contract, snapshot, raw)
        registration = dict(record_type='PORTFOLIO_EXPLORATORY_SOURCE_REGISTERED',
                            registered_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
                            issue=119, exchange=contract['exchange'], instrument_type=contract['instrument_type'],
                            symbols=contract['symbols'], source_window=[contract['start'],contract['end_exclusive']],
                            training_window=[contract['training_start'],contract['end_exclusive']],
                            purpose='EXPLORATORY_TRAINING', independent_evidence=False,
                            source_contract_sha256=digest(json.dumps(contract, sort_keys=True).encode()),
                            launch_manifest_sha256=manifest_sha, prior_ledger_sha256=digest(raw),
                            native_authorized=False, authorization=contract['authorization'])
        with Path(ledger_path).open('ab') as f:
            if raw and not raw.endswith(b'\n'):
                raise SourceError('ledger lacks final newline')
            f.write((json.dumps(registration, sort_keys=True)+'\n').encode())
            f.flush()
            os.fsync(f.fileno())
        return registration
