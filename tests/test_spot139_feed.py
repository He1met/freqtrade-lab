from decimal import Decimal as D
from lab.spot139_feed import history_at


def test_day_not_visible_until_midnight_and_short_or_missing_day_rejected():
    bar=(D(100),D(110),D(90),D(101))
    hourly={'BTC':{h:(bar,True) for h in range(48)}};daily={'BTC':{}}
    assert not history_at(23,hourly,daily)['BTC']
    assert history_at(24,hourly,daily)['BTC']=={0:bar}
    hourly['BTC'][47]=(bar,False)
    assert 1 not in history_at(48,hourly,daily)['BTC']
    del hourly['BTC'][47]
    assert 1 not in history_at(48,hourly,daily)['BTC']
