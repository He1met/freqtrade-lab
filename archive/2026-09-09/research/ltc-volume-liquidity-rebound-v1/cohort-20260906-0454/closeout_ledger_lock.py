"""Hold the existing ledger sidecar lock around an exact apply_patch append."""
import fcntl
import hashlib
import json
from pathlib import Path
from datetime import datetime,timezone

ROOT=Path(__file__).resolve().parent
LEDGER=Path('/Users/shenjianpeng/Documents/freqtrade-lab-local/search-research-supervision-20260902/global-research-ledger.jsonl')
ACTUAL='0c9ab37c-7d1d-413b-bf9a-f42bec79860a'
def sha(b):return hashlib.sha256(b).hexdigest()
def matches(raw):
    def has(x):
        if isinstance(x,str):return x==ACTUAL
        if isinstance(x,dict):return any(has(v) for v in x.values())
        if isinstance(x,list):return any(has(v) for v in x)
        return False
    return [i for i,l in enumerate(raw.splitlines(),1) if l.strip() and has(json.loads(l))]

with open(str(LEDGER)+'.lock','a+b') as lock:
    fcntl.flock(lock,fcntl.LOCK_EX)
    before=LEDGER.read_bytes();found=matches(before)
    assert len(found)<=1
    if found:
        print(json.dumps({'already_registered':True,'actual_campaign_id':ACTUAL,'record_line':found[0],'bytes':len(before),'sha256':sha(before)}),flush=True)
    else:
        assert len(before)==96819 and sha(before)=='17a731bd6278b3eb8386edb4fe91957422e892da3b9bcbbe78e81a963f0c75ee'
        assert before.endswith(b'\n') and before.splitlines()[-1].strip()
        row={'record_type':'SEARCH_TERMINAL_IMPORTED','created_at_utc':datetime.now(timezone.utc).isoformat(),'issue':93,'campaign_id':ACTUAL,'cohort_id':ACTUAL,'planned_campaign_id':'8d8fb912-cd54-42d2-8d89-70b2dea155c3','exchange':'okx','trading_mode':'spot','pair':'LTC/USDT','instrument_id':'LTC-USDT','timeframe':'1d','status':'SEARCH_TERMINATED_NO_FINALIST','technical_status':'VALID','search_timerange':'20210501-20240101','search_window_consumed':True,'development_timerange':'20240101-20250101','development_status':'PRODUCER_QC_ONLY_NOT_RUN','holdout_timerange':'20250101-20260531','holdout_status':'SEALED_UNREAD_NOT_ACQUIRED','holdout_stress_status':'SEALED_UNREAD_NOT_RUN','attempts_consumed':1,'maximum_attempts':1,'remaining_attempts':0,'native_backtests':1,'research_run_id':None,'protocol_sha256':sha((ROOT/'protocol.md').read_bytes()),'terminal_sha256':sha((ROOT/'search/search-terminal.json').read_bytes()),'audit_sha256':sha((ROOT/'search-economic-audit.json').read_bytes()),'raw_zip_sha256':'4ed632a76a06ba0ddf433e8d9aca43c06956f6be510a43013a8d2bd4360ff419','research_terminal_path':str(ROOT/'research-terminal.md'),'identity_receipt_path':str(ROOT/'terminal-identity-verification.json'),'prior_ledger_sha256':sha(before)}
        line=json.dumps(row,ensure_ascii=False,separators=(',',':'))
        print(json.dumps({'already_registered':False,'before_bytes':len(before),'before_sha256':sha(before),'last_line':before.splitlines()[-1].decode(),'new_line':line}),flush=True)
        assert input()=='verify'
        after=LEDGER.read_bytes();assert after==before+(line+'\n').encode()
        now=matches(after);assert len(now)==1 and after[:len(before)]==before
        receipt={'method':'EXACT_APPLY_PATCH_APPEND_UNDER_SIDECAR_FLOCK','actual_campaign_id':ACTUAL,'before_bytes':len(before),'before_sha256':sha(before),'after_bytes':len(after),'after_sha256':sha(after),'old_prefix_unchanged':True,'blank_lines_preserved':True,'matching_actual_records':1,'record_line':now[0]}
        with (ROOT/'global-ledger-terminal-receipt.json').open('x') as out:json.dump(receipt,out,indent=2)
        print(json.dumps(receipt),flush=True)
