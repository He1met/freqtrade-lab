from decimal import Decimal as D
from pathlib import Path
import sys
import tempfile
import time
import pytest
import pandas as pd
sys.path.insert(0,str(Path(__file__).parents[1]))
from scripts import issue157_native_display as p
from lab.spot139_native_bridge import make_engine
from lab.spot139_native_v3 import execute_order
from freqtrade.persistence import LocalTrade
from freqtrade.data.btanalysis import load_backtest_stats


def market():
    return dict(id='BTCUSDT',symbol='BTC/USDT',base='BTC',quote='USDT',baseId='BTC',quoteId='USDT',active=True,
        spot=True,contract=False,swap=False,future=False,option=False,type='spot',contractSize=1.,
        precision={'amount':.001,'price':.00001},limits={'amount':{'min':.001,'max':1000},
        'price':{'min':.00001,'max':1000000},'cost':{'min':5,'max':None},'leverage':{'min':1,'max':1}},maker=.001,taker=.001,info={})


def test_actual_native_synthetic_replay_export_and_mismatch(tmp_path):
    allowed={('BTC/USDT',h):D(100) for h in range(48)}
    rows=[]
    engine,exchange=make_engine(tmp_path/'first',[market()],D('.001'))
    try:
        for h,side,q in [(1,'buy','1'),(2,'sell','.999'),(25,'buy','1'),(26,'sell','.999')]:
            rows.append(execute_order(engine,dict(symbol='BTC/USDT',hour=h,side=side,quantity=D(q),price=D(100),fee_base=D('.001'),fee_quote=D('.0999')),allowed))
    finally:engine.cleanup();exchange.close()
    engine,exchange=make_engine(tmp_path/'rebuild',[market()],D('.001'))
    try:
        compared,open_positions=p.replay(engine,rows,allowed)
        assert len(compared)==4 and len(open_positions)==1
        assert len(LocalTrade.bt_trades_open)==1
        frames={'BTC/USDT':pd.DataFrame([[pd.Timestamp(h*3600,unit='s',tz='UTC'),100.,101.,99.,100.,1.] for h in range(48)],columns=['date','open','high','low','close','volume'])}
        export=tmp_path/'export';export.mkdir()
        out=p.official_export(engine,frames,export,'SYNTHETIC_DISPLAY_REPLAY_FORCE_EXIT','synthetic',time.time())
        assert out['terminal_extra_orders']==1 and out['native_trades']==1
        loaded=load_backtest_stats(Path(out['zip_path']))
        strat=loaded['strategy']['SYNTHETIC_DISPLAY_REPLAY_FORCE_EXIT']
        assert strat['trades'][0]['exit_reason']=='force_exit'
        assert 'NOT signal backtest' in loaded['metadata']['SYNTHETIC_DISPLAY_REPLAY_FORCE_EXIT']['notes']
        assert abs(out['synthetic_terminal_impact']['change'])<.01
    finally:engine.cleanup();exchange.close()
    engine,exchange=make_engine(tmp_path/'mismatch',[market()],D('.001'))
    try:
        bad=dict(rows[0],native_cash='0')
        with pytest.raises(ValueError,match='mismatch'):p.replay(engine,[bad],allowed)
    finally:engine.cleanup();exchange.close()


def test_existing_attempt_cannot_reenter(tmp_path,monkeypatch):
    monkeypatch.setattr(p,'ROOT',tmp_path)
    (tmp_path/'base').mkdir()
    grant=tmp_path/'grant.json'
    p.write(grant,dict(manifest_sha256='freeze',costs=['base','stress'],calls=2,terminal_mode='OFFICIAL_FORCE_EXIT_DISPLAY_ONLY'))
    with pytest.raises(FileExistsError):p.execute({},'freeze','base',grant,p.sha(grant))
