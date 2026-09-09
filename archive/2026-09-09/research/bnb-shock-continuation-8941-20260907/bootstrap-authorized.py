from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,os
from lab.database import init_database,get_connection
from lab.codex_generation import load_profile_snapshot
from lab.bounded_research import canonical,profile_search_contract
from lab.bounded_strategy import validate_bounded_causal_strategy_file
r=Path(__file__).parent
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
assert sha(r/'final-protocol.md')=='0bac2485cbe9265e6657891cd3e94f8330945d70964bced95524aed95d454bfb'
assert sha(r/'BnbDailyShockContinuation48H.py')=='d250751eb5314acb622266a6033e603da2c137b96592d7a16c7bd7498ddc4ba6'
assert sha(r/'synthetic-proof.json')=='2f2d49680da8ac631fd570c45a8cee94c4fdf1c7c58b687b7bdee7067e015ecf'
validate_bounded_causal_strategy_file(r/'BnbDailyShockContinuation48H.py','BnbDailyShockContinuation48H',expected_timeframe='1d')
def write(name,obj):
 with (r/name).open('xb') as f:f.write(canonical(obj))
now=datetime.now(timezone.utc).isoformat()
write('supervisor-authorization.json',{'authorized_by_thread':'01a05dcc-17fd-7972-9177-9fed95e4b07a',
 'recorded_at_utc':now,'protocol_sha256':sha(r/'final-protocol.md'),
 'strategy_sha256':sha(r/'BnbDailyShockContinuation48H.py'),
 'synthetic_receipt_sha256':sha(r/'synthetic-proof.json'),
 'lab_commit':'9218724a1465cf8ae517e15f59e28bd6674fa13c',
 'authorized':'New six-table Profile; one exact CODEX Generation/approval; one complete S+D capture and prepare; one S signal capacity prefilter after all data checks; native Search not authorized; no repeated permission needed',
 'S':['2023-11-06','2024-11-04'],'D_source_QC_only':['2024-11-04','2025-11-03'],
 'capture_window':['2023-10-02','2025-11-03'],'pre_roll':35,'capture_maximum':1,
 'capture_budget':{'CCXT_fetch':2000,'alarm_seconds':7200,'post_response_decoded_threshold':2147483648,
 'post_response_disk_threshold':5368709120,'may_overshoot_by_one_response':True,'wire_attempts':'UNKNOWN','automatic_retries':0},
 'Search_maximum':0,'Generation_maximum':1,'D_H_Stress_Release_trading_execution_budget':0,
 'failure':'Preserve original error; no source retry, window/gate changes or extra Candidate/native attempt'})
assert not (r/'lab.sqlite').exists()
init_database(r/'lab.sqlite')
profile={'id':'issue104-bnb-daily-shock-continuation-48h-v1','name':'Issue104 BNB daily shock continuation 48h',
 'domain':'BINANCE_CRYPTO_PERP','exchange':'binance','trading_mode':'futures','margin_mode':'isolated',
 'pairs_json':'["BNB/USDT:USDT"]','timeframe':'1d','detail_timeframe':None,'history_start_date':'2023-10-02',
 'smoke_days':7,'holdout_days':203,'starting_balance':1000.,'stake_amount':250.,'max_open_trades':1,
 'taker_fee_rate':.001,'stress_fee_multiplier':2.,'max_drawdown_pct':10.,'min_development_trades':24,
 'min_holdout_trades':14,'min_profit_factor':1.1,'is_default':1,'created_at':now,'updated_at':now}
with get_connection(r/'lab.sqlite') as conn:
 conn.execute('INSERT INTO research_profiles ('+','.join(profile)+') VALUES ('+','.join('?' for _ in profile)+')',tuple(profile.values()))
 snapshot=load_profile_snapshot(conn,profile['id'])
write('profile-snapshot.json',snapshot)
gate={'name':'PROFILE_DRIVEN_ECONOMIC_GATE_V1','version':1,'minimum_net_profit_after_base_fees_pct':1.,
 'minimum_average_holding_period_minutes':1440,'maximum_roi_exit_count':0}
baseline={'mode':'SINGLE_BASELINE_V1','version':1,'maximum_attempts':1,'maximum_rounds':1,
 'protocol_sha256':sha(r/'final-protocol.md'),'strategy_sha256':sha(r/'BnbDailyShockContinuation48H.py')}
write('economic-gate.json',gate);write('single-baseline.json',baseline)
write('window.json',{'schema':'freqtrade-lab-profile-source-window-v1','data_start_utc':'2023-10-02T00:00:00Z',
 'search_start_utc':'2023-11-06T00:00:00Z','development_start_utc':'2024-11-04T00:00:00Z','end_exclusive_utc':'2025-11-03T00:00:00Z'})
write('profile-contract.json',profile_search_contract(snapshot,'20231106-20241104','20241104-20251103',35,gate,single_baseline=baseline))
for name in ['console-runtime','releases','artifacts']: (r/name).mkdir(mode=0o700)
print(json.dumps({'profile_id':profile['id'],'profile_sha256':sha(r/'profile-snapshot.json'),'contract_sha256':sha(r/'profile-contract.json'),'market_requests':0}))
