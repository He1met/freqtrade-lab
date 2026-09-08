#!/usr/bin/env python3
"""Existing-order reconstruction and official export; never a new signal backtest."""
import argparse
from datetime import datetime, timezone
from decimal import Decimal as D
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time

REPO = Path(__file__).resolve().parents[1]
SOURCE = Path('/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue-43-profile-driven-v1/freqtrade')
ROOT = Path('/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue157-native-display-v1')
sys.path[:0] = [str(REPO), str(SOURCE)]
from scripts.issue147_diagnostic import deadline, sha, write


def deny_network(event, args):
    if event in ('socket.connect', 'socket.getaddrinfo', 'socket.bind'):
        raise ValueError('offline reconstruction only')


def markets_from_metadata(data):
    markets = []
    for m in data['symbols']:
        f = {x['filterType']: x for x in m['filters']}
        lot, ml, price = f['LOT_SIZE'], f['MARKET_LOT_SIZE'], f['PRICE_FILTER']
        markets.append(dict(id=m['symbol'], symbol=m['baseAsset']+'/USDT', base=m['baseAsset'], quote='USDT',
            baseId=m['baseAsset'], quoteId='USDT', active=True, spot=True, contract=False, swap=False,
            future=False, option=False, type='spot', contractSize=1.,
            precision={'amount':float(max(D(lot['stepSize']), D(ml['stepSize']))), 'price':float(price['tickSize'])},
            limits={'amount':{'min':float(max(D(lot['minQty']), D(ml['minQty']))), 'max':float(min(D(lot['maxQty']), D(ml['maxQty'])))},
                    'price':{'min':float(price['minPrice']), 'max':float(price['maxPrice'])},
                    'cost':{'min':float(f['NOTIONAL']['minNotional']), 'max':float(f['NOTIONAL']['maxNotional'])},
                    'leverage':{'min':1,'max':1}}, maker=.001, taker=.001, info={}))
    return markets


def load_bound_prices(sources):
    import pandas as pd
    frames, allowed = {}, {}
    for source in sources:
        if sha(source['path']) != source['sha256']:
            raise ValueError('source hash drift')
        if source['request'].get('interval') != '1h':
            continue
        pair = source['request']['symbol'][:-4]+'/USDT'
        values = frames.setdefault(pair, {})
        for row in json.loads(Path(source['path']).read_text()):
            h = row[0]//3600000
            if not 447072 <= h < 464592:
                continue
            if row[0]%3600000 or h in values:
                raise ValueError('duplicate/time boundary')
            values[h] = [pd.Timestamp(row[0], unit='ms', tz='UTC'), *map(float, row[1:6])]
            if row[6] == row[0]+3599999:
                allowed[pair, h] = D(row[1])
    return {p:pd.DataFrame([v for _,v in sorted(xs.items())], columns=['date','open','high','low','close','volume']) for p,xs in frames.items()}, allowed


def replay(engine, rows, allowed):
    from lab.spot139_native_v3 import execute_order
    from freqtrade.persistence import LocalTrade
    compared = []
    for r in rows:
        fill = dict(symbol=r['symbol'], hour=r['hour'], side=r['side'], quantity=D(r['gross_amount']),
                    price=D(r['price']), fee_base=D(r.get('reference_fee_base','0')), fee_quote=D(r.get('reference_fee_quote','0')))
        out = execute_order(engine, fill, allowed)
        for key in ('gross_amount','price','native_order_cost','native_trade_amount','native_cash','native_realized','native_entry_price','native_orders'):
            if D(str(out[key])) != D(str(r[key])):
                raise ValueError('native record mismatch: '+key)
        compared.append(out)
    return compared, [t.to_json() for t in LocalTrade.bt_trades_open]


