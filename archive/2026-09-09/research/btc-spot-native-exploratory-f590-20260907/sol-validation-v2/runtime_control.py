import fcntl
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LEDGER = Path('/Users/shenjianpeng/Documents/freqtrade-lab-local/search-research-supervision-20260902/global-research-ledger.jsonl')
os.umask(0o077)

def sha(value):
    return hashlib.sha256(value).hexdigest()

def put(name, value):
    with (ROOT / name).open('x') as f:
        json.dump(value, f, indent=2, sort_keys=True)
        f.write('\n')

def append(value, expected=None):
    with Path(str(LEDGER) + '.lock').open('r+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        before = LEDGER.read_bytes()
        if expected is not None:
            assert sha(before) == expected, 'ledger changed; stop'
        record = {**value, 'cohort_id': 'sol-spot-fixed-rule-validation-f590-v2',
                  'recorded_at_utc': datetime.now(timezone.utc).isoformat(),
                  'previous_prefix_sha256': sha(before)}
        with LEDGER.open('ab') as f:
            if before and not before.endswith(b'\n'):
                f.write(b'\n')
            f.write(json.dumps(record, sort_keys=True, separators=(',', ':')).encode() + b'\n')
            f.flush()
            os.fsync(f.fileno())
        after = LEDGER.read_bytes()
        assert after.startswith(before)
        return {'before_sha256': sha(before), 'after_sha256': sha(after), 'original_prefix_preserved': True}

def verify_freeze():
    manifest = json.loads((ROOT / 'freeze-manifest.json').read_text())
    for name, digest in manifest['files'].items():
        assert sha((ROOT / name).read_bytes()) == digest, name

