"""Native experiment adapter and fill-based MTM audit, not a second matcher."""
from datetime import timedelta
from pathlib import Path
import hashlib
import json
import math
import os
import subprocess
import sys

SOURCE = Path('/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue-43-profile-driven-v1/freqtrade')
NATIVE_COMMIT = '52bc96f4480b1a0da6a9b455bd00b17fbb6786a5'
REPO = Path(__file__).resolve().parents[1]
PROTOCOL = REPO/'docs/protocols/perp-first-experiment-v1.json'
PAIRS = ('BTC/USDT:USDT', 'ETH/USDT:USDT')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    path=Path(path);temporary=path.with_name(path.name+'.pending')
    with temporary.open('w') as stream:
        stream.write(json.dumps(value, indent=2, ensure_ascii=False, default=str, allow_nan=False)+'\n')
        stream.flush();os.fsync(stream.fileno())
    os.replace(temporary,path)


def native_environment():
    import importlib.metadata
    expected = {'freqtrade':'2026.7','ccxt':'4.5.68','pandas':'3.0.3','pyarrow':'25.0.0'}
    actual = {p:importlib.metadata.version(p) for p in expected}
    commit = subprocess.check_output(['git','-C',str(SOURCE),'rev-parse','HEAD'], text=True).strip()
    dirty = subprocess.check_output(['git','-C',str(SOURCE),'status','--porcelain'], text=True).strip()
    if actual != expected or commit != NATIVE_COMMIT or dirty:
        raise ValueError('pinned native dependencies/source mismatch')
    sys.path.insert(0, str(SOURCE))
    import freqtrade
    if Path(freqtrade.__file__).resolve() != (SOURCE/'freqtrade/__init__.py').resolve():
        raise ValueError('wrong Freqtrade source')
    return dict(python=sys.version.split()[0], interpreter=sys.executable, packages=actual, source_commit=commit)


def load_source(root):
    import pandas as pd
    root = Path(root)
    receipt = json.loads((root/'receipt.json').read_text())
    protocol = json.loads(PROTOCOL.read_text())
    expected = pd.date_range(protocol['source_start'], protocol['score_end_exclusive'], freq='1h', inclusive='left')
    frames, marks, events, binding = {}, {}, {}, {}
    for pair in PAIRS:
        symbol = pair.split('/')[0]+'USDT'
        for kind in ('ohlcv','mark','funding'):
            name = f'{symbol}-{kind}'
            item = receipt['datasets'][name]
            path = root/item['path']
            if sha(path) != item['sha256']:
                raise ValueError('source SHA mismatch: '+name)
            binding[name] = dict(path=str(path), sha256=sha(path), rows=item['rows'])
            rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
            if len(rows) != item['rows']:
                raise ValueError('source row count changed')
            if kind == 'funding':
                values = pd.DataFrame([dict(date=r['event_time'], open_fund=float(r['rate']),
                                           open_mark=float(r['mark_price'])) for r in rows])
                values['date'] = pd.to_datetime(values.date, utc=True, format='mixed')
                if values.empty or values.date.duplicated().any() or not values.date.is_monotonic_increasing:
                    raise ValueError('empty/duplicate/disordered funding')
                if not all(math.isfinite(x) for x in values.open_fund) or not all(x > 0 for x in values.open_mark):
                    raise ValueError('invalid actual funding/settlement mark')
                # Observed BTC/ETH schedule for this frozen batch, not a universal
                # 8h assumption. Require one raw event in each observed UTC slot;
                # preserve exact milliseconds for accounting, including changes.
                slots = values.date.dt.floor('8h')
                expected_slots = pd.date_range(expected[0], expected[-1], freq='8h')
                if not pd.DatetimeIndex(slots).equals(expected_slots):
                    raise ValueError('funding coverage not complete for observed batch schedule')
                events[pair] = values
            else:
                # Mark candles have no traded-volume meaning. Native requires a
                # numeric placeholder but the strategy never consumes mark volume.
                values = pd.DataFrame([dict(date=r['event_time'], **{c:float(r[c]) for c in ('open','high','low','close')},
                    volume=0. if kind=='mark' else float(r['volume'])) for r in rows])
                values['date'] = pd.to_datetime(values.date, utc=True)
                if not pd.DatetimeIndex(values.date).equals(expected):
                    raise ValueError('hourly price/mark gap; native filling prohibited')
                if not all(math.isfinite(x) and x > 0 for c in ('open','high','low','close') for x in values[c]):
                    raise ValueError('invalid price or mark')
                (frames if kind == 'ohlcv' else marks)[pair] = values
    metadata = json.loads((root/'instrument-rules.json').read_text())['symbols']
    binding['instrument_rules'] = dict(path=str(root/'instrument-rules.json'), sha256=sha(root/'instrument-rules.json'))
    return frames, marks, events, metadata, binding


