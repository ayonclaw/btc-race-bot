"""cbBTC minute-bar trading bot: regime-gated momentum with a volatility trail.

The bot is long-only on one symbol and holds cash by default. It buys only when a slow
trend gate says the market is in an up-regime and the last hour's return is large enough
to clear a full round trip's fees, slippage and price impact; it then rides the move with
a trailing stop measured in units of realised per-minute volatility and steps aside as
soon as the trend gate breaks. Every exit condition is a rule on data already received,
so two runs over the same batch stream take byte-identical decisions.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))

import makefun_bars

SYMBOL = "CBBTC"

# Slow trend gate: EMA(20) above EMA(360) means the last six hours trend up.
FAST_EMA = 20
SLOW_EMA = 360
# The trend gate's own exit line: leave once the fast EMA falls under the 4-hour EMA.
EXIT_EMA = 240
# Momentum trigger: the last hour's return, in basis points, that is worth a round trip.
MOM_BARS = 60
MOM_BPS = 60
# Trailing stop: 2.5 units of the 60-bar standard deviation, so it breathes with the tape.
TRAIL_SIGMA = 2.5
VOL_WINDOW = 60
# Refuse new risk when a single minute's volatility explodes past this many basis points.
VOL_EXPLODE_BPS = 80.0
# Hard stop on the open position, from its entry price, in basis points.
HARD_STOP_BPS = 130
# Fraction of cash committed to a buy, leaving room for the fee and any rounding.
CASH_FRACTION = 0.995
# Orders are allowed to fill this far from the close they were decided on; a wider gap is
# not chased. The modelled slippage plus this size's own impact is well inside it.
MAX_SLIPPAGE_BPS = 120


class Strategy:
    """Everything the bot remembers, updated once per minute bar."""

    def __init__(self):
        self.closes = []
        self.fast = None
        self.slow = None
        self.exit_line = None
        self.peak = 0
        self.entry = 0

    def _ema(self, value):
        """Advance the two trend EMAs and the exit line by one close."""
        for name, period in (("fast", FAST_EMA), ("slow", SLOW_EMA), ("exit_line", EXIT_EMA)):
            prev = getattr(self, name)
            if prev is None:
                setattr(self, name, value)
            else:
                weight = 2.0 / (period + 1.0)
                setattr(self, name, value * weight + prev * (1.0 - weight))

    def _sigma_bps(self):
        """Per-minute volatility in basis points over the trailing window."""
        window = self.closes[-VOL_WINDOW:]
        if len(window) < VOL_WINDOW:
            return None
        mean = sum(window) / float(VOL_WINDOW)
        var = sum((x - mean) * (x - mean) for x in window) / float(VOL_WINDOW)
        if mean <= 0:
            return None
        return (var ** 0.5) / mean * 10000.0

    def _momentum_bps(self):
        """The trailing hour's return in basis points, or None before there is an hour."""
        if len(self.closes) <= MOM_BARS:
            return None
        then = self.closes[-MOM_BARS - 1]
        if then <= 0:
            return None
        return (self.closes[-1] - then) / float(then) * 10000.0

    def on_bar(self, state, bar):
        """Fold one new close in. Returns the order list for the next bar, or []."""
        self.closes.append(int(bar["c"]))
        self._ema(int(bar["c"]))
        price = int(bar["c"])
        sigma = self._sigma_bps()
        held = state.positions.get(SYMBOL)

        if held is not None and held.qty > 0:
            if price > self.peak:
                self.peak = price
            stopped = sigma is not None and price < self.peak * (1.0 - TRAIL_SIGMA * sigma / 10000.0)
            lost_too_much = price < self.entry * (1.0 - HARD_STOP_BPS / 10000.0)
            trend_gone = self.fast < self.exit_line
            if stopped or lost_too_much or trend_gone:
                return [{
                    "side": "sell",
                    "symbol": SYMBOL,
                    "qty": held.qty,
                    "max_slippage_bps": MAX_SLIPPAGE_BPS,
                }]
            return []

        momentum = self._momentum_bps()
        if momentum is None or sigma is None:
            return []
        if sigma > VOL_EXPLODE_BPS:
            return []
        if self.fast <= self.slow or momentum <= MOM_BPS:
            return []

        room = state.weight_room(SYMBOL)
        budget = int(min(room, state.cash * CASH_FRACTION))
        minimum = int(state.hello["fees"]["min_notional_quote_units"])
        if budget < minimum * 2:
            return []
        self.peak = price
        self.entry = price
        return [{
            "side": "buy",
            "symbol": SYMBOL,
            "notional_quote_units": budget,
            "max_slippage_bps": MAX_SLIPPAGE_BPS,
        }]


def on_batch(state, batch):
    """Answer one batch: one order list, decided on the bar that just closed."""
    if state.warming_up:
        return []
    for bar in batch["bars"]:
        if bar["symbol"] == SYMBOL:
            return STRATEGY.on_bar(state, bar)
    return []


STRATEGY = Strategy()


if __name__ == "__main__":
    makefun_bars.run(on_batch)
