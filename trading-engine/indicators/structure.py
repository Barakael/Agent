"""Swing support/resistance and market structure (HH/HL / LH/LL)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

import pandas as pd

TrendDirection = Literal["up", "down", "sideways"]


@dataclass
class StructureLevels:
    support: float
    resistance: float
    swing_low: float
    swing_high: float
    trend: TrendDirection
    higher_highs: bool
    higher_lows: bool
    lower_highs: bool
    lower_lows: bool


def _swing_points(series: pd.Series, left: int = 2, right: int = 2) -> list[tuple[int, float]]:
    vals = series.astype(float)
    points: list[tuple[int, float]] = []
    for i in range(left, len(vals) - right):
        window = vals.iloc[i - left : i + right + 1]
        if float(vals.iloc[i]) == float(window.max()) or float(vals.iloc[i]) == float(window.min()):
            points.append((i, float(vals.iloc[i])))
    return points


def detect_structure(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    lookback: int = 40,
) -> StructureLevels:
    h = high.astype(float).iloc[-lookback:]
    l = low.astype(float).iloc[-lookback:]
    c = close.astype(float)

    swing_high = float(h.max())
    swing_low = float(l.min())
    price = float(c.iloc[-1])

    # Nearest structural levels relative to price
    resistance = swing_high
    support = swing_low
    highs = _swing_points(h)
    lows = _swing_points(l)
    above = [p for _, p in highs if p >= price]
    below = [p for _, p in lows if p <= price]
    if above:
        resistance = min(above)
    if below:
        support = max(below)

    # Structure from last two swing highs/lows
    hh = hl = lh = ll = False
    if len(highs) >= 2:
        prev_h, curr_h = highs[-2][1], highs[-1][1]
        hh = curr_h > prev_h
        lh = curr_h < prev_h
    if len(lows) >= 2:
        prev_l, curr_l = lows[-2][1], lows[-1][1]
        hl = curr_l > prev_l
        ll = curr_l < prev_l

    if hh and hl:
        trend: TrendDirection = "up"
    elif lh and ll:
        trend = "down"
    else:
        trend = "sideways"

    return StructureLevels(
        support=support,
        resistance=resistance,
        swing_low=swing_low,
        swing_high=swing_high,
        trend=trend,
        higher_highs=hh,
        higher_lows=hl,
        lower_highs=lh,
        lower_lows=ll,
    )


def detect_pin_bar(open_: float, high: float, low: float, close: float) -> Optional[str]:
    body = abs(close - open_)
    rng = max(high - low, 1e-12)
    upper = high - max(open_, close)
    lower = min(open_, close) - low
    if lower >= 2 * body and lower >= 0.6 * rng:
        return "bullish_pin"
    if upper >= 2 * body and upper >= 0.6 * rng:
        return "bearish_pin"
    return None


def detect_engulfing(
    prev_o: float, prev_c: float, cur_o: float, cur_c: float
) -> Optional[str]:
    bull = prev_c < prev_o and cur_c > cur_o and cur_c >= prev_o and cur_o <= prev_c
    bear = prev_c > prev_o and cur_c < cur_o and cur_c <= prev_o and cur_o >= prev_c
    if bull:
        return "bullish_engulfing"
    if bear:
        return "bearish_engulfing"
    return None


def detect_inside_bar(
    prev_h: float, prev_l: float, cur_h: float, cur_l: float
) -> bool:
    return cur_h <= prev_h and cur_l >= prev_l
