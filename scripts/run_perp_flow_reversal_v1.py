#!/usr/bin/env python3
"""Two frozen development controls, offline native fills and one shared writer."""
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
PROTOCOL=REPO/'docs/protocols/perp-flow-reversal-v1.json'


class NativeDeadline(BaseException):
    pass


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()


def verify_files(bindings):
    for path,expected in bindings.items():
        if sha(path)!=expected: raise ValueError('frozen source/code drift: '+str(path))


def reserve_once(scheduler_root,current,claim_json,out,check):
    if Path(current.get('expected_output_root','')).resolve()!=out.resolve():
        raise ValueError('output root differs from the registered experiment')
    out.mkdir(parents=True,exist_ok=True)
    reservation=out/'reservation.json'
    if reservation.exists() or (out/'manifest.json').exists():
        raise ValueError('existing experiment artifacts; reconcile without replay')
    folder=scheduler_root/'development-reservations';folder.mkdir(exist_ok=True)
    path=folder/(current['dispatch_experiment_key']+'.json')
    value=dict(task_id=current['id'],claim_sha256=sha(claim_json),reserved_at=datetime.now(timezone.utc).isoformat(),
        output_root=str(out),code_sha256=check['code_sha256'],data_sha256=check['data_sha256'],planned_native_calls=2)
    with path.open('x') as f:
        json.dump(value,f,indent=2);f.flush();os.fsync(f.fileno())
    write(reservation,value)
    return path


def verify_entries(result, records, variant, frames, factors, start, end):
    """Match actual fills to recorded, causally available frozen source rows."""
    import math
    import pandas as pd
    from lab.perp_flow_reversal import flow_features, flow_masks
    tables={pair:flow_features(frame.merge(factors[pair],on='date',validate='one_to_one')).set_index('date',drop=False)
        for pair,frame in frames.items()}
    for trade in result['trades']:
        at=pd.to_datetime(trade['open_timestamp'],unit='ms',utc=True)
        closed=pd.to_datetime(trade['close_timestamp'],unit='ms',utc=True)
        if (not start<=at<end or closed>end or not pd.Timedelta(0)<=closed-at<=pd.Timedelta(hours=12) or
                trade['leverage']!=1 or trade.get('enter_tag')!=variant):
            raise ValueError('native flow fill outside frozen time/holding/leverage bounds')
        source=at-pd.Timedelta(hours=2)
        if trade['pair'] not in tables or source not in tables[trade['pair']].index:
            raise ValueError('actual entry source is absent')
        matches=[r for r in records if r['pair']==trade['pair'] and pd.Timestamp(r['at'])==at and r['accepted_stake']>0]
        if len(matches)!=1: raise ValueError('actual entry lacks unique accepted audit; callback fallback is forbidden')
        r=matches[0];row=tables[trade['pair']].loc[[source]]
        if r.get('variant')!=variant or r.get('side')!=('short' if trade['is_short'] else 'long'):
            raise ValueError('actual entry side/variant audit mismatch')
        long,short=flow_masks(row,variant)
        if not bool((short if trade['is_short'] else long).iloc[0]):
            raise ValueError('actual fill violates frozen entry rule')
        if (pd.Timestamp(r['signal_candle'])!=source or pd.Timestamp(r['flow_available_at'])!=row.flow_available_at.iloc[0] or
                row.flow_available_at.iloc[0]>at or r['multiplier']!=1):
            raise ValueError('actual entry time/availability/stake audit mismatch')
        for name in ('shock_z','source_return','pressure_prior','pressure_current'):
            if not math.isclose(r[name],float(row[name].iloc[0]),rel_tol=1e-10,abs_tol=1e-12):
                raise ValueError('actual entry factor audit differs from frozen source: '+name)
    return dict(status='PASS',actual_position_cycles=len(result['trades']),callback_fallback_permitted=False)


