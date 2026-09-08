#!/usr/bin/env python3
"""Default read-only endpoint check; never score a live or unfinished window."""
import argparse
from datetime import datetime,timedelta,timezone
import hashlib
import json
from pathlib import Path
import signal
import sys
import time

REPO=Path(__file__).resolve().parents[1];sys.path.insert(0,str(REPO))
from lab.perp_forward_signal import control,dt,read,atomic


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,default=str).encode()).hexdigest()
def endpoint(protocol,now):
    start=dt(protocol['window']['start_inclusive']);end=dt(protocol['window']['end_exclusive'])
    if start!=dt('2026-09-10T00:00:00Z') or end!=dt('2026-12-09T00:00:00Z') or end-start!=timedelta(days=90):
        raise ValueError('only the unchanged frozen 90-day confirmation is supported')
    return dict(status='WAIT_FORWARD' if now<end+timedelta(minutes=10) else 'CHECK_INPUT_READINESS',
        earliest_ready_at=(end+timedelta(minutes=10)).isoformat(),window_start=start.isoformat(),window_end_exclusive=end.isoformat(),
        execution_class='confirmation',native_calls=0,economic_result=None,economic_qualification=False)


def reserve_once(scheduler_root,claim,preflight,output,now):
    # Caller already holds the scheduler writer lock; survive a process crash
    # before state commit and refuse a rerun even with a different output path.
    folder=Path(scheduler_root)/'confirmation-reservations';folder.mkdir(exist_ok=True)
    path=folder/(claim['candidate_budget_key']+'-'+digest(claim['fixed_input_window'])+'.json')
    if path.exists():raise ValueError('confirmation already reserved; reconcile without replay')
    atomic(path,dict(task_id=claim['id'],reserved_at=now.isoformat(),output_root=str(output),
        code_sha256=preflight['code_sha256'],data_sha256=preflight['data_sha256'],policy_sha256=preflight['policy_sha256'],
        native_calls_reserved=1,maximum_seconds=2400))
    return path


def verify_final_bindings(code,sources,policy_path,policy_sha,manifest_path,manifest_sha,snapshot_path,snapshot_sha,artifacts):
    for name,expected in code.items():
        if sha(REPO/name)!=expected:raise ValueError('confirmation code changed during execution')
    expected=dict(sources);expected.update(artifacts)
    expected.update({str(policy_path):policy_sha,str(manifest_path):manifest_sha,str(snapshot_path):snapshot_sha})
    for name,value in expected.items():
        if sha(name)!=value:raise ValueError('confirmation input/artifact changed during execution')


