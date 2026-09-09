"""SYNTHETIC_TEST_ONLY. Stream fixture; unchanged native complete indicator chain."""
import datetime, hashlib, json, os, sys, time, traceback
from pathlib import Path
ROOT=Path(__file__).resolve().parent
START=978307200000
COUNT=9216
TOTAL=9337408
PAIR='LINK/USDT:USDT'
os.umask(0o077)
def no_network(event,args):
    if event in {'socket.connect','socket.getaddrinfo','socket.sendto'}:
        raise RuntimeError('Synthetic process network forbidden')
sys.addaudithook(no_network)
def count(i): return 1013+(i<1600)
def row(i,j,ident):
    n=count(i)
    return [START+i*300000+1+(j*299998)//(n-1),str(ident),None,'sell' if j%2==0 else 'buy',100.0,1.0,100.0]
def stream(path,candles):
    h=hashlib.sha256(); size=0; ident=0
    with path.open('xb') as f:
        def write(b):
            nonlocal size
            # Leave >500MiB for all other new-root files and logs, so total remains <2GiB.
            if size+len(b)>1536*1024**2: raise RuntimeError('OUTPUT_SIZE_LIMIT')
            f.write(b); h.update(b); size+=len(b)
        write(b'[')
        for i in range(candles):
            for j in range(count(i)):
                b=json.dumps(row(i,j,ident),separators=(',',':')).encode()
                write((b',' if ident else b'')+b); ident+=1
        write(b']')
    return {'rows':ident,'bytes':size,'sha256':h.hexdigest()}
def small():
    import pandas as pd
    from pandas.testing import assert_frame_equal
    from freqtrade.constants import DEFAULT_TRADES_COLUMNS
    from freqtrade.data.converter.trade_converter import trades_list_to_df
    from freqtrade.data.history import get_datahandler
    from freqtrade.enums import TradingMode
    assert DEFAULT_TRADES_COLUMNS==['timestamp','id','type','side','price','amount','cost']
    path=ROOT/'small/data/futures/LINK_USDT_USDT-trades.json'
    result=stream(path,2)
    rows=[row(i,j,sum(count(k) for k in range(i))+j) for i in range(2) for j in range(count(i))]
    expected=trades_list_to_df(rows)
    h=get_datahandler(ROOT/'small/data','json')
    actual=h.trades_load(PAIR,TradingMode.FUTURES)
    assert_frame_equal(expected,actual)
    native=get_datahandler(ROOT/'small/native','json'); native.trades_store(PAIR,actual,TradingMode.FUTURES)
    assert_frame_equal(expected,native.trades_load(PAIR,TradingMode.FUTURES))
    result['native_schema_roundtrip']='PASS'; return result
def process():
    import pandas as pd
    from freqtrade.data.dataprovider import DataProvider
    from freqtrade.enums import RunMode,TradingMode,CandleType
    from LinkTakerAbsorptionR2 import LinkTakerAbsorptionR2
    cfg={'runmode':RunMode.BACKTEST,'trading_mode':TradingMode.FUTURES,'candle_type_def':CandleType.FUTURES,
         'timeframe':'5m','datadir':ROOT/'scale/data','dataformat_trades':'json',
         'exchange':{'use_public_trades':True},
         'orderflow':{'cache_size':1000,'max_candles':10000,'scale':.01,'stacked_imbalance_range':3,'imbalance_volume':1,'imbalance_ratio':3}}
    dates=pd.date_range('2001-01-01T00:00:00Z',periods=COUNT,freq='5min')
    data=pd.DataFrame({'date':dates,'open':100.,'high':101.,'low':99.,'close':100.,'volume':[float(count(i)) for i in range(COUNT)]})
    strategy=LinkTakerAbsorptionR2(cfg); strategy.dp=DataProvider(cfg,None,None)
    calls={}; began=time.monotonic()
    selected={('interface.py','advise_all_indicators'),('dataprovider.py','trades'),('jsondatahandler.py','_trades_load'),('orderflow.py','populate_dataframe_with_trades')}
    def trace(frame,event,arg):
        if frame.f_code.co_name not in {'advise_all_indicators','trades','_trades_load','populate_dataframe_with_trades'}: return
        key=(Path(frame.f_code.co_filename).name,frame.f_code.co_name)
        if key in selected and event in ('call','return'):
            if event=='call': calls[str(key)]=calls.get(str(key),0)+1
            print(json.dumps({'stage':key,'event':event,'elapsed_seconds':time.monotonic()-began}),flush=True)
    sys.setprofile(trace)
    try:
        enriched=strategy.advise_all_indicators({PAIR:data})[PAIR]
        native_chain_seconds=time.monotonic()-began
    finally: sys.setprofile(None)
    verify_started=time.monotonic()
    assert all(calls.get(str(k))==1 for k in selected),calls
    assert len(enriched)==COUNT and enriched.date.equals(data.date)
    assert enriched[['bid','ask','delta','total_trades','sell_share']].notna().all().all()
    observed=0
    for i,r in enriched.iterrows():
        n=count(i); bid=(n+1)//2; ask=n//2
        assert r['bid']==bid and r['ask']==ask and r['delta']==ask-bid and r['total_trades']==n, i
        assert r['sell_share']==bid/n, i
        # Verify every original ID, timestamp, side, price, amount and cost after full native processing.
        assert len(r['trades'])==n
        for j,t in enumerate(r['trades']):
            exp=row(i,j,observed)
            assert pd.isna(t['type']),(i,j)
            assert [t[c] for c in ['timestamp','id','side','price','amount','cost']]==[exp[k] for k in [0,1,3,4,5,6]],(i,j)
            observed+=1
    assert observed==TOTAL
    enriched[['date','bid','ask','delta','total_trades','sell_share']].to_json(ROOT/'all-flow-rows.json',orient='records',date_format='iso')
    return {'rows':COUNT,'trades':observed,'start_utc':str(enriched.date.iloc[0]),'last_candle_utc':str(enriched.date.iloc[-1]),'exclusive_end_utc':'2001-02-02T00:00:00Z','every_row_flow_and_every_trade_verified':True,'native_calls':calls,'native_chain_seconds':native_chain_seconds,'verification_and_output_seconds':time.monotonic()-verify_started}
if __name__=='__main__':
    mode=sys.argv[1]; start=time.monotonic(); result={'label':'SYNTHETIC_TEST_ONLY','mode':mode}
    try:
        if mode=='small': result.update(small())
        elif mode=='generate':
            result.update(stream(ROOT/'scale/data/futures/LINK_USDT_USDT-trades.json',COUNT)); assert result['rows']==TOTAL
        elif mode=='process': result.update(process())
        else: raise ValueError(mode)
        result['status']='PASS_SYNTHETIC_ONLY'
    except Exception as e:
        result.update(status='FAIL_STOP',error=repr(e),traceback=traceback.format_exc()); raise
    finally:
        result['elapsed_seconds']=time.monotonic()-start
        (ROOT/(mode+'-result.json')).write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps(result),flush=True)
