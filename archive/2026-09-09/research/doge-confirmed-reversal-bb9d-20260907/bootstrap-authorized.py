from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,os
from lab.database import init_database,get_connection
from lab.codex_generation import load_profile_snapshot
from lab.bounded_research import canonical,profile_search_contract
from lab.bounded_strategy import validate_bounded_causal_strategy_file
r=Path(__file__).parent
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
assert sha(r/'final-protocol.md')=='e0920ce3dfe27bdc7dff18828ed0676c6f3cbefa4eb160e33f5dcf5585ee9127'
assert sha(r/'DogeConfirmedShockReversal3D-v2.py')=='61488a724e54fca3dfe11a47294c3a3a02077090cb38baaef5385d16ef43d05f'
assert sha(r/'synthetic-equivalence.json')=='b848470c9fdccfae4feaf0baa9c29238649445e17a2b40e97479b29f0a858752'
validate_bounded_causal_strategy_file(r/'DogeConfirmedShockReversal3D-v2.py','DogeConfirmedShockReversal3D',expected_timeframe='1d')
def write(name,obj):
 with (r/name).open('xb') as f:f.write(canonical(obj))
now=datetime.now(timezone.utc).isoformat()
write('supervisor-authorization.json',{'authorized_by_thread':'01a05dcc-17fd-7972-9177-9fed95e4b07a',
 'recorded_at_utc':now,'protocol_sha256':sha(r/'final-protocol.md'),
 'strategy_sha256':sha(r/'DogeConfirmedShockReversal3D-v2.py'),
 'synthetic_receipt_sha256':sha(r/'synthetic-equivalence.json'),
 'lab_commit':'df3dc41dba4ccba6dba84031de7e2568f7e63399',
 'authorized':'New six-table Profile; one exact CODEX Generation/approval; one complete S+D capture and prepare; one Search after all data checks; no repeated permission needed',
 'S':['2023-11-06','2024-11-04'],'D_source_QC_only':['2024-11-04','2025-11-03'],
 'capture_window':['2023-09-30','2025-11-03'],'pre_roll':37,'capture_maximum':1,
 'capture_budget':{'CCXT_fetch':2000,'alarm_seconds':7200,'post_response_decoded_threshold':2147483648,
 'post_response_disk_threshold':5368709120,'may_overshoot_by_one_response':True,'wire_attempts':'UNKNOWN','automatic_retries':0},
 'Search_maximum':1,'Generation_maximum':1,'D_H_Stress_Release_trading_execution_budget':0,
 'failure':'Preserve original error; no source retry, window/gate changes or extra Candidate/native attempt'})
assert not (r/'lab.sqlite').exists()
init_database(r/'lab.sqlite')
profile={'id':'issue98-doge-confirmed-reversal-v1','name':'Issue98 DOGE confirmed shock reversal 3D',
 'domain':'BINANCE_CRYPTO_PERP','exchange':'binance','trading_mode':'futures','margin_mode':'isolated',
 'pairs_json':'["DOGE/USDT:USDT"]','timeframe':'1d','detail_timeframe':None,'history_start_date':'2023-09-30',
 'smoke_days':7,'holdout_days':203,'starting_balance':1000.,'stake_amount':250.,'max_open_trades':1,
 'taker_fee_rate':.001,'stress_fee_multiplier':2.,'max_drawdown_pct':10.,'min_development_trades':18,
 'min_holdout_trades':10,'min_profit_factor':1.1,'is_default':1,'created_at':now,'updated_at':now}
with get_connection(r/'lab.sqlite') as conn:
 conn.execute('INSERT INTO research_profiles ('+','.join(profile)+') VALUES ('+','.join('?' for _ in profile)+')',tuple(profile.values()))
 snapshot=load_profile_snapshot(conn,profile['id'])
write('profile-snapshot.json',snapshot)
gate={'name':'PROFILE_DRIVEN_ECONOMIC_GATE_V1','version':1,'minimum_net_profit_after_base_fees_pct':1.,
 'minimum_average_holding_period_minutes':1440,'maximum_roi_exit_count':0}
baseline={'mode':'SINGLE_BASELINE_V1','version':1,'maximum_attempts':1,'maximum_rounds':1,
 'protocol_sha256':sha(r/'final-protocol.md'),'strategy_sha256':sha(r/'DogeConfirmedShockReversal3D-v2.py')}
write('economic-gate.json',gate);write('single-baseline.json',baseline)
write('window.json',{'schema':'freqtrade-lab-profile-source-window-v1','data_start_utc':'2023-09-30T00:00:00Z',
 'search_start_utc':'2023-11-06T00:00:00Z','development_start_utc':'2024-11-04T00:00:00Z','end_exclusive_utc':'2025-11-03T00:00:00Z'})
write('profile-contract.json',profile_search_contract(snapshot,'20231106-20241104','20241104-20251103',37,gate,single_baseline=baseline))
for name in ['console-runtime','releases','artifacts']: (r/name).mkdir(mode=0o700)
print(json.dumps({'profile_id':profile['id'],'profile_sha256':sha(r/'profile-snapshot.json'),'contract_sha256':sha(r/'profile-contract.json'),'market_requests':0}))