class Deadline(BaseException):pass


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('registration','confirmation-protocol','observer-binding','seed-root','incremental-root','signal-root','bundle-root','output-root','native-acceptance','policy'):
        parser.add_argument('--'+name,type=Path,required=True)
    op=parser.add_mutually_exclusive_group();op.add_argument('--check-only',action='store_true');op.add_argument('--freeze-bundle',action='store_true');op.add_argument('--execute',action='store_true')
    parser.add_argument('--claim-json',type=Path);args=parser.parse_args();began=time.monotonic();now=datetime.now(timezone.utc)
    registration,protocol,binding,identity=control(args.registration,args.confirmation_protocol,args.observer_binding)
    code=dict(registration['code_bindings']);code.update(binding['code_bindings'])
    for path in (args.registration,args.confirmation_protocol,Path(__file__).resolve(),REPO/'lab/perp_forward_confirmation.py',REPO/'lab/perp_forward_native.py'):
        code[str(path.relative_to(REPO) if path.is_absolute() and path.is_relative_to(REPO) else path)]=sha(path)
    gate=endpoint(protocol,now);gate.update(code_bindings=code,code_sha256=digest(code),data_sha256=None,policy_sha256=sha(args.policy))
    if gate['status']=='WAIT_FORWARD':
        print(json.dumps(gate,ensure_ascii=False));return
    # No observed source, activation state, future economic value, or native
    # import is read before the real-clock endpoint guard above.
    from lab.perp_baseline_runner import native_environment
    env=native_environment()
    from lab import perp_forward_confirmation as c,perp_schedule as scheduler
    c.activation(args.signal_root,identity,protocol,args.native_acceptance)
    for path in (args.bundle_root,args.output_root):
        if not path.is_absolute() or any((p/'.git').exists() for p in (path,*path.parents)):
            raise ValueError('Git-external absolute artifact roots required')
    manifest_path=args.bundle_root/'input-manifest.json';snapshot_path=args.bundle_root/'intent-snapshot.json'
    if manifest_path.exists():
        manifest=read(manifest_path)
        if manifest.get('intent_snapshot_sha256')!=sha(snapshot_path):raise ValueError('frozen confirmation snapshot drift')
        snap=read(snapshot_path)
        if snap['identity']!=identity:raise ValueError('frozen confirmation identity changed')
    else:
        snap=c.snapshot(args.seed_root,args.incremental_root,args.signal_root,args.registration,args.confirmation_protocol,args.observer_binding,args.native_acceptance,now)
        manifest=dict(schema='perp-confirmation-input-v1',identity=identity,source_files=snap['source_files'],
            start=snap['start'],end=snap['end'],signal_root=snap['signal_root'],intent_content_sha256=digest(snap))
    frames,marks,events,metadata,factors,intents,coverage=c.decode(snap)
    if args.freeze_bundle:
        args.bundle_root.mkdir(parents=True,exist_ok=False);atomic(snapshot_path,snap)
        manifest.update(intent_snapshot_path=str(snapshot_path),intent_snapshot_sha256=sha(snapshot_path));atomic(manifest_path,manifest)
    preflight=dict(status='READY_NATIVE_ACCEPTANCE' if manifest_path.exists() else 'READY_TO_FREEZE_INPUTS',
        readiness_label='READY_NATIVE_CONFIRMATION' if manifest_path.exists() else 'READY_TO_FREEZE_CONFIRMATION_INPUTS',
        execution_class='confirmation',compatibility_note='READY_NATIVE_ACCEPTANCE is only the existing scheduler materialization wire status; this executor consumes the frozen 90-day confirmation window.',
        code_bindings=code,code_sha256=digest(code),data_sha256=sha(manifest_path) if manifest_path.exists() else None,
        policy_sha256=sha(args.policy),source_manifest=manifest,input_manifest_path=str(manifest_path),
        coverage=coverage,environment=env,preparation_seconds=time.monotonic()-began,native_calls=0,economic_result=None)
    if not args.execute:
        print(json.dumps(preflight,ensure_ascii=False));return
    if not manifest_path.exists() or args.claim_json is None:raise ValueError('frozen input bundle and actual RUNNING confirmation claim required')
    claim=read(args.claim_json);scheduler_root=args.signal_root.parent/'scheduler'
    with scheduler.locked(scheduler_root,args.policy) as (locked_root,policy,state):
        current=scheduler.task_by_id(state,claim['id'])
        if (current.get('status')!='RUNNING' or current.get('kind')!='confirmation' or current.get('native_calls')!=1 or current.get('variants')!=0 or
                any(t['id']!=current['id'] and t['status'] in ('RUNNING','UNKNOWN_INTERRUPTED') for t in state['tasks']) or
                any(current.get(k)!=claim.get(k) or current.get(k)!=preflight.get(k) for k in ('code_sha256','data_sha256','policy_sha256')) or
                current.get('candidate_sha256')!=identity['registration_sha256'] or current.get('frozen_contract_sha256')!=identity['confirmation_protocol_sha256'] or
                scheduler.validate_execution_class(current,policy)['candidate_budget_key']!=current.get('candidate_budget_key')):
            raise ValueError('actual confirmation claim/candidate/code/data/policy mismatch')
        if datetime.now(timezone.utc)<dt(current['contract_ready_at']):raise ValueError('WAIT_FORWARD: actual claim time gate')
        remaining=int(current['max_seconds']-(datetime.now(timezone.utc)-dt(current['started_at'])).total_seconds())
        if remaining<1:raise ValueError('claim runtime expired; reconcile without native replay')
        scheduler.verify_preflight(preflight,current)
        output=args.output_root;output.mkdir(parents=True,exist_ok=True)
        if (output/'reservation.json').exists():raise ValueError('output already reserved; never overwrite')
        reservation=reserve_once(locked_root,current,preflight,output,datetime.now(timezone.utc))
        atomic(output/'reservation.json',read(reservation));atomic(output/'preflight.json',preflight)
        task_binding=dict(task_id=current['id'],**{k:preflight[k] for k in ('code_sha256','data_sha256','policy_sha256')})
        def deny(event,args):
            if event in ('socket.connect','socket.getaddrinfo','socket.bind'):raise RuntimeError('confirmation worker is offline')
        sys.addaudithook(deny)
        def alarm(*_):raise Deadline('one confirmation exceeded its bounded wall time')
        signal.signal(signal.SIGALRM,alarm);signal.alarm(min(2400,remaining))
        try:
            start=dt(protocol['window']['start_inclusive']);end=dt(protocol['window']['end_exclusive']);native_started=time.monotonic()
            result,archives=c.run_native_confirmation(output/'native',frames,events,metadata,factors,intents,start-timedelta(hours=3),end)
            native_files={str(output/'native'/'exports'/name):value for name,value in archives.items()}
            for path in (output/'native'/'native-result.json',output/'native'/'entry-audit.json'):native_files[str(path)]=sha(path)
            for trade in result['trades']:
                at=datetime.fromtimestamp(trade['open_timestamp']/1000,timezone.utc);target=intents.get(at.isoformat(),{}).get(trade['pair'])
                if not 0<=trade['close_timestamp']-trade['open_timestamp']<=72*3600*1000:
                    raise ValueError('native position exceeds the frozen 72-hour holding limit')
                if not start<=at<dt(protocol['window']['last_new_entry_exclusive']) or not target or target['intent']!=('short' if trade['is_short'] else 'long'):
                    raise ValueError('native entry lacks same-time timely intent or exceeds frozen window')
            result_report,points=c.score(result,marks,events,start,end,coverage,protocol)
            verify_final_bindings(code,snap['source_files'],args.policy,preflight['policy_sha256'],manifest_path,preflight['data_sha256'],snapshot_path,manifest['intent_snapshot_sha256'],native_files)
            summary=dict(status='UNDERPOWERED' if result_report['decision']['verdict']=='UNDERPOWERED' else 'COMPLETED',
                conclusion='已完成固定 90 日窗口的一次原生确认。结论为 '+result_report['decision']['verdict']+'；不自动延长窗口或授予实盘资格。',
                task_binding=task_binding,result=result_report,native_calls=1,native_seconds=time.monotonic()-native_started,
                total_seconds=time.monotonic()-began,actual_entry_provenance='PASS',native_archives=archives,
                execution_class='confirmation',input_manifest_sha256=preflight['data_sha256'],intent_snapshot_sha256=manifest['intent_snapshot_sha256'],native_artifact_bindings=native_files)
            atomic(output/'equity.json',points);summary['equity_sha256']=sha(output/'equity.json')
        except BaseException as exc:
            summary=dict(status='BLOCKED_RUNTIME',conclusion='正式确认的原生执行或完整账务核验受阻；本次预约已消费，禁止自动重放。',
                task_binding=task_binding,error=str(exc),native_calls=1,economic_result=None,verified_process_stopped=True)
            atomic(output/'summary.json',summary);(output/'report.zh.md').write_text(c.chinese_report(summary));raise
        finally:signal.alarm(0)
        atomic(output/'summary.json',summary);(output/'report.zh.md').write_text(c.chinese_report(summary))
        print(json.dumps(dict(status=summary['status'],summary_path=str(output/'summary.json'),report_path=str(output/'report.zh.md')),ensure_ascii=False))


if __name__=='__main__':main()
