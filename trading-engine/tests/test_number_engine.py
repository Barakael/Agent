"""Number Engine and Strategy Manager tests."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from number_engine import NumberEngine
from config import settings
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


def _make_snap(**overrides):
    from number_engine.snapshot import MarketSnapshot

    base = dict(
        symbol="R_50",
        epoch=1_700_000_000,
        open=100.0,
        high=100.5,
        low=99.5,
        close=100.2,
        volume=10.0,
        ema_9=100.1,
        ema_21=100.0,
        ema_50=99.8,
        sma_20=100.0,
        rsi=55.0,
        atr=0.5,
        atr_sma=0.5,
        macd=0.01,
        macd_signal=0.0,
        macd_hist=0.01,
        macd_hist_prev=0.0,
        macd_bull_cross=False,
        macd_bear_cross=False,
        bb_upper=101.0,
        bb_mid=100.0,
        bb_lower=99.0,
        bb_width=0.02,
        bb_mid_slope=0.001,
        support=99.0,
        resistance=101.0,
        swing_low=99.0,
        swing_high=101.0,
        structure_trend="up",
        higher_highs=True,
        higher_lows=True,
        lower_highs=False,
        lower_lows=False,
        ema_aligned_up=True,
        ema_aligned_down=False,
        trend_direction="up",
        regime="trending",
        regime_reasons=["test"],
    )
    base.update(overrides)
    return MarketSnapshot(**base)


def test_trend_following_rejects_soft_structure():
    snap = _make_snap(
        higher_highs=False,
        higher_lows=False,
        lower_highs=False,
        lower_lows=False,
        trend_direction="up",
    )
    ev = TrendFollowingStrategy().evaluate_snapshot(snap)
    assert not ev.is_trade
    assert any("hard" in r.lower() or "HH/HL" in r or "structure" in r.lower() for r in ev.reasons)


def test_trend_following_rejects_no_pullback():
    # Close well above EMA21 without wick touching it
    snap = _make_snap(low=100.5, close=100.8, ema_21=100.0)
    ev = TrendFollowingStrategy().evaluate_snapshot(snap)
    assert not ev.is_trade
    assert any("pullback" in r.lower() for r in ev.reasons)


def test_trend_following_accepts_hard_pullback():
    snap = _make_snap(low=99.9, close=100.2, ema_21=100.0, rsi=55.0)
    ev = TrendFollowingStrategy().evaluate_snapshot(snap)
    assert ev.is_trade
    assert ev.direction == SignalDirection.BUY
    assert ev.confidence >= 70


def test_strategy_allowlist_only_trend(monkeypatch):
    monkeypatch.setattr(settings, "STRATEGY_ALLOWLIST", "trend_following")
    # Clear cached property path by ensuring allowlist reads STRATEGY_ALLOWLIST
    from strategies import apply_strategy_allowlist, allowlist_strategy_ids

    assert allowlist_strategy_ids() == ["trend_following"]
    filtered = apply_strategy_allowlist(
        ["trend_following", "momentum", "price_action", "range_trading"]
    )
    assert filtered == ["trend_following"]

    snap = _make_snap()
    mgr = StrategyManager(confidence_threshold=50)
    result = mgr.select(
        snap,
        ["trend_following", "momentum", "price_action"],
        StrategyContext(),
    )
    ids = [e.strategy_id for e in result.evaluations]
    assert ids == ["trend_following"] or (result.signal and result.signal.strategy_id == "trend_following")
    assert all(e.strategy_id == "trend_following" for e in result.evaluations)


def test_strategy_allowlist_evaluates_outside_regime(monkeypatch):
    """Focused allowlist still evaluates trend_following in ranging; quality filters decide."""
    monkeypatch.setattr(settings, "STRATEGY_ALLOWLIST", "trend_following")
    snap = _make_snap(regime="ranging")
    mgr = StrategyManager(confidence_threshold=50)
    result = mgr.select(snap, ["trend_following", "range_trading"], StrategyContext())
    assert all(e.strategy_id == "trend_following" for e in result.evaluations)
    assert result.signal is not None  # hard HH/HL + pullback fixture still qualifies


def test_trend_following_accepts_near_ema_pullback():
    snap = _make_snap(
        low=100.3,
        close=100.35,
        ema_21=100.0,
        atr=0.8,
        atr_sma=0.8,
        rsi=55.0,
    )
    # close within 0.5*ATR of EMA21 from above, no wick touch
    ev = TrendFollowingStrategy().evaluate_snapshot(snap)
    assert ev.is_trade
    assert any("Near EMA21" in r for r in ev.reasons)


def test_higher_timeframe_aligned_buy():
    from analysis.multi_timeframe import higher_timeframe_aligned

    # Strong uptrend → HTF MACD typically >= 0 for buy
    df = _ohlc_df(n=150, trend=0.001)
    ok, reason = higher_timeframe_aligned(df, "buy")
    assert isinstance(ok, bool)
    assert reason
    # Soft: with strong uptrend expect aligned or insufficient skipped as True
    if "insufficient" not in reason:
        assert ok is True


def test_higher_timeframe_skips_when_short():
    from analysis.multi_timeframe import higher_timeframe_aligned

    df = _ohlc_df(n=40)
    ok, reason = higher_timeframe_aligned(df, "buy")
    assert ok is True
    assert "insufficient" in reason or "unavailable" in reason or "aligned" in reason

