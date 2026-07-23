"""RSI divergence vs recent swing highs/lows."""

from __future__ import annotations

from typing import Optional

import pandas as pd

from indicators.rsi import compute_rsi
from signals.engine import SignalDirection
from strategies.base import StrategyContext, StrategySignal, make_signal


class RsiDivergenceStrategy:
    strategy_id = "rsi_divergence"
    trade_mode = "pattern"
    lookback = 20

    def evaluate(
        self, symbol: str, df: pd.DataFrame, ctx: StrategyContext | None = None
    ) -> Optional[StrategySignal]:
        ctx = ctx or StrategyContext()
        if len(df) < self.lookback + 15:
            return None
        close = df["close"].astype(float)
        rsi = compute_rsi(close, 14)
        window = close.iloc[-self.lookback :]
        rsi_w = rsi.iloc[-self.lookback :]
        price = float(close.iloc[-1])
        epoch = int(df["epoch"].iloc[-1])
        rsi_val = float(rsi.iloc[-1])

        # Bullish divergence: price lower low, RSI higher low
        price_ll = float(window.iloc[-1]) < float(window.iloc[:-3].min())
        rsi_hl = float(rsi_w.iloc[-1]) > float(rsi_w.iloc[:-3].min()) + 2
        # Bearish divergence: price higher high, RSI lower high
        price_hh = float(window.iloc[-1]) > float(window.iloc[:-3].max())
        rsi_lh = float(rsi_w.iloc[-1]) < float(rsi_w.iloc[:-3].max()) - 2

        if price_ll and rsi_hl and rsi_val < 45:
            return make_signal(
                strategy_id=self.strategy_id,
                symbol=symbol,
                direction=SignalDirection.BUY,
                price=price,
                epoch=epoch,
                reason=f"Bullish RSI divergence RSI={rsi_val:.1f}",
                rsi=rsi_val,
                trade_mode=ctx.trade_mode,
                hold_policy=ctx.hold_policy,
            )
        if price_hh and rsi_lh and rsi_val > 55:
            return make_signal(
                strategy_id=self.strategy_id,
                symbol=symbol,
                direction=SignalDirection.SELL,
                price=price,
                epoch=epoch,
                reason=f"Bearish RSI divergence RSI={rsi_val:.1f}",
                rsi=rsi_val,
                trade_mode=ctx.trade_mode,
                hold_policy=ctx.hold_policy,
            )
        return None
