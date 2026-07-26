"""Price Action — pin bars, engulfing, inside bars, break of structure."""

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


class PriceActionStrategy:
    strategy_id = "price_action"
    trade_mode = "pattern"
    regimes = ("trending", "ranging", "breakout")

    def evaluate_snapshot(
        self, snapshot: MarketSnapshot, ctx: StrategyContext | None = None
    ) -> StrategyEvaluation:
        scores: dict[str, float] = {}
        reasons: list[str] = []
        direction: Optional[SignalDirection] = None

        # Pattern (30)
        if snapshot.engulfing == "bullish_engulfing":
            direction = SignalDirection.BUY
            scores["pattern"] = 30
            reasons.append("Bullish engulfing")
        elif snapshot.engulfing == "bearish_engulfing":
            direction = SignalDirection.SELL
            scores["pattern"] = 30
            reasons.append("Bearish engulfing")
        elif snapshot.pin_bar == "bullish_pin":
            direction = SignalDirection.BUY
            scores["pattern"] = 28
            reasons.append("Bullish pin bar")
        elif snapshot.pin_bar == "bearish_pin":
            direction = SignalDirection.SELL
            scores["pattern"] = 28
            reasons.append("Bearish pin bar")
        elif snapshot.break_of_structure_up:
            direction = SignalDirection.BUY
            scores["pattern"] = 25
            reasons.append("Break of structure up")
        elif snapshot.break_of_structure_down:
            direction = SignalDirection.SELL
            scores["pattern"] = 25
            reasons.append("Break of structure down")
        elif snapshot.inside_bar:
            return no_trade(self.strategy_id, ["Inside bar — wait for break"])
        else:
            return no_trade(self.strategy_id, ["No price-action pattern"])

        assert direction is not None

        # Structure context (25)
        if direction == SignalDirection.BUY and (
            snapshot.trend_direction == "up" or snapshot.higher_lows
        ):
            scores["structure"] = 25
            reasons.append("Bullish structure")
        elif direction == SignalDirection.SELL and (
            snapshot.trend_direction == "down" or snapshot.lower_highs
        ):
            scores["structure"] = 25
            reasons.append("Bearish structure")
        else:
            scores["structure"] = 8

        # EMA filter (20)
        if direction == SignalDirection.BUY and snapshot.close > snapshot.ema_50:
            scores["ema"] = 20
        elif direction == SignalDirection.SELL and snapshot.close < snapshot.ema_50:
            scores["ema"] = 20
        else:
            scores["ema"] = 5

        # RSI (15)
        if direction == SignalDirection.BUY and snapshot.rsi < 65:
            scores["rsi"] = 15
        elif direction == SignalDirection.SELL and snapshot.rsi > 35:
            scores["rsi"] = 15
        else:
            scores["rsi"] = 0

        # ATR + RR (20)
        atr_ratio = snapshot.atr / snapshot.atr_sma if snapshot.atr_sma > 0 else 1.0
        scores["atr"] = 10 if 0.7 <= atr_ratio <= 2.0 else 3
        scores["risk_reward"] = 10

        total = sum(scores.values())
        confidence = min(100.0, round(total / 1.1, 1))

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
