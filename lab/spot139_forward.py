"""Explicitly granted Binance public daily source; reuses daily state/commit engine."""
import json
import os
import signal
import time
import tempfile
import urllib.request
import urllib.error
import urllib.parse
from contextlib import contextmanager
from pathlib import Path
from decimal import Decimal as D
from datetime import datetime
from . import spot139_daily as d

LIMITS = dict(normal_gets=795,recovery_gets=12,gets=807,bytes=104988672,
              task_seconds=47700,cost_updates=360,recovery_cost_updates=6,data_days=265)
META_FIELDS = ('symbol','status','baseAsset','quoteAsset','isSpotTradingAllowed',
               'baseAssetPrecision','quoteAssetPrecision','baseCommissionPrecision','quoteCommissionPrecision')


class Stop(ValueError): pass


def semantic(info):
    if not isinstance(info,dict) or not isinstance(info.get('symbols'),list) or len(info['symbols'])!=2 or info.get('exchangeFilters',[]) != []: raise Stop('metadata shape/global filter')
    result={}
    for row in info['symbols']:
        if not isinstance(row,dict) or not set(META_FIELDS+('orderTypes','filters')) <= row.keys(): raise Stop('metadata fields missing')
        if not isinstance(row['orderTypes'],list) or not all(isinstance(x,str) for x in row['orderTypes']) or not isinstance(row['filters'],list): raise Stop('metadata list fields')
        if not all(isinstance(x,dict) and isinstance(x.get('filterType'),str) for x in row['filters']): raise Stop('filter fields missing')
        s=row.get('symbol','').replace('USDT','/USDT')
        if s not in d.SYMBOLS or s in result: raise Stop('metadata symbols')
        if row.get('status')!='TRADING' or row.get('isSpotTradingAllowed') is not True or row.get('quoteAsset')!='USDT' or row.get('baseAsset')!=s.split('/')[0]: raise Stop('spot identity/status')
        out={k:row[k] for k in META_FIELDS}
        for k in META_FIELDS[5:]:
            if type(out[k]) is not int or not 0<=out[k]<=18: raise Stop('precision')
        out['orderTypes']=sorted(row['orderTypes'])
        if 'MARKET' not in out['orderTypes']: raise Stop('market order unavailable')
        filters={f['filterType']:dict(f) for f in row['filters']}
        if len(filters)!=len(row['filters']) or not {'LOT_SIZE','MARKET_LOT_SIZE','PRICE_FILTER','NOTIONAL'} <= filters.keys(): raise Stop('filter schema')
        for f in filters.values():
            for k,v in f.items():
                if isinstance(v,str) and k!='filterType':
                    try: number=D(v)
                    except ArithmeticError as error: raise Stop('filter numeric syntax') from error
                    if not number.is_finite() or number<0: raise Stop('filter numeric value')
                    if number and not -24<=number.adjusted()<=30: raise Stop('unsupported filter magnitude')
                    exact=format(number,'f');f[k]=exact.rstrip('0').rstrip('.') if '.' in exact else exact
        out['filters']=filters;result[s]=out
    return result


def rules_from_semantic(rows):
    out={}
    for s,row in rows.items():
        fs=row['filters'];lot=fs['LOT_SIZE'];market=fs['MARKET_LOT_SIZE']
        out[s]=d.Rule(max(D(lot['stepSize']),D(market['stepSize'])),max(D(lot['minQty']),D(market['minQty'])),
                      D(fs['NOTIONAL']['minNotional']),min(D(lot['maxQty']),D(market['maxQty'])),
                      D(10)**-row['baseCommissionPrecision'],D(10)**-row['quoteCommissionPrecision'],D(fs['PRICE_FILTER']['tickSize']))
    return out


def utc_epoch(value):
    stamp=datetime.fromisoformat(value)
    if stamp.tzinfo is None or stamp.utcoffset().total_seconds()!=0: raise Stop('explicit UTC timestamp required')
    return stamp.timestamp()


def check_manifest(m):
    if m['version']!='ISSUE139_REAL_FORWARD_V1' or m['kind']!='REAL_FORWARD' or m['candidate_sha256']!=d.candidate_sha(): raise Stop('manifest identity')
    w=m['window']
    if not all(type(v) is int for v in w.values()) or set(w)!= {'W','S0','E'} or w['S0']!=w['W']+85 or w['E']!=w['W']+265: raise Stop('calendar contract')
    if m['limits']!=LIMITS or m['costs']!={c:[str(f),str(s)] for c,(f,s) in d.COSTS.items()}: raise Stop('limits/costs changed')
    if d.digest(d.canonical(m['expected_metadata']))!=m['metadata_semantic_sha256'] or d.digest(d.canonical(d.encode(rules_from_semantic(m['expected_metadata']))))!=m['rules_sha256']: raise Stop('rule baseline binding')
    if set(m['code_bindings']) != {'lab/spot139_daily.py','lab/spot139_forward.py','scripts/spot139_forward.py','lab/spot139_model.py','lab/spot139_residual_v3.py'}: raise Stop('implementation files incomplete')
    for p,h in m['code_bindings'].items():
        if d.digest((Path(__file__).resolve().parents[1]/p).read_bytes())!=h: raise Stop('implementation binding changed')
    return m


