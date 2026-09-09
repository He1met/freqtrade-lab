"""Immutable observed entry intents. No HTTP, native runs, orders or account model."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile

UTC = timezone.utc
HOUR = timedelta(hours=1)
REPO = Path(__file__).resolve().parents[1]
PAIRS = ('BTC/USDT:USDT', 'ETH/USDT:USDT')
OBSERVER_FILES = ('lab/perp_forward_signal.py', 'scripts/perp_forward_signal.py', 'lab/perp_schedule.py')


def clock(): return datetime.now(UTC)
def dt(value):
    value = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if value.tzinfo is None: raise ValueError('UTC-aware timestamp required')
    return value.astimezone(UTC)
def iso(value): return value.astimezone(UTC).isoformat()
def sha(raw): return hashlib.sha256(raw).hexdigest()
def encoded(value): return (json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)+'\n').encode()
def read(path): return json.loads(Path(path).read_bytes())


def atomic(path, value):
    path = Path(path)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.'+path.name, delete=False) as f:
        f.write(encoded(value)); f.flush(); os.fsync(f.fileno()); temporary = f.name
    os.replace(temporary, path)
    fd = os.open(path.parent, os.O_RDONLY)
    try: os.fsync(fd)
    finally: os.close(fd)


def control(registration_path, protocol_path, binding_path):
    registration, protocol, binding = map(read, (registration_path, protocol_path, binding_path))
    rh, ph = sha(Path(registration_path).read_bytes()), sha(Path(protocol_path).read_bytes())
    if (registration.get('schema') != 'perp-candidate-registration-v1' or
            registration.get('variant') != 'carry_nonpaying' or
            registration.get('confirmation_protocol_sha256') != ph or
            registration.get('window') != protocol.get('window') or
            dt(registration['registered_at']) >= dt(protocol['window']['start_inclusive'])):
        raise ValueError('candidate registration/protocol/time binding mismatch')
    if binding.get('registration_sha256') != rh or binding.get('confirmation_protocol_sha256') != ph:
        raise ValueError('observer registration/protocol binding mismatch')
    if not set(OBSERVER_FILES) <= binding.get('code_bindings', {}).keys():
        raise ValueError('observer code must be independently bound before observation')
    for group in (registration['code_bindings'], binding['code_bindings']):
        for name, digest in group.items():
            path = (REPO/name).resolve()
            if not path.is_relative_to(REPO) or sha(path.read_bytes()) != digest:
                raise ValueError('code SHA drift: '+name)
    identity = dict(candidate_id=registration['candidate_id'], registration_sha256=rh,
                    confirmation_protocol_sha256=ph, observer_binding_sha256=sha(Path(binding_path).read_bytes()))
    return registration, protocol, binding, identity


def observed_rows(seed_root, incremental_root, source_at, observed_at):
    """Convert public vintages in memory, preserving both publication and fetch floors."""
    pools = {(p, k): {} for p in PAIRS for k in ('ohlcv', 'funding', 'premium')}
    sources = {}
    roots = [Path(seed_root)] + sorted(p.parent for p in Path(incremental_root).glob('*/receipt.json'))
    for root in roots:
        receipt_path = root/'receipt.json'
        receipt = read(receipt_path)
        if receipt.get('exchange') != 'binance': raise ValueError('wrong public source exchange')
        if (dt(receipt['window_end_exclusive']) < source_at-168*HOUR or
                dt(receipt['window_start']) > source_at+HOUR): continue
        sources[str(receipt_path)] = sha(receipt_path.read_bytes())
        for pair, kind in pools:
            name = pair.split('/')[0]+'USDT-'+kind
            item = receipt.get('datasets', {}).get(name)
            if not item: continue
            path = (root/item['path']).resolve()
            if not path.is_relative_to(root.resolve()): raise ValueError('source path escapes capture')
            raw = path.read_bytes()
            if sha(raw) != item['sha256']: raise ValueError('public vintage SHA drift: '+name)
            rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
            if len(rows) != item['rows']: raise ValueError('public vintage row count drift')
            sources[str(path)] = item['sha256']
            for row in rows:
                event, fetched = dt(row['event_time']), dt(row['fetched_at'])
                if not source_at-169*HOUR <= event <= source_at+HOUR: continue
                declared = dt(row.get('historical_available_at_assumption', row['available_at']))
                floor = event+HOUR+(timedelta(seconds=60) if kind != 'funding' else timedelta())
                if declared < floor: raise ValueError('publication before frozen conservative lag')
                effective = max(dt(row['available_at']), fetched, declared)
                if max(effective, fetched) > observed_at: continue
                converted = dict(row, event=event, fetched=fetched, declared=declared,
                                 effective=effective, row_sha256=sha(encoded(row)))
                prior = pools[pair, kind].get(event)
                if prior and prior['fetched']==fetched and prior['row_sha256']!=converted['row_sha256']:
                    raise ValueError('conflicting same-time vintage')
                if prior is None or fetched > prior['fetched']:
                    pools[pair, kind][event] = converted
    return pools, sources


def intent(pair, pools, source_at):
    """Reuse the exact historical formulas with separately checked observed availability."""
    from lab.perp_baseline_runner import native_environment
    native_environment()  # Version/source check only; does not instantiate a native worker.
    import pandas as pd
    from lab.perp_funding_premium import features, align_factors, gate_masks
    cutoff = source_at+HOUR+timedelta(seconds=60)
    prices = [pools[pair, 'ohlcv'].get(source_at-n*HOUR) for n in range(168, -1, -1)]
    premium = pools[pair, 'premium'].get(source_at)
    funding = [r for r in pools[pair, 'funding'].values() if r['declared'] <= cutoff]
    if any(r is None for r in prices) or premium is None or not funding:
        return dict(status='MISSING_INPUT', intent=None, reason='169 consecutive prices, same-hour premium and settled funding required')
    funding = max(funding, key=lambda r:r['event'])
    if any(r['declared'] > cutoff for r in prices+[premium]) or cutoff-funding['event'] > 12*HOUR:
        return dict(status='MISSING_INPUT', intent=None, reason='unpublished or stale input')
    rows = [dict(date=r['event'], **{k:float(r[k]) for k in ('open','high','low','close','volume')}) for r in prices]
    if any(not math.isfinite(row[k]) or row[k] <= 0 for row in rows for k in ('open','high','low','close')):
        raise ValueError('invalid OHLC price')
    if any(not math.isfinite(row['volume']) or row['volume'] < 0 for row in rows): raise ValueError('invalid volume')
    rate, premium_close = float(funding['rate']), float(premium['close'])
    if not all(math.isfinite(v) for v in (rate,premium_close)): raise ValueError('invalid factor')
    aligned = align_factors(pd.Series([source_at]),
        pd.DataFrame([dict(funding_event_at=funding['event'],funding_available_at=funding['declared'],funding_rate=rate)]),
        pd.DataFrame([dict(date=source_at,premium_available_at=premium['declared'],premium_close=premium_close)]))
    last = features(pd.DataFrame(rows)).iloc[-1]
    lg, sg = gate_masks(aligned, 'carry_nonpaying')
    if not bool(aligned.iloc[0].factor_valid):
        return dict(status='MISSING_INPUT', intent=None, reason='inherited factor_valid unavailable')
    risk_valid=math.isfinite(float(last.risk_multiplier))
    long = bool(risk_valid and last.baseline_long and last.volume>0 and last.persistence>=.25 and lg.iloc[0])
    short = bool(risk_valid and last.baseline_short and last.volume>0 and last.persistence<=-.25 and sg.iloc[0])
    selected = prices+[premium,funding]
    return dict(status='VALID_INTENT', intent='long' if long else 'short' if short else 'NO_TRADE',
        persistence=float(last.persistence) if math.isfinite(float(last.persistence)) else None,
        risk_multiplier=float(last.risk_multiplier) if risk_valid else None, funding_rate=rate,
        funding_event_at=iso(funding['event']), funding_declared_available_at=iso(funding['declared']),
        premium_completeness=True, premium_sign_used=False,
        latest_required_fetched_at=iso(max(r['fetched'] for r in selected)),
        effective_available_at=iso(max(r['effective'] for r in selected)),
        input_rows_sha256=sha(encoded([r['row_sha256'] for r in selected])),
        exit_long=bool(last.channel_exit_long), exit_short=bool(last.channel_exit_short))


@contextmanager
def locked(root, identity, seed_root):
    root = Path(root).resolve()
    if any((p/'.git').exists() for p in (root,*root.parents)): raise ValueError('Git-external signal root required')
    root.mkdir(parents=True,exist_ok=True)
    with (root/'writer.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        path=root/'state.json'; seed_hash=sha((Path(seed_root)/'receipt.json').read_bytes())
        state=read(path) if path.exists() else dict(identity=identity,seed_receipt_sha256=seed_hash,
            active=False,records={},last_source=None,last_observed_at=None)
        if state['identity']!=identity or state['seed_receipt_sha256']!=seed_hash: raise ValueError('observer identity/seed drift')
        for key, item in state['records'].items():
            for kind in ('intent','receipt'):
                if sha((root/'hours'/(key+'.'+kind+'.json')).read_bytes())!=item[kind+'_sha256']:
                    raise ValueError('immutable signal evidence drift')
        yield root,state
        atomic(path,state)


def publish_hour(root,state,protocol,identity,source_at,observed_at,pools,sources,clock_fn):
    entry=source_at+2*HOUR; key=entry.strftime('%Y%m%dT%H00Z')
    folder=root/'hours';folder.mkdir(exist_ok=True)
    raw_path=folder/(key+'.intent.json'); receipt_path=folder/(key+'.receipt.json')
    if key in state['records']: return
    if receipt_path.exists():
        prior=read(receipt_path)
        if prior['identity']!=identity or prior['intent_sha256']!=sha(raw_path.read_bytes()): raise ValueError('interrupted commit identity drift')
    else:
        if raw_path.exists():
            results={p:dict(status='UNKNOWN_INTERRUPTED',intent=None) for p in PAIRS}
        else:
            results={p:(dict(status='LATE',intent=None) if observed_at>=entry else intent(p,pools,source_at)) for p in PAIRS}
            end=dt(protocol['window']['last_new_entry_exclusive'])
            for result in results.values():
                if entry>=end and result['status']=='VALID_INTENT': result.update(intent='NO_TRADE',entry_window_closed=True)
            atomic(raw_path,dict(identity=identity,source_candle=iso(source_at),nominal_cutoff=iso(source_at+HOUR+timedelta(seconds=60)),
                planned_entry=iso(entry),observed_at=iso(observed_at),computed_at=iso(clock_fn()),pairs=results,source_bindings=sources,
                source_bundle_sha256=sha(encoded(sources)),scope='ENTRY_INTENT_ONLY_NO_ORDERS_OR_ACCOUNT'))
        published=clock_fn()  # Read after durable intent publication; never invent an earlier persistence time.
        phase=('CONFIRMATION' if state['active'] and dt(protocol['window']['start_inclusive'])<=entry<dt(protocol['window']['end_exclusive'])
               else 'PRE_CONFIRMATION' if entry<dt(protocol['window']['start_inclusive']) else 'UNACTIVATED_OR_OUTSIDE_WINDOW')
        for result in results.values():
            if result['status']=='VALID_INTENT':
                result['status']=('TIMELY_NO_TRADE' if result['intent']=='NO_TRADE' else 'TIMELY_SIGNAL') if published<entry else 'LATE'
        atomic(receipt_path,dict(identity=identity,intent_sha256=sha(raw_path.read_bytes()),
            published_observed_at=iso(published),phase=phase,pairs=results,native_calls=0,orders=0))
    state['records'][key]=dict(intent_sha256=sha(raw_path.read_bytes()),receipt_sha256=sha(receipt_path.read_bytes()))
    state['last_source']=iso(source_at)


def _run(root,registration_path,protocol_path,binding_path,seed_root,incremental_root,command='tick',clock_fn=clock,
        native_acceptance_path=None,native_acceptance_sha256=None):
    registration,protocol,binding,identity=control(registration_path,protocol_path,binding_path)
    observed=clock_fn();source=observed.replace(minute=0,second=0,microsecond=0)-HOUR
    if command=='check':
        pools,sources=observed_rows(seed_root,incremental_root,source,observed)
        return dict(status='CHECK_ONLY',identity=identity,pairs={p:intent(p,pools,source) for p in PAIRS},source_bindings=sources,native_calls=0,orders=0)
    with locked(root,identity,seed_root) as (root,state):
        if state['last_observed_at'] and observed<dt(state['last_observed_at']): raise ValueError('clock moved backwards')
        if command=='activate':
            if observed>=dt(protocol['window']['start_inclusive']): raise ValueError('activation missed fixed start')
            receipt_path=native_acceptance_path
            if not receipt_path or sha(Path(receipt_path).read_bytes())!=native_acceptance_sha256:
                raise ValueError('independent native acceptance receipt required')
            acceptance=read(receipt_path)
            if (acceptance.get('status') not in {'PASS','LIMITED_PASS'} or acceptance.get('registration_sha256')!=identity['registration_sha256'] or
                    acceptance.get('confirmation_protocol_sha256')!=identity['confirmation_protocol_sha256'] or
                    acceptance.get('observer_binding_sha256')!=identity['observer_binding_sha256'] or
                    acceptance.get('signal_root')!=str(root) or acceptance.get('native_calls')!=1 or
                    acceptance.get('economic_validation') is not False):
                raise ValueError('native acceptance binding/status mismatch')
            if not acceptance.get('code_bindings'): raise ValueError('native consumer code binding required')
            for name,digest in acceptance['code_bindings'].items():
                if sha((REPO/name).read_bytes())!=digest: raise ValueError('native consumer code SHA drift')
            ready=any(all(v['status'].startswith('TIMELY_') for v in read(root/'hours'/(k+'.receipt.json'))['pairs'].values()) for k in state['records'])
            if not ready: raise ValueError('actual complete timely preflight observation required')
            if state['active']:
                if state['native_acceptance_receipt_sha256']!=native_acceptance_sha256: raise ValueError('activation receipt changed')
                return dict(status='ALREADY_ACTIVATED',economic_qualification=False,identity=identity)
            state.update(active=True,activated_at=iso(observed),native_acceptance_receipt_sha256=native_acceptance_sha256)
            return dict(status='ACTIVATED_RESEARCH_INTENTS_ONLY',economic_qualification=False,identity=identity)
        if command!='tick': raise ValueError('unsupported signal command')
        final_source=dt(protocol['window']['end_exclusive'])-3*HOUR
        source=min(source,final_source)
        if state['last_source'] and dt(state['last_source'])>=final_source:
            return dict(status='FIXED_WINDOW_ENDED',native_calls=0,orders=0)
        if observed.minute<10: return dict(status='WAIT_PUBLICATION_BUFFER',native_calls=0,orders=0)
        pools,sources=observed_rows(seed_root,incremental_root,source,observed)
        cursor=dt(state['last_source'])+HOUR if state['last_source'] else source
        while cursor<=source:
            publish_hour(root,state,protocol,identity,cursor,observed,pools,sources,clock_fn);cursor+=HOUR
        state['last_observed_at']=iso(observed)
        key=(source+2*HOUR).strftime('%Y%m%dT%H00Z')
        return dict(status='OBSERVATION_RECORDED',active=state['active'],latest_receipt=str(root/'hours'/(key+'.receipt.json')),
                    record_count=len(state['records']),native_calls=0,orders=0,identity=identity)


def run(root,registration_path,protocol_path,binding_path,seed_root,incremental_root,command='tick',clock_fn=clock,
        native_acceptance_path=None,native_acceptance_sha256=None,runtime_policy_path=None):
    if not Path(root).is_absolute(): raise ValueError('absolute signal root required')
    args=(root,registration_path,protocol_path,binding_path,seed_root,incremental_root,command,clock_fn,
          native_acceptance_path,native_acceptance_sha256)
    if command=='check': return _run(*args)
    control(registration_path,protocol_path,binding_path)
    if runtime_policy_path is None: raise ValueError('explicit current runtime policy required')
    from lab.perp_schedule import locked as scheduler_locked
    with scheduler_locked(Path(root).parent/'scheduler',runtime_policy_path) as (_,_,state):
        if any(t['status'] in {'RUNNING','UNKNOWN_INTERRUPTED'} for t in state['tasks']):
            return dict(status='WAIT_RESEARCH_WRITER',native_calls=0,orders=0)
        return _run(*args)
