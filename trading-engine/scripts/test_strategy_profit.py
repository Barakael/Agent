#!/usr/bin/env python3
"""One-strategy profit probe: RSI+MACD confluence → backtest → optional one demo trade.

Strategy (single best rule set already used by the bot):
  BUY  when RSI < oversold AND MACD bullish crossover
  SELL when RSI > overbought AND MACD bearish crossover
  Risk: DEFAULT_SL_PIPS / DEFAULT_TP_PIPS (1:2 by default)

Usage:
  PYTHONPATH=. python scripts/test_strategy_profit.py           # backtest only
  PYTHONPATH=. python scripts/test_strategy_profit.py --trade   # backtest + one demo trade if signal
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time

import pandas as pd

from backtest.runner import BacktestRunner
from config import settings
from data.deriv_ws import DerivWebSocketClient
from signals.engine import SignalEngine

STAKE = 1.0
MULTIPLIER = 100
MONITOR_SECONDS = 90
POLL_SECONDS = 3


async def backtest_all(count: int = 500) -> dict:
    runner = BacktestRunner(initial_balance=10_000.0)
    print(
        f"=== Backtest MACD+RSI "
        f"({count} x {settings.CANDLE_TIMEFRAME_MINUTES}m bars) ===\n"
    )
    results = await runner.run_all_pairs(count)
    ranked = []
    for symbol, data in results.items():
        if "error" in data:
            print(f"{symbol}: ERROR {data['error']}")
            continue
        print(
            f"{symbol}: trades={data['total_trades']} pnl={data['total_pnl']} "
            f"win%={data['win_rate']} expectancy={data['expectancy']} "
            f"passed={data['passed']}"
        )
        ranked.append((symbol, data))

    ranked.sort(
        key=lambda x: (x[1].get("passed", False), x[1].get("total_pnl", -1e9)),
        reverse=True,
    )
    return {"results": results, "best": ranked[0] if ranked else None}


async def live_signal(client: DerivWebSocketClient, symbol: str) -> dict | None:
    engine = SignalEngine()
    candles = await client.get_candles_history(
        symbol, settings.granularity_seconds, settings.CANDLE_BUFFER_SIZE
    )
    df = pd.DataFrame(candles)
    signal = engine.evaluate(symbol, df)
    return signal.to_dict() if signal else None


async def one_demo_trade(symbol: str, direction: str) -> int:
    client = DerivWebSocketClient()
    await client.connect()
    try:
        await client.authorize()
        if not client.is_demo:
            print(f"FAIL — refusing live account {client.loginid}")
            return 1
        if client.market_data_only:
            print("FAIL — market data only; cannot trade")
            return 1

        balance_before = client.balance
        contract_type = "MULTUP" if direction == "buy" else "MULTDOWN"
        print(
            f"\nPlacing demo {contract_type} {symbol} stake={STAKE} x{MULTIPLIER} "
            f"(account={client.loginid} bal={balance_before:.2f})"
        )
        buy = await client.buy_contract(
            symbol=symbol,
            contract_type=contract_type,
            amount=STAKE,
            duration=15,
            duration_unit="m",
            multiplier=MULTIPLIER,
        )
        contract_id = int(buy["contract_id"])
        print(f"BUY OK contract_id={contract_id} buy_price={buy.get('buy_price')}")

        deadline = time.time() + MONITOR_SECONDS
        sell = None
        last_err = None
        while time.time() < deadline:
            await asyncio.sleep(POLL_SECONDS)
            try:
                sell = await client.sell_contract(contract_id)
                last_err = None
                break
            except Exception as exc:
                last_err = exc
                msg = str(exc)
                if "EntryTickMissing" in msg or "Waiting for entry" in msg:
                    continue
                if "ResaleNotOffered" in msg:
                    break
                print(f"sell retry: {exc}")

        if sell is None:
            print(
                f"FAIL — could not sell: {last_err}. "
                f"Close manually contract_id={contract_id}"
            )
            return 1

        sold_for = float(sell.get("sold_for") or 0)
        pnl = sold_for - STAKE
        print(
            f"SELL OK sold_for={sold_for:.2f} approx_pnl={pnl:+.2f} "
            f"(short hold — strategy edge needs many trades / SL-TP holds)"
        )
        print(
            json.dumps(
                {"buy": buy, "sell": sell, "approx_pnl": round(pnl, 2)},
                indent=2,
                default=str,
            )
        )
        return 0
    finally:
        await client.disconnect()


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--trade",
        action="store_true",
        help="After backtest, place one demo trade if a live confluence signal exists",
    )
    parser.add_argument("--bars", type=int, default=500)
    args = parser.parse_args()

    print("Strategy: MACD crossover + RSI confirmation (bot default)")
    print(
        f"  BUY  MACD bull cross + RSI < 55 | "
        f"SELL MACD bear cross + RSI > 45"
    )
    print(
        f"  SL={settings.DEFAULT_SL_PIPS} pips "
        f"TP={settings.DEFAULT_TP_PIPS} pips (R-multiple backtest model)\n"
    )

    summary = await backtest_all(args.bars)
    best = summary["best"]
    if not best:
        print("\nNo backtest results.")
        return 1

    symbol, data = best
    print(
        f"\nBest pair by backtest: {symbol} "
        f"pnl={data.get('total_pnl')} passed={data.get('passed')}"
    )

    if not args.trade:
        print(
            "\nBacktest only. Re-run with --trade to place one demo trade "
            "on a live signal."
        )
        return 0 if data.get("passed") or data.get("total_pnl", 0) > 0 else 1

    if data.get("total_pnl", 0) <= 0 and not data.get("passed"):
        # Still allow trade if any pair was profitable
        any_good = any(
            isinstance(v, dict)
            and v.get("total_pnl", 0) > 0
            and v.get("total_trades", 0) > 0
            for v in summary["results"].values()
        )
        if not any_good:
            print("\nSkipping live demo trade — backtest not profitable on any pair.")
            return 1
        print("\nBest pair flat/negative, but another pair was profitable — continuing.")

    client = DerivWebSocketClient()
    await client.connect()
    try:
        await client.authorize()
        if client.market_data_only or not client._authorized:
            print("FAIL — could not authorize for trading (OTP/token). Check PAT + App ID.")
            return 1
        if not client.is_demo:
            print(f"FAIL — not demo (loginid={client.loginid})")
            return 1
        signal = await live_signal(client, symbol)
        chosen = symbol
        if not signal:
            for alt in settings.pairs_list:
                if alt == symbol:
                    continue
                signal = await live_signal(client, alt)
                if signal:
                    chosen = alt
                    break
    finally:
        await client.disconnect()

    if not signal:
        print(
            "\nNo live confluence signal right now on configured pairs. "
            "Backtest done; wait for RSI+MACD setup or run bot in demo mode."
        )
        return 0

    print(f"\nLive signal on {chosen}: {json.dumps(signal)}")
    return await one_demo_trade(chosen, signal["direction"])


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
