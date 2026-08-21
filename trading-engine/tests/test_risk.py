import pandas as pd
import pytest

from risk.gate import RiskGate, RiskDecision
from signals.engine import SignalDirection, SignalEngine, TradeSignal


def _make_df(n: int = 50, trend: str = "up") -> pd.DataFrame:
    base = 1.1000
    closes = []
    for i in range(n):
        if trend == "up":
            closes.append(base + i * 0.0001)
        else:
            closes.append(base - i * 0.0001)
    return pd.DataFrame(
        {
            "epoch": list(range(n)),
            "open": closes,
            "high": [c + 0.0002 for c in closes],
            "low": [c - 0.0002 for c in closes],
            "close": closes,
            "volume": [1] * n,
        }
    )


def test_risk_gate_rejects_without_sl_tp_manual():
    gate = RiskGate()
    result = gate.validate_manual_order(0, 1.105, 10.0)
    assert result.decision == RiskDecision.REJECTED


def test_risk_gate_approves_manual_with_sl_tp():
    gate = RiskGate()
    result = gate.validate_manual_order(1.095, 1.110, 10.0)
    assert result.decision == RiskDecision.APPROVED


def test_daily_kill_switch(monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "DAILY_KILL_SWITCH_ENABLED", True)
    gate = RiskGate()
    gate.kill_switch_enabled = True
    gate.reset_session(10000.0)
    gate.record_pnl(-300.0)  # 3% — below 4% limit
    assert not gate.kill_switch_active
    gate.record_pnl(-100.0)  # 4% total — triggers kill switch
    assert gate.kill_switch_active


def test_daily_kill_switch_disabled_by_default():
    gate = RiskGate()
    gate.reset_session(10000.0)
    gate.record_pnl(-500.0)  # 5% — would trip if enabled
    assert not gate.kill_switch_active


def test_stake_calculation_positive():
    gate = RiskGate()
    stake = gate.calculate_stake(10000.0, 15, "frxEURUSD")
    assert stake > 0


def test_demo_fixed_stake(monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "TRADING_MODE", "demo")
    monkeypatch.setattr(settings, "DEMO_FIXED_STAKE_USD", 100.0)
    gate = RiskGate()
    assert gate.calculate_stake(10000.0, 15, "R_100") == 100.0


def test_live_percent_stake(monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "TRADING_MODE", "live")
    gate = RiskGate()
    gate.risk_percent = 1.5
    assert gate.calculate_stake(10000.0, 15, "R_100") == 150.0


def test_unlimited_trades_when_max_zero(monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "TRADING_MODE", "demo")
    monkeypatch.setattr(settings, "DEMO_FIXED_STAKE_USD", 100.0)
    monkeypatch.setattr(settings, "PLAN_MAX_STAKE_USD_CEILING", 100.0)
    gate = RiskGate()
    gate.max_trades_per_day = 0
    gate.reset_session(10000.0)
    for _ in range(25):
        gate.record_trade_opened()
    signal = TradeSignal(
        symbol="frxEURUSD",
        direction=SignalDirection.BUY,
        rsi=25.0,
        macd=0.001,
        macd_signal=0.0,
        price=1.1,
        epoch=1000,
        reason="test",
    )
    result = gate.evaluate(signal, 10000.0)
    assert result.decision == RiskDecision.APPROVED
    assert result.stake == 100.0


def test_risk_rejects_when_kill_switch_active(monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "DAILY_KILL_SWITCH_ENABLED", True)
    gate = RiskGate()
    gate.kill_switch_enabled = True
    gate.trigger_kill_switch()
    signal = TradeSignal(
        symbol="frxEURUSD",
        direction=SignalDirection.BUY,
        rsi=25.0,
        macd=0.001,
        macd_signal=0.0,
        price=1.1,
        epoch=1000,
        reason="test",
    )
    result = gate.evaluate(signal, 10000.0)
    assert result.decision == RiskDecision.REJECTED