def check_grant(m,g):
    check_manifest(m)
    if g.get('authorized') is not True or g.get('manifest_sha256')!=d.digest(d.canonical(m)) or g.get('run_root')!=m['run_root'] or g.get('candidate_sha256')!=m['candidate_sha256'] or g.get('rules_sha256')!=m['rules_sha256']: raise Stop('external exact grant required')
    if not str(g.get('authorization_reference','')).startswith('https://github.com/He1met/freqtrade-lab/issues/139#issuecomment-'): raise Stop('authorization reference required')
    if not m['window']['W']<=g['start_day']<g['end_day']<=m['window']['E']: raise Stop('grant subwindow')
    caps=g['cumulative_caps']
    if set(caps)!=set(LIMITS) or any(type(v) is not int or not 0<=v<=LIMITS[k] for k,v in caps.items()): raise Stop('grant exceeds campaign cap')
    p=Path(g['registration_path']);raw=p.read_bytes()
    if d.digest(raw)!=g['registration_sha256']: raise Stop('registration changed')
    expected=dict(record_type='ISSUE139_REAL_FORWARD_REGISTERED',campaign=m['campaign'],manifest_sha256=d.digest(d.canonical(m)),window=m['window'],candidate_sha256=m['candidate_sha256'],rules_sha256=m['rules_sha256'])
    matches=[r for r in (json.loads(line) for line in raw.splitlines() if line.strip()) if all(r.get(k)==v for k,v in expected.items())]
    if len(matches)!=1 or utc_epoch(matches[0]['registered_at_utc'])>m['window']['W']*86400: raise Stop('no exact pre-window forward registration')
    return g


@contextmanager
def deadline(seconds):
    if seconds<=0: raise TimeoutError('deadline before attempt')
    started=time.monotonic();old_handler=signal.getsignal(signal.SIGALRM);old_timer=signal.getitimer(signal.ITIMER_REAL)
    def expired(*args): raise TimeoutError('hard wall-clock deadline')
    signal.signal(signal.SIGALRM,expired)
    signal.setitimer(signal.ITIMER_REAL,min(seconds,old_timer[0]) if old_timer[0]>0 else seconds)
    try: yield
    finally:
        signal.setitimer(signal.ITIMER_REAL,0);signal.signal(signal.SIGALRM,old_handler)
        if old_timer[0]>0: signal.setitimer(signal.ITIMER_REAL,max(.000001,old_timer[0]-(time.monotonic()-started)),old_timer[1])


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*a,**k): raise Stop('redirect forbidden')


def public_open(request,timeout):
    if request['method']!='GET' or request['host']!='api.binance.com' or request['endpoint'] not in ('/api/v3/exchangeInfo','/api/v3/klines'): raise Stop('HTTP allowlist')
    url='https://api.binance.com'+request['endpoint']+'?'+urllib.parse.urlencode(request['params'])
    # Explicit empty proxy mapping: no environment proxy credentials or cookies.
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
    req=urllib.request.Request(url,headers={'Accept-Encoding':'identity','User-Agent':'freqtrade-lab-forward139/1'},method='GET')
    return opener.open(req,timeout=timeout)


def stop(root,reason):
    p=root/'source-stop.json'
    if not p.exists(): d.write(p,dict(reason=reason,resumable=('budget' in reason or 'grant exhausted' in reason)));d.fsync_dir(root)


