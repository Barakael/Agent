"""Momentum — strong candle, MACD acceleration, RSI strength."""

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


class MomentumStrategy:
    strategy_id = "momentum"
    trade_mode = "pattern"
    regimes = ("trending", "breakout")

    def evaluate_snapshot(
        self, snapshot: MarketSnapshot, ctx: StrategyContext | None = None
    ) -> StrategyEvaluation:
        scores: dict[str, float] = {}
        reasons: list[str] = []

        body = abs(snapshot.close - snapshot.open)
        rng = max(snapshot.high - snapshot.low, 1e-12)
        strong = body / rng >= 0.65

        bull = (
            snapshot.macd_bull_cross
            or (snapshot.macd_hist > 0 and snapshot.macd_hist > snapshot.macd_hist_prev)
        )
        bear = (
            snapshot.macd_bear_cross
            or (snapshot.macd_hist < 0 and snapshot.macd_hist < snapshot.macd_hist_prev)
        )

        if bull and snapshot.rsi < 65:
            direction = SignalDirection.BUY
        elif bear and snapshot.rsi > 35:
            direction = SignalDirection.SELL
        else:
            return no_trade(self.strategy_id, ["No momentum trigger"])

        # Strong candle (25)
        if strong and (
            (direction == SignalDirection.BUY and snapshot.close > snapshot.open)
            or (direction == SignalDirection.SELL and snapshot.close < snapshot.open)
        ):
            scores["candle"] = 25
            reasons.append("Strong candle")
        else:
            scores["candle"] = 8

        # MACD acceleration (25)
        if direction == SignalDirection.BUY and snapshot.macd_bull_cross:
            scores["macd"] = 25
            reasons.append("MACD bullish cross")
        elif direction == SignalDirection.SELL and snapshot.macd_bear_cross:
            scores["macd"] = 25
            reasons.append("MACD bearish cross")
        elif abs(snapshot.macd_hist) > abs(snapshot.macd_hist_prev):
            scores["macd"] = 15
            reasons.append("MACD accelerating")
        else:
            scores["macd"] = 5

        # RSI strength (20)
        if direction == SignalDirection.BUY and 45 <= snapshot.rsi <= 70:
            scores["rsi"] = 20
            reasons.append(f"RSI strength {snapshot.rsi:.1f}")
        elif direction == SignalDirection.SELL and 30 <= snapshot.rsi <= 55:
            scores["rsi"] = 20
            reasons.append(f"RSI strength {snapshot.rsi:.1f}")
        else:
            scores["rsi"] = 5

        # Trend / EMA (20)
        if direction == SignalDirection.BUY and snapshot.ema_aligned_up:
            scores["ema"] = 20
        elif direction == SignalDirection.SELL and snapshot.ema_aligned_down:
            scores["ema"] = 20
        else:
            scores["ema"] = 5

        # ATR (10) + RR (10)
        atr_ratio = snapshot.atr / snapshot.atr_sma if snapshot.atr_sma > 0 else 1.0
        scores["atr"] = 10 if atr_ratio >= 0.9 else 3
        scores["risk_reward"] = 10

        total = sum(scores.values())
        confidence = min(100.0, round(total / 1.1, 1))
        if scores.get("macd", 0) < 10:
            return no_trade(self.strategy_id, reasons + ["Weak MACD"], scores)

        sl, tp, method = atr_sl_tp(snapshot, direction)
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
