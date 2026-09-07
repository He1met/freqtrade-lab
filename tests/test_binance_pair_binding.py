"""Two fixed identities, synthetic inputs only: no HTTP or native backtests."""
import hashlib
import json

import pytest

from lab import binance_source as producer, bounded_research as pilot
from lab.futures_costs import FuturesCostError, audit_from_source, binance_identity
from tests.test_spot_research import spot_profile

PAIRS = ['BCH/USDT:USDT', 'DOGE/USDT:USDT']
START = 1704067200000  # synthetic 2024-01-01
DAY = 86400000


@pytest.mark.parametrize('pair', PAIRS)
def test_transport_binds_one_pair_even_when_other_pair_is_supported(pair):
    identity = binance_identity(pair)
    other = binance_identity(next(p for p in PAIRS if p != pair))
    for path, interval in [('fundingRate',''), ('klines','&interval=1d'), ('markPriceKlines','&interval=1h')]:
        url = f'https://fapi.binance.com/fapi/v1/{path}?symbol={identity["instrument_id"]}&startTime=100{interval}'
        assert 'endTime=199' in producer.bounded_url(url,'GET',100,200,pair=pair)
        with pytest.raises(FuturesCostError, match='identity'):
            producer.bounded_url(url.replace(identity['instrument_id'],other['instrument_id']),
                                 'GET',100,200,pair=pair)


def synthetic_source(tmp_path, monkeypatch, pair):
    pytest.importorskip('freqtrade.data.converter')
    from scripts import fetch_okx_profile_data
    _, profile = spot_profile(tmp_path)
    profile.update(domain='BINANCE_CRYPTO_PERP',exchange='binance',trading_mode='futures',
        margin_mode='isolated',pairs=[pair],timeframe='1d',max_open_trades=1,history_start_date='2023-12-30',
        min_development_trades=2)  # Small synthetic source contract, not the Issue98 economic Profile.
    contract=pilot.profile_search_contract(profile,'20240101-20240105','20240105-20240109',2)
    monkeypatch.setattr(fetch_okx_profile_data,'validate_runtime',lambda:{
        'freqtrade_tag':'2026.7','freqtrade_commit':'52bc96f4480b1a0da6a9b455bd00b17fbb6786a5',
        'versions':dict(pilot.RUNNER_DEPENDENCIES)})
    i=binance_identity(pair)
    market={'symbol':i['instrument_id'],'baseAsset':i['base'],'quoteAsset':'USDT','marginAsset':'USDT',
        'status':'TRADING','contractType':'PERPETUAL','deliveryDate':4133404800000,'onboardDate':1600000000000,
        'pricePrecision':5,'quantityPrecision':0,'baseAssetPrecision':8,'quotePrecision':8,
        'filters':[{'filterType':'PRICE_FILTER','minPrice':'0.00001','maxPrice':'10000','tickSize':'0.00001'},
                   {'filterType':'LOT_SIZE','minQty':'1','maxQty':'1000000','stepSize':'1'},
                   {'filterType':'MIN_NOTIONAL','notional':'5'}]}
    raw=tmp_path/'raw';raw.mkdir(); receipts=tmp_path/'receipts.jsonl';records=[]
    def add(path, body, query=''):
        data=json.dumps(body).encode();name=f'{len(records)}.json';(raw/name).write_bytes(data)
        records.append({'url':'https://fapi.binance.com/fapi/v1/'+path+query,
            'body_file':name,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()})
    add('exchangeInfo',{'symbols':[market]})
    lo,hi=START-2*DAY,START+8*DAY
    query=f'?symbol={i["instrument_id"]}&startTime={lo}&endTime={hi-1}'
    for path,step,tf in [('klines',DAY,'1d'),('markPriceKlines',3600000,'1h')]:
        add(path,[[t,'100','102','98','100','1000',t+step-1,'100000',1,'500','50000','0']
                  for t in range(lo,hi,step)],query+'&interval='+tf)
    add('fundingRate',[{'symbol':i['instrument_id'],'fundingTime':t,'fundingRate':'0.001','markPrice':'100'}
                       for t in range(START,hi,28800000)],query)
    receipts.write_text(''.join(json.dumps(r)+'\n' for r in records))
    return contract,receipts,raw


