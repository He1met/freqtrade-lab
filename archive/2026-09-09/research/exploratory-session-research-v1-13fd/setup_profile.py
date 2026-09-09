from pathlib import Path
import hashlib,json,sys
sys.path.insert(0,'/Users/shenjianpeng/.codex/worktrees/13fd/freqtrade-lab')
from lab.database import init_database,get_connection
from lab.bounded_research import canonical,EXPLORATORY_PROTOCOL,PROFILE_ECONOMIC_GATE
r=Path(__file__).resolve().parent
exploration={'protocol':EXPLORATORY_PROTOCOL,'status':'NOT_INDEPENDENTLY_VALIDATED','exposure_audit_sha256':hashlib.sha256((r/'exposure-audit.json').read_bytes()).hexdigest(),'prior_research':['global-ledger-77-lines-8caba129','fixed-session-decision-2cf6-27407682','Issue49-consumed-Dev','Issue52-consumed-Dev']}
(r/'exploration-contract.json').write_bytes(canonical(exploration))
window={'schema':'freqtrade-lab-exploratory-source-window-v1','data_start_utc':'2024-01-31T18:00:00Z','search_start_utc':'2024-02-01T00:00:00Z','development_start_utc':'2024-08-01T00:00:00Z','end_exclusive_utc':'2024-08-01T00:00:00Z','exploration':exploration}
(r/'window-spec.json').write_bytes(canonical(window))
gate={'name':PROFILE_ECONOMIC_GATE,'version':1,'minimum_net_profit_after_base_fees_pct':1.25,'minimum_average_holding_period_minutes':0.,'maximum_roi_exit_count':0}
(r/'economic-gate.json').write_bytes(canonical(gate))
db=r/'research.sqlite';assert not db.exists();init_database(db)
profile={'id':'exploratory-session-link-v1','name':'LINK NY session exploratory V1','domain':'OKX_CRYPTO_PERP','exchange':'okx','trading_mode':'futures','margin_mode':'isolated','pairs_json':'["LINK/USDT:USDT"]','timeframe':'5m','detail_timeframe':None,'history_start_date':'2024-01-31','smoke_days':1,'holdout_days':1,'starting_balance':2000.,'stake_amount':500.,'max_open_trades':1,'taker_fee_rate':.0005,'stress_fee_multiplier':2.,'max_drawdown_pct':15.,'min_development_trades':50,'min_holdout_trades':50,'min_profit_factor':1.1,'is_default':1,'created_at':'2026-09-05T01:00:00Z','updated_at':'2026-09-05T01:00:00Z'}
with get_connection(db) as con:con.execute('INSERT INTO research_profiles ('+','.join(profile)+') VALUES ('+','.join('?' for _ in profile)+')',tuple(profile.values()));con.commit()
(r/'profile.json').write_bytes(canonical(profile))
for name in ('console-runtime','unused-validation-root'):(r/name).mkdir(mode=0o700)
print(db)
