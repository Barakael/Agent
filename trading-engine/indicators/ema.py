"""EMA / SMA helpers."""

from __future__ import annotations

import pandas as pd


def compute_ema(series: pd.Series, period: int) -> pd.Series:
    return series.astype(float).ewm(span=period, adjust=False).mean()


def compute_sma(series: pd.Series, period: int) -> pd.Series:
    return series.astype(float).rolling(period).mean()
