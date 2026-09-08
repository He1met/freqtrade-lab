"""V2 changes only the persistence strategy's opposing exit-channel length."""
from pathlib import Path

from lab.perp_baseline import PerpBaseline


class PerpTurnoverV2(PerpBaseline):
    def bot_start(self, **kwargs):
        super().bot_start(**kwargs)
        if self.config['perp_variant'] != 'persistence' or self.config.get('perp_exit_hours') not in (24,48):
            raise ValueError('V2 permits only persistence with 24h/48h exit channel')

    def populate_exit_trend(self, dataframe, metadata):
        hours=self.config['perp_exit_hours']
        if hours not in (24,48):
            raise ValueError('exit channel outside frozen two-variant budget')
        long=dataframe.close < dataframe.low.shift(1).rolling(hours).min()
        short=dataframe.close > dataframe.high.shift(1).rolling(hours).max()
        # Keep V1 close+60s availability and native's additional next-bar shift.
        dataframe['exit_long']=long.shift(1,fill_value=False).astype(int)
        dataframe['exit_short']=short.shift(1,fill_value=False).astype(int)
        return dataframe


def run_native_v2(root,frames,events,metadata,hours,start,end):
    """Use V1's native assembly/accounting; select a separately named V2 class."""
    import pandas as pd
    from freqtrade.commands.optimize_commands import setup_optimize_configuration
    from freqtrade.enums import RunMode,CandleType
    from freqtrade.exchange.binance import Binance
    from freqtrade.optimize.backtesting import Backtesting
    from freqtrade.data.history.datahandlers import get_datahandler
    from lab.perp_baseline_runner import REPO,PAIRS,native_config,assembly,write,sha
    from lab.portfolio_native_export import read_strategy_export
    if hours not in (24,48):
        raise ValueError('unknown V2 variant')
    root=Path(root)
    for name in ('user','exports','data'):
        (root/name).mkdir(parents=True)
    handler=get_datahandler(root/'data','feather')
    for pair,frame in frames.items():
        handler.ohlcv_store(pair,'1h',frame,CandleType.FUTURES)
    value=native_config('persistence',1.)
    value.update(strategy='PerpTurnoverV2',perp_exit_hours=hours)
    path=root/'config.json';write(path,value)
    config=setup_optimize_configuration(dict(command='backtesting',config=[str(path)],
        datadir=str(root/'data'),user_data_dir=str(root/'user'),strategy_path=str(REPO/'lab'),
        strategy='PerpTurnoverV2',timerange=f'{int(start.timestamp())}-{int(end.timestamp())}',fee=.0008,
        export='trades',exportdirectory=str(root/'exports'),dataformat_ohlcv='feather',
        disableparamexport=True,backtest_cache='none'),RunMode.BACKTEST)

    class EventBacktesting(Backtesting):
        def _load_bt_data_detail(self):
            if self.timeframe_detail:
                raise ValueError('no V2 intrahour extension')
            self.detail_data={};self.futures_data=events;self.funding_fee_timeframe_secs=3600

    class EventBinance(Binance):
        def calculate_funding_fees(self,df,amount,is_short,open_date,close_date):
            return super().calculate_funding_fees(df.loc[df.date>pd.Timestamp(open_date)],
                amount=amount,is_short=is_short,open_date=open_date,close_date=close_date)

    exchange=EventBinance(config,validate=False,load_leverage_tiers=False)
    def deny(*a,**k):raise RuntimeError('V2 native worker cannot request exchange')
    exchange._api.fetch=deny;exchange._api_async.fetch=deny
    markets,tiers=assembly(metadata)
    exchange._api.set_markets(markets,{});exchange._api_async.set_markets(markets,{})
    exchange._markets=exchange._api.markets;exchange._leverage_tiers=tiers
    engine=None
    try:
        engine=EventBacktesting(config,exchange=exchange)
        if len(engine.strategylist)!=1 or set(engine.pairlists.whitelist)!=set(PAIRS):
            raise ValueError('wrong native wallet/pair scope')
        engine.start()
        archives=list((root/'exports').glob('*.zip'))
        if len(archives)!=1:raise ValueError('expected one native archive')
        result=read_strategy_export(archives[0],'PerpTurnoverV2')
        write(root/'native-result.json',result)
        write(root/'entry-audit.json',engine.strategylist[0].entry_audit)
        return result,{p.name:sha(p) for p in archives}
    finally:
        if engine is not None:engine.cleanup()
        exchange.close()
