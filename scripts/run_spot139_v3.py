#!/usr/bin/env python3
"""Fixed V3 B diagnostics: read-only default, external grant, shared ancestor locks."""
import argparse,json,os,sys,subprocess,fcntl,hashlib
from contextlib import ExitStack,contextmanager
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from lab.spot139_binding import validate_sources,sha,deny_network,BindingError
SOURCE=Path('/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue-43-profile-driven-v1/freqtrade')
PYTHON=SOURCE.parent/'venv/bin/python'
OLD=Path('/Users/shenjianpeng/.codex/runs/freqtrade-lab/btc-eth-portfolio-v1')
V2=Path('/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue139-spot-native-v1')
GLOBAL=Path('/Users/shenjianpeng/Documents/freqtrade-lab-local/search-research-supervision-20260902/global-research-ledger.jsonl')
BUDGET=Path('/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue139-spot-native-v3')
KEYS=[f'ISSUE139_B_RESIDUAL_V3/development-2021-2023/{c}' for c in ['base','stress']]
JOBS=[dict(key=k,mode='B',cost=c,fee_each_side=f,slippage_each_side=s,timeout_seconds=180,technical_retries=0,native_calls=1) for k,c,f,s in zip(KEYS,['base','stress'],['0.001','0.002'],['0.0006','0.0012'])]


def utc():return datetime.now(timezone.utc).isoformat()
def dump(path,value):
    with Path(path).open('w') as stream:json.dump(value,stream,indent=2,default=str,allow_nan=False);stream.write('\n');stream.flush();os.fsync(stream.fileno())

def events(path,allow_blank=False):
    if not path.exists():return []
    raw=path.read_bytes()
    if raw and not raw.endswith(b'\n'):raise BindingError('truncated ledger')
    return [json.loads(x) for x in raw.splitlines() if x.strip() or not allow_blank]

def completed_count(rows,key_field):
    pending=set();seen=set()
    for row in rows:
        key=row.get(key_field);event=row.get('event')
        if event=='RESERVED':
            if key in seen:raise BindingError('duplicate ancestor reservation')
            seen.add(key);pending.add(key)
        elif event in ('SUCCEEDED','FAILED','INTERRUPTED'):
            if key not in pending:raise BindingError('invalid ancestor terminal')
            pending.remove(key)
        elif event!='AUDIT_RECOVERED':raise BindingError('unknown ancestor event')
    if pending:raise BindingError('unresolved ancestor writer')
    return len(seen)


def preflight(manifest):
    if manifest.get('protocol')!='ISSUE139_B_RESIDUAL_V3_EXECUTION' or manifest.get('model')!='SpotResidualV3' or manifest.get('mapper')!='ReconcilerV3' or manifest.get('jobs')!=JOBS:raise BindingError('V3 model/cost/key binding changed')
    if manifest.get('window')!={'start_hour':447072,'end_hour_exclusive':464592}:raise BindingError('window changed')
    validate_sources(manifest)
    if subprocess.check_output(['git','-C',str(SOURCE),'rev-parse','HEAD'],text=True).strip()!=manifest['native_commit']:raise BindingError('native commit changed')
    if subprocess.check_output(['git','-C',str(SOURCE),'status','--porcelain'],text=True).strip():raise BindingError('native source dirty')
    for path in [OLD/'calls.jsonl',V2/'calls.jsonl',GLOBAL]:
        if sha(path)!=manifest['ancestor_sha256'][str(path)]:raise BindingError('ancestor drift')
    old=completed_count(events(OLD/'calls.jsonl'),'key');v2=completed_count(events(V2/'calls.jsonl'),'cost')
    checkpoints=[x for x in events(GLOBAL,allow_blank=True) if x.get('record_type')=='ISSUE139_SPOT_NATIVE_FIRST_BATCH_CHECKPOINT']
    if not checkpoints:raise BindingError('missing linked global checkpoint')
    checkpoint=checkpoints[-1]
    if checkpoint['historical_calls_sha256']!=sha(OLD/'calls.jsonl') or checkpoint['issue139_calls_sha256']!=sha(V2/'calls.jsonl') or checkpoint['old_consumed']!=old or checkpoint['new_reserved']!=v2 or checkpoint['total_consumed']!=old+v2:raise BindingError('global linked count mismatch')
    if old+v2!=30 or checkpoint['global_limit']!=96:raise BindingError('unapproved budget baseline')
    return old+v2


