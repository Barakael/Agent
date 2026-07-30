"""Strategy registry and Strategy Manager (regime + confidence selection)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Iterable, Optional

import pandas as pd

from config import settings
from number_engine.snapshot import MarketSnapshot
from signals.engine import SignalDirection
from strategies.base import (
    StrategyContext,
    StrategyEvaluation,
    StrategySignal,
    evaluation_to_signal,
)
from strategies.bias_swing import BiasSwingStrategy
from strategies.breakout import BreakoutStrategy
from strategies.momentum import MomentumStrategy
from strategies.price_action import PriceActionStrategy
from strategies.range_trading import RangeTradingStrategy
from strategies.trend_following import TrendFollowingStrategy

logger = logging.getLogger(__name__)

# Primary archetypes
PATTERN_STRATEGY_IDS = (
    "trend_following",
    "breakout",
    "range_trading",
    "momentum",
    "price_action",
)

ALL_STRATEGY_IDS = PATTERN_STRATEGY_IDS + ("bias_swing",)

# Legacy plan/webhook IDs → archetype
STRATEGY_ALIASES = {
    "macd_rsi": "momentum",
    "ema_pullback": "trend_following",
    "bollinger_mean_reversion": "range_trading",
    "engulfing_htf": "price_action",
    "rsi_divergence": "momentum",
}

REGIME_STRATEGIES = {
    "trending": ("trend_following", "momentum", "price_action"),
    "ranging": ("range_trading", "price_action"),
    "breakout": ("breakout", "momentum", "price_action"),
    "quiet": (),
}

_REGISTRY = {
    "trend_following": TrendFollowingStrategy(),
    "breakout": BreakoutStrategy(),
    "range_trading": RangeTradingStrategy(),
    "momentum": MomentumStrategy(),
    "price_action": PriceActionStrategy(),
    "bias_swing": BiasSwingStrategy(),
}


def resolve_strategy_id(strategy_id: str) -> str:
    return STRATEGY_ALIASES.get(strategy_id, strategy_id)


def get_strategy(strategy_id: str):
    return _REGISTRY.get(resolve_strategy_id(strategy_id))


def allowlist_strategy_ids() -> list[str]:
    """Resolved STRATEGY_ALLOWLIST ids; empty list means no restriction."""
    raw = list(getattr(settings, "strategy_allowlist", None) or [])
    if not raw:
        # Fallback if property missing in older settings
        text = str(getattr(settings, "STRATEGY_ALLOWLIST", "") or "")
        raw = [p.strip() for p in text.split(",") if p.strip()]
    if not raw:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for sid in raw:
        resolved = resolve_strategy_id(sid)
        if resolved in seen:
            continue
        seen.add(resolved)
        out.append(resolved)
    return out


def apply_strategy_allowlist(strategy_ids: Iterable[str]) -> list[str]:
    """Filter requested ids by allowlist when configured."""
    requested = [resolve_strategy_id(s) for s in strategy_ids]
    allowed = allowlist_strategy_ids()
    if not allowed:
        return requested
    allowed_set = set(allowed)
    return [s for s in requested if s in allowed_set]


@dataclass
class ManagerResult:
    signal: Optional[StrategySignal]
    regime: str
    evaluations: list[StrategyEvaluation] = field(default_factory=list)
    skip_reason: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "regime": self.regime,
            "skip_reason": self.skip_reason,
            "signal": self.signal.to_dict() if self.signal else None,
            "evaluations": [
                {
                    "strategy_id": e.strategy_id,
                    "direction": e.direction.value,
                    "confidence": e.confidence,
                    "reasons": e.reasons,
                    "score_breakdown": e.score_breakdown,
                }
                for e in self.evaluations
            ],
        }


class StrategyManager:
    """Regime router + multi-strategy confidence scoring. No Trade is valid."""

    def __init__(self, confidence_threshold: float | None = None) -> None:
        self.confidence_threshold = (
            confidence_threshold
            if confidence_threshold is not None
            else float(getattr(settings, "STRATEGY_CONFIDENCE_THRESHOLD", 88.0))
        )

    def select(
        self,
        snapshot: MarketSnapshot,
        strategy_ids: Iterable[str],
        ctx: StrategyContext,
        armed_ids: Optional[set[str]] = None,
    ) -> ManagerResult:
        regime = snapshot.regime
        if regime == "quiet":
            return ManagerResult(
                signal=None,
                regime=regime,
                evaluations=[],
                skip_reason="Quiet market — no trade",
            )

        # Bias mode: only bias_swing
        if ctx.trade_mode == "bias":
            strat = _REGISTRY["bias_swing"]
            ev = strat.evaluate_snapshot(snapshot, ctx)
            evaluations = [ev]
            if ev.is_trade and ev.confidence >= self.confidence_threshold:
                return ManagerResult(
                    signal=evaluation_to_signal(ev, snapshot, ctx),
                    regime=regime,
                    evaluations=evaluations,
                )
            return ManagerResult(
                signal=None,
                regime=regime,
                evaluations=evaluations,
                skip_reason=(
                    f"Bias confidence {ev.confidence:.0f} < {self.confidence_threshold:.0f}"
                    if ev.is_trade
                    else "; ".join(ev.reasons) or "Bias no trade"
                ),
            )

        allowed_by_regime = set(REGIME_STRATEGIES.get(regime, ()))
        requested = apply_strategy_allowlist(strategy_ids)
        allowlist = allowlist_strategy_ids()
        if allowlist and not requested:
            return ManagerResult(
                signal=None,
                regime=regime,
                evaluations=[],
                skip_reason="No strategies in allowlist for this request",
            )
        # Deduplicate while preserving order
        seen: set[str] = set()
        ordered: list[str] = []
        for sid in requested:
            if sid in seen:
                continue
            seen.add(sid)
            ordered.append(sid)

        candidates = []
        for sid in ordered:
            if sid == "bias_swing":
                continue
            # Focused allowlist: still evaluate those strategies outside the regime map
            # (strategy quality filters decide). Broad mode keeps regime routing.
            if sid not in allowed_by_regime and not (allowlist and sid in allowlist):
                continue
            if armed_ids is not None:
                # Armed set may contain legacy or new ids
                armed_resolved = {resolve_strategy_id(a) for a in armed_ids}
                if sid not in armed_resolved and sid not in armed_ids:
                    continue
            strat = _REGISTRY.get(sid)
            if not strat:
                continue
            candidates.append(strat)

        if not candidates:
            # Fall back: evaluate requested pattern strategies even if regime map empty
            for sid in ordered:
                if sid == "bias_swing":
                    continue
                strat = _REGISTRY.get(sid)
                if strat:
                    candidates.append(strat)
            if not candidates:
                return ManagerResult(
                    signal=None,
                    regime=regime,
                    evaluations=[],
                    skip_reason=f"No strategy candidates for regime={regime}",
                )

        evaluations: list[StrategyEvaluation] = []
        for strat in candidates:
            evaluations.append(strat.evaluate_snapshot(snapshot, ctx))

        tradeable = [
            e
            for e in evaluations
            if e.is_trade and e.confidence >= self.confidence_threshold
        ]
        if not tradeable:
            best = max(evaluations, key=lambda e: e.confidence, default=None)
            reason = "No strategy above confidence threshold"
            if best and best.is_trade:
                reason = (
                    f"Best {best.strategy_id} confidence {best.confidence:.0f} "
                    f"< {self.confidence_threshold:.0f}"
                )
            elif best:
                reason = "; ".join(best.reasons) or reason
            return ManagerResult(
                signal=None,
                regime=regime,
                evaluations=evaluations,
                skip_reason=reason,
            )

        winner = max(tradeable, key=lambda e: e.confidence)
        signal = evaluation_to_signal(winner, snapshot, ctx)
        logger.info(
            "StrategyManager %s regime=%s picked %s conf=%.1f",
            snapshot.symbol,
            regime,
            winner.strategy_id,
            winner.confidence,
        )
        return ManagerResult(signal=signal, regime=regime, evaluations=evaluations)


_manager = StrategyManager()


def evaluate_strategies(
    symbol: str,
    df: pd.DataFrame,
    strategy_ids: Iterable[str],
    ctx: StrategyContext,
    armed_ids: Optional[set[str]] = None,
    snapshot: Optional[MarketSnapshot] = None,
) -> Optional[StrategySignal]:
    """Backward-compatible entry: returns winning signal or None."""
    result = evaluate_strategies_detailed(
        symbol, df, strategy_ids, ctx, armed_ids=armed_ids, snapshot=snapshot
    )
    return result.signal


def evaluate_strategies_detailed(
    symbol: str,
    df: pd.DataFrame,
    strategy_ids: Iterable[str],
    ctx: StrategyContext,
    armed_ids: Optional[set[str]] = None,
    snapshot: Optional[MarketSnapshot] = None,
) -> ManagerResult:
    from number_engine import NumberEngine

    snap = snapshot or NumberEngine().compute(symbol, df)
    if snap is None:
        return ManagerResult(
            signal=None,
            regime="quiet",
            skip_reason="Insufficient data for Number Engine",
        )
    return _manager.select(snap, strategy_ids, ctx, armed_ids=armed_ids)
