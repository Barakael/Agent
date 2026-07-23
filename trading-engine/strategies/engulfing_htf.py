"""Engulfing candle filtered by higher-timeframe EMA direction."""

from __future__ import annotations

from typing import Optional

import pandas as pd

from signals.engine import SignalDirection
from strategies.base import StrategyContext, StrategySignal, make_signal


class EngulfingHtfStrategy:
    strategy_id = "engulfing_htf"
    trade_mode = "pattern"
    htf_factor = 3  # ~15m if base is 5m

    def evaluate(
        self, symbol: str, df: pd.DataFrame, ctx: StrategyContext | None = None
    ) -> Optional[StrategySignal]:
        ctx = ctx or StrategyContext()
        if len(df) < 60:
            return None
        o = df["open"].astype(float) if "open" in df.columns else df["close"].astype(float).shift(1)
        h = df["high"].astype(float) if "high" in df.columns else df["close"].astype(float)
        l = df["low"].astype(float) if "low" in df.columns else df["close"].astype(float)
        c = df["close"].astype(float)

        # HTF close via resample-like step
        htf_close = c.iloc[:: self.htf_factor]
        if len(htf_close) < 30:
            return None
        htf_ema = htf_close.ewm(span=20, adjust=False).mean()
        htf_bull = float(htf_close.iloc[-1]) > float(htf_ema.iloc[-1])
        htf_bear = float(htf_close.iloc[-1]) < float(htf_ema.iloc[-1])

        prev_o, prev_c = float(o.iloc[-2]), float(c.iloc[-2])
        cur_o, cur_c = float(o.iloc[-1]), float(c.iloc[-1])
        price = float(c.iloc[-1])
        epoch = int(df["epoch"].iloc[-1])

        bull_engulf = prev_c < prev_o and cur_c > cur_o and cur_c >= prev_o and cur_o <= prev_c
        bear_engulf = prev_c > prev_o and cur_c < cur_o and cur_c <= prev_o and cur_o >= prev_c

        if bull_engulf and htf_bull:
            return make_signal(
                strategy_id=self.strategy_id,
                symbol=symbol,
                direction=SignalDirection.BUY,
                price=price,
                epoch=epoch,
                reason="Bullish engulfing + HTF EMA up",
                trade_mode=ctx.trade_mode,
                hold_policy=ctx.hold_policy,
            )
        if bear_engulf and htf_bear:
            return make_signal(
                strategy_id=self.strategy_id,
                symbol=symbol,
                direction=SignalDirection.SELL,
                price=price,
                epoch=epoch,
                reason="Bearish engulfing + HTF EMA down",
                trade_mode=ctx.trade_mode,
                hold_policy=ctx.hold_policy,
            )
        return None
