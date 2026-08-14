# Method

What this system is allowed to trade, how it decides, what it must be charged,
and the bar a configuration has to clear before it trades real money. Every
number here was measured against the live Deriv endpoint rather than assumed, and
each has a script that reproduces it.

## The failure this method exists to avoid

The first live configuration traded R_50 synthetics on a swing thesis: a stop
about one daily ATR beyond the six-hour swing, a target at twice that. It won one
of thirteen trades. The post-mortem found the losses were not mainly wrong-way
calls — most trades opened with the prevailing trend and simply never travelled.

Two causes, both structural rather than bad luck:

1. **The instrument could not hold the stop.** R_50's daily ATR is about 4.1% of
   price. The lowest multiplier Deriv offers on it is x80, which liquidates at
   1.25%. A one-ATR stop needed x20 or lower, which does not exist. The thesis
   asked for room the contract could never give, so positions died at a third of
   the planned distance. `scripts/instrument_fit.py` measures this.
2. **The journal and the contract disagreed.** The journal recorded ATR-width
   stops in price terms while the live contract used a fixed dollar amount
   roughly half as wide. The strategy being measured was not the strategy being
   traded.

Both faults are now checks that run before a trade, not conclusions drawn after
one. The lesson generalises: **a chart level means nothing until the contract can
encode it.**

## Instruments

Forex majors only: `frxEURUSD`, `frxGBPUSD`, `frxUSDJPY`, `frxAUDUSD`,
`frxUSDCAD`.

Deriv offers multipliers of 100, 200, 300, 500 and 800 on forex. x100 gives the
most room — liquidation at 1.00% of price — and is the only value that holds a
one-ATR daily stop:

| Instrument | Daily ATR | Room at lowest multiplier | Fits? |
|---|---|---|---|
| frxEURUSD | 0.43% | 1.00% (x100) | yes, 2.4x headroom |
| frxGBPUSD | 0.48% | 1.00% (x100) | yes, 2.1x |
| frxUSDJPY | 0.70% | 1.00% (x100) | yes, 1.4x |
| frxAUDUSD | 0.59% | 1.00% (x100) | yes, 1.7x |
| frxUSDCAD | 0.39% | 1.00% (x100) | yes, 2.6x |
| frxXAUUSD | 2.15% | 1.00% (x100) | **no** — would need x37 |
| R_50 | 4.09% | 1.25% (x80) | **no** — would need x20 |

Gold and the synthetics are excluded for the same reason, not by preference.
Before adding any instrument, run `scripts/instrument_fit.py`; if the stop does
not fit with the safety margin, the instrument is not tradable here.

USDJPY has the thinnest headroom of the five. If its volatility expands, it is
the first to become unencodable, and the gate will say so rather than shrink the
stop.

## Costs that must always be charged

Deriv's contract is not `stake x multiplier x move`. Measured from proposals,
which quote the trigger price for any dollar limit:

```
net P/L = 0.97 x stake x multiplier x (move / entry) - cost
cost    = 0.088% of gross notional
```

Three consequences, each of which flattered earlier results:

- **Only ~97% of the position earns the move.** The remaining 3% is the venue's.
- **Real cost is about 0.088% of notional, four times the ~0.02% commission the
  proposal quotes.** The rest is spread. On a 0.42% stop, cost is roughly 21% of
  the amount risked per trade, so a strategy must clear about 0.2R per trade
  before it breaks even.
- **Liquidation arrives sooner than `1 / multiplier`.** Cost comes out of the
  same stake, so a x100 contract stops out at 0.94%, not 1.00%.

`ContractSpec` in `backtest/replay.py` carries these as defaults. A backtest that
charges less than this is reporting an edge the account will not see. Cost also
cannot be avoided by holding longer: it is charged per position, so fewer, larger
trades pay less of it than many small ones.

## Barriers must land where the chart says

Deriv's `limit_order` takes dollar amounts, and those amounts are net of cost.
Converting a chart distance with plain arithmetic therefore misplaces both
barriers, and both errors work against the position. Measured live on frxEURUSD:

| | intended | plain arithmetic | calibrated |
|---|---|---|---|
| stop | 1.15294 | 1.15381 (8.7 pips early, 18% of the distance) | 1.15297 (0.6 pips) |
| target | 1.16521 | 1.16647 (12.6 pips further, 17% harder) | 1.16515 (1.6 pips) |

A stop 18% tighter and a target 17% further away raises the stop-out rate and
lowers the win rate against everything the backtest assumed — the same class of
error as the original failure, smaller in size.

