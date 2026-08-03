"""Rolling 6h market bias: BUY_ONLY | SELL_ONLY | NO_TRADE."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Literal, Optional

import pandas as pd

from bias.regime_24h import RegimeState
from config import settings
from indicators.atr import compute_atr
from indicators.ema import compute_ema
from indicators.rsi import compute_rsi
from indicators.structure import detect_structure

BiasDirection = Literal["BUY_ONLY", "SELL_ONLY", "NO_TRADE"]


@dataclass
class BiasState:
    direction: BiasDirection
    bias_id: str
    range_high: float
    range_low: float
    atr_6h: float
    return_6h: float
    structure_trend: str
    ema_aligned_up: bool
    ema_aligned_down: bool
    rsi: float
    reasons: list[str] = field(default_factory=list)
    features: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "direction": self.direction,
            "bias_id": self.bias_id,
            "range_high": self.range_high,
            "range_low": self.range_low,
            "atr_6h": round(self.atr_6h, 6),
            "return_6h": round(self.return_6h, 6),
            "structure_trend": self.structure_trend,
            "ema_aligned_up": self.ema_aligned_up,
            "ema_aligned_down": self.ema_aligned_down,
            "rsi": round(self.rsi, 2),
            "reasons": self.reasons,
            "features": self.features,
        }


def _bias_id(direction: str, epoch: int, range_high: float, range_low: float) -> str:
    raw = f"{direction}:{epoch}:{range_high:.5f}:{range_low:.5f}"
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def compute_bias_6h(
    df_5m: pd.DataFrame,
    regime: RegimeState,
    *,
    bar_minutes: int = 5,
    hours: int | None = None,
    deadzone_atr_frac: float | None = None,
    prev_bias: Optional[BiasState] = None,
) -> BiasState:
    hours = hours if hours is not None else int(settings.BIAS_LOOKBACK_HOURS)
    deadzone = (
        deadzone_atr_frac
        if deadzone_atr_frac is not None
        else float(settings.BIAS_DEADZONE_ATR_FRAC)
    )
    bars_needed = max(40, int(hours * 60 / max(bar_minutes, 1)))
    epoch = int(df_5m["epoch"].iloc[-1]) if df_5m is not None and "epoch" in df_5m.columns and len(df_5m) else 0

    if df_5m is None or len(df_5m) < bars_needed:
        return BiasState(
            direction="NO_TRADE",
            bias_id=_bias_id("NO_TRADE", epoch, 0, 0),
            range_high=0.0,
            range_low=0.0,
            atr_6h=0.0,
            return_6h=0.0,
            structure_trend="sideways",
            ema_aligned_up=False,
            ema_aligned_down=False,
            rsi=50.0,
            reasons=["insufficient_bars_for_6h_bias"],
        )

    # Block entries in range/compression regimes at bias level
    if regime.label in ("range", "compression", "unknown"):
        return BiasState(
            direction="NO_TRADE",
            bias_id=_bias_id("NO_TRADE", epoch, 0, 0),
            range_high=float(df_5m["high"].astype(float).iloc[-bars_needed:].max()),
            range_low=float(df_5m["low"].astype(float).iloc[-bars_needed:].min()),
            atr_6h=regime.atr,
            return_6h=0.0,
            structure_trend=regime.structure_trend,
            ema_aligned_up=regime.ema_aligned_up,
            ema_aligned_down=regime.ema_aligned_down,
            rsi=50.0,
            reasons=[f"regime_blocks_bias:{regime.label}"],
            features={"regime": regime.label},
        )

    window = df_5m.iloc[-bars_needed:].copy()
    h = window["high"].astype(float)
    l = window["low"].astype(float)
    c = window["close"].astype(float)
    o0 = float(window["open"].astype(float).iloc[0])
    c1 = float(c.iloc[-1])
    ret = (c1 - o0) / o0 if o0 else 0.0
    range_high = float(h.max())
    range_low = float(l.min())

    atr = compute_atr(h, l, c, 14)
    atr_6h = float(atr.iloc[-1]) if len(atr) and pd.notna(atr.iloc[-1]) else 0.0
    ema9 = compute_ema(c, 9)
    ema21 = compute_ema(c, 21)
    ema50 = compute_ema(c, 50)
    e9, e21, e50 = float(ema9.iloc[-1]), float(ema21.iloc[-1]), float(ema50.iloc[-1])
    aligned_up = e9 > e21 > e50
    aligned_down = e9 < e21 < e50
    structure = detect_structure(h, l, c, lookback=min(48, len(window)))
    rsi_s = compute_rsi(c, 14)
    rsi = float(rsi_s.iloc[-1]) if len(rsi_s) and pd.notna(rsi_s.iloc[-1]) else 50.0

    reasons: list[str] = [
        f"return_6h={ret:.4%}",
        f"atr_6h={atr_6h:.5f}",
        f"structure={structure.trend}",
    ]
    features = {
        "regime": regime.label,
        "return_6h": ret,
        "atr_6h": atr_6h,
        "range_high": range_high,
        "range_low": range_low,
        "hh": structure.higher_highs,
        "hl": structure.higher_lows,
        "lh": structure.lower_highs,
        "ll": structure.lower_lows,
        "rsi": rsi,
    }

    # Dead zone: move too small vs ATR
    move = abs(c1 - o0)
    if atr_6h > 0 and move < deadzone * atr_6h:
        direction: BiasDirection = "NO_TRADE"
        reasons.append("deadzone_flat_6h")
    elif (
        aligned_up
        and ret > 0
        and (structure.higher_highs or structure.higher_lows)
        and not (structure.lower_highs and structure.lower_lows)
        and structure.trend in ("up", "sideways")
        and regime.label in ("strong_bull", "weak_trend", "expansion")
    ):
        direction = "BUY_ONLY"
        reasons.append("bull_bias_aligned")
    elif (
        aligned_down
        and ret < 0
        and (structure.lower_highs or structure.lower_lows)
        and not (structure.higher_highs and structure.higher_lows)
        and structure.trend in ("down", "sideways")
        and regime.label in ("strong_bear", "weak_trend", "expansion")
    ):
        direction = "SELL_ONLY"
        reasons.append("bear_bias_aligned")
    else:
        direction = "NO_TRADE"
        reasons.append("no_clear_6h_bias")

    # Keep prior bias_id while direction unchanged (thesis continuity)
    bid = _bias_id(direction, epoch // (hours * 3600), range_high, range_low)
    if prev_bias and prev_bias.direction == direction and direction != "NO_TRADE":
        bid = prev_bias.bias_id
        reasons.append("bias_thesis_continued")

    return BiasState(
        direction=direction,
        bias_id=bid,
        range_high=range_high,
        range_low=range_low,
        atr_6h=atr_6h,
        return_6h=ret,
        structure_trend=structure.trend,
        ema_aligned_up=aligned_up,
        ema_aligned_down=aligned_down,
        rsi=rsi,
        reasons=reasons,
        features=features,
    )
