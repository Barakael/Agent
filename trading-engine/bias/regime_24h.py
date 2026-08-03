"""Rolling 24h market regime classification from 5m OHLC."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import pandas as pd

from indicators.atr import compute_atr
from indicators.ema import compute_ema
from indicators.structure import detect_structure

RegimeLabel = Literal[
    "strong_bull",
    "strong_bear",
    "weak_trend",
    "range",
    "expansion",
    "compression",
    "unknown",
]


@dataclass
class RegimeState:
    label: RegimeLabel
    return_24h: float
    atr: float
    atr_ratio: float
    ema_aligned_up: bool
    ema_aligned_down: bool
    structure_trend: str
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "return_24h": round(self.return_24h, 6),
            "atr": round(self.atr, 6),
            "atr_ratio": round(self.atr_ratio, 4),
            "ema_aligned_up": self.ema_aligned_up,
            "ema_aligned_down": self.ema_aligned_down,
            "structure_trend": self.structure_trend,
            "reasons": self.reasons,
        }


def compute_regime_24h(
    df_5m: pd.DataFrame,
    *,
    bar_minutes: int = 5,
    hours: int = 24,
) -> RegimeState:
    bars_needed = max(60, int(hours * 60 / max(bar_minutes, 1)))
    if df_5m is None or len(df_5m) < bars_needed:
        return RegimeState(
            label="unknown",
            return_24h=0.0,
            atr=0.0,
            atr_ratio=1.0,
            ema_aligned_up=False,
            ema_aligned_down=False,
            structure_trend="sideways",
            reasons=["insufficient_bars_for_24h_regime"],
        )

    window = df_5m.iloc[-bars_needed:].copy()
    h = window["high"].astype(float)
    l = window["low"].astype(float)
    c = window["close"].astype(float)
    open0 = float(window["open"].astype(float).iloc[0])
    close1 = float(c.iloc[-1])
    ret = (close1 - open0) / open0 if open0 else 0.0

    atr = compute_atr(h, l, c, 14)
    atr_val = float(atr.iloc[-1]) if len(atr) and pd.notna(atr.iloc[-1]) else 0.0
    atr_sma = atr.rolling(20).mean()
    atr_sma_val = float(atr_sma.iloc[-1]) if len(atr_sma) and pd.notna(atr_sma.iloc[-1]) else atr_val
    atr_ratio = atr_val / atr_sma_val if atr_sma_val > 0 else 1.0

    ema9 = compute_ema(c, 9)
    ema21 = compute_ema(c, 21)
    ema50 = compute_ema(c, 50)
    e9, e21, e50 = float(ema9.iloc[-1]), float(ema21.iloc[-1]), float(ema50.iloc[-1])
    aligned_up = e9 > e21 > e50
    aligned_down = e9 < e21 < e50

    structure = detect_structure(h, l, c, lookback=min(80, len(window)))
    reasons: list[str] = [
        f"return_24h={ret:.4%}",
        f"atr_ratio={atr_ratio:.2f}",
        f"structure={structure.trend}",
    ]

    # Compression / expansion first
    if atr_ratio < 0.75 and abs(ret) < 0.003:
        return RegimeState(
            "compression", ret, atr_val, atr_ratio, aligned_up, aligned_down, structure.trend, reasons + ["ATR compressed"]
        )
    if atr_ratio >= 1.5:
        label: RegimeLabel = "expansion"
        if aligned_up and ret > 0:
            label = "strong_bull"
            reasons.append("expansion_with_bull_stack")
        elif aligned_down and ret < 0:
            label = "strong_bear"
            reasons.append("expansion_with_bear_stack")
        return RegimeState(label, ret, atr_val, atr_ratio, aligned_up, aligned_down, structure.trend, reasons)

    # Strong / weak trend vs range
    if aligned_up and structure.higher_highs and structure.higher_lows and ret > 0.004:
        return RegimeState(
            "strong_bull", ret, atr_val, atr_ratio, aligned_up, aligned_down, structure.trend, reasons + ["HH_HL_bull"]
        )
    if aligned_down and structure.lower_highs and structure.lower_lows and ret < -0.004:
        return RegimeState(
            "strong_bear", ret, atr_val, atr_ratio, aligned_up, aligned_down, structure.trend, reasons + ["LH_LL_bear"]
        )
    if (aligned_up or aligned_down) and structure.trend in ("up", "down"):
        return RegimeState(
            "weak_trend", ret, atr_val, atr_ratio, aligned_up, aligned_down, structure.trend, reasons + ["soft_trend"]
        )
    if abs(ret) < 0.002 and atr_ratio < 1.2:
        return RegimeState(
            "range", ret, atr_val, atr_ratio, aligned_up, aligned_down, structure.trend, reasons + ["sideways"]
        )
    return RegimeState(
        "weak_trend" if (aligned_up or aligned_down) else "range",
        ret,
        atr_val,
        atr_ratio,
        aligned_up,
        aligned_down,
        structure.trend,
        reasons,
    )
