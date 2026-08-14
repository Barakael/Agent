# Wayda Trading Engine

Autonomous Deriv forex bot with RSI/MACD confluence, ATAE analysis gates, and AI agent supervision.

## Deriv API setup (official — per Deriv support)

Deriv updated their API. Old tokens **no longer work**. Follow this path:

### 1. Create developer account + app

1. Sign out of all Deriv accounts first (cleaner setup)
2. Register at [developers.deriv.com](https://developers.deriv.com/) (new email = new developer account)
3. Register a **PAT-type** application → copy **App ID** (UUID) → `DERIV_APP_ID`

### 2. Create API token (Deriv support path)

Per Deriv support (Amy):

> [home.deriv.com/dashboard/profile](https://home.deriv.com/dashboard/profile) → scroll to **API Management** → **Explore Deriv API** → **Dashboard** → **API Tokens** → generate token

On the token form enable:

- **Trade** — buy/sell
- **Account management** — list accounts, OTP WebSocket

Copy the `pat_...` token once → `DERIV_API_TOKEN` in `.env`. Copy the **Application ID** from that **same** registered app → `DERIV_APP_ID`. If REST returns `Invalid application`, the UUID is wrong (often a Client ID from another screen) — open the app that issued the PAT and copy its Application ID again.

Complete any **partner profile** banner on developers.deriv.com — tokens fail with 401 until done.

### 3. Configure `.env`

```env
DERIV_API_TOKEN=pat_your_token_here
DERIV_APP_ID=your-uuid-app-id
DERIV_WS_APP_ID=1089
DERIV_ACCOUNT_ID=          # optional — filled after first successful account list
TRADING_MODE=log_only
```

### 4. Test credentials

```bash
cd trading-engine && source .venv/bin/activate
PYTHONPATH=. python scripts/test_deriv_auth.py
PYTHONPATH=. python scripts/verify_candles.py frxEURUSD
```

---

## How auth works in this engine

Per [Deriv API Overview](https://developers.deriv.com/docs/intro/api-overview):

| Step | API | Our code |
|------|-----|----------|
| List accounts | `GET /trading/v1/options/accounts` | `data/deriv_rest.py` |
| Get WebSocket URL | `POST .../accounts/{id}/otp` | `deriv_ws._authorize_via_otp()` |
| Stream prices / candles | WebSocket `ticks`, `ticks_history` | `deriv_ws.py` |
| Monitor positions | WebSocket `portfolio` | `get_open_positions()` |
| Trade | WebSocket `proposal` + `buy`, `sell` | `execution/orders.py` |
| Fallback (no auth) | Public legacy WS `app_id=1089` | `market_data_only` mode |

**Forex pairs** (`frxEURUSD`, etc.) use the legacy WebSocket protocol on `ws.derivws.com` for candles/ticks. New PAT tokens authenticate via REST OTP first, then fall back to public data if the token is not yet active.

---

## AI agent endpoints (your system)

The AI agent does **not** call Deriv directly. It supervises via **trading-engine** (`:8002`):

| AI tool | Trading engine | Purpose |
|---------|----------------|---------|
| `trading.status` | `GET /status` | Bot state, balance, analysis armed |
| `trading.positions` | `GET /positions` | Open positions |
| `trading.metrics` | `GET /metrics` | Win rate, PnL, drawdown |
| `trading.preflight_summary` | `GET /preflight/latest` | Daily GO/NO-GO |
| `trading.analysis_sources` | `GET /analysis/sources` | Data feed status |
| `trading.pause` / `resume` | `POST /pause`, `/resume` | Halt/resume bot |
| `trading.close_all` | `POST /positions/close-all` | Emergency close |

Laravel proxies these at `http://localhost:8000/api/trading/*` for the React UI.

---

## Quick start

```bash
cp .env.example .env
# Set DERIV_API_TOKEN, DERIV_APP_ID, TRADING_SERVICE_API_KEY

python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

uvicorn main:app --host 0.0.0.0 --port 8002
curl -X POST http://localhost:8002/start -H "Authorization: Bearer $TRADING_SERVICE_API_KEY"
```

## Modes

| Mode | Behavior |
|------|----------|
| `log_only` | Signals + analysis only (default) |
| `demo` | Real Deriv demo orders (after preflight passes) |
| `live` | Real money (not recommended until demo validated) |

## Measuring before deploying

The engine trades Deriv multiplier contracts, which are liquidated once price
moves `1 / multiplier` against the position. A chart stop wider than that room
cannot be encoded, so it must be rejected rather than quietly tightened. At
multiplier 80 the room is 1.25%; at 30 it is 3.33%.

Replay is the only place a configuration earns the right to run:

```bash
# Pull history once (needs DERIV_API_TOKEN), then compare barriers and exits
python scripts/replay_report.py --days 30 --json replay.json

# Re-run offline against the cached history
python scripts/replay_report.py --offline --days 30 --json replay.json

# Check the result against the promotion criteria
python scripts/acceptance_check.py --report replay.json
```

`replay_report.py` scores every barrier mode and exit policy on an identical
entry list, so the comparison reflects the rule rather than the sample each rule
happened to produce. Two columns matter most:

- `encod%` — share of stops that fit inside the contract's room.
- `exp` — expectancy per resolved trade. Positions still open when the data ends
  are counted under `open`, not marked to the final close.
- `t` and `ci95` — how many standard errors the expectancy sits above zero, and
  its 95% confidence interval. A positive `exp` with `t` below 2 is a lucky
  sample, not an edge; `sig` says so directly.
- `needs` — engine capability the exit policy would require. The bot sends one
  static stop and target at open, so a policy needing `contract_update` or
  `partial_close` cannot be deployed today no matter how well it scores.

Commission defaults to 0.02% of notional, which is what Deriv charges to open a
multiplier position. It is small per trade ($0.60 at stake 100 × multiplier 30)
but it is the entire result when a strategy has no edge, so it is never omitted.

### Promotion criteria

A configuration is promoted to the demo journal only when every strategy clears:

| Criterion | Bar |
|-----------|-----|
| Sample size | ≥ 200 resolved replay trades |
| Expectancy | above zero per trade |
| Significance | ≥ 2 standard errors above zero |
| Worst losing run | inside `DAILY_DRAWDOWN_LIMIT_PERCENT` at the configured stake |
| Stops | 100% encodable inside the contract's room |

A failing configuration is revised or dropped. Stake and frequency are never
raised to make a losing configuration look profitable, and no criterion promises
a win in any window — including an eight-hour one.

After promotion, start a clean journal and watch for drift:

```bash
python scripts/acceptance_check.py --reset-journal        # archives the old db
python scripts/acceptance_check.py --report replay.json --drift
```

If live expectancy diverges materially from replay, stop the run and re-measure.
The replay is not re-fitted to match the live result.

### Measured result on the volatility indices

Run against 60 days of real 5-minute history for R_10, R_25, R_50, R_75 and
R_100 (17,280 bars each, 100% coverage), across both barrier modes, multipliers
30 and 80, and all six exit policies. Roughly 2,000 resolved trades per
configuration. **No configuration produced a positive expectancy.** The best was
−$0.37 per trade; the chart-matched runs clustered between −$0.37 and −$1.34,
which is the commission and nothing else.

The reason is a property of the instruments, not of the strategy:

| Test | Result | Meaning |
|------|--------|---------|
| Realized annualized volatility | 10.00, 25.12, 49.96, 74.72, 99.96% | Exactly the nameplate — generated, not discovered |
| Drift per bar | t between 0.09 and 1.53 | No directional bias to capture |
| Autocorrelation, lags 1–5 | all inside ±0.0149 | No momentum and no mean reversion |
| Variance ratio, k = 2…96 | 0.93 to 1.07 | A random walk from 10 minutes to 8 hours |

These series are driftless geometric Brownian motion with constant volatility,
so price is a martingale. Any rule that decides when to enter and exit using
past prices has an expected value of exactly zero before costs and exactly minus
the commission after. That is a theorem, not a tuning problem: no pattern gate,
exit policy, multiplier, or stop placement can produce a positive expectancy
here, and a backtest that appears to is measuring its own luck or a bug.

An earlier R_50-only run did produce +$4.96 per trade. It was noise: it needed
`contract_update`, which the engine does not implement, and it fell to −$1.52
once the sample grew from 399 to 1,788 trades. The `t` column and the `needs`
column both exist to catch that class of mistake before it reaches an account.

Positive expectancy requires an instrument with real structure — order flow,
participants, a supply and demand imbalance to lean on. The synthetics have none
by construction.

### Measured result on real instruments

The same battery was run on eight instruments Deriv also offers as multipliers:
`frxEURUSD`, `frxGBPUSD`, `frxUSDJPY`, `frxXAUUSD`, `OTC_SPC`, `OTC_NDX`,
`OTC_GDAXI`, `OTC_N225` — roughly 12,000 five-minute bars each. Returns spanning
a weekend or overnight gap were excluded, because a gap injects a fake "one bar"
move that inflates both autocorrelation and the variance ratio.

`frxUSDJPY` looked promising at first: lag-3 autocorrelation of +0.067 against a
±0.018 band, with variance ratios above 1 to match. It did not survive a
split-half check — the first half is −0.003 and the second is +0.087, so the
whole signal lives in one stretch of the sample. No other instrument showed
structure that held in both halves either.

At 5-minute resolution, none of these instruments offers this style of bot a
persistent edge. Note also that 24 tests were run (8 symbols × 3 lags), which
alone produces about one spurious hit at the 5% level, so any single significant
lag needs the split-half check before it means anything.

The practical consequence: raising stake, adding symbols, or trying more exit
policies cannot fix a zero edge, and searching more configurations makes a false
positive more likely, not less. Use the harness to reject ideas cheaply; an edge,
if one exists, has to come from information this bot does not currently use.

### Why longer horizons cannot be validated on Deriv data alone

Daily-horizon trend following is the obvious next idea, since time-series
momentum has decades of published out-of-sample support. It cannot be tested
here, for two independent reasons.

**The API serves about one year of daily history.** All sixteen forex, metal and
index symbols return 244–261 daily bars, roughly 12.4 months. A 12-month-lookback
signal with a 1-month holding period therefore yields *zero* usable
signal-and-outcome pairs. Pooling does not rescue it: mean pairwise correlation
of daily returns is 0.15 with a maximum of 0.93, giving about 4.9 effectively
independent instruments out of 16.

**The power arithmetic is unforgiving.** Confirming a strategy at t = 2 needs
roughly `(2 / Sharpe)²` years of data:

| True Sharpe | Years needed | t-stat after 1 year |
|-------------|--------------|---------------------|
| 0.3 | 44 | 0.30 |
| 0.4 | 25 | 0.40 |
| 0.5 | 16 | 0.50 |
| 1.0 | 4 | 1.00 |

Published time-series momentum runs a Sharpe near 0.3–0.5, so validating it needs
16–44 years. With one year, a real edge is indistinguishable from nothing — and
any positive result found in that year is the noise trap again.

**Holding cost compounds the problem.** Multipliers are charged swap nightly, in
both directions on derived indices. The one-off 0.02% commission is minor next to
20-plus nights of swap on a monthly holding period, so a long-horizon design must
budget carrying cost as its dominant expense, not its smallest.

The only sound sequence is to validate on decades of history from an external
source first, and use Deriv purely for execution once something survives.

## Easier alternatives?

If Deriv setup remains blocked, consider:

| Platform | Pros | Cons |
|----------|------|------|
| **OANDA** | Clean REST forex API, free practice account | Different from Deriv |
| **Alpaca** | Excellent API docs, paper trading | US stocks, not forex |
| **Deriv (stay)** | You already have demo account, our bot built | New API migration pain |

Staying on Deriv is viable once the token is active — our engine now supports the official OTP flow.

---

## Daily plan + Cursor Automations

See **[docs/CURSOR_TRADING_AUTOMATION.md](../docs/CURSOR_TRADING_AUTOMATION.md)** for:

- HMAC webhook endpoints (`/api/webhooks/trading/daily-plan`)
- Plan JSON schema and clamps
- Example signed `curl`
- Cursor Automation prompt contract

Engine endpoints (internal Bearer `TRADING_SERVICE_API_KEY`):

- `GET /plan/active`
- `PUT /plan/active`
