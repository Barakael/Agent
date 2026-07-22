# Cursor Automation — Daily Trading Plan

Cloud Automations (Cursor Pro) act as a **daily planner**, not a live trader.
The VPS bot keeps Deriv credentials and places orders.

## Prerequisites

1. Public HTTPS Laravel API (e.g. `https://your-domain.com`).
2. `AUTOMATION_WEBHOOK_SECRET` set in `backend/.env` (separate from `TRADING_SERVICE_API_KEY`).
3. Trading-engine reachable from Laravel with `TRADING_SERVICE_URL` + `TRADING_SERVICE_API_KEY`.
4. Cron writes nightly report: `trading-engine/scripts/demo_daily_report.sh` at ~21:05 UTC.

## Endpoints

| Method | Path | Auth |
|--------|------|------|
| GET | `/api/webhooks/trading/daily-context` | HMAC `X-Wayda-Signature` |
| POST | `/api/webhooks/trading/daily-plan` | HMAC `X-Wayda-Signature` |

Signature: `X-Wayda-Signature: sha256=<hex>` where hex is  
`HMAC_SHA256(secret, raw_body)` for POST, or  
`HMAC_SHA256(secret, "GET\|/api/webhooks/trading/daily-context")` for GET (method + full request URI).

## Plan JSON (POST body)

```json
{
  "date": "2026-07-23",
  "pairs": ["frxAUDUSD"],
  "strategy_id": "macd_rsi",
  "sl_pips": 15,
  "tp_pips": 30,
  "risk_percent": 1.5,
  "max_stake_usd": 25,
  "notes": "Favor AUDUSD; avoid chasing JPY",
  "source": "cursor-automation"
}
```

Clamps enforced server-side: pairs allowlist, `strategy_id=macd_rsi`, SL 5–50, TP 10–100, TP≥SL, risk ≤ 2%, stake ≤ $50. Payload cannot set trading mode.

## Example curl

```bash
SECRET="${AUTOMATION_WEBHOOK_SECRET}"
BASE="https://your-domain.com"

# GET context
PATH_Q="/api/webhooks/trading/daily-context"
SIG=$(printf 'GET|%s' "$PATH_Q" | openssl dgst -sha256 -hmac "$SECRET" | awk '{print $2}')
curl -sS "$BASE$PATH_Q" -H "X-Wayda-Signature: sha256=$SIG" | jq .

# POST plan
BODY='{"date":"2026-07-23","pairs":["frxAUDUSD"],"strategy_id":"macd_rsi","sl_pips":15,"tp_pips":30,"risk_percent":1.5,"max_stake_usd":25,"notes":"Demo plan","source":"cursor-automation"}'
SIG=$(printf '%s' "$BODY" | openssl dgst -sha256 -hmac "$SECRET" | awk '{print $2}')
curl -sS -X POST "$BASE/api/webhooks/trading/daily-plan" \
  -H "Content-Type: application/json" \
  -H "X-Wayda-Signature: sha256=$SIG" \
  -d "$BODY" | jq .
```

## Cursor Automation prompt (paste into Automations editor)

**Trigger:** Schedule daily ~22:00 UTC (after report) and/or ~06:30 UTC (before session).

**Instructions:**

1. Call GET `/api/webhooks/trading/daily-context` with HMAC signature.
2. Summarize metrics, preflight, and yesterday’s report in a few bullets.
3. Propose tomorrow’s plan within clamps (prefer pairs that passed backtest).
4. POST `/api/webhooks/trading/daily-plan` with HMAC over the exact JSON body.
5. Do **not** request Deriv tokens, place orders, raise risk above clamps, or set live mode.

## Dashboard

Sanctum routes: `GET /api/trading/plan/active`, `GET /api/trading/reviews`.  
Trading UI shows Active plan + Latest review cards.
