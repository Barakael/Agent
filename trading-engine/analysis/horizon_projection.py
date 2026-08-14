"""Structure + ATR forward projection from the last N hours (FX-style pointers).

Scenario analysis only — not a guaranteed price forecast.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal, Optional

import pandas as pd

from config import settings
from indicators.atr import compute_atr
from indicators.ema import compute_ema
from indicators.structure import detect_structure

ProjectionDirection = Literal["up", "down", "flat"]


@dataclass
class HorizonProjection:
    direction: ProjectionDirection
    lookback_hours: int
    horizon_hours: int
    entry_now: float
    atr: float
    range_high: float
    range_low: float
    ema21: float
    bull: float
    base: float
    bear: float
    extent_pts: float
    extent_pct: float
    invalidation: float
    pointers: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "direction": self.direction,
            "lookback_hours": self.lookback_hours,
            "horizon_hours": self.horizon_hours,
            "entry_now": round(self.entry_now, 5),
            "atr": round(self.atr, 6),
            "range_high": round(self.range_high, 5),
            "range_low": round(self.range_low, 5),
            "ema21": round(self.ema21, 5),
            "bull": round(self.bull, 5),
            "base": round(self.base, 5),
            "bear": round(self.bear, 5),
            "extent_pts": round(self.extent_pts, 5),
            "extent_pct": round(self.extent_pct, 6),
            "invalidation": round(self.invalidation, 5),
            "pointers": self.pointers,
            "reasons": self.reasons,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }


def compute_horizon_projection(
    df_5m: pd.DataFrame,
    *,
    lookback_hours: int | None = None,
    forward_hours: int | None = None,
    bar_minutes: int = 5,
    atr_mult: float | None = None,
) -> HorizonProjection:
    """Project next several hours from rolling last-Nh structure + ATR."""
    lookback = lookback_hours if lookback_hours is not None else int(settings.PROJECTION_LOOKBACK_HOURS)
    forward = forward_hours if forward_hours is not None else int(settings.PROJECTION_FORWARD_HOURS)
    k = atr_mult if atr_mult is not None else float(settings.PROJECTION_ATR_MULT)
    lookback = max(1, int(lookback))
    forward = max(1, int(forward))
    bars_needed = max(24, int(lookback * 60 / max(bar_minutes, 1)))

    empty = HorizonProjection(
        direction="flat",
        lookback_hours=lookback,
        horizon_hours=forward,
        entry_now=0.0,
        atr=0.0,
        range_high=0.0,
        range_low=0.0,
        ema21=0.0,
        bull=0.0,
        base=0.0,
        bear=0.0,
        extent_pts=0.0,
        extent_pct=0.0,
        invalidation=0.0,
        pointers=["wait_for_warmup"],
        reasons=["insufficient_bars"],
    )
    if df_5m is None or len(df_5m) < bars_needed:
        return empty

    window = df_5m.iloc[-bars_needed:].copy()
    h = window["high"].astype(float)
    l = window["low"].astype(float)
    c = window["close"].astype(float)
    o0 = float(window["open"].astype(float).iloc[0])
    entry = float(c.iloc[-1])
    ret = (entry - o0) / o0 if o0 else 0.0
    range_high = float(h.max())
    range_low = float(l.min())

    atr_s = compute_atr(h, l, c, 14)
    atr = float(atr_s.iloc[-1]) if len(atr_s) and pd.notna(atr_s.iloc[-1]) else 0.0
    atr = max(atr, 1e-8)
    ema21_s = compute_ema(c, 21)
    ema21 = float(ema21_s.iloc[-1]) if len(ema21_s) and pd.notna(ema21_s.iloc[-1]) else entry
    ema9 = float(compute_ema(c, 9).iloc[-1])
    ema50 = float(compute_ema(c, 50).iloc[-1]) if len(c) >= 50 else ema21
    aligned_up = ema9 > ema21 > ema50
    aligned_down = ema9 < ema21 < ema50
    structure = detect_structure(h, l, c, lookback=min(48, len(window)))

    deadzone = float(getattr(settings, "BIAS_DEADZONE_ATR_FRAC", 0.3) or 0.3)
    move = abs(entry - o0)
    reasons: list[str] = [
        f"return_{lookback}h={ret:.4%}",
        f"structure={structure.trend}",
        f"atr={atr:.5f}",
    ]
    pointers: list[str] = []

    if move < deadzone * atr * max(lookback / 6.0, 1.0):
        direction: ProjectionDirection = "flat"
        reasons.append("deadzone_flat")
        base_mult = 0.5 * k
        bull = entry + base_mult * atr
        bear = entry - base_mult * atr
        base = entry
        extent_pts = 0.0
        invalidation = entry
        pointers.append(f"chop_box ±{base_mult:.1f}×ATR for next {forward}h")
        pointers.append("stand_aside_until_range_break")
    elif ret > 0 and (
        aligned_up
        or structure.trend == "up"
        or structure.higher_highs
        or structure.higher_lows
    ) and not (structure.lower_highs and structure.lower_lows):
        direction = "up"
        reasons.append("bull_structure_stack" if aligned_up else "bull_return_structure")
        weak = structure.trend != "up" or not aligned_up
        base_mult = (0.5 if weak else 1.0) * k
        bull_mult = 1.5 * k
        bear_mult = 1.0 * k
        bull = max(entry + bull_mult * atr, range_high + 0.25 * atr)
        base = entry + base_mult * atr
        bear = entry - bear_mult * atr
        extent_pts = base - entry
        invalidation = min(range_low - 0.1 * atr, entry - 1.0 * atr)
        pointers.append(f"pullback_to_ema21={ema21:.5f} then +{base_mult:.1f}×ATR")
        pointers.append(f"first_target_base={base:.5f}")
        pointers.append(f"stretch_bull={bull:.5f}")
        pointers.append(f"invalidation_below={invalidation:.5f}")
    elif ret < 0 and (
        aligned_down
        or structure.trend == "down"
        or structure.lower_highs
        or structure.lower_lows
    ) and not (structure.higher_highs and structure.higher_lows):
        direction = "down"
        reasons.append("bear_structure_stack" if aligned_down else "bear_return_structure")
        weak = structure.trend != "down" or not aligned_down
        base_mult = (0.5 if weak else 1.0) * k
        bull_mult = 1.0 * k
        bear_mult = 1.5 * k
        bear = min(entry - bear_mult * atr, range_low - 0.25 * atr)
        base = entry - base_mult * atr
        bull = entry + bull_mult * atr
        extent_pts = entry - base
        invalidation = max(range_high + 0.1 * atr, entry + 1.0 * atr)
        pointers.append(f"rally_to_ema21={ema21:.5f} then -{base_mult:.1f}×ATR")
        pointers.append(f"first_target_base={base:.5f}")
        pointers.append(f"stretch_bear={bear:.5f}")
        pointers.append(f"invalidation_above={invalidation:.5f}")
    else:
        direction = "flat"
        reasons.append("mixed_or_choppy")
        base_mult = 0.5 * k
        bull = entry + base_mult * atr
        bear = entry - base_mult * atr
        base = entry
        extent_pts = 0.0
        invalidation = entry
        pointers.append("mixed_structure_wait_for_clear_break")
        pointers.append(f"watch_range={range_low:.5f}-{range_high:.5f}")

    extent_pct = (extent_pts / entry) if entry else 0.0
    return HorizonProjection(
        direction=direction,
        lookback_hours=lookback,
        horizon_hours=forward,
        entry_now=entry,
        atr=atr,
        range_high=range_high,
        range_low=range_low,
        ema21=ema21,
        bull=bull,
        base=base,
        bear=bear,
        extent_pts=extent_pts,
        extent_pct=extent_pct,
        invalidation=invalidation,
        pointers=pointers,
        reasons=reasons,
    )


def projection_agrees_with_bias(
    bias_direction: str,
    projection: HorizonProjection,
    stance_8h: Optional[str] = None,
) -> tuple[bool, list[str], list[str]]:
    """Soft gate: bias must agree with projection (+ 8h stance not opposing).

    Returns (ok, gates_passed, gates_failed).
    """
    passed: list[str] = []
    failed: list[str] = []
    if not getattr(settings, "PROJECTION_ENABLED", True):
        return True, ["projection_disabled"], []
    if not getattr(settings, "PROJECTION_SOFT_GATE", True):
        passed.append(f"projection:{projection.direction}")
        return True, passed, failed

    passed.append(f"projection:{projection.direction}")
    if stance_8h:
        passed.append(f"stance_8h:{stance_8h}")

    if bias_direction == "NO_TRADE":
        failed.append("bias_no_trade")
        return False, passed, failed

    if projection.direction == "flat":
        failed.append("projection_not_aligned")
        return False, passed, failed

    # STAND_ASIDE is neutral — do not veto when projection already agrees with bias.
    # Only a directional opposing stance blocks.
    if bias_direction == "BUY_ONLY":
        if projection.direction != "up":
            failed.append("projection_not_aligned")
        if stance_8h == "FAVOR_SELL":
            failed.append("stance_opposes_buy")
            failed.append("projection_not_aligned")
    elif bias_direction == "SELL_ONLY":
        if projection.direction != "down":
            failed.append("projection_not_aligned")
        if stance_8h == "FAVOR_BUY":
            failed.append("stance_opposes_sell")
            failed.append("projection_not_aligned")
    else:
        failed.append("projection_not_aligned")

    ok = len(failed) == 0
    if ok:
        passed.append("projection_aligned")
    return ok, passed, failed
