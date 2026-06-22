"""Multi-timeframe trend confirmation (Phase 4)."""

from __future__ import annotations

import pandas as pd

from indicators.macd import compute_macd


def resample_ohlc(df: pd.DataFrame, factor: int) -> pd.DataFrame:
    """Aggregate 5m bars into higher timeframe (factor * 5m)."""
    if df.empty or factor < 2:
        return df.copy()
    chunk = factor
    rows = []
    for i in range(0, len(df) - chunk + 1, chunk):
        block = df.iloc[i : i + chunk]
        rows.append(
            {
                "open": float(block.iloc[0]["open"]),
                "high": float(block["high"].max()),
                "low": float(block["low"].min()),
                "close": float(block.iloc[-1]["close"]),
            }
        )
    return pd.DataFrame(rows)


def higher_timeframe_aligned(df: pd.DataFrame, direction: str, factor: int = 3) -> tuple[bool, str]:
    """Check 15m-equivalent MACD trend aligns with signal direction."""
    htf = resample_ohlc(df, factor)
    if len(htf) < 30:
        return True, "htf_insufficient_data_skipped"
    macd_df = compute_macd(htf["close"])
    if macd_df.empty:
        return True, "htf_macd_unavailable"
    last = macd_df.iloc[-1]
    macd_val = float(last["macd"])
    if direction == "buy":
        aligned = macd_val >= 0
    else:
        aligned = macd_val <= 0
    return aligned, f"htf_macd={macd_val:.6f}_aligned={aligned}"
