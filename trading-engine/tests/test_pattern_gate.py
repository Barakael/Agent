"""Tests for explicit entry-pattern gating."""

from __future__ import annotations

import numpy as np
import pandas as pd

from bias.bias_6h import BiasState
from bias.confirm_1h import allowed_confirmations, confirm_1h_entry
from bias.regime_24h import RegimeState
from config import settings
from strategies.price_action import PriceActionStrategy, allowed_patterns
from tests.test_replay import _snapshot


def test_allowed_patterns_defaults_to_rejections_only(monkeypatch):
    monkeypatch.setattr(settings, "PRICE_ACTION_PATTERNS", "pin,engulfing")
    assert allowed_patterns() == {"pin", "engulfing"}
    monkeypatch.setattr(settings, "PRICE_ACTION_PATTERNS", "")
    assert allowed_patterns() == {"pin", "engulfing"}
    monkeypatch.setattr(settings, "PRICE_ACTION_PATTERNS", "pin, break_of_structure")
    assert allowed_patterns() == {"pin", "break_of_structure"}


def test_break_of_structure_cannot_fire_when_not_enabled(monkeypatch):
    monkeypatch.setattr(settings, "PRICE_ACTION_PATTERNS", "pin,engulfing")
    strategy = PriceActionStrategy()

    snap = _snapshot(break_of_structure_up=True)
    result = strategy.evaluate_snapshot(snap)

    assert result.is_trade is False
    assert result.confidence == 0.0
    assert "break_of_structure" in " ".join(result.reasons)


def test_break_of_structure_fires_once_explicitly_enabled(monkeypatch):
    monkeypatch.setattr(settings, "PRICE_ACTION_PATTERNS", "break_of_structure")
    strategy = PriceActionStrategy()

    result = strategy.evaluate_snapshot(_snapshot(break_of_structure_up=True))

    assert result.is_trade is True
    assert result.pattern == "break_of_structure"


def test_rejection_patterns_report_their_label(monkeypatch):
    monkeypatch.setattr(settings, "PRICE_ACTION_PATTERNS", "pin,engulfing")
    strategy = PriceActionStrategy()

    pin = strategy.evaluate_snapshot(_snapshot(pin_bar="bullish_pin"))
    eng = strategy.evaluate_snapshot(_snapshot(engulfing="bullish_engulfing"))

    assert pin.pattern == "pin"
    assert eng.pattern == "engulfing"
    assert pin.is_trade and eng.is_trade


def test_confidence_alone_could_not_have_excluded_breakouts(monkeypatch):
    """A breakout still scores above the gate — only the pattern check stops it."""
    monkeypatch.setattr(settings, "PRICE_ACTION_PATTERNS", "break_of_structure")
    strategy = PriceActionStrategy()
    in_trend = _snapshot(break_of_structure_up=True, ema_50=99.0)
    breakout = strategy.evaluate_snapshot(in_trend)
    # 80 of the 100 points come from trend context, so a breakout clears 94.
    assert breakout.confidence == 95.5
    assert breakout.confidence >= settings.STRATEGY_CONFIDENCE_THRESHOLD


def _regime(label: str = "weak_trend") -> RegimeState:
    return RegimeState(
        label=label,  # type: ignore[arg-type]
        return_24h=0.01,
        atr=1.0,
        atr_ratio=1.0,
        ema_aligned_up=True,
        ema_aligned_down=False,
        structure_trend="up",
        reasons=[],
    )


def _bias(direction: str = "BUY_ONLY") -> BiasState:
    return BiasState(
        direction=direction,  # type: ignore[arg-type]
        bias_id="bias-test",
        range_high=110.0,
        range_low=90.0,
        atr_6h=1.0,
        return_6h=0.01,
        structure_trend="up",
        ema_aligned_up=True,
        ema_aligned_down=False,
        rsi=55.0,
        reasons=["test bias"],
    )


def _hourly_frame(confirm: str) -> pd.DataFrame:
    """Build 5m bars whose last two 1h candles produce the wanted confirmation."""
    rows: list[tuple[float, float, float, float]] = []
    price = 100.0
    for _ in range(40 * 12):
        rows.append((price, price + 0.1, price - 0.1, price + 0.02))
        price += 0.02

    def hour(o, h, l, c):
        step = (c - o) / 12
        for k in range(12):
            bar_o = o + step * k
            bar_c = o + step * (k + 1)
            bar_h = h if k == 11 else max(bar_o, bar_c)
            bar_l = l if k == 11 else min(bar_o, bar_c)
            rows.append((bar_o, bar_h, bar_l, bar_c))

    base = rows[-1][3]
    if confirm == "break_prev":
        # Prior hour up (so no engulfing), current closes above its high with a
        # body too large to read as a pin: a pure breakout.
        hour(base, base + 0.25, base - 0.05, base + 0.2)
        hour(base + 0.2, base + 3.0, base + 0.15, base + 2.5)
    else:
        hour(base, base + 0.4, base - 0.4, base - 0.3)
        # Long lower wick, small body: a bullish pin.
        hour(base - 0.3, base + 0.4, base - 4.0, base + 0.3)

    arr = np.array(rows, dtype=float)
    n = len(arr)
    # End on an exact hour boundary so is_entry_bar_close would pass.
    end = 1_700_000_000
    epochs = [end - (n - 1 - i) * 300 for i in range(n)]
    return pd.DataFrame(
        {
            "epoch": epochs,
            "open": arr[:, 0],
            "high": arr[:, 1],
            "low": arr[:, 2],
            "close": arr[:, 3],
            "volume": np.zeros(n),
        }
    )


def test_break_prev_confirmation_is_blocked_by_default(monkeypatch):
    monkeypatch.setattr(settings, "BIAS_CONFIRM_TYPES", "pin,engulfing")
    regime = _regime()
    result = confirm_1h_entry(
        _hourly_frame("break_prev"), _bias(), regime, bar_minutes=5, entry_tf_minutes=60
    )
    blocked = [g for g in result.gates_failed if g.startswith("confirm_not_enabled")]
    assert result.ok is False
    assert blocked == ["confirm_not_enabled:break_prev"]


def test_break_prev_confirmation_passes_the_gate_when_enabled(monkeypatch):
    monkeypatch.setattr(settings, "BIAS_CONFIRM_TYPES", "pin,engulfing,break_prev")
    regime = _regime()
    result = confirm_1h_entry(
        _hourly_frame("break_prev"), _bias(), regime, bar_minutes=5, entry_tf_minutes=60
    )
    assert not any(g.startswith("confirm_not_enabled") for g in result.gates_failed)


def test_allowed_confirmations_defaults_to_rejections(monkeypatch):
    monkeypatch.setattr(settings, "BIAS_CONFIRM_TYPES", "")
    assert allowed_confirmations() == {"pin", "engulfing"}
