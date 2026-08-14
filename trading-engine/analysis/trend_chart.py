"""Multi-speed trend reads and the charts that show them.

The forecast is a volatility-normalised exponentially weighted moving average
crossover, averaged over three speeds. Dividing the crossover by volatility is
what makes a number comparable across instruments and across calm and violent
weeks: a 30-pip gap between averages means something different on EURUSD than on
USDJPY, but 0.8 ATRs means the same thing on both. This is the standard
construction in the systematic-trend literature (Carver, *Systematic Trading*,
ch. 7; Clenow, *Following the Trend*).

Nothing here is evidence of an edge. It measures and draws the state of the
market so a decision can be argued about; whether trading it pays is a separate
question answered by the replay harness and the acceptance gate.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Sequence

import pandas as pd

from execution.multiplier import contract_room_pct, stop_fits
from indicators.atr import compute_atr
from risk.gate import pip_size

logger = logging.getLogger(__name__)

# Fast/slow pairs in bars. Each speed catches a different length of move, and
# averaging them stops a single arbitrary lookback deciding everything.
TREND_SPEEDS: tuple[tuple[int, int], ...] = ((8, 32), (16, 64), (32, 128))

# Forecasts are capped so one violent move cannot dominate, and a small reading
# is treated as no signal rather than a weak one.
FORECAST_CAP = 2.0
FORECAST_ENTRY_THRESHOLD = 0.5


@dataclass
class SpeedForecast:
    fast: int
    slow: int
    raw: float
    forecast: float


@dataclass
class TrendRead:
    """What the trend looks like on one instrument, and what it would imply."""

    symbol: str
    price: float
    atr: float
    atr_pct: float
    forecast: float
    direction: str  # "long" | "short" | "flat"
    speeds: list[SpeedForecast] = field(default_factory=list)
    stop: Optional[float] = None
    target: Optional[float] = None
    multiplier: float = 0.0
    encodable: bool = False
    bars: int = 0
    # The volatility the stop was sized from, which may be a longer horizon than
    # the bars the trend was read on.
    stop_atr: float = 0.0

    @property
    def strength(self) -> str:
        magnitude = abs(self.forecast)
        if magnitude < FORECAST_ENTRY_THRESHOLD:
            return "none"
        if magnitude < 1.0:
            return "weak"
        if magnitude < 1.5:
            return "moderate"
        return "strong"

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "price": round(self.price, 5),
            "atr": round(self.atr, 5),
            "atr_pct": round(self.atr_pct, 5),
            "forecast": round(self.forecast, 3),
            "direction": self.direction,
            "strength": self.strength,
            "stop": round(self.stop, 5) if self.stop else None,
            "target": round(self.target, 5) if self.target else None,
            "stop_atr": round(self.stop_atr, 5),
            "encodable": self.encodable,
            "speeds": [
                {"fast": s.fast, "slow": s.slow, "forecast": round(s.forecast, 3)}
                for s in self.speeds
            ],
            "bars": self.bars,
        }

    def summary(self) -> str:
        pip = pip_size(self.symbol)
        if self.direction == "flat":
            return (
                f"{self.symbol}: no trend (forecast {self.forecast:+.2f}), "
                f"ATR {self.atr / pip:.0f} pips"
            )
        room = "" if self.encodable else "  [stop will not fit the contract]"
        stop_pips = abs(self.price - self.stop) / pip
        return (
            f"{self.symbol}: {self.direction} {self.strength} "
            f"(forecast {self.forecast:+.2f}) at {self.price:.5f}, "
            f"stop {self.stop:.5f} target {self.target:.5f}, "
            f"risking {stop_pips:.0f} pips{room}"
        )


def _ewma(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False, min_periods=span).mean()


def read_trend(
    df: pd.DataFrame,
    symbol: str,
    *,
    multiplier: float,
    atr_period: int = 14,
    stop_atr_mult: float = 1.0,
    reward_ratio: float = 1.5,
    stop_safety: float = 1.25,
    speeds: Sequence[tuple[int, int]] = TREND_SPEEDS,
    stop_atr: Optional[float] = None,
) -> Optional[TrendRead]:
    """Score the trend and derive the stop and target it would imply.

    ``stop_atr`` sets the stop width independently of the bar size used to read
    the trend. They are different horizons: a 4h ATR is around a fifth of a daily
    ATR, so sizing a swing stop from the chart's own bars puts it inside the
    day's normal noise and guarantees being stopped out. Pass the daily ATR to
    size the stop on the horizon the trade is actually held over.
    """
    needed = max(slow for _, slow in speeds)
    frame = df.dropna(subset=["high", "low", "close"]).reset_index(drop=True)
    if len(frame) < needed + atr_period:
        logger.debug(
            "%s has %d bars, needs %d for a trend read",
            symbol,
            len(frame),
            needed + atr_period,
        )
        return None

    close = frame["close"].astype(float)
    atr = float(
        compute_atr(frame["high"], frame["low"], frame["close"], period=atr_period).iloc[-1]
    )
    price = float(close.iloc[-1])
    if atr <= 0 or price <= 0:
        return None

    scored: list[SpeedForecast] = []
    for fast, slow in speeds:
        raw = float(_ewma(close, fast).iloc[-1] - _ewma(close, slow).iloc[-1])
        # Volatility normalisation: the crossover in ATRs, not in price units.
        capped = max(-FORECAST_CAP, min(FORECAST_CAP, raw / atr))
        scored.append(SpeedForecast(fast=fast, slow=slow, raw=raw, forecast=capped))

    forecast = sum(s.forecast for s in scored) / len(scored)
    if forecast >= FORECAST_ENTRY_THRESHOLD:
        direction = "long"
    elif forecast <= -FORECAST_ENTRY_THRESHOLD:
        direction = "short"
    else:
        direction = "flat"

    stop = target = None
    stop_distance = (stop_atr if stop_atr and stop_atr > 0 else atr) * stop_atr_mult
    if direction == "long":
        stop, target = price - stop_distance, price + stop_distance * reward_ratio
    elif direction == "short":
        stop, target = price + stop_distance, price - stop_distance * reward_ratio

    return TrendRead(
        symbol=symbol,
        price=price,
        atr=atr,
        atr_pct=atr / price,
        forecast=forecast,
        direction=direction,
        speeds=scored,
        stop=stop,
        target=target,
        multiplier=float(multiplier),
        encodable=stop_fits(multiplier, stop_distance / price, safety=stop_safety),
        bars=len(frame),
        stop_atr=stop_distance / max(stop_atr_mult, 1e-9),
    )


def render_chart(
    df: pd.DataFrame,
    read: TrendRead,
    out_path: str | Path,
    *,
    bars: int = 120,
    title_suffix: str = "",
) -> Optional[Path]:
    """Draw candles with the trend averages and the levels the read implies."""
    try:
        import matplotlib

        matplotlib.use("Agg")  # No display on a VPS.
        import matplotlib.pyplot as plt
        import mplfinance as mpf
    except ImportError:
        logger.warning("matplotlib/mplfinance not installed — skipping chart")
        return None

    frame = df.dropna(subset=["open", "high", "low", "close"]).copy()
    if "epoch" in frame.columns:
        frame["Date"] = pd.to_datetime(frame["epoch"], unit="s", utc=True)
        frame = frame.set_index("Date")
    frame = frame.rename(
        columns={"open": "Open", "high": "High", "low": "Low", "close": "Close"}
    )
    plot_frame = frame.tail(bars)
    if plot_frame.empty:
        return None

    fast, slow = read.speeds[0].fast, read.speeds[-1].slow
    fast_line = _ewma(frame["Close"].astype(float), fast).tail(bars)
    slow_line = _ewma(frame["Close"].astype(float), slow).tail(bars)
    overlays = [
        mpf.make_addplot(fast_line, color="#1f77b4", width=1.1),
        mpf.make_addplot(slow_line, color="#ff7f0e", width=1.1),
    ]

    pip = pip_size(read.symbol)
    decimals = 3 if pip >= 0.01 else 5
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Keep the stop and target inside the frame, or the levels the chart exists
    # to show end up cropped off it.
    levels = [v for v in (read.stop, read.target) if v is not None]
    low = min([plot_frame["Low"].min(), *levels])
    high = max([plot_frame["High"].max(), *levels])
    pad = (high - low) * 0.06 or high * 0.001

    try:
        fig, axes = mpf.plot(
            plot_frame[["Open", "High", "Low", "Close"]],
            type="candle",
            style="charles",
            addplot=overlays,
            ylabel="",
            figsize=(12, 6.5),
            ylim=(low - pad, high + pad),
            returnfig=True,
        )
        ax = axes[0]
        risk = f"{abs(read.price - read.stop) / pip:.0f} pips" if read.stop else "n/a"
        ax.set_title(
            f"{read.symbol}   {read.direction.upper()}   forecast {read.forecast:+.2f}"
            f" ({read.strength})   risk {risk}{title_suffix}",
            pad=14,
            fontsize=12,
        )
        for value, color, label in (
            (read.stop, "#d62728", "stop"),
            (read.target, "#2ca02c", "target"),
        ):
            if value is None:
                continue
            ax.axhline(value, color=color, linestyle="--", linewidth=1.0)
            ax.annotate(
                f"{label} {value:.{decimals}f}",
                xy=(1.0, value),
                xycoords=ax.get_yaxis_transform(),
                xytext=(-4, 3),
                textcoords="offset points",
                ha="right",
                fontsize=8,
                color=color,
            )
        ax.legend(
            handles=[
                plt.Line2D([], [], color="#1f77b4", label=f"EWMA {fast}"),
                plt.Line2D([], [], color="#ff7f0e", label=f"EWMA {slow}"),
            ],
            loc="lower left",
            fontsize=8,
            framealpha=0.8,
        )
        # mplfinance puts the price scale on the right; leave room for it.
        fig.subplots_adjust(left=0.04, right=0.9, top=0.9, bottom=0.16)
        fig.savefig(out_path, dpi=110)
        plt.close(fig)
    except Exception:
        logger.exception("Chart render failed for %s", read.symbol)
        return None
    return out_path


def brief_text(reads: Sequence[TrendRead], *, header: str = "") -> str:
    """A short readable brief: what each instrument is doing and what it implies."""
    if not reads:
        return "No instrument had enough history for a trend read."
    lines = [header] if header else []
    actionable = [r for r in reads if r.direction != "flat" and r.encodable]
    standing_aside = [r for r in reads if r.direction == "flat"]
    blocked = [r for r in reads if r.direction != "flat" and not r.encodable]

    for read in sorted(reads, key=lambda r: -abs(r.forecast)):
        lines.append(f"  {read.summary()}")

    lines.append("")
    lines.append(
        f"{len(actionable)} tradable, {len(standing_aside)} no trend, "
        f"{len(blocked)} blocked by contract room"
    )
    if actionable:
        room = contract_room_pct(actionable[0].multiplier) * 100
        lines.append(
            f"Contract room at x{actionable[0].multiplier:g} is {room:.2f}% of price."
        )
    lines.append(
        "A forecast is a description of the trend, not evidence that trading it pays."
    )
    return "\n".join(lines)
