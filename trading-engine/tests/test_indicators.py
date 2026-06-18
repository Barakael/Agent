import pandas as pd
import pytest

from indicators.macd import compute_macd, detect_bullish_crossover
from indicators.rsi import compute_rsi


def test_rsi_range():
    close = pd.Series([float(i) for i in range(1, 50)])
    rsi = compute_rsi(close, 14)
    assert 0 <= rsi.iloc[-1] <= 100


def test_macd_length():
    close = pd.Series([1.0 + i * 0.001 for i in range(50)])
    macd, signal, hist = compute_macd(close)
    assert len(macd) == len(close)


def test_bullish_crossover_detection():
    macd = pd.Series([0.0, -0.1, 0.05])
    signal = pd.Series([0.0, 0.0, 0.0])
    assert bool(detect_bullish_crossover(macd, signal)) is True
