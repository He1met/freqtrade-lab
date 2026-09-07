"""Fixed synthetic target probe only, NOT the final economic signal template.

No arbitrary user schedule or source is accepted. Targets deliberately stress
the shared-wallet adapter; daily trend/ATR/reversal discovery is not simulated.
"""
from datetime import datetime, timedelta, timezone
from freqtrade.strategy import IStrategy
from freqtrade.persistence import Trade
from lab.portfolio_execution import SYNTHETIC_VECTOR as VECTOR, capped_targets, executable_quantity, fill_equity

PAIRS = ("BTC/USDT:USDT", "ETH/USDT:USDT")
PRICES = dict(zip(PAIRS, VECTOR["prices"]))
START = datetime.fromisoformat(VECTOR["start"])
MODES = ("B-risk", "A-trend", "A-reversal", "B", "C")


def synthetic_mark(pair, instant, mode):
    factor = 1.
    if mode == "B-risk":
        for hours, value in VECTOR["risk_marks_after_hours"]:
            if instant >= START+timedelta(hours=hours): factor = value
    return PRICES[pair]*factor


def desired_families(instant, mode):
    day = (instant-START).days
    if mode == "B-risk":
        return [dict(zip(PAIRS, VECTOR["risk_target"]))], 1.
    trend = VECTOR["trend"]
    reversal = VECTOR["reversal"]
    t = dict(zip(PAIRS, trend[day] if 0 <= day < 5 else (0., 0.)))
    r = dict(zip(PAIRS, reversal[day] if 0 <= day < 5 else (0., 0.)))
    if mode == "A-trend": return [t], 1.
    if mode == "A-reversal": return [r], 1.
    # Scripted, causal risk-state vector tests callbacks only. It is explicitly
    # not a claim that this table implements the economic volatility formula.
    mult = (VECTOR["C_multiplier"][day] if 0 <= day < 5 else 1.) if mode == "C" else 1.
    return [t, r], mult


class PortfolioSyntheticProbe(IStrategy):
    INTERFACE_VERSION = 3
    timeframe = "1h"
    can_short = True
    startup_candle_count = 1
    minimal_roi = {}
    stoploss = -.99
    position_adjustment_enable = True
    max_entry_position_adjustment = -1
    process_only_new_candles = True
    use_exit_signal = True

    def bot_start(self, **kwargs):
        self.mode = self.config["portfolio_probe_mode"]
        if self.mode not in MODES or self.config["dry_run"] is not True:
            raise ValueError("synthetic probe only")
        self.trace = []
        self.peak = 1000.
        self.halted = False
        self.warned = False

    def populate_indicators(self, dataframe, metadata):
        return dataframe

    def populate_entry_trend(self, dataframe, metadata):
        pair = metadata["pair"]
        # The engine shifts a signal by one hourly candle. The vector is known
        # from the preceding closed daily decision, including next-hour flips.
        targets = dataframe.date.map(lambda d: sum(f.get(pair, 0) for f in desired_families(d.to_pydatetime()+timedelta(hours=1), self.config["portfolio_probe_mode"])[0]))
        dataframe["enter_long"] = (targets > 0).astype(int)
        dataframe["enter_short"] = (targets < 0).astype(int)
        return dataframe

    def populate_exit_trend(self, dataframe, metadata):
        dataframe["exit_long"] = 0; dataframe["exit_short"] = 0
        return dataframe

    def _snapshot(self, current_time):
        trades = Trade.get_trades_proxy()
        fills = [{"pair": t.pair, "side": o.ft_order_side, "amount": o.safe_filled, "price": o.safe_price}
                 for t in trades for o in t.orders if o.safe_filled > 0 and o.order_filled_utc <= current_time]
        marks = {p: synthetic_mark(p, current_time-timedelta(hours=1), self.mode) for p in PAIRS}
        result = fill_equity(fills, marks, funding=sum(t.funding_fees or 0 for t in trades))
        eq = float(result["equity"])
        self.peak = max(self.peak, eq)
        dd = (self.peak-eq)/self.peak
        self.warned |= dd >= .1
        self.halted |= dd >= .15
        families, mult = desired_families(current_time, self.mode)
        if self.halted: mult = 0.
        elif self.warned: mult *= .5
        targets = capped_targets(families, PRICES, eq, mult)
        return eq, targets, result

    def bot_loop_start(self, current_time, **kwargs):
        eq, targets, result = self._snapshot(current_time)
        self.trace.append({"time": current_time.isoformat(), "equity": eq,
                           "wallet_total": self.wallets.get_total("USDT"),
                           "free": self.wallets.get_free("USDT"), "halted": self.halted,
                           "targets": {p: float(q) for p, q in targets.items()},
                           "inventory": {p: float(q) for p, q in result["inventory"].items()}})

    def _target(self, pair, current_time):
        _, targets, _ = self._snapshot(current_time)
        return float(executable_quantity(targets[pair], PRICES[pair], step="0.001", min_qty="0.001",
                     min_notional="50" if pair == PAIRS[0] else "20", max_qty="120" if pair == PAIRS[0] else "2000"))

    def custom_stake_amount(self, pair, current_time, current_rate, proposed_stake, min_stake, max_stake, leverage, entry_tag, side, **kwargs):
        # Also enforce the native padded minimum, so native cannot raise it.
        q = self._target(pair, current_time)
        if (q > 0) != (side == "long") or self.halted: return 0.
        desired = min(abs(q)*current_rate, max_stake)
        if desired < (min_stake or 0):
            self.trace.append({"time": current_time.isoformat(), "pair": pair, "skip_small": desired, "native_min": min_stake})
            return 0.
        return desired

    def confirm_trade_entry(self, pair, order_type, amount, rate, time_in_force, current_time, entry_tag, side, **kwargs):
        desired = abs(self._target(pair, current_time))
        existing = sum(t.amount for t in Trade.get_trades_proxy(pair=pair, is_open=True))
        return amount+existing <= desired+1e-9

    def custom_exit(self, pair, trade, current_time, current_rate, current_profit, **kwargs):
        q = self._target(pair, current_time)
        if q == 0 or (q < 0) != trade.is_short:
            return "portfolio_target_close"
        return None

    def adjust_trade_position(self, trade, current_time, current_rate, current_profit, min_stake, max_stake, **kwargs):
        q = self._target(trade.pair, current_time)
        if q == 0 or (q < 0) != trade.is_short: return None
        change = abs(q)-trade.amount
        if abs(change) < .001: return None
        if change < 0:
            # Native API consumes stake units at entry basis for reductions.
            return change/trade.amount*trade.stake_amount, "target_reduce"
        stake = change*current_rate
        if stake < (min_stake or 0) or stake > max_stake: return None
        return stake, "target_increase"

    def leverage(self, **kwargs):
        return 1.