The fix is not a formula but a measurement. `calibrate_contract` sends two
proposals, reads the trigger price the venue quotes for each, and fits
`usd = notional x pct ± cost`. `barriers_from_risk` then inverts it, so a chart
level becomes the dollar limit that actually fires there. The fit is validated by
predicting a third point it was not given, and a target in the opposite
direction, to within a cent. If the fit looks implausible the engine falls back
to plain arithmetic and says so, rather than trading a number it does not trust.

## Trading rules

- **Direction** comes from a volatility-normalised EWMA crossover, averaged over
  three speeds (8/32, 16/64, 32/128 bars). Dividing by ATR is what makes the
  reading comparable across instruments and across calm and violent weeks.
  Forecasts are capped at ±2 so one violent move cannot dominate, and anything
  inside ±0.5 is treated as no signal rather than a weak one.
- **Stop** is one daily ATR, sized on the horizon the trade is held over, not on
  the bar size the trend is read on. A 4h ATR is roughly a fifth of a daily ATR;
  sizing a swing stop from it puts the stop inside a single day's noise.
- **Target** is 1.5x the stop distance. Earlier work asked for 2x and price
  almost never got halfway there.
- **Unencodable stops are refused, never shrunk.** `REJECT_UNENCODABLE_STOP`
  stays on. Trading a tighter stop than the thesis called for is what produced
  the original record.
- **No trading when the market is shut.** Forex closes Friday 20:55 to Sunday
  21:05 UTC. The last price before the break is stale, and a quiet feed is not a
  broken one.
- **Flat before the weekend.** A stop is a dollar limit, not a guaranteed exit
  price, and Monday's open can gap straight through it. Positions close 20
  minutes before Friday's close, swing trades included, because a gap does not
  care how a position was labelled.
- **One position at a time** (`MAX_OPEN_POSITIONS`), so results measure the
  method rather than the accident of how many trades overlapped.

## The bar for going live

From `backtest/acceptance.py`. All must hold, per strategy:

- at least 200 resolved replay trades
- expectancy per trade above zero after the costs above
- expectancy at least two standard errors above zero (`t >= 2`), so it is an edge
  rather than a lucky sample
- worst losing run inside the daily drawdown limit at the intended stake
- every stop encodable inside the contract's room

Two further disciplines matter as much as the thresholds:

- **A backtest that has been retried many times needs a higher bar than one.**
  Testing enough variants guarantees one looks good. Trials must be counted, and
  the more configurations tried, the larger the t-statistic required.
- **Live results are compared against the replay's expectancy, not just against
  zero.** `scripts/acceptance_check.py --drift` does this. A live result far
  below its own backtest means the model is wrong, whether or not the account is
  up.

Nothing here promises a profit in any given window, and no rule in this document
guarantees a winning trade in the next eight hours. A configuration that fails
the bar is revised or dropped. It is not deployed at a larger stake.

## Current status

Phase 1 is complete: the engine points at real forex, the API schema and
multiplier questions are settled, market hours and weekend risk are handled,
barriers are calibrated against the venue, and the demo path has been exercised
end to end with a verified round trip.

What has **not** been established is that any strategy here makes money. The
5-minute configurations were measured as unprofitable on both synthetics and real
forex. The trend method above is implemented and drawn but not yet validated
against the bar, and validating it properly needs more history than Deriv's API
serves. Until it clears the bar, `scripts/daily_brief.py` output is a description
of the market, not a recommendation.

## Reproducing the numbers

```bash
python scripts/instrument_fit.py      # volatility vs contract room, per symbol
python scripts/demo_readiness.py      # auth, demo, candles, multipliers, quotes
python scripts/demo_roundtrip.py      # place, verify barriers, close
python scripts/daily_brief.py         # trend read and charts into reports/
python scripts/replay_report.py       # expectancy by strategy and exit policy
python scripts/acceptance_check.py    # does a configuration clear the bar
```

## Sources

The construction here follows standard systematic-trading practice rather than
anything invented for this repository:

- Robert Carver, *Systematic Trading* — volatility-normalised forecasts, forecast
  capping, position sizing from risk rather than from capital, and the argument
  that a small number of well-understood rules beats many fitted ones.
- Andreas Clenow, *Following the Trend* — multi-speed trend following on futures,
  and why most individual trades lose while the aggregate can still pay.
- Marcos López de Prado, *Advances in Financial Machine Learning* — multiple
  testing and the deflated Sharpe ratio: the reason a good backtest found after
  many attempts is weak evidence.
- Perry Kaufman, *Trading Systems and Methods* — ATR-based stop placement and the
  effect of costs on short-horizon systems.