@pytest.mark.parametrize('pair', PAIRS)
def test_compile_source_actual_converter_and_search_development_consumer(tmp_path, monkeypatch, pair):
    contract,receipts,raw=synthetic_source(tmp_path,monkeypatch,pair)
    output=tmp_path/'source'
    hashes=producer.compile_source(output,receipts,raw,contract)
    provenance=json.loads((output/'retained-data-provenance.json').read_bytes())
    i=binance_identity(pair)
    assert provenance['source']['pair']==pair
    assert provenance['source']['instrument_id']==i['instrument_id']
    assert all(p.name.startswith(i['file_stem']) for p in (output/'data/binance/futures').iterdir())
    # Full producer-to-consumer validation, including Profile, native market/tiers and S+D coverage.
    loaded=pilot._load_search_source(output,hashes['provenance_sha256'],hashes['retrieval_receipt_sha256'],
                                    profile_contract=contract)
    assert loaded
    for timerange in ('20240101-20240105','20240105-20240109'):
        start,stop=pilot.timerange(timerange,'synthetic phase')
        source=producer.phase_source(provenance['source'],start,stop)
        producer.validate_source(source,output/'data/binance',pair,start,stop)
        report={'trades':[],'starting_balance':1000,'profit_total':0}
        audit=audit_from_source(report,source,output/'data/binance',timerange)
        assert audit['conservative_final_balance']==1000
        assert audit['conservative_profit_factor'] is None
    # Nonzero native long/short cash flows must retain the selected pair through the audit adapter.
    from tests.test_futures_costs import trade
    for short in (False,True):
        t=trade(short,opened=START+3600000,closed=START+9*3600000)
        pnl=0.1 if short else -0.1
        t.update(pair=pair,funding_fees=pnl,profit_abs=pnl)
        source=producer.phase_source(provenance['source'],*pilot.timerange('20240101-20240105','S'))
        audit=audit_from_source({'trades':[t],'starting_balance':1000,'profit_total':pnl/1000},
                                source,output/'data/binance','20240101-20240105')
        assert audit['conservative_final_balance']==pytest.approx(1000+pnl)


@pytest.mark.parametrize('pair',PAIRS)
def test_capture_uses_frozen_pair_for_config_command_and_prefetch_guard(tmp_path,monkeypatch,pair):
    contract,_,_=synthetic_source(tmp_path,monkeypatch,pair)
    import ccxt
    import freqtrade.main as native_main
    identity=binance_identity(pair);calls=[]
    def fake_transport(exchange,url,method,headers,body):
        calls.append(url)
        exchange.last_http_response='[]';exchange.last_response_headers={}
        return []
    monkeypatch.setattr(ccxt.Exchange,'fetch',fake_transport)
    def fake_main(argv):
        from pathlib import Path
        assert argv[argv.index('--pairs')+1]==pair
        config=json.loads(Path(argv[argv.index('--config')+1]).read_bytes())
        assert config['exchange']['pair_whitelist']==[pair]
        client=ccxt.binance()
        client.fetch(f'https://fapi.binance.com/fapi/v1/fundingRate?symbol={identity["instrument_id"]}&startTime={START}')
        other=binance_identity(next(p for p in PAIRS if p!=pair))
        with pytest.raises(FuturesCostError):
            client.fetch(f'https://fapi.binance.com/fapi/v1/fundingRate?symbol={other["instrument_id"]}&startTime={START}')
    monkeypatch.setattr(native_main,'main',fake_main)
    receipts,_=producer.capture_native(tmp_path/'capture',contract)
    assert len(calls)==1 and len(receipts.read_text().splitlines())==1


def test_invalid_profile_fails_before_capture_root_or_retained_reads(tmp_path,monkeypatch):
    contract,receipts,raw=synthetic_source(tmp_path,monkeypatch,PAIRS[1])
    contract['profile_snapshot']['pairs']=['ETH/USDT:USDT']
    with pytest.raises(pilot.PilotError):producer.capture_native(tmp_path/'capture',contract)
    with pytest.raises(pilot.PilotError):producer.compile_source(tmp_path/'output',receipts,raw,contract)
    assert not (tmp_path/'capture').exists() and not (tmp_path/'output').exists()


