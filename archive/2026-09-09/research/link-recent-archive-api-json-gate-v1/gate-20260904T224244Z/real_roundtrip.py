"""Native JSON 100-row conditional contracts-quantity format only."""
import sys,pathlib,json,hashlib,os
from decimal import Decimal
ROOT=pathlib.Path(__file__).resolve().parent
os.umask(0o077)
network=[]
def block_network(event,args):
    if event in {'socket.connect','socket.getaddrinfo','socket.sendto'}:
        network.append(event); raise RuntimeError('NETWORK_FORBIDDEN')
sys.addaudithook(block_network)
import freqtrade
from pandas.testing import assert_frame_equal
from freqtrade.data.converter.trade_converter import trades_list_to_df
from freqtrade.data.history import get_datahandler
from freqtrade.enums import TradingMode
receipt={'status':'FAILED_STOP','dataformat_trades':'json','unit':'conditional contracts-quantity only','historical_contractSize':'UNKNOWN','base_amount_conversion':'UNPROVEN','real_strategy_called':False}
try:
    assert freqtrade.__version__=='2026.7'
    bridge=json.loads((ROOT/'bridge-result.json').read_text()); assert bridge['status']=='PASS_SAMPLE_BRIDGE_ONLY'
    for n,h in bridge['persisted_sha256'].items(): assert hashlib.sha256((ROOT/n).read_bytes()).hexdigest()==h
    selected=json.loads((ROOT/'selected-normalized.json').read_text()); assert len(selected)==100
    rows=[[r['timestamp'],r['id'],None,r['side'],float(Decimal(r['price'])),float(Decimal(r['contracts_size'])),None] for r in selected]
    before=trades_list_to_df(rows)
    parent=ROOT/'real-format'/'data'; assert parent.is_dir()
    handler=get_datahandler(parent,'json')
    handler.trades_store('LINK/USDT:USDT',before,TradingMode.FUTURES)
    after=handler.trades_load('LINK/USDT:USDT',TradingMode.FUTURES)
    assert_frame_equal(before,after,check_exact=True)
    assert len(after)==100
    for original,(_,r) in zip(selected,after.iterrows()):
        assert r['id']==original['id'] and r['timestamp']==original['timestamp'] and r['side']==original['side'],'IDENTITY'
        assert Decimal(str(r['price']))==Decimal(original['price']),'DECIMAL_PRICE'
        assert Decimal(str(r['amount']))==Decimal(original['contracts_size']),'DECIMAL_CONTRACTS_QUANTITY'
    assert not network
    p=parent/'futures'/'LINK_USDT_USDT-trades.json'
    receipt.update(status='PASS_REAL_FORMAT_ONLY',rows=100,exact_dataframe_roundtrip=True,exact_source_decimal_comparison=True,sha256=hashlib.sha256(p.read_bytes()).hexdigest())
except Exception as e:
    receipt['error_type']=type(e).__name__; receipt['error']=str(e)
    raise
finally:
    receipt['network_attempts']=network
    (ROOT/'real-format-result.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps(receipt,indent=2))
