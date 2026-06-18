"""MACD (12, 26, 9) standard EMA-based."""

from __future__ import annotations

import pandas as pd


def compute_macd(
    close: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def detect_bullish_crossover(
    macd_line: pd.Series, signal_line: pd.Series
) -> bool:
    """True if MACD crossed above signal on the latest bar."""
    if len(macd_line) < 2:
        return False
    prev_diff = macd_line.iloc[-2] - signal_line.iloc[-2]
    curr_diff = macd_line.iloc[-1] - signal_line.iloc[-1]
    return prev_diff <= 0 and curr_diff > 0


def detect_bearish_crossover(
    macd_line: pd.Series, signal_line: pd.Series
) -> bool:
    if len(macd_line) < 2:
        return False
    prev_diff = macd_line.iloc[-2] - signal_line.iloc[-2]
    curr_diff = macd_line.iloc[-1] - signal_line.iloc[-1]
    return prev_diff >= 0 and curr_diff < 0
