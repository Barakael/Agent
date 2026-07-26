"""Number Engine — compute all indicators once per candle close."""

from __future__ import annotations

import logging
from typing import Optional

import pandas as pd

from config import settings
from indicators.atr import compute_atr
from indicators.bollinger import compute_bollinger
from indicators.ema import compute_ema, compute_sma
from indicators.macd import (
    compute_macd,
    detect_bearish_crossover,
    detect_bullish_crossover,
)
from indicators.rsi import compute_rsi
from indicators.structure import (
    detect_engulfing,
    detect_inside_bar,
    detect_pin_bar,
    detect_structure,
)
from number_engine.regime import detect_regime
from number_engine.snapshot import MarketSnapshot

logger = logging.getLogger(__name__)


class NumberEngine:
    """Pure mathematics over OHLCV — no AI, no strategy decisions."""

    def __init__(
        self,
        rsi_period: int | None = None,
        macd_fast: int | None = None,
        macd_slow: int | None = None,
        macd_signal: int | None = None,
        atr_period: int = 14,
        bb_period: int = 20,
        bb_stdev: float = 2.0,
    ) -> None:
        self.rsi_period = rsi_period or settings.RSI_PERIOD
        self.macd_fast = macd_fast or settings.MACD_FAST
        self.macd_slow = macd_slow or settings.MACD_SLOW
        self.macd_signal = macd_signal or settings.MACD_SIGNAL
        self.atr_period = atr_period
        self.bb_period = bb_period
        self.bb_stdev = bb_stdev

    @property
    def min_bars(self) -> int:
        return max(60, self.macd_slow + self.macd_signal + 5, self.atr_period + 20)

    def compute(self, symbol: str, df: pd.DataFrame) -> Optional[MarketSnapshot]:
        if df is None or len(df) < self.min_bars:
            logger.debug(
                "NumberEngine insufficient bars for %s: %s < %s",
                symbol,
                0 if df is None else len(df),
                self.min_bars,
            )
            return None

        o = df["open"].astype(float) if "open" in df.columns else df["close"].astype(float).shift(1).fillna(df["close"])
        h = df["high"].astype(float) if "high" in df.columns else df["close"].astype(float)
        l = df["low"].astype(float) if "low" in df.columns else df["close"].astype(float)
        c = df["close"].astype(float)
        vol = df["volume"].astype(float) if "volume" in df.columns else pd.Series(0.0, index=df.index)

        ema9 = compute_ema(c, 9)
        ema21 = compute_ema(c, 21)
        ema50 = compute_ema(c, 50)
        sma20 = compute_sma(c, 20)
        rsi = compute_rsi(c, self.rsi_period)
        atr = compute_atr(h, l, c, self.atr_period)
        atr_sma = atr.rolling(20).mean()
        macd_line, signal_line, hist = compute_macd(
            c, self.macd_fast, self.macd_slow, self.macd_signal
        )
        bb_u, bb_m, bb_l = compute_bollinger(c, self.bb_period, self.bb_stdev)
        structure = detect_structure(h, l, c)

        price = float(c.iloc[-1])
        atr_val = float(atr.iloc[-1]) if pd.notna(atr.iloc[-1]) else 0.0
        atr_sma_val = float(atr_sma.iloc[-1]) if pd.notna(atr_sma.iloc[-1]) else atr_val
        bb_mid = float(bb_m.iloc[-1]) if pd.notna(bb_m.iloc[-1]) else price
        bb_upper = float(bb_u.iloc[-1]) if pd.notna(bb_u.iloc[-1]) else price
        bb_lower = float(bb_l.iloc[-1]) if pd.notna(bb_l.iloc[-1]) else price
        bb_width = (bb_upper - bb_lower) / max(bb_mid, 1e-12)
        bb_mid_prev = float(bb_m.iloc[-5]) if len(bb_m) >= 5 and pd.notna(bb_m.iloc[-5]) else bb_mid
        bb_mid_slope = abs(bb_mid - bb_mid_prev) / max(bb_mid, 1e-12)

        ema_aligned_up = float(ema9.iloc[-1]) > float(ema21.iloc[-1]) > float(ema50.iloc[-1])
        ema_aligned_down = float(ema9.iloc[-1]) < float(ema21.iloc[-1]) < float(ema50.iloc[-1])

        if ema_aligned_up and structure.trend == "up":
            trend_direction = "up"
        elif ema_aligned_down and structure.trend == "down":
            trend_direction = "down"
        elif ema_aligned_up:
            trend_direction = "up"
        elif ema_aligned_down:
            trend_direction = "down"
        else:
            trend_direction = structure.trend

        regime, regime_reasons = detect_regime(
            atr=atr_val,
            atr_sma=atr_sma_val,
            bb_width=bb_width,
            bb_mid_slope=bb_mid_slope,
            ema_aligned_up=ema_aligned_up,
            ema_aligned_down=ema_aligned_down,
            structure_trend=structure.trend,
            close=price,
            support=structure.support,
            resistance=structure.resistance,
        )

        prev_o, prev_c = float(o.iloc[-2]), float(c.iloc[-2])
        cur_o, cur_c = float(o.iloc[-1]), float(c.iloc[-1])
        prev_h, prev_l = float(h.iloc[-2]), float(l.iloc[-2])
        cur_h, cur_l = float(h.iloc[-1]), float(l.iloc[-1])

        # Break of structure: close beyond prior swing
        bos_up = price > structure.swing_high * 0.999 and structure.higher_highs
        bos_down = price < structure.swing_low * 1.001 and structure.lower_lows

        return MarketSnapshot(
            symbol=symbol,
            epoch=int(df["epoch"].iloc[-1]),
            open=cur_o,
            high=cur_h,
            low=cur_l,
            close=price,
            volume=float(vol.iloc[-1]) if len(vol) else 0.0,
            ema_9=float(ema9.iloc[-1]),
            ema_21=float(ema21.iloc[-1]),
            ema_50=float(ema50.iloc[-1]),
            sma_20=float(sma20.iloc[-1]) if pd.notna(sma20.iloc[-1]) else price,
            rsi=float(rsi.iloc[-1]),
            atr=atr_val,
            atr_sma=atr_sma_val,
            macd=float(macd_line.iloc[-1]),
            macd_signal=float(signal_line.iloc[-1]),
            macd_hist=float(hist.iloc[-1]),
            macd_hist_prev=float(hist.iloc[-2]) if len(hist) > 1 else 0.0,
            macd_bull_cross=detect_bullish_crossover(macd_line, signal_line),
            macd_bear_cross=detect_bearish_crossover(macd_line, signal_line),
            bb_upper=bb_upper,
            bb_mid=bb_mid,
            bb_lower=bb_lower,
            bb_width=bb_width,
            bb_mid_slope=bb_mid_slope,
            support=structure.support,
            resistance=structure.resistance,
            swing_low=structure.swing_low,
            swing_high=structure.swing_high,
            structure_trend=structure.trend,
            higher_highs=structure.higher_highs,
            higher_lows=structure.higher_lows,
            lower_highs=structure.lower_highs,
            lower_lows=structure.lower_lows,
            ema_aligned_up=ema_aligned_up,
            ema_aligned_down=ema_aligned_down,
            trend_direction=trend_direction,  # type: ignore[arg-type]
            regime=regime,
            regime_reasons=regime_reasons,
            pin_bar=detect_pin_bar(cur_o, cur_h, cur_l, cur_c),
            engulfing=detect_engulfing(prev_o, prev_c, cur_o, cur_c),
            inside_bar=detect_inside_bar(prev_h, prev_l, cur_h, cur_l),
            break_of_structure_up=bos_up,
            break_of_structure_down=bos_down,
            df=df,
        )