def assembly(metadata):
    markets, tiers = [], {}
    for info in metadata:
        if info['symbol'] not in ('BTCUSDT','ETHUSDT'):
            continue
        base = info['baseAsset']; pair = base+'/USDT:USDT'
        filters = {r['filterType']:r for r in info['filters']}
        lot = filters['MARKET_LOT_SIZE']; price = filters['PRICE_FILTER']
        step = float(lot['stepSize']) or float(filters['LOT_SIZE']['stepSize'])
        markets.append(dict(id=info['symbol'],symbol=pair,base=base,quote='USDT',settle='USDT',
            baseId=base,quoteId='USDT',settleId='USDT',active=True,contract=True,swap=True,
            spot=False,future=False,option=False,linear=True,inverse=False,type='swap',contractSize=1.,expiry=None,
            precision={'amount':step,'price':float(price['tickSize'])},
            limits={'amount':{'min':float(lot['minQty']),'max':float(lot['maxQty'])},
                    'price':{'min':float(price['minPrice']),'max':float(price['maxPrice'])},
                    'cost':{'min':float(filters['MIN_NOTIONAL']['notional']),'max':None},
                    'leverage':{'min':1.,'max':1.}},maker=.0006,taker=.0006,info={}))
        # Unauthenticated historical tier data unavailable. An explicit engine
        # assumption is necessary even at 1x; liquidation must be reported.
        tiers[pair] = [dict(minNotional=0.,maxNotional=1000000.,maintenanceMarginRate=.025,maxLeverage=1.,maintAmt=0.)]
    if {r['symbol'] for r in markets} != set(PAIRS):
        raise ValueError('wrong market specification scope')
    return markets, tiers


def native_config(variant, multiplier):
    return dict(max_open_trades=2,stake_currency='USDT',stake_amount='unlimited',
        tradable_balance_ratio=1.,fiat_display_currency='USD',dry_run=True,dry_run_wallet=1000.,
        cancel_open_orders_on_exit=False,trading_mode='futures',margin_mode='isolated',
        timeframe='1h',fee=.0008,unfilledtimeout={'entry':10,'exit':30,'exit_timeout_count':0,'unit':'minutes'},
        entry_pricing={'price_side':'other','use_order_book':True,'order_book_top':1},
        exit_pricing={'price_side':'other','use_order_book':True,'order_book_top':1},
        exchange={'name':'binance','enable_ws':False,'pair_whitelist':list(PAIRS),'pair_blacklist':[]},
        pairlists=[{'method':'StaticPairList'}],strategy='PerpBaseline',dataformat_ohlcv='feather',
        disableparamexport=True,backtest_cache='none',
        order_types={'entry':'market','exit':'market','stoploss':'market','stoploss_on_exchange':False},
        perp_variant=variant,perp_fixed_multiplier=multiplier)


