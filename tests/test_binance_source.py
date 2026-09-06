import hashlib
import json
from urllib.parse import parse_qs, urlsplit

import pytest

from lab.binance_source import bounded_url, compile_source, retained_responses
from lab.futures_costs import FuturesCostError


def test_native_transport_clamps_discovery_and_exclusive_end():
    url = bounded_url('https://fapi.binance.com/fapi/v1/klines?symbol=BCHUSDT&interval=1d&startTime=0', 'GET', 100, 200)
    assert parse_qs(urlsplit(url).query)['startTime'] == ['100']
    assert parse_qs(urlsplit(url).query)['endTime'] == ['199']


@pytest.mark.parametrize('url', [
    'https://fapi.binance.com/fapi/v1/income?startTime=100',
    'https://fapi.binance.com/fapi/v1/fundingRate?symbol=BCHUSDT&startTime=99',
    'https://fapi.binance.com/fapi/v1/fundingRate?symbol=BCHUSDT&startTime=200',
    'https://fapi.binance.com/fapi/v1/fundingRate?symbol=ETHUSDT&startTime=100',
    'https://fapi.binance.com/fapi/v1/fundingRate?symbol=BCHUSDT&startTime=100&signature=bad',
    'https://other.invalid/fapi/v1/exchangeInfo',
])
def test_transport_rejects_before_fetch(url):
    with pytest.raises(FuturesCostError): bounded_url(url, 'GET', 100, 200)


def test_retained_tamper_rejected(tmp_path):
    body = b'{"symbols": []}'
    (tmp_path/'body').write_bytes(body+b' ')
    receipts=tmp_path/'receipts.jsonl'
    receipts.write_text(json.dumps({'url':'https://fapi.binance.com/fapi/v1/exchangeInfo',
        'body_file':'body','bytes':len(body),'sha256':hashlib.sha256(body).hexdigest()}))
    with pytest.raises(FuturesCostError,match='digest'): retained_responses(receipts,tmp_path)


@pytest.mark.parametrize('failure', ['conversion', 'write', 'publication', 'existing'])
def test_source_failure_cleans_only_owned_temporary_directory(tmp_path, monkeypatch, failure):
    converter = pytest.importorskip('freqtrade.data.converter')
    native = pytest.importorskip('freqtrade.exchange.binance')
    import ccxt
    from lab import binance_source, bounded_research
    from scripts import fetch_okx_profile_data
    start=1699228800000
    rows={'futures':{start:[start,100,100,100,100,1]},
          'mark':{start+i*3600000:[start+i*3600000,100,100,100,100,0] for i in range(24)},
          'funding':{start+i*28800000:{'symbol':'BCHUSDT','fundingTime':start+i*28800000,
              'fundingRate':'0.001','markPrice':'100'} for i in range(3)}}
    monkeypatch.setattr(binance_source,'retained_responses',lambda *_:(rows,{}))
    monkeypatch.setattr(bounded_research,'validate_profile_runtime_contract',lambda *_:None)
    monkeypatch.setattr(fetch_okx_profile_data,'validate_runtime',lambda:{
        'freqtrade_tag':'2026.7','freqtrade_commit':'0'*40,
        'versions':{key:'test' for key in ('ccxt','pandas','pyarrow','python')}})
    monkeypatch.setattr(ccxt.binance,'parse_market',lambda *_:{'symbol':'BCH/USDT:USDT'})
    monkeypatch.setattr(native,'__file__',str(tmp_path/'binance.py'))
    (tmp_path/'binance_leverage_tiers.json').write_text('{"BCH/USDT:USDT": []}')
    class Frame:
        def __init__(self,values):self.size=len(values)
        def __len__(self):return self.size
        def to_feather(self,path):
            path.write_bytes(b'partial')
            if failure=='write':raise OSError('injected write failure')
    def convert(values,*args,**kwargs):
        if failure=='conversion':raise ValueError('injected conversion failure')
        return Frame(values)
    monkeypatch.setattr(converter,'ohlcv_to_dataframe',convert)
    if failure=='publication':
        monkeypatch.setattr(bounded_research,'profile_search_config',lambda *_:{})
        monkeypatch.setattr(bounded_research,'_profile_acquisition_contract_fields',lambda *_:[])
        monkeypatch.setattr(bounded_research,'_publish_directory_exclusive',lambda *_: (_ for _ in ()).throw(OSError('injected publication failure')))
        (tmp_path/'receipts').write_text('test receipt')
    output=tmp_path/'source'
    if failure=='existing':
        output.mkdir();(output/'user-file').write_text('preserve')
    contract={'profile_snapshot':{'exchange':'binance'},'search_timerange':'20231106-20231107',
              'development_timerange':None,'pre_roll_candles':0}
    with pytest.raises((FuturesCostError,ValueError,OSError)):
        compile_source(output,tmp_path/'receipts',tmp_path,contract)
    assert not list(tmp_path.glob('.binance-source-*'))
    if failure=='existing':assert (output/'user-file').read_text()=='preserve'
    else:assert not output.exists()
