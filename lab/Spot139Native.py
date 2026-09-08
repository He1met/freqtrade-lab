"""Minimal strategy shell. Frozen controller supplies all orders explicitly."""
from freqtrade.strategy import IStrategy


class Spot139Native(IStrategy):
    INTERFACE_VERSION=3
    timeframe='1h';can_short=False;startup_candle_count=0
    minimal_roi={};stoploss=-.99;use_exit_signal=True
    position_adjustment_enable=True
    order_types={'entry':'market','exit':'market','stoploss':'market','stoploss_on_exchange':False}
    order_time_in_force={'entry':'GTC','exit':'GTC'}
    def populate_indicators(self,dataframe,metadata):return dataframe
    def populate_entry_trend(self,dataframe,metadata):dataframe['enter_long']=0;return dataframe
    def populate_exit_trend(self,dataframe,metadata):dataframe['exit_long']=0;return dataframe

    def custom_stake_amount(self, pair, current_time, current_rate, proposed_stake, min_stake, max_stake, leverage, entry_tag, side, **kwargs):
        return self.frozen_stake
