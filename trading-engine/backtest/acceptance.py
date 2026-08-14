"""Promotion criteria for a replayed configuration.

A configuration earns demo time only by clearing these bars. Nothing here
promises a win in any window; the test is expectancy above zero on a sample
large enough to mean something, with a losing streak the daily limit survives.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from backtest.replay import ReplayStats
from config import settings

MIN_TRADES = 200
MIN_EXPECTANCY = 0.0
# A drifting live result is the signal to stop, not to re-tune the replay.
MAX_EXPECTANCY_DRIFT_PCT = 50.0


@dataclass
class AcceptanceResult:
    strategy_id: str
    passed: bool
    checks: dict[str, bool] = field(default_factory=dict)
    detail: dict[str, object] = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "strategy_id": self.strategy_id,
            "passed": self.passed,
            "checks": self.checks,
            "detail": self.detail,
            "failures": self.failures,
        }


def worst_streak_loss(stats: ReplayStats, stake: float) -> float:
    """Dollar cost of the worst losing run at full stake."""
    return stats.max_consecutive_losses * stake


def daily_drawdown_budget(balance: float) -> float:
    return balance * float(settings.DAILY_DRAWDOWN_LIMIT_PERCENT) / 100.0


def evaluate_acceptance(
    strategy_id: str,
    stats: ReplayStats,
    *,
    stake: Optional[float] = None,
    balance: float = 10_000.0,
    min_trades: int = MIN_TRADES,
) -> AcceptanceResult:
    """Check one strategy's replay result against the promotion criteria."""
    stake = float(stake if stake is not None else settings.DEMO_FIXED_STAKE_USD)
    budget = daily_drawdown_budget(balance)
    streak_cost = worst_streak_loss(stats, stake)
    trades_per_day = int(settings.MAX_TRADES_PER_DAY or 0)
    # Only the trades a single day can hold are charged against the daily limit.
    day_streak = min(stats.max_consecutive_losses, trades_per_day or stats.max_consecutive_losses)
    day_cost = day_streak * stake

    checks = {
        "sample_size": stats.n >= min_trades,
        "expectancy_positive": stats.expectancy > MIN_EXPECTANCY,
        "expectancy_significant": stats.significant,
        "streak_inside_daily_limit": day_cost <= budget,
        "stops_encodable": stats.encodable_rate >= 0.999,
    }
    failures = []
    if not checks["sample_size"]:
        failures.append(f"only {stats.n} resolved trades, need {min_trades}")
    if not checks["expectancy_positive"]:
        failures.append(f"expectancy {stats.expectancy:.2f} is not above zero")
    if not checks["expectancy_significant"]:
        failures.append(
            f"expectancy {stats.expectancy:.2f} is only {stats.t_stat:.2f} standard "
            f"errors from zero (95% CI {stats.ci95_low:.2f} to {stats.ci95_high:.2f}), "
            "so it is indistinguishable from luck"
        )
    if not checks["streak_inside_daily_limit"]:
        failures.append(
            f"{day_streak} losses in a day costs ${day_cost:.0f} against a "
            f"${budget:.0f} daily limit"
        )
    if not checks["stops_encodable"]:
        failures.append(
            f"only {stats.encodable_rate * 100:.1f}% of stops fit the contract room"
        )

    return AcceptanceResult(
        strategy_id=strategy_id,
        passed=all(checks.values()),
        checks=checks,
        detail={
            "trades": stats.n,
            "unresolved": stats.unresolved,
            "win_rate_pct": round(stats.win_rate * 100, 2),
            "expectancy": round(stats.expectancy, 2),
            "t_stat": round(stats.t_stat, 2),
            "ci95": [round(stats.ci95_low, 2), round(stats.ci95_high, 2)],
            "max_consecutive_losses": stats.max_consecutive_losses,
            "worst_streak_cost": round(streak_cost, 2),
            "daily_budget": round(budget, 2),
            "stake": stake,
        },
        failures=failures,
    )


@dataclass
class DriftResult:
    replay_expectancy: float
    live_expectancy: float
    live_trades: int
    drift_pct: float
    diverged: bool
    detail: str = ""

    def to_dict(self) -> dict:
        return {
            "replay_expectancy": round(self.replay_expectancy, 2),
            "live_expectancy": round(self.live_expectancy, 2),
            "live_trades": self.live_trades,
            "drift_pct": round(self.drift_pct, 1),
            "diverged": self.diverged,
            "detail": self.detail,
        }


def expectancy_drift(
    replay_expectancy: float,
    live_pnls: list[float],
    *,
    min_live_trades: int = 20,
    max_drift_pct: float = MAX_EXPECTANCY_DRIFT_PCT,
) -> DriftResult:
    """Compare live expectancy against what replay promised.

    Divergence means the model of the market or the contract is wrong, so the run
    should stop rather than the replay be re-fitted to match.
    """
    n = len(live_pnls)
    live = sum(live_pnls) / n if n else 0.0
    if n < min_live_trades:
        return DriftResult(
            replay_expectancy=replay_expectancy,
            live_expectancy=live,
            live_trades=n,
            drift_pct=0.0,
            diverged=False,
            detail=f"only {n} live trades; need {min_live_trades} to judge drift",
        )

    scale = abs(replay_expectancy)
    if scale < 1e-9:
        drift = 0.0 if abs(live) < 1e-9 else 100.0
    else:
        drift = abs(live - replay_expectancy) / scale * 100.0

    diverged = drift > max_drift_pct or (replay_expectancy > 0 and live <= 0)
    return DriftResult(
        replay_expectancy=replay_expectancy,
        live_expectancy=live,
        live_trades=n,
        drift_pct=drift,
        diverged=diverged,
        detail=(
            "live expectancy diverged from replay — stop and re-measure"
            if diverged
            else "live expectancy tracks replay"
        ),
    )
