"""Tests for 8h structure+ATR forward projection and soft gate."""

from __future__ import annotations

import numpy as np
import pandas as pd

from analysis.horizon_projection import (
    HorizonProjection,
    compute_horizon_projection,
    projection_agrees_with_bias,
)
from analysis.horizon_review import compute_8h_review
from config import settings


def _epochs(n: int, bar_sec: int = 300) -> list[int]:
    base = 1_700_000_000
    base = base - (base % (8 * 3600))
    end = base + (n - 1) * bar_sec
    end = end - (end % (8 * 3600))
    start = end - (n - 1) * bar_sec
    return [start + i * bar_sec for i in range(n)]


def _ohlc_trend(n: int = 120, up: bool = True, step: float = 0.4) -> pd.DataFrame:
    """Strong monotonic trend so EMAs + structure stack cleanly."""
    closes = []
    price = 100.0
    delta = step if up else -step
    for i in range(n):
        price += delta
        # tiny noise that does not reverse structure
        closes.append(price + (0.02 if i % 5 == 0 else 0.0))
    closes = np.array(closes, dtype=float)
    opens = np.concatenate([[closes[0] - delta], closes[:-1]])
    highs = np.maximum(opens, closes) + 0.15
    lows = np.minimum(opens, closes) - 0.15
    return pd.DataFrame(
        {
            "epoch": _epochs(n),
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
        }
    )


def test_uptrend_projects_up_with_bull_above_entry():
    df = _ohlc_trend(120, up=True)
    proj = compute_horizon_projection(df, lookback_hours=8, forward_hours=6)
    assert proj.direction == "up"
    assert proj.horizon_hours == 6
    assert proj.bull > proj.entry_now
    assert proj.base > proj.entry_now
    assert proj.invalidation < proj.entry_now
    assert proj.invalidation <= proj.range_low + 1e-6 or proj.invalidation < proj.entry_now
    d = proj.to_dict()
    assert d["direction"] == "up"
    assert "pointers" in d and d["pointers"]


def test_flat_deadzone_projects_flat():
    n = 120
    closes = 100.0 + np.zeros(n)
    df = pd.DataFrame(
        {
            "epoch": _epochs(n),
            "open": closes.copy(),
            "high": closes + 0.05,
            "low": closes - 0.05,
            "close": closes,
        }
    )
    proj = compute_horizon_projection(df, lookback_hours=8, forward_hours=6)
    assert proj.direction == "flat"
    assert proj.extent_pts == 0.0

    ok_buy, _, failed_buy = projection_agrees_with_bias("BUY_ONLY", proj, stance_8h="FAVOR_BUY")
    ok_sell, _, failed_sell = projection_agrees_with_bias(
        "SELL_ONLY", proj, stance_8h="FAVOR_SELL"
    )
    assert ok_buy is False
    assert ok_sell is False
    assert "projection_not_aligned" in failed_buy
    assert "projection_not_aligned" in failed_sell


def test_soft_gate_buy_rejects_down_projection():
    down = HorizonProjection(
        direction="down",
        lookback_hours=8,
        horizon_hours=6,
        entry_now=100.0,
        atr=1.0,
        range_high=102.0,
        range_low=98.0,
        ema21=100.5,
        bull=101.0,
        base=99.0,
        bear=98.0,
        extent_pts=1.0,
        extent_pct=0.01,
        invalidation=102.0,
    )
    ok, passed, failed = projection_agrees_with_bias(
        "BUY_ONLY", down, stance_8h="FAVOR_BUY"
    )
    assert ok is False
    assert "projection_not_aligned" in failed
    assert "projection:down" in passed


def test_soft_gate_buy_accepts_up_when_stance_ok():
    up = HorizonProjection(
        direction="up",
        lookback_hours=8,
        horizon_hours=6,
        entry_now=100.0,
        atr=1.0,
        range_high=102.0,
        range_low=98.0,
        ema21=99.5,
        bull=102.0,
        base=101.0,
        bear=99.0,
        extent_pts=1.0,
        extent_pct=0.01,
        invalidation=98.0,
    )
    ok, passed, failed = projection_agrees_with_bias(
        "BUY_ONLY", up, stance_8h="FAVOR_BUY"
    )
    assert ok is True
    assert failed == []
    assert "projection_aligned" in passed


def test_soft_gate_stand_aside_blocks():
    up = HorizonProjection(
        direction="up",
        lookback_hours=8,
        horizon_hours=6,
        entry_now=100.0,
        atr=1.0,
        range_high=102.0,
        range_low=98.0,
        ema21=99.5,
        bull=102.0,
        base=101.0,
        bear=99.0,
        extent_pts=1.0,
        extent_pct=0.01,
        invalidation=98.0,
    )
    ok, _, failed = projection_agrees_with_bias(
        "BUY_ONLY", up, stance_8h="STAND_ASIDE"
    )
    assert ok is False
    assert "projection_not_aligned" in failed


def test_horizon_review_attaches_projection():
    assert settings.PROJECTION_ENABLED is True
    df = _ohlc_trend(120, up=True)
    rev = compute_8h_review("R_50", df, hours=8)
    assert rev.projection is not None
    assert "direction" in rev.projection
    assert "projection" in rev.to_dict()
