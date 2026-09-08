#!/usr/bin/env python3
"""First B/base or B/stress. Check-only by default; explicit external grant required."""
import argparse,hashlib,json,os,sys,subprocess,tempfile,fcntl
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from lab.spot139_binding import validate_sources,sha,deny_network,BindingError
SOURCE=Path('/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue-43-profile-driven-v1/freqtrade')
PYTHON=SOURCE.parent/'venv/bin/python'
BUDGET=Path('/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue139-spot-native-v1')


def worker(manifest,cost,output):
    sys.addaudithook(deny_network);sys.path.insert(0,str(SOURCE))
    from decimal import Decimal as D
    from lab.spot139_feed import decode,history_at
    from lab.spot139_model import SpotReference
    from lab.spot139_native_bridge import make_engine,Reconciler
    from freqtrade.persistence import LocalTrade
    hourly,daily,markets,rules=decode(manifest)
    job=next(j for j in manifest['jobs'] if j['cost']==cost)
    fee=D(job['fee_each_side']);slip=D(job['slippage_each_side'])
    model=SpotReference('B',rules,fee=fee,slip=slip)
    allowed={(s,h):bar[0][0] for s,bars in hourly.items() for h,bar in bars.items()}
    with tempfile.TemporaryDirectory(prefix='spot139-native-') as tmp:
        engine,exchange=make_engine(tmp,markets,fee)
        try:
            mapper=Reconciler(engine,fee);observed_dd=D(0);stale_hours=0
            for hour in range(1609459200//3600,1672531200//3600):
                opens={s:bars[hour][0][0] for s,bars in hourly.items() if hour in bars}
                lows={s:bars[hour-1][0][2] for s,bars in hourly.items() if hour-1 in bars}
                history=history_at(hour,hourly,daily) if hour%24==0 else None
                n=len(model.fills);state=model.on_hour(hour,opens,history,lows)
                for fill in model.fills[n:]:mapper.apply(fill,allowed)
                mapper.compare_model(model)
                observed_dd=max(observed_dd,(model.wallet.peak-model.equity())/model.wallet.peak)
                stale_hours+=int(state['stale'])
            engine.handle_left_open(LocalTrade.bt_trades_open_pp,{})
            result=dict(status='COMPLETED_EXPLORATORY_MAPPING',cost=cost,orders=mapper.rows,
                modeled_terminal=model.terminal(hour),native_terminal=engine.retained_terminal,
                native_cash=str(engine.wallets.get_free('USDT')),global_dust_block=model.blocked,
                observed_open_drawdown=str(observed_dd),real_drawdown='UNKNOWN',stale_hours=stale_hours,
                independent_qualification=False,native_matching_statistics_identical=False)
            Path(output).write_text(json.dumps(result,default=str,indent=2)+'\n')
        finally:engine.cleanup();exchange.close()


def main():
    p=argparse.ArgumentParser();p.add_argument('manifest');p.add_argument('--manifest-sha256',required=True)
    p.add_argument('--cost',choices=['base','stress'],required=True);p.add_argument('--execute',action='store_true')
    p.add_argument('--grant');p.add_argument('--grant-sha256');p.add_argument('--worker-output',help=argparse.SUPPRESS)
    args=p.parse_args()
    if sha(args.manifest)!=args.manifest_sha256:raise BindingError('manifest SHA changed')
    manifest=json.loads(Path(args.manifest).read_text());validate_sources(manifest)
    if manifest.get('protocol')!='ISSUE139_SPOT_NATIVE_MAPPING_V2':raise BindingError('wrong mapping version')
    native_sha=subprocess.check_output(['git','-C',str(SOURCE),'rev-parse','HEAD'],text=True).strip()
    if native_sha!=manifest['native_commit']:raise BindingError('native commit changed')
    if subprocess.check_output(['git','-C',str(SOURCE),'status','--porcelain'],text=True).strip():raise BindingError('native checkout is dirty')
    if args.worker_output:
        # Worker only accepts a parent-held inherited descriptor, never a public bypass flag.
        fd=int(os.environ.get('SPOT139_RESERVATION_FD','-1'))
        if fd<0 or os.fstat(fd).st_ino!=os.stat(BUDGET/'writer.lock').st_ino:raise BindingError('no parent reservation')
        worker(manifest,args.cost,args.worker_output);return
    if not args.execute:
        print(json.dumps(dict(status='READY_FOR_SUPERVISOR_EXECUTION_REVIEW',source_integrity='PASS',market_native_calls=0,reservations=0,economic_result=None)));return
    if not args.grant or not args.grant_sha256 or sha(args.grant)!=args.grant_sha256:raise BindingError('external grant required')
    grant=json.loads(Path(args.grant).read_text())
    if grant.get('market_execution_authorized') is not True or grant.get('manifest_sha256')!=args.manifest_sha256 or grant.get('costs')!=['base','stress'] or not grant.get('authorization_reference'):
        raise BindingError('external grant does not authorize this exact first batch')
    BUDGET.mkdir(parents=True,exist_ok=True)
    with (BUDGET/'writer.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        ledger=BUDGET/'calls.jsonl';events=[json.loads(x) for x in ledger.read_text().splitlines()] if ledger.exists() else []
        reserved=[e for e in events if e['event']=='RESERVED']
        if any(e['cost']==args.cost for e in reserved) or len(reserved)>=2:raise BindingError('duplicate/overbudget; failures consume slots')
        if args.cost=='stress' and not any(e['event']=='SUCCEEDED' and e['cost']=='base' for e in events):raise BindingError('base must complete before stress')
        if sum(e['event']=='RESERVED' for e in events)!=sum(e['event'] in ('FAILED','SUCCEEDED') for e in events):raise BindingError('unresolved previous reservation; no reclaim')
        def append(event,**extra):
            row=dict(event=event,cost=args.cost,manifest_sha256=args.manifest_sha256,grant_sha256=args.grant_sha256,**extra)
            with ledger.open('a') as stream:stream.write(json.dumps(row,sort_keys=True)+'\n');stream.flush();os.fsync(stream.fileno())
        append('RESERVED',historical_market_calls=28,old_sealed=10,first_batch_limit=2,timeout_seconds=180,technical_retries=0)
        output=BUDGET/(args.cost+'-result.json')
        try:
            env=dict(os.environ,SPOT139_RESERVATION_FD=str(lock.fileno()),PYTHONDONTWRITEBYTECODE='1')
            cmd=[str(PYTHON),str(Path(__file__).resolve()),str(Path(args.manifest).resolve()),'--manifest-sha256',args.manifest_sha256,'--cost',args.cost,'--worker-output',str(output)]
            run=subprocess.run(cmd,env=env,pass_fds=(lock.fileno(),),capture_output=True,text=True,timeout=180)
            if run.returncode:raise RuntimeError(run.stderr[-4000:])
            append('SUCCEEDED',result_sha256=sha(output));print(output)
        except BaseException as error:
            append('FAILED',error=str(error),economic_result=None);raise
if __name__=='__main__':main()