def fetch(root,m,g,request,target,open_response=public_open,now=time.time,sleep=time.sleep):
    """Caller holds the campaign writer lock and outer 180-second deadline."""
    check_grant(m,g)
    if not g['start_day'] <= request['day'] <= target < g['end_day']: raise Stop('request outside grant')
    if request not in d.request_plan(request['day'],target): raise Stop('request plan drift')
    key=d.digest(d.canonical(request));cache=root/'sources'/key
    rows=d.events(root/'source-attempts.jsonl');attempts=[r for r in rows if r['event']=='ATTEMPT']
    if cache.exists():
        receipt=json.loads((cache/'receipt.json').read_bytes());raw=(cache/'body.json').read_bytes()
        if d.digest(raw)!=receipt['sha256'] or receipt['key']!=key or receipt['request']!=request: raise Stop('immutable source changed')
        return json.loads(raw),receipt
    same=any(r['key']==key for r in attempts)
    bucket='normal_gets' if request['day']==target and not same else 'recovery_gets'
    if request['kind']=='metadata' and same: raise Stop('metadata retry not authorized')
    cap=256*1024 if request['kind']=='metadata' else 64*1024
    ceilings=g['cumulative_caps']
    if sum(r['bucket']==bucket for r in attempts)>=ceilings[bucket] or len(attempts)>=ceilings['gets'] or sum(r['byte_cap'] for r in attempts)+cap>ceilings['bytes']: raise Stop('source budget exhausted')
    # A byte-cap reservation survives crashes, so unknown bytes cannot be refunded.
    if attempts: sleep(1)  # Also safe across clock corrections/process restarts.
    index=len(attempts)+1
    d.append(root/'source-attempts.jsonl',dict(event='ATTEMPT',key=key,bucket=bucket,byte_cap=cap,started_epoch=now(),request=request,grant_sha256=d.digest(d.canonical(g))))
    raw=bytearray()
    try:
        with deadline(20),open_response(request,20) as response:
            if response.status!=200: raise Stop('HTTP '+str(response.status))
            if response.headers.get('Content-Encoding','identity')!='identity': raise Stop('encoded response')
            length=response.headers.get('Content-Length')
            if length is not None and int(length)>cap: raise Stop('Content-Length over byte cap')
            while True:
                chunk=response.read(min(8192,cap-len(raw)))
                if not chunk: break
                raw.extend(chunk)
                if len(raw)>=cap: raise Stop('stream byte ceiling')
        value=json.loads(raw)
        receipt=dict(sha256=d.digest(raw),received_epoch=now(),attempt=index,key=key,request=request)
        temp=root/'sources'/('attempt-'+str(index));temp.mkdir();d.write(temp/'receipt.json',receipt)
        with (temp/'body.json').open('xb') as stream: stream.write(raw);stream.flush();os.fsync(stream.fileno())
        d.fsync_dir(temp);os.rename(temp,cache);d.fsync_dir(root/'sources')
        d.append(root/'source-attempts.jsonl',dict(event='SUCCEEDED',key=key,bytes=len(raw),sha256=receipt['sha256']))
        return value,receipt
    except BaseException as error:
        d.append(root/'source-attempts.jsonl',dict(event='FAILED',key=key,bytes=len(raw),reason=type(error).__name__))
        if isinstance(error,(Stop,ValueError,urllib.error.HTTPError)): stop(root,type(error).__name__+':source rejected')
        raise


def parse_klines(value,day):
    if not isinstance(value,list) or len(value)>24: raise Stop('kline shape')
    rows=[];seen=set()
    for x in value:
        if not isinstance(x,list) or len(x)!=12 or type(x[0]) is not int or type(x[6]) is not int: raise Stop('kline schema')
        h=x[0]//3600000
        if x[0]%3600000 or not day*24<=h<(day+1)*24 or h in seen or not x[0]<=x[6]<=x[0]+3599999: raise Stop('kline time')
        if seen and h<=max(seen): raise Stop('kline order')
        seen.add(h);rows.append(dict(hour=h,ohlc=x[1:5],full=x[6]==x[0]+3599999))
    return rows


def initialize(m,g,now=time.time):
    check_grant(m,g)
    root=Path(m['run_root'])
    if root.exists():
        if json.loads((root/'contract.json').read_bytes())!=m: raise Stop('existing root belongs to another contract')
        d.committed(root,m);return {'status':'NO_OP_ALREADY_INITIALIZED','root':str(root)}
    if utc_epoch(g['authorized_at_utc'])>m['window']['W']*86400 or now()>=m['window']['W']*86400: raise Stop('initial authorization/start after W; cannot backdate')
    state=d.initial_state(rules_from_semantic(m['expected_metadata']),m['window']['W'],contract=m)
    parent=Path(tempfile.mkdtemp(prefix='.issue139-init-',dir=root.parent));stage=parent/'campaign'
    d.initialize(stage,d.pack(state,m),m)
    d.write(stage/'contract.json',m);(stage/'sources').mkdir();d.fsync_dir(stage)
    os.rename(stage,root);d.fsync_dir(root.parent);parent.rmdir()
    return {'status':'REAL_FORWARD_INITIALIZED_NO_GET','root':str(root)}


def run_daily(m,g,target,open_response=public_open,now=time.time,sleep=time.sleep,fault=lambda p:None):
    with deadline(180):
        return _run_daily(m,g,target,open_response,now,sleep,fault)


