"""EMA trend stack + pullback entry."""

from __future__ import annotations

from typing import Optional

import pandas as pd

from indicators.rsi import compute_rsi
from signals.engine import SignalDirection
from strategies.base import StrategyContext, StrategySignal, make_signal


class EmaPullbackStrategy:
    strategy_id = "ema_pullback"
    trade_mode = "pattern"

    def __init__(self, fast: int = 9, mid: int = 21, slow: int = 50) -> None:
        self.fast = fast
        self.mid = mid
        self.slow = slow

    def evaluate(
        self, symbol: str, df: pd.DataFrame, ctx: StrategyContext | None = None
    ) -> Optional[StrategySignal]:
        ctx = ctx or StrategyContext()
        if len(df) < self.slow + 5:
            return None
        close = df["close"].astype(float)
        ema_f = close.ewm(span=self.fast, adjust=False).mean()
        ema_m = close.ewm(span=self.mid, adjust=False).mean()
        ema_s = close.ewm(span=self.slow, adjust=False).mean()
        rsi = compute_rsi(close, 14)
        price = float(close.iloc[-1])
        epoch = int(df["epoch"].iloc[-1])
        rsi_val = float(rsi.iloc[-1])

        uptrend = ema_f.iloc[-1] > ema_m.iloc[-1] > ema_s.iloc[-1]
        downtrend = ema_f.iloc[-1] < ema_m.iloc[-1] < ema_s.iloc[-1]
        # Pullback: prior bar touched mid EMA, current closes back with trend
        prev_low = float(df["low"].astype(float).iloc[-2]) if "low" in df.columns else float(close.iloc[-2])
        prev_high = float(df["high"].astype(float).iloc[-2]) if "high" in df.columns else float(close.iloc[-2])
        mid = float(ema_m.iloc[-1])

        if uptrend and prev_low <= mid and price > mid and 40 <= rsi_val <= 60:
            return make_signal(
                strategy_id=self.strategy_id,
                symbol=symbol,
                direction=SignalDirection.BUY,
                price=price,
                epoch=epoch,
                reason=f"EMA pullback long RSI={rsi_val:.1f}",
                rsi=rsi_val,
                trade_mode=ctx.trade_mode,
                hold_policy=ctx.hold_policy,
            )
        if downtrend and prev_high >= mid and price < mid and 40 <= rsi_val <= 60:
            return make_signal(
                strategy_id=self.strategy_id,
                symbol=symbol,
                direction=SignalDirection.SELL,
                price=price,
                epoch=epoch,
                reason=f"EMA pullback short RSI={rsi_val:.1f}",
                rsi=rsi_val,
                trade_mode=ctx.trade_mode,
                hold_policy=ctx.hold_policy,
            )
        return None
