"""Tests for independent mid (4/6h) and 8h horizon reviews."""

from __future__ import annotations

import numpy as np
import pandas as pd

from analysis.horizon_review import (
    compute_8h_review,
    compute_horizon_review,
    compute_mid_review,
    is_horizon_bar_close,
)


def _epochs(n: int, bar_sec: int = 300) -> list[int]:
    base = 1_700_000_000
    base = base - (base % (8 * 3600))
    end = base + (n - 1) * bar_sec
    # Align end to 8h boundary so last bar can be both mid and long close when applicable
    end = end - (end % (8 * 3600))
    start = end - (n - 1) * bar_sec
    return [start + i * bar_sec for i in range(n)]


def _ohlc_zigzag(n: int = 200, up: bool = True) -> pd.DataFrame:
    price = 100.0
    closes = []
    step = 0.35 if up else -0.35
    pull = -0.08 if up else 0.08
    while len(closes) < n:
        for _ in range(8):
            price += step
            closes.append(price)
        for _ in range(3):
            price += pull
            closes.append(price)
    closes = np.array(closes[:n], dtype=float)
    opens = np.concatenate([[closes[0]], closes[:-1]])
    highs = np.maximum(opens, closes) + 0.12
    lows = np.minimum(opens, closes) - 0.12
    return pd.DataFrame(
        {
            "epoch": _epochs(n),
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
        }
    )


def test_is_horizon_bar_close_independent_cadences():
    assert is_horizon_bar_close(6 * 3600, 6) is True
    assert is_horizon_bar_close(6 * 3600 + 300, 6) is False
    assert is_horizon_bar_close(8 * 3600, 8) is True
    assert is_horizon_bar_close(8 * 3600, 6) is False  # 8h close is not a 6h close
    assert is_horizon_bar_close(24 * 3600, 6) is True
    assert is_horizon_bar_close(24 * 3600, 8) is True  # both align at day boundary


def test_8h_uptrend_favors_buy():
    df = _ohlc_zigzag(200, up=True)
    rev = compute_8h_review("R_50", df, hours=8)
    assert rev.hours == 8
    assert rev.stance in ("FAVOR_BUY", "STAND_ASIDE")  # structure-dependent
    assert rev.review_id
    assert rev.return_pct > 0
    d = rev.to_dict()
    assert "watch" in d and "reasons" in d


def test_8h_flat_stands_aside():
    n = 200
    closes = 100.0 + np.zeros(n)
    opens = closes.copy()
    df = pd.DataFrame(
        {
            "epoch": _epochs(n),
            "open": opens,
            "high": closes + 0.05,
            "low": closes - 0.05,
            "close": closes,
        }
    )
    rev = compute_horizon_review("R_50", df, hours=8)
    assert rev.stance == "STAND_ASIDE"


def test_mid_and_8h_are_independent_objects():
    df = _ohlc_zigzag(220, up=True)
    mid = compute_mid_review("R_50", df, hours=6)
    long8 = compute_8h_review("R_50", df, hours=8)
    assert mid.hours == 6
    assert long8.hours == 8
    assert mid.review_id != long8.review_id or mid.hours != long8.hours


def test_4h_mid_review_supported():
    df = _ohlc_zigzag(160, up=False)
    rev = compute_mid_review("R_50", df, hours=4)
    assert rev.hours == 4
    assert rev.stance in ("FAVOR_BUY", "FAVOR_SELL", "STAND_ASIDE")