def report_zh(summary):
    lines=['# BTC/ETH 冲击反转与主动成交转换开发对照', '',summary['conclusion'],'',
        '固定已曝光开发数据；两个变体共用相同窗口、原生撮合、1x共享钱包和完整费用。确认窗口的信号、交易和收益均不作为研究特征或选型输入；调度只核必需采集及意图回执的完整性、身份与时序。','',
        '| 变体 | 毛额 USDT | Taker | 滑点 | 资金费 | 净额 | 小时MTM回撤 | 周期 / 72h簇 |',
        '| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    for name,r in summary.get('variants',{}).items():
        lines.append(f"| {name} | {r['gross_price_effect_usdt']:.4f} | {r['taker_fee_usdt']:.4f} | {r['slippage_allowance_usdt']:.4f} | {r['funding_usdt']:.4f} | {r['net_usdt']:.4f} | {r['observed_hourly_mtm_drawdown']:.2%} | {r['native_position_cycles']} / {r['common_72h_entry_clusters']} |")
    lines+=['', '唯一优先下一方向：'+summary.get('unique_next_direction','先核本次原生产物和具体阻塞，不重放。'),'',
        'taker买入基币成交量是主动成交方向代理，不是OI、资金净流入或订单簿OFI。过滤会改变仓位与交易数，净额差不是已隔离的纯因子收益。约20%为研究目标；实际小时内风险、历史合约规则和盘口冲击仍未知。',
        '真实调用数、不可变来源、逐币/方向、费用压力、回撤持续时间与月收益均在机器摘要；所有结果仅为开发描述，独立确认与实盘资格均未授予。','']
    if summary.get('error'): lines+=['实际阻塞：'+summary['error'],'']
    return '\n'.join(lines)


def prepare(args):
    from lab import perp_dispatch as dispatch
    env=native_environment()
    from lab.perp_flow_reversal import load_flow_source
    protocol=json.loads(PROTOCOL.read_bytes())
    if (protocol['variants']!=['shock_rebound','flow_turn'] or protocol['budget']['new_market_native_calls']!=2 or
            protocol['budget']['maximum_total_seconds']!=900 or protocol['policy_sha256']!=sha(args.policy)):
        raise ValueError('frozen two-control protocol/budget differs')
    # Admission must inspect actual market timestamps before any feature load.
    admission=dispatch.validate_development_manifest(args.development_manifest,sha(args.development_manifest),args.dispatch_policy)
    frames,marks,events,metadata,core=load_source(args.source_root)
    factors,factor_binding=load_flow_source(args.source_root,frames)
    paths=[PROTOCOL,REPO/protocol['policy_path'],args.dispatch_policy,
        REPO/'lab/perp_flow_reversal.py',Path(__file__).resolve(),
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
    check=dict(status='READY_FROZEN_FLOW_DEVELOPMENT',code=code,code_sha256=digest(code),
        data_sha256=sha(args.development_manifest),policy_sha256=sha(args.policy),
        development_manifest_path=str(args.development_manifest),development_manifest_sha256=sha(args.development_manifest),
        source_files=source_files,environment=env,admission=admission,market_native_calls=0,
        planned_new_native_calls=2,variants=protocol['variants'],economic_qualification=False,
        source_use='EXPOSED_DEVELOPMENT_ONLY',score_start=protocol['score_start'],score_end_exclusive=protocol['score_end_exclusive'])
    return check,protocol,(frames,marks,events,metadata,factors)


def execute(args,check,protocol,inputs,began):
    import pandas as pd
    from lab import perp_dispatch as dispatch
    from lab.perp_flow_reversal import run_native_flow
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
                current.get('variants')!=2 or not 1<=current.get('max_seconds',0)<=900):
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
                result,archives=run_native_flow(out/variant,frames,events,metadata,factors,variant,start,end)
                calls+=1
                entries=verify_entries(result,json.loads((out/variant/'entry-audit.json').read_bytes()),variant,frames,factors,start,end)
                audited,points=audit_native(result,marks,events,start,end)
                audited.update(variant=variant,artifacts=archives,source_use='EXPOSED_DEVELOPMENT_ONLY',
                    actual_entry_provenance=entries,periods=period_diagnostics(points,pd.Timestamp(protocol['training_end_exclusive'])))
                write(out/variant/'equity.json',points);write(out/variant/'summary.json',audited)
                timings[variant]=time.monotonic()-tick;results[variant]=audited
                attempt(dict(event='COMPLETED',variant=variant,at=datetime.now(timezone.utc).isoformat(),
                    summary_sha256=sha(out/variant/'summary.json'),native_and_audit_seconds=timings[variant]))
            verify_files(code_files);verify_files(check['source_files'])
            if sha(args.development_manifest)!=check['data_sha256']: raise ValueError('development admission changed during execution')
            baseline=results['shock_rebound'];flow=results['flow_turn']
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
