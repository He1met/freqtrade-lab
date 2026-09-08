"""Synthetic-only daily persistence adapter. No acquisition or native engine."""
import dataclasses
import hashlib
import json
import os
import sys
import fcntl
from pathlib import Path
from decimal import Decimal as D
from datetime import datetime, timezone
from contextlib import contextmanager
from lab.spot139_model import Wallet, Rule, Episode, signal
from lab.spot139_binding import deny_network
from lab.spot139_residual_v3 import SpotResidualV3

VERSION = 'SPOT139_DAILY_SYNTHETIC_V1'
SYMBOLS = ('BTC/USDT', 'ETH/USDT')
COSTS = {'base': (D('.001'), D('.0006')), 'stress': (D('.002'), D('.0012'))}
CORE = {'spot139_model.py': 'fec7ca77813ae7d526765a549fe785fe3ab95d6e66369b06205f2f81e53d8c83',
        'spot139_residual_v3.py': '1027365f693fee313b54f2db9906e52a7692caa60f56d59e06de83a84037f9be'}
TYPES = {c.__name__: c for c in (Wallet, Rule, Episode, SpotResidualV3)}


def canonical(x):
    return json.dumps(x, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def digest(x):
    return hashlib.sha256(x).hexdigest()


def candidate_sha():
    for name, expected in CORE.items():
        if digest(Path(__file__).with_name(name).read_bytes()) != expected:
            raise ValueError('frozen candidate code changed')
    return digest(canonical(CORE))


def encode(x):
    if isinstance(x, D):
        if not x.is_finite(): raise ValueError('nonfinite amount')
        return {'$decimal': str(x)}
    if dataclasses.is_dataclass(x):
        return {'$class': type(x).__name__, 'fields': {f.name: encode(getattr(x, f.name)) for f in dataclasses.fields(x)}}
    if isinstance(x, dict): return {'$dict': [[encode(k), encode(v)] for k, v in sorted(x.items(), key=lambda p: str(p[0]))]}
    if isinstance(x, set): return {'$set': [encode(v) for v in sorted(x)]}
    if isinstance(x, tuple): return {'$tuple': [encode(v) for v in x]}
    if isinstance(x, list): return [encode(v) for v in x]
    if x is None or type(x) in (str, int, bool): return x
    raise ValueError('unsupported state type')


def decode(x):
    if isinstance(x, list): return [decode(v) for v in x]
    if not isinstance(x, dict):
        if x is None or type(x) in (str, int, bool): return x
        raise ValueError('invalid scalar')
    if set(x) == {'$decimal'}:
        v = D(x['$decimal'])
        if not v.is_finite(): raise ValueError('nonfinite state')
        return v
    if set(x) == {'$dict'}:
        pairs = [(decode(k), decode(v)) for k, v in x['$dict']]
        out = dict(pairs)
        if len(out) != len(pairs): raise ValueError('duplicate state key')
        return out
    if set(x) == {'$set'}: return set(decode(v) for v in x['$set'])
    if set(x) == {'$tuple'}: return tuple(decode(v) for v in x['$tuple'])
    if set(x) == {'$class', 'fields'} and x['$class'] in TYPES:
        cls = TYPES[x['$class']]
        if set(x['fields']) != {f.name for f in dataclasses.fields(cls)}: raise ValueError('incomplete model fields')
        obj = object.__new__(cls)  # Do not call __post_init__: it resets episode arms.
        for k, v in x['fields'].items(): object.__setattr__(obj, k, decode(v))
        return obj
    raise ValueError('unknown state encoding')


def pack(state):
    return {'version': VERSION, 'candidate_sha256': candidate_sha(), 'kind': 'SYNTHETIC_ONLY', 'payload': encode(state)}


def unpack(envelope):
    if set(envelope) != {'version', 'candidate_sha256', 'kind', 'payload'} or envelope['version'] != VERSION or envelope['candidate_sha256'] != candidate_sha() or envelope['kind'] != 'SYNTHETIC_ONLY':
        raise ValueError('state version/candidate/synthetic boundary')
    s = decode(envelope['payload'])
    required = {'warmup_start', 'end_day', 'next_day', 'last_hour', 'score_start', 'models', 'daily', 'previous', 'stopped'}
    if set(s) != required or set(s['models']) != set(COSTS) or set(s['daily']) != set(SYMBOLS): raise ValueError('state shape')
    if s['end_day'] != s['warmup_start']+265 or not s['warmup_start'] <= s['next_day'] <= s['end_day']: raise ValueError('finite calendar changed')
    if any(type(d) is not int or not s['warmup_start'] <= d < s['next_day'] for xs in s['daily'].values() for d in xs): raise ValueError('future indicator calendar')
    if s['score_start'] is not None and not s['warmup_start']+85 <= s['score_start'] < s['next_day']: raise ValueError('score clock')
    if s['last_hour'] != s['next_day'] * 24 - 1 and not s['stopped']: raise ValueError('state clock')
    if set(s['previous']) != set(SYMBOLS): raise ValueError('previous-hour assets')
    for symbol in SYMBOLS:
        if any(type(h) is not int or not (s['next_day']-1)*24 <= h < s['next_day']*24 for h in s['previous'][symbol]): raise ValueError('future previous-hour source')
    for cost, model in s['models'].items():
        if type(model) is not SpotResidualV3 or set(model.rules) != set(SYMBOLS) or (model.fee, model.slip) != COSTS[cost]: raise ValueError('model identity')
        if any(type(r) is not Rule or any(not isinstance(getattr(r,f.name),D) or not getattr(r,f.name).is_finite() or getattr(r,f.name)<=0 for f in dataclasses.fields(r)) for r in model.rules.values()): raise ValueError('invalid rules')
        if model.wallet.cash < 0 or any(q < 0 for q in model.wallet.inventory.values()): raise ValueError('negative wallet')
        if model.rules != s['models']['base'].rules: raise ValueError('cost scenario rules differ')
        if s['score_start'] is not None and model.last_hour != s['last_hour']: raise ValueError('model clock')
        if model.wallet.cash != 1000-model.cost_added+model.sale_proceeds or sum(model.basis.values(), D(0)) != model.cost_added-model.cost_released or model.realized != model.sale_proceeds-model.cost_released: raise ValueError('accounting invariant')
    return s


def initial_state(rules, first_day, history=None, warmup_start=None):
    if set(rules) != set(SYMBOLS): raise ValueError('fixed two assets required')
    w = first_day if warmup_start is None else warmup_start
    daily = history or {s: {} for s in SYMBOLS}
    if set(daily) != set(SYMBOLS) or any(d < w or d >= first_day for xs in daily.values() for d in xs): raise ValueError('warmup calendar')
    state = dict(warmup_start=w, end_day=w+265, next_day=first_day, last_hour=first_day*24-1, score_start=None,
                 models={c: SpotResidualV3(rules, fee=f, slip=p) for c, (f, p) in COSTS.items()}, daily=daily,
                 previous={s: {} for s in SYMBOLS}, stopped=None)
    unpack(pack(state))
    return state


def validate_day(packet, state):
    if set(packet) != {'kind', 'candidate_sha256', 'day', 'received_at_hour', 'bars'} or packet['kind'] != 'SYNTHETIC_ONLY' or packet['candidate_sha256'] != candidate_sha(): raise ValueError('unaccepted source identity')
    day = packet['day']
    if type(day) is not int or day != state['next_day'] or not state['warmup_start'] <= day < state['end_day']: raise ValueError('missing/outside day; no calendar jump')
    if type(packet['received_at_hour']) is not int or packet['received_at_hour'] < (day+1)*24: raise ValueError('future or unclosed source')
    if set(packet['bars']) != set(SYMBOLS): raise ValueError('source assets')
    bars = {}
    for s, rows in packet['bars'].items():
        bars[s] = {}
        for row in rows:
            if set(row) != {'hour', 'ohlc', 'full'} or type(row['hour']) is not int or not day*24 <= row['hour'] < (day+1)*24 or row['hour'] in bars[s] or type(row['full']) is not bool: raise ValueError('source clock/duplicate')
            if len(row['ohlc']) != 4 or any(type(v) is not str for v in row['ohlc']): raise ValueError('decimal source strings required')
            o, h, l, c = map(D, row['ohlc'])
            if any(not v.is_finite() or v <= 0 for v in (o,h,l,c)) or not l <= min(o,c) <= max(o,c) <= h: raise ValueError('invalid OHLC')
            bars[s][row['hour']] = ((o,h,l,c), row['full'])
    return bars


def apply_day(state, packet, on_cost=lambda c: None, fault=lambda point: None):
    """Pure update on caller-owned state. Only synthetic input is admitted."""
    bars = validate_day(packet, state)
    if state['stopped']: raise ValueError('joint observation stopped')
    day = packet['day']; results = {c: {'orders': [], 'events': [], 'hourly': []} for c in COSTS}
    ready = day >= state['warmup_start']+85 and all(signal(day-1, state['daily'][s], 'B') is not None for s in SYMBOLS)
    if state['score_start'] is None and ready: state['score_start'] = day
    if state['score_start'] is not None:
        previous = state['previous']
        for hour in range(day*24, (day+1)*24):
            opens = {s: xs[hour][0][0] for s, xs in bars.items() if hour in xs}
            lows = {s: (bars[s] if hour-1 in bars[s] else previous[s])[hour-1][0][2] for s in SYMBOLS if hour-1 in bars[s] or hour-1 in previous[s]}
            history = state['daily'] if hour % 24 == 0 else None
            breach = False
            for cost, model in state['models'].items():
                if hour == day*24: on_cost(cost)
                n, e = len(model.fills), len(model.events)
                status = model.on_hour(hour, opens, history, lows)
                results[cost]['orders'].extend(model.fills[n:]); results[cost]['events'].extend(model.events[e:])
                results[cost]['hourly'].append(dict(hour=hour, cash=model.wallet.cash, equity=model.equity(), peak=model.wallet.peak,
                    inventory=dict(model.wallet.inventory), basis=dict(model.basis), status=status,
                    mark_age={s: hour-model.marked_at[s] for s in model.marked_at}))
                breach |= status['observed_dd'] > D('.20')
            state['last_hour'] = hour
            fault('after_hour')
            if breach:
                state['stopped'] = 'RISK_LIMIT_BREACHED'; break
    else: state['last_hour'] = (day+1)*24-1
    for s, xs in bars.items():
        if len(xs) == 24 and all(v[1] for v in xs.values()):
            ordered = [xs[h][0] for h in range(day*24,(day+1)*24)]
            state['daily'][s][day] = (ordered[0][0], max(b[1] for b in ordered), min(b[2] for b in ordered), ordered[-1][3])
        state['daily'][s] = {d: b for d,b in state['daily'][s].items() if d >= day-84}
    state['previous'] = bars
    state['next_day'] = day+1
    if state['next_day'] == state['end_day'] and not state['stopped']: state['stopped'] = 'FINITE_CALENDAR_END'
    for cost, model in state['models'].items():
        results[cost]['terminal'] = model.terminal(state['last_hour']) if state['score_start'] is not None else None
    return dict(day=day, input_sha256=digest(canonical(packet)), event_end_hour=state['last_hour'],
                received_at_hour=packet['received_at_hour'], observation='DELAYED_OBSERVATION_SYNTHETIC',
                qualification=False, score_start=state['score_start'], stopped=state['stopped'], costs=results)


def write(path, value):
    with Path(path).open('xb') as stream:
        stream.write(canonical(value)+b'\n'); stream.flush(); os.fsync(stream.fileno())


def fsync_dir(path):
    fd = os.open(path, os.O_RDONLY)
    try: os.fsync(fd)
    finally: os.close(fd)


def append(path, row):
    row = dict(row, recorded_at_utc=datetime.now(timezone.utc).isoformat())
    with Path(path).open('ab') as stream:
        stream.write(canonical(row)+b'\n'); stream.flush(); os.fsync(stream.fileno())
    fsync_dir(Path(path).parent)


def events(path):
    if not path.exists(): return []
    data = path.read_bytes()
    if data and not data.endswith(b'\n'): raise ValueError('truncated attempt ledger; manual review')
    return [json.loads(line) for line in data.splitlines()]


def initialize(root, envelope):
    unpack(envelope)  # Validation before root creation.
    root = Path(root); root.mkdir()
    write(root/'initial.json', envelope); (root/'commits').mkdir(); (root/'attempts').mkdir(); (root/'writer.lock').touch()
    fsync_dir(root)


@contextmanager
def lock(root):
    root = Path(root)
    with (root/'writer.lock').open('r') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield root


def committed(root):
    envelope = json.loads((root/'initial.json').read_bytes()); unpack(envelope)
    for directory in sorted((root/'commits').iterdir()):
        receipt = json.loads((directory/'receipt.json').read_bytes())
        if receipt['previous_state_sha256'] != digest(canonical(envelope)): raise ValueError('commit chain drift')
        for name in ('state', 'result', 'input'):
            if digest((directory/(name+'.json')).read_bytes()) != receipt[name+'_file_sha256']: raise ValueError('committed bytes changed')
        envelope = json.loads((directory/'state.json').read_bytes()); unpack(envelope)
    return envelope


def commit_day(root, previous, packet, fault=lambda point: None):
    with lock(root) as root:
        unpack(previous)
        input_sha = digest(canonical(packet)); dest = root/'commits'/f'{packet["day"]:08d}'
        current = committed(root)  # Validate committed history even for no-op.
        if dest.exists():
            r = json.loads((dest/'receipt.json').read_bytes())
            if r['input_sha256'] != input_sha or r['previous_state_sha256'] != digest(canonical(previous)): raise ValueError('committed key/source revision')
            return {'status': 'NO_OP_COMMITTED', 'path': str(dest)}
        if digest(canonical(previous)) != digest(canonical(current)): raise ValueError('stale previous state')
        state = unpack(previous); validate_day(packet, state)
        if state['stopped']: raise ValueError('joint observation stopped')
        rows = events(root/'attempts.jsonl')
        if any(r['event']=='FATAL' for r in rows): raise ValueError('joint observation stopped by accounting/control failure')
        reserved = [r for r in rows if r['event'] == 'RESERVED']
        same = [r for r in reserved if r['day'] == packet['day']]
        if any(r['input_sha256'] != input_sha or r['previous_state_sha256'] != digest(canonical(previous)) for r in same): raise ValueError('uncommitted recovery must use same input/state')
        recovery = bool(same)
        # Reserve both cost slots conservatively. Starts are recorded separately.
        if recovery and sum(r['cost_slots'] for r in reserved if r['bucket']=='recovery')+2 > 6: raise ValueError('six recovery cost slots exhausted')
        has_update = state['score_start'] is not None or (packet['day'] >= state['warmup_start']+85 and all(signal(packet['day']-1,state['daily'][s],'B') is not None for s in SYMBOLS))
        slots = 2 if recovery or has_update else 0
        attempt = len(reserved)+1; stage = root/'attempts'/f'{attempt:08d}'
        append(root/'attempts.jsonl', dict(event='RESERVED', attempt=attempt, day=packet['day'], bucket='recovery' if recovery else 'normal', cost_slots=slots,
            input_sha256=input_sha, previous_state_sha256=digest(canonical(previous))))
        try:
            fault('after_reservation_before_files')
            stage.mkdir(); fsync_dir(root/'attempts')
            write(stage/'input.json',packet)
            fault('after_reservation')
            def start(cost): append(root/'attempts.jsonl',dict(event='COST_STARTED',attempt=attempt,cost=cost))
            result = apply_day(state, packet, start, fault)
            envelope = pack(state); unpack(envelope)
            write(stage/'state.json',envelope); write(stage/'result.json',encode(result))
            write(stage/'receipt.json',dict(input_sha256=input_sha, previous_state_sha256=digest(canonical(previous)),
                computed_at_utc=datetime.now(timezone.utc).isoformat(), observation='DELAYED_OBSERVATION_SYNTHETIC',
                input_file_sha256=digest((stage/'input.json').read_bytes()),
                state_file_sha256=digest((stage/'state.json').read_bytes()),result_file_sha256=digest((stage/'result.json').read_bytes())))
            fsync_dir(stage); fault('before_commit')
            os.rename(stage,dest); fsync_dir(root/'commits'); fsync_dir(root/'attempts')
            fault('after_commit')
            append(root/'attempts.jsonl',dict(event='COMMITTED',attempt=attempt,day=packet['day']))
            return {'status':'COMMITTED','path':str(dest)}
        except BaseException as error:
            event = 'FATAL' if isinstance(error,(ValueError,ArithmeticError)) and not dest.exists() else 'INTERRUPTED'
            append(root/'attempts.jsonl',dict(event=event,attempt=attempt,error=type(error).__name__))
            raise


def request_plan(first_missing, target_day):
    if type(first_missing) is not int or type(target_day) is not int or not 1 <= target_day-first_missing+1 <= 3: raise ValueError('at most three pending days including current target')
    plan = [dict(method='GET',host='api.binance.com',endpoint='/api/v3/exchangeInfo',params={'symbols':'["BTCUSDT","ETHUSDT"]'},day=target_day,kind='metadata')]
    for day in range(first_missing,target_day+1):
        for s in SYMBOLS:
            plan.append(dict(method='GET',host='api.binance.com',endpoint='/api/v3/klines',params=dict(symbol=s.replace('/',''),interval='1h',startTime=day*86400000,endTime=(day+1)*86400000-1,limit=24),day=day,kind='klines'))
    return plan


def offline_request(root, request, first_missing, target_day, transport):
    """Offline injected bytes only; durable one-bucket charging before each call."""
    if getattr(transport,'offline',False) is not True: raise ValueError('offline transport required; no network implementation')
    if request not in request_plan(first_missing,target_day): raise ValueError('unfrozen request')
    with lock(root) as root:
        s = unpack(committed(root))
        if not s['warmup_start'] <= first_missing <= target_day < s['end_day'] or first_missing != s['next_day']: raise ValueError('request calendar scope')
        key = digest(canonical(request)); cache = root/('source-'+key+'.json')
        rows = events(root/'requests.jsonl'); attempts = [r for r in rows if r['event']=='ATTEMPT']
        if cache.exists():
            success = [r for r in rows if r.get('key')==key and r['event']=='SUCCEEDED']
            if not success or digest(cache.read_bytes()) != success[-1]['sha256']: raise ValueError('cached source drift')
            return cache.read_bytes()
        old = any(r['key']==key for r in attempts)
        bucket = 'normal' if request['day']==target_day and not old else 'recovery'
        if request['kind']=='metadata' and old: raise ValueError('metadata retry not authorized')
        limit = 795 if bucket=='normal' else 12
        if sum(r['bucket']==bucket for r in attempts)>=limit: raise ValueError('source attempt budget exhausted')
        append(root/'requests.jsonl',dict(event='ATTEMPT',key=key,bucket=bucket,request=request,target_day=target_day))
        try:
            sys.addaudithook(deny_network)
            data = transport(request)
            cap = 256*1024 if request['kind']=='metadata' else 64*1024
            if type(data) is not bytes or len(data)>cap or json.loads(data).get('kind')!='SYNTHETIC_TRANSPORT': raise ValueError('invalid offline response')
            with cache.open('xb') as stream: stream.write(data); stream.flush(); os.fsync(stream.fileno())
            append(root/'requests.jsonl',dict(event='SUCCEEDED',key=key,sha256=digest(data)))
            fsync_dir(root); return data
        except BaseException as error:
            append(root/'requests.jsonl',dict(event='FAILED',key=key,error=type(error).__name__)); raise
