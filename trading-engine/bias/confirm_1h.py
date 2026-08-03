"""1h entry confirmation after 6h bias is set."""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from analysis.multi_timeframe import resample_ohlc
from bias.bias_6h import BiasState
from bias.regime_24h import RegimeState
from config import settings
from indicators.ema import compute_ema
from indicators.rsi import compute_rsi
from indicators.structure import detect_engulfing, detect_pin_bar


@dataclass
class ConfirmResult:
    ok: bool
    direction: str  # buy | sell | none
    gates_passed: list[str] = field(default_factory=list)
    gates_failed: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    entry_price: float = 0.0
    rsi: float = 0.0
    macd: float = 0.0
    confirm_type: str = ""

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "direction": self.direction,
            "gates_passed": self.gates_passed,
            "gates_failed": self.gates_failed,
            "reasons": self.reasons,
            "entry_price": self.entry_price,
            "rsi": round(self.rsi, 2),
            "confirm_type": self.confirm_type,
        }


def _to_1h(df_5m: pd.DataFrame, entry_tf_minutes: int, bar_minutes: int) -> pd.DataFrame:
    factor = max(2, int(entry_tf_minutes / max(bar_minutes, 1)))
    htf = resample_ohlc(df_5m, factor)
    if "epoch" in df_5m.columns and len(htf) and len(df_5m) >= factor:
        # Approximate epoch as last 5m epoch of each chunk
        epochs = []
        for i in range(0, len(df_5m) - factor + 1, factor):
            epochs.append(int(df_5m["epoch"].iloc[i + factor - 1]))
        if len(epochs) == len(htf):
            htf = htf.copy()
            htf["epoch"] = epochs
    return htf


def is_entry_bar_close(epoch: int, entry_tf_minutes: int = 60) -> bool:
    """True when the closed 5m bar completes an entry-TF candle (e.g. top of hour)."""
    period = entry_tf_minutes * 60
    return epoch > 0 and epoch % period == 0


def confirm_1h_entry(
    df_5m: pd.DataFrame,
    bias: BiasState,
    regime: RegimeState,
    *,
    bar_minutes: int = 5,
    entry_tf_minutes: int | None = None,
) -> ConfirmResult:
    entry_tf = entry_tf_minutes or int(settings.BIAS_ENTRY_TF_MINUTES)
    failed: list[str] = []
    passed: list[str] = []

    if bias.direction == "NO_TRADE":
        return ConfirmResult(
            ok=False,
            direction="none",
            gates_failed=["bias_no_trade"],
            reasons=list(bias.reasons),
        )

    if regime.label in ("range", "compression", "unknown"):
        return ConfirmResult(
            ok=False,
            direction="none",
            gates_failed=[f"regime_blocked:{regime.label}"],
            reasons=[f"regime={regime.label}"],
        )

    want_buy = bias.direction == "BUY_ONLY"
    if want_buy and regime.label == "strong_bear":
        return ConfirmResult(ok=False, direction="none", gates_failed=["regime_opposes_buy"])
    if (not want_buy) and regime.label == "strong_bull":
        return ConfirmResult(ok=False, direction="none", gates_failed=["regime_opposes_sell"])

    passed.append(f"bias:{bias.direction}")
    passed.append(f"regime:{regime.label}")

    htf = _to_1h(df_5m, entry_tf, bar_minutes)
    if len(htf) < 30:
        return ConfirmResult(
            ok=False,
            direction="none",
            gates_passed=passed,
            gates_failed=["insufficient_1h_bars"],
        )

    o = htf["open"].astype(float)
    h = htf["high"].astype(float)
    l = htf["low"].astype(float)
    c = htf["close"].astype(float)
    ema21 = compute_ema(c, 21)
    rsi_s = compute_rsi(c, 14)

    cur_o, cur_h, cur_l, cur_c = float(o.iloc[-1]), float(h.iloc[-1]), float(l.iloc[-1]), float(c.iloc[-1])
    prev_o, prev_h, prev_l, prev_c = float(o.iloc[-2]), float(h.iloc[-2]), float(l.iloc[-2]), float(c.iloc[-2])
    mid = float(ema21.iloc[-1])
    rsi = float(rsi_s.iloc[-1]) if pd.notna(rsi_s.iloc[-1]) else 50.0
    rsi_prev = float(rsi_s.iloc[-2]) if pd.notna(rsi_s.iloc[-2]) else rsi
    rsi_prev2 = float(rsi_s.iloc[-3]) if len(rsi_s) > 2 and pd.notna(rsi_s.iloc[-3]) else rsi_prev

    # Hard EMA21 touch (wick), not "near only"
    if want_buy:
        touched = cur_l <= mid <= cur_c or prev_l <= mid <= max(prev_c, cur_c)
    else:
        touched = cur_h >= mid >= cur_c or prev_h >= mid >= min(prev_c, cur_c)
    if not touched:
        failed.append("no_hard_ema21_touch")
    else:
        passed.append("hard_ema21_touch")

    pin = detect_pin_bar(cur_o, cur_h, cur_l, cur_c)
    eng = detect_engulfing(prev_o, prev_c, cur_o, cur_c)
    break_prev = (want_buy and cur_c > prev_h) or ((not want_buy) and cur_c < prev_l)

    confirm_type = ""
    if want_buy:
        if pin == "bullish_pin":
            confirm_type = "bullish_pin"
        elif eng == "bullish_engulfing":
            confirm_type = "bullish_engulfing"
        elif break_prev:
            confirm_type = "break_prev_high"
    else:
        if pin == "bearish_pin":
            confirm_type = "bearish_pin"
        elif eng == "bearish_engulfing":
            confirm_type = "bearish_engulfing"
        elif break_prev:
            confirm_type = "break_prev_low"

    if not confirm_type:
        failed.append("no_rejection_or_break")
    else:
        passed.append(f"confirm:{confirm_type}")

    # Momentum returning (not free-fall)
    if want_buy:
        mom_ok = rsi >= rsi_prev >= rsi_prev2 - 1e-9 or (rsi > rsi_prev and rsi_prev2 <= rsi_prev)
        if not mom_ok:
            failed.append("rsi_not_rising")
        else:
            passed.append("rsi_rising")
    else:
        mom_ok = rsi <= rsi_prev <= rsi_prev2 + 1e-9 or (rsi < rsi_prev and rsi_prev2 >= rsi_prev)
        if not mom_ok:
            failed.append("rsi_not_falling")
        else:
            passed.append("rsi_falling")

    ok = len(failed) == 0
    return ConfirmResult(
        ok=ok,
        direction="buy" if want_buy else "sell",
        gates_passed=passed,
        gates_failed=failed,
        reasons=list(bias.reasons) + ([confirm_type] if confirm_type else []),
        entry_price=cur_c,
        rsi=rsi,
        confirm_type=confirm_type,
    )