def test_holdout_cannot_rebind_authorized_profile_before_output(tmp_path,monkeypatch):
    contract,receipts,raw=synthetic_source(tmp_path,monkeypatch,PAIRS[1])
    contract['holdout_source']={'profile_snapshot':{**contract['profile_snapshot'],'pairs':[PAIRS[0]]}}
    with pytest.raises(FuturesCostError,match='Profile binding'):
        producer.capture_native(tmp_path/'capture',contract)
    with pytest.raises(FuturesCostError,match='Profile binding'):
        producer.compile_source(tmp_path/'output',receipts,raw,contract)
    assert not (tmp_path/'capture').exists() and not (tmp_path/'output').exists()


@pytest.mark.parametrize('failure',['request_pair','funding_pair','market_base','market_margin',
    'missing_mark','missing_event','duplicate_event','native_tiers'])
def test_mixed_or_incomplete_source_rejected_before_publication(tmp_path, monkeypatch, failure):
    contract,receipts,raw=synthetic_source(tmp_path,monkeypatch,PAIRS[1])
    records=[json.loads(line) for line in receipts.read_text().splitlines()]
    index=0 if failure.startswith('market') else 3
    rec=records[index];body=json.loads((raw/rec['body_file']).read_bytes())
    if failure=='request_pair':rec['url']=rec['url'].replace('DOGEUSDT','BCHUSDT')
    elif failure=='funding_pair':body[0]['symbol']='BCHUSDT'
    elif failure=='market_base':body['symbols'][0]['baseAsset']='BCH'
    elif failure=='market_margin':body['symbols'][0]['marginAsset']='DOGE'
    elif failure=='missing_mark':body[0]['markPrice']=''
    elif failure=='missing_event':body.pop(0)
    elif failure=='duplicate_event':body[1]['fundingTime']=body[0]['fundingTime']+1
    elif failure=='native_tiers':
        import freqtrade.exchange.binance as native
        monkeypatch.setattr(native,'__file__',str(tmp_path/'native.py'))
        (tmp_path/'binance_leverage_tiers.json').write_text(json.dumps({PAIRS[1]:[{'symbol':PAIRS[0]}]}))
    data=json.dumps(body).encode();(raw/rec['body_file']).write_bytes(data)
    rec.update(bytes=len(data),sha256=hashlib.sha256(data).hexdigest())
    receipts.write_text(''.join(json.dumps(r)+'\n' for r in records))
    with pytest.raises(FuturesCostError):producer.compile_source(tmp_path/'output',receipts,raw,contract)
    assert not (tmp_path/'output').exists() and not list(tmp_path.glob('.binance-source-*'))


@pytest.mark.parametrize('failure',['source_pair','source_symbol','source_family','mark_path','trade_pair'])
def test_consumer_and_audit_cannot_substitute_other_supported_pair(tmp_path,monkeypatch,failure):
    contract,receipts,raw=synthetic_source(tmp_path,monkeypatch,PAIRS[1])
    output=tmp_path/'source';producer.compile_source(output,receipts,raw,contract)
    source=json.loads((output/'retained-data-provenance.json').read_bytes())['source']
    start,stop=pilot.timerange('20240101-20240103','S')
    source=producer.phase_source(source,start,stop)
    if failure=='source_pair':source['pair']=PAIRS[0]
    elif failure=='source_symbol':source['instrument_id']='BCHUSDT'
    elif failure=='source_family':source['pair_family']='BCH-USDT'
    elif failure=='mark_path':
        mark=output/'data/binance/futures/DOGE_USDT_USDT-1h-mark.feather'
        mark.rename(mark.with_name('BCH_USDT_USDT-1h-mark.feather'))
    if failure!='trade_pair':
        with pytest.raises((FuturesCostError,FileNotFoundError)):
            producer.validate_source(source,output/'data/binance',PAIRS[1],start,stop)
    else:
        from tests.test_futures_costs import trade
        t=trade(opened=START,closed=START+3600000)
        with pytest.raises(FuturesCostError,match='pair'):
            audit_from_source({'trades':[t],'starting_balance':1000,'profit_total':-0.001},
                              source,output/'data/binance','20240101-20240103')


def test_unknown_pair_rejected_before_receipt_read_or_output(tmp_path):
    with pytest.raises(FuturesCostError):
        producer.retained_responses(tmp_path/'missing',tmp_path,pair='ETH/USDT:USDT')
    with pytest.raises(FuturesCostError):
        producer.bounded_url('https://fapi.binance.com/fapi/v1/exchangeInfo','GET',100,200,pair='ETH/USDT:USDT')
    assert list(tmp_path.iterdir())==[]
