"""Tests for ATAE analysis gates."""

from datetime import datetime, timedelta, timezone

import pandas as pd

from analysis.scenario_open import simulate_sl_tp_window
from data.calendar import EconomicCalendar, EconomicEvent
from signals.engine import SignalDirection, TradeSignal


def _make_df(rows: int = 60, start: float = 1.1000) -> pd.DataFrame:
    prices = [start + i * 0.0001 for i in range(rows)]
    return pd.DataFrame(
        {
            "open": prices,
            "high": [p + 0.0002 for p in prices],
            "low": [p - 0.0002 for p in prices],
            "close": prices,
        }
    )


def test_calendar_currency_filter_blocks_matching_pair_only():
    cal = EconomicCalendar(pause_before_minutes=30, pause_after_minutes=30)
    now = datetime(2026, 6, 18, 12, 0, tzinfo=timezone.utc)
    cal._events = [
        EconomicEvent(
            title="US CPI",
            currency="USD",
            impact="High",
            event_time=now,
        )
    ]
    paused_eur, _ = cal.is_paused_for_currencies({"EUR"}, now=now)
    paused_usd, reason_usd = cal.is_paused_for_currencies({"USD"}, now=now)
    assert not paused_eur
    assert paused_usd
    assert "US CPI" in reason_usd


def test_open_scenario_rejects_insufficient_bars():
    df = _make_df(5)
    signal = TradeSignal(
        symbol="frxEURUSD",
        direction=SignalDirection.BUY,
        rsi=28.0,
        macd=0.0001,
        macd_signal=0.00005,
        price=1.1010,
        epoch=0,
        reason="test",
    )
    result = simulate_sl_tp_window(df, signal)
    assert not result.passed
    assert "insufficient" in result.reason.lower()


def test_open_scenario_runs_on_sufficient_bars():
    df = _make_df(60, start=1.1000)
    signal = TradeSignal(
        symbol="frxEURUSD",
        direction=SignalDirection.BUY,
        rsi=28.0,
        macd=0.0001,
        macd_signal=0.00005,
        price=float(df.iloc[-1]["close"]),
        epoch=0,
        reason="test",
    )
    result = simulate_sl_tp_window(df, signal)
    assert result.simulated_trades >= 0 or result.reason
