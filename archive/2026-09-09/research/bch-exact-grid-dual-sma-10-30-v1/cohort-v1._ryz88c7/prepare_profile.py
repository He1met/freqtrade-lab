import json, os
from pathlib import Path
from datetime import datetime, UTC
from lab.database import init_database, get_connection
from lab.bounded_research import profile_acquisition_contract

os.umask(0o077)
root=Path(__file__).resolve().parent
assert json.loads((root/'funding-precheck-terminal.json').read_text())['status']=='FUNDING_RAW_EXACT_GRID_PASS'
db=root/'lab.sqlite'
assert not db.exists()
profile_id='bch-exact-grid-dual-sma-10-30-v1'
profile={'id':profile_id,'name':'BCH_EXACT_GRID_DUAL_SMA_10_30_V1','domain':'OKX_CRYPTO_PERP','exchange':'okx','trading_mode':'futures','margin_mode':'isolated','pairs_json':json.dumps(['BCH/USDT:USDT']),'timeframe':'1d','detail_timeframe':None,'history_start_date':'2023-10-04','smoke_days':30,'holdout_days':180,'starting_balance':1000,'stake_amount':100,'max_open_trades':1,'taker_fee_rate':.0005,'stress_fee_multiplier':2,'max_drawdown_pct':15,'min_development_trades':5,'min_holdout_trades':4,'min_profit_factor':1.10,'is_default':1,'created_at':datetime.now(UTC).isoformat(),'updated_at':datetime.now(UTC).isoformat()}
gate={'name':'PROFILE_DRIVEN_ECONOMIC_GATE_V1','version':1,'minimum_net_profit_after_base_fees_pct':1.25,'minimum_average_holding_period_minutes':10080,'maximum_roi_exit_count':0}
window={'schema':'freqtrade-lab-profile-source-window-v1','data_start_utc':'2023-10-04T00:00:00Z','search_start_utc':'2024-02-01T00:00:00Z','development_start_utc':'2025-02-01T00:00:00Z','end_exclusive_utc':'2026-02-01T00:00:00Z'}
init_database(db)
with get_connection(db,must_exist=True) as con:
    con.execute('INSERT INTO research_profiles ('+','.join(profile)+') VALUES ('+','.join(':'+k for k in profile)+')',profile)
    assert len(con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall())==6
contract=profile_acquisition_contract(db,profile_id,'20240201-20250201','20250201-20260201',120,gate)
for name,data in [('profile.json',profile),('economic-gate.json',gate),('window-spec.json',window),('profile-acquisition-contract.json',contract)]:
    (root/name).write_text(json.dumps(data,indent=2)+'\n')
print(json.dumps({'database':str(db),'profile_id':profile_id,'tables':6,'contract':contract}))
