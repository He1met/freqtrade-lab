import json
import sys
from pathlib import Path
sys.path.insert(0,'/Users/shenjianpeng/.codex/worktrees/3f31/freqtrade-lab')
from lab.database import init_database,get_connection
from lab.binance_source import compile_source
from lab.bounded_research import profile_acquisition_contract,prepare_search_data

root=Path(__file__).resolve().parent
db=root/'engineering-sanitized-source.sqlite'
init_database(db)
with get_connection(db) as c:
    c.execute("""INSERT INTO research_profiles
    (id,name,domain,exchange,trading_mode,margin_mode,pairs_json,timeframe,history_start_date,smoke_days,holdout_days,starting_balance,stake_amount,max_open_trades,taker_fee_rate,stress_fee_multiplier,max_drawdown_pct,min_development_trades,min_holdout_trades,min_profit_factor,created_at,updated_at)
    VALUES ('engineering-binance','Technical engineering fixture','BINANCE_CRYPTO_PERP','binance','futures','isolated','["BCH/USDT:USDT"]','1d','2023-10-23',7,7,1000,100,1,0.0005,2,20,0,0,1,'2026-09-07T00:00:00Z','2026-09-07T00:00:00Z')""")
contract=profile_acquisition_contract(db,'engineering-binance','20231106-20231113','20231113-20231120',14)
result=compile_source(root/'engineering-source',root/'native-full-s-http-receipts.jsonl',root/'native-full-s-raw',contract)
print('source',result)
print(prepare_search_data(root/'engineering-source',root/'engineering-search',result['provenance_sha256'],result['retrieval_receipt_sha256'],database_path=db,profile_id='engineering-binance',search_timerange='20231106-20231113',development_timerange='20231113-20231120',pre_roll_candles=14))
