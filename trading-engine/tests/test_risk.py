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


def test_daily_kill_switch():
    gate = RiskGate()
    gate.reset_session(10000.0)
    gate.record_pnl(-300.0)  # 3% — below 4% limit
    assert not gate.kill_switch_active
    gate.record_pnl(-100.0)  # 4% total — triggers kill switch
    assert gate.kill_switch_active


def test_stake_calculation_positive():
    gate = RiskGate()
    stake = gate.calculate_stake(10000.0, 15, "frxEURUSD")
    assert stake > 0


def test_risk_rejects_when_kill_switch_active():
    gate = RiskGate()
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