def _run_daily(m,g,target,open_response,now,sleep,fault):
    check_grant(m,g)
    root=Path(m['run_root'])
    if json.loads((root/'contract.json').read_bytes())!=m: raise Stop('campaign contract changed')
    with d.lock(root),deadline(180):
        previous=d.committed(root,m);s=d.unpack(previous,m)
        if m['window']['W']<=target<s['next_day']: return {'status':'NO_OP_COMMITTED','through_day':s['next_day']-1}
        halted=root/'source-stop.json'
        if halted.exists():
            h=d.digest(halted.read_bytes())
            if not json.loads(halted.read_bytes())['resumable'] or g.get('resume_stop_sha256')!=h: raise Stop('campaign stopped; explicit bound resumption required')
            os.rename(halted,root/('source-stop-resolved-'+h+'.json'));d.fsync_dir(root)
        if s['stopped']: raise Stop('joint risk/calendar stopped')
        if not g['start_day']<=s['next_day']<=target<g['end_day'] or target!=int(now()//86400)-1: raise Stop('not authorized latest closed UTC day')
        plan=d.request_plan(s['next_day'],target)
        tasks=[r for r in d.events(root/'tasks.jsonl') if r['event']=='STARTED']
        if any(r['target_day']==target and r['grant_sha256']==d.digest(d.canonical(g)) for r in tasks): return {'status':'NO_OP_ALREADY_ATTEMPTED_TODAY'}
        if (len(tasks)+1)*180>g['cumulative_caps']['task_seconds']: raise Stop('task time budget exhausted')
        if len(list((root/'commits').iterdir()))+target-s['next_day']+1>g['cumulative_caps']['data_days']: raise Stop('authorized data-day count exhausted')
        started=now();d.append(root/'tasks.jsonl',dict(event='STARTED',target_day=target,reserved_seconds=180,grant_sha256=d.digest(d.canonical(g))))
        try:
            info,meta_receipt=fetch(root,m,g,plan[0],target,open_response,now,sleep)
            if semantic(info)!=m['expected_metadata']: raise Stop('metadata material change before price')
            baseline=root/'metadata-baseline.json'
            if not baseline.exists():
                temp=root/('baseline-'+str(len(tasks)+1)+'.tmp')
                d.write(temp,dict(semantic_sha256=m['metadata_semantic_sha256'],first_response=meta_receipt));os.rename(temp,baseline);d.fsync_dir(root)
            elif json.loads(baseline.read_bytes())['semantic_sha256']!=m['metadata_semantic_sha256']: raise Stop('baseline drift')
            completed=[]
            for day in range(s['next_day'],target+1):
                previous=d.committed(root,m);s=d.unpack(previous,m)
                packet_path=root/f'accepted-{day}.json'
                if packet_path.exists():
                    packet=json.loads(packet_path.read_bytes())
                    for symbol,receipt in packet['source_receipts'].items():
                        source=root/'sources'/receipt['key'];raw=(source/'body.json').read_bytes()
                        if d.digest(raw)!=receipt['sha256'] or json.loads((source/'receipt.json').read_bytes())!=receipt: raise Stop('accepted source changed')
                        if symbol=='metadata':
                            if semantic(json.loads(raw))!=m['expected_metadata']: raise Stop('accepted metadata changed')
                        elif packet['bars'][symbol]!=parse_klines(json.loads(raw),day): raise Stop('accepted bars do not match source')
                else:
                    bars={};receipts={'metadata':meta_receipt}
                    for req in d.request_plan(day,day)[1:]:
                        value,receipt=fetch(root,m,g,req,target,open_response,now,sleep)
                        symbol=req['params']['symbol'].replace('USDT','/USDT');bars[symbol]=parse_klines(value,day);receipts[symbol]=receipt
                    packet=dict(kind='REAL_FORWARD',candidate_sha256=d.candidate_sha(),source_contract_sha256=d.digest(d.canonical(m)),day=day,
                                received_at_hour=int(max(r['received_epoch'] for r in receipts.values())//3600),bars=bars,source_receipts=receipts)
                    d.validate_day(packet,s,m)
                    temp=root/f'accepted-{day}-task-{len(tasks)+1}.tmp'
                    d.write(temp,packet);os.rename(temp,packet_path);d.fsync_dir(root)
                def guard(rows,recovery,slots):
                    bucket='recovery_cost_updates' if recovery else 'cost_updates'
                    used=sum(r['cost_slots'] for r in rows if r['event']=='RESERVED' and (r['bucket']=='recovery')==recovery)
                    if used+slots>g['cumulative_caps'][bucket]: raise Stop('cost-update grant exhausted')
                completed.append(d.commit_day(root,previous,packet,fault,contract=m,already_locked=True,budget_guard=guard))
            return dict(status='DAYS_COMMITTED',days=len(completed),observation='DELAYED_OBSERVATION_REAL')
        except BaseException as error:
            if isinstance(error,(Stop,ValueError)): stop(root,str(error))
            raise
        finally:
            d.append(root/'tasks.jsonl',dict(event='FINISHED',target_day=target,actual_elapsed=max(0,now()-started)))
