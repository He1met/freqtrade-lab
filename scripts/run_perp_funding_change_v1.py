#!/usr/bin/env python3
"""Two settled-funding controls using existing native and accounting components."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import signal
import sys
import time

REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO))
from lab import perp_schedule as legacy
from lab.perp_baseline_runner import native_environment, load_source, audit_native, sha, write
PROTOCOL=REPO/'docs/protocols/perp-funding-change-v1.json'
from scripts.run_perp_flow_reversal_v1 import NativeDeadline, digest, verify_files, reserve_once


def verify_entries(result, records, variant, schedules, start, end):
    if variant not in ('level_contrarian','change_contrarian'):
        raise ValueError('unregistered settled-funding variant')
    import math
    import pandas as pd
    from lab.perp_funding_change import filter_schedule
    tables={p:filter_schedule(f,start,end).set_index('execution_at',drop=False) for p,f in schedules.items()}
    seen=set();last_close={}
    for trade in sorted(result['trades'],key=lambda t:t['open_timestamp']):
        pair=trade['pair'];at=pd.to_datetime(trade['open_timestamp'],unit='ms',utc=True)
        closed=pd.to_datetime(trade['close_timestamp'],unit='ms',utc=True)
        if pair not in tables or at not in tables[pair].index:raise ValueError('fill is outside admitted event calendar')
        row=tables[pair].loc[at];duration=closed-at
        if (trade.get('enter_tag')!=variant or trade['leverage']!=1 or not start<=at<end or
                closed>end-pd.Timedelta(hours=1) or not pd.Timedelta(0)<=duration<=pd.Timedelta(hours=8)):
            raise ValueError('native fill tag/leverage/window/holding drift')
        if trade['exit_reason']!='stop_loss' and (trade['exit_reason']!='holding_8h' or duration!=pd.Timedelta(hours=8)):
            raise ValueError('non-stop fill must hold exactly eight hours')
        if pair in last_close and last_close[pair]>=at:raise ValueError('occupied-hour event was replayed after exit')
        last_close[pair]=closed
        key=(pair,row.event_id)
        if key in seen:raise ValueError('same funding event entered twice')
        seen.add(key)
        sign=lambda value:int(value>0)-int(value<0)
        direction=-sign(row.rate) if variant=='level_contrarian' else -sign(row.delta)
        side='short' if trade['is_short'] else 'long'
        if direction==0 or (direction<0)!=(side=='short'):raise ValueError('fill direction differs from frozen funding rule')
        expected=max(row.available_at,row.previous_available_at).floor('1h')+pd.Timedelta(hours=1)
        if at!=expected or row.date!=at-pd.Timedelta(hours=1):raise ValueError('funding entry is not the first strictly later boundary')
        matches=[r for r in records if r['pair']==pair and pd.Timestamp(r['at'])==at and r['accepted_stake']>0]
        if len(matches)!=1:raise ValueError('fill lacks one accepted entry audit')
        audit=matches[0]
        if (audit.get('event_id')!=row.event_id or audit.get('variant')!=variant or audit.get('side')!=side or
                audit.get('entry_confirmed') is not True or audit.get('multiplier')!=1):
            raise ValueError('entry event/variant/side/confirmation audit mismatch')
        for name in ('event_at','previous_event_at','available_at','previous_available_at','execution_at'):
            if pd.Timestamp(audit[name])!=row[name]:raise ValueError('entry timestamp audit mismatch: '+name)
        if pd.Timestamp(audit['signal_candle'])!=row.date:raise ValueError('entry signal carrier mismatch')
        for name in ('rate','previous_rate','delta'):
            if not math.isclose(float(audit[name]),float(row[name]),rel_tol=1e-10,abs_tol=1e-15):raise ValueError('entry funding audit mismatch')
    return dict(status='PASS',actual_position_cycles=len(result['trades']),event_unique=True,occupied_hour_replay=False)


def report_zh(summary):
    lines=['# BTC/ETH 已结算资金费水平与变化开发对照','',summary['conclusion'],'',
        '| 对照 | 毛额 USDT | Taker | 滑点 | 资金费 | 净额 | 小时MTM回撤 | 周期 / 簇 |',
        '| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    for name,r in summary.get('variants',{}).items():
        lines.append(f"| {name} | {r['gross_price_effect_usdt']:.4f} | {r['taker_fee_usdt']:.4f} | {r['slippage_allowance_usdt']:.4f} | {r['funding_usdt']:.4f} | {r['net_usdt']:.4f} | {r['observed_hourly_mtm_drawdown']:.2%} | {r['native_position_cycles']} / {r['common_72h_entry_clusters']} |")
    lines += ['', '唯一下一方向：'+summary.get('unique_next_direction','核已有产物，不重放。'),'',
        '全部为已曝光开发证据。历史资金费可用时间为假设，未验证历史PIT。每小时开始已有仓位则跳过该事件，不能同小时平仓后复活。固定carry_nonpaying确认保持；没有独立确认、盈利资格或实盘权限。','']
    if summary.get('error'):lines += [summary['error'],'']
    return '\n'.join(lines)


def prepare(args):
    from lab import perp_dispatch as dispatch
    env=native_environment()
    from lab.perp_funding_change import load_change_source
    protocol=json.loads(PROTOCOL.read_bytes())
    if (protocol['variants']!=['level_contrarian','change_contrarian'] or protocol['budget']['new_market_native_calls']!=2 or
            protocol['budget']['maximum_total_seconds']!=900 or protocol['policy_sha256']!=sha(args.policy)):
        raise ValueError('frozen two-control protocol/budget differs')
    if (sha(protocol['input_preflight_path'])!=protocol['input_preflight_sha256'] or
            sha(args.development_manifest)!=protocol['development_manifest_sha256'] or
            sha(REPO/protocol['mechanism_card'])!=protocol['mechanism_card_sha256'] or
            sha(args.dispatch_policy)!=protocol['dispatch_policy_sha256'] or
            args.source_root.resolve()!=Path(protocol['source_root']).resolve()):
        raise ValueError('preregistered preflight/source/manifest differs')
    # Admission must inspect actual market timestamps before any feature load.
    admission=dispatch.validate_development_manifest(args.development_manifest,sha(args.development_manifest),args.dispatch_policy)
    frames,marks,events,metadata,core=load_source(args.source_root)
    factors,factor_binding=load_change_source(args.source_root,frames)
    paths=[PROTOCOL,REPO/protocol['policy_path'],args.dispatch_policy,
        REPO/'lab/perp_funding_change.py',Path(__file__).resolve(),
        REPO/'scripts/run_perp_flow_reversal_v1.py',REPO/protocol['mechanism_card'],
        REPO/'lab/perp_dispatch.py',REPO/'scripts/perp_dispatch.py',
        REPO/'lab/perp_schedule.py',REPO/'lab/perp_baseline.py',
        REPO/'lab/perp_baseline_runner.py',REPO/'lab/perp_baseline_report.py',
        REPO/'lab/portfolio_native_export.py',REPO/'docs/protocols/perp-first-experiment-v1.json']
    code={str(p.relative_to(REPO)):sha(p) for p in paths}
    source_files={item['path']:item['sha256'] for item in core.values()}
    for item in factor_binding.values(): source_files[item['path']]=item['sha256']
    source_files[str(args.source_root/'receipt.json')]=sha(args.source_root/'receipt.json')
    manifest=json.loads(args.development_manifest.read_bytes())
    if Path(manifest['runtime_root']).resolve()!=args.runtime_root.resolve():
        raise ValueError('development admission runtime differs from selected runtime')
    admitted={item['path']:item['sha256'] for item in manifest['files']}
    if any(admitted.get(path)!=expected for path,expected in source_files.items()):
        raise ValueError('runner input was not present in the verified development admission')
    check=dict(status='READY_FROZEN_FUNDING_CHANGE_DEVELOPMENT',code=code,code_sha256=digest(code),
        data_sha256=sha(args.development_manifest),policy_sha256=sha(args.policy),
        development_manifest_path=str(args.development_manifest),development_manifest_sha256=sha(args.development_manifest),
        source_files=source_files,environment=env,admission=admission,market_native_calls=0,
        planned_new_native_calls=2,variants=protocol['variants'],economic_qualification=False,
        source_use='EXPOSED_DEVELOPMENT_ONLY',score_start=protocol['score_start'],score_end_exclusive=protocol['score_end_exclusive'])
    return check,protocol,(frames,marks,events,metadata,factors)


def execute(args,check,protocol,inputs,began):
    import pandas as pd
    from lab import perp_dispatch as dispatch
    from lab.perp_funding_change import run_native_change
    from lab.perp_baseline_report import period_diagnostics
    claim=json.loads(args.claim_json.read_bytes())
    frames,marks,events,metadata,factors=inputs
    start=pd.Timestamp(protocol['score_start']);end=pd.Timestamp(protocol['score_end_exclusive'])
    if not args.output_root.is_absolute(): raise ValueError('absolute output root required')
    args.output_root=args.output_root.resolve()
    if any((p/'.git').exists() for p in (args.output_root,*args.output_root.parents)):
        raise ValueError('absolute Git-external output required')
    with legacy.locked(args.runtime_root/'scheduler',args.policy) as (scheduler_root,policy,state):
        current=legacy.task_by_id(state,claim['id'])
        if (current!=claim or current.get('status')!='RUNNING' or current.get('kind')!='research' or
                current.get('variants')!=2 or current.get('max_seconds')!=protocol['budget']['maximum_total_seconds']):
            raise ValueError('actual RUNNING two-variant claim required')
        if any(current[k]!=check[k] for k in ('code_sha256','data_sha256','policy_sha256')):
            raise ValueError('actual code/data/policy claim mismatch')
        dispatch.validate_running_admission(scheduler_root,state,current,args.policy,args.dispatch_policy,datetime.now(timezone.utc))
        code_files={str(REPO/name):value for name,value in check['code'].items()}
        verify_files(code_files);verify_files(check['source_files'])
        out=args.output_root
        # This process has no replay path. Unknown or completed reservations are reconciled by reading artifacts.
        global_reservation=reserve_once(scheduler_root,current,args.claim_json,out,check)
        write(out/'manifest.json',check)
        remaining=current['max_seconds']-(datetime.now(timezone.utc)-legacy.utc(current['started_at'])).total_seconds()
        if remaining<1: raise ValueError('claim expired; retain reservation and reconcile')
        def deny(event,args):
            if event in ('socket.connect','socket.getaddrinfo','socket.bind'): raise RuntimeError('development native worker is offline')
        sys.addaudithook(deny)
        def deadline(*_): raise NativeDeadline('bounded development runtime expired')
        signal.signal(signal.SIGALRM,deadline);signal.alarm(max(1,int(remaining)))
        results={};calls=0;wrapper_attempts=0;timings={};summary=None
        binding=dict(task_id=current['id'],**{k:check[k] for k in ('code_sha256','data_sha256','policy_sha256')})
        def attempt(value):
            with (out/'attempts.jsonl').open('a') as f:
                f.write(json.dumps(value,ensure_ascii=False)+'\n');f.flush();os.fsync(f.fileno())
        try:
            for variant in protocol['variants']:
                wrapper_attempts+=1;at=datetime.now(timezone.utc).isoformat();tick=time.monotonic()
                attempt(dict(event='WRAPPER_STARTED',variant=variant,at=at,wrapper_attempt=wrapper_attempts))
                result,archives=run_native_change(out/variant,frames,events,metadata,factors,variant,start,end)
                calls+=1
                entries=verify_entries(result,json.loads((out/variant/'entry-audit.json').read_bytes()),variant,factors,start,end)
                audited,points=audit_native(result,marks,events,start,end)
                audited.update(variant=variant,artifacts=archives,source_use='EXPOSED_DEVELOPMENT_ONLY',
                    actual_entry_provenance=entries,periods=period_diagnostics(points,pd.Timestamp(protocol['training_end_exclusive'])))
                write(out/variant/'equity.json',points);write(out/variant/'summary.json',audited)
                timings[variant]=time.monotonic()-tick;results[variant]=audited
                attempt(dict(event='COMPLETED',variant=variant,at=datetime.now(timezone.utc).isoformat(),
                    summary_sha256=sha(out/variant/'summary.json'),native_and_audit_seconds=timings[variant]))
            verify_files(code_files);verify_files(check['source_files'])
            if sha(args.development_manifest)!=check['data_sha256']: raise ValueError('development admission changed during execution')
            if sha(protocol['input_preflight_path'])!=protocol['input_preflight_sha256']: raise ValueError('input preflight proof changed during execution')
            baseline=results['level_contrarian'];flow=results['change_contrarian']
            increment=flow['net_usdt']-baseline['net_usdt']
            enough=flow['native_position_cycles']>=30 and flow['common_72h_entry_clusters']>=12
            supported=enough and flow['gross_price_effect_usdt']>0 and flow['net_usdt']>0 and increment>0
            verdict='LIMITED_DEVELOPMENT_SUPPORT' if supported else 'UNDERPOWERED' if not enough else 'NO_INCREMENTAL_COST_SUPPORT_STOP_BRANCH'
            summary=dict(status='COMPLETED',conclusion='固定两变体开发对照完成：'+verdict+'；不授予独立确认或盈利资格。',
                verdict=verdict,task_binding=binding,variants=results,incremental_net_usdt=increment,
                unique_next_direction=protocol['unique_next_if_supported' if supported else 'unique_next_if_stopped'],
                market_native_calls_total=calls,new_native_calls_this_invocation=calls,wrapper_attempts=wrapper_attempts,technical_retries=0,
                independent_confirmation=False,economic_qualification=False,development_only=True,
                native_engine_start_reservations=sum((out/v/'native-started.json').exists() for v in protocol['variants']),
                native_engine_completions=sum((out/v/'native-completed.json').exists() for v in protocol['variants']),
                global_reservation_path=str(global_reservation),global_reservation_sha256=sha(global_reservation),
                risk_review={v:'RISK_RECALIBRATION_REQUIRED' if r['observed_hourly_mtm_drawdown']>=.30 else
                    'ABOVE_TARGET_REQUIRES_EXPLANATION' if r['observed_hourly_mtm_drawdown']>.20 else 'WITHIN_RESEARCH_TARGET'
                    for v,r in results.items()},
                preparation_seconds=check['preparation_seconds'],variant_native_and_audit_seconds=timings,
                total_seconds=time.monotonic()-began,cpu_seconds=None,monetary_cost=None)
        except BaseException as exc:
            starts=sum((out/v/'native-started.json').exists() for v in protocol['variants'])
            completed=sum((out/v/'native-completed.json').exists() for v in protocol['variants'])
            summary=dict(status='BLOCKED_RUNTIME',conclusion='本次独立开发执行或核账受阻；保留已用名额和原生产物，禁止自动重放。',
                task_binding=binding,error=type(exc).__name__+': '+str(exc),variants=results,
                market_native_calls_total=completed if starts==completed else None,native_engine_start_reservations=starts,
                native_engine_completions=completed,wrapper_attempts=wrapper_attempts,technical_retries=0,
                economic_result=None,verified_process_stopped=True)
            write(out/'summary.json',summary);(out/'report.zh.md').write_text(report_zh(summary));raise
        finally: signal.alarm(0)
        write(out/'summary.json',summary);(out/'report.zh.md').write_text(report_zh(summary))
        print(json.dumps(dict(status=summary['status'],summary_path=str(out/'summary.json'),report_path=str(out/'report.zh.md'))))


def main():
    began=time.monotonic();parser=argparse.ArgumentParser(description=__doc__)
    for name in ('source-root','output-root','runtime-root','development-manifest','dispatch-policy','policy'):
        parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--check-only',action='store_true');parser.add_argument('--claim-json',type=Path)
    args=parser.parse_args();check,protocol,inputs=prepare(args);check['preparation_seconds']=time.monotonic()-began
    if args.check_only: print(json.dumps(check,ensure_ascii=False));return
    if args.claim_json is None: raise ValueError('scheduler claim is required')
    execute(args,check,protocol,inputs,began)


if __name__=='__main__': main()
