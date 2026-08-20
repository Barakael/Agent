# Cursor Automation — Daily Trading Plan

Cursor Automation owns **news + chart review + when/how far to trade**.
The VPS bot **only executes** MULTUP/MULTDOWN (risk, RR, session, stake caps).

Laravel cron `trading:daily-analysis` may log a brief and post **stand-aside**
(`awaiting_cursor_plan`) if no Cursor plan exists — it must **never** invent buy/sell.

## Who does what

| Actor | Role |
|-------|------|
| Cursor Automation | News + calendar + chart levels → full daily plan (bias, pairs, setups, SL/TP, max trades, avoid window, written review) |
| Laravel cron | Log brief; stand-aside only if Cursor missing |
| Trading engine | Execute Cursor setups; no local chart re-decision |

## Prerequisites

1. Public HTTPS Laravel API: `https://wayda.co.tz`
2. `AUTOMATION_WEBHOOK_SECRET` in `backend/.env`
3. Trading-engine reachable from Laravel with `TRADING_SERVICE_URL` + `TRADING_SERVICE_API_KEY`
4. Engine rejects opens unless `active_plan.source` starts with `cursor`

## Endpoints

| Method | Path | Auth |
|--------|------|------|
| GET | `/api/webhooks/trading/daily-context` | HMAC `X-Wayda-Signature` |
| POST | `/api/webhooks/trading/daily-plan` | HMAC `X-Wayda-Signature` |

Signature: `X-Wayda-Signature: sha256=<hex>` where hex is  
`HMAC_SHA256(secret, raw_body)` for POST, or  
`HMAC_SHA256(secret, "GET|/api/webhooks/trading/daily-context")` for GET.

## Daily context — what Cursor must read

`data.market_brief` includes:

- `pairs` — price, RSI, MACD, **ema21**, **atr**, **swing_high/low**, `dist_ema21_pct`, `suggested_entry_style`
- `calendar` — `upcoming_high_impact`, `next_6h`
- `headlines` — FX/macro RSS
- `cursor_instructions` — execute-only bot model
- `constraints` — clamps + `max_trades_today_cap` (4)

**Allowlisted pairs (1–3):**  
`frxEURUSD`, `frxGBPUSD`, `frxUSDJPY`, `frxAUDUSD`, `frxUSDCAD`

## Required plan — full Cursor execute brief

```json
{
  "date": "2026-08-20",
  "trade_mode": "bias",
  "directional_bias": "buy",
  "hold_policy": "swing",
  "max_hold_days": 1,
  "pairs": ["frxEURUSD", "frxGBPUSD"],
  "sl_pips": 20,
  "tp_pips": 40,
  "risk_percent": 1.5,
  "max_stake_usd": 25,
  "confidence": 72,
  "execution_mode": "cursor_execute",
  "max_trades_today": 2,
  "entry_style": "pullback",
  "avoid_until_utc": null,
  "review": "USD soft on overnight yields; EUR/GBP stronger vs USD. Prefer longs into London. Cap 2 fills. Avoid JPY into BOJ risk.",
  "notes": "USD soft; EURUSD+GBPUSD longs",
  "source": "cursor-automation",
  "setups": [
    {
      "symbol": "frxEURUSD",
      "direction": "buy",
      "entry_style": "pullback",
      "sl_pips": 20,
      "tp_pips": 40,
      "rationale": "Bullish MACD + pullback toward EMA21; USD soft thesis"
    },
    {
      "symbol": "frxGBPUSD",
      "direction": "buy",
      "entry_style": "market",
      "sl_pips": 22,
      "tp_pips": 45,
      "rationale": "Already near support swing; enter on open if session live"
    }
  ]
}
```

### Field rules

| Field | Meaning |
|-------|---------|
| `execution_mode` | `cursor_execute` (default for Cursor) — bot skips 1h chart confirm |
| `max_trades_today` | How far to go today (0–4). `0` = stand-aside |
| `entry_style` | Plan default: `pullback` (wait near EMA21) or `market` |
| `review` | Full written thesis (news + chart levels + day plan) |
| `avoid_until_utc` | ISO time — bot will not open before this (e.g. into CPI) |
| `setups` | Per-pair entry instructions Cursor already decided |

Rules:

- `directional_bias` must be `buy` or `sell` for bias mode.
- Pick **1–3** majors that match the thesis.
- Never recommend `R_*`, gold, or binaries.
- Unclear / conflicting news → stand-aside. Do **not** invent a buy.
- `tp_pips` ≥ `sl_pips`; risk ≤ 2%; max_stake ≤ 50.
- Payload cannot set live mode or raise clamps.

### Stand-aside

```json
{
  "date": "2026-08-20",
  "trade_mode": "pattern",
  "directional_bias": "neutral",
  "hold_policy": "intraday",
  "pairs": ["frxEURUSD"],
  "max_trades_today": 0,
  "execution_mode": "cursor_execute",
  "review": "Stand aside — conflicting USD news ahead of high-impact event",
  "source": "cursor-automation"
}
```

## What the bot does after the plan lands

1. Session window 09:00–21:00 UTC (still enforced).
2. Respects `avoid_until_utc` and `max_trades_today`.
3. For each setup: if `entry_style=pullback`, waits until price is near EMA21; if `market`, enters on next eligible candle.
4. Applies RiskGate + RR ≥ 1.5 + stake caps.
5. Places MULTUP/MULTDOWN — **does not** re-run 24h/6h/1h bias confirmation.

## Cursor Automation schedule + prompt

**Triggers:** daily **06:30 UTC** and **12:00 UTC**.

1. GET `/api/webhooks/trading/daily-context`.
2. Read `market_brief` — headlines, calendar, pair ema21/atr/swings.
3. Write one thesis + day extent (`max_trades_today`).
4. Fill `setups` with direction, style, SL/TP, rationale.
5. Put the full narrative in `review`.
6. POST `/api/webhooks/trading/daily-plan` with `source=cursor-automation`.
7. If no edge → `max_trades_today: 0` stand-aside.
8. Do **not** place orders yourself or raise risk clamps.

## Dashboard

`https://wayda.co.tz` — Trading page shows mode, bias, pairs, hold policy via Sanctum `/api/trading/*`.
