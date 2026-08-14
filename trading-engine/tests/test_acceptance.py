"""Tests for promotion criteria and live-versus-replay drift."""

from __future__ import annotations

from backtest.acceptance import (
    MIN_TRADES,
    evaluate_acceptance,
    expectancy_drift,
)
from backtest.replay import ReplayStats


def _stats(
    n: int = 250,
    expectancy: float = 5.0,
    streak: int = 3,
    encodable: float = 1.0,
) -> ReplayStats:
    stats = ReplayStats(n=n)
    stats.expectancy = expectancy
    stats.win_rate = 0.4
    stats.total_pnl = expectancy * n
    stats.max_consecutive_losses = streak
    stats.encodable_rate = encodable
    # A tight error bar so the significance check passes unless a test targets it.
    stats.stdev = abs(expectancy) * 2 or 1.0
    stats.std_error = stats.stdev / (n**0.5)
    stats.t_stat = expectancy / stats.std_error if stats.std_error else 0.0
    stats.ci95_low = expectancy - 1.96 * stats.std_error
    stats.ci95_high = expectancy + 1.96 * stats.std_error
    return stats


def test_a_healthy_result_is_promotable():
    result = evaluate_acceptance("trend_following", _stats(), stake=100, balance=10_000)
    assert result.passed is True
    assert result.failures == []


def test_small_sample_is_not_promotable():
    result = evaluate_acceptance("trend_following", _stats(n=50))
    assert result.passed is False
    assert result.checks["sample_size"] is False
    assert str(MIN_TRADES) in result.failures[0]


def test_zero_or_negative_expectancy_is_not_promotable():
    for expectancy in (0.0, -0.01, -12.0):
        result = evaluate_acceptance("x", _stats(expectancy=expectancy))
        assert result.passed is False
        assert result.checks["expectancy_positive"] is False


def test_losing_streak_must_fit_the_daily_drawdown_limit():
    # 4% of $10,000 is $400, so four $100 losses in one day is the ceiling.
    ok = evaluate_acceptance("x", _stats(streak=4), stake=100, balance=10_000)
    assert ok.checks["streak_inside_daily_limit"] is True

    too_big = evaluate_acceptance("x", _stats(streak=9), stake=200, balance=10_000)
    assert too_big.checks["streak_inside_daily_limit"] is False
    assert too_big.passed is False


def test_expectancy_inside_the_noise_is_not_promotable():
    """A positive mean that is one standard error from zero must not promote."""
    stats = ReplayStats(n=400)
    stats.expectancy = 4.96
    stats.stdev = 100.0
    stats.std_error = 5.0
    stats.t_stat = 4.96 / 5.0
    stats.ci95_low = 4.96 - 1.96 * 5.0
    stats.ci95_high = 4.96 + 1.96 * 5.0
    stats.encodable_rate = 1.0
    stats.max_consecutive_losses = 7

    result = evaluate_acceptance("trend_following", stats, stake=100, balance=10_000)

    assert result.checks["expectancy_positive"] is True
    assert result.checks["expectancy_significant"] is False
    assert result.passed is False
    assert "indistinguishable from luck" in " ".join(result.failures)


def test_unencodable_stops_block_promotion():
    result = evaluate_acceptance("x", _stats(encodable=0.62))
    assert result.checks["stops_encodable"] is False
    assert "62.0%" in " ".join(result.failures)


def test_drift_needs_a_live_sample_before_judging():
    result = expectancy_drift(10.0, [5.0] * 5)
    assert result.diverged is False
    assert "need 20" in result.detail


def test_live_expectancy_tracking_replay_is_not_divergence():
    result = expectancy_drift(10.0, [9.0] * 30)
    assert result.diverged is False
    assert result.drift_pct < 50


def test_large_gap_between_live_and_replay_is_divergence():
    result = expectancy_drift(10.0, [1.0] * 30)
    assert result.diverged is True
    assert result.drift_pct == 90.0


def test_positive_replay_but_losing_live_is_divergence():
    result = expectancy_drift(8.0, [-2.0] * 25)
    assert result.diverged is True
    assert result.live_expectancy == -2.0
