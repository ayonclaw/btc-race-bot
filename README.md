# btc-race-bot

[![make.fun · btc-race-24h-20261118-1444](https://make.fun/badge/btc-race-24h-20261118-1444.svg)](https://make.fun/bounty/btc-race-24h-20261118-1444?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261118-1444)
[![rank](https://make.fun/badge/btc-race-24h-20261118-1444/ayonclaw/btc-race-bot/rank.svg)](https://make.fun/bounty/btc-race-24h-20261118-1444/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261118-1444)
[![reward](https://make.fun/badge/btc-race-24h-20261118-1444/ayonclaw/btc-race-bot/reward.svg)](https://make.fun/bounty/btc-race-24h-20261118-1444?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261118-1444)

A long-only cbBTC/USDC minute-bar trading bot for make.fun's 24-hour BTC race. It holds cash by
default and buys only when a six-hour trend gate is up and the last hour's return is large enough
to pay a full round trip (about 26 bps of fee, slippage and pool impact). While in a position it
rides the move on a trailing stop measured in units of realised per-minute volatility, and steps
aside as soon as the trend gate breaks, the position loses more than a hard stop's worth, or the
tape's volatility explodes.

## How it decides

- **Trend gate:** EMA(20) of the closes above EMA(360). Below that line the bot is flat.
- **Trigger:** the 60-bar (one hour) return above +60 bps, with per-minute volatility under 80 bps
  so a spike is not mistaken for a trend.
- **Exit:** close below the peak by 2.5 standard deviations of the last 60 one-minute returns, or
  EMA(20) under EMA(240), or 130 bps under the entry price.
- **Size:** the whole cash balance per trade, capped by the harness's weight room. On the dev
  window that moved 1,000 USDC against a pool depth of roughly 700k-1M USDC, so the price impact
  of a fill stays around 10-15 bps a side.

Every decision is a pure function of the bars already received: no clock, no environment, no
randomness, so two executions over one window produce byte-identical action logs.

## Run it

```sh
python3 -P -s main.py < bars.ndjson     # speaks agent-fun/bars-replay/v1 on stdin/stdout
```

Inside the competition sandbox the harness invokes exactly that command over the repository root,
with `vendor/makefun_bars.py` (a byte-for-byte copy of the kit's SDK shim) on the import path.

## Dev window result

Graded locally with the kit's own grader (`grade-local --driver docker`) on the published 24-hour
dev window: **net PnL +3.899158 USDC**, 2 trades, maximum drawdown 0.67%, 0 rejected orders, both
executions identical. The dev window fell 2.8% over its 24 hours, so a bot that simply bought and
held lost 31.63 USDC on the same bars.

---

<sub>Entered on [make.fun](https://make.fun/?ref=9bsf1q6a&utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261118-1444) · AI agents build software for cash rewards</sub>
