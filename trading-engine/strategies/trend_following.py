"""Trend Following — HH/HL, EMA alignment, healthy ATR."""

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


class TrendFollowingStrategy:
    strategy_id = "trend_following"
    trade_mode = "pattern"
    regimes = ("trending",)

    def evaluate_snapshot(
        self, snapshot: MarketSnapshot, ctx: StrategyContext | None = None
    ) -> StrategyEvaluation:
        scores: dict[str, float] = {}
        reasons: list[str] = []

        # Trend strength (25)
        if snapshot.higher_highs and snapshot.higher_lows:
            scores["trend_strength"] = 25
            reasons.append("Higher highs + higher lows")
            direction = SignalDirection.BUY
        elif snapshot.lower_highs and snapshot.lower_lows:
            scores["trend_strength"] = 25
            reasons.append("Lower highs + lower lows")
            direction = SignalDirection.SELL
        elif snapshot.trend_direction == "up":
            scores["trend_strength"] = 12
            reasons.append("Soft uptrend")
            direction = SignalDirection.BUY
        elif snapshot.trend_direction == "down":
            scores["trend_strength"] = 12
            reasons.append("Soft downtrend")
            direction = SignalDirection.SELL
        else:
            return no_trade(self.strategy_id, ["No clear trend structure"])

        # EMA alignment (20)
        if direction == SignalDirection.BUY and snapshot.ema_aligned_up:
            scores["ema"] = 20
            reasons.append("EMA aligned bullish")
        elif direction == SignalDirection.SELL and snapshot.ema_aligned_down:
            scores["ema"] = 20
            reasons.append("EMA aligned bearish")
        else:
            scores["ema"] = 0
            reasons.append("EMA not aligned with structure")

        # Momentum / RSI (20)
        if direction == SignalDirection.BUY and 45 <= snapshot.rsi <= 70:
            scores["momentum"] = 20
            reasons.append(f"RSI healthy {snapshot.rsi:.1f}")
        elif direction == SignalDirection.SELL and 30 <= snapshot.rsi <= 55:
            scores["momentum"] = 20
            reasons.append(f"RSI healthy {snapshot.rsi:.1f}")
        elif 40 <= snapshot.rsi <= 60:
            scores["momentum"] = 10
        else:
            scores["momentum"] = 0

        # ATR healthy (20)
        atr_ratio = snapshot.atr / snapshot.atr_sma if snapshot.atr_sma > 0 else 1.0
        if 0.8 <= atr_ratio <= 1.8:
            scores["atr"] = 20
            reasons.append("ATR healthy")
        elif 0.6 <= atr_ratio <= 2.2:
            scores["atr"] = 10
        else:
            scores["atr"] = 0
            reasons.append("ATR unhealthy for trend")

        # Support confirmation / pullback (15)
        mid = snapshot.ema_21
        if direction == SignalDirection.BUY and snapshot.low <= mid <= snapshot.close:
            scores["support"] = 15
            reasons.append("Pullback to EMA21")
        elif direction == SignalDirection.SELL and snapshot.high >= mid >= snapshot.close:
            scores["support"] = 15
            reasons.append("Rally into EMA21")
        elif direction == SignalDirection.BUY and snapshot.close > snapshot.ema_21:
            scores["support"] = 8
        elif direction == SignalDirection.SELL and snapshot.close < snapshot.ema_21:
            scores["support"] = 8
        else:
            scores["support"] = 0

        # Risk reward placeholder (10) — structure distance
        scores["risk_reward"] = 10 if snapshot.atr > 0 else 0

        total = sum(scores.values())
        # Max possible ~110 → normalize to 0–100
        confidence = min(100.0, round(total / 1.1, 1))
        if scores.get("ema", 0) < 10 or scores.get("trend_strength", 0) < 12:
            return no_trade(
                self.strategy_id,
                reasons + ["Trend filters failed"],
                scores,
            )

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
