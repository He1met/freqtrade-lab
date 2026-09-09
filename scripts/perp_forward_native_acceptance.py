#!/usr/bin/env python3
"""Freeze and consume one bounded observed-intent interval; default is read-only."""
import argparse
import fcntl
import json
from pathlib import Path
import signal
import sys
import time

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))


class Deadline(BaseException):pass


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('registration','confirmation-protocol','observer-binding','seed-root','incremental-root','signal-root','bundle-root','output-root','policy'):
        parser.add_argument('--'+name,type=Path,required=True)
    operation=parser.add_mutually_exclusive_group()
    operation.add_argument('--check-only',action='store_true')
    operation.add_argument('--freeze-bundle',action='store_true',help='After real data readiness, write immutable input snapshot; never invokes native')
    operation.add_argument('--execute',action='store_true')
    parser.add_argument('--claim-json',type=Path)
    args=parser.parse_args();began=time.monotonic()
    for name,value in vars(args).items():
        if isinstance(value,Path):setattr(args,name,value.resolve())
    from lab.perp_baseline_runner import native_environment,write,audit_native
    env=native_environment()
    from lab.perp_forward_signal import clock,dt,control
    from lab.perp_forward_native import PROTOCOL,snapshot,decode,run_native_acceptance,sha,read,digest
    spec=read(PROTOCOL);registration,confirmation,binding,identity=control(args.registration,args.confirmation_protocol,args.observer_binding)
    policy=read(args.policy)
    if policy.get('policy_version')!='BTC_ETH_PERP_AUTONOMOUS_V3':raise ValueError('current acceptance execution policy V3 required')
    if (identity['registration_sha256']!=spec['registration_sha256'] or
            identity['confirmation_protocol_sha256']!=spec['confirmation_protocol_sha256']):raise ValueError('fixed acceptance candidate differs')
    code=dict(registration['code_bindings']);code.update(binding['code_bindings'])
    for path in (PROTOCOL,args.registration,args.confirmation_protocol,Path(__file__).resolve(),ROOT/'lab/perp_forward_native.py'):
        code[str(path.resolve().relative_to(ROOT))]=sha(path)
    if clock()<dt(spec['earliest_ready_at']):
        print(json.dumps(dict(status='WAITING_DATA',reason='Fixed seven-hour observation interval and publication gate not complete',
            earliest_ready_at=spec['earliest_ready_at'],code_bindings=code,code_sha256=digest(code),data_sha256=None,policy_sha256=sha(args.policy),native_calls=0,economic_validation=False,
            preparation_seconds=time.monotonic()-began)))
        if args.execute or args.freeze_bundle:raise SystemExit(2)
        return
    bundle=args.bundle_root;manifest_path=bundle/'input-manifest.json';snapshot_path=bundle/'intent-snapshot.json'
    if manifest_path.exists():
        data=read(manifest_path)
        if sha(snapshot_path)!=data['intent_snapshot_sha256']:raise ValueError('frozen intent snapshot drift')
        snap=read(snapshot_path)
        if snap['identity']!=identity:raise ValueError('frozen candidate/observer identity changed')
    else:
        snap=snapshot(args.seed_root,args.incremental_root,args.signal_root,args.registration,args.confirmation_protocol,args.observer_binding,clock())
        data=dict(schema='perp-native-acceptance-input-v1',identity=identity,source_files=snap['source_files'],
            intent_content_sha256=digest(snap),signal_root=snap['signal_root'],start=snap['start'],end=snap['end'])
    frames,marks,events,metadata,factors,intents,coverage=decode(snap)
    if args.freeze_bundle:
        if manifest_path.exists():raise ValueError('input bundle already frozen; no overwrite')
        bundle.mkdir(parents=True,exist_ok=False)
        write(snapshot_path,snap);data['intent_snapshot_sha256']=sha(snapshot_path);data['intent_snapshot_path']=str(snapshot_path)
        write(manifest_path,data)
    preflight=dict(status='READY_NATIVE_ACCEPTANCE' if manifest_path.exists() else 'READY_TO_FREEZE_INPUTS',
        code_bindings=code,code_sha256=digest(code),data_sha256=sha(manifest_path) if manifest_path.exists() else None,
        actual_input_content_sha256=digest(data),policy_sha256=sha(args.policy),candidate_economic_policy_sha256=registration['policy_sha256'],
        source_manifest=data,input_manifest_path=str(manifest_path),coverage=coverage,environment=env,
        preparation_seconds=time.monotonic()-began,native_calls=0,economic_validation=False)
    if not args.execute:
        print(json.dumps(preflight,ensure_ascii=False));return
    if not manifest_path.exists() or args.claim_json is None:raise ValueError('frozen actual inputs and RUNNING claim are required')
    claim=read(args.claim_json)
    if (claim.get('status')!='RUNNING' or claim.get('kind')!='acceptance' or claim.get('native_calls')!=1 or claim.get('variants')!=0 or
            any(claim.get(k)!=preflight[k] for k in ('code_sha256','data_sha256','policy_sha256'))):raise ValueError('acceptance claim/code/data/policy mismatch')
    output=args.output_root;output.mkdir(parents=True,exist_ok=True)
    with (output/'writer.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if (output/'reservation.json').exists():raise ValueError('acceptance already reserved; inspect original, never silently rerun')
        write(output/'preflight.json',preflight);write(output/'reservation.json',dict(claim=claim,reserved_at=clock().isoformat(),native_calls=1))
        def no_network(event,args):
            if event in ('socket.connect','socket.getaddrinfo','socket.bind'):raise RuntimeError('acceptance native worker is offline')
        sys.addaudithook(no_network)
        def alarm(*_):raise Deadline('bounded acceptance deadline')
        signal.signal(signal.SIGALRM,alarm);signal.alarm(min(1800,int(claim.get('max_seconds',1800))))
        task_binding=dict(task_id=claim['id'],**{k:preflight[k] for k in ('code_sha256','data_sha256','policy_sha256')})
        native_started=None;native_started_at=None
        try:
            from datetime import timedelta
            start=dt(spec['window_start']);end=dt(spec['window_end_exclusive']);native_started=time.monotonic();native_started_at=clock().isoformat()
            result,archives=run_native_acceptance(output/'native',frames,events,metadata,factors,intents,start-timedelta(hours=spec['native_flat_prefix_hours']),end)
            native_seconds=time.monotonic()-native_started
            accounting,points=audit_native(result,marks,events,start,end)
            for trade in result['trades']:
                from datetime import datetime,timezone
                at=datetime.fromtimestamp(trade['open_timestamp']/1000,timezone.utc).isoformat()
                target=intents.get(at,{}).get(trade['pair'])
                if not target or target['intent']!=('short' if trade['is_short'] else 'long'):raise ValueError('native entry lacks same-time durable intention')
            for name,expected in code.items():
                if sha(ROOT/name)!=expected:raise ValueError('consumer code changed during execution')
            for name,expected in snap['source_files'].items():
                if sha(name)!=expected:raise ValueError('source evidence changed during execution')
            if (sha(manifest_path)!=preflight['data_sha256'] or sha(snapshot_path)!=data['intent_snapshot_sha256'] or
                    sha(args.policy)!=preflight['policy_sha256']):raise ValueError('execution binding changed during native call')
            limited=not result['trades'] or bool(coverage['omitted'])
            acceptance=dict(status='LIMITED_PASS' if limited else 'PASS',**identity,signal_root=snap['signal_root'],
                native_calls=1,economic_validation=False,economic_result=None,code_bindings=code,
                input_manifest_sha256=sha(manifest_path),intent_snapshot_sha256=sha(snapshot_path),coverage=coverage,
                native_position_cycles=len(result['trades']),native_orders=accounting['native_orders'],
                accounting_reconciliation=accounting['accounting_reconciliation'],actual_entry_provenance='PASS',
                preparation_seconds=preflight['preparation_seconds'],native_started_at=native_started_at,native_seconds=native_seconds,total_seconds=time.monotonic()-began,native_artifacts=archives,
                limitations=['Non-scoring seven-hour consumer engineering only','Missing/late intentions masked, never filled','Native intrahour/precision assumptions persist','No actual exchange fills or production protection evidence'])
            write(output/'acceptance.json',acceptance)
            summary=dict(status='COMPLETED',conclusion='已完成冻结真实意图的原生消费者验收；'+('零交易或缺失时段使证据受限，不能视为盈利验证。' if limited else '只证明接口一致性，不证明盈利。'),
                task_binding=task_binding,acceptance=acceptance,acceptance_sha256=sha(output/'acceptance.json'),
                native_calls=1,economic_validation=False,economic_result=None,monetary_cost=None)
            write(output/'summary.json',summary)
            (output/'report.zh.md').write_text('# 真实意图原生消费者验收\n\n'+summary['conclusion']+'\n\n'+json.dumps(coverage,ensure_ascii=False,indent=2)+'\n')
            print(json.dumps(dict(status=summary['status'],acceptance_status=acceptance['status'],summary_path=str(output/'summary.json')),ensure_ascii=False))
        except BaseException as exc:
            failure=dict(status='BLOCKED_RUNTIME',conclusion='原生消费者验收受阻，保留原次运行，不自动重复。',task_binding=task_binding,
                error=str(exc),native_calls=1,economic_validation=False,economic_result=None,monetary_cost=None,
                preparation_seconds=preflight['preparation_seconds'],native_started_at=native_started_at,
                native_elapsed_seconds=time.monotonic()-native_started if native_started is not None else None,total_seconds=time.monotonic()-began)
            write(output/'summary.json',failure)
            (output/'report.zh.md').write_text('# 原生消费者验收受阻\n\n'+failure['conclusion']+'\n\n错误：'+str(exc)+'\n')
            raise
        finally:signal.alarm(0)


if __name__=='__main__':main()
