#!/usr/bin/env python3
"""Test Deriv credentials — REST, OTP, legacy WebSocket, public candles."""

import asyncio
import json
import sys

from config import settings


async def main() -> int:
    print("=== Deriv auth test ===\n")
    print(f"APP_ID:     {settings.DERIV_APP_ID}")
    print(f"TOKEN:      {'set (' + settings.DERIV_API_TOKEN[:12] + '...)' if settings.DERIV_API_TOKEN else 'MISSING'}")
    print(f"WS_APP_ID:  {settings.deriv_ws_app_id}\n")

    if not settings.DERIV_API_TOKEN:
        print("Set DERIV_API_TOKEN in .env")
        return 1

    # 1. REST accounts (required for PAT OTP trading)
    print("1. REST GET /options/accounts")
    try:
        from data.deriv_rest import list_accounts

        accounts = await list_accounts()
        print(f"   OK — {len(accounts)} account(s)")
        for a in accounts[:3]:
            print(f"   - {a}")
    except Exception as e:
        print(f"   FAIL — {e}")
        if str(settings.DERIV_API_TOKEN).startswith("pat_"):
            print(
                "   NOTE: PAT trading requires a valid DERIV_APP_ID for the issuing app. "
                "'Invalid application' means the UUID/Client ID does not match."
            )

    # 2. Full client authorize (OTP → legacy → fallback)
    print("\n2. WebSocket authorize (OTP + legacy)")
    from data.deriv_ws import DerivWebSocketClient

    client = DerivWebSocketClient()
    await client.connect()
    try:
        auth = await client.authorize()
        if client.market_data_only:
            print("   PARTIAL — public market data only (token not fully active)")
            candles = await client.get_candles_history(
                settings.pairs_list[0], settings.granularity_seconds, 3
            )
            print(f"   Candles OK — {settings.pairs_list[0]} last close={candles[-1]['close']}")
            print("\n=== Auth insufficient for trading ===")
            return 1
        elif auth:
            print(f"   OK — loginid={client.loginid} demo={client.is_demo} balance={client.balance}")
        candles = await client.get_candles_history(
            settings.pairs_list[0], settings.granularity_seconds, 3
        )
        print(f"   Candles OK — {settings.pairs_list[0]} last close={candles[-1]['close']}")
    except Exception as e:
        print(f"   FAIL — {e}")
        return 1
    finally:
        await client.disconnect()

    print("\n=== Done ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
