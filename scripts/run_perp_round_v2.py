#!/usr/bin/env python3
"""Execute the two precommitted turnover variants; never recompute parent 12h."""
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

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from lab.perp_baseline_runner import native_environment,load_source,audit_native,sha,write
PROTOCOL=ROOT/'docs/protocols/perp-turnover-v2.json'


class Deadline(BaseException):pass


def main():
    began=time.monotonic()
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root',type=Path,required=True)
    parser.add_argument('--parent-root',type=Path,required=True)
    parser.add_argument('--output-root',type=Path,required=True)
    operation=parser.add_mutually_exclusive_group()
    operation.add_argument('--check-only',action='store_true')
    operation.add_argument('--execute',action='store_true',help='Run only after supervisor budget claim; default is read-only preflight')
    args=parser.parse_args();env=native_environment()
    import pandas as pd
    from lab.perp_variant_v2 import run_native_v2
    p=json.loads(PROTOCOL.read_text())
    parent=json.loads((args.parent_root/'manifest.json').read_text())
    if parent['idempotency_key']!=p['parent_result_idempotency_key']:
        raise ValueError('wrong parent experiment')
    for relative,digest in parent['code'].items():
        if sha(ROOT/relative)!=digest:raise ValueError('parent implementation changed: '+relative)
    frames,marks,events,metadata,binding=load_source(args.source_root)
    if binding!=parent['source']:
        raise ValueError('V2 must use exact parent public data')
    parent_result=json.loads((args.parent_root/'persistence/summary.json').read_text())
    parent_attempts=[json.loads(line) for line in (args.parent_root/'attempts.jsonl').read_text().splitlines() if line.strip()]
    expected=[a for a in parent_attempts if a['event']=='COMPLETED' and a['variant']=='persistence']
    if len(expected)!=1 or expected[0]['summary_sha256']!=sha(args.parent_root/'persistence/summary.json'):
        raise ValueError('parent completed result digest differs')
    for name,digest in parent_result['artifacts'].items():
        if sha(args.parent_root/'persistence/exports'/name)!=digest:
            raise ValueError('parent native archive differs')
    paths=[PROTOCOL,ROOT/p['policy_path'],ROOT/'lab/perp_variant_v2.py',ROOT/'lab/perp_baseline_report.py',
        ROOT/'lab/portfolio_native_export.py',Path(__file__).resolve()]
    code={str(path.relative_to(ROOT)):sha(path) for path in paths};code.update(parent['code'])
    fingerprint=hashlib.sha256(json.dumps(dict(source=binding,code=code),sort_keys=True).encode()).hexdigest()
    check=dict(status='READY_V2_OFFLINE_DEVELOPMENT',idempotency_key=fingerprint,
        source=binding,code=code,environment=env,parent_root=str(args.parent_root),
        parent_summary_sha256=sha(args.parent_root/'persistence/summary.json'),
        prepared_at=pd.Timestamp.now(tz='UTC').isoformat(),preparation_seconds=time.monotonic()-began,
        market_native_calls=0,planned_new_native_calls=2)
    if not args.execute:
        print(json.dumps(check,ensure_ascii=False));return
    root=args.output_root;root.mkdir(parents=True,exist_ok=True)
    start=pd.Timestamp(p['score_start']);end=pd.Timestamp(p['score_end_exclusive'])
    with (root/'writer.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        manifest=root/'manifest.json'
        if manifest.exists() and json.loads(manifest.read_text())['idempotency_key']!=fingerprint:
            raise ValueError('V2 root code/data drift; retain prior attempt and version separately')
        if not manifest.exists():write(manifest,check)
        def append(row):
            with (root/'attempts.jsonl').open('a') as stream:
                stream.write(json.dumps(row,ensure_ascii=False)+'\n');stream.flush();os.fsync(stream.fileno())
        def no_network(event,args):
            if event in ('socket.connect','socket.getaddrinfo','socket.bind'):
                raise RuntimeError('V2 native worker is offline')
        sys.addaudithook(no_network)
        results={};new_calls=0
        for variant,hours in p['variants'].items():
            output=root/variant
            if (output/'summary.json').exists():
                rows=[json.loads(line) for line in (root/'attempts.jsonl').read_text().splitlines() if line.strip()]
                complete=[r for r in rows if r['event']=='COMPLETED' and r['variant']==variant]
                if len(complete)!=1 or complete[0]['summary_sha256']!=sha(output/'summary.json'):
                    raise ValueError('V2 completed output digest differs')
                results[variant]=json.loads((output/'summary.json').read_text())
                for name,digest in results[variant]['files'].items():
                    if sha(output/name)!=digest:raise ValueError('V2 retained artifact changed: '+name)
                continue
            if output.exists():raise ValueError('unfinished attempt requires supervised versioned recovery')
            output.mkdir();new_calls+=1
            append(dict(event='RESERVED',variant=variant,at=pd.Timestamp.now(tz='UTC').isoformat(),idempotency_key=fingerprint))
            started=time.monotonic()
            def alarm(*_):raise Deadline('240s V2 deadline')
            signal.signal(signal.SIGALRM,alarm);signal.alarm(240)
            try:
                result,archives=run_native_v2(output,frames,events,metadata,hours,start,end)
                native_seconds=time.monotonic()-started;audit_start=time.monotonic()
                report,points=audit_native(result,marks,events,start,end)
                report.update(variant=variant,exit_hours=hours,stage=p['stage'],artifacts=archives,
                    native_seconds=native_seconds,audit_seconds=time.monotonic()-audit_start,
                    source_fingerprint=fingerprint,parent_net_usdt=parent_result['net_usdt'],
                    delta_net_vs_parent_usdt=report['net_usdt']-parent_result['net_usdt'])
                write(output/'equity.json',points)
                report['files']={str(file.relative_to(output)):sha(file) for file in [output/'native-result.json',output/'entry-audit.json',output/'equity.json',*[output/'exports'/name for name in archives]]}
                write(output/'summary.json',report);results[variant]=report
                append(dict(event='COMPLETED',variant=variant,at=pd.Timestamp.now(tz='UTC').isoformat(),summary_sha256=sha(output/'summary.json')))
                print(json.dumps(dict(variant=variant,net_usdt=report['net_usdt'],gross_usdt=report['gross_price_effect_usdt'],dd=report['observed_hourly_mtm_drawdown'])),flush=True)
            except BaseException as exc:
                write(output/'failure.json',dict(status='TECHNICAL_BLOCKED',economic_result=None,error=str(exc),traceback=traceback.format_exc()))
                append(dict(event='FAILED',variant=variant,error=str(exc),at=pd.Timestamp.now(tz='UTC').isoformat()))
                raise
            finally:signal.alarm(0)
        write(root/'summary.json',dict(status='COMPLETED_DEVELOPMENT',idempotency_key=fingerprint,
            market_native_calls_total=len(results),new_native_calls_this_invocation=new_calls,
            parent_12h_recomputed=False,parent=parent_result,variants=results,
            preparation_seconds=check['preparation_seconds'],total_seconds=time.monotonic()-began,
            technical_retries=0,independent_confirmation=False))


if __name__=='__main__':main()
