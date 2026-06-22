"""Pre-open scenario simulation on recent price action."""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from config import settings
from risk.gate import PIP_SIZE
from signals.engine import SignalDirection, TradeSignal


@dataclass
class OpenScenarioResult:
    passed: bool
    reason: str
    win_rate: float = 0.0
    simulated_trades: int = 0
    expected_value: float = 0.0
    details: dict = field(default_factory=dict)


def _pip_size(symbol: str) -> float:
    return PIP_SIZE.get(symbol, 0.0001)


def simulate_sl_tp_window(
    df: pd.DataFrame,
    signal: TradeSignal,
    sl_pips: int | None = None,
    tp_pips: int | None = None,
) -> OpenScenarioResult:
    """Replay hypothetical entries on recent bars with current SL/TP."""
    sl_pips = sl_pips or settings.DEFAULT_SL_PIPS
    tp_pips = tp_pips or settings.DEFAULT_TP_PIPS
    window = min(settings.ANALYSIS_SCENARIO_WINDOW_BARS, len(df))
    if window < 10:
        return OpenScenarioResult(False, "insufficient_bars_for_scenario", details={"bars": window})

    pip = _pip_size(signal.symbol)
    sl_dist = sl_pips * pip
    tp_dist = tp_pips * pip
    slice_df = df.tail(window)
    wins = 0
    losses = 0
    total_pnl = 0.0
    trades = 0

    for i in range(len(slice_df) - 5):
        entry = float(slice_df.iloc[i]["close"])
        direction = signal.direction
        for j in range(i + 1, len(slice_df)):
            price = float(slice_df.iloc[j]["close"])
            if direction == SignalDirection.BUY:
                sl_hit = price <= entry - sl_dist
                tp_hit = price >= entry + tp_dist
            else:
                sl_hit = price >= entry + sl_dist
                tp_hit = price <= entry - tp_dist
            if sl_hit or tp_hit:
                pnl = tp_pips if tp_hit else -sl_pips
                total_pnl += pnl
                trades += 1
                if tp_hit:
                    wins += 1
                else:
                    losses += 1
                break

    if trades == 0:
        return OpenScenarioResult(
            False,
            "scenario_no_simulated_outcomes",
            details={"window": window},
        )

    win_rate = wins / trades
    expected_value = total_pnl / trades
    passed = win_rate >= settings.ANALYSIS_MIN_SCENARIO_WIN_RATE and expected_value > 0

    return OpenScenarioResult(
        passed=passed,
        reason="scenario_pass" if passed else "scenario_negative_ev_or_low_win_rate",
        win_rate=round(win_rate, 4),
        simulated_trades=trades,
        expected_value=round(expected_value, 4),
        details={"wins": wins, "losses": losses, "window": window},
    )
