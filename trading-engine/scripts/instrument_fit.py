#!/usr/bin/env python3
"""Does the contract have room for the instrument's volatility?

    python scripts/instrument_fit.py
    python scripts/instrument_fit.py --symbols frxEURUSD,frxXAUUSD --atr-mult 1.0

A Deriv multiplier position is liquidated once price moves ``1 / multiplier``
against it, so the multiplier menu, not the chart, sets the widest stop that can
be encoded. This measures each instrument's true daily range and reports the
lowest multiplier that still leaves headroom for a stop of ``atr-mult`` ATRs.

This is the check the R_50 configuration failed: its stop was roughly half the
distance the thesis asked for, so trades died to the contract rather than to the
market. An instrument that does not fit here should not be traded here.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

import pandas as pd

from config import settings
from data.deriv_ws import DerivWebSocketClient
from execution.multiplier import DEFAULT_STOP_SAFETY, contract_room_pct
from indicators.atr import compute_atr

DAY_SECONDS = 86400


def _frame(candles: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(candles)
    for col in ("open", "high", "low", "close"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.dropna(subset=["high", "low", "close"]).reset_index(drop=True)


async def measure(
    symbols: list[str], atr_mult: float, days: int, safety: float
) -> list[dict]:
    client = DerivWebSocketClient()
    rows: list[dict] = []
    try:
        await client.connect()
        await client.authorize()
        for symbol in symbols:
            try:
                candles = await client.get_candles_history(
                    symbol, granularity=DAY_SECONDS, count=days
                )
            except Exception as exc:  # noqa: BLE001
                rows.append({"symbol": symbol, "error": f"{type(exc).__name__}: {exc}"})
                continue
            df = _frame(candles or [])
            if len(df) < 20:
                rows.append({"symbol": symbol, "error": f"only {len(df)} daily bars"})
                continue

            price = float(df["close"].iloc[-1])
            atr_abs = float(
                compute_atr(df["high"], df["low"], df["close"], period=14).iloc[-1]
            )
            atr_pct = atr_abs / price
            stop_pct = atr_pct * atr_mult

            allowed = await client.get_allowed_multipliers(symbol) or []
            # The lowest multiplier on offer gives the most room, so it decides
            # whether the instrument is tradable here at all.
            lowest = min(allowed) if allowed else None
            room_pct = contract_room_pct(lowest) if lowest else None
            rows.append(
                {
                    "symbol": symbol,
                    "price": price,
                    "atr_pct": atr_pct,
                    "stop_pct": stop_pct,
                    "allowed": allowed,
                    "lowest": lowest,
                    "room_pct": room_pct,
                    "headroom": (room_pct / stop_pct) if room_pct and stop_pct else None,
                    "fits": bool(room_pct and room_pct >= stop_pct * safety),
                }
            )
    finally:
        try:
            await client.disconnect()
        except Exception:  # noqa: BLE001
            pass
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", default="", help="comma separated; default config pairs")
    parser.add_argument(
        "--atr-mult",
        type=float,
        default=1.0,
        help="stop width in daily ATRs (default 1.0)",
    )
    parser.add_argument("--days", type=int, default=120, help="daily bars to read")
    parser.add_argument(
        "--safety",
        type=float,
        default=DEFAULT_STOP_SAFETY,
        help="required headroom between stop and liquidation",
    )
    args = parser.parse_args()

    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()] or settings.pairs_list
    rows = asyncio.run(measure(symbols, args.atr_mult, args.days, args.safety))

    print(
        f"\nContract room vs volatility — stop = {args.atr_mult:g} x daily ATR, "
        f"safety x{args.safety:g}\n"
    )
    header = f"{'symbol':<12} {'price':>10} {'ATR%':>7} {'stop%':>7} {'room%':>7} {'mult':>6}  verdict"
    print(header)
    print("-" * len(header))
    for row in rows:
        if row.get("error"):
            print(f"{row['symbol']:<12} {'':>10} {'':>7} {'':>7} {'':>7} {'':>6}  ERROR {row['error']}")
            continue
        verdict = (
            f"fits at x{row['lowest']:g} ({row['headroom']:.1f}x headroom)"
            if row["fits"]
            else f"NO ROOM — needs x{1.0 / (row['stop_pct'] * args.safety):.0f} or lower"
        )
        print(
            f"{row['symbol']:<12} {row['price']:>10.4f} {row['atr_pct'] * 100:>6.2f}% "
            f"{row['stop_pct'] * 100:>6.2f}% {row['room_pct'] * 100:>6.2f}% "
            f"{row['lowest']:>6.0f}  {verdict}"
        )

    tradable = [r["symbol"] for r in rows if r.get("fits")]
    blocked = [r["symbol"] for r in rows if not r.get("fits") and not r.get("error")]
    print(f"\nfits:    {', '.join(tradable) if tradable else 'none'}")
    if blocked:
        print(f"no room: {', '.join(blocked)}")
    print(
        "\n'room%' is the adverse move that liquidates the position at the lowest\n"
        "multiplier the venue offers. A stop wider than that cannot be encoded."
    )
    return 0 if tradable else 1


if __name__ == "__main__":
    sys.exit(main())
