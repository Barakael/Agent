"""Directional bias / swing entries — pullback with HTF confirmation."""

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


class BiasSwingStrategy:
    strategy_id = "bias_swing"
    trade_mode = "bias"
    regimes = ("trending", "ranging", "breakout")

    def evaluate_snapshot(
        self, snapshot: MarketSnapshot, ctx: StrategyContext | None = None
    ) -> StrategyEvaluation:
        ctx = ctx or StrategyContext()
        bias = (ctx.directional_bias or "neutral").lower()
        if bias not in {"buy", "sell"}:
            return no_trade(self.strategy_id, ["No directional bias"])

        scores: dict[str, float] = {}
        reasons: list[str] = []
        direction = SignalDirection.BUY if bias == "buy" else SignalDirection.SELL

        # Structure / EMA (25)
        if bias == "buy" and snapshot.ema_21 >= snapshot.ema_50:
            scores["structure"] = 25
            reasons.append("Bullish EMA structure")
        elif bias == "sell" and snapshot.ema_21 <= snapshot.ema_50:
            scores["structure"] = 25
            reasons.append("Bearish EMA structure")
        else:
            return no_trade(self.strategy_id, ["Structure against bias"])

        # Pullback (25)
        if bias == "buy" and snapshot.low <= snapshot.ema_21 <= snapshot.close:
            scores["pullback"] = 25
            reasons.append("Long pullback to EMA21")
        elif bias == "sell" and snapshot.high >= snapshot.ema_21 >= snapshot.close:
            scores["pullback"] = 25
            reasons.append("Short pullback to EMA21")
        else:
            return no_trade(self.strategy_id, ["No pullback entry"], scores)

        # Momentum (25)
        if bias == "buy" and snapshot.macd >= snapshot.macd_signal and snapshot.rsi < 60:
            scores["momentum"] = 25
            reasons.append(f"Bullish momentum RSI={snapshot.rsi:.1f}")
        elif bias == "sell" and snapshot.macd <= snapshot.macd_signal and snapshot.rsi > 40:
            scores["momentum"] = 25
            reasons.append(f"Bearish momentum RSI={snapshot.rsi:.1f}")
        else:
            scores["momentum"] = 5

        # Trend alignment (20) + RR (10)
        if bias == "buy" and snapshot.trend_direction in ("up", "sideways"):
            scores["trend"] = 20
        elif bias == "sell" and snapshot.trend_direction in ("down", "sideways"):
            scores["trend"] = 20
        else:
            scores["trend"] = 5
        scores["risk_reward"] = 10

        total = sum(scores.values())
        confidence = min(100.0, round(total / 1.05, 1))
        if scores.get("momentum", 0) < 10:
            return no_trade(self.strategy_id, reasons + ["Weak momentum"], scores)

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
        ctx = ctx or StrategyContext()
        # Bias mode defaults hold to swing
        if not ctx.hold_policy or ctx.hold_policy == "intraday":
            ctx = StrategyContext(
                trade_mode="bias",
                directional_bias=ctx.directional_bias,
                hold_policy="swing",
            )
        return evaluation_to_signal(self.evaluate_snapshot(snap, ctx), snap, ctx)
