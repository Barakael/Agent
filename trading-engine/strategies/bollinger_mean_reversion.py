"""Bollinger band mean reversion with RSI confirmation (range markets)."""

from __future__ import annotations

from typing import Optional

import pandas as pd

from indicators.rsi import compute_rsi
from signals.engine import SignalDirection
from strategies.base import StrategyContext, StrategySignal, make_signal


class BollingerMeanReversionStrategy:
    strategy_id = "bollinger_mean_reversion"
    trade_mode = "pattern"

    def __init__(self, period: int = 20, stdev: float = 2.0) -> None:
        self.period = period
        self.stdev = stdev

    def evaluate(
        self, symbol: str, df: pd.DataFrame, ctx: StrategyContext | None = None
    ) -> Optional[StrategySignal]:
        ctx = ctx or StrategyContext()
        if len(df) < self.period + 5:
            return None
        close = df["close"].astype(float)
        mid = close.rolling(self.period).mean()
        std = close.rolling(self.period).std()
        upper = mid + self.stdev * std
        lower = mid - self.stdev * std
        # Flat mid = range (reject strong trends)
        mid_slope = abs(float(mid.iloc[-1]) - float(mid.iloc[-5])) / max(float(mid.iloc[-1]), 1e-9)
        if mid_slope > 0.0015:
            return None
        rsi = compute_rsi(close, 14)
        price = float(close.iloc[-1])
        epoch = int(df["epoch"].iloc[-1])
        rsi_val = float(rsi.iloc[-1])
        prev = float(close.iloc[-2])

        if prev <= float(lower.iloc[-2]) and price > float(lower.iloc[-1]) and rsi_val < 35:
            return make_signal(
                strategy_id=self.strategy_id,
                symbol=symbol,
                direction=SignalDirection.BUY,
                price=price,
                epoch=epoch,
                reason=f"BB mean-reversion long RSI={rsi_val:.1f}",
                rsi=rsi_val,
                trade_mode=ctx.trade_mode,
                hold_policy=ctx.hold_policy,
            )
        if prev >= float(upper.iloc[-2]) and price < float(upper.iloc[-1]) and rsi_val > 65:
            return make_signal(
                strategy_id=self.strategy_id,
                symbol=symbol,
                direction=SignalDirection.SELL,
                price=price,
                epoch=epoch,
                reason=f"BB mean-reversion short RSI={rsi_val:.1f}",
                rsi=rsi_val,
                trade_mode=ctx.trade_mode,
                hold_policy=ctx.hold_policy,
            )
        return None
