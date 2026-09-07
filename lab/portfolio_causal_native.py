"""Narrow bridge: no replacement of native matching, prices, orders or wallet."""
from freqtrade.optimize.backtesting import Backtesting, LONG_IDX, SHORT_IDX


class CausalBacktesting(Backtesting):
    def validate_row(self,data,pair,row_index,current_time):
        row=super().validate_row(data,pair,row_index,current_time)
        if not row: return row
        # Native backtesting reads entry bits directly and does not call
        # IStrategy.get_entry_signal. Route the already computed current-hour
        # net target into those bits, preserving all OHLC and native order code.
        result=list(row)
        q=self.strategy._target(pair,current_time)
        result[LONG_IDX]=int(q>0)
        result[SHORT_IDX]=int(q<0)
        return result
