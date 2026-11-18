"""cbBTC minute-bar strategy bot for agent-fun/bars-replay/v1.

Long-only trend follower with a volatility gate:
  * three incremental EMAs (20, 360, 240) over the closes seen so far
  * 60-bar return in bps and 60-bar population stdev in bps
  * entry when trend and momentum agree and the tape is quiet
  * exit on a stdev-scaled trailing stop, a hard stop, or a trend break

The harness runs this file as ``python3 -P -s /bot/main.py``, so it has to
trust nothing about sys.path and add its own vendor/ directory first.
"""

import os
import sys

_VENDOR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor")
if _VENDOR not in sys.path:
    sys.path.insert(0, _VENDOR)

import makefun_bars  # noqa: E402  (after the sys.path fix, on purpose)

SYMBOL = "CBBTC"

# --- strategy parameters ----------------------------------------------------
EMA_FAST_N = 20
EMA_SLOW_N = 360
EMA_TREND_N = 240

RET_WINDOW = 60          # bars used for the momentum return
VOL_WINDOW = 60          # bars used for the volatility estimate
MIN_HISTORY = 420        # no entries before this many closes

ENTRY_RETURN_BPS = 60.0  # 60-bar return must exceed this
ENTRY_VOL_BPS = 80.0     # and volatility must stay at or under this
TRAIL_SIGMA = 2.5        # trailing stop distance, in sigmas
HARD_STOP_BPS = 130.0    # hard stop below the entry close
BUY_SLIPPAGE_BPS = 120
SELL_SLIPPAGE_BPS = 120
CASH_FRACTION = 0.995    # keep a sliver back so the fill always clears
MIN_NOTIONAL_MULT = 2    # only enter if size >= twice the venue minimum

# --- round-trip cost model --------------------------------------------------
# What one complete trade pays, in bps of notional:
#   fees      4 bps on each fill (entry + exit)           = 8 bps
#   slippage  2 bps per side, the tolerance we hand in    = 4 bps
#   impact    ~10-15 bps at a ~1,000 USDC order against
#             the dev window's 700k-1M USDC depths        = ~14 bps
#   total     ~26 bps of notional paid to go in and out.
# The 60 bps entry threshold sits well above that ~26 bps so a trade must
# clear its own cost by more than a 2x margin before it is taken.

BPS = 10_000.0


class Strategy:
    """Stateful per-run strategy: price history, EMAs, and the open trade."""

    def __init__(self):
        self.closes = []
        self.ema_fast = None
        self.ema_slow = None
        self.ema_trend = None
        self.entry_price = None
        self.peak_price = None

    # -- indicator bookkeeping ----------------------------------------------

    def _seed_or_update(self, current, close, n):
        if current is None:
            return float(close)
        alpha = 2.0 / (n + 1.0)
        return current + alpha * (float(close) - current)

    def _push(self, close):
        self.closes.append(close)
        self.ema_fast = self._seed_or_update(self.ema_fast, close, EMA_FAST_N)
        self.ema_slow = self._seed_or_update(self.ema_slow, close, EMA_SLOW_N)
        self.ema_trend = self._seed_or_update(self.ema_trend, close, EMA_TREND_N)

    # -- measurements --------------------------------------------------------

    def _return_bps(self):
        window = self.closes[-(RET_WINDOW + 1):]
        base = window[0]
        if base <= 0:
            return 0.0
        return (float(self.closes[-1]) - float(base)) / float(base) * BPS

    def _sigma_bps(self):
        sample = self.closes[-VOL_WINDOW:]
        count = len(sample)
        if count == 0:
            return 0.0
        mean = sum(float(x) for x in sample) / float(count)
        if mean <= 0:
            return 0.0
        variance = sum((float(x) - mean) ** 2 for x in sample) / float(count)
        return variance ** 0.5 / mean * BPS

    # -- the callbacks -------------------------------------------------------

    def on_batch(self, state, batch):
        bar = None
        for candidate in batch.get("bars", ()):
            if candidate.get("symbol") == SYMBOL:
                bar = candidate
                break
        if bar is None:
            return []

        close = int(bar["c"])
        self._push(close)

        if state.warming_up:
            return []

        if len(self.closes) < MIN_HISTORY:
            return []

        sigma_bps = self._sigma_bps()
        holding = state.positions.get(SYMBOL)

        if holding is not None and int(holding.qty) > 0:
            return self._manage_exit(state, close, sigma_bps, holding)

        # Flat: the trade is over, forget the old reference prices.
        self.entry_price = None
        self.peak_price = None
        return self._consider_entry(state, close, sigma_bps)

    def _consider_entry(self, state, close, sigma_bps):
        if self.ema_fast <= self.ema_slow:
            return []
        if self._return_bps() <= ENTRY_RETURN_BPS:
            return []
        if sigma_bps > ENTRY_VOL_BPS:
            return []

        min_notional = int(state.hello["fees"]["min_notional_quote_units"])
        budget = min(int(state.weight_room(SYMBOL)), int(state.cash * CASH_FRACTION))
        if budget <= 0:
            return []
        if budget < MIN_NOTIONAL_MULT * min_notional:
            return []

        self.entry_price = close
        self.peak_price = close
        return [{
            "side": "buy",
            "symbol": SYMBOL,
            "notional_quote_units": budget,
            "max_slippage_bps": BUY_SLIPPAGE_BPS,
        }]

    def _manage_exit(self, state, close, sigma_bps, holding):
        if self.entry_price is None:
            self.entry_price = close
        if self.peak_price is None or close > self.peak_price:
            self.peak_price = close

        trail_level = self.peak_price * (1.0 - TRAIL_SIGMA * sigma_bps / BPS)
        stop_level = self.entry_price * (1.0 - HARD_STOP_BPS / BPS)

        hit_trail = float(close) < trail_level
        hit_stop = float(close) < stop_level
        hit_trend = self.ema_fast < self.ema_trend

        if not (hit_trail or hit_stop or hit_trend):
            return []

        self.entry_price = None
        self.peak_price = None
        return [{
            "side": "sell",
            "symbol": SYMBOL,
            "qty": int(holding.qty),
            "max_slippage_bps": SELL_SLIPPAGE_BPS,
        }]


def main():
    strategy = Strategy()

    def on_batch(state, batch):
        return strategy.on_batch(state, batch)

    makefun_bars.run(on_batch)


if __name__ == "__main__":
    main()
