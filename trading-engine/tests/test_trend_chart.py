"""The trend forecast must be comparable across instruments and volatilities."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from analysis.trend_chart import (
    FORECAST_CAP,
    TREND_SPEEDS,
    brief_text,
    read_trend,
)


def _frame(closes: list[float], spread: float = 0.0005) -> pd.DataFrame:
    closes = [float(c) for c in closes]
    return pd.DataFrame(
        {
            "epoch": [1700000000 + i * 14400 for i in range(len(closes))],
            "open": closes,
            "high": [c + spread for c in closes],
            "low": [c - spread for c in closes],
            "close": closes,
        }
    )


def _rising(n: int = 200, start: float = 1.10, step: float = 0.0004) -> pd.DataFrame:
    return _frame([start + i * step for i in range(n)])


def _falling(n: int = 200, start: float = 1.30, step: float = 0.0004) -> pd.DataFrame:
    return _frame([start - i * step for i in range(n)])


def _choppy(n: int = 200, start: float = 1.20) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    # A mean-reverting walk: no persistent direction for the crossover to find.
    closes, level = [], start
    for _ in range(n):
        level += rng.normal(0, 0.0004) - (level - start) * 0.25
        closes.append(level)
    return _frame(closes)


def test_a_rising_market_reads_long_and_a_falling_one_short():
    up = read_trend(_rising(), "frxEURUSD", multiplier=100)
    down = read_trend(_falling(), "frxGBPUSD", multiplier=100)
    assert up is not None and down is not None
    assert up.direction == "long"
    assert up.forecast > 0
    assert down.direction == "short"
    assert down.forecast < 0


def test_a_directionless_market_reads_flat():
    read = read_trend(_choppy(), "frxEURUSD", multiplier=100)
    assert read is not None
    assert read.direction == "flat"
    assert read.stop is None and read.target is None
    assert read.strength == "none"


def test_forecast_is_volatility_normalised_so_instruments_compare():
    """The same trend shape at a different price scale must score the same.

    Without dividing by volatility, USDJPY's larger absolute moves would always
    outrank EURUSD's regardless of how strong either trend is.
    """
    small = read_trend(_rising(start=1.10, step=0.0004), "frxEURUSD", multiplier=100)
    # Same relative trend and same relative range, a hundred times the price.
    large = read_trend(
        _frame([110.0 + i * 0.04 for i in range(200)], spread=0.05),
        "frxUSDJPY",
        multiplier=100,
    )
    assert small is not None and large is not None
    assert small.forecast == pytest.approx(large.forecast, rel=0.02)


def test_forecast_is_capped_so_one_violent_move_cannot_dominate():
    read = read_trend(_rising(step=0.02), "frxEURUSD", multiplier=100)
    assert read is not None
    assert abs(read.forecast) <= FORECAST_CAP


def test_each_speed_is_scored_separately():
    read = read_trend(_rising(), "frxEURUSD", multiplier=100)
    assert read is not None
    assert [(s.fast, s.slow) for s in read.speeds] == list(TREND_SPEEDS)
    assert read.forecast == pytest.approx(
        sum(s.forecast for s in read.speeds) / len(read.speeds)
    )


def test_stop_is_sized_from_the_supplied_horizon_not_the_bar_size():
    """A 4h ATR would put a swing stop inside a single day's noise."""
    df = _rising()
    own = read_trend(df, "frxEURUSD", multiplier=100)
    daily = read_trend(df, "frxEURUSD", multiplier=100, stop_atr=0.0060)
    assert own is not None and daily is not None
    assert abs(daily.price - daily.stop) == pytest.approx(0.0060, abs=1e-6)
    assert abs(daily.price - daily.stop) > abs(own.price - own.stop)


def test_target_sits_at_the_reward_ratio():
    read = read_trend(_rising(), "frxEURUSD", multiplier=100, reward_ratio=1.5)
    assert read is not None
    risk = read.price - read.stop
    reward = read.target - read.price
    assert reward == pytest.approx(risk * 1.5)


def test_a_stop_too_wide_for_the_contract_is_flagged_not_silently_shrunk():
    # A stop of 4% of price cannot fit inside a x100 contract's 1% of room.
    read = read_trend(_rising(), "frxEURUSD", multiplier=100, stop_atr=0.045)
    assert read is not None
    assert read.direction == "long"
    assert read.encodable is False


def test_insufficient_history_returns_nothing_rather_than_a_guess():
    assert read_trend(_rising(n=40), "frxEURUSD", multiplier=100) is None


def test_brief_counts_tradable_flat_and_blocked():
    reads = [
        read_trend(_rising(), "frxEURUSD", multiplier=100),
        read_trend(_choppy(), "frxGBPUSD", multiplier=100),
        read_trend(_falling(), "frxAUDUSD", multiplier=100, stop_atr=0.045),
    ]
    text = brief_text([r for r in reads if r], header="test")
    assert "1 tradable, 1 no trend, 1 blocked" in text
    assert "not evidence that trading it pays" in text


def test_brief_handles_having_nothing_to_say():
    assert "enough history" in brief_text([])
