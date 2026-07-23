#!/usr/bin/env python3
"""Place 5 risk-capped demo multiplier trades for observation."""

from __future__ import annotations

import asyncio
import random
import sys

from config import settings
from data.deriv_ws import DerivWebSocketClient
from risk.gate import RiskDecision, RiskGate
from signals.engine import SignalDirection, TradeSignal

PAIRS = ["frxAUDUSD", "frxEURUSD", "frxGBPUSD", "frxUSDJPY"]
PLAN_MAX = 25.0


async def place_one(client: DerivWebSocketClient, symbol: str, direction: SignalDirection, stake: float) -> dict:
    ctype = "MULTUP" if direction == SignalDirection.BUY else "MULTDOWN"
    # Multiplier limit_order uses USD P/L amounts (2 d.p.), not FX prices
    sl_usd = round(stake * 0.8, 2)
    tp_usd = round(stake * 2.0, 2)
    try:
        return await client.buy_contract(
            symbol=symbol,
            contract_type=ctype,
            amount=stake,
            duration=15,
            duration_unit="m",
            stop_loss=sl_usd,
            take_profit=tp_usd,
            multiplier=100,
        )
    except Exception as first:
        print(f"   limit-order failed ({first}); retry without limits")
        return await client.buy_contract(
            symbol=symbol,
            contract_type=ctype,
            amount=stake,
            duration=15,
            duration_unit="m",
            stop_loss=None,
            take_profit=None,
            multiplier=100,
        )


async def main() -> int:
    if settings.TRADING_MODE != "demo":
        print(f"REFUSE: TRADING_MODE={settings.TRADING_MODE}")
        return 2

    client = DerivWebSocketClient()
    risk = RiskGate()
    risk.risk_percent = 1.5

    await client.connect()
    await client.authorize()
    print(f"account={client.loginid} demo={client.is_demo} balance={client.balance}")
    if not client.is_demo:
        print("REFUSE: not demo")
        await client.disconnect()
        return 2

    balance = float(client.balance or 0)
    results: list[dict] = []
    for i in range(5):
        symbol = random.choice(PAIRS)
        direction = random.choice([SignalDirection.BUY, SignalDirection.SELL])
        candles = await client.get_candles_history(symbol, settings.granularity_seconds, 3)
        price = float(candles[-1]["close"])
        signal = TradeSignal(
            symbol=symbol,
            direction=direction,
            rsi=50.0,
            macd=0.0,
            macd_signal=0.0,
            price=price,
            epoch=int(candles[-1]["epoch"]),
            reason=f"manual_observe_{i + 1}",
        )
        check = risk.evaluate(
            signal,
            balance,
            sl_pips=15,
            tp_pips=30,
            max_stake_usd=PLAN_MAX,
        )
        if check.decision != RiskDecision.APPROVED:
            print(f"{i + 1} REJECT {symbol} {direction.value}: {check.reason}")
            continue

        stake = min(float(check.stake), PLAN_MAX)
        assert stake <= PLAN_MAX
        print(f"{i + 1} PLACE {direction.value} {symbol} stake={stake}")
        try:
            order = await place_one(client, symbol, direction, stake)
            cid = order.get("contract_id")
            bal = order.get("balance_after")
            print(f"   OK contract_id={cid} balance_after={bal}")
            results.append(
                {
                    "symbol": symbol,
                    "direction": direction.value,
                    "stake": stake,
                    "contract_id": cid,
                }
            )
            if bal is not None:
                balance = float(bal)
        except Exception as exc:
            print(f"   FAIL {exc}")
        await asyncio.sleep(1.2)

    pos = await client.get_open_positions()
    print(f"\nopen_positions={len(pos)} placed={len(results)}")
    for p in pos:
        print(
            " ",
            p.get("contract_id"),
            p.get("underlying") or p.get("symbol"),
            p.get("contract_type"),
            "buy_price=",
            p.get("buy_price"),
            "profit=",
            p.get("profit"),
        )
    await client.disconnect()
    return 0 if len(results) >= 5 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
