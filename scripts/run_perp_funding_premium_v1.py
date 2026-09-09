#!/usr/bin/env python3
"""Bounded offline native factor comparison; preparation never computes outcomes."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from lab.perp_baseline_runner import native_environment, load_source, audit_native, sha, write
PROTOCOL = ROOT/'docs/protocols/perp-funding-premium-v1.json'


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def event_diagnostic(frames, factors, events, start, end):
    """Frozen 24h labels are explanatory; never used to choose a parameter."""
    import pandas as pd
    from lab.perp_baseline import features
    from lab.perp_funding_premium import VARIANTS, gate_masks
    records = []
    for pair, frame in frames.items():
        f = features(frame).merge(factors[pair], on='date', validate='one_to_one').set_index('date')
        masks = {v: gate_masks(f, v) for v in VARIANTS}; ev = events[pair]
        for at, row in f.iterrows():
            side = 1 if row.baseline_long and row.persistence >= .25 else -1 if row.baseline_short and row.persistence <= -.25 else 0
            entered = at+pd.Timedelta(hours=2); closed = at+pd.Timedelta(hours=26)
            if (not side or pd.isna(row.risk_multiplier) or entered < start or closed >= end or
                    entered not in f.index or closed not in f.index): continue
            op = float(f.loc[entered, 'open']); cp = float(f.loc[closed, 'open'])
            funded = ev.loc[(ev.date > entered) & (ev.date <= closed)]
            flow = -side*float((funded.open_fund*funded.open_mark).sum())/op
            gross = side*(cp/op-1); cost = .0008*(1+cp/op)
            records.append(dict(entry=entered, gross=gross, cost=cost, funding=flow,
                net=gross-cost+flow, **{v: bool(mask[0 if side==1 else 1].loc[at]) for v,mask in masks.items()}))
    table = pd.DataFrame(records)
    def describe(part):
        return dict(events=len(part), common_72h_clusters=int(part.entry.dt.floor('72h').nunique()) if len(part) else 0,
            mean_gross=float(part.gross.mean()) if len(part) else None,
            mean_cost=float(part.cost.mean()) if len(part) else None,
            mean_funding=float(part.funding.mean()) if len(part) else None,
            mean_net=float(part.net.mean()) if len(part) else None)
    return dict(label='OVERLAPPING_24H_EVENTS_DEVELOPMENT_NOT_WALLET_OR_INDEPENDENT',
        parent=describe(table), variants={v: describe(table.loc[table[v]]) for v in VARIANTS}, confidence_interval=None)


def chinese_report(summary):
    lines = ['# BTC/ETH 资金费与 premium 固定符号门控开发报告 V1', '', summary['conclusion'], '',
        '所有数据均为已曝光开发历史，历史可用时点是假设，没有独立确认或真实成交证据。父 persistence 12h 结果复用并验 SHA，本轮未重算父策略。', '',
        '| 变体 | 价格毛额 USDT | Taker | 滑点假设 | 资金费现金流 | 净额 | 小时 MTM DD | 周期 / 72h 簇 |',
        '|---|---:|---:|---:|---:|---:|---:|---:|']
    for v, r in summary['variants'].items():
        lines.append(f"| {v} | {r['gross_price_effect_usdt']:.4f} | {r['taker_fee_usdt']:.4f} | {r['slippage_allowance_usdt']:.4f} | {r['funding_usdt']:.4f} | {r['net_usdt']:.4f} | {r['observed_hourly_mtm_drawdown']:.2%} | {r['native_position_cycles']} / {r['common_72h_entry_clusters']} |")
    lines += ['', f"唯一优先下一方向：{summary['unique_next_direction']}", '',
        '20% 是研究风险目标，略高不会机械淘汰；实际小时内回撤、盘口冲击和历史合约规则仍未知。过滤可能仅减少仓位/交易，需要结合事件层毛效应、换手及敞口判断。每币/方向、月收益、最差小时与交易、回撤持续时间、费用压力和完整回执均在 summary.json 与每变体产物中。', '',
        f"本次新增原生市场计算 {summary['new_native_calls_this_invocation']} 次；累计本轮 {summary['market_native_calls_total']} 次；技术重试 {summary['technical_retries']} 次。CPU/货币成本不可得，不估造。", '']
    return '\n'.join(lines)


def main():
    began = time.monotonic(); parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source-root', 'parent-root', 'output-root'):
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--check-only', action='store_true')
    parser.add_argument('--claim-json', type=Path)
    args = parser.parse_args(); env = native_environment()
    import pandas as pd
    from lab.perp_funding_premium import load_factor_source, run_native_factor
    p = json.loads(PROTOCOL.read_text()); parent = json.loads((args.parent_root/'manifest.json').read_text())
    if parent['idempotency_key'] != p['parent_result_idempotency_key']:
        raise ValueError('wrong parent experiment')
    for relative, value in parent['code'].items():
        if sha(ROOT/relative) != value: raise ValueError('frozen parent implementation changed: '+relative)
    frames, marks, events, metadata, core = load_source(args.source_root)
    if core != parent['source']: raise ValueError('factor study must preserve exact parent core inputs')
    parent_result = json.loads((args.parent_root/'persistence/summary.json').read_text())
    attempts = [json.loads(line) for line in (args.parent_root/'attempts.jsonl').read_text().splitlines() if line.strip()]
    prior = [a for a in attempts if a['event']=='COMPLETED' and a['variant']=='persistence']
    if len(prior)!=1 or prior[0]['summary_sha256'] != sha(args.parent_root/'persistence/summary.json'):
        raise ValueError('parent completed summary differs')
    for name, value in parent_result['artifacts'].items():
        if sha(args.parent_root/'persistence/exports'/name) != value: raise ValueError('parent native archive changed')
    start = pd.Timestamp(p['score_start']); end = pd.Timestamp(p['score_end_exclusive'])
    factors, factor_binding = load_factor_source(args.source_root, frames, start, end)
    source = dict(core=core, factors=factor_binding)
    paths = [PROTOCOL, ROOT/p['policy_path'], ROOT/'lab/perp_funding_premium.py',
        ROOT/'lab/perp_baseline_report.py', ROOT/'lab/portfolio_native_export.py', Path(__file__).resolve()]
    code = {str(path.relative_to(ROOT)): sha(path) for path in paths}; code.update(parent['code'])
    fingerprint = digest(dict(source=source, code=code))
    check = dict(status='READY_FACTOR_OFFLINE_DEVELOPMENT', idempotency_key=fingerprint,
        source=source, code=code, code_sha256=digest(code), data_sha256=digest(source),
        policy_sha256=sha(ROOT/p['policy_path']), environment=env,
        parent_summary_sha256=sha(args.parent_root/'persistence/summary.json'),
        prepared_at=pd.Timestamp.now(tz='UTC').isoformat(), preparation_seconds=time.monotonic()-began,
        market_native_calls=0, planned_new_native_calls=2)
    if args.check_only:
        print(json.dumps(check, ensure_ascii=False)); return
    if args.claim_json is None: raise ValueError('actual scheduler claim JSON required before market computation')
    claim = json.loads(args.claim_json.read_text())
    if (claim.get('status') != 'RUNNING' or claim.get('variants') != 2 or
            any(claim.get(k) != check[k] for k in ('code_sha256', 'data_sha256', 'policy_sha256'))):
        raise ValueError('claim status/variants/actual factor code-data-policy binding differs')
    root = args.output_root; root.mkdir(parents=True, exist_ok=True)
    with (root/'writer.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX|fcntl.LOCK_NB)
        manifest = root/'manifest.json'
        if manifest.exists() and json.loads(manifest.read_text())['idempotency_key'] != fingerprint:
            raise ValueError('factor output root drift; retain original and version explicitly')
        if not manifest.exists(): write(manifest, check)
        def append(row):
            with (root/'attempts.jsonl').open('a') as stream:
                stream.write(json.dumps(row, ensure_ascii=False)+'\n'); stream.flush(); os.fsync(stream.fileno())
        def no_network(event, args):
            if event in ('socket.connect', 'socket.getaddrinfo', 'socket.bind'):
                raise RuntimeError('factor native worker is offline')
        sys.addaudithook(no_network)
        results = {}; new_calls = 0
        for variant in p['variants']:
            output = root/variant
            if (output/'summary.json').exists():
                rows = [json.loads(line) for line in (root/'attempts.jsonl').read_text().splitlines() if line.strip()]
                complete = [r for r in rows if r['event']=='COMPLETED' and r['variant']==variant]
                if len(complete)!=1 or complete[0]['summary_sha256'] != sha(output/'summary.json'):
                    raise ValueError('factor completed result differs')
                results[variant] = json.loads((output/'summary.json').read_text())
                for name, value in results[variant]['files'].items():
                    if sha(output/name) != value: raise ValueError('retained factor artifact changed: '+name)
                continue
            if output.exists(): raise ValueError('unfinished factor attempt requires supervised versioned recovery')
            output.mkdir(); new_calls += 1
            append(dict(event='RESERVED', variant=variant, at=pd.Timestamp.now(tz='UTC').isoformat(), idempotency_key=fingerprint))
            started = time.monotonic()
            def alarm(*_): raise TimeoutError('240s factor native deadline')
            signal.signal(signal.SIGALRM, alarm); signal.alarm(240)
            try:
                result, archives = run_native_factor(output, frames, events, metadata, factors, variant, start, end)
                native_seconds = time.monotonic()-started; audit_start = time.monotonic()
                report, points = audit_native(result, marks, events, start, end)
                report.update(variant=variant, stage=p['stage'], artifacts=archives, native_seconds=native_seconds,
                    audit_seconds=time.monotonic()-audit_start, source_fingerprint=fingerprint,
                    delta_net_vs_parent_usdt=report['net_usdt']-parent_result['net_usdt'])
                write(output/'equity.json', points)
                report['files'] = {str(file.relative_to(output)): sha(file) for file in [output/'native-result.json',
                    output/'entry-audit.json', output/'equity.json', *[output/'exports'/name for name in archives]]}
                write(output/'summary.json', report); results[variant] = report
                append(dict(event='COMPLETED', variant=variant, at=pd.Timestamp.now(tz='UTC').isoformat(), summary_sha256=sha(output/'summary.json')))
                print(json.dumps(dict(variant=variant, net_usdt=report['net_usdt'], dd=report['observed_hourly_mtm_drawdown'])), flush=True)
            except BaseException as exc:
                write(output/'failure.json', dict(status='TECHNICAL_BLOCKED', economic_result=None, error=str(exc), traceback=traceback.format_exc()))
                append(dict(event='FAILED', variant=variant, error=str(exc), at=pd.Timestamp.now(tz='UTC').isoformat())); raise
            finally: signal.alarm(0)
        supported = {v:r for v,r in results.items() if r['net_usdt']>0 and r['common_72h_entry_clusters']>=12}
        conclusion = ('至少一项固定符号门控在本次开发样本成本后为正，仍需风险解释与真正未来确认。' if supported else
            '两项固定符号门控未形成样本充分的成本后支持，关闭本分支，不继续调阈值。')
        next_direction = p['unique_next_if_supported' if supported else 'unique_next_if_stopped']
        summary = dict(status='COMPLETED_DEVELOPMENT', idempotency_key=fingerprint,
            task_binding=dict(task_id=claim['id'], **{k:check[k] for k in ('code_sha256','data_sha256','policy_sha256')}),
            conclusion=conclusion, unique_next_direction=next_direction, supported_variants=list(supported),
            parent=parent_result, variants=results, event_layer=event_diagnostic(frames, factors, events, start, end),
            market_native_calls_total=len(results), new_native_calls_this_invocation=new_calls, parent_recomputed=False,
            technical_retries=0, independent_confirmation=False, preparation_seconds=check['preparation_seconds'],
            total_seconds=time.monotonic()-began, cpu_seconds=None, monetary_cost=None)
        write(root/'summary.json', summary); (root/'report.zh.md').write_text(chinese_report(summary))


if __name__ == '__main__': main()
