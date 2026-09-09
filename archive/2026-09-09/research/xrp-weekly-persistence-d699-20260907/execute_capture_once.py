"""Invoke the frozen existing capture command once; retain control receipts."""
from pathlib import Path
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
import subprocess
import time

ROOT=Path(__file__).parent
LEDGER=Path('/Users/shenjianpeng/Documents/freqtrade-lab-local/search-research-supervision-20260902/global-research-ledger.jsonl')
os.umask(0o077)
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def put(name,value):
    with (ROOT/name).open('x') as stream:json.dump(value,stream,sort_keys=True,allow_nan=False)
    return sha(ROOT/name)
def append(record,expected=None):
    with Path(str(LEDGER)+'.lock').open('r+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        before=LEDGER.read_bytes();before_sha=hashlib.sha256(before).hexdigest()
        if expected is not None:assert before_sha==expected,'ledger changed before capture'
        record={**record,'previous_prefix_sha256':before_sha,'recorded_at_utc':datetime.now(timezone.utc).isoformat()}
        with LEDGER.open('ab') as stream:
            if before and not before.endswith(b'\n'):stream.write(b'\n')
            stream.write(json.dumps(record,sort_keys=True,separators=(',',':')).encode()+b'\n');stream.flush();os.fsync(stream.fileno())
        after=LEDGER.read_bytes();assert after.startswith(before)
        return dict(before_sha256=before_sha,after_sha256=hashlib.sha256(after).hexdigest(),old_prefix_preserved=True)

generation=json.loads((ROOT/'generation-execution-receipt.json').read_bytes())
assert generation['status']=='GENERATION_COMPLETED_CANDIDATE_APPROVED'
frozen=json.loads((ROOT/'freeze-package-receipt.json').read_bytes())
for name,record in frozen['files'].items():assert sha(ROOT/name)==record['sha256']
for name in ('capture-sd-01','source-sd-01'):assert not (ROOT/name).exists()
start=dict(status='AUTHORIZED_CAPTURE_STARTING',cohort_id=ROOT.name,pair='XRP/USDT:USDT',
    profile_id=generation['profile_id'],generation_id=generation['generation_id'],candidate_id=generation['candidate_id'],
    source_window=dict(start_utc='2023-10-23T00:00:00Z',end_exclusive_utc='2025-11-03T00:00:00Z'),
    protocol_sha256=frozen['protocol_sha256'],controlled_fetch_calls_so_far=0,
    exposure='S_D_DATA_ACQUISITION_AUTHORIZED_PENDING',S_signal_exposed=False,
    D_policy='MECHANICAL_QC_ONLY',H_policy='NO_H_SOURCE_OR_SIGNAL; PRIOR_METADATA_DISCLOSED',
    market_native_calls=0,search_window_consumed=False,automatic_retries=0,
    authorization='Supervisor 01a05dcc explicit frozen package acquisition authorization',
    created_at_utc=datetime.now(timezone.utc).isoformat())
receipt_sha=put('capture-once-guard.json',start)
ledger_start=append({**start,'record_type':'DATA_ACQUISITION_STARTED','receipt_path':str(ROOT/'capture-once-guard.json'),
                     'receipt_sha256':receipt_sha},frozen['ledger_observed_sha256'])
put('capture-start-ledger-receipt.json',ledger_start)
print(json.dumps({'status':'CAPTURE_STARTED','ledger_sha256':ledger_start['after_sha256']}),flush=True)
started=time.monotonic()
result=subprocess.run(['sh',str(ROOT/'capture-command.sh')],check=False)
capture=ROOT/'capture-sd-01'; source=ROOT/'source-sd-01'; receipts=capture/'http-receipts.jsonl'
rows=[] if not receipts.exists() else [json.loads(line) for line in receipts.read_bytes().splitlines() if line]
errors=[dict(index=i+1,error_class=r['error_class']) for i,r in enumerate(rows) if r.get('error_class')]
returned=None
if result.returncode==0:
    for line in (ROOT/'capture.stdout').read_text(errors='replace').splitlines()[::-1]:
        try: value=json.loads(line)
        except json.JSONDecodeError:continue
        if isinstance(value,dict) and set(value)=={'provenance_sha256','retrieval_receipt_sha256'}:returned=value;break
passed=(result.returncode==0 and returned is not None and source.is_dir() and not errors)
if passed:
    assert sha(source/'retained-data-provenance.json')==returned['provenance_sha256']
    assert sha(source/'retrieval_receipt.json')==returned['retrieval_receipt_sha256']
terminal=dict(status='SOURCE_CAPTURE_COMPILED' if passed else 'BLOCKED_DATA',return_code=result.returncode,
    elapsed_seconds=round(time.monotonic()-started,3),controlled_fetch_receipts=len(rows),
    wire_attempt_count='UNKNOWN',decoded_bytes=sum(r['bytes'] for r in rows),
    capture_disk_bytes=sum(p.stat().st_size for p in capture.rglob('*') if p.is_file()) if capture.exists() else 0,
    source_disk_bytes=sum(p.stat().st_size for p in source.rglob('*') if p.is_file()) if source.exists() else 0,
    errors=errors,source=returned,source_exists=source.exists(),cohort_id=ROOT.name,pair='XRP/USDT:USDT',
    D_policy='MECHANICAL_QC_ONLY',H_source_acquired=False,S_signal_exposed=False,
    economic_results_computed=False,market_native_calls=0,automatic_retries=0,
    finished_at_utc=datetime.now(timezone.utc).isoformat())
terminal_sha=put('capture-terminal-receipt.json',terminal)
ledger_end=append({**terminal,'record_type':'DATA_ACQUISITION_TERMINAL','exposure':'S_D_DATA_QC_ONLY',
    'search_window_consumed':False,'receipt_path':str(ROOT/'capture-terminal-receipt.json'),'receipt_sha256':terminal_sha})
put('capture-terminal-ledger-receipt.json',ledger_end)
print(json.dumps({**terminal,'ledger_sha256':ledger_end['after_sha256']}),flush=True)
raise SystemExit(0 if passed else 1)
