#!/usr/bin/env python3
"""Read the trend on every pair, draw it, and report.

    python scripts/daily_brief.py
    python scripts/daily_brief.py --timeframe 240 --send
    python scripts/daily_brief.py --no-charts

Writes one chart per instrument to ``reports/`` and prints a brief. With
``--send`` the brief and charts go to Telegram through the existing alert path.

The brief describes the market and what the method's rules would imply. It does
not claim the implication is profitable: that is what the replay harness and
acceptance gate are for, and until a configuration clears that bar this output
is for reading, not for trading.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from alerts.telegram import TelegramAlerter
from analysis.trend_chart import brief_text, read_trend, render_chart
from config import settings
from data.deriv_ws import DerivWebSocketClient
from indicators.atr import compute_atr
from risk.market_hours import is_market_open, seconds_until_open

REPORTS = Path("reports")


def _frame(candles: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(candles)
    if df.empty:
        return df
    for col in ("open", "high", "low", "close"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.dropna(subset=["open", "high", "low", "close"]).reset_index(drop=True)


async def _daily_atr(client: DerivWebSocketClient, symbol: str) -> float:
    """Daily ATR, which sizes the stop regardless of the bars the trend is read on."""
    try:
        candles = await client.get_candles_history(symbol, granularity=86400, count=60)
    except Exception:  # noqa: BLE001
        return 0.0
    df = _frame(candles or [])
    if len(df) < 20:
        return 0.0
    return float(
        compute_atr(df["high"], df["low"], df["close"], period=14).iloc[-1]
    )


async def build(
    symbols: list[str], timeframe_minutes: int, bars: int, charts: bool
) -> tuple[str, list[str], list[dict]]:
    client = DerivWebSocketClient()
    reads = []
    chart_paths: list[str] = []
    stamp = datetime.now(timezone.utc)
    try:
        await client.connect()
        await client.authorize()
        for symbol in symbols:
            try:
                candles = await client.get_candles_paged(
                    symbol, granularity=timeframe_minutes * 60, total=bars
                )
            except Exception as exc:  # noqa: BLE001
                print(f"{symbol}: history failed — {type(exc).__name__}: {exc}")
                continue
            df = _frame(candles or [])
            if df.empty:
                print(f"{symbol}: no candles")
                continue
            read = read_trend(
                df,
                symbol,
                multiplier=float(settings.DERIV_MULTIPLIER),
                stop_atr=await _daily_atr(client, symbol),
            )
            if read is None:
                print(f"{symbol}: not enough history for a trend read ({len(df)} bars)")
                continue
            reads.append(read)
            if charts:
                path = render_chart(
                    df,
                    read,
                    REPORTS / f"{symbol}_{timeframe_minutes}m_{stamp:%Y%m%d}.png",
                    title_suffix=f"  ({timeframe_minutes}m, {stamp:%Y-%m-%d %H:%M} UTC)",
                )
                if path:
                    chart_paths.append(str(path))
    finally:
        try:
            await client.disconnect()
        except Exception:  # noqa: BLE001
            pass

    closed = [s for s in symbols if not is_market_open(s)]
    header = f"{stamp:%Y-%m-%d %H:%M} UTC — {timeframe_minutes}m bars"
    if closed:
        hours = seconds_until_open(closed[0]) / 3600.0
        header += f"\nMarket closed, reopens in {hours:.1f}h — this is a read, not a plan"
    text = brief_text(reads, header=header)
    return text, chart_paths, [r.to_dict() for r in reads]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", default="", help="default: configured pairs")
    parser.add_argument(
        "--timeframe",
        type=int,
        default=240,
        help="bar size in minutes (default 240, the swing horizon)",
    )
    parser.add_argument("--bars", type=int, default=400)
    parser.add_argument("--no-charts", action="store_true")
    parser.add_argument("--send", action="store_true", help="deliver via Telegram")
    parser.add_argument("--json", default="", help="also write the reads as JSON")
    args = parser.parse_args()

    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()] or settings.pairs_list
    text, charts, payload = asyncio.run(
        build(symbols, args.timeframe, args.bars, not args.no_charts)
    )

    print("\n" + text)
    if charts:
        print("\ncharts:")
        for path in charts:
            print(f"  {path}")

    if args.json:
        Path(args.json).write_text(json.dumps(payload, indent=2))
        print(f"\nwrote {args.json}")

    if args.send:
        alerter = TelegramAlerter()
        if not alerter.enabled:
            print("\nTelegram is not configured (TELEGRAM_BOT_TOKEN / CHAT_ID unset).")
            return 1
        asyncio.run(alerter.daily_brief(text, charts))
        print("\nsent to Telegram")
    return 0


if __name__ == "__main__":
    sys.exit(main())
