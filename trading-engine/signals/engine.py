"""Signal engine — RSI + MACD confluence on candle close."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional

import pandas as pd

from config import settings
from indicators.macd import (
    compute_macd,
    detect_bearish_crossover,
    detect_bullish_crossover,
)
from indicators.rsi import compute_rsi

logger = logging.getLogger(__name__)


class SignalDirection(str, Enum):
    BUY = "buy"
    SELL = "sell"
    NONE = "none"


@dataclass
class TradeSignal:
    symbol: str
    direction: SignalDirection
    rsi: float
    macd: float
    macd_signal: float
    price: float
    epoch: int
    reason: str

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "direction": self.direction.value,
            "rsi": round(self.rsi, 2),
            "macd": round(self.macd, 6),
            "macd_signal": round(self.macd_signal, 6),
            "price": self.price,
            "epoch": self.epoch,
            "reason": self.reason,
        }


class SignalEngine:
    """Generate signals on MACD crossover with RSI confirmation (single best strategy).

    BUY:  MACD bullish cross and RSI below 55 (not chasing extended upside)
    SELL: MACD bearish cross and RSI above 45 (not chasing extended downside)
    """

    def __init__(self) -> None:
        self.rsi_period = settings.RSI_PERIOD
        self.rsi_oversold = settings.RSI_OVERSOLD
        self.rsi_overbought = settings.RSI_OVERBOUGHT
        self.macd_fast = settings.MACD_FAST
        self.macd_slow = settings.MACD_SLOW
        self.macd_signal_period = settings.MACD_SIGNAL
        # Soft RSI confirmation bands (stricter than oversold/overbought extremes)
        self.rsi_buy_max = 55.0
        self.rsi_sell_min = 45.0

    def evaluate(self, symbol: str, df: pd.DataFrame) -> Optional[TradeSignal]:
        min_bars = max(self.rsi_period, self.macd_slow + self.macd_signal_period) + 2
        if len(df) < min_bars:
            logger.debug("Insufficient bars for %s: %d < %d", symbol, len(df), min_bars)
            return None

        close = df["close"].astype(float)
        rsi_series = compute_rsi(close, self.rsi_period)
        macd_line, signal_line, _ = compute_macd(
            close, self.macd_fast, self.macd_slow, self.macd_signal_period
        )

        rsi_val = float(rsi_series.iloc[-1])
        macd_val = float(macd_line.iloc[-1])
        signal_val = float(signal_line.iloc[-1])
        price = float(close.iloc[-1])
        epoch = int(df["epoch"].iloc[-1])

        bull_cross = detect_bullish_crossover(macd_line, signal_line)
        bear_cross = detect_bearish_crossover(macd_line, signal_line)

        if bull_cross and rsi_val < self.rsi_buy_max:
            return TradeSignal(
                symbol=symbol,
                direction=SignalDirection.BUY,
                rsi=rsi_val,
                macd=macd_val,
                macd_signal=signal_val,
                price=price,
                epoch=epoch,
                reason=f"MACD bullish cross + RSI {rsi_val:.1f} < {self.rsi_buy_max}",
            )

        if bear_cross and rsi_val > self.rsi_sell_min:
            return TradeSignal(
                symbol=symbol,
                direction=SignalDirection.SELL,
                rsi=rsi_val,
                macd=macd_val,
                macd_signal=signal_val,
                price=price,
                epoch=epoch,
                reason=f"MACD bearish cross + RSI {rsi_val:.1f} > {self.rsi_sell_min}",
            )

        return None
