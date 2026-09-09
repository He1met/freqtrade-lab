#!/usr/bin/env python3
"""One locked, bounded native BTC/ETH experiment. Public data in; offline only."""
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
from lab.perp_baseline_runner import PROTOCOL,native_environment,load_source,run_native,audit_native,sha,write


class Deadline(BaseException):
    pass


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root',type=Path,required=True)
    parser.add_argument('--output-root',type=Path,required=True)
    parser.add_argument('--check-only',action='store_true')
    args=parser.parse_args()
    env=native_environment()
    import pandas as pd
    from lab.perp_baseline import calibrate_fixed
    protocol=json.loads(PROTOCOL.read_text())
    frames,marks,events,metadata,binding=load_source(args.source_root)
    start=pd.Timestamp(protocol['score_start']);end=pd.Timestamp(protocol['score_end_exclusive'])
    train_end=pd.Timestamp(protocol['training_end_exclusive'])
    fixed,n=calibrate_fixed(frames,start,train_end)
    code={str(p.relative_to(ROOT)):sha(p) for p in [PROTOCOL,ROOT/protocol['policy_path'],ROOT/'lab/perp_baseline.py',ROOT/'lab/perp_baseline_runner.py',Path(__file__).resolve()]}
    fingerprint=hashlib.sha256(json.dumps(dict(source=binding,code=code),sort_keys=True).encode()).hexdigest()
    check=dict(status='READY_OFFLINE_DEVELOPMENT',environment=env,source=binding,code=code,
        idempotency_key=fingerprint,fixed_multiplier=fixed,training_signal_rows=n,market_native_calls=0)
    if args.check_only:
        print(json.dumps(check,ensure_ascii=False));return
    root=args.output_root;root.mkdir(parents=True,exist_ok=True)
    with (root/'writer.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        manifest=root/'manifest.json'
        if manifest.exists() and json.loads(manifest.read_text())['idempotency_key']!=fingerprint:
            raise ValueError('existing experiment has different code/data; use a versioned root')
        if not manifest.exists():write(manifest,check)
        def append(value):
            with (root/'attempts.jsonl').open('a') as stream:
                stream.write(json.dumps(value,ensure_ascii=False)+'\n');stream.flush();os.fsync(stream.fileno())
        def deny_network(event,args):
            if event in ('socket.connect','socket.getaddrinfo','socket.bind'):
                raise RuntimeError('native market worker is strictly offline')
        sys.addaudithook(deny_network)
        results={}
        for variant in protocol['variants']:
            output=root/variant
            if (output/'summary.json').exists():
                attempts=[json.loads(line) for line in (root/'attempts.jsonl').read_text().splitlines() if line.strip()]
                completed=[a for a in attempts if a['variant']==variant and a['event']=='COMPLETED']
                if len(completed)!=1 or completed[0]['summary_sha256']!=sha(output/'summary.json'):
                    raise ValueError('completed output digest missing or changed')
                results[variant]=json.loads((output/'summary.json').read_text())
                if any(sha(output/'exports'/name)!=digest for name,digest in results[variant]['artifacts'].items()):
                    raise ValueError('retained native artifact changed')
                continue
            if output.exists():
                raise ValueError('unfinished/failed variant retained; requires explicitly versioned technical retry')
            output.mkdir()
            append(dict(event='RESERVED',variant=variant,idempotency_key=fingerprint,at=time.time()))
            began=time.monotonic()
            def alarm(*_):raise Deadline('240s native execution deadline')
            signal.signal(signal.SIGALRM,alarm);signal.alarm(240)
            try:
                native,artifacts=run_native(output,frames,events,metadata,variant,fixed,start,end)
                report,points=audit_native(native,marks,events,start,end)
                report.update(variant=variant,stage=protocol['stage'],artifacts=artifacts,
                    duration_seconds=time.monotonic()-began,source_fingerprint=fingerprint,
                    fixed_multiplier=fixed,training_signal_rows=n)
                write(output/'equity.json',points);write(output/'summary.json',report)
                results[variant]=report
                append(dict(event='COMPLETED',variant=variant,summary_sha256=sha(output/'summary.json'),at=time.time()))
                print(json.dumps(dict(variant=variant,net_usdt=report['net_usdt'],dd=report['observed_hourly_mtm_drawdown'])),flush=True)
            except BaseException as exc:
                write(output/'failure.json',dict(status='TECHNICAL_BLOCKED',economic_result=None,error=str(exc),traceback=traceback.format_exc()))
                append(dict(event='FAILED',variant=variant,error=str(exc),at=time.time()))
                raise
            finally:
                signal.alarm(0)
        write(root/'summary.json',dict(status='COMPLETED_DEVELOPMENT',idempotency_key=fingerprint,
            market_native_calls=len(results),variants=results,independent_confirmation=False))


if __name__=='__main__':main()
