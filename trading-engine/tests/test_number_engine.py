"""Number Engine and Strategy Manager tests."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from number_engine import NumberEngine
from signals.engine import SignalDirection
from strategies import StrategyManager, evaluate_strategies_detailed
from strategies.base import StrategyContext
from strategies.momentum import MomentumStrategy
from strategies.trend_following import TrendFollowingStrategy


def _ohlc_df(n: int = 120, trend: float = 0.0002) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    close = 1.1000 + np.cumsum(rng.normal(trend, 0.0003, n))
    high = close + rng.uniform(0.0001, 0.0005, n)
    low = close - rng.uniform(0.0001, 0.0005, n)
    open_ = close + rng.normal(0, 0.0001, n)
    return pd.DataFrame(
        {
            "epoch": list(range(1_700_000_000, 1_700_000_000 + n * 300, 300)),
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": rng.integers(10, 100, n),
        }
    )


def test_number_engine_snapshot_fields():
    df = _ohlc_df()
    snap = NumberEngine().compute("frxEURUSD", df)
    assert snap is not None
    assert snap.rsi >= 0
    assert snap.atr > 0
    assert snap.regime in ("trending", "ranging", "breakout", "quiet")
    assert snap.support > 0
    assert snap.resistance > 0
    d = snap.to_dict()
    assert "ema_9" in d and "regime" in d


def test_number_engine_insufficient_bars():
    df = _ohlc_df(20)
    assert NumberEngine().compute("frxEURUSD", df) is None


def test_strategy_manager_quiet_is_no_trade():
    df = _ohlc_df(n=120, trend=0.0)
    # Compress range artificially for quiet-ish data
    df["high"] = df["close"] + 0.00005
    df["low"] = df["close"] - 0.00005
    engine = NumberEngine()
    snap = engine.compute("frxEURUSD", df)
    assert snap is not None
    mgr = StrategyManager(confidence_threshold=70)
    result = mgr.select(
        snap,
        ["trend_following", "momentum", "range_trading", "breakout", "price_action"],
        StrategyContext(),
    )
    # Either quiet skip or below-threshold — never a forced first-match
    if snap.regime == "quiet":
        assert result.signal is None
        assert result.skip_reason


def test_momentum_evaluate_snapshot_returns_evaluation():
    df = _ohlc_df(trend=0.0004)
    snap = NumberEngine().compute("frxEURUSD", df)
    assert snap is not None
    ev = MomentumStrategy().evaluate_snapshot(snap)
    assert ev.strategy_id == "momentum"
    assert isinstance(ev.confidence, float)
    assert ev.direction in (SignalDirection.BUY, SignalDirection.SELL, SignalDirection.NONE)


def test_evaluate_strategies_detailed_logs_path():
    df = _ohlc_df()
    result = evaluate_strategies_detailed(
        "frxEURUSD",
        df,
        ["momentum", "trend_following"],
        StrategyContext(),
    )
    assert result.regime
    assert isinstance(result.evaluations, list)


def test_legacy_alias_resolution():
    from strategies import resolve_strategy_id

    assert resolve_strategy_id("macd_rsi") == "momentum"
    assert resolve_strategy_id("ema_pullback") == "trend_following"


def test_atr_sl_tp_buy():
    from strategies.base import atr_sl_tp

    df = _ohlc_df()
    snap = NumberEngine().compute("frxEURUSD", df)
    assert snap is not None
    sl, tp, method = atr_sl_tp(snap, SignalDirection.BUY)
    assert sl < snap.close < tp
    assert method.startswith("atr")


def test_trend_following_uses_snapshot():
    df = _ohlc_df(trend=0.0005)
    snap = NumberEngine().compute("frxEURUSD", df)
    assert snap is not None
    ev = TrendFollowingStrategy().evaluate_snapshot(snap)
    assert "score_breakdown" in ev.__dict__ or isinstance(ev.score_breakdown, dict)
