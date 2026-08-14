#!/usr/bin/env python3
"""Preflight the live Deriv connection before any forex order is placed.

    python scripts/demo_readiness.py
    python scripts/demo_readiness.py --symbols frxEURUSD,frxXAUUSD

Every check is a fact read from the endpoint, not an assumption:

  * the token authorises, and the account it lands on is a demo account
  * the endpoint's instrument field name (``symbol`` vs ``underlying_symbol``)
  * candles arrive for each symbol at the configured timeframe
  * the configured multiplier is one the venue actually offers per symbol
  * a priced proposal comes back for a minimum stake, with barriers attached
  * the market is open, so a quiet feed is not mistaken for a broken one

Exit code is 0 only when nothing blocks a demo order. Nothing here places one.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone

from config import settings
from data.deriv_ws import DerivWebSocketClient
from execution.multiplier import contract_room_pct, usd_from_pct
from risk.market_hours import is_market_open, seconds_until_open

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")

PASS = "PASS"
FAIL = "FAIL"
WARN = "WARN"


@dataclass
class Check:
    name: str
    status: str
    detail: str


@dataclass
class Report:
    checks: list[Check] = field(default_factory=list)

    def add(self, name: str, status: str, detail: str = "") -> None:
        self.checks.append(Check(name, status, detail))

    @property
    def blocking(self) -> list[Check]:
        return [c for c in self.checks if c.status == FAIL]

    def render(self) -> str:
        width = max((len(c.name) for c in self.checks), default=10)
        lines = [f"  {c.status:<4} {c.name:<{width}}  {c.detail}" for c in self.checks]
        return "\n".join(lines)


def _currency(auth: dict, loginid: str) -> str:
    """Account currency, which the newer endpoint reports per account entry."""
    if not isinstance(auth, dict):
        return ""
    direct = auth.get("currency")
    if direct:
        return str(direct)
    for entry in auth.get("account_list") or []:
        if str(entry.get("loginid")) == loginid and entry.get("currency"):
            return str(entry["currency"])
    return ""


async def _check_account(client: DerivWebSocketClient, report: Report) -> None:
    if not settings.DERIV_API_TOKEN:
        report.add("token", FAIL, "DERIV_API_TOKEN is not set")
        return
    try:
        await client.connect()
        auth = await client.authorize()
    except Exception as exc:  # noqa: BLE001 - surfaced as a failed check
        report.add("authorize", FAIL, f"{type(exc).__name__}: {exc}")
        return

    if client.market_data_only:
        report.add(
            "authorize",
            FAIL,
            "connected for market data only — token did not authorise for trading",
        )
        return

    report.add("authorize", PASS, f"loginid={client.loginid}")
    if client.is_demo:
        report.add("demo account", PASS, f"{client.loginid} balance={client.balance:.2f}")
    else:
        report.add(
            "demo account",
            FAIL,
            f"{client.loginid} is not a demo account — refusing to call it ready",
        )
    report.add("currency", PASS if _currency(auth, client.loginid) == "USD" else WARN,
               _currency(auth, client.loginid) or "not reported")


async def _check_symbol(
    client: DerivWebSocketClient, symbol: str, stake: float, report: Report
) -> None:
    if is_market_open(symbol):
        report.add(f"{symbol} market", PASS, "open")
    else:
        hours = seconds_until_open(symbol) / 3600.0
        report.add(f"{symbol} market", WARN, f"closed — reopens in {hours:.1f}h")

    timeframe = settings.CANDLE_TIMEFRAME_MINUTES
    try:
        candles = await client.get_candles_history(
            symbol, granularity=timeframe * 60, count=50
        )
    except Exception as exc:  # noqa: BLE001
        report.add(f"{symbol} candles", FAIL, f"{type(exc).__name__}: {exc}")
        return
    if not candles:
        report.add(f"{symbol} candles", FAIL, "no candles returned")
        return
    last = candles[-1]
    age_min = (
        datetime.now(timezone.utc).timestamp() - float(last.get("epoch", 0))
    ) / 60.0
    detail = f"{len(candles)} bars @{timeframe}m, last close={last.get('close')} ({age_min:.0f}m old)"
    report.add(f"{symbol} candles", PASS, detail)

    configured = float(settings.DERIV_MULTIPLIER)
    try:
        allowed = await client.get_allowed_multipliers(symbol)
    except Exception as exc:  # noqa: BLE001
        report.add(f"{symbol} multipliers", FAIL, f"{type(exc).__name__}: {exc}")
        allowed = []
    if not allowed:
        report.add(
            f"{symbol} multipliers", WARN, "venue did not report a list; cannot verify"
        )
    elif configured in allowed:
        room_pct = contract_room_pct(configured)
        report.add(
            f"{symbol} multipliers",
            PASS,
            f"x{configured:g} offered (of {', '.join(f'{m:g}' for m in allowed)}); "
            f"liquidates at {room_pct * 100:.2f}% of price "
            f"(${usd_from_pct(stake, configured, room_pct):.2f} on a ${stake:g} stake)",
        )
    else:
        report.add(
            f"{symbol} multipliers",
            FAIL,
            f"x{configured:g} not offered — venue allows {', '.join(f'{m:g}' for m in allowed)}",
        )

    quote = await client._send_for_symbol(
        {
            "proposal": 1,
            "amount": stake,
            "basis": "stake",
            "contract_type": "MULTUP",
            "currency": "USD",
            "multiplier": configured,
        },
        symbol,
    )
    error = quote.get("error") if isinstance(quote, dict) else None
    if isinstance(error, dict):
        report.add(
            f"{symbol} proposal",
            FAIL,
            f"{error.get('code')}: {error.get('message')}",
        )
        return
    proposal = quote.get("proposal") or {}
    report.add(
        f"{symbol} proposal",
        PASS,
        f"spot={proposal.get('spot')} ask={proposal.get('ask_price')} "
        f"commission={proposal.get('commission')}",
    )


async def run(symbols: list[str], stake: float) -> Report:
    report = Report()
    report.add("mode", PASS, f"TRADING_MODE={settings.TRADING_MODE}")
    report.add(
        "require demo",
        PASS if settings.DERIV_REQUIRE_DEMO else WARN,
        str(settings.DERIV_REQUIRE_DEMO),
    )

    client = DerivWebSocketClient()
    try:
        await _check_account(client, report)
        if not report.blocking:
            for symbol in symbols:
                await _check_symbol(client, symbol, stake, report)
            report.add(
                "schema", PASS, f"endpoint names instruments '{client.symbol_key}'"
            )
    finally:
        try:
            await client.disconnect()
        except Exception:  # noqa: BLE001
            pass
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--symbols",
        default="",
        help="comma separated; defaults to the configured trading pairs",
    )
    parser.add_argument(
        "--stake", type=float, default=1.0, help="stake used to price the test proposal"
    )
    args = parser.parse_args()

    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    symbols = symbols or settings.pairs_list

    report = asyncio.run(run(symbols, args.stake))

    print(f"\nDemo readiness — {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC")
    print(f"symbols: {', '.join(symbols)}\n")
    print(report.render())

    blocking = report.blocking
    if blocking:
        print(f"\nNOT READY — {len(blocking)} blocking issue(s):")
        for check in blocking:
            print(f"  - {check.name}: {check.detail}")
        return 1
    warnings = [c for c in report.checks if c.status == WARN]
    print("\nREADY for a demo order." + (f" {len(warnings)} warning(s)." if warnings else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
