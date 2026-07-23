# Cursor Automation — Daily Trading Plan

Cloud Automations (Cursor Pro) act as a **daily planner**, not a live trader.
The VPS bot keeps Deriv credentials and places orders.

## Prerequisites

1. Public HTTPS Laravel API: `https://wayda.co.tz`
2. `AUTOMATION_WEBHOOK_SECRET` in `backend/.env` (separate from `TRADING_SERVICE_API_KEY`)
3. Trading-engine reachable from Laravel with `TRADING_SERVICE_URL` + `TRADING_SERVICE_API_KEY`
4. Cron writes nightly report: `trading-engine/scripts/demo_daily_report.sh` at ~21:05 UTC

## Endpoints

| Method | Path | Auth |
|--------|------|------|
| GET | `/api/webhooks/trading/daily-context` | HMAC `X-Wayda-Signature` |
| POST | `/api/webhooks/trading/daily-plan` | HMAC `X-Wayda-Signature` |

Signature: `X-Wayda-Signature: sha256=<hex>` where hex is  
`HMAC_SHA256(secret, raw_body)` for POST, or  
`HMAC_SHA256(secret, "GET|/api/webhooks/trading/daily-context")` for GET.

## Plan modes

### Pattern (intraday) — up to 5 strategies

```json
{
  "date": "2026-07-23",
  "trade_mode": "pattern",
  "hold_policy": "intraday",
  "pairs": ["frxAUDUSD"],
  "enabled_strategies": ["macd_rsi", "ema_pullback"],
  "strategy_id": "macd_rsi",
  "sl_pips": 15,
  "tp_pips": 30,
  "risk_percent": 1.5,
  "max_stake_usd": 25,
  "notes": "Prefer AUDUSD; enable strategies that passed 70% gate",
  "source": "cursor-automation"
}
```

Allowlist: `macd_rsi`, `ema_pullback`, `rsi_divergence`, `bollinger_mean_reversion`, `engulfing_htf`.  
Engine arms a pattern strategy only when preflight win rate ≥ 70% (min trades).

### Bias / swing (macro thesis)

```json
{
  "date": "2026-07-23",
  "trade_mode": "bias",
  "directional_bias": "buy",
  "hold_policy": "swing",
  "max_hold_days": 5,
  "pairs": ["frxEURUSD"],
  "sl_pips": 40,
  "tp_pips": 120,
  "risk_percent": 1.5,
  "max_stake_usd": 25,
  "notes": "USD weakness expected after payrolls + Fed tone; prefer EURUSD long pullbacks",
  "source": "cursor-automation"
}
```

Swing positions are **not** force-closed at 21:00 UTC. Payload cannot set live mode.

## Example curl

```bash
SECRET="${AUTOMATION_WEBHOOK_SECRET}"
BASE="https://wayda.co.tz"

PATH_Q="/api/webhooks/trading/daily-context"
SIG=$(printf 'GET|%s' "$PATH_Q" | openssl dgst -sha256 -hmac "$SECRET" | awk '{print $2}')
curl -sS "$BASE$PATH_Q" -H "X-Wayda-Signature: sha256=$SIG" | jq .

BODY='{"date":"2026-07-23","trade_mode":"pattern","pairs":["frxAUDUSD"],"enabled_strategies":["macd_rsi"],"sl_pips":15,"tp_pips":30,"risk_percent":1.5,"max_stake_usd":25,"notes":"Demo","source":"cursor-automation"}'
SIG=$(printf '%s' "$BODY" | openssl dgst -sha256 -hmac "$SECRET" | awk '{print $2}')
curl -sS -X POST "$BASE/api/webhooks/trading/daily-plan" \
  -H "Content-Type: application/json" \
  -H "X-Wayda-Signature: sha256=$SIG" \
  -d "$BODY" | jq .
```

## Cursor Automation prompt

**Trigger:** daily ~22:00 UTC and/or ~06:30 UTC.

1. GET `daily-context` (HMAC).
2. Read `strategy_win_rates` / `armed_strategies` and latest report.
3. Either:
   - **Pattern:** enable up to 5 strategies that passed the 70% gate, or
   - **Bias:** set `trade_mode=bias`, `directional_bias`, swing SL/TP, thesis in `notes`.
4. POST `daily-plan` within clamps.
5. Do **not** request Deriv tokens, place orders, raise risk above clamps, or set live mode.

## Dashboard

`https://wayda.co.tz` serves the React app. Trading page shows mode, bias, enabled strategies, hold policy via Sanctum `/api/trading/*`.
