"""Live multi-source market brief for Cursor Automations and AI synthesis."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

import pandas as pd

from analysis.engine import PAIR_CURRENCIES
from config import settings
from data.calendar import EconomicCalendar
from data.news_feeds import fetch_headlines
from indicators.macd import compute_macd, detect_bearish_crossover, detect_bullish_crossover
from indicators.rsi import compute_rsi
from risk.session import SessionManager
from signals.engine import SignalEngine
from strategies import PATTERN_STRATEGY_IDS

logger = logging.getLogger(__name__)

# ATR multiples for location / pullback quality (book-lite)
PULLBACK_ATR_MAX = 0.5
CHASE_SWING_ATR = 0.35
RSI_LONG_EXTREME = 65.0
RSI_SHORT_EXTREME = 35.0


def _atr14(df: pd.DataFrame) -> Optional[float]:
    if len(df) < 2 or not {"high", "low", "close"}.issubset(df.columns):
        return None
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    prev_close = df["close"].astype(float).shift(1)
    tr = pd.concat(
        [(high - low), (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    if len(tr) < 14:
        return float(tr.mean()) if len(tr) else None
    return float(tr.tail(14).mean())


def _resample_ohlc(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    if "epoch" not in df.columns or len(df) < 5:
        return pd.DataFrame()
    work = df.copy()
    work["ts"] = pd.to_datetime(work["epoch"], unit="s", utc=True)
    work = work.set_index("ts").sort_index()
    ohlc = work.resample(rule).agg(
        {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "epoch": "last",
        }
    ).dropna(subset=["close"])
    return ohlc


def _htf_bias(df_htf: pd.DataFrame) -> dict[str, Any]:
    if df_htf is None or len(df_htf) < 25:
        return {"trend": "unknown", "rsi": None, "ema21_slope": None}
    close = df_htf["close"].astype(float)
    ema = close.ewm(span=21, adjust=False).mean()
    ema_now = float(ema.iloc[-1])
    ema_prev = float(ema.iloc[-6]) if len(ema) >= 6 else float(ema.iloc[0])
    slope = ema_now - ema_prev
    rsi_s = compute_rsi(close, settings.RSI_PERIOD)
    rsi = float(rsi_s.iloc[-1]) if len(rsi_s) else None
    macd_line, signal_line, _ = compute_macd(
        close, settings.MACD_FAST, settings.MACD_SLOW, settings.MACD_SIGNAL
    )
    macd_side = "neutral"
    try:
        if float(macd_line.iloc[-1]) > float(signal_line.iloc[-1]):
            macd_side = "bullish"
        elif float(macd_line.iloc[-1]) < float(signal_line.iloc[-1]):
            macd_side = "bearish"
    except Exception:
        pass

    # Structure: last 8 bars HH/HL vs LH/LL
    structure = "range"
    if len(close) >= 8:
        recent = close.tail(8)
        if float(recent.iloc[-1]) > float(recent.iloc[0]) and slope > 0:
            structure = "up"
        elif float(recent.iloc[-1]) < float(recent.iloc[0]) and slope < 0:
            structure = "down"

    trend = "neutral"
    if structure == "up" and macd_side != "bearish":
        trend = "bullish"
    elif structure == "down" and macd_side != "bullish":
        trend = "bearish"
    elif macd_side in {"bullish", "bearish"}:
        trend = macd_side

    return {
        "trend": trend,
        "structure": structure,
        "macd_side": macd_side,
        "rsi": round(rsi, 2) if rsi is not None else None,
        "ema21_slope": round(slope, 8),
    }


def _pair_snapshot(symbol: str, df: pd.DataFrame, calendar: EconomicCalendar) -> dict[str, Any]:
    close = float(df.iloc[-1]["close"])
    rsi_series = compute_rsi(df["close"], settings.RSI_PERIOD)
    rsi = float(rsi_series.iloc[-1]) if len(rsi_series) else None
    macd_line, signal_line, hist = compute_macd(
        df["close"],
        settings.MACD_FAST,
        settings.MACD_SLOW,
        settings.MACD_SIGNAL,
    )
    signals = SignalEngine()
    signal = signals.evaluate(symbol, df)
    currencies = PAIR_CURRENCIES.get(symbol, set())
    news_paused, news_reason = calendar.is_paused_for_currencies(currencies)

    trend = "neutral"
    if rsi is not None:
        if rsi >= settings.RSI_OVERBOUGHT:
            trend = "overbought"
        elif rsi <= settings.RSI_OVERSOLD:
            trend = "oversold"
        elif float(macd_line.iloc[-1]) > float(signal_line.iloc[-1]):
            trend = "bullish"
        elif float(macd_line.iloc[-1]) < float(signal_line.iloc[-1]):
            trend = "bearish"

    ema21 = None
    atr = None
    swing_high = None
    swing_low = None
    try:
        ema21 = float(df["close"].ewm(span=21, adjust=False).mean().iloc[-1])
        atr = _atr14(df)
        high = df["high"].astype(float)
        low = df["low"].astype(float)
        look = min(48, len(df))
        swing_high = float(high.tail(look).max())
        swing_low = float(low.tail(look).min())
    except Exception:
        pass

    dist_ema_pct = None
    dist_ema_atr = None
    dist_swing_high_atr = None
    dist_swing_low_atr = None
    if ema21 and close:
        dist_ema_pct = round(((close - ema21) / ema21) * 100, 4)
    if atr and atr > 0:
        if ema21 is not None:
            dist_ema_atr = round(abs(close - ema21) / atr, 3)
        if swing_high is not None:
            dist_swing_high_atr = round(abs(swing_high - close) / atr, 3)
        if swing_low is not None:
            dist_swing_low_atr = round(abs(close - swing_low) / atr, 3)

    chase_long_risk = bool(
        (dist_swing_high_atr is not None and dist_swing_high_atr <= CHASE_SWING_ATR)
        or (rsi is not None and rsi >= RSI_LONG_EXTREME and trend in {"bearish", "overbought"})
        or (rsi is not None and rsi >= 70)
    )
    chase_short_risk = bool(
        (dist_swing_low_atr is not None and dist_swing_low_atr <= CHASE_SWING_ATR)
        or (rsi is not None and rsi <= RSI_SHORT_EXTREME and trend in {"bullish", "oversold"})
        or (rsi is not None and rsi <= 30)
    )
    pullback_ok_long = bool(
        dist_ema_atr is not None
        and dist_ema_atr <= PULLBACK_ATR_MAX
        and close <= (ema21 or close) * 1.0005
        and not chase_long_risk
    )
    pullback_ok_short = bool(
        dist_ema_atr is not None
        and dist_ema_atr <= PULLBACK_ATR_MAX
        and close >= (ema21 or close) * 0.9995
        and not chase_short_risk
    )

    htf_1h = _htf_bias(_resample_ohlc(df, "1h"))
    htf_4h = _htf_bias(_resample_ohlc(df, "4h"))

    structure_supports_long = htf_1h.get("trend") == "bullish" or (
        htf_1h.get("trend") == "neutral" and htf_4h.get("trend") == "bullish"
    )
    structure_supports_short = htf_1h.get("trend") == "bearish" or (
        htf_1h.get("trend") == "neutral" and htf_4h.get("trend") == "bearish"
    )
    rsi_ok_long = rsi is None or rsi < RSI_LONG_EXTREME
    rsi_ok_short = rsi is None or rsi > RSI_SHORT_EXTREME

    decision_gates = {
        "structure_supports_long": bool(structure_supports_long),
        "structure_supports_short": bool(structure_supports_short),
        "not_chasing_long": not chase_long_risk,
        "not_chasing_short": not chase_short_risk,
        "rsi_ok_long": bool(rsi_ok_long),
        "rsi_ok_short": bool(rsi_ok_short),
        "pullback_ok_long": pullback_ok_long,
        "pullback_ok_short": pullback_ok_short,
        "news_paused": bool(news_paused),
    }

    decimals = 3 if "JPY" in symbol else 5
    return {
        "price": round(close, decimals),
        "rsi": round(rsi, 2) if rsi is not None else None,
        "macd": round(float(macd_line.iloc[-1]), 6),
        "macd_signal": round(float(signal_line.iloc[-1]), 6),
        "macd_histogram": round(float(hist.iloc[-1]), 6),
        "bullish_cross": bool(detect_bullish_crossover(macd_line, signal_line)),
        "bearish_cross": bool(detect_bearish_crossover(macd_line, signal_line)),
        "trend": trend,
        "signal": signal.direction.value if signal else "none",
        "signal_reason": signal.reason if signal else None,
        "news_paused": bool(news_paused),
        "news_reason": news_reason or None,
        "ema21": round(ema21, decimals) if ema21 else None,
        "atr": round(atr, 6) if atr else None,
        "swing_high": round(swing_high, decimals) if swing_high else None,
        "swing_low": round(swing_low, decimals) if swing_low else None,
        "dist_ema21_pct": dist_ema_pct,
        "dist_ema21_atr": dist_ema_atr,
        "dist_swing_high_atr": dist_swing_high_atr,
        "dist_swing_low_atr": dist_swing_low_atr,
        "chase_long_risk": chase_long_risk,
        "chase_short_risk": chase_short_risk,
        "pullback_ok_long": pullback_ok_long,
        "pullback_ok_short": pullback_ok_short,
        "htf_1h": htf_1h,
        "htf_4h": htf_4h,
        "decision_gates": decision_gates,
        "suggested_entry_style": (
            "pullback"
            if trend in ("overbought", "oversold") or chase_long_risk or chase_short_risk
            else ("market" if trend in ("bullish", "bearish") else "pullback")
        ),
    }


def _currency_board(pairs: dict[str, Any], headlines: list[dict]) -> dict[str, str]:
    """Lite lean board from pair trends + headline currency hints."""
    scores: dict[str, float] = {c: 0.0 for c in ("USD", "EUR", "GBP", "JPY", "AUD", "CAD")}
    # Pair map: base/quote
    pair_ccy = {
        "frxEURUSD": ("EUR", "USD"),
        "frxGBPUSD": ("GBP", "USD"),
        "frxUSDJPY": ("USD", "JPY"),
        "frxAUDUSD": ("AUD", "USD"),
        "frxUSDCAD": ("USD", "CAD"),
    }
    for sym, snap in pairs.items():
        if not isinstance(snap, dict) or snap.get("error"):
            continue
        base_q = pair_ccy.get(sym)
        if not base_q:
            continue
        base, quote = base_q
        t = snap.get("trend") or "neutral"
        htf = (snap.get("htf_1h") or {}).get("trend") or t
        if htf == "bullish":
            scores[base] += 1.0
            scores[quote] -= 1.0
        elif htf == "bearish":
            scores[base] -= 1.0
            scores[quote] += 1.0
    for h in headlines[:20]:
        for code in h.get("currencies_hint") or []:
            title = (h.get("title") or "").lower()
            if code not in scores:
                continue
            if any(w in title for w in ("soft", "weak", "falls", "slides", "downside")):
                scores[code] -= 0.3
            if any(w in title for w in ("firm", "strong", "rises", "upside", "gains")):
                scores[code] += 0.3

    board: dict[str, str] = {}
    for c, s in scores.items():
        if s >= 0.8:
            board[c] = "firm"
        elif s <= -0.8:
            board[c] = "weak"
        else:
            board[c] = "mixed"
    return board


def _event_risk(calendar: EconomicCalendar) -> dict[str, Any]:
    brief = calendar.to_brief_dict(hours=12)
    upcoming = brief.get("upcoming_high_impact") or brief.get("next_6h") or []
    return {
        "hours": 12,
        "high_impact_count": len(upcoming) if isinstance(upcoming, list) else 0,
        "items": upcoming[:8] if isinstance(upcoming, list) else [],
    }


async def build_market_brief(
    *,
    bot: Any = None,
    client: Any = None,
    symbols: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Assemble live prices, calendar, headlines, and strategy fitness."""
    now = datetime.now(timezone.utc)
    symbols = symbols or list(settings.pairs_list)
    session = SessionManager()
    calendar = EconomicCalendar()
    if bot is not None and getattr(bot, "analysis", None) is not None:
        calendar = bot.analysis.calendar
    await calendar.refresh()

    pairs: dict[str, Any] = {}
    own_client = False
    ws = client
    if ws is None and bot is not None:
        ws = getattr(bot, "client", None)

    for symbol in symbols:
        df = None
        if bot is not None:
            try:
                df = bot.aggregator.get_dataframe(symbol)
            except Exception:
                df = None
        if df is None or len(df) < 30:
            try:
                if ws is None or not getattr(ws, "_authorized", False):
                    from data.deriv_ws import DerivWebSocketClient

                    ws = DerivWebSocketClient()
                    await ws.connect()
                    await ws.authorize()
                    own_client = True
                candles = await ws.get_candles_history(
                    symbol, settings.granularity_seconds, settings.CANDLE_BUFFER_SIZE
                )
                df = pd.DataFrame(candles)
            except Exception:
                logger.exception("Failed candles for %s in market brief", symbol)
                pairs[symbol] = {"error": "candles_unavailable"}
                continue
        try:
            pairs[symbol] = _pair_snapshot(symbol, df, calendar)
        except Exception:
            logger.exception("Pair snapshot failed for %s", symbol)
            pairs[symbol] = {"error": "snapshot_failed"}

    if own_client and ws is not None:
        try:
            await ws.disconnect()
        except Exception:
            pass

    headlines: list[dict] = []
    try:
        headlines = await fetch_headlines()
    except Exception:
        logger.exception("Headline fetch failed")

    strategy_fitness: dict[str, Any] = {}
    armed: list[str] = []
    if bot is not None:
        strategy_fitness = dict(getattr(bot.analysis, "strategy_win_rates", {}) or {})
        armed = sorted(getattr(bot.analysis, "armed_strategy_ids", set()) or [])
        if not strategy_fitness:
            for sid in PATTERN_STRATEGY_IDS:
                strategy_fitness.setdefault(
                    sid,
                    {
                        "win_rate": 0.0,
                        "total_trades": 0,
                        "passed": False,
                        "min_win_rate": settings.STRATEGY_MIN_WIN_RATE * 100,
                    },
                )

    status_bits: dict[str, Any] = {}
    if bot is not None:
        try:
            st = bot.status()
            status_bits = {
                "state": st.get("state"),
                "mode": st.get("mode"),
                "is_demo": st.get("is_demo"),
                "balance": st.get("balance"),
                "loginid": st.get("loginid"),
                "kill_switch_active": st.get("kill_switch_active"),
                "daily_pnl": st.get("daily_pnl"),
                "analysis_armed": st.get("analysis_armed"),
            }
        except Exception:
            logger.exception("status() failed in market brief")

    currency_board = _currency_board(pairs, headlines)
    event_risk = _event_risk(calendar)

    return {
        "as_of_utc": now.isoformat(),
        "session": session.session_status(),
        "pairs": pairs,
        "calendar": calendar.to_brief_dict(hours=48),
        "headlines": headlines,
        "currency_board": currency_board,
        "event_risk_next_hours": event_risk,
        "strategy_fitness": strategy_fitness,
        "armed_strategies": armed,
        "constraints": {
            "mode": settings.TRADING_MODE,
            "pairs_allowlist": list(settings.pairs_list),
            "risk_percent_max": float(getattr(settings, "PLAN_RISK_PERCENT_MAX", 2.0)),
            "max_stake_usd_ceiling": float(getattr(settings, "PLAN_MAX_STAKE_USD_CEILING", 50.0)),
            "min_strategy_win_rate": float(getattr(settings, "STRATEGY_MIN_WIN_RATE", 0.70)) * 100,
            "pattern_strategy_ids": list(PATTERN_STRATEGY_IDS),
            "execution_model": "cursor_owns_analysis",
            "max_trades_today_cap": 4,
            "entry_styles": ["market", "pullback"],
            "hard_gate": "news_chart_aligned",
            "required_plan_fields": [
                "trade_mode=bias",
                "directional_bias",
                "pairs",
                "sl_pips",
                "tp_pips",
                "max_trades_today",
                "entry_style",
                "review",
                "setups",
                "analysis.checklist",
            ],
            "bot_role": "execute_only",
        },
        "cursor_instructions": (
            "Hard rule: news AND charts must ALIGN or stand aside (max_trades_today=0). "
            "Use htf_1h/htf_4h, chase_*_risk, pullback_ok_*, decision_gates, currency_board. "
            "Never buy into chase_long_risk or elevated RSI against the trade. "
            "Fill analysis.checklist honestly. Bot only times ATR pullback / exits."
        ),
        "bot": status_bits,
    }
