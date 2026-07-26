"""MarketSnapshot — single source of truth for all strategy math."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Optional

import pandas as pd

MarketRegime = Literal["trending", "ranging", "breakout", "quiet"]
TrendDirection = Literal["up", "down", "sideways"]


@dataclass
class MarketSnapshot:
    symbol: str
    epoch: int
    open: float
    high: float
    low: float
    close: float
    volume: float

    ema_9: float
    ema_21: float
    ema_50: float
    sma_20: float

    rsi: float
    atr: float
    atr_sma: float

    macd: float
    macd_signal: float
    macd_hist: float
    macd_hist_prev: float
    macd_bull_cross: bool
    macd_bear_cross: bool

    bb_upper: float
    bb_mid: float
    bb_lower: float
    bb_width: float
    bb_mid_slope: float

    support: float
    resistance: float
    swing_low: float
    swing_high: float
    structure_trend: TrendDirection
    higher_highs: bool
    higher_lows: bool
    lower_highs: bool
    lower_lows: bool

    ema_aligned_up: bool
    ema_aligned_down: bool
    trend_direction: TrendDirection

    regime: MarketRegime
    regime_reasons: list[str] = field(default_factory=list)

    # Candle patterns on latest bar
    pin_bar: Optional[str] = None
    engulfing: Optional[str] = None
    inside_bar: bool = False
    break_of_structure_up: bool = False
    break_of_structure_down: bool = False

    # Raw frame retained for HTF / lookback strategies
    df: Optional[pd.DataFrame] = field(default=None, repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "epoch": self.epoch,
            "ohlcv": {
                "open": self.open,
                "high": self.high,
                "low": self.low,
                "close": self.close,
                "volume": self.volume,
            },
            "ema_9": round(self.ema_9, 6),
            "ema_21": round(self.ema_21, 6),
            "ema_50": round(self.ema_50, 6),
            "sma_20": round(self.sma_20, 6),
            "rsi": round(self.rsi, 2),
            "atr": round(self.atr, 6),
            "macd": round(self.macd, 6),
            "macd_signal": round(self.macd_signal, 6),
            "bb_upper": round(self.bb_upper, 6),
            "bb_mid": round(self.bb_mid, 6),
            "bb_lower": round(self.bb_lower, 6),
            "support": round(self.support, 6),
            "resistance": round(self.resistance, 6),
            "trend_direction": self.trend_direction,
            "structure_trend": self.structure_trend,
            "regime": self.regime,
            "regime_reasons": self.regime_reasons,
            "pin_bar": self.pin_bar,
            "engulfing": self.engulfing,
            "inside_bar": self.inside_bar,
        }
