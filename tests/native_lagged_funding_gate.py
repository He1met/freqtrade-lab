"""Wholly synthetic gate through the existing pinned offline adapter.

Run with pinned Python and PYTHONDONTWRITEBYTECODE=1; ROOT must be outside Git.
No public data retrieval or economic inference. The adapter input is explicitly
synthetic, including its market identity and provenance fixture.
"""
import ast
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from lab.lagged_funding import funding_source


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def record(path):
    data = path.read_bytes()
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


def main():
    root, native = map(Path, sys.argv[1:3])
    root.mkdir(parents=True, exist_ok=False)
    # Exact native package snapshot is required by the unmodified offline adapter.
    snapshot = root / 'native'
    shutil.copytree(native / 'freqtrade', snapshot / 'freqtrade', ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    digest = hashlib.sha256(b'freqtrade-lab-source-tree-v1\0')
    for path in sorted(p for p in snapshot.rglob('*') if p.is_file()):
        data = path.read_bytes()
        digest.update(path.relative_to(snapshot).as_posix().encode()+b'\0'+str(len(data)).encode()+b'\0'+data+b'\0')
    source_sha = digest.hexdigest()
    # Import native only after snapshot selection, as in the actual adapter launch.
    sys.path.insert(0, str(snapshot))
    import pandas as pd
    from freqtrade.data.dataprovider import DataProvider
    from freqtrade.data.history.datahandlers import get_datahandler
    from freqtrade.enums import CandleType, RunMode
    from freqtrade.exchange.okx import Okx
    from lab.bounded_research import profile_search_config, _verify_profile_output_dates, _search_data_names
    from scripts import run_freqtrade_backtest as runner

    pair = 'LINK/USDT:USDT'
    start, stop = pd.Timestamp('2024-03-01T00:00Z'), pd.Timestamp('2024-03-08T00:00Z')
    dates = pd.date_range(start-pd.Timedelta(minutes=5*289), stop, freq='5min', inclusive='left')
    frame = pd.DataFrame(dict(date=dates, open=100., high=100.1, low=99.9, close=100., volume=10000.))
    # Daily declining midnight closes create enumerated, consecutive short entries.
    midnight = (frame.date.dt.hour == 0) & (frame.date.dt.minute == 0)
    frame.loc[midnight, 'close'] = [100.*.97**i for i in range(midnight.sum())]
    frame['low'] = frame[['open','close','low']].min(axis=1)
    frame.loc[frame.date == pd.Timestamp('2024-03-05T01:00Z'), 'high'] = 104.
    data_dir = root / 'data'; data_dir.mkdir()
    handler = get_datahandler(data_dir, 'feather')
    handler.ohlcv_store(pair, '5m', frame, CandleType.FUTURES)
    mark_dates = pd.date_range(dates[0].floor('h'), stop, freq='h', inclusive='left')
    mark = pd.DataFrame(dict(date=mark_dates, open=100., high=100., low=100., close=100., volume=0.))
    handler.ohlcv_store(pair, '1h', mark, CandleType.MARK)
    event_dates = pd.date_range(start, stop, freq='8h', inclusive='left')
    rates = [0., .0003, .0006, -.0009, 0., 0., .0003, .0006, .0009,
             .0003, -.0004, .0006, .0003, .0006, .0009, .0003, .0006, .0009, .0003, .0006, .0009]
    events = pd.DataFrame(dict(date=event_dates, open=rates, high=0., low=0., close=0., volume=0.))
    handler.ohlcv_store(pair, '1h', events, CandleType.FUNDING_RATE)
    names = _search_data_names(pair,'5m')
    _verify_profile_output_dates(data_dir,names,'20240301-20240308',phase='Search',timeframe='5m',pre_roll_candles=289)
    profile = dict(pairs=[pair],max_open_trades=1,stake_amount=400.,starting_balance=2000.,taker_fee_rate=.0005,timeframe='5m')
    base_config = profile_search_config(profile)
    config = {**base_config, 'runmode':RunMode.BACKTEST, 'datadir':data_dir, 'timerange':'20240301-20240308','candle_type_def':CandleType.FUTURES,'startup_candle_count':289}
    exchange = Okx(config, validate=False, load_leverage_tiers=False)
    dp = DataProvider(config,exchange)
    hourly = dp.get_pair_dataframe(pair,timeframe='1h',candle_type='funding_rate')
    assert len(hourly)>len(events)
    assert hourly.loc[hourly.date == start,'open'].iloc[0] == 0.
    recovered = hourly.loc[(hourly.date.dt.hour % 8 == 0) & (hourly.date.dt.minute == 0)]
    assert recovered.date.tolist() == events.date.tolist()
    assert recovered.open.tolist() == rates
    namespace={}; exec(compile(funding_source(),'<fixed-synthetic-template>','exec'),namespace)
    strategy=namespace['LaggedFundingR1'](config); strategy.dp=dp
    analyzed=strategy.populate_indicators(frame.copy(),{'pair':pair})
    literal = [('2024-03-03',.0003),('2024-03-04',-.0003),('2024-03-05',.0006),('2024-03-06',.0005/3),('2024-03-07',.0006)]
    for day, mean in literal:
        row=analyzed.loc[analyzed.date==pd.Timestamp(day+'T00:00Z')].iloc[0]
        assert abs(row.lagged_funding-mean)<1e-14, (day,row.lagged_funding,mean)
        assert row.funding_valid and row.price_valid and row.time_valid
    assert not analyzed.loc[analyzed.date<pd.Timestamp('2024-03-03T00:00Z'),'funding_valid'].any()
    before=strategy.populate_entry_trend(analyzed.copy(),{'pair':pair})
    exits=strategy.populate_exit_trend(analyzed.copy(),{'pair':pair})
    assert not (before.enter_short.eq(1) & exits.exit_short.eq(1)).any()
    child_namespace={};exec(compile(funding_source('LaggedFundingR2',True),'<fixed-synthetic-template>','exec'),child_namespace)
    child=child_namespace['LaggedFundingR2'](config);child.dp=dp
    child_analyzed=child.populate_indicators(frame.copy(),{'pair':pair})
    for column in ('price_valid','time_valid','funding_valid','lagged_funding'):
        pd.testing.assert_series_equal(analyzed[column],child_analyzed[column])
    # Missing/zero OHLCV inside the 289-candle requirement disables both rounds.
    decision=pd.Timestamp('2024-03-03T00:00Z')
    for case in ('missing','zero_volume'):
        bad=frame.copy()
        damaged=bad.date==pd.Timestamp('2024-03-02T12:00Z')
        if case=='missing': bad=bad.loc[~damaged].reset_index(drop=True)
        else: bad.loc[damaged,'volume']=0.
        for item in (strategy,child):
            tested=item.populate_indicators(bad.copy(),{'pair':pair})
            tested=item.populate_entry_trend(tested,{'pair':pair})
            assert not tested.loc[tested.date==decision,'enter_short'].eq(1).any(),case
    changed=events.copy(); changed.loc[changed.date>=pd.Timestamp('2024-03-05T00:00Z'),'open']=.5
    handler.ohlcv_store(pair,'1h',changed,CandleType.FUNDING_RATE)
    strategy.dp=DataProvider(config,exchange)
    after=strategy.populate_indicators(frame.copy(),{'pair':pair})
    pd.testing.assert_series_equal(analyzed.loc[analyzed.date<pd.Timestamp('2024-03-06T00:00Z'),'lagged_funding'],after.loc[after.date<pd.Timestamp('2024-03-06T00:00Z'),'lagged_funding'])
    handler.ohlcv_store(pair,'1h',events,CandleType.FUNDING_RATE)
    # Producer and consumer reject malformed ORIGINAL events, before native fill.
    from scripts import fetch_okx_profile_data as producer
    from lab.database import get_connection, init_database
    from lab.bounded_research import canonical, profile_acquisition_contract, EXPLORATORY_PROTOCOL
    exploration={'protocol':EXPLORATORY_PROTOCOL,'status':'NOT_INDEPENDENTLY_VALIDATED','exposure_audit_sha256':'a'*64,'prior_research':['synthetic-test-reference']}
    producer_test=root/'producer-test';producer_test.mkdir()
    database=producer_test/'synthetic.sqlite';init_database(database)
    snapshot_profile=dict(id='synthetic',name='Synthetic only',domain='OKX_CRYPTO_PERP',exchange='okx',trading_mode='futures',margin_mode='isolated',pairs=[pair],timeframe='5m',detail_timeframe=None,history_start_date='2024-01-01',smoke_days=7,holdout_days=30,starting_balance=2000.,stake_amount=400.,max_open_trades=1,taker_fee_rate=.0005,stress_fee_multiplier=2.,max_drawdown_pct=15.,min_development_trades=20,min_holdout_trades=20,min_profit_factor=1.1,is_default=0,created_at='2024-01-01T00:00:00Z',updated_at='2024-01-01T00:00:00Z')
    db_profile={key:value for key,value in snapshot_profile.items() if key!='pairs'}
    db_profile['pairs_json']=json.dumps([pair])
    with get_connection(database) as con:
        con.execute(f'INSERT INTO research_profiles ({",".join(db_profile)}) VALUES ({",".join("?" for _ in db_profile)})',tuple(db_profile.values()))
        con.commit()
    window=producer_test/'window.json'
    write_json(window,{'schema':'freqtrade-lab-exploratory-source-window-v1','exploration':exploration,'data_start_utc':'2024-02-28T23:55:00Z','search_start_utc':'2024-03-01T00:00:00Z','development_start_utc':'2024-03-08T00:00:00Z','end_exclusive_utc':'2024-03-08T00:00:00Z'})
    producer.configure_profile_acquisition(database,'synthetic',window,289)
    original=[{'timestamp':int(d.timestamp()*1000),'fundingRate':rate} for d,rate in zip(event_dates,rates)]
    producer.validate_funding_history(original)
    negatives={
        'missing':events.drop(index=3),
        'duplicate':pd.concat([events.iloc[:3],events.iloc[2:]]),
        'unordered':events.iloc[[1,0,*range(2,len(events))]],
        'off_grid':events.assign(date=events.date+pd.Timedelta(minutes=1)),
        'hourly_filled':hourly,
    }
    rejected=[]
    for label,bad in negatives.items():
        raw=[{'timestamp':int(r.date.timestamp()*1000),'fundingRate':r.open} for r in bad.itertuples()]
        try: producer.validate_funding_history(raw)
        except RuntimeError: pass
        else: raise AssertionError('producer accepted '+label)
        handler.ohlcv_store(pair,'1h',bad,CandleType.FUNDING_RATE)
        try: _verify_profile_output_dates(data_dir,names,'20240301-20240308',phase='Search',timeframe='5m',pre_roll_candles=289)
        except Exception as exc:
            assert 'not contiguous' in str(exc),str(exc)
        else: raise AssertionError('consumer accepted '+label)
        rejected.append(label)
    # A missing true-grid event is silently filled with zero by native. It is
    # indistinguishable there from an actual zero; ORIGINAL validation is vital.
    handler.ohlcv_store(pair,'1h',events.drop(index=3),CandleType.FUNDING_RATE)
    filled_missing=DataProvider(config,exchange).get_pair_dataframe(pair,timeframe='1h',candle_type='funding_rate')
    assert filled_missing.loc[filled_missing.date==events.iloc[3].date,'open'].iloc[0]==0.
    handler.ohlcv_store(pair,'1h',events,CandleType.FUNDING_RATE)
    exchange.close()
    market=dict(id='LINK-USDT-SWAP',symbol=pair,base='LINK',quote='USDT',settle='USDT',baseId='LINK',quoteId='USDT',settleId='USDT',active=True,contract=True,swap=True,spot=False,future=False,option=False,linear=True,inverse=False,type='swap',contractSize=1.,expiry=None,precision={'amount':.01,'price':.001},limits={'amount':{'min':.01,'max':1000000},'price':{'min':.001,'max':None},'cost':{'min':1.,'max':None},'leverage':{'min':1.,'max':20.}},maker=.0005,taker=.0005,info={})
    tiers=[{'symbol':pair,'minNotional':0.,'maxNotional':1000000.,'maintenanceMarginRate':.005,'maxLeverage':20.,'info':{'imr':'.05','mmr':'.005'}}]
    write_json(root/'market.json',market);write_json(root/'tiers.json',tiers)
    # Existing producer configuration accepts the planned window/pre-roll, before
    # any market values: this does not download or assert historical availability.
    planned=json.loads(window.read_text())
    planned.update(development_start_utc='2024-07-31T00:00:00Z',end_exclusive_utc='2024-07-31T00:00:00Z')
    planned_window=producer_test/'planned-window.json';write_json(planned_window,planned)
    planned_contract=producer.configure_profile_acquisition(database,'synthetic',planned_window,289)
    from lab.bounded_research import _search_window_contract
    planned_rows=_search_window_contract(planned_contract['search_timerange'],timeframe='5m',pre_roll_candles=289)['rows']
    assert planned_rows=={'futures_5m':44065,'mark_1h':3673,'funding_history':456}
    # Exercise the existing producer's native writer and provenance, then its
    # actual Search consumer. This entirely synthetic source is never downloaded.
    producer.configure_profile_acquisition(database,'synthetic',window,289)
    synthetic_source=root/'synthetic-source'
    source_data=synthetic_source/'data'/'okx';source_data.mkdir(parents=True)
    def candle_rows(table):
        return [[int(row.date.timestamp()*1000),row.open,row.high,row.low,row.close,row.volume]
                for row in table.itertuples()]
    producer.store_profile_market_data(source_data,candle_rows(frame),candle_rows(mark),original)
    write_json(synthetic_source/'market_snapshot.json',market)
    write_json(synthetic_source/'isolated_tiers_snapshot.json',tiers)
    synthetic_receipt=synthetic_source/'retrieval_receipt.json'
    write_json(synthetic_receipt,{'synthetic':True,'meaning':'Invented test values; no public retrieval or economic evidence',
        'host':'www.okx.com','authentication':'none','pair':pair,'instrument_id':market['id'],
        'data_window':{'start_utc':dates[0].isoformat(),'end_exclusive_utc':stop.isoformat(),
            'fully_closed_at_fetch':True,'development_start_utc':start.isoformat(),
            'holdout_start_utc':stop.isoformat(),'startup_candles_required':289}})
    provenance_path=producer.write_profile_provenance(synthetic_source,synthetic_receipt,
        {'freqtrade_tag':'2026.7','freqtrade_commit':runner.SUPPORTED_FREQTRADE_COMMIT,'versions':runner.SUPPORTED_DEPENDENCIES})
    from lab.bounded_research import prepare_search_data
    source_preparation=prepare_search_data(synthetic_source,root/'synthetic-consumer',record(provenance_path)['sha256'],record(synthetic_receipt)['sha256'],
        database_path=database,profile_id='synthetic',search_timerange='20240301-20240308',development_timerange=None,pre_roll_candles=289,exploration=exploration)
    from lab.search_campaign import _acquisition_snapshot
    consumer_binding=_acquisition_snapshot(root/'synthetic-consumer',database)
    assert consumer_binding['pre_roll_candles']==289 and consumer_binding['exploration']==exploration
    assert consumer_binding['profile_snapshot']==snapshot_profile
    reports=[]
    for index in (1,2):
        run=root/f'run-{index}';run.mkdir();(run/'strategies').mkdir();(run/'user').mkdir();(run/'exports').mkdir()
        name=f'LaggedFundingR{index}';path=run/'strategies'/f'{name}.py';path.write_text(funding_source(name,index==2))
        from lab.research_candidate import _runtime_config
        write_json(run/'config.json',_runtime_config(base_config,config_source=run/'config.json',data_dir=data_dir,user_data_dir=run/'user',strategy_path=path.parent,strategy=name,timerange='20240301-20240308',fee=.0005,export_dir=run/'exports'))
        provenance={'synthetic':True,'meaning':'Wholly invented fixture. No public retrieval, model provenance, research, or economic evidence.', 'schema':runner.SEARCH_DATA_SCHEMA,'source':{'host':'www.okx.com','authentication':'none','pair':pair,'instrument_id':market['id']},'freqtrade':{'version':'2026.7','tag':'2026.7','commit':runner.SUPPORTED_FREQTRADE_COMMIT,'dependencies':runner.SUPPORTED_DEPENDENCIES},'contract':{'timeframe':'5m','search_timerange':'20240301-20240308','data_dir':'data','market_snapshot':'market.json','leverage_tiers':'tiers.json','strategy':'strategies/'+path.name},'files':{'strategies/'+path.name:record(path)},'local_only_files':{'data/'+p.relative_to(data_dir).as_posix():record(p) for p in data_dir.rglob('*.feather')}}
        # Runtime Profile binding: reuse a fully shaped synthetic Profile from tests.
        provenance['contract'].update(profile_snapshot=snapshot_profile,profile_snapshot_sha256=hashlib.sha256(canonical(snapshot_profile)).hexdigest())
        provenance['local_only_files'].update({'market.json':record(root/'market.json'),'tiers.json':record(root/'tiers.json')})
        write_json(run/'provenance.json',provenance)
        argv=[sys.executable,str(REPO/'scripts/run_freqtrade_backtest.py'),'--runner-sha256',record(REPO/'scripts/run_freqtrade_backtest.py')['sha256'],'--freqtrade-source',str(snapshot),'--source-tree-sha256',source_sha,'--scenario','SEARCH','--config',str(run/'config.json'),'--data-dir',str(data_dir),'--user-data-dir',str(run/'user'),'--strategy-path',str(path.parent),'--strategy-file',str(path),'--strategy-sha256',record(path)['sha256'],'--strategy',name,'--timerange','20240301-20240308','--fee','.0005','--export-dir',str(run/'exports'),'--market-snapshot',str(root/'market.json'),'--leverage-tiers',str(root/'tiers.json'),'--data-provenance',str(run/'provenance.json')]
        write_json(run/'argv.json',argv)
        result=subprocess.run(argv,env={**os.environ,'PYTHONPATH':str(snapshot),'PYTHONDONTWRITEBYTECODE':'1'},capture_output=True,text=True)
        (run/'stdout.txt').write_text(result.stdout);(run/'stderr.txt').write_text(result.stderr)
        assert result.returncode==0,result.stderr
        summary=json.loads(result.stdout)
        with zipfile.ZipFile(run/'exports'/summary['archive']) as archive:
            report_name=next(n for n in archive.namelist() if n.endswith('.json') and not n.endswith('_config.json'))
            report=json.loads(archive.read(report_name))['strategy'][name]
        trades=report['trades']
        assert len(trades)==(5 if index==1 else 4),trades
        assert len({trade['open_date'][:10] for trade in trades})==len(trades)
        assert trades[-1]['open_date'].startswith('2024-03-07')
        for trade in trades:
            assert trade['open_date'].endswith('00:05:00+00:00'),trade
            assert trade['is_short'] and trade['leverage']==1
            if trade['open_date'].startswith('2024-03-05'):
                assert trade['exit_reason']=='stop_loss' and trade['trade_duration']==55,trade
                assert trade['funding_fees']==0,trade
            else:
                assert trade['exit_reason']=='exit_signal' and trade['close_date'].endswith('08:05:00+00:00') and trade['trade_duration']==480,trade
                expected={'2024-03-03':.24,'2024-03-04':-.16,'2024-03-06':.24,'2024-03-07':.24}[trade['open_date'][:10]]
                assert abs(trade['funding_fees']-expected)<1e-10,trade
        reports.append({'strategy':name,'native_summary':summary,'trades':trades})
    write_json(root/'gate.json',{'status':'PASS','synthetic_only':True,'original_events':len(events),'native_hourly_rows':len(hourly),'first_decision':'2024-03-03T00:05:00Z','rejected_originals':rejected,'shared_guards_and_entry_exit_conflicts':'PASS','planned_window_rows_metadata_only':planned_rows,'actual_synthetic_producer_consumer':source_preparation,'reports':reports})
    print(json.dumps({'status':'PASS','synthetic_only':True,'root':str(root)}))


if __name__=='__main__': main()
