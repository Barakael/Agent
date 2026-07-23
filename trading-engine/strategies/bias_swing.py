"""Directional bias / swing entries — pullback with HTF confirmation."""

from __future__ import annotations

from typing import Optional

import pandas as pd

from indicators.macd import compute_macd
from indicators.rsi import compute_rsi
from signals.engine import SignalDirection
from strategies.base import StrategyContext, StrategySignal, make_signal


class BiasSwingStrategy:
    strategy_id = "bias_swing"
    trade_mode = "bias"

    def evaluate(
        self, symbol: str, df: pd.DataFrame, ctx: StrategyContext | None = None
    ) -> Optional[StrategySignal]:
        ctx = ctx or StrategyContext()
        bias = (ctx.directional_bias or "neutral").lower()
        if bias not in {"buy", "sell"}:
            return None
        if len(df) < 80:
            return None

        close = df["close"].astype(float)
        ema20 = close.ewm(span=20, adjust=False).mean()
        ema50 = close.ewm(span=50, adjust=False).mean()
        rsi = compute_rsi(close, 14)
        macd_line, signal_line, _ = compute_macd(close, 12, 26, 9)
        price = float(close.iloc[-1])
        epoch = int(df["epoch"].iloc[-1])
        rsi_val = float(rsi.iloc[-1])
        htf = close.iloc[::3]
        htf_ema = htf.ewm(span=20, adjust=False).mean()

        if bias == "buy":
            htf_ok = float(htf.iloc[-1]) >= float(htf_ema.iloc[-1])
            structure = float(ema20.iloc[-1]) >= float(ema50.iloc[-1])
            pullback = float(close.iloc[-2]) <= float(ema20.iloc[-2]) and price >= float(ema20.iloc[-1])
            momentum = float(macd_line.iloc[-1]) >= float(signal_line.iloc[-1]) and rsi_val < 60
            if htf_ok and structure and pullback and momentum:
                return make_signal(
                    strategy_id=self.strategy_id,
                    symbol=symbol,
                    direction=SignalDirection.BUY,
                    price=price,
                    epoch=epoch,
                    reason=f"Bias long pullback RSI={rsi_val:.1f}",
                    rsi=rsi_val,
                    macd=float(macd_line.iloc[-1]),
                    macd_signal=float(signal_line.iloc[-1]),
                    trade_mode="bias",
                    hold_policy=ctx.hold_policy or "swing",
                )
        else:
            htf_ok = float(htf.iloc[-1]) <= float(htf_ema.iloc[-1])
            structure = float(ema20.iloc[-1]) <= float(ema50.iloc[-1])
            pullback = float(close.iloc[-2]) >= float(ema20.iloc[-2]) and price <= float(ema20.iloc[-1])
            momentum = float(macd_line.iloc[-1]) <= float(signal_line.iloc[-1]) and rsi_val > 40
            if htf_ok and structure and pullback and momentum:
                return make_signal(
                    strategy_id=self.strategy_id,
                    symbol=symbol,
                    direction=SignalDirection.SELL,
                    price=price,
                    epoch=epoch,
                    reason=f"Bias short pullback RSI={rsi_val:.1f}",
                    rsi=rsi_val,
                    macd=float(macd_line.iloc[-1]),
                    macd_signal=float(signal_line.iloc[-1]),
                    trade_mode="bias",
                    hold_policy=ctx.hold_policy or "swing",
                )
        return None
