"""When an instrument is actually tradable.

Synthetic indices run continuously, so the engine was built assuming a feed that
never stops. Forex and metals close from late Friday to late Sunday, and treating
that silence as a dead connection would make the watchdogs reconnect in a loop.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from config import settings
from risk.gate import is_forex_symbol

# Deriv forex runs from late Sunday to Friday 20:55 UTC, with a short daily roll
# around the same time. Held a few minutes wide of the published edges so the
# engine is never mid-order when the book closes.
FOREX_CLOSE_HOUR = 20
FOREX_CLOSE_MINUTE = 55
FOREX_OPEN_HOUR = 21
FOREX_OPEN_MINUTE = 5

_FRIDAY = 4
_SATURDAY = 5
_SUNDAY = 6


def _minutes(dt: datetime) -> int:
    return dt.hour * 60 + dt.minute


_CLOSE_AT = FOREX_CLOSE_HOUR * 60 + FOREX_CLOSE_MINUTE
_OPEN_AT = FOREX_OPEN_HOUR * 60 + FOREX_OPEN_MINUTE


def is_market_open(symbol: str, now: datetime | None = None) -> bool:
    """True when the venue is quoting this symbol."""
    if not is_forex_symbol(symbol):
        return True

    now = now or datetime.now(timezone.utc)
    weekday = now.weekday()
    minute_of_day = _minutes(now)

    if weekday == _SATURDAY:
        return False
    if weekday == _SUNDAY:
        return minute_of_day >= _OPEN_AT
    if weekday == _FRIDAY:
        return minute_of_day < _CLOSE_AT
    # Monday to Thursday, bar the daily roll.
    return not (_CLOSE_AT <= minute_of_day < _OPEN_AT)


def should_flatten_for_weekend(
    symbol: str, now: datetime | None = None, minutes_before: int | None = None
) -> bool:
    """True in the run-up to Friday's close, when open forex risk should be cut.

    A multiplier stop is a dollar limit on the contract, not a guaranteed exit
    price. Monday's open can gap straight past it, so exposure carried across the
    weekend is risk the stop does not actually bound.
    """
    if not is_forex_symbol(symbol):
        return False
    now = now or datetime.now(timezone.utc)
    if now.weekday() != _FRIDAY:
        return False
    window = (
        settings.FOREX_WEEKEND_FLATTEN_MINUTES
        if minutes_before is None
        else minutes_before
    )
    return _CLOSE_AT - int(window) <= _minutes(now) < _CLOSE_AT


def next_open(symbol: str, now: datetime | None = None) -> datetime | None:
    """When the symbol next quotes, or None if it is already open."""
    now = now or datetime.now(timezone.utc)
    if is_market_open(symbol, now):
        return None

    candidate = now.replace(
        hour=FOREX_OPEN_HOUR, minute=FOREX_OPEN_MINUTE, second=0, microsecond=0
    )
    if candidate <= now:
        candidate += timedelta(days=1)
    # Step to the next day that is actually open at the reopen time.
    for _ in range(8):
        if is_market_open(symbol, candidate):
            return candidate
        candidate += timedelta(days=1)
    return None


def seconds_until_open(symbol: str, now: datetime | None = None) -> int:
    """Seconds until the symbol quotes again; 0 when already open."""
    now = now or datetime.now(timezone.utc)
    upcoming = next_open(symbol, now)
    if upcoming is None:
        return 0
    return max(0, int((upcoming - now).total_seconds()))


def market_status(symbols: list[str], now: datetime | None = None) -> dict:
    """Per-symbol open/closed summary for status endpoints and preflight."""
    now = now or datetime.now(timezone.utc)
    return {
        symbol: {
            "open": is_market_open(symbol, now),
            "seconds_until_open": seconds_until_open(symbol, now),
        }
        for symbol in symbols
    }