def suffix(manifest_sha):
    
    if not (BUDGET/'calls.jsonl').exists() and BUDGET.exists() and any(any(BUDGET.glob(pattern)) for pattern in ['*-result.json','*-hourly.jsonl','*-failure.json','*-command.json']):raise BindingError('V3 ledger missing with existing result; no reset')
    rows=events(BUDGET/'calls.jsonl');previous='0'*64;opened={};ended={}
    for row in rows:
        if row.get('previous_sha256')!=previous or row.get('manifest_sha256')!=manifest_sha or row.get('key') not in KEYS or row.get('cost')!=row.get('key','').rsplit('/',1)[-1]:raise BindingError('V3 ledger binding/chain changed')
        previous=hashlib.sha256(json.dumps(row,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        key=row['key']
        if row['event']=='RESERVED':
            if key in opened or len(opened)!=len(ended):raise BindingError('overlapping/duplicate V3 reservation')
            if key==KEYS[1] and ended.get(KEYS[0])!='SUCCEEDED':raise BindingError('stress before successful base')
            opened[key]=row
        elif row['event'] in ('SUCCEEDED','FAILED'):
            if key not in opened or key in ended:raise BindingError('invalid V3 terminal')
            if row.get('grant_sha256')!=opened[key].get('grant_sha256'):raise BindingError('terminal grant changed')
            if row['event']=='SUCCEEDED' and sha(BUDGET/(row['cost']+'-result.json'))!=row['result_sha256']:raise BindingError('completed result changed')
            ended[key]=row['event']
        else:raise BindingError('unknown V3 event')
    return rows,previous,opened,ended


def lock_paths():return [OLD/'writer.lock',V2/'writer.lock',Path(str(GLOBAL)+'.lock'),BUDGET/'writer.lock']

@contextmanager
def locked(execute):
    with ExitStack() as stack:
        locks=[]
        if execute:BUDGET.mkdir(parents=True,exist_ok=True)
        for path in lock_paths():
            if not path.exists() and not execute and path==BUDGET/'writer.lock':continue
            mode='a' if execute and path==BUDGET/'writer.lock' else 'r'
            stream=stack.enter_context(path.open(mode));fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB);locks.append(stream)
        yield locks


def validate_grant(args):
    if not args.grant or not args.grant_sha256 or sha(args.grant)!=args.grant_sha256:raise BindingError('external exact grant required')
    grant=json.loads(Path(args.grant).read_text())
    if grant.get('market_execution_authorized') is not True or grant.get('manifest_sha256')!=args.manifest_sha256 or grant.get('keys')!=KEYS or grant.get('costs')!=['base','stress'] or not grant.get('authorization_reference'):raise BindingError('grant does not authorize V3 pair')
    return grant


def worker(manifest,args):
    descriptors=json.loads(os.environ.get('SPOT139_V3_LOCK_FDS','[]'))
    if len(descriptors)!=4:raise BindingError('no parent lock/reservation')
    for fd,path in zip(descriptors,lock_paths()):
        actual=os.fstat(fd);expected=path.stat()
        if (actual.st_dev,actual.st_ino)!=(expected.st_dev,expected.st_ino):raise BindingError('wrong inherited lock')
    _,_,opened,ended=suffix(args.manifest_sha256);key=KEYS[['base','stress'].index(args.cost)]
    if key not in opened or key in ended:raise BindingError('worker has no pending reservation')
    sys.addaudithook(deny_network);sys.path.insert(0,str(SOURCE))
    from lab.spot139_feed import decode
    from lab.spot139_native_bridge import make_engine
    from lab.spot139_reconcile_v3 import ReconcilerV3
    from lab.spot139_report_v3 import create_model,RunReport,run_loop
    from freqtrade.persistence import LocalTrade
    import tempfile
    job=JOBS[['base','stress'].index(args.cost)];hourly,daily,markets,rules=decode(manifest)
    model=create_model(rules,job);report=RunReport(model);engine=None;exchange=None
    snapshots=BUDGET/(args.cost+'-hourly.jsonl');result_path=BUDGET/(args.cost+'-result.json')
    try:
        with tempfile.TemporaryDirectory(prefix='spot139-v3-') as tmp,snapshots.open('x') as stream:
            engine,exchange=make_engine(tmp,markets,model.fee);mapper=ReconcilerV3(engine,model.fee,rules)
            def snapshot(row):stream.write(json.dumps(row,default=str,allow_nan=False)+'\n');stream.flush()
            result=run_loop(model,mapper,hourly,daily,447072,464592,report,snapshot)
            stream.flush();os.fsync(stream.fileno());engine.handle_left_open(LocalTrade.bt_trades_open_pp,{})
            result.update(status='COMPLETED_V3_DEVELOPMENT_DIAGNOSTIC',cost=args.cost,key=key,model='SpotResidualV3',mapper='ReconcilerV3',native_orders=mapper.rows,native_terminal=engine.retained_terminal,native_positions=[dict(pair=t.pair,gross_amount=str(t.amount),stake=str(t.stake_amount),display_open_rate=str(t.open_rate),realized=str(t.realized_profit)) for t in LocalTrade.bt_trades_open],native_cash=str(engine.wallets.get_free('USDT')),native_realized=str(LocalTrade.bt_total_profit+sum(t.realized_profit for t in LocalTrade.bt_trades_open)),hourly_path=str(snapshots),hourly_sha256=sha(snapshots),manifest_sha256=args.manifest_sha256,grant_sha256=opened[key]['grant_sha256'])
            dump(result_path,result)
    except BaseException as error:
        dump(BUDGET/(args.cost+'-failure.json'),dict(status='FAILED_NOT_VALID_ECONOMIC_RESULT',error=str(error),economic_result=None,last_completed_hour=report.last_hour,confirmed_model_orders=report.orders,native_orders=mapper.rows if engine is not None and 'mapper' in locals() else [],hourly_sha256=sha(snapshots) if snapshots.exists() else None));raise
    finally:
        if engine is not None:engine.cleanup()
        if exchange is not None:exchange.close()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('manifest');parser.add_argument('--manifest-sha256',required=True);parser.add_argument('--cost',choices=['base','stress'],required=True)
    parser.add_argument('--execute',action='store_true');parser.add_argument('--grant');parser.add_argument('--grant-sha256');parser.add_argument('--worker',action='store_true',help=argparse.SUPPRESS)
    args=parser.parse_args()
    if sha(args.manifest)!=args.manifest_sha256:raise BindingError('manifest SHA changed')
    manifest=json.loads(Path(args.manifest).read_text())
    if args.worker:
        preflight(manifest);worker(manifest,args);return
    if args.execute:validate_grant(args)
    with locked(args.execute) as locks:
        baseline=preflight(manifest);rows,previous,opened,ended=suffix(args.manifest_sha256)
        if len(opened)!=len(ended):raise BindingError('unresolved V3 reservation; no reclaim')
        key=KEYS[['base','stress'].index(args.cost)]
        if not args.execute:
            print(json.dumps(dict(status='CHECK_ONLY_READY_FOR_REVIEW',model='SpotResidualV3',mapper='ReconcilerV3',cost=args.cost,execution_gate=('CONSUMED_NO_RETRY' if key in opened else 'STOPPED_FAILURE' if 'FAILED' in ended.values() else 'BASE_SUCCESS_REQUIRED' if args.cost=='stress' and ended.get(KEYS[0])!='SUCCEEDED' else 'EXTERNAL_GRANT_REQUIRED'),source_integrity='PASS',ancestor_consumed=baseline,v3_reserved=len(opened),v3_status=ended,global_consumed=baseline+len(opened),market_calls_this_check=0,reservations_this_check=0,economic_result=None)));return
        if key in opened or len(opened)>=2 or 'FAILED' in ended.values():raise BindingError('consumed/failed V3 batch; no retry')
        if args.cost=='stress' and ended.get(KEYS[0])!='SUCCEEDED':raise BindingError('base must succeed before stress')
        def append(event,**extra):
            nonlocal previous
            row=dict(event=event,key=key,cost=args.cost,at_utc=utc(),manifest_sha256=args.manifest_sha256,grant_sha256=args.grant_sha256,previous_sha256=previous,**extra)
            raw=json.dumps(row,sort_keys=True,separators=(',',':')).encode()+b'\n'
            with (BUDGET/'calls.jsonl').open('ab') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
            fd=os.open(BUDGET,os.O_RDONLY)
            try:os.fsync(fd)
            finally:os.close(fd)
            previous=hashlib.sha256(raw.rstrip(b'\n')).hexdigest()
        append('RESERVED',ancestor_consumed=baseline,total_consumed_after=baseline+len(opened)+1,timeout_seconds=180,technical_retries=0,ancestor_sha256=manifest['ancestor_sha256'])
        started=utc()
        try:
            env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',SPOT139_V3_LOCK_FDS=json.dumps([s.fileno() for s in locks]))
            cmd=[str(PYTHON),str(Path(__file__).resolve()),str(Path(args.manifest).resolve()),'--manifest-sha256',args.manifest_sha256,'--cost',args.cost,'--worker']
            started=utc();run=subprocess.run(cmd,env=env,pass_fds=tuple(s.fileno() for s in locks),capture_output=True,text=True,timeout=180)
            dump(BUDGET/(args.cost+'-command.json'),dict(started_at=started,finished_at=utc(),returncode=run.returncode,stdout=run.stdout,stderr=run.stderr))
            if run.returncode:raise RuntimeError(run.stderr[-6000:])
            result_path=BUDGET/(args.cost+'-result.json');result=json.loads(result_path.read_text())
            if result.get('status')!='COMPLETED_V3_DEVELOPMENT_DIAGNOSTIC' or result.get('key')!=key:raise BindingError('worker result identity/status mismatch')
            append('SUCCEEDED',result_sha256=sha(result_path));print(result_path)
        except BaseException as error:
            if not (BUDGET/(args.cost+'-command.json')).exists():dump(BUDGET/(args.cost+'-command.json'),dict(started_at=started,finished_at=utc(),error=str(error),timeout_seconds=180))
            failure=BUDGET/(args.cost+'-failure.json')
            append('FAILED',error=str(error),economic_result=None,failure_receipt_sha256=sha(failure) if failure.exists() else None);raise
if __name__=='__main__':main()
