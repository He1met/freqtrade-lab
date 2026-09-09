import fcntl
import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from lab.database import init_database, get_connection
from lab.bounded_research import load_profile_snapshot

ROOT = Path(__file__).resolve().parent
LEDGER = Path('/Users/shenjianpeng/Documents/freqtrade-lab-local/search-research-supervision-20260902/global-research-ledger.jsonl')
EXPECTED_LEDGER = 'b29b11a8e01f43c00b742c994fde5df2d77a54df8f02f99ba8b96e3a03b20d73'
os.umask(0o077)

def sha(b):
    return hashlib.sha256(b).hexdigest()

def put(name, value):
    with (ROOT/name).open('x') as f:
        json.dump(value, f, indent=2, sort_keys=True)

def append(value, expected=None):
    with Path(str(LEDGER)+'.lock').open('r+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        before=LEDGER.read_bytes()
        if expected is not None:
            assert sha(before)==expected, 'ledger changed; stop'
        record={**value,'cohort_id':ROOT.name,'recorded_at_utc':datetime.now(timezone.utc).isoformat(),'previous_prefix_sha256':sha(before)}
        with LEDGER.open('ab') as f:
            if before and not before.endswith(b'\n'):
                f.write(b'\n')
            f.write(json.dumps(record,sort_keys=True,separators=(',',':')).encode()+b'\n')
            f.flush();os.fsync(f.fileno())
        after=LEDGER.read_bytes()
        assert after.startswith(before)
        return {'before_sha256':sha(before),'after_sha256':sha(after),'original_prefix_preserved':True}

def main():
    freeze=json.loads((ROOT/'freeze-receipt.json').read_text())
    for name,digest in freeze['files'].items():
        assert sha((ROOT/name).read_bytes())==digest, name
    assert not (ROOT/'lab.sqlite').exists()
    assert not (ROOT/'synthetic-01').exists()
    entry=append({'record_type':'AUTHORIZED_NEW_OBSERVED_TRAINING_PROTOCOL','status':'AUTHORIZED_SYNTHETIC_THEN_CONDITIONAL_CAPTURE_R1',
        'authorization_source_thread':'01a05dcc-17fd-7972-9177-9fed95e4b07a',
        'pair':'BTC/USDT','mode':'EXPLORATORY','search_window':['2024-01-30','2024-12-31'],
        'source_window':['2024-01-01','2024-12-31'],'maximum_synthetic_calls':1,'maximum_capture_invocations':1,
        'maximum_R1_market_calls':1,'R2_D_H_Stress_benchmark_smoke_authorized':False,
        'old_training_seen':True,'old_invalid_and_no_replay_preserved':True,
        'freeze_receipt_sha256':sha((ROOT/'freeze-receipt.json').read_bytes())},EXPECTED_LEDGER)
    put('authorization-ledger-receipt.json',entry)
    init_database(ROOT/'lab.sqlite')
    profile=json.loads((ROOT/'profile.json').read_text())
    columns={**profile};columns['pairs_json']=json.dumps(columns.pop('pairs'))
    con=get_connection(ROOT/'lab.sqlite',must_exist=True)
    try:
        with con:
            con.execute('INSERT INTO research_profiles ('+','.join(columns)+') VALUES ('+','.join('?' for _ in columns)+')',tuple(columns.values()))
        assert load_profile_snapshot(con,profile['id'])==profile
        counts={t:con.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in ['research_profiles','generation_runs','candidates','research_runs','backtest_executions','releases']}
        assert con.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchone()[0]==6
    finally:
        con.close()
    put('database-initialization-receipt.json',{'database':str(ROOT/'lab.sqlite'),'profile_id':profile['id'],'profile_sha256':sha((ROOT/'profile.json').read_bytes()),'counts':counts,'original_profile_exact':True})
    pre=append({'record_type':'SYNTHETIC_NATIVE_AUTHORIZED_START','synthetic_native_calls_consumed':1,'market_native_calls':0,'capture_invocations':0,'source_market_values_read':False,'probe_sha256':sha((ROOT/'synthetic_probe.py').read_bytes())})
    put('synthetic-start-receipt.json',pre)
    command=json.loads((ROOT/'synthetic-command.json').read_text())['argv']
    timed_out=False
    with (ROOT/'synthetic.stdout').open('x') as out,(ROOT/'synthetic.stderr').open('x') as err:
        try:
            done=subprocess.run(command,cwd='/Users/shenjianpeng/.codex/worktrees/f590/freqtrade-lab',stdout=out,stderr=err,timeout=300)
            rc=done.returncode
        except subprocess.TimeoutExpired:
            timed_out=True;rc=None
    evidence=ROOT/'synthetic-01/evidence.json'
    result={'status':'SYNTHETIC_PASS' if rc==0 and evidence.exists() else 'SYNTHETIC_FAILED_STOP',
        'return_code':rc,'timeout':timed_out,'synthetic_native_calls':1,'market_native_calls':0,'capture_invocations':0,
        'database_counts':counts,'network_deny_installed_in_probe':True,
        'evidence_sha256':sha(evidence.read_bytes()) if evidence.exists() else None,
        'stdout_sha256':sha((ROOT/'synthetic.stdout').read_bytes()),'stderr_sha256':sha((ROOT/'synthetic.stderr').read_bytes()),
        'retry_allowed':False,'remaining_calls_require_success':True}
    put('synthetic-execution-receipt.json',result)
    result['ledger']=append({'record_type':'SYNTHETIC_NATIVE_TERMINAL',**result})
    put('synthetic-delivery-receipt.json',result)
    print(json.dumps(result,indent=2))

if __name__=='__main__':
    main()
