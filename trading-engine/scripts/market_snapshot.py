#!/usr/bin/env python3
"""One-shot live market snapshot for all monitored pairs."""

import asyncio
import json
from datetime import datetime, timezone

import pandas as pd

from config import settings
from data.calendar import EconomicCalendar
from data.deriv_ws import DerivWebSocketClient
from indicators.macd import compute_macd, detect_bearish_crossover, detect_bullish_crossover
from indicators.rsi import compute_rsi
from risk.session import TradingSession
from signals.engine import SignalEngine


async def main() -> None:
    now = datetime.now(timezone.utc)
    session = TradingSession()
    cal = EconomicCalendar()
    await cal.refresh()

    client = DerivWebSocketClient()
    await client.connect()
    report = {
        "timestamp_utc": now.isoformat(),
        "session": {
            "open": session.is_session_open(now),
            "must_force_close": session.must_force_close(now),
            "close_time_utc": f"{settings.SESSION_CLOSE_HOUR_UTC:02d}:{settings.SESSION_CLOSE_MINUTE_UTC:02d}",
        },
        "trading_mode": settings.TRADING_MODE,
        "pairs": {},
    }

    try:
        await client.authorize()
        report["account"] = {
            "loginid": client.loginid,
            "is_demo": client.is_demo,
            "balance": client.balance,
            "currency": getattr(client, "currency", "USD"),
        }

        signals = SignalEngine()
        for symbol in settings.pairs_list:
            candles = await client.get_candles_history(
                symbol, settings.granularity_seconds, settings.CANDLE_BUFFER_SIZE
            )
            df = pd.DataFrame(candles)
            close = float(df.iloc[-1]["close"])
            rsi_series = compute_rsi(df["close"], settings.RSI_PERIOD)
            rsi = float(rsi_series.iloc[-1])
            macd_line, signal_line, hist = compute_macd(
                df["close"],
                settings.MACD_FAST,
                settings.MACD_SLOW,
                settings.MACD_SIGNAL,
            )
            signal = signals.evaluate(symbol, df)
            news_paused, news_reason = cal.is_paused_for_currencies(
                {"EUR", "USD"} if "EUR" in symbol else
                {"GBP", "USD"} if "GBP" in symbol else
                {"AUD", "USD"} if "AUD" in symbol else
                {"USD", "JPY"}
            )

            report["pairs"][symbol] = {
                "price": round(close, 5),
                "rsi": round(rsi, 2),
                "macd": round(float(macd_line.iloc[-1]), 6),
                "macd_signal": round(float(signal_line.iloc[-1]), 6),
                "macd_histogram": round(float(hist.iloc[-1]), 6),
                "bullish_cross": detect_bullish_crossover(macd_line, signal_line),
                "bearish_cross": detect_bearish_crossover(macd_line, signal_line),
                "signal": signal.direction.value if signal else "none",
                "signal_reason": signal.reason if signal else None,
                "news_paused": news_paused,
                "news_reason": news_reason or None,
            }
    finally:
        await client.disconnect()

    upcoming = cal.upcoming_high_impact(24)
    report["upcoming_high_impact_news"] = [
        {"title": e.title, "currency": e.currency, "time": e.event_time.isoformat()}
        for e in upcoming[:5]
    ]
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
