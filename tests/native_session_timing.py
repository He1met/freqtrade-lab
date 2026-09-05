"""Isolated native Freqtrade timing probe with wholly synthetic OHLCV/mark/funding.

Run using the pinned native Python: native_session_timing.py ROOT R1.py R2.py.
This is a test harness, never a research runner or economic evidence.
"""
import json
import sys
from pathlib import Path

import pandas as pd
from freqtrade.commands.optimize_commands import setup_optimize_configuration
from freqtrade.data.history.datahandlers import get_datahandler
from freqtrade.enums import CandleType, RunMode
from freqtrade.exchange.okx import Okx
from freqtrade.optimize.backtesting import Backtesting

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lab.bounded_research import profile_search_config


def main():
    root = Path(sys.argv[1]); root.mkdir(parents=True, exist_ok=True)
    pair = 'LINK/USDT:USDT'
    dates = pd.date_range('2024-03-06T00:00Z', '2024-03-14T19:45Z', freq='5min')
    frame = pd.DataFrame({'date':dates, 'open':100., 'high':100.1, 'low':99.9, 'close':100., 'volume':10000.})
    local = frame.date.dt.tz_convert('America/New_York')
    # Morning zero on Tuesday, downward on Friday/Wednesday; weekends are nonzero.
    morning = (local.dt.hour == 9) & (local.dt.minute == 55)
    frame.loc[morning & (local.dt.dayofweek != 1), 'close'] = 101.
    frame.loc[morning & local.dt.dayofweek.isin([2,4]), 'close'] = 99.
    # R2 agrees on Friday/Mon/final Thu, disagrees Wednesday, flat on first Thu.
    recent = (local.dt.hour == 15) & (local.dt.minute == 25)
    frame.loc[recent & (local.dt.dayofweek != 4), 'close'] = 100.5
    frame.loc[recent & (local.dt.dayofweek == 4), 'close'] = 99.5
    frame.loc[recent & (local.dt.strftime('%Y-%m-%d') == '2024-03-07'), 'close'] = 100.
    frame['high'] = frame[['open','close','high']].max(axis=1)
    frame['low'] = frame[['open','close','low']].min(axis=1)
    # Wednesday short stop loss, without a new entry signal later that day.
    frame.loc[(local.dt.dayofweek == 2) & (local.dt.hour == 15) & (local.dt.minute == 40), 'high'] = 103.
    (root / 'data').mkdir()
    handler = get_datahandler(root / 'data', 'feather')
    handler.ohlcv_store(pair, '5m', frame, CandleType.FUTURES)
    mark = frame.iloc[::12].copy(); mark[['open','high','low','close']] = 100.
    handler.ohlcv_store(pair, '1h', mark, CandleType.MARK)
    funding = frame.iloc[::96].copy(); funding[['open','high','low','close','volume']] = 0.
    handler.ohlcv_store(pair, '1h', funding, CandleType.FUNDING_RATE)
    market = dict(id='LINK-USDT-SWAP', symbol=pair, base='LINK', quote='USDT', settle='USDT', baseId='LINK', quoteId='USDT', settleId='USDT', active=True, contract=True, swap=True, spot=False, future=False, option=False, linear=True, inverse=False, type='swap', contractSize=1., expiry=None, precision={'amount':.01,'price':.001}, limits={'amount':{'min':.01,'max':1000000},'price':{'min':.001,'max':None},'cost':{'min':1.,'max':None},'leverage':{'min':1.,'max':20.}}, maker=.0005, taker=.0005, info={})
    profile = dict(pairs=[pair], max_open_trades=1, stake_amount=250., starting_balance=1000., taker_fee_rate=.0005, timeframe='5m')
    reports = []
    for index, source_path in enumerate(map(Path,sys.argv[2:]),1):
        import ast
        name = next(node.name for node in ast.parse(source_path.read_text()).body if isinstance(node, ast.ClassDef))
        work = root / f'run-{index}'; work.mkdir()
        config_path=work/'config.json'; config_path.write_text(json.dumps(profile_search_config(profile)))
        user=work/'user';user.mkdir();export=work/'exports';export.mkdir()
        config=setup_optimize_configuration({'command':'backtesting','config':[str(config_path)],'datadir':str(root/'data'),'user_data_dir':str(user),'strategy_path':str(source_path.parent),'strategy':name,'timerange':'20240307-20240315','fee':.0005,'export':'trades','exportdirectory':str(export),'dataformat_ohlcv':'feather','disableparamexport':True,'backtest_cache':'none'},RunMode.BACKTEST)
        exchange=Okx(config,validate=False,load_leverage_tiers=False)
        def deny(*args,**kwargs): raise AssertionError('Synthetic timing probe attempted network access')
        exchange._api.fetch=deny
        exchange._api_async.fetch=deny
        exchange._api.set_markets([market],{});exchange._api_async.set_markets([market],{})
        exchange._markets=exchange._api.markets
        exchange._leverage_tiers={pair:[{'minNotional':0.,'maxNotional':1000000.,'maintenanceMarginRate':.005,'maxLeverage':20.,'maintAmt':0.}]}
        backtest=Backtesting(config,exchange=exchange)
        data, timerange=backtest.load_bt_data()
        strategy=backtest.strategylist[0]
        # Check indexes against literal clock dates, independent of formula construction.
        analyzed=strategy.advise_all_indicators({pair:frame.copy()})[pair]
        signals=strategy.advise_entry(analyzed.copy(), {'pair':pair})
        exits=strategy.advise_exit(analyzed.copy(), {'pair':pair})
        for row in signals[signals.get('enter_long',0).eq(1) | signals.get('enter_short',0).eq(1)].itertuples():
            clock=row.date.tz_convert('America/New_York')
            assert clock.weekday()<5 and (clock.hour,clock.minute)==(15,25)
        assert not ((signals.get('enter_long',0)==1)&(signals.get('enter_short',0)==1)).any()
        assert not (((signals.get('enter_long',0)==1)|(signals.get('enter_short',0)==1)) & ((exits.get('exit_long',0)==1)|(exits.get('exit_short',0)==1))).any()
        backtest.backtest_one_strategy(strategy,data,timerange)
        result=backtest.all_bt_content[name]['results']
        trades=[]
        for row in result.itertuples():
            opened=row.open_date.tz_convert('America/New_York');closed=row.close_date.tz_convert('America/New_York')
            assert opened.weekday()<5 and (opened.hour,opened.minute)==(15,30)
            assert row.leverage==1.
            assert row.fee_open==.0005 and row.fee_close==.0005
            if row.exit_reason=='exit_signal':
                assert (closed.hour,closed.minute)==(16,0) and row.trade_duration==30
            elif row.exit_reason=='stop_loss':
                assert opened.weekday()==2 and (closed.hour,closed.minute)==(15,40)
            else:
                assert row.exit_reason=='force_exit' and closed.date().isoformat()=='2024-03-14'
            trades.append({'open':row.open_date.isoformat(),'close':row.close_date.isoformat(),'short':row.is_short,'exit':row.exit_reason,'minutes':row.trade_duration})
        assert len({r['open'][:10] for r in trades})==len(trades)
        assert any(r['open'].endswith('20:30:00+00:00') for r in trades)
        assert any(r['open'].endswith('19:30:00+00:00') for r in trades)
        assert not any(r['open'].startswith('2024-03-12') for r in trades)
        assert len(trades)==(5 if index==1 else 3),trades
        assert any(r['short'] for r in trades) and any(not r['short'] for r in trades)
        reports.append({'strategy':name,'synthetic':True,'trades':trades})
        backtest.cleanup(); exchange.close()
    (root/'timing-evidence.json').write_text(json.dumps(reports,indent=2)+'\n')
    print(json.dumps({'status':'PASS','synthetic_only':True,'reports':reports}))


if __name__=='__main__': main()
