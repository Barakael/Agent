# Cursor Automation — Daily Trading Plan (hardened after #220)

Cursor Automation owns **news + chart confluence** and the daily plan.
The VPS bot **only times entries / exits** (risk, RR, session, ATR pullback hygiene).

**Hard rule:** news thesis and chart structure must **ALIGN** before any BUY/SELL.
If they disagree → stand-aside (`max_trades_today: 0`). Never trade on headlines alone.

Laravel cron may log a brief and post stand-aside if Cursor is missing — it must **never** invent buy/sell.

## Who does what

| Actor | Role |
|-------|------|
| Cursor Automation | News + charts → ALIGN gate → bias, pairs, setups, day extent, review |
| Market brief (VPS) | Live facts: HTF proxies, ATR location, chase flags, headlines, calendar |
| Laravel cron | Log; stand-aside only if Cursor missing (Mon–Fri only) |
| Trading engine | Execute approved setups only (timing/risk) |

## Book-lite chart rules (not full textbook clones)

| Idea | Encoded as |
|------|------------|
| Elder triple screen | HTF (~1h/4h) bias must agree before LTF entry |
| Murphy / classic TA | RSI extremes, MACD side, no blind buys into resistance |
| Price action location | Swings + ATR distance; anti-chase |
| News + technical confluence | `analysis.checklist.news_chart_aligned` |

## ALIGN gate (mandatory)

All must be true for each traded pair:

1. Clear news currency lean + calendar not blocking
2. HTF structure agrees with that lean on the pair
3. Not chasing (`chase_long_risk` / `chase_short_risk` false for direction)
4. RSI not extreme against the trade
5. Entry style matches brief (`pullback_ok_*` / suggested style)

Machine-enforced: schema rejects `cursor_execute` bias plans when checklist flags are missing or false.

## Endpoints

| Method | Path | Auth |
|--------|------|------|
| GET | `/api/webhooks/trading/daily-context` | HMAC |
| POST | `/api/webhooks/trading/daily-plan` | HMAC |

Signature: `X-Wayda-Signature: sha256=<hex>` = HMAC of raw body (POST) or `GET|/api/webhooks/trading/daily-context` (GET).

## Market brief — what Cursor must read

Per pair: price, RSI, MACD, ema21, atr, swings, **htf_1h / htf_4h**, `dist_*_atr`, `chase_long_risk`, `chase_short_risk`, `pullback_ok_long/short`, `decision_gates`.

Top-level: `currency_board`, `event_risk_next_hours`, `cursor_instructions`, headlines, calendar.

Allowlist (1–3): `frxEURUSD`, `frxGBPUSD`, `frxUSDJPY`, `frxAUDUSD`, `frxUSDCAD`

## Required plan (aligned execute)

```json
{
  "date": "2026-08-20",
  "trade_mode": "bias",
  "directional_bias": "buy",
  "hold_policy": "swing",
  "pairs": ["frxEURUSD"],
  "sl_pips": 20,
  "tp_pips": 40,
  "risk_percent": 1.5,
  "max_stake_usd": 25,
  "confidence": 70,
  "execution_mode": "cursor_execute",
  "max_trades_today": 1,
  "entry_style": "pullback",
  "source": "cursor-automation",
  "review": "NEWS: USD soft. CHART: EURUSD htf_1h bullish, chase_long_risk false, pullback_ok. ALIGNED. Prefer EURUSD only; skip GBPUSD (RSI elevated / chase).",
  "analysis": {
    "news_thesis": "USD soft after Treasury buybacks",
    "structure_bias": "bullish_eurusd",
    "currency_board": {"USD": "weak", "EUR": "firm", "GBP": "mixed"},
    "invalidation": "EURUSD closes below EMA21 / swing low",
    "prefer_symbol_order": ["frxEURUSD"],
    "checklist": {
      "news_chart_aligned": true,
      "structure_aligned": true,
      "not_chasing": true,
      "rsi_ok": true,
      "event_ok": true
    }
  },
  "setups": [
    {
      "symbol": "frxEURUSD",
      "direction": "buy",
      "entry_style": "pullback",
      "priority": 1,
      "sl_pips": 20,
      "tp_pips": 40,
      "rationale": "News USD soft + HTF bullish + not chasing"
    }
  ]
}
```

### Stand-aside (misaligned — like #220)

