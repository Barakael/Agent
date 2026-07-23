"""Strategy protocol shared by pattern and bias modes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Protocol

import pandas as pd

from signals.engine import SignalDirection, TradeSignal


@dataclass
class StrategyContext:
    trade_mode: str = "pattern"  # pattern | bias
    directional_bias: Optional[str] = None  # buy | sell | neutral
    hold_policy: str = "intraday"  # intraday | swing
    enabled: bool = True


@dataclass
class StrategySignal(TradeSignal):
    strategy_id: str = "macd_rsi"
    trade_mode: str = "pattern"
    hold_policy: str = "intraday"

    def to_dict(self) -> dict:
        base = super().to_dict()
        base.update(
            {
                "strategy_id": self.strategy_id,
                "trade_mode": self.trade_mode,
                "hold_policy": self.hold_policy,
            }
        )
        return base


class Strategy(Protocol):
    strategy_id: str
    trade_mode: str

    def evaluate(
        self, symbol: str, df: pd.DataFrame, ctx: StrategyContext | None = None
    ) -> Optional[StrategySignal]:
        ...


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
    )
