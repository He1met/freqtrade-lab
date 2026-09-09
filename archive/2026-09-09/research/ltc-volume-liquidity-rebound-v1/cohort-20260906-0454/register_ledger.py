"""Issue93 exact pre-value registration under the existing sidecar lock."""
import fcntl
import hashlib
import json
import os
from datetime import datetime,timezone
from pathlib import Path
from binding import logical_snapshot

ROOT=Path(__file__).resolve().parent
LEDGER=Path('/Users/shenjianpeng/Documents/freqtrade-lab-local/search-research-supervision-20260902/global-research-ledger.jsonl')
EXPECTED='8defdf5888380fe9c0ae95a99cc15be3c140de392441d67e7f229b893dd20f49'
def sha(data):return hashlib.sha256(data).hexdigest()

def main():
    frozen=json.loads((ROOT/'freeze-receipt.json').read_text())
    assert not (ROOT/'source-attempts.jsonl').exists() and not (ROOT/'source').exists()
    for n,h in frozen['files_sha256'].items():assert sha((ROOT/n).read_bytes())==h
    assert logical_snapshot(ROOT/'research.sqlite',frozen['profile_id'],frozen['candidate_id'])==json.loads((ROOT/'database-logical-snapshot.json').read_text())
    with open(str(LEDGER)+'.lock','a+b') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        before=LEDGER.read_bytes()
        assert len(before)==93576 and sha(before)==EXPECTED and before.endswith(b'\n')
        assert not any('LTC' in l.decode() for l in before.splitlines())
        row={'record_type':'COHORT_PREREGISTERED','recorded_at_utc':datetime.now(timezone.utc).isoformat(),'issue':93,'cohort_id':frozen['planned_campaign_id'],'planned_campaign_id':frozen['planned_campaign_id'],'actual_campaign_id':None,'supervisor_task':'01a05dcc-17fd-7972-9177-9fed95e4b07a','root':str(ROOT),'exchange':'okx','trading_mode':'spot','pair':'LTC/USDT','instrument_id':'LTC-USDT','timeframe':'1d','mechanism':'volume_liquidity_rebound_v1_conditional_reversal_family_not_proven_independent','search_timerange':'20210501-20240101','development_timerange':'20240101-20250101','holdout_timerange':'20250101-20260531','pre_roll_candles':40,'source_window':['2021-03-22T00:00:00Z','2025-01-01T00:00:00Z'],'status':'FROZEN_SOURCE_AUTHORIZED_SEARCH_NOT_AUTHORIZED','economic_results_opened':False,'native_backtests':0,'maximum_search_attempts':1,'maximum_search_rounds':1,'D':'PRODUCER_QC_ONLY_NOT_RUN','H':'SEALED_UNREAD_NOT_ACQUIRED','Stress':'SEALED_UNREAD_NOT_RUN','source_budget':{'maximum_http_requests':24,'maximum_seconds':1800,'automatic_retries':0},'profile_id':frozen['profile_id'],'candidate_id':frozen['candidate_id'],'generation_id':frozen['generation_id'],'protocol_sha256':frozen['protocol_sha256'],'strategy_sha256':frozen['files_sha256']['LtcVolumeLiquidityReboundV1.py'],'freeze_sha256':sha((ROOT/'freeze-receipt.json').read_bytes()),'database_logical_snapshot_sha256':frozen['database_binding']['snapshot_sha256'],'prior_ledger_sha256':EXPECTED}
        addition=(json.dumps(row,ensure_ascii=False,separators=(',',':'))+'\n').encode()
        with LEDGER.open('ab') as out:out.write(addition);out.flush();os.fsync(out.fileno())
        after=LEDGER.read_bytes();assert after==before+addition
        receipt={'status':'PREREGISTERED_BEFORE_FIRST_SOURCE_REQUEST','before_bytes':len(before),'before_sha256':sha(before),'after_bytes':len(after),'after_sha256':sha(after),'old_prefix_unchanged':True,'record_line':len(after.splitlines()),'new_record_sha256':sha(addition),'cohort_id':row['cohort_id'],'registry_method':'SINGLE_APPEND_UNDER_SIDECAR_FLOCK','script_sha256':sha(Path(__file__).read_bytes())}
        with (ROOT/'ledger-preregistration-receipt.json').open('x') as out:json.dump(receipt,out,indent=2)
        print(json.dumps(receipt))

if __name__=='__main__':main()
