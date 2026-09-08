#!/usr/bin/env python3
"""One bounded heartbeat entry: checkpoint, incremental public data, then report due work."""
import argparse
from datetime import datetime, timezone
import fcntl
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lab import perp_data, perp_schedule


def run(root, policy_path, updater=perp_data.update):
    root = Path(root)
    policy, policy_sha = perp_schedule.load_policy(policy_path)
    if not root.is_absolute() or any((p/'.git').exists() for p in [root, *root.parents]):
        raise ValueError('absolute Git-external dedicated runtime required')
    root.mkdir(parents=True, exist_ok=True)
    with (root/'heartbeat.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {'status': 'LOCK_CONFLICT', 'requests': 0}
        state = perp_schedule.tick(root/'scheduler', policy_path)
        active = [t['id'] for t in state['tasks'] if t['status'] in {'RUNNING', 'UNKNOWN_INTERRUPTED'}]
        used_bytes = sum(p.stat().st_size for p in root.rglob('*') if p.is_file() and not p.is_symlink())
        if active:
            data = {'status': 'WAIT_RESEARCH_WRITER', 'requests': 0, 'task_ids': active}
        elif used_bytes >= policy['disk_soft_cap_bytes']:
            data = {'status': 'WAIT_DISK_BUDGET', 'requests': 0, 'bytes': used_bytes}
        else:
            data = updater(root/'data'/'incremental')
        clock_now = datetime.now(timezone.utc)
        observed = clock_now.isoformat()
        feed_state = root/'data'/'incremental'/'state.json'
        last_close = json.loads(feed_state.read_text()).get('last_complete_end') if feed_state.exists() else None
        age = (clock_now-datetime.fromisoformat(last_close.replace('Z','+00:00'))).total_seconds() if last_close else None
        freshness = dict(last_complete_end=last_close, age_seconds=age,
            status='UNKNOWN' if age is None else 'STALE' if age > 7200 else 'RECENT_CAPTURE',
            note='Capture freshness only; no forward strategy scoring or signal replay.')
        result = dict(status='HEARTBEAT_CHECKPOINT', observed_at=observed,
            policy_sha256=policy_sha, data=data, freshness=freshness,
            research=[dict(id=t['id'],status=t['status'],hypothesis=t['hypothesis'])
                      for t in state['tasks'] if t['status'] in perp_schedule.OPEN],
            due=state['due'], native_calls=0, production_orders=0,
            note='Research is dispatched separately only after claim and budget checks; data capture is not a trading signal.')
        # Store actual data freshness separately from due bookkeeping.
        with perp_schedule.locked(root/'scheduler', policy_path) as (_, _, current):
            current['data_checkpoint'] = dict(observed_at=observed, result=data, freshness=freshness)
            if data.get('status') in {'DATA_CAPTURED','NO_OP_ALREADY_CAPTURED'} and data.get('core_complete') is True:
                current['due']['hourly_data'].update(status='DATA_CAPTURE_RECEIPT', receipt_root=data.get('root'))
            result['due'] = current['due']
        folder = root/'heartbeat-receipts'; folder.mkdir(exist_ok=True)
        path = folder/(observed.replace(':','').replace('+','_')+'.json')
        perp_schedule.atomic(path, perp_schedule.canonical(result))
        return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--policy',type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(run(args.root,args.policy),ensure_ascii=False,allow_nan=False))


if __name__=='__main__':
    main()
