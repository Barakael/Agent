"""Forex closes at weekends; synthetics do not."""

from __future__ import annotations

from datetime import datetime, timezone

from risk.market_hours import (
    is_market_open,
    market_status,
    next_open,
    seconds_until_open,
    should_flatten_for_weekend,
)


def _at(day: int, hour: int, minute: int = 0) -> datetime:
    """A datetime in a week where 2026-08-10 is the Monday."""
    return datetime(2026, 8, 10 + day, hour, minute, tzinfo=timezone.utc)


def test_synthetics_are_always_open():
    for day in range(7):
        assert is_market_open("R_50", _at(day, 3)) is True
    assert seconds_until_open("R_50", _at(5, 12)) == 0
    assert next_open("R_50", _at(5, 12)) is None


def test_forex_is_shut_all_saturday():
    for hour in (0, 6, 12, 23):
        assert is_market_open("frxEURUSD", _at(5, hour)) is False


def test_forex_reopens_late_sunday():
    assert is_market_open("frxEURUSD", _at(6, 20, 0)) is False
    assert is_market_open("frxEURUSD", _at(6, 21, 4)) is False
    assert is_market_open("frxEURUSD", _at(6, 21, 5)) is True
    assert is_market_open("frxEURUSD", _at(6, 23, 0)) is True


def test_forex_closes_friday_evening():
    assert is_market_open("frxEURUSD", _at(4, 20, 54)) is True
    assert is_market_open("frxEURUSD", _at(4, 20, 55)) is False
    assert is_market_open("frxEURUSD", _at(4, 23, 0)) is False


def test_weekday_daily_roll_is_closed():
    assert is_market_open("frxEURUSD", _at(1, 20, 54)) is True
    assert is_market_open("frxEURUSD", _at(1, 20, 57)) is False
    assert is_market_open("frxEURUSD", _at(1, 21, 5)) is True


def test_metals_follow_the_forex_calendar():
    assert is_market_open("frxXAUUSD", _at(5, 12)) is False
    assert is_market_open("frxXAUUSD", _at(2, 12)) is True


def test_seconds_until_open_spans_the_weekend():
    # Saturday noon to Sunday 21:05 is 33h05m.
    assert seconds_until_open("frxEURUSD", _at(5, 12)) == (33 * 3600) + (5 * 60)


def test_next_open_from_friday_night_is_sunday():
    upcoming = next_open("frxEURUSD", _at(4, 22, 0))
    assert upcoming is not None
    assert upcoming.weekday() == 6
    assert (upcoming.hour, upcoming.minute) == (21, 5)


def test_weekend_flatten_window_is_the_run_up_to_friday_close():
    assert should_flatten_for_weekend("frxEURUSD", _at(4, 20, 30), 20) is False
    assert should_flatten_for_weekend("frxEURUSD", _at(4, 20, 35), 20) is True
    assert should_flatten_for_weekend("frxEURUSD", _at(4, 20, 54), 20) is True
    # Once shut there is nothing left to flatten.
    assert should_flatten_for_weekend("frxEURUSD", _at(4, 20, 55), 20) is False
    assert should_flatten_for_weekend("frxEURUSD", _at(3, 20, 40), 20) is False


def test_synthetics_are_never_flattened_for_the_weekend():
    assert should_flatten_for_weekend("R_50", _at(4, 20, 40), 20) is False


def test_market_status_reports_each_symbol():
    status = market_status(["R_50", "frxEURUSD"], _at(5, 12))
    assert status["R_50"]["open"] is True
    assert status["frxEURUSD"]["open"] is False
    assert status["frxEURUSD"]["seconds_until_open"] > 0
