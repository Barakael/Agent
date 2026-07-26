"""Breakout — S/R break with ATR expansion."""

from __future__ import annotations

from typing import Optional

import pandas as pd

from number_engine.snapshot import MarketSnapshot
from signals.engine import SignalDirection
from strategies.base import (
    StrategyContext,
    StrategyEvaluation,
    StrategySignal,
    atr_sl_tp,
    evaluation_to_signal,
    no_trade,
)


class BreakoutStrategy:
    strategy_id = "breakout"
    trade_mode = "pattern"
    regimes = ("breakout",)

    def evaluate_snapshot(
        self, snapshot: MarketSnapshot, ctx: StrategyContext | None = None
    ) -> StrategyEvaluation:
        scores: dict[str, float] = {}
        reasons: list[str] = []
        atr_ratio = snapshot.atr / snapshot.atr_sma if snapshot.atr_sma > 0 else 1.0

        broke_res = snapshot.close > snapshot.resistance
        broke_sup = snapshot.close < snapshot.support

        if not broke_res and not broke_sup:
            return no_trade(self.strategy_id, ["No S/R break"])

        direction = SignalDirection.BUY if broke_res else SignalDirection.SELL
        scores["break"] = 25
        reasons.append("Resistance break" if broke_res else "Support break")

        # ATR expansion (20)
        if atr_ratio >= 1.25:
            scores["atr"] = 20
            reasons.append(f"ATR expansion {atr_ratio:.2f}x")
        elif atr_ratio >= 1.1:
            scores["atr"] = 10
        else:
            scores["atr"] = 0
            reasons.append("No ATR expansion")

        # Momentum (20)
        if direction == SignalDirection.BUY and snapshot.macd_hist > snapshot.macd_hist_prev:
            scores["momentum"] = 20
            reasons.append("MACD accelerating up")
        elif direction == SignalDirection.SELL and snapshot.macd_hist < snapshot.macd_hist_prev:
            scores["momentum"] = 20
            reasons.append("MACD accelerating down")
        else:
            scores["momentum"] = 5

        # Volume proxy via candle body strength (15)
        body = abs(snapshot.close - snapshot.open)
        rng = max(snapshot.high - snapshot.low, 1e-12)
        if body / rng >= 0.6:
            scores["volume"] = 15
            reasons.append("Strong breakout candle")
        else:
            scores["volume"] = 5

        # EMA confirmation (20)
        if direction == SignalDirection.BUY and snapshot.close > snapshot.ema_21:
            scores["ema"] = 20
        elif direction == SignalDirection.SELL and snapshot.close < snapshot.ema_21:
            scores["ema"] = 20
        else:
            scores["ema"] = 0

        scores["risk_reward"] = 10
        total = sum(scores.values())
        confidence = min(100.0, round(total / 1.1, 1))

        if scores.get("atr", 0) < 10:
            return no_trade(self.strategy_id, reasons + ["Breakout without volatility"], scores)

        sl, tp, method = atr_sl_tp(snapshot, direction, atr_mult=1.2, rr=2.0)
        return StrategyEvaluation(
            strategy_id=self.strategy_id,
            direction=direction,
            confidence=confidence,
            reasons=reasons,
            score_breakdown=scores,
            suggested_sl=sl,
            suggested_tp=tp,
            sl_tp_method=method,
        )

    def evaluate(
        self, symbol: str, df: pd.DataFrame, ctx: StrategyContext | None = None
    ) -> Optional[StrategySignal]:
        from number_engine import NumberEngine

        snap = NumberEngine().compute(symbol, df)
        if not snap:
            return None
        return evaluation_to_signal(self.evaluate_snapshot(snap, ctx), snap, ctx or StrategyContext())
