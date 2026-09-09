from pathlib import Path
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
import shlex
import subprocess
import sys

R = Path(__file__).resolve().parent
repo = Path('/Users/shenjianpeng/.codex/worktrees/8941/freqtrade-lab')
now = datetime.now(timezone.utc)
assert now >= datetime(2026, 9, 7, 6, 31, tzinfo=timezone.utc)
auth = json.loads((R/'recovery-authorization.json').read_text())
for name, key in [('final-protocol.md','protocol_sha256'), ('BnbDailyShockContinuation48H.py','strategy_sha256'), ('profile-snapshot.json','profile_sha256')]:
    assert hashlib.sha256((R/name).read_bytes()).hexdigest() == auth[key]
for name in ['native-capture-v2','complete-source-v2','source-publication-v2.json','source-capture-v2.log']:
    assert not (R/name).exists()
for line in subprocess.check_output(['ps','-axo','command='],text=True).splitlines():
    try: args = shlex.split(line)
    except ValueError: continue
    assert not any(Path(arg).name == 'fetch_binance_profile_data.py' for arg in args), 'Another native source capture is active'
record = {'record_type':'SOURCE_CAPTURE_RECOVERY_AUTHORIZED', 'issue':104,
    'cohort_id':'issue104-bnb-daily-shock-continuation-single-v1','pair':'BNB/USDT:USDT',
    'recorded_at_utc':now.isoformat(),'time_gate_passed':True,'duplicate_local_capture':False,
    'recovery_budget':1,'cumulative_capture_budget':2,'generation_additional_budget':0,
    'new_capture_root':str(R/'native-capture-v2'),'old_capture_preserved':True,
    'authorization_sha256':hashlib.sha256((R/'recovery-authorization.json').read_bytes()).hexdigest(),
    'native_Search_authorized':False}
with (R/'recovery-started.json').open('x') as f:json.dump(record,f,indent=2)
ledger = Path('/Users/shenjianpeng/Documents/freqtrade-lab-local/search-research-supervision-20260902/global-research-ledger.jsonl')
with Path(str(ledger)+'.lock').open('a+b') as lock:
    fcntl.flock(lock.fileno(),fcntl.LOCK_EX);before=ledger.read_bytes()
    record['previous_prefix_sha256']=hashlib.sha256(before).hexdigest()
    addition=(json.dumps(record,sort_keys=True)+'\n').encode()
    with ledger.open('ab') as f:f.write(addition);f.flush();os.fsync(f.fileno())
    after=ledger.read_bytes();assert after==before+addition
    (R/'recovery-ledger-receipt.json').write_text(json.dumps({'before_bytes':len(before),'after_bytes':len(after),
        'before_sha256':hashlib.sha256(before).hexdigest(),'after_sha256':hashlib.sha256(after).hexdigest(),'prefix_preserved':True},indent=2)+'\n')
argv=[sys.executable,str(repo/'scripts/fetch_binance_profile_data.py'),
    '--profile-database',str(R/'lab.sqlite'),'--profile-id','issue104-bnb-daily-shock-continuation-48h-v1',
    '--window-spec',str(R/'window.json'),'--pre-roll-candles','35','--economic-gate',str(R/'economic-gate.json'),
    '--single-baseline',str(R/'single-baseline.json'),'--capture-root',str(R/'native-capture-v2'),
    '--output-root',str(R/'complete-source-v2')]
with (R/'source-publication-v2.json').open('xb') as out, (R/'source-capture-v2.log').open('xb') as err:
    result=subprocess.run(argv,cwd=repo,stdout=out,stderr=err)
(R/'recovery-process-exit.json').write_text(json.dumps({'exit_code':result.returncode,'finished_at_utc':datetime.now(timezone.utc).isoformat(),'native_capture_ordinal':2})+'\n')
print(json.dumps({'exit_code':result.returncode,'native_capture_ordinal':2}))
sys.exit(result.returncode)
