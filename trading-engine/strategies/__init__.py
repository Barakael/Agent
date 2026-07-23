"""Strategy registry and dispatcher."""

from __future__ import annotations

from typing import Iterable, Optional

import pandas as pd

from strategies.base import StrategyContext, StrategySignal
from strategies.bias_swing import BiasSwingStrategy
from strategies.bollinger_mean_reversion import BollingerMeanReversionStrategy
from strategies.ema_pullback import EmaPullbackStrategy
from strategies.engulfing_htf import EngulfingHtfStrategy
from strategies.macd_rsi import MacdRsiStrategy
from strategies.rsi_divergence import RsiDivergenceStrategy

PATTERN_STRATEGY_IDS = (
    "macd_rsi",
    "ema_pullback",
    "rsi_divergence",
    "bollinger_mean_reversion",
    "engulfing_htf",
)

ALL_STRATEGY_IDS = PATTERN_STRATEGY_IDS + ("bias_swing",)

_REGISTRY = {
    "macd_rsi": MacdRsiStrategy(),
    "ema_pullback": EmaPullbackStrategy(),
    "rsi_divergence": RsiDivergenceStrategy(),
    "bollinger_mean_reversion": BollingerMeanReversionStrategy(),
    "engulfing_htf": EngulfingHtfStrategy(),
    "bias_swing": BiasSwingStrategy(),
}


def get_strategy(strategy_id: str):
    return _REGISTRY.get(strategy_id)


def evaluate_strategies(
    symbol: str,
    df: pd.DataFrame,
    strategy_ids: Iterable[str],
    ctx: StrategyContext,
    armed_ids: Optional[set[str]] = None,
) -> Optional[StrategySignal]:
    """Return first signal from enabled strategies (order preserved)."""
    for sid in strategy_ids:
        if armed_ids is not None and sid not in armed_ids and sid != "bias_swing":
            continue
        strat = _REGISTRY.get(sid)
        if not strat:
            continue
        signal = strat.evaluate(symbol, df, ctx)
        if signal is not None:
            return signal
    return None
