"""Third separately authorized synthetic run; reuse group 2, never market data."""
import hashlib, json, signal, socket, sys, time
from pathlib import Path
ROOT=Path(__file__).resolve().parent
NATIVE=Path('/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue-43-profile-driven-v1/freqtrade')
sys.path[:0]=[str(NATIVE),'/Users/shenjianpeng/.codex/worktrees/d699/freqtrade-lab']
signal.alarm(290)
calls=[]
def deny(*a,**k):
    calls.append('BLOCKED');raise RuntimeError('NETWORK_FORBIDDEN')
socket.create_connection=deny
socket.socket.connect=deny
socket.socket.connect_ex=deny
socket.getaddrinfo=deny
import pandas as pd
from freqtrade.enums import RunMode, TradingMode, MarginMode, CandleType
from freqtrade.exchange.binance import Binance
from freqtrade.optimize.backtesting import Backtesting
from lab.futures_costs import audit_native_trades
source=ROOT/'intrawEEK_stops'
out=ROOT/'benchmark-synthetic'
receipt=out/'native-attempt.json'
with receipt.open('x') as f: json.dump({'authorization':'root B+C delegation, third synthetic, maximum one','market':False},f)
cfg=json.loads((source/'config-synthetic.json').read_text())
cfg.update(strategy='NativeBuyAndHoldDiagnostic',strategy_path=str(out),datadir=out,user_data_dir=out,
           runmode=RunMode.BACKTEST,trading_mode=TradingMode.FUTURES,
           margin_mode=MarginMode.ISOLATED,candle_type_def=CandleType.FUTURES)
market=json.loads((source/'market-synthetic.json').read_text())
(out/'config-synthetic.json').write_text(json.dumps(cfg,default=str,indent=2))
ex=Binance(cfg,validate=False,load_leverage_tiers=False)
ex._api.set_markets([market],{});ex._api_async.set_markets([market],{})
ex._markets=ex._api.markets
pair=market['symbol']
ex._leverage_tiers={pair:[{'minNotional':0,'maxNotional':100000000,'maintenanceMarginRate':.005,'maxLeverage':1,'maintAmt':0}]}
bt=Backtesting(cfg,exchange=ex)
bt._set_strategy(bt.strategylist[0])
frame=pd.read_feather(source/'invented-1d.feather')
f=json.loads((source/'invented-mark-funding.json').read_text())
mark=pd.DataFrame({'date':[pd.Timestamp(r[0],unit='ms',tz='UTC') for r in f['marks']], 'open':[r[1] for r in f['marks']]})
fund=pd.DataFrame({'date':[pd.Timestamp(e['fundingTime'],unit='ms',tz='UTC') for e in f['events']], 'open':[e['fundingRate'] for e in f['events']]})
bt.futures_data={pair:ex.combine_funding_and_mark(fund,mark)}
bt.funding_fee_timeframe_secs=3600
start=time.monotonic()
result=bt.backtest(bt.strategy.advise_all_indicators({pair:frame.copy()}),
                  frame.iloc[14]['date'].to_pydatetime(),frame.iloc[-1]['date'].to_pydatetime())
trades=json.loads(result['results'].to_json(orient='records',date_format='iso'))
(out/'native-trades.json').write_text(json.dumps(trades,indent=2))
assert len(trades)==1
t=trades[0]
assert not t['is_short'] and t['leverage']==1 and 249.999<=t['stake_amount']<=250
assert t['open_date']=='2030-01-22T00:00:00.000Z'
assert t['close_date']=='2030-03-31T00:00:00.000Z' and t['exit_reason']=='force_exit'
assert t['stop_loss_abs']==0.0 and t['initial_stop_loss_abs']==0.0
assert bt.strategy.stoploss==-1.0
audit=audit_native_trades(trades,f['events'],f['marks'],symbol='XRPUSDT',
      start_ms=int(frame.iloc[14]['date'].timestamp()*1000),
      end_ms=int((frame.iloc[-1]['date']+pd.Timedelta(days=1)).timestamp()*1000),starting_balance=1000)
(out/'conservative-audit.json').write_text(json.dumps(audit,indent=2))
report={'status':'PASSED_SYNTHETIC_EXPRESSION_ONLY','native_runs':1,'total_authorized_synthetic_run_ordinal':3,
        'elapsed_seconds':time.monotonic()-start,'network_attempts':calls,'source_group':'intrawEEK_stops',
        'strategy_sha256':hashlib.sha256((out/'NativeBuyAndHoldDiagnostic.py').read_bytes()).hexdigest(),
        'native_trade_count':1,'entry':t['open_date'],'exit':t['close_date'],'stop_price':t['stop_loss_abs'],
        'liquidation_price':t.get('liquidation_price'),'no_liquidation_disabled':True,
        'entry_timing':'First scoring candle produces signal; next day open is first native execution slot.',
        'cash_executable':audit['cash_executable'],'no_market_data':True,'no_business_db':True}
assert not calls
(out/'receipt.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report,indent=2))
ex.close()
