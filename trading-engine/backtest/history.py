"""Local candle history cache for replay runs."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).resolve().parent / "history_cache"
COLUMNS = ["epoch", "open", "high", "low", "close", "volume"]


def cache_path(symbol: str, granularity: int) -> Path:
    return CACHE_DIR / f"{symbol}_{granularity}s.csv"


def load_cached(symbol: str, granularity: int) -> Optional[pd.DataFrame]:
    path = cache_path(symbol, granularity)
    if not path.exists():
        return None
    df = pd.read_csv(path)
    return normalize(df)


def save_cached(symbol: str, granularity: int, df: pd.DataFrame) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = cache_path(symbol, granularity)
    normalize(df).to_csv(path, index=False)
    return path


def normalize(df: pd.DataFrame) -> pd.DataFrame:
    """Sort by epoch, drop duplicates, and keep the standard columns."""
    out = df.copy()
    missing = [c for c in COLUMNS if c not in out.columns]
    if missing:
        raise ValueError(f"history missing columns: {missing}")
    out = out[COLUMNS]
    out["epoch"] = out["epoch"].astype("int64")
    out = out.drop_duplicates(subset="epoch").sort_values("epoch")
    return out.reset_index(drop=True)


def gap_report(df: pd.DataFrame, granularity: int) -> dict:
    """Coverage and missing-bar summary, so a thin sample is never mistaken for a clean one."""
    epochs = df["epoch"].astype("int64")
    if len(epochs) < 2:
        return {"bars": int(len(epochs)), "gaps": 0, "coverage_pct": 0.0}
    span = int(epochs.iloc[-1] - epochs.iloc[0])
    expected = span // granularity + 1
    diffs = epochs.diff().dropna().astype("int64")
    gaps = int((diffs > granularity).sum())
    return {
        "bars": int(len(epochs)),
        "expected_bars": int(expected),
        "coverage_pct": round(100.0 * len(epochs) / max(expected, 1), 2),
        "gaps": gaps,
        "largest_gap_bars": int(diffs.max() // granularity) if gaps else 1,
        "first_epoch": int(epochs.iloc[0]),
        "last_epoch": int(epochs.iloc[-1]),
        "days": round(span / 86400, 2),
    }


async def fetch_history(
    client,
    symbol: str,
    granularity: int,
    days: float,
) -> pd.DataFrame:
    """Page Deriv history for roughly ``days`` of candles and cache the result."""
    total = int(days * 86400 / granularity)
    candles = await client.get_candles_paged(symbol, granularity, total=total)
    if not candles:
        raise RuntimeError(f"No history returned for {symbol}")
    df = normalize(pd.DataFrame(candles))
    save_cached(symbol, granularity, df)
    logger.info("Cached %s bars for %s: %s", len(df), symbol, gap_report(df, granularity))
    return df
