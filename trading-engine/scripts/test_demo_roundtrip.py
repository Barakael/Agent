#!/usr/bin/env python3
"""One-shot demo buy → sell smoke test against Deriv.

Hard-aborts unless the authorized account is demo.
Uses a tiny stake and immediately sells the contract.
"""

from __future__ import annotations

import asyncio
import json
import sys

from config import settings
from data.deriv_ws import DerivWebSocketClient

STAKE = 1.0
# Multipliers support early sell; binary CALL/PUT on forex often cannot be resold.
DURATION_MINUTES = 15  # unused for MULTUP; kept for API signature
CONTRACT_TYPE = "MULTUP"
MULTIPLIER = 100


def _pp(label: str, payload: object) -> None:
    print(f"\n--- {label} ---")
    print(json.dumps(payload, indent=2, default=str))


async def main() -> int:
    print("=== Deriv demo buy/sell roundtrip ===\n")

    token = (settings.DERIV_API_TOKEN or "").strip()
    if not token or token.startswith("paste_"):
        print("FAIL — set DERIV_API_TOKEN in trading-engine/.env")
        return 1
    if not settings.DERIV_APP_ID.strip():
        print("FAIL — set DERIV_APP_ID in trading-engine/.env")
        return 1

    symbol = settings.pairs_list[0]
    print(f"APP_ID:     {settings.DERIV_APP_ID}")
    print(f"TOKEN:      set ({token[:10]}...)")
    print(f"MODE:       {settings.TRADING_MODE}")
    print(f"SYMBOL:     {symbol}")
    print(f"STAKE:      {STAKE} USD")
    print(f"CONTRACT:   {CONTRACT_TYPE} x{MULTIPLIER}")

    # Preflight REST (PAT apps) — surface Invalid application before WS noise
    if token.startswith("pat_"):
        print("\n0. REST preflight /options/accounts")
        try:
            from data.deriv_rest import list_accounts

            accounts = await list_accounts()
            print(f"   OK — {len(accounts)} account(s)")
        except Exception as exc:
            print(f"   FAIL — {exc}")
            print(
                "\nCannot place demo trades until REST auth works for this PAT.\n"
                "Fix DERIV_APP_ID (must be the Application ID of the app that issued the PAT),\n"
                "or use a classic Security→API Tokens token (no pat_ prefix) with DERIV_APP_ID=1089."
            )
            return 1

    client = DerivWebSocketClient()
    await client.connect()
    contract_id: int | None = None

    try:
        auth = await client.authorize()
        if client.market_data_only or not client._authorized:
            print(
                "FAIL — authorized as market-data-only (token not trading-capable). "
                "Check Trade + Account management scopes / partner profile / DERIV_APP_ID."
            )
            return 1

        balance_before = client.balance
        print(
            f"\nAuthorized loginid={client.loginid} demo={client.is_demo} "
            f"balance={balance_before:.2f}"
        )
        if auth:
            _pp("authorize summary", {
                "loginid": client.loginid,
                "is_demo": client.is_demo,
                "balance": balance_before,
            })

        if not client.is_demo:
            print(
                f"FAIL — refusing trade: account {client.loginid} is LIVE. "
                "Set DERIV_DEMO_LOGINID or use a demo wallet."
            )
            return 1

        print("\nPlacing demo buy...")
        try:
            buy = await client.buy_contract(
                symbol=symbol,
                contract_type=CONTRACT_TYPE,
                amount=STAKE,
                duration=DURATION_MINUTES,
                duration_unit="m",
                multiplier=MULTIPLIER,
            )
        except Exception as exc:
            print(f"FAIL — buy/proposal error: {exc}")
            return 1

        _pp("buy response", buy)
        raw_id = buy.get("contract_id")
        if raw_id is None:
            print("FAIL — buy succeeded but no contract_id in response")
            return 1
        contract_id = int(raw_id)
        print(f"\nBUY OK — contract_id={contract_id}")

        print("\nSelling contract...")
        sell_error: Exception | None = None
        sell: dict = {}
        for attempt in (1, 2):
            try:
                sell = await client.sell_contract(contract_id)
                sell_error = None
                break
            except Exception as exc:
                sell_error = exc
                print(f"Sell attempt {attempt} failed: {exc}")
                if attempt == 1:
                    await asyncio.sleep(1.5)

        if sell_error is not None:
            try:
                open_pos = await client.get_open_positions()
            except Exception as portfolio_exc:
                open_pos = [{"portfolio_error": str(portfolio_exc)}]
            print(
                f"FAIL — sell failed after buy. Close manually in Deriv Trader: "
                f"contract_id={contract_id}"
            )
            _pp("open positions", open_pos)
            return 1

        _pp("sell response", sell)
        print(
            f"\nSELL OK — contract_id={contract_id} "
            f"profit={sell.get('profit')} sold_for={sell.get('sold_for')}"
        )

        try:
            bal_resp = await client._send({"balance": 1})
            balance_after = float(bal_resp.get("balance", {}).get("balance", client.balance))
        except Exception:
            balance_after = client.balance

        print(f"\nBalance before={balance_before:.2f} after={balance_after:.2f}")
        print("\nPASS — demo buy/sell roundtrip succeeded")
        return 0
    finally:
        await client.disconnect()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