def run_native(root, frames, events, metadata, variant, multiplier, start, end):
    """Retain native matching, precision, stops, orders, exports and shared wallet."""
    import pandas as pd
    from freqtrade.commands.optimize_commands import setup_optimize_configuration
    from freqtrade.enums import RunMode, CandleType
    from freqtrade.exchange.binance import Binance
    from freqtrade.optimize.backtesting import Backtesting
    from freqtrade.data.history.datahandlers import get_datahandler
    from lab.portfolio_native_export import read_strategy_export
    root = Path(root)
    for name in ('user','exports','data'):
        (root/name).mkdir(parents=True)
    handler = get_datahandler(root/'data','feather')
    for pair, frame in frames.items():
        handler.ohlcv_store(pair,'1h',frame,CandleType.FUTURES)
    config_path = root/'config.json'; write(config_path,native_config(variant,multiplier))
    config = setup_optimize_configuration(dict(command='backtesting',config=[str(config_path)],
        datadir=str(root/'data'),user_data_dir=str(root/'user'),strategy_path=str(REPO/'lab'),
        strategy='PerpBaseline',timerange=f'{int(start.timestamp())}-{int(end.timestamp())}',fee=.0008,
        export='trades',exportdirectory=str(root/'exports'),dataformat_ohlcv='feather',
        disableparamexport=True,backtest_cache='none'),RunMode.BACKTEST)

    class EventBacktesting(Backtesting):
        def _load_bt_data_detail(self):
            if self.timeframe_detail:
                raise ValueError('intrahour extension outside first batch')
            self.detail_data = {}; self.futures_data = events
            self.funding_fee_timeframe_secs = 3600

    class EventBinance(Binance):
        def calculate_funding_fees(self, df, amount, is_short, open_date, close_date):
            # Preserve actual ms; same-timestamp event precedes entry/exit fills.
            # Native default includes opening boundary; filtering makes strictly
            # after entry and inclusive close without replacing native formula.
            return super().calculate_funding_fees(df.loc[df.date > pd.Timestamp(open_date)],
                amount=amount,is_short=is_short,open_date=open_date,close_date=close_date)

    exchange = EventBinance(config,validate=False,load_leverage_tiers=False)
    def deny(*args,**kwargs):
        raise RuntimeError('offline native exchange request prohibited')
    exchange._api.fetch=deny; exchange._api_async.fetch=deny
    markets,tiers=assembly(metadata)
    exchange._api.set_markets(markets,{});exchange._api_async.set_markets(markets,{})
    exchange._markets=exchange._api.markets;exchange._leverage_tiers=tiers
    engine=None
    try:
        engine=EventBacktesting(config,exchange=exchange)
        if len(engine.strategylist)!=1 or set(engine.pairlists.whitelist)!=set(PAIRS):
            raise ValueError('native account/pair scope differs')
        engine.start()
        archives=list((root/'exports').glob('*.zip'))
        if len(archives)!=1:
            raise ValueError('expected one retained native artifact')
        result=read_strategy_export(archives[0],'PerpBaseline')
        write(root/'native-result.json',result)
        write(root/'entry-audit.json',engine.strategylist[0].entry_audit)
        return result, {p.name:sha(p) for p in archives}
    finally:
        if engine is not None:
            engine.cleanup()
        exchange.close()


