"""One native strategy class; all five modes use the same observed callbacks."""
from freqtrade.strategy import IStrategy
from lab.portfolio_observed_adapter import ObservedCallbacks


class PortfolioObserved(ObservedCallbacks,IStrategy):
    pass
