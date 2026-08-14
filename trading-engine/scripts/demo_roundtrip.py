#!/usr/bin/env python3
"""Open one minimum-stake demo position, verify its barriers, then close it.

    python scripts/demo_roundtrip.py --symbol frxEURUSD --stake 1

This exists to answer the question that sank the previous configuration: does the
stop the venue actually applies sit where the chart said it should? The journal
recorded an ATR-width stop while the live contract used a fixed dollar amount
about half as wide, so positions died to the contract rather than to the thesis.

The order goes through OrderExecutor, the same path the bot uses, so a pass here
is evidence about production rather than about this script. Refuses to run
outside a demo account.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timezone

import pandas as pd

from config import settings
from data.deriv_ws import DerivWebSocketClient
from execution.orders import OrderExecutor, barriers_from_risk
from execution.multiplier import usd_from_pct
from indicators.atr import compute_atr
from risk.gate import RiskCheckResult, RiskDecision, pip_size
from risk.market_hours import is_market_open
from signals.engine import SignalDirection, TradeSignal

DAY_SECONDS = 86400


async def _daily_atr(client: DerivWebSocketClient, symbol: str) -> tuple[float, float]:
    """Latest price and daily ATR, the width the chart asks the stop to be."""
    candles = await client.get_candles_history(symbol, granularity=DAY_SECONDS, count=60)
    df = pd.DataFrame(candles)
    for col in ("high", "low", "close"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["high", "low", "close"])
    atr = float(compute_atr(df["high"], df["low"], df["close"], period=14).iloc[-1])
    return float(df["close"].iloc[-1]), atr


async def run(symbol: str, stake: float, atr_mult: float, hold: float) -> int:
    if settings.TRADING_MODE == "log_only":
        print("TRADING_MODE=log_only — nothing would be sent. Set TRADING_MODE=demo.")
        return 1
    if not is_market_open(symbol):
        print(f"{symbol} is closed right now. Run this while the forex market is open.")
        return 1

    client = DerivWebSocketClient()
    contract_id = None
    try:
        await client.connect()
        await client.authorize()
        if not client.is_demo:
            print(f"{client.loginid} is not a demo account — refusing to trade.")
            return 1
        print(f"account {client.loginid} (demo) balance={client.balance:.2f}")

        price, atr = await _daily_atr(client, symbol)
        stop_distance = atr * atr_mult
        # Long, with a one-ATR stop and a 1.5R target, matching the method.
        stop_price = price - stop_distance
        target_price = price + stop_distance * 1.5

        risk = RiskCheckResult(
            decision=RiskDecision.APPROVED,
            reason="demo_roundtrip",
            stake=stake,
            stop_loss_price=stop_price,
            take_profit_price=target_price,
            sl_tp_method="atr",
        )
        signal = TradeSignal(
            symbol=symbol,
            direction=SignalDirection.BUY,
            rsi=50.0,
            macd=0.0,
            macd_signal=0.0,
            price=price,
            epoch=int(datetime.now(timezone.utc).timestamp()),
            reason="demo_roundtrip",
        )
        calibration = await client.calibrate_contract(
            symbol, stake, float(settings.DERIV_MULTIPLIER)
        )
        if calibration:
            print(
                f"\ncalibration: notional ${calibration.notional:.2f} of a "
                f"${calibration.gross_notional:.2f} gross position, "
                f"${calibration.cost:.4f} of cost inside every limit "
                f"({calibration.cost / calibration.gross_notional * 100:.3f}% of notional)"
            )
        barriers = barriers_from_risk(risk, price, calibration=calibration)
        print(
            f"\nintent: buy {symbol} @ {price:.5f}\n"
            f"  daily ATR      {atr:.5f} ({atr / price * 100:.2f}% of price)\n"
            f"  stop price     {stop_price:.5f}  ({barriers.sl_pct * 100:.3f}% away)\n"
            f"  target price   {target_price:.5f}  ({barriers.tp_pct * 100:.3f}% away)\n"
            f"  encoded as     stop=${barriers.usd_sl:.2f} target=${barriers.usd_tp:.2f} "
            f"at x{barriers.multiplier:g}\n"
            f"  contract room  {barriers.room_pct * 100:.2f}% "
            f"(encodable={barriers.encodable})"
        )

        executor = OrderExecutor(client)
        order = await executor.execute_signal(signal, risk)
        if not order:
            print("no order returned")
            return 1
        contract_id = order.get("contract_id")
        print(
            f"\nopened contract_id={contract_id} buy_price={order.get('buy_price')} "
            f"start={order.get('start_time')}"
        )

        await asyncio.sleep(hold)
        detail = await client.get_contract(int(contract_id))
        entry = float(detail.get("entry_spot") or price)
        limits = {
            str(o.get("name")): o
            for o in (detail.get("limit_order") or {}).values()
            if isinstance(o, dict)
        } or (detail.get("limit_order") or {})

        print("\nas the venue reports it:")
        print(f"  entry spot     {entry}")
        print(f"  current spot   {detail.get('current_spot')}")
        print(f"  profit         {detail.get('profit')}")
        print(f"  limit_order    {detail.get('limit_order')}")

        ok = _verify_barriers(detail, entry, stake, barriers, stop_price, target_price)

        sold = await client.sell_contract(int(contract_id))
        print(f"\nclosed: {sold}")
        contract_id = None
        return 0 if ok else 1
    finally:
        if contract_id is not None:
            try:
                await client.sell_contract(int(contract_id))
                print(f"cleanup: sold {contract_id}")
            except Exception as exc:  # noqa: BLE001
                print(f"WARNING: could not close {contract_id}: {exc}")
        try:
            await client.disconnect()
        except Exception:  # noqa: BLE001
            pass


def _verify_barriers(
    detail: dict,
    entry: float,
    stake: float,
    barriers,
    stop_price: float,
    target_price: float,
) -> bool:
    """Compare the chart levels against the trigger prices the venue itself quotes.

    Deriv reports a ``value`` per limit order: the price at which it fires. That
    is the ground truth, and it is not the same as converting the dollar amount
    back with the contract formula, because the dollar limit is net of costs
    while the chart distance is gross. Recomputing our own number here would
    only confirm our own arithmetic.
    """
    limit = detail.get("limit_order") or {}
    pip = pip_size(str(detail.get("underlying") or detail.get("symbol") or ""))
    ok = True
    print("\nchart level vs the trigger price the venue quotes:")
    for label, key, intended in (
        ("stop", "stop_loss", stop_price),
        ("target", "take_profit", target_price),
    ):
        node = limit.get(key)
        if not isinstance(node, dict):
            print(f"  {label:<7} venue reported no {label} — cannot verify")
            ok = False
            continue
        try:
            trigger = float(node.get("value"))
            usd = abs(float(node.get("order_amount")))
        except (TypeError, ValueError):
            print(f"  {label:<7} unreadable: {node}")
            ok = False
            continue

        gap_price = trigger - intended
        gap_pips = abs(gap_price) / pip if pip else 0.0
        intended_distance = abs(entry - intended)
        share = abs(gap_price) / intended_distance * 100 if intended_distance else 0.0
        gross = usd_from_pct(
            stake, barriers.multiplier, abs(trigger - entry) / entry
        )
        direction = "tighter than" if abs(trigger - entry) < intended_distance else "wider than"
        verdict = "ok" if share < 5.0 else "OFF"
        print(
            f"  {label:<7} ${usd:.2f} fires at {trigger:.5f}, chart wanted {intended:.5f}"
            f"  ({gap_pips:.1f} pips {direction} plan, {share:.0f}% of the distance) {verdict}"
        )
        print(
            f"          gross move at that price is ${gross:.2f}, so ${usd - gross:.2f} "
            f"of the ${usd:.2f} limit is cost, not price"
        )
        if share >= 5.0:
            ok = False
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", default="frxEURUSD")
    parser.add_argument("--stake", type=float, default=1.0)
    parser.add_argument("--atr-mult", type=float, default=1.0)
    parser.add_argument(
        "--hold", type=float, default=5.0, help="seconds to hold before closing"
    )
    args = parser.parse_args()
    return asyncio.run(run(args.symbol, args.stake, args.atr_mult, args.hold))


if __name__ == "__main__":
    sys.exit(main())
