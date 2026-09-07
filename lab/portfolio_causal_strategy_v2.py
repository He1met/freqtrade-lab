"""Synthetic/7 consumer: same native callbacks with explicitly versioned risk."""
from lab.portfolio_causal_strategy import PortfolioCausalProbe
from lab.portfolio_causal_fixture_v2 import input_sha,expand
from lab.portfolio_causal import BASE_SHA,State
from lab.portfolio_risk_v2 import V2_SHA,RiskState,decision_v2,advance_v2


class PortfolioCausalProbeV2(PortfolioCausalProbe):
    fixed_input_sha=staticmethod(input_sha)
    fixed_expand=staticmethod(expand)

    def initial_state(self): return RiskState(State('B'))

    def make_decision(self,current_time,equity):
        return decision_v2(self.daily,current_time,equity,mode='B',selection=self.spec['selection'],
                           base_protocol_sha256=BASE_SHA,semantics_sha256=V2_SHA)

    def advance_state(self,**kwargs):
        return advance_v2(self.state,base_protocol_sha256=BASE_SHA,semantics_sha256=V2_SHA,**kwargs)
