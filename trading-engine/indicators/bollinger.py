"""Bollinger Bands."""

from __future__ import annotations

import pandas as pd

from indicators.ema import compute_sma


def compute_bollinger(
    close: pd.Series,
    period: int = 20,
    stdev: float = 2.0,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    mid = compute_sma(close, period)
    std = close.astype(float).rolling(period).std()
    upper = mid + stdev * std
    lower = mid - stdev * std
    return upper, mid, lower
