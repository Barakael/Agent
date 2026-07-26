"""Classify market regime from a MarketSnapshot's indicator fields."""

from __future__ import annotations

from typing import Literal

MarketRegime = Literal["trending", "ranging", "breakout", "quiet"]


def detect_regime(
    *,
    atr: float,
    atr_sma: float,
    bb_width: float,
    bb_mid_slope: float,
    ema_aligned_up: bool,
    ema_aligned_down: bool,
    structure_trend: str,
    close: float,
    support: float,
    resistance: float,
    atr_expand_ratio: float = 1.25,
    quiet_atr_ratio: float = 0.75,
    range_slope_max: float = 0.0012,
) -> tuple[MarketRegime, list[str]]:
    reasons: list[str] = []
    atr_ratio = atr / atr_sma if atr_sma > 0 else 1.0
    band = max(resistance - support, 1e-12)
    near_break = close >= resistance - 0.15 * band or close <= support + 0.15 * band

    if atr_ratio < quiet_atr_ratio and abs(bb_mid_slope) < range_slope_max:
        reasons.append(f"ATR compressed ({atr_ratio:.2f}x avg)")
        reasons.append("Flat BB mid — quiet market")
        return "quiet", reasons

    if atr_ratio >= atr_expand_ratio and near_break:
        reasons.append(f"ATR expansion ({atr_ratio:.2f}x avg)")
        reasons.append("Price pressing support/resistance")
        return "breakout", reasons

    if (ema_aligned_up or ema_aligned_down) and structure_trend in ("up", "down"):
        reasons.append("EMA stack aligned")
        reasons.append(f"Structure trend={structure_trend}")
        return "trending", reasons

    if abs(bb_mid_slope) <= range_slope_max and atr_ratio < atr_expand_ratio:
        reasons.append("Sideways BB mid")
        reasons.append("ATR not expanded — ranging")
        return "ranging", reasons

    # Fallback: mild trend without clean structure
    if ema_aligned_up or ema_aligned_down:
        reasons.append("EMA alignment without strong structure")
        return "trending", reasons

    reasons.append("No clear regime — treat as quiet")
    return "quiet", reasons
