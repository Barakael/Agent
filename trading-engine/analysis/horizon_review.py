"""Independent horizon market reviews (mid 4/6h + long 8h).

These do not place orders. They publish a trade stance from the last N hours
and refresh only when an N-hour bar closes — separate from the 6h bias → 1h
entry pipeline.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal, Optional

import pandas as pd

from config import settings
from indicators.atr import compute_atr
from indicators.ema import compute_ema
from indicators.macd import compute_macd
from indicators.rsi import compute_rsi
from indicators.structure import detect_structure

TradeStance = Literal["FAVOR_BUY", "FAVOR_SELL", "STAND_ASIDE"]


@dataclass
class HorizonReview:
    """Snapshot of what the last N hours imply for trading."""

    hours: int
    stance: TradeStance
    review_id: str
    symbol: str
    epoch: int
    return_pct: float
    atr: float
    range_high: float
    range_low: float
    rsi: float
    macd_hist: float
    structure_trend: str
    ema_aligned_up: bool
    ema_aligned_down: bool
    reasons: list[str] = field(default_factory=list)
    watch: list[str] = field(default_factory=list)
    valid_until_epoch: int = 0

    def to_dict(self) -> dict:
        return {
            "hours": self.hours,
            "stance": self.stance,
            "review_id": self.review_id,
            "symbol": self.symbol,
            "epoch": self.epoch,
            "return_pct": round(self.return_pct, 6),
            "atr": round(self.atr, 6),
            "range_high": self.range_high,
            "range_low": self.range_low,
            "rsi": round(self.rsi, 2),
            "macd_hist": round(self.macd_hist, 6),
            "structure_trend": self.structure_trend,
            "ema_aligned_up": self.ema_aligned_up,
            "ema_aligned_down": self.ema_aligned_down,
            "reasons": self.reasons,
            "watch": self.watch,
            "valid_until_epoch": self.valid_until_epoch,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }


def is_horizon_bar_close(epoch: int, hours: int) -> bool:
    """True when the closed bar completes an N-hour period (UTC-aligned)."""
    if epoch <= 0 or hours <= 0:
        return False
    period = int(hours) * 3600
    return epoch % period == 0


def _review_id(symbol: str, hours: int, stance: str, epoch: int) -> str:
    block = epoch // max(hours * 3600, 1)
    raw = f"{symbol}:{hours}h:{stance}:{block}"
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def compute_horizon_review(
    symbol: str,
    df_5m: pd.DataFrame,
    *,
    hours: int,
    bar_minutes: int = 5,
) -> HorizonReview:
    """Analyse the last `hours` of 5m OHLC and recommend a trade stance."""
    hours = max(1, int(hours))
    bars_needed = max(24, int(hours * 60 / max(bar_minutes, 1)))
    epoch = (
        int(df_5m["epoch"].iloc[-1])
        if df_5m is not None and "epoch" in df_5m.columns and len(df_5m)
        else 0
    )
    valid_until = epoch + hours * 3600 if epoch else 0

    if df_5m is None or len(df_5m) < bars_needed:
        return HorizonReview(
            hours=hours,
            stance="STAND_ASIDE",
            review_id=_review_id(symbol, hours, "STAND_ASIDE", epoch),
            symbol=symbol,
            epoch=epoch,
            return_pct=0.0,
            atr=0.0,
            range_high=0.0,
            range_low=0.0,
            rsi=50.0,
            macd_hist=0.0,
            structure_trend="sideways",
            ema_aligned_up=False,
            ema_aligned_down=False,
            reasons=["insufficient_bars"],
            watch=["wait_for_warmup"],
            valid_until_epoch=valid_until,
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

    atr_s = compute_atr(h, l, c, 14)
    atr = float(atr_s.iloc[-1]) if len(atr_s) and pd.notna(atr_s.iloc[-1]) else 0.0
    ema9 = compute_ema(c, 9)
    ema21 = compute_ema(c, 21)
    ema50 = compute_ema(c, 50)
    e9, e21, e50 = float(ema9.iloc[-1]), float(ema21.iloc[-1]), float(ema50.iloc[-1])
    aligned_up = e9 > e21 > e50
    aligned_down = e9 < e21 < e50
    structure = detect_structure(h, l, c, lookback=min(48, len(window)))
    rsi_s = compute_rsi(c, 14)
    rsi = float(rsi_s.iloc[-1]) if len(rsi_s) and pd.notna(rsi_s.iloc[-1]) else 50.0
    _, _, hist = compute_macd(c, 12, 26, 9)
    macd_hist = float(hist.iloc[-1]) if len(hist) and pd.notna(hist.iloc[-1]) else 0.0

    reasons: list[str] = [
        f"return_{hours}h={ret:.4%}",
        f"structure={structure.trend}",
        f"rsi={rsi:.1f}",
    ]
    watch: list[str] = [
        f"range_high={range_high:.5f}",
        f"range_low={range_low:.5f}",
        f"atr={atr:.5f}",
    ]

    # Deadzone: little net movement vs ATR → stand aside
    move = abs(c1 - o0)
    deadzone = float(getattr(settings, "BIAS_DEADZONE_ATR_FRAC", 0.3) or 0.3)
    if atr > 0 and move < deadzone * atr * max(hours / 6.0, 1.0):
        stance: TradeStance = "STAND_ASIDE"
        reasons.append("deadzone_flat_horizon")
        watch.append("no_directional_edge")
    elif (
        aligned_up
        and ret > 0
        and (structure.higher_highs or structure.higher_lows or structure.trend == "up")
        and not (structure.lower_highs and structure.lower_lows)
        and rsi < 78
        and macd_hist >= 0
    ):
        stance = "FAVOR_BUY"
        reasons.append("bull_horizon_stack")
        watch.append("prefer_longs_on_pullback_to_ema21")
        watch.append("avoid_shorts_until_structure_breaks")
    elif (
        aligned_down
        and ret < 0
        and (structure.lower_highs or structure.lower_lows or structure.trend == "down")
        and not (structure.higher_highs and structure.higher_lows)
        and rsi > 22
        and macd_hist <= 0
    ):
        stance = "FAVOR_SELL"
        reasons.append("bear_horizon_stack")
        watch.append("prefer_shorts_on_rally_to_ema21")
        watch.append("avoid_longs_until_structure_breaks")
    else:
        stance = "STAND_ASIDE"
        reasons.append("mixed_or_choppy_horizon")
        watch.append("wait_for_clear_structure")

    return HorizonReview(
        hours=hours,
        stance=stance,
        review_id=_review_id(symbol, hours, stance, epoch),
        symbol=symbol,
        epoch=epoch,
        return_pct=ret,
        atr=atr,
        range_high=range_high,
        range_low=range_low,
        rsi=rsi,
        macd_hist=macd_hist,
        structure_trend=structure.trend,
        ema_aligned_up=aligned_up,
        ema_aligned_down=aligned_down,
        reasons=reasons,
        watch=watch,
        valid_until_epoch=valid_until,
    )


def compute_mid_review(
    symbol: str,
    df_5m: pd.DataFrame,
    *,
    bar_minutes: int = 5,
    hours: Optional[int] = None,
) -> HorizonReview:
    h = hours if hours is not None else int(settings.REVIEW_MID_HOURS)
    return compute_horizon_review(symbol, df_5m, hours=h, bar_minutes=bar_minutes)


def compute_8h_review(
    symbol: str,
    df_5m: pd.DataFrame,
    *,
    bar_minutes: int = 5,
    hours: Optional[int] = None,
) -> HorizonReview:
    h = hours if hours is not None else int(settings.REVIEW_8H_HOURS)
    return compute_horizon_review(symbol, df_5m, hours=h, bar_minutes=bar_minutes)
