"""Native pure-method checks only; this file never creates Backtesting objects."""
from pathlib import Path
import subprocess
import sys

PYTHON=Path('/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue-43-profile-driven-v1/venv/bin/python')


def check_methods():
    from decimal import Decimal,ROUND_HALF_UP
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
    from lab.portfolio_observed_prepare import NATIVE_SOURCE
    from lab.portfolio_observed_source import load_view
    from datetime import timedelta
    import pandas as pd
    from math import isnan
    sys.path.insert(0,str(NATIVE_SOURCE))
    from freqtrade.exchange.exchange_utils import price_to_precision
    from ccxt import ROUND,TICK_SIZE
    from freqtrade.data.btanalysis.historic_precision import get_tick_size_over_time
    for tick in ('.1','.01','.05'):
        for price in ('1.05','1.15','99.995','100.005','100.025','100.035','67890.15'):
            expected=(Decimal(price)/Decimal(tick)).to_integral_value(rounding=ROUND_HALF_UP)*Decimal(tick)
            assert Decimal(str(price_to_precision(float(price),float(tick),TICK_SIZE,rounding_mode=ROUND)))==expected
            assert price_to_precision(float(price),float(tick),TICK_SIZE)==float(expected)
    # Native market entries don't apply the limit custom-price rounder. Every
    # allowed actual open must already lie on the frozen tick; no tolerance.
    view=load_view()
    for pair,bars in view.hourly.items():
        tick=Decimal(next(f['tickSize'] for f in view.metadata[pair]['filters'] if f['filterType']=='PRICE_FILTER'))
        native_rows=[dict(date=t,open=b.open,high=b.high,low=b.low,close=b.close) for t,b in bars.items()
                     if t>=view.start-timedelta(hours=4)]
        grids=get_tick_size_over_time(pd.DataFrame(native_rows))
        for t,bar in bars.items():
            value=Decimal(str(bar.open))
            assert value%tick==0
            assert Decimal(str(price_to_precision(bar.open,float(tick),TICK_SIZE)))==value
            if t>=view.start:
                grid=grids.asof(t)
                if isnan(grid):grid=float(tick)
                assert Decimal(str(price_to_precision(bar.open,grid,TICK_SIZE)))==value


def test_locked_native_rounding_and_real_open_tick_without_backtesting():
    if not PYTHON.exists():
        import pytest
        pytest.skip('locked Git-external native environment unavailable')
    subprocess.run([str(PYTHON),str(Path(__file__).resolve())],check=True,timeout=30)


if __name__=='__main__':check_methods()
