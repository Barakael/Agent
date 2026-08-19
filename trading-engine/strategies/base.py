"""Strategy protocol shared by pattern and bias modes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Protocol

import pandas as pd

from number_engine.snapshot import MarketSnapshot
from signals.engine import SignalDirection, TradeSignal


@dataclass
class StrategyContext:
    trade_mode: str = "pattern"  # pattern | bias
    directional_bias: Optional[str] = None  # buy | sell | neutral
    hold_policy: str = "intraday"  # intraday | swing
    enabled: bool = True


@dataclass
class StrategySignal(TradeSignal):
    strategy_id: str = "momentum"
    trade_mode: str = "pattern"
    hold_policy: str = "intraday"
    confidence: float = 0.0
    market_condition: str = ""
    score_breakdown: dict = field(default_factory=dict)
    suggested_sl: Optional[float] = None
    suggested_tp: Optional[float] = None
    sl_tp_method: str = "atr"
    bias_id: Optional[str] = None
    feature_json: Optional[dict] = None
    gates: Optional[dict] = None

    def to_dict(self) -> dict:
        base = super().to_dict()
        base.update(
            {
                "strategy_id": self.strategy_id,
                "trade_mode": self.trade_mode,
                "hold_policy": self.hold_policy,
                "confidence": self.confidence,
                "market_condition": self.market_condition,
                "score_breakdown": self.score_breakdown,
                "suggested_sl": self.suggested_sl,
                "suggested_tp": self.suggested_tp,
                "sl_tp_method": self.sl_tp_method,
                "bias_id": self.bias_id,
                "feature_json": self.feature_json,
                "gates": self.gates,
            }
        )
        return base


@dataclass
class StrategyEvaluation:
    """Result of one strategy analysing a MarketSnapshot."""

    strategy_id: str
    direction: SignalDirection  # BUY / SELL / NONE (= no trade)
    confidence: float
    reasons: list[str] = field(default_factory=list)
    score_breakdown: dict = field(default_factory=dict)
    suggested_sl: Optional[float] = None
    suggested_tp: Optional[float] = None
    sl_tp_method: str = "atr"
    # Entry trigger that produced this evaluation, so a pattern can be required
    # or excluded independently of the confidence score.
    pattern: Optional[str] = None

    @property
    def is_trade(self) -> bool:
        return self.direction in (SignalDirection.BUY, SignalDirection.SELL) and self.confidence > 0


class Strategy(Protocol):
    strategy_id: str
    trade_mode: str
    regimes: tuple[str, ...]

    def evaluate_snapshot(
        self, snapshot: MarketSnapshot, ctx: StrategyContext | None = None
    ) -> StrategyEvaluation:
        ...

    def evaluate(
        self, symbol: str, df: pd.DataFrame, ctx: StrategyContext | None = None
    ) -> Optional[StrategySignal]:
        ...


MIN_RR = 1.5  # never ship a target closer than 1.5x the stop


def atr_sl_tp(
    snapshot: MarketSnapshot,
    direction: SignalDirection,
    """Structure-aware ATR stop and R:R take-profit. TP is always at least 1.5R."""
    rr = max(rr, MIN_RR)
    rr: float = 2.0,
) -> tuple[float, float, str]:
    """Structure-aware ATR stop and R:R take-profit."""
    atr = max(snapshot.atr, 1e-8)
    price = snapshot.close
    method = "atr"

    if direction == SignalDirection.BUY:
        structure_sl = snapshot.swing_low - 0.1 * atr
        risk = max(price - sl, 1e-8)
        sl = min(structure_sl, atr_sl) if structure_sl < price else atr_sl
        # Prefer resistance as TP only when it offers at least MIN_RR
        if snapshot.resistance > price and (snapshot.resistance - price) >= MIN_RR * risk:
        risk = price - sl
        tp = price + rr * risk
        # Enforce minimum RR
        if (tp - price) < MIN_RR * risk:
            tp = price + MIN_RR * risk
        # Prefer resistance as TP if it offers at least 1.5R
        if snapshot.resistance > price and (snapshot.resistance - price) >= 1.5 * risk:
            tp = snapshot.resistance
        risk = max(sl - price, 1e-8)
    else:
        if snapshot.support < price and (price - snapshot.support) >= MIN_RR * risk:
        atr_sl = price + atr_mult * atr
        sl = max(structure_sl, atr_sl) if structure_sl > price else atr_sl
        # Enforce minimum RR
        if (price - tp) < MIN_RR * risk:
            tp = price - MIN_RR * risk
        if structure_sl > price:
            method = "atr_swing"
        risk = sl - price
        tp = price - rr * risk
        if snapshot.support < price and (price - snapshot.support) >= 1.5 * risk:
            tp = snapshot.support
            method = "atr_structure"
    return sl, tp, method


def make_signal(
    *,
    strategy_id: str,
    symbol: str,
    direction: SignalDirection,
    price: float,
    epoch: int,
    reason: str,
    rsi: float = 0.0,
    macd: float = 0.0,
    macd_signal: float = 0.0,
    trade_mode: str = "pattern",
    hold_policy: str = "intraday",
    confidence: float = 0.0,
    market_condition: str = "",
    score_breakdown: dict | None = None,
    suggested_sl: float | None = None,
    suggested_tp: float | None = None,
    sl_tp_method: str = "atr",
    bias_id: str | None = None,
    feature_json: dict | None = None,
    gates: dict | None = None,
) -> StrategySignal:
    return StrategySignal(
        symbol=symbol,
        direction=direction,
        rsi=rsi,
        macd=macd,
        macd_signal=macd_signal,
        price=price,
        epoch=epoch,
        reason=reason,
        strategy_id=strategy_id,
        trade_mode=trade_mode,
        hold_policy=hold_policy,
        confidence=confidence,
        market_condition=market_condition,
        score_breakdown=score_breakdown or {},
        suggested_sl=suggested_sl,
        suggested_tp=suggested_tp,
        sl_tp_method=sl_tp_method,
        bias_id=bias_id,
        feature_json=feature_json,
        gates=gates,
    )


def evaluation_to_signal(
    ev: StrategyEvaluation,
    snapshot: MarketSnapshot,
    ctx: StrategyContext,
) -> Optional[StrategySignal]:
    if not ev.is_trade:
        return None
    return make_signal(
        strategy_id=ev.strategy_id,
        symbol=snapshot.symbol,
        direction=ev.direction,
        price=snapshot.close,
        epoch=snapshot.epoch,
        reason="; ".join(ev.reasons) if ev.reasons else ev.strategy_id,
        rsi=snapshot.rsi,
        macd=snapshot.macd,
        macd_signal=snapshot.macd_signal,
        trade_mode=ctx.trade_mode,
        hold_policy=ctx.hold_policy,
        confidence=ev.confidence,
        market_condition=snapshot.regime,
        score_breakdown=ev.score_breakdown,
        suggested_sl=ev.suggested_sl,
        suggested_tp=ev.suggested_tp,
        sl_tp_method=ev.sl_tp_method,
    )


def no_trade(strategy_id: str, reasons: list[str], breakdown: dict | None = None) -> StrategyEvaluation:
    return StrategyEvaluation(
        strategy_id=strategy_id,
        direction=SignalDirection.NONE,
        confidence=0.0,
        reasons=reasons,
        score_breakdown=breakdown or {},
    )
