"""Native matching unchanged; direct millisecond funding table replaces join."""
from freqtrade.optimize.backtesting import Backtesting,LONG_IDX,SHORT_IDX
from lab.portfolio_observed_source import load_view,funding_records



class ObservedBacktesting(Backtesting):
    def _load_bt_data_detail(self):
        import pandas as pd
        from lab.portfolio_source import SourceError
        if self.timeframe_detail:raise SourceError('intrahour detail not in model')
        view=load_view();self.detail_data={};self.funding_fee_timeframe_secs=3600
        self.futures_data={}
        for pair in self.pairlists.whitelist:
            rows=funding_records(view,pair)
            if not rows:raise SourceError('missing event segment')
            frame=pd.DataFrame(rows)
            frame['date']=pd.to_datetime(frame['date'],utc=True)
            frame['open_fund']=frame['open_fund'].astype(float);frame['open_mark']=frame['open_mark'].astype(float)
            if frame.isna().any().any():raise SourceError('event table NaN forbidden')
            self.futures_data[pair]=frame
    def validate_row(self,data,pair,row_index,current_time):
        self.strategy.raise_if_invalid()
        row=super().validate_row(data,pair,row_index,current_time)
        if not row:return row
        result=list(row);q=self.strategy._target(pair,current_time)
        result[LONG_IDX]=int(q>0);result[SHORT_IDX]=int(q<0)
        return result
