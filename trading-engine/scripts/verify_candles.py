#!/usr/bin/env python3
"""Verify aggregated candles against Deriv history (A1 gate)."""

import asyncio
import sys

from config import settings
from data.deriv_ws import DerivWebSocketClient


async def main() -> int:
    symbol = sys.argv[1] if len(sys.argv) > 1 else settings.pairs_list[0]
    client = DerivWebSocketClient()
    await client.connect()
    try:
        if settings.DERIV_API_TOKEN:
            await client.authorize()
            if client.market_data_only:
                print("Note: PAT not authorized — using public market data (candles still work).")
            elif client.is_demo:
                print(f"Authorized demo account {client.loginid} balance={client.balance}")
        candles = await client.get_candles_history(
            symbol, settings.granularity_seconds, 10
        )
        print(f"Last 10 candles for {symbol} (granularity={settings.granularity_seconds}s):")
        for c in candles[-10:]:
            print(
                f"  epoch={c['epoch']} O={c['open']:.5f} H={c['high']:.5f} "
                f"L={c['low']:.5f} C={c['close']:.5f}"
            )
        print("\nCompare these OHLC values with Deriv chart (same symbol/timeframe).")
        return 0
    finally:
        await client.disconnect()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
