"""SL/TP from 6h bias envelope (matches hold timeframe)."""

from __future__ import annotations

from bias.bias_6h import BiasState
from config import settings
from signals.engine import SignalDirection

MIN_RR = 1.5  # never ship a target closer than 1.5x the stop


def bias_sl_tp(
    bias: BiasState,
    entry: float,
    direction: SignalDirection,
    *,
    atr_mult: float | None = None,
    rr: float | None = None,
    rr = max(rr if rr is not None else float(settings.DEFAULT_RR_RATIO), MIN_RR)
    atr_mult = atr_mult if atr_mult is not None else float(settings.BIAS_SL_ATR_MULT)
    rr = rr if rr is not None else float(settings.DEFAULT_RR_RATIO)
    atr = max(float(bias.atr_6h or 0.0), 1e-8)
    method = "bias_6h_atr"

    if direction == SignalDirection.BUY:
        swing_sl = float(bias.range_low) - 0.05 * atr
        atr_sl = entry - atr_mult * atr
        sl = min(swing_sl, atr_sl) if swing_sl < entry else atr_sl
        if swing_sl < entry:
            method = "bias_6h_swing"
        risk = max(entry - sl, 1e-8)
        tp = entry + rr * risk
    else:
        swing_sl = float(bias.range_high) + 0.05 * atr
        atr_sl = entry + atr_mult * atr
        sl = max(swing_sl, atr_sl) if swing_sl > entry else atr_sl
        if swing_sl > entry:
            method = "bias_6h_swing"
        risk = max(sl - entry, 1e-8)
        tp = entry - rr * risk
    return sl, tp, method
