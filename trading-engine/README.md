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

## Easier alternatives?

If Deriv setup remains blocked, consider:

| Platform | Pros | Cons |
|----------|------|------|
| **OANDA** | Clean REST forex API, free practice account | Different from Deriv |
| **Alpaca** | Excellent API docs, paper trading | US stocks, not forex |
| **Deriv (stay)** | You already have demo account, our bot built | New API migration pain |

Staying on Deriv is viable once the token is active — our engine now supports the official OTP flow.
