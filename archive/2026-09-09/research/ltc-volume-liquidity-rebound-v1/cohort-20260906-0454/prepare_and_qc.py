"""One successful source -> pure QC and the existing isolated S consumer only."""
import hashlib
import json
import subprocess
import sys
from pathlib import Path
import numpy as np
import pandas as pd
import pyarrow.feather as feather
from binding import logical_snapshot

ROOT=Path(__file__).resolve().parent
PROJECT=Path('/Users/shenjianpeng/.codex/worktrees/3c7c/freqtrade-lab')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def dates(path,start,stop,rows):
    df=feather.read_feather(path)
    expected=pd.date_range(start,stop,freq='D',inclusive='left',tz='UTC')
    assert len(df)==rows==len(expected)
    actual=pd.DatetimeIndex(df.date)
    assert str(actual.tz)=='UTC' and bool((actual==expected).all())
    assert list(df.columns)==['date','open','high','low','close','volume']
    a=df[['open','high','low','close','volume']].to_numpy()
    assert np.isfinite(a).all() and (a>0).all()
    assert ((df.high>=df.open)&(df.high>=df.close)&(df.low<=df.open)&(df.low<=df.close)&(df.high>=df.low)).all()
    return {'rows':len(df),'start':df.date.iloc[0].isoformat(),'last':df.date.iloc[-1].isoformat(),'end_exclusive':expected[-1].__add__(pd.Timedelta(days=1)).isoformat(),'utc_exact_continuity':True,'positive_finite_ohlcv':True,'ohlc_consistent':True,'sha256':sha(path)}

def main():
    assert not (ROOT/'search').exists()
    frozen=json.loads((ROOT/'freeze-receipt.json').read_text())
    for n,h in frozen['files_sha256'].items():assert sha(ROOT/n)==h
    for p,h in {**frozen['producer_files_sha256'],**frozen['native_files_sha256']}.items():assert sha(Path(p))==h
    assert logical_snapshot(ROOT/'research.sqlite',frozen['profile_id'],frozen['candidate_id'])==json.loads((ROOT/'database-logical-snapshot.json').read_text())
    source=ROOT/'source';prov=source/'retained-data-provenance.json';receipt=source/'retrieval_receipt.json'
    rr=json.loads(receipt.read_text());attempts=[json.loads(x) for x in (ROOT/'source-attempts.jsonl').read_text().splitlines()]
    assert attempts[-1]=={'attempts':15,'event':'SOURCE_COMPLETED'}
    assert sum(x['event']=='ATTEMPT_BEFORE_NETWORK' for x in attempts)==15
    assert len(rr['requests'])==15 and rr['instrument_id']=='LTC-USDT' and rr['pair']=='LTC/USDT'
    assert all(x['status_code']==200 for x in attempts if x['event']=='ATTEMPT_RETURNED')
    assert not any(x['event']=='ATTEMPT_FAILED' for x in attempts)
    source_qc=dates(source/'data/okx/LTC_USDT-1d.feather','2021-03-22','2025-01-01',1381)
    # Do not emit any price/volume/statistic, signal or profitability from D.
    cmd=[sys.executable,str(PROJECT/'scripts/run_bounded_research_pilot.py'),'prepare-search-data',
         '--source-root',str(source),'--source-provenance-sha256',sha(prov),'--source-receipt-sha256',sha(receipt),
         '--database',str(ROOT/'research.sqlite'),'--profile-id',frozen['profile_id'],
         '--search-timerange','20210501-20240101','--development-timerange','20240101-20250101','--pre-roll-candles','40',
         '--economic-gate',str(ROOT/'economic-gate.json'),'--single-baseline',str(ROOT/'single-baseline.json'),
         '--output-root',str(ROOT/'search')]
    (ROOT/'prepare-search-command-2.json').write_text(json.dumps(cmd,indent=2)+'\n')
    with (ROOT/'prepare-search-command-2.log').open('xb') as log:
        subprocess.run(cmd,cwd=PROJECT,stdout=log,stderr=subprocess.STDOUT,check=True)
    targets=list((ROOT/'search').rglob('LTC_USDT-1d.feather'))
    assert targets
    sliced={str(p.relative_to(ROOT/'search')):dates(p,'2021-03-22','2024-01-01',1015) for p in targets}
    assert not list((ROOT/'search').rglob('*.zip')) and not (ROOT/'search/search-terminal.json').exists()
    assert logical_snapshot(ROOT/'research.sqlite',frozen['profile_id'],frozen['candidate_id'])==json.loads((ROOT/'database-logical-snapshot.json').read_text())
    result={'status':'SOURCE_AND_S_CONSUMER_QC_PASSED_SEARCH_NOT_RUN','actual_http_requests':15,'source':source_qc,
        'search_slices':sliced,'source_provenance_sha256':sha(prov),'source_receipt_sha256':sha(receipt),
        'source_all_file_sha256':{str(p.relative_to(source)):sha(p) for p in source.rglob('*') if p.is_file()},
        'frozen_files_preserved':True,'logical_database_binding_preserved':True,
        'raw_candle_validation':'PRODUCER_CONFIRMED_NINE_FIELDS_EXACT_UTC_BASE_VOLUME',
        'D':'PRODUCER_QC_ONLY_NO_ECONOMIC_READ','H':'NOT_ACQUIRED_SEALED_UNREAD','native_backtests':0,
        'prepare_command_sha256':sha(ROOT/'prepare-search-command-2.json'),'prepare_log_sha256':sha(ROOT/'prepare-search-command-2.log'),
        'preparation_invocations':2,'preparation_first_failure':'missing explicit frozen Development timerange; no output root or market request',
        'source_acquisition_invocations':1,'source_retried':False}
    (ROOT/'source-consumer-qc.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:result[k] for k in ['status','actual_http_requests','source','search_slices','source_provenance_sha256','source_receipt_sha256','D','H','native_backtests']}))

if __name__=='__main__':main()