```json
{
  "date": "2026-08-20",
  "trade_mode": "pattern",
  "directional_bias": "neutral",
  "pairs": ["frxEURUSD"],
  "max_trades_today": 0,
  "execution_mode": "cursor_execute",
  "source": "cursor-automation",
  "review": "Stand aside — news USD soft but GBPUSD charts bearish/RSI elevated near swing high (news_chart_aligned=false).",
  "analysis": {
    "news_thesis": "USD soft",
    "structure_bias": "conflict_gbpusd",
    "checklist": {
      "news_chart_aligned": false,
      "structure_aligned": false,
      "not_chasing": false,
      "rsi_ok": false,
      "event_ok": true
    }
  }
}
```

## Automation schedule + prompt

**Triggers (UTC, Monday–Friday only):** `06:30`, `12:00`, `16:00`.

FX is closed Fri 20:55–Sun 21:05 UTC. Do **not** schedule weekend runs. Each weekday run is a fresh decision — re-read the brief and update or replace the daily plan.

Laravel fallback cron (stand-aside only if Cursor missing) also runs weekdays at `06:50`, `12:00`, `16:00` UTC.

1. GET `daily-context`; read `market_brief` first.
2. Build news lean + currency board.
3. For each candidate pair, require ALIGN (structure + not chasing + rsi_ok).
4. If none align → stand-aside. Do not invent a buy.
5. POST plan with `analysis.checklist` all true for execute plans.
6. Prefer `tp_pips` ≈ 1.5–2× `sl_pips` (schema allows `tp >= sl`; bot prefers ≥ 1.5R).
7. Bot only times ATR pullback / anti-chase; does not re-decide direction.

### Prompt appendix (copy into Cursor Automation)

```
You are the sole market decision-maker for Wayda FX majors (demo/live bot on VPS).

Hard rule: news AND charts must ALIGN or you stand aside (max_trades_today=0). Never invent a buy from headlines alone. Never buy into chase_long_risk or elevated RSI against a long; never sell into chase_short_risk.

Schedule context: you run three times per UTC weekday — 06:30, 12:00, 16:00 — Monday through Friday only. FX is closed Fri 20:55–Sun 21:05 UTC. Do not post a trading plan on weekends. Each run is a fresh decision — re-read the brief and update or replace the daily plan.

Steps:
1) GET https://wayda.co.tz/api/webhooks/trading/daily-context
   Header: X-Wayda-Signature: sha256=<HMAC_SHA256(AUTOMATION_WEBHOOK_SECRET, "GET|/api/webhooks/trading/daily-context")>
2) Read data.market_brief first: headlines, calendar, currency_board, event_risk_next_hours, and each pair's htf_1h/htf_4h, chase_long_risk/chase_short_risk, pullback_ok_long/short, decision_gates, RSI, ema21, atr, swings. Also honour data.schedule (Mon–Fri only).
3) Build one clear news thesis (who is strong/weak: USD EUR GBP JPY AUD CAD).
4) For each candidate major, require ALIGN: HTF structure agrees with thesis, not chasing, rsi_ok, calendar not blocking. Allowlist only: frxEURUSD, frxGBPUSD, frxUSDJPY, frxAUDUSD, frxUSDCAD (pick 1–3).
5) If none align → stand-aside plan: trade_mode pattern, directional_bias neutral, pairs must still include at least one allowlisted symbol (e.g. frxEURUSD), max_trades_today 0, honest checklist false flags, written review.
6) If aligned → bias plan: trade_mode bias, directional_bias buy|sell, hold_policy swing, execution_mode cursor_execute, source cursor-automation, max_trades_today 1–2 (cap 4), entry_style pullback unless brief says market and not chasing, sl_pips/tp_pips with tp preferably ~1.5–2× sl (tp must be >= sl), setups with priority, analysis.checklist all true, review citing NEWS + CHART + ALIGN.
7) POST https://wayda.co.tz/api/webhooks/trading/daily-plan
   Content-Type application/json
   Header: X-Wayda-Signature: sha256=<HMAC_SHA256(AUTOMATION_WEBHOOK_SECRET, raw_json_body)>
   Body must include date (UTC YYYY-MM-DD), pairs, sl_pips, tp_pips (tp>=sl), risk_percent<=2, max_stake_usd<=50, review, analysis, setups when trading.

Do not place Deriv orders, change live mode, or raise clamps. The VPS bot only times ATR pullback entries and exits.
```

## Bot after plan lands

1. Session 09:00–21:00 UTC
2. `avoid_until_utc`, `max_trades_today`, setup `priority` / `prefer_symbol_order`
3. ATR pullback + anti-chase timing
4. RiskGate + RR ≥ 1.5 → MULTUP/MULTDOWN