def audit_native(result, marks, events, start, end):
    """Reconstruct actual native fills and settlement cash flows at hourly marks."""
    import pandas as pd
    import numpy as np
    trades=result['trades']; fills=[]; expected_funding=0.; native_funding=0.
    for trade in trades:
        if trade['leverage'] != 1 or trade['fee_open'] != .0008 or trade['fee_close'] != .0008:
            raise ValueError('native leverage/fee differs')
        opened=pd.to_datetime(trade['open_timestamp'],unit='ms',utc=True)
        closed=pd.to_datetime(trade['close_timestamp'],unit='ms',utc=True)
        event=events[trade['pair']]
        funded=event.loc[(event.date>opened)&(event.date<=closed)]
        expected_funding+=float((funded.open_fund*funded.open_mark*trade['amount']).sum())*(1 if trade['is_short'] else -1)
        native_funding+=trade['funding_fees']
        for order in trade['orders']:
            if not order.get('order_filled_timestamp'):
                continue
            fills.append(dict(pair=trade['pair'],side=order['ft_order_side'],
                amount=order['amount'],price=order['safe_price'],
                at=pd.to_datetime(order['order_filled_timestamp'],unit='ms',utc=True),
                is_entry=order['ft_is_entry']))
    if abs(expected_funding-native_funding)>1e-7:
        raise ValueError(f'native funding differs from raw settlement by {native_funding-expected_funding}')
    timeline=[]
    for f in fills:
        timeline.append((f['at'],1,'fill',f))
    for pair,frame in events.items():
        for e in frame.itertuples():
            if start<=e.date<=end:
                timeline.append((e.date,0,'funding',(pair,e.open_fund,e.open_mark)))
    mark_map={p:dict(zip(f.date+timedelta(hours=1),f.close)) for p,f in marks.items()}
    for at in pd.date_range(start,end,freq='1h'):
        if all(at in mark_map[p] for p in PAIRS):
            timeline.append((at,2,'mark',None))
    timeline.sort(key=lambda x:(x[0],x[1]))
    cash=1000.; inventory={p:0. for p in PAIRS}; cost=0.; funding=0.; peak=1000.; rows=[]; turnover=0.
    # At each hour snapshot after fills uses the prior close mark. Both have
    # observed timestamps; 1h intrabar MTM risk still remains unknown.
    for at,_,kind,value in timeline:
        if kind=='fill':
            signed=value['amount']*(1 if value['side']=='buy' else -1)
            fee=value['amount']*value['price']*.0008
            cash-=signed*value['price']+fee
            inventory[value['pair']]+=signed
            cost+=fee; turnover+=value['amount']*value['price']
        elif kind=='funding':
            pair,rate,mark=value; flow=-inventory[pair]*rate*mark
            cash+=flow;funding+=flow
        else:
            eq=cash+sum(inventory[p]*mark_map[p][at] for p in PAIRS)
            peak=max(peak,eq)
            rows.append(dict(at=at.isoformat(),equity=eq,drawdown=1-eq/peak,
                gross_exposure=sum(abs(inventory[p])*mark_map[p][at] for p in PAIRS),
                signed_exposure=sum(inventory[p]*mark_map[p][at] for p in PAIRS),
                funding=funding,cost=cost,turnover=turnover))
    if any(abs(q)>1e-9 for q in inventory.values()):
        raise ValueError('native final inventory not flat')
    native_profit=sum(t['profit_abs'] for t in trades)
    if abs(cash-1000-native_profit)>1e-6 or abs(funding-native_funding)>1e-7:
        raise ValueError('native wallet/fill/funding reconciliation failed')
    eq=pd.DataFrame(rows); eq['at']=pd.to_datetime(eq['at'],utc=True); eq=eq.set_index('at')
    monthly=eq.equity.resample('ME').last()
    monthly_return=monthly.pct_change(); monthly_return.iloc[0]=monthly.iloc[0]/1000-1
    under=0;duration=0
    for row in rows:
        under=under+1 if row['drawdown']>1e-12 else 0;duration=max(duration,under)
    def subset(p=None,short=None):
        selected=[t for t in trades if (p is None or t['pair']==p) and (short is None or t['is_short']==short)]
        return dict(position_cycles=len(selected),net_usdt=sum(t['profit_abs'] for t in selected),funding_usdt=sum(t['funding_fees'] for t in selected))
    groups=[pd.to_datetime(t['open_timestamp'],unit='ms',utc=True).floor('72h') for t in trades]
    returns=eq.equity.pct_change().dropna()
    report=dict(native_position_cycles=len(trades),native_orders=sum(len(t['orders']) for t in trades),
        filled_orders=len(fills),completed_position_cycles=sum(not t['is_open'] for t in trades),
        common_72h_entry_clusters=len(set(groups)),clusters_are_approximately_dependent=True,
        net_usdt=cash-1000,total_return=cash/1000-1,
        annualized_return=(cash/1000)**(365/((end-start).total_seconds()/86400))-1 if cash>0 else None,
        annualization_is_descriptive_development=True,gross_price_effect_usdt=cash-1000+cost-funding,
        taker_fee_usdt=cost*.75,slippage_allowance_usdt=cost*.25,funding_usdt=funding,
        observed_hourly_mtm_drawdown=max(r['drawdown'] for r in rows),drawdown_duration_hours=duration,
        mean_gross_exposure_fraction=float((eq.gross_exposure/eq.equity).mean()),
        max_gross_exposure_fraction=float((eq.gross_exposure/eq.equity).max()),
        turnover_notional_usdt=turnover,turnover_starting_capital=turnover/1000,
        worst_hour_equity_return=float(returns.min()) if len(returns) else None,
        worst_position_net_usdt=min((t['profit_abs'] for t in trades),default=None),
        by_pair={p:subset(p=p) for p in PAIRS},by_side={'long':subset(short=False),'short':subset(short=True)},
        monthly_returns={str(k.date()):float(v) for k,v in monthly_return.items()},
        conditional_same_fill_stress_net_usdt=cash-1000-turnover*.0004,
        native_exit_reasons={k:sum(t['exit_reason']==k for t in trades) for k in sorted({t['exit_reason'] for t in trades})},
        accounting_reconciliation='PASS',native_profit_usdt=native_profit,independent_confirmation=False,
        true_intrahour_drawdown=None,actual_bid_ask_impact=None,
        historical_contract_rules_verified=False,confidence_interval=None,
        uncertainty='Development only; overlapping two-asset signals and selection prohibit independent-sample significance. No return CI fabricated.')
    return report, rows
