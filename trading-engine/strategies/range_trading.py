"""Range Trading — support bounce / resistance rejection, low ATR."""

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


class RangeTradingStrategy:
    strategy_id = "range_trading"
    trade_mode = "pattern"
    regimes = ("ranging",)

    def evaluate_snapshot(
        self, snapshot: MarketSnapshot, ctx: StrategyContext | None = None
    ) -> StrategyEvaluation:
        scores: dict[str, float] = {}
        reasons: list[str] = []
        atr_ratio = snapshot.atr / snapshot.atr_sma if snapshot.atr_sma > 0 else 1.0

        if atr_ratio > 1.3 or snapshot.bb_mid_slope > 0.0015:
            return no_trade(self.strategy_id, ["Market not ranging"])

        scores["range"] = 20
        reasons.append("Sideways market")

        # Low ATR (20)
        if atr_ratio <= 1.0:
            scores["atr"] = 20
            reasons.append("Low ATR")
        else:
            scores["atr"] = 10

        band = max(snapshot.resistance - snapshot.support, 1e-12)
        near_sup = abs(snapshot.close - snapshot.support) / band <= 0.2 or snapshot.close <= snapshot.bb_lower
        near_res = abs(snapshot.close - snapshot.resistance) / band <= 0.2 or snapshot.close >= snapshot.bb_upper

        if near_sup and snapshot.rsi < 40:
            direction = SignalDirection.BUY
            scores["support"] = 25
            reasons.append("Support bounce")
        elif near_res and snapshot.rsi > 60:
            direction = SignalDirection.SELL
            scores["support"] = 25
            reasons.append("Resistance rejection")
        else:
            return no_trade(self.strategy_id, ["No S/R bounce setup"], scores)

        # BB reclaim / mean reversion (20)
        if direction == SignalDirection.BUY and snapshot.close > snapshot.bb_lower:
            scores["bb"] = 20
            reasons.append("Reclaim lower BB")
        elif direction == SignalDirection.SELL and snapshot.close < snapshot.bb_upper:
            scores["bb"] = 20
            reasons.append("Reject upper BB")
        else:
            scores["bb"] = 5

        # RSI extreme (15)
        if direction == SignalDirection.BUY and snapshot.rsi < 35:
            scores["rsi"] = 15
        elif direction == SignalDirection.SELL and snapshot.rsi > 65:
            scores["rsi"] = 15
        else:
            scores["rsi"] = 8

        scores["risk_reward"] = 10
        total = sum(scores.values())
        confidence = min(100.0, round(total / 1.1, 1))

        sl, tp, method = atr_sl_tp(snapshot, direction, atr_mult=1.0, rr=1.5)
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
