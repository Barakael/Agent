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

    return {
        "price": round(close, 5 if "JPY" not in symbol else 3),
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
            # Ensure keys exist for automation even before preflight
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

    return {
        "as_of_utc": now.isoformat(),
        "session": session.session_status(),
        "pairs": pairs,
        "calendar": calendar.to_brief_dict(hours=48),
        "headlines": headlines,
        "strategy_fitness": strategy_fitness,
        "armed_strategies": armed,
        "constraints": {
            "mode": settings.TRADING_MODE,
            "pairs_allowlist": list(settings.pairs_list),
            "risk_percent_max": float(getattr(settings, "PLAN_RISK_PERCENT_MAX", 2.0)),
            "max_stake_usd_ceiling": float(getattr(settings, "PLAN_MAX_STAKE_USD_CEILING", 50.0)),
            "min_strategy_win_rate": float(getattr(settings, "STRATEGY_MIN_WIN_RATE", 0.70)) * 100,
            "pattern_strategy_ids": list(PATTERN_STRATEGY_IDS),
        },
        "bot": status_bits,
    }
