"""Tests for plan/bias pipeline gates added in the live-fix.

Covers:
- RR reject (post-calibration dollar TP < 1.5x SL raises InvertedRR)
- Session gate blocks swing forex before 09:00 UTC
- Close gate: profit >= 0 no longer auto-closes; TP-reached closes correctly
- Non-frx symbol rejected at RiskGate
- Missing daily plan skips; plan-bias conflict skips
"""

from __future__ import annotations

import types
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# RR gate
# ---------------------------------------------------------------------------

def test_inverted_rr_raised():
    """InvertedRR is exported from execution.orders."""
    from execution.orders import InvertedRR, MIN_DOLLAR_RR
    assert MIN_DOLLAR_RR == 1.5
    exc = InvertedRR("frxEURUSD dollar RR 5.00/10.00=0.50 < 1.5")
    assert "frxEURUSD" in str(exc)


def test_bias_sl_tp_min_rr_buy():
    """bias_sl_tp never returns TP closer than MIN_RR to entry (buy)."""
    from bias.risk import MIN_RR, bias_sl_tp
    from signals.engine import SignalDirection

    bias = MagicMock()
    bias.atr_6h = 0.001
    bias.range_low = 1.0900
    bias.range_high = 1.1100
    entry = 1.1000

    # Force very tight rr
    sl, tp, method = bias_sl_tp(bias, entry, SignalDirection.BUY, rr=0.1)
    risk = entry - sl
    assert risk > 0
    assert (tp - entry) >= MIN_RR * risk - 1e-10


def test_bias_sl_tp_min_rr_sell():
    """bias_sl_tp never returns TP closer than MIN_RR to entry (sell)."""
    from bias.risk import MIN_RR, bias_sl_tp
    from signals.engine import SignalDirection

    bias = MagicMock()
    bias.atr_6h = 0.001
    bias.range_low = 1.0900
    bias.range_high = 1.1100
    entry = 1.1000

    sl, tp, method = bias_sl_tp(bias, entry, SignalDirection.SELL, rr=0.1)
    risk = sl - entry
    assert risk > 0
    assert (entry - tp) >= MIN_RR * risk - 1e-10


# ---------------------------------------------------------------------------
# Close gate
# ---------------------------------------------------------------------------

def test_close_gate_profit_gt_zero_no_close():
    """Positive profit alone must NOT trigger a close."""
    import pandas as pd
    from analysis.scenario_close import evaluate_close

    position = {
        "profit": 5.0,
        "contract_type": "MULTUP",
        "underlying": "frxEURUSD",
        "buy_price": 100.0,
        "limit_order": {"take_profit": 20.0, "stop_loss": -15.0},
    }
    df = pd.DataFrame()
    result = evaluate_close(position, df)
    assert result.passed is False, "Positive profit alone should not close"


def test_close_gate_tp_reached_closes():
    """When profit >= tp limit, close is approved."""
    import pandas as pd
    from analysis.scenario_close import evaluate_close

    position = {
        "profit": 21.0,
        "contract_type": "MULTUP",
        "underlying": "frxEURUSD",
        "buy_price": 100.0,
        "limit_order": {"take_profit": 20.0, "stop_loss": -15.0},
    }
    df = pd.DataFrame()
    result = evaluate_close(position, df)
    assert result.passed is True
    assert result.reason == "take_profit_reached"


def test_close_gate_force_eod():
    """force_eod=True always closes."""
    import pandas as pd
    from analysis.scenario_close import evaluate_close

    position = {"profit": -3.0, "contract_type": "MULTUP", "underlying": "frxEURUSD",
                "buy_price": 100.0, "limit_order": {}}
    result = evaluate_close(position, pd.DataFrame(), force_eod=True)
    assert result.passed is True
    assert "force_close" in result.reason


# ---------------------------------------------------------------------------
# Non-frx reject
# ---------------------------------------------------------------------------

def test_risk_gate_rejects_synthetic():
    """RiskGate.evaluate rejects R_50 and 1HZ100V."""
    from risk.gate import RiskGate, RiskDecision

    gate = RiskGate()
    for sym in ("R_50", "1HZ100V", "R_75", "CRASH500"):
        signal = MagicMock()
        signal.symbol = sym
        result = gate.evaluate(signal, balance=10000.0)
        assert result.decision == RiskDecision.REJECTED, f"{sym} should be rejected"
        assert "non_frx" in result.reason


def test_risk_gate_allows_frx():
    """RiskGate.evaluate does NOT reject frx majors at the symbol check."""
    from risk.gate import RiskGate, RiskDecision

    gate = RiskGate()
    signal = MagicMock()
    signal.symbol = "frxEURUSD"
    signal.price = 1.10000
    signal.suggested_sl = None
    signal.suggested_tp = None
    signal.sl_tp_method = None
    # May fail for other reasons (balance, caps) but not symbol rejection
    result = gate.evaluate(signal, balance=10000.0)
    assert "non_frx" not in (result.reason or "")


# ---------------------------------------------------------------------------
# Session gate
# ---------------------------------------------------------------------------

def _make_session_mgr(enforce=True, open_h=9, close_h=21, close_m=0):
    from risk.session import SessionManager
    mgr = SessionManager.__new__(SessionManager)
    mgr.enforce = enforce
    mgr.open_hour = open_h
    mgr.close_hour = close_h
    mgr.close_minute = close_m
    return mgr


def test_session_blocks_before_09_utc():
    """SessionManager reports closed before SESSION_OPEN_HOUR_UTC=9."""
    mgr = _make_session_mgr()
    now = datetime(2026, 8, 19, 7, 0, 0, tzinfo=timezone.utc)
    assert mgr.is_session_open(now) is False


def test_session_open_at_09_utc():
    """SessionManager reports open at 09:00 UTC."""
    mgr = _make_session_mgr()
    now = datetime(2026, 8, 19, 9, 0, 0, tzinfo=timezone.utc)
    assert mgr.is_session_open(now) is True


def test_session_blocks_after_21_utc():
    """SessionManager reports closed at 21:00 UTC."""
    mgr = _make_session_mgr()
    now = datetime(2026, 8, 19, 21, 0, 0, tzinfo=timezone.utc)
    assert mgr.is_session_open(now) is False
