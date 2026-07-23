"""MACD + RSI confluence pattern strategy."""

from __future__ import annotations

from typing import Optional

import pandas as pd

from config import settings
from indicators.macd import compute_macd, detect_bearish_crossover, detect_bullish_crossover
from indicators.rsi import compute_rsi
from signals.engine import SignalDirection
from strategies.base import StrategyContext, StrategySignal, make_signal


class MacdRsiStrategy:
    strategy_id = "macd_rsi"
    trade_mode = "pattern"

    def __init__(self) -> None:
        self.rsi_period = settings.RSI_PERIOD
        self.macd_fast = settings.MACD_FAST
        self.macd_slow = settings.MACD_SLOW
        self.macd_signal_period = settings.MACD_SIGNAL
        self.rsi_buy_max = 55.0
        self.rsi_sell_min = 45.0

    def evaluate(
        self, symbol: str, df: pd.DataFrame, ctx: StrategyContext | None = None
    ) -> Optional[StrategySignal]:
        ctx = ctx or StrategyContext()
        min_bars = max(self.rsi_period, self.macd_slow + self.macd_signal_period) + 2
        if len(df) < min_bars:
            return None

        close = df["close"].astype(float)
        rsi_series = compute_rsi(close, self.rsi_period)
        macd_line, signal_line, _ = compute_macd(
            close, self.macd_fast, self.macd_slow, self.macd_signal_period
        )
        rsi_val = float(rsi_series.iloc[-1])
        macd_val = float(macd_line.iloc[-1])
        signal_val = float(signal_line.iloc[-1])
        price = float(close.iloc[-1])
        epoch = int(df["epoch"].iloc[-1])

        bull = detect_bullish_crossover(macd_line, signal_line)
        bear = detect_bearish_crossover(macd_line, signal_line)

        if bull and rsi_val < self.rsi_buy_max:
            return make_signal(
                strategy_id=self.strategy_id,
                symbol=symbol,
                direction=SignalDirection.BUY,
                price=price,
                epoch=epoch,
                reason=f"MACD bullish cross + RSI {rsi_val:.1f} < {self.rsi_buy_max}",
                rsi=rsi_val,
                macd=macd_val,
                macd_signal=signal_val,
                trade_mode=ctx.trade_mode,
                hold_policy=ctx.hold_policy,
            )
        if bear and rsi_val > self.rsi_sell_min:
            return make_signal(
                strategy_id=self.strategy_id,
                symbol=symbol,
                direction=SignalDirection.SELL,
                price=price,
                epoch=epoch,
                reason=f"MACD bearish cross + RSI {rsi_val:.1f} > {self.rsi_sell_min}",
                rsi=rsi_val,
                macd=macd_val,
                macd_signal=signal_val,
                trade_mode=ctx.trade_mode,
                hold_policy=ctx.hold_policy,
            )
        return None