def official_export(engine, frames, exportdir, name, run_id, started):
    """Explicit standard terminal force exits, separate from preserved B results."""
    import pandas as pd
    from freqtrade.optimize.backtesting import Backtesting
    from freqtrade.persistence import LocalTrade, PairLocks
    from freqtrade.data.btanalysis import trade_list_to_dataframe
    from freqtrade.optimize.optimize_reports import generate_backtest_stats, store_backtest_results
    terminal = {}
    for pair, frame in frames.items():
        bar = frame.iloc[-1]
        terminal[pair] = [[bar['date'],bar['open'],bar['high'],bar['low'],bar['close'],0,0,0,0,'','']]
    before = sum(len(t.orders) for t in LocalTrade.bt_trades_open)
    before_cash = engine.wallets.get_free('USDT')
    before_mark = before_cash + sum(t.amount*float(frames[t.pair].iloc[-1]['open']) for t in LocalTrade.bt_trades_open)
    Backtesting.handle_left_open(engine, LocalTrade.bt_trades_open_pp, terminal)
    engine.wallets.update()
    trades = list(LocalTrade.bt_trades)
    content = dict(results=trade_list_to_dataframe(trades), config=engine.strategy.config,
        locks=PairLocks.get_all_locks(), rejected_signals=engine.rejected_trades,
        timedout_entry_orders=engine.timedout_entry_orders, timedout_exit_orders=engine.timedout_exit_orders,
        canceled_trade_entries=engine.canceled_trade_entries, canceled_entry_orders=engine.canceled_entry_orders,
        replaced_entry_orders=engine.replaced_entry_orders, final_balance=engine.wallets.get_total('USDT'),
        run_id=run_id, backtest_start_time=int(started), backtest_end_time=int(time.time()))
    # Market context is computed by the official function from original, unfilled rows.
    start = min(f['date'].min() for f in frames.values()).to_pydatetime()
    end = max(f['date'].max() for f in frames.values()).to_pydatetime()
    note = ('DISPLAY ONLY: archived native order reconstruction, NOT signal backtest. '
            'Official terminal force_exit added for residual positions; not executable dust liquidation. '
            'Native quote-fee statistics differ from B base-fee model; trade-close DD is not wallet DD. '
            'No independent or risk qualification.')
    stats = generate_backtest_stats(frames, {name:content}, start, end, notes=note)
    config = dict(engine.strategy.config, exportdirectory=exportdir,
                  original_config=dict(engine.strategy.config))
    path = store_backtest_results(config, stats, datetime.now(timezone.utc).strftime('%Y-%m-%d_%H-%M-%S'))
    return dict(zip_path=str(path), zip_sha256=sha(path), terminal_extra_orders=sum(len(t.orders) for t in trades)-before,
                native_trades=len(trades), synthetic_terminal_impact=dict(before_cash=before_cash, before_native_mark_equity=before_mark, after_native_balance=content['final_balance'], change=content['final_balance']-before_mark), official_summary={k:stats['strategy'][name][k] for k in ['profit_total','profit_total_abs','final_balance','max_drawdown_account']},
                note=note)


def check(manifest, digest):
    if sha(manifest) != digest:
        raise ValueError('manifest SHA')
    m = json.loads(Path(manifest).read_text())
    if m['root'] != str(ROOT) or m['budget'] != {'costs':['base','stress'],'calls':2,'seconds_each':180,'retries':0,'market_gets':0}:
        raise ValueError('scope/budget')
    for path, expected in m['bindings'].items():
        if sha(path) != expected:
            raise ValueError('binding drift: '+path)
    return m


def execute(m, digest, cost, grant, grant_sha):
    if sha(grant) != grant_sha:
        raise ValueError('grant SHA')
    g = json.loads(Path(grant).read_text())
    if g != dict(manifest_sha256=digest, costs=['base','stress'], calls=2, terminal_mode='OFFICIAL_FORCE_EXIT_DISPLAY_ONLY'):
        raise ValueError('execution grant mismatch')
    ROOT.mkdir(exist_ok=True)
    r = ROOT/cost; r.mkdir()  # Exactly one attempt for each cost; no old runner/root involved.
    write(r/'attempt.json', dict(manifest_sha256=digest, grant_sha256=grant_sha, cost=cost, seconds=180, at=time.time()))
    engine = exchange = None
    started = time.time()
    try:
        with deadline(180):
            sys.addaudithook(deny_network)
            from lab.spot139_native_bridge import make_engine
            source = m['results'][cost]
            if sha(source['path']) != source['sha256']:
                raise ValueError('result hash drift')
            old = json.loads(Path(source['path']).read_text())
            frames, allowed = load_bound_prices(m['sources'])
            metadata = json.loads(Path(m['sources'][0]['path']).read_text())
            with tempfile.TemporaryDirectory(prefix='issue157-native-') as temp:
                engine, exchange = make_engine(temp, markets_from_metadata(metadata), D('.001' if cost=='base' else '.002'))
                compared, positions = replay(engine, old['native_orders'], allowed)
                write(r/'reconstructed-before-terminal.json', dict(orders=compared, open_trades=positions, original_model_terminal=old['modeled_terminal'], original_result_sha256=source['sha256']))
                if str(engine.wallets.get_free('USDT')) != old['native_cash']:
                    raise ValueError('final native cash mismatch')
                exportdir=r/'export'; exportdir.mkdir()
                result = official_export(engine, frames, exportdir, 'B_V3_DISPLAY_REPLAY_'+cost.upper()+'_SYNTHETIC_FORCE_EXIT', digest+'-'+cost, started)
                write(r/'terminal.json', dict(status='DISPLAY_EXPORT_ONLY', **result, cost=cost, matched_orders=len(compared), elapsed_seconds=time.time()-started))
    except BaseException as e:
        write(r/'failure.json', dict(status='FAILED_NO_RETRY', error=type(e).__name__+': '+str(e)))
        raise
    finally:
        if engine is not None: engine.cleanup()
        if exchange is not None: exchange.close()


def main():
    p=argparse.ArgumentParser(); p.add_argument('command', choices=['check','execute'])
    p.add_argument('--manifest',required=True);p.add_argument('--sha256',required=True)
    p.add_argument('--cost',choices=['base','stress']);p.add_argument('--grant');p.add_argument('--grant-sha256')
    a=p.parse_args();m=check(a.manifest,a.sha256)
    if a.command=='check':print('CONTROL_PASS_NO_NATIVE_EXECUTION')
    else:execute(m,a.sha256,a.cost,a.grant,a.grant_sha256)

if __name__=='__main__':main()
