"""Risk gate ATR SL/TP and daily limits."""

from risk.gate import RiskDecision, RiskGate
from signals.engine import SignalDirection, TradeSignal
from strategies.base import StrategySignal


def _signal(**kwargs) -> StrategySignal:
    base = dict(
        symbol="frxEURUSD",
        direction=SignalDirection.BUY,
        rsi=50.0,
        macd=0.0,
        macd_signal=0.0,
        price=1.1000,
        epoch=1,
        reason="test",
        strategy_id="momentum",
        confidence=80.0,
        market_condition="trending",
        suggested_sl=1.0980,
        suggested_tp=1.1040,
        sl_tp_method="atr",
    )
    base.update(kwargs)
    return StrategySignal(**base)


def test_risk_uses_suggested_sl_tp():
    gate = RiskGate()
    gate.reset_session(10000)
    result = gate.evaluate(_signal(), 10000)
    assert result.decision == RiskDecision.APPROVED
    assert result.stop_loss_price == 1.0980
    assert result.take_profit_price == 1.1040
    assert result.sl_tp_method == "atr"


def test_max_trades_per_day():
    gate = RiskGate()
    gate.reset_session(10000)
    gate.max_trades_per_day = 2
    gate.record_trade_opened()
    gate.record_trade_opened()
    result = gate.evaluate(_signal(), 10000)
    assert result.decision == RiskDecision.REJECTED
    assert "Max trades" in result.reason
