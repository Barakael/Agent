"""Aggregate tick data into OHLC candles with a rolling buffer."""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Deque, Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class Candle:
    symbol: str
    epoch: int  # candle open time (unix)
    open: float
    high: float
    low: float
    close: float
    volume: int = 0

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "epoch": self.epoch,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
        }


@dataclass
class SymbolCandleState:
    symbol: str
    timeframe_seconds: int
    buffer_size: int
    current_bucket: Optional[int] = None
    current_candle: Optional[Candle] = None
    closed_candles: Deque[Candle] = field(default_factory=deque)

    def __post_init__(self) -> None:
        self.closed_candles = deque(maxlen=self.buffer_size)


class CandleAggregator:
    """Build OHLC candles from ticks; emit on bucket close."""

    def __init__(self, timeframe_minutes: int = 5, buffer_size: int = 200) -> None:
        self.timeframe_seconds = timeframe_minutes * 60
        self.buffer_size = buffer_size
        self._states: Dict[str, SymbolCandleState] = {}

    def _state(self, symbol: str) -> SymbolCandleState:
        if symbol not in self._states:
            self._states[symbol] = SymbolCandleState(
                symbol=symbol,
                timeframe_seconds=self.timeframe_seconds,
                buffer_size=self.buffer_size,
            )
        return self._states[symbol]

    @staticmethod
    def bucket_epoch(epoch: int, timeframe_seconds: int) -> int:
        return (epoch // timeframe_seconds) * timeframe_seconds

    def on_tick(
        self, symbol: str, price: float, epoch: Optional[int] = None
    ) -> Optional[Candle]:
        """Process a tick; return closed candle if a bucket completed."""
        epoch = epoch or int(datetime.now(timezone.utc).timestamp())
        state = self._state(symbol)
        bucket = self.bucket_epoch(epoch, self.timeframe_seconds)

        if state.current_bucket is None:
            state.current_bucket = bucket
            state.current_candle = Candle(
                symbol=symbol,
                epoch=bucket,
                open=price,
                high=price,
                low=price,
                close=price,
                volume=1,
            )
            return None

        if bucket > state.current_bucket:
            closed = state.current_candle
            if closed is not None:
                state.closed_candles.append(closed)
                logger.debug(
                    "Candle closed %s @ %s O=%.5f C=%.5f",
                    symbol,
                    closed.epoch,
                    closed.open,
                    closed.close,
                )
            state.current_bucket = bucket
            state.current_candle = Candle(
                symbol=symbol,
                epoch=bucket,
                open=price,
                high=price,
                low=price,
                close=price,
                volume=1,
            )
            return closed

        candle = state.current_candle
        if candle is None:
            return None
        candle.high = max(candle.high, price)
        candle.low = min(candle.low, price)
        candle.close = price
        candle.volume += 1
        return None

    def load_historical_candles(self, symbol: str, candles: List[dict]) -> None:
        """Seed buffer from Deriv ticks_history OHLC rows."""
        state = self._state(symbol)
        state.closed_candles.clear()
        state.current_bucket = None
        state.current_candle = None
        if not candles:
            return
        parsed: List[Candle] = []
        for row in candles:
            parsed.append(
                Candle(
                    symbol=symbol,
                    epoch=int(row["epoch"]),
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=int(row.get("volume", 0)),
                )
            )
        # All but last are closed; last is the forming candle so ticks keep updating
        # and the next bucket boundary fires a real close (not a None no-op).
        for c in parsed[:-1]:
            state.closed_candles.append(c)
        last = parsed[-1]
        state.current_bucket = last.epoch
        state.current_candle = Candle(
            symbol=last.symbol,
            epoch=last.epoch,
            open=last.open,
            high=last.high,
            low=last.low,
            close=last.close,
            volume=last.volume,
        )

    def get_dataframe(self, symbol: str) -> pd.DataFrame:
        state = self._state(symbol)
        rows = [c.to_dict() for c in state.closed_candles]
        if state.current_candle:
            rows.append(state.current_candle.to_dict())
        if not rows:
            return pd.DataFrame(
                columns=["symbol", "epoch", "open", "high", "low", "close", "volume"]
            )
        df = pd.DataFrame(rows)
        df = df.sort_values("epoch").reset_index(drop=True)
        return df

    def latest_closed(self, symbol: str) -> Optional[Candle]:
        state = self._state(symbol)
        if state.closed_candles:
            return state.closed_candles[-1]
        return None
