"""Tests for the multiplier-aware replay harness."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backtest.replay import (
    ContractSpec,
    ExitPolicy,
    ReplayConfig,
    ReplayTrade,
    build_barriers,
    exit_policies,
    find_pattern_entries,
    group_stats,
    replay_pattern_strategy,
    resolve_entries,
    resolve_exit,
    snapshot_pattern,
    summarize,
)
from number_engine.snapshot import MarketSnapshot
from signals.engine import SignalDirection

BAR = 300


def _frame(highs, lows, closes, opens=None, start: int = 1_700_000_000) -> pd.DataFrame:
    n = len(closes)
    opens = closes if opens is None else opens
    return pd.DataFrame(
        {
            "epoch": [start + i * BAR for i in range(n)],
            "open": np.array(opens, dtype=float),
            "high": np.array(highs, dtype=float),
            "low": np.array(lows, dtype=float),
            "close": np.array(closes, dtype=float),
            "volume": np.zeros(n),
        }
    )


def test_time_exit_measures_wall_clock_across_a_session_gap():
    """An instrument that closes overnight must not age a position by bar count."""
    spec = ContractSpec(stake=100.0, multiplier=30.0, cost_pct_of_notional=0.0, exposure_factor=1.0)
    barriers = build_barriers(
        symbol="frxUSDJPY",
        entry=100.0,
        direction=SignalDirection.BUY,
        chart_sl=99.0,
        chart_tp=102.0,
        spec=spec,
        mode="chart_matched",
    )
    # Three 5m bars, then a weekend-sized gap before the fourth.
    epochs = [0, 300, 600, 900, 900 + 3 * 86400]
    df = pd.DataFrame(
        {
            "epoch": epochs,
            "open": [100.0] * 5,
            "high": [100.1] * 5,
            "low": [99.9] * 5,
            "close": [100.0] * 5,
        }
    )
    policy = ExitPolicy(name="time_4h", max_hours=4.0)
    _, _, resolution, bars_held, _, _ = resolve_exit(
        df,
        0,
        entry=100.0,
        direction=SignalDirection.BUY,
        barriers=barriers,
        spec=spec,
        policy=policy,
        bar_minutes=5,
    )
    # By bar count nothing is 4h old; by the clock the post-gap bar is days old.
    assert resolution == "time"
    assert bars_held == 4


def test_cost_is_charged_on_notional_and_reduces_pnl():
    free = ContractSpec(
        stake=100.0, multiplier=30.0, cost_pct_of_notional=0.0, exposure_factor=1.0
    )
    real = ContractSpec(
        stake=100.0, multiplier=30.0, cost_pct_of_notional=0.0002, exposure_factor=1.0
    )
    # 0.02% of $3,000 notional is $0.60, charged win or lose.
    assert real.cost_usd == 0.6
    assert real.pnl_usd(100.0, 102.0, SignalDirection.BUY) == 59.4
    assert free.pnl_usd(100.0, 102.0, SignalDirection.BUY) == 60.0
    # A bigger multiplier means bigger notional and a bigger fee.
    big = ContractSpec(stake=100.0, multiplier=80.0, cost_pct_of_notional=0.0002)
    assert big.cost_usd == 1.6


def test_default_cost_matches_what_the_venue_actually_charges():
    """Charging only the quoted commission understates real cost fourfold.

    Deriv's proposals price a x100 forex contract as ~97% exposure plus ~0.088%
    of notional in total cost; the 0.02% commission field is a fraction of it.
    """
    spec = ContractSpec()
    assert spec.cost_pct_of_notional == pytest.approx(0.00088, abs=1e-5)
    assert spec.exposure_factor == pytest.approx(0.97)


def test_a_loss_can_never_exceed_the_stake():
    """Cost comes out of the stake, so stop-out is the floor, not stake plus fees."""
    spec = ContractSpec(stake=100.0, multiplier=100.0)
    assert spec.pnl_usd(100.0, 50.0, SignalDirection.BUY) == -100.0


def test_stake_out_arrives_sooner_than_one_over_the_multiplier():
    """Deriv quoted stop-out at 0.94% on a x100 contract, not 1.00%."""
    spec = ContractSpec(stake=1.0, multiplier=100.0)
    assert spec.stake_out_pct == pytest.approx(0.0094, abs=0.0002)
    assert spec.stake_out_pct < 1 / 100


def test_expectancy_carries_an_error_bar():
    trades = [
        ReplayTrade(
            symbol="R_50",
            strategy_id="s",
            direction="buy",
            pattern="pin",
            regime="trending",
            entry_epoch=0,
            entry_price=100.0,
            exit_price=101.0,
            pnl_usd=pnl,
            resolution="target",
            bars_held=1,
            hours_held=0.1,
            mfe_r=1.0,
            mae_r=-0.1,
            sl_pct=0.02,
            tp_pct=0.03,
            encodable=True,
        )
        for pnl in ([60.0] * 50 + [-60.0] * 50)
    ]
    stats = summarize(trades)
    assert stats.expectancy == 0.0
    assert stats.std_error > 0
    assert stats.significant is False
    low, high = stats.to_dict()["ci95"]
    assert low < 0 < high


def test_a_small_positive_mean_inside_one_standard_error_is_not_significant():
    noisy = [100.0] * 50 + [-95.0] * 50
    trades = [
        ReplayTrade(
            symbol="R_50",
            strategy_id="s",
            direction="buy",
            pattern="pin",
            regime="trending",
            entry_epoch=0,
            entry_price=100.0,
            exit_price=101.0,
            pnl_usd=pnl,
            resolution="stop",
            bars_held=1,
            hours_held=0.1,
            mfe_r=1.0,
            mae_r=-0.1,
            sl_pct=0.02,
            tp_pct=0.03,
            encodable=True,
        )
        for pnl in noisy
    ]
    stats = summarize(trades)
    assert stats.expectancy > 0
    assert stats.t_stat < 2.0
    assert stats.significant is False


def test_trailing_policies_declare_the_capability_they_need():
    by_name = {p.name: p for p in exit_policies()}
    assert by_name["trail_after_1r"].requires == "contract_update"
    assert by_name["target_2r"].requires == ""


def test_stake_out_pct_is_inverse_multiplier_when_frictionless():
    for multiplier in (30, 80):
        spec = ContractSpec(
            multiplier=multiplier, cost_pct_of_notional=0.0, exposure_factor=1.0
        )
        assert spec.stake_out_pct == 1 / multiplier


def test_multiplier_pnl_scales_with_notional():
    spec = ContractSpec(stake=100.0, multiplier=30.0, cost_pct_of_notional=0.0, exposure_factor=1.0)
    # A 2% favourable move on 30x pays 60% of stake.
    assert spec.pnl_usd(100.0, 102.0, SignalDirection.BUY) == 60.0
    assert spec.pnl_usd(100.0, 98.0, SignalDirection.SELL) == 60.0
    # Loss can never exceed the stake.
    assert spec.pnl_usd(100.0, 50.0, SignalDirection.BUY) == -100.0


def test_as_deployed_barriers_reproduce_the_fixed_dollar_stop():
    spec = ContractSpec(stake=100.0, multiplier=80.0, cost_pct_of_notional=0.0, exposure_factor=1.0)
    barriers = build_barriers(
        symbol="R_50",
        entry=100.0,
        direction=SignalDirection.BUY,
        chart_sl=98.0,
        chart_tp=104.0,
        spec=spec,
        mode="as_deployed",
    )
    # $80 on a $100 stake at 80x is a 1% move, half the 2-point chart stop.
    assert barriers.usd_sl == 80.0
    assert round(barriers.sl_pct, 6) == 0.01
    assert round(barriers.sl_price, 4) == 99.0
    assert barriers.encodable is True


def test_chart_matched_barriers_keep_plan_distance_but_flag_unencodable():
    spec80 = ContractSpec(stake=100.0, multiplier=80.0, cost_pct_of_notional=0.0, exposure_factor=1.0)
    tight = build_barriers(
        symbol="R_50",
        entry=100.0,
        direction=SignalDirection.BUY,
        chart_sl=98.0,
        chart_tp=103.0,
        spec=spec80,
        mode="chart_matched",
    )
    assert round(tight.sl_pct, 6) == 0.02
    assert tight.sl_price == 98.0
    # 2% stop cannot live inside 1.25% of contract room.
    assert tight.encodable is False

    spec30 = ContractSpec(stake=100.0, multiplier=30.0, cost_pct_of_notional=0.0, exposure_factor=1.0)
    roomy = build_barriers(
        symbol="R_50",
        entry=100.0,
        direction=SignalDirection.BUY,
        chart_sl=98.0,
        chart_tp=103.0,
        spec=spec30,
        mode="chart_matched",
    )
    assert roomy.encodable is True
    assert roomy.usd_sl == 60.0
    assert roomy.usd_tp == 90.0


def test_bar_spanning_both_barriers_resolves_as_stop():
    spec = ContractSpec(stake=100.0, multiplier=30.0, cost_pct_of_notional=0.0, exposure_factor=1.0)
    barriers = build_barriers(
        symbol="R_50",
        entry=100.0,
        direction=SignalDirection.BUY,
        chart_sl=98.0,
        chart_tp=103.0,
        spec=spec,
        mode="chart_matched",
    )
    df = _frame(highs=[100, 104], lows=[100, 97], closes=[100, 100])
    _, pnl, resolution, _, _, _ = resolve_exit(
        df,
        0,
        entry=100.0,
        direction=SignalDirection.BUY,
        barriers=barriers,
        spec=spec,
        policy=ExitPolicy(),
        bar_minutes=5,
    )
    assert resolution == "stop"
    assert pnl == -60.0


def test_liquidation_fires_before_a_wider_chart_stop():
    spec = ContractSpec(stake=100.0, multiplier=80.0, cost_pct_of_notional=0.0, exposure_factor=1.0)
    barriers = build_barriers(
        symbol="R_50",
        entry=100.0,
        direction=SignalDirection.BUY,
        chart_sl=98.0,
        chart_tp=103.0,
        spec=spec,
        mode="chart_matched",
    )
    # Drops 1.5%: past the 1.25% liquidation, short of the 2% chart stop.
    df = _frame(highs=[100, 100.1], lows=[100, 98.5], closes=[100, 98.6])
    _, pnl, resolution, _, _, _ = resolve_exit(
        df,
        0,
        entry=100.0,
        direction=SignalDirection.BUY,
        barriers=barriers,
        spec=spec,
        policy=ExitPolicy(),
        bar_minutes=5,
    )
    assert resolution == "stake_out"
    assert pnl == -100.0


def test_target_resolution_pays_the_planned_reward():
    spec = ContractSpec(stake=100.0, multiplier=30.0, cost_pct_of_notional=0.0, exposure_factor=1.0)
    barriers = build_barriers(
        symbol="R_50",
        entry=100.0,
        direction=SignalDirection.BUY,
        chart_sl=98.0,
        chart_tp=103.0,
        spec=spec,
        mode="chart_matched",
    )
    df = _frame(highs=[100, 103.5], lows=[100, 99.9], closes=[100, 103.2])
    exit_price, pnl, resolution, _, mfe_r, _ = resolve_exit(
        df,
        0,
        entry=100.0,
        direction=SignalDirection.BUY,
        barriers=barriers,
        spec=spec,
        policy=ExitPolicy(),
        bar_minutes=5,
    )
    assert resolution == "target"
    assert exit_price == 103.0
    assert pnl == 90.0
    assert mfe_r >= 1.5


def test_time_exit_closes_at_the_bar_close():
    spec = ContractSpec(stake=100.0, multiplier=30.0, cost_pct_of_notional=0.0, exposure_factor=1.0)
    barriers = build_barriers(
        symbol="R_50",
        entry=100.0,
        direction=SignalDirection.BUY,
        chart_sl=98.0,
        chart_tp=106.0,
        spec=spec,
        mode="chart_matched",
    )
    closes = [100.0] + [100.3] * 12
    df = _frame(highs=[c + 0.05 for c in closes], lows=[c - 0.05 for c in closes], closes=closes)
    exit_price, pnl, resolution, _, _, _ = resolve_exit(
        df,
        0,
        entry=100.0,
        direction=SignalDirection.BUY,
        barriers=barriers,
        spec=spec,
        policy=ExitPolicy(name="time_1h", max_hours=1.0),
        bar_minutes=5,
    )
    assert resolution == "time"
    assert exit_price == 100.3
    assert pnl > 0


def test_trailing_stop_locks_profit_after_one_r():
    spec = ContractSpec(stake=100.0, multiplier=30.0, cost_pct_of_notional=0.0, exposure_factor=1.0)
    barriers = build_barriers(
        symbol="R_50",
        entry=100.0,
        direction=SignalDirection.BUY,
        chart_sl=98.0,
        chart_tp=110.0,
        spec=spec,
        mode="chart_matched",
    )
    # Runs to +4%, then gives it all back toward entry.
    df = _frame(
        highs=[100, 104, 104, 100.5],
        lows=[100, 101, 101.5, 99.0],
        closes=[100, 103.5, 103.8, 99.2],
    )
    _, pnl, resolution, _, _, _ = resolve_exit(
        df,
        0,
        entry=100.0,
        direction=SignalDirection.BUY,
        barriers=barriers,
        spec=spec,
        policy=ExitPolicy(name="trail_1r", trail_after_r=1.0),
        bar_minutes=5,
    )
    assert resolution == "trail"
    assert pnl > 0


def test_a_bar_that_reaches_one_r_and_stops_out_is_not_a_trail_exit():
    """The trail only applies from the next bar, so this is still a plain stop."""
    spec = ContractSpec(stake=100.0, multiplier=30.0, cost_pct_of_notional=0.0, exposure_factor=1.0)
    barriers = build_barriers(
        symbol="R_50",
        entry=100.0,
        direction=SignalDirection.BUY,
        chart_sl=98.0,
        chart_tp=110.0,
        spec=spec,
        mode="chart_matched",
    )
    # One bar spans +2% and -2%.
    df = _frame(highs=[100, 102.5], lows=[100, 97.5], closes=[100, 98.0])
    _, pnl, resolution, _, _, _ = resolve_exit(
        df,
        0,
        entry=100.0,
        direction=SignalDirection.BUY,
        barriers=barriers,
        spec=spec,
        policy=ExitPolicy(name="trail_1r", trail_after_r=1.0),
        bar_minutes=5,
    )
    assert resolution == "stop"
    assert pnl == -60.0


def test_liquidation_label_survives_a_same_bar_one_r_excursion():
    spec = ContractSpec(stake=100.0, multiplier=80.0, cost_pct_of_notional=0.0, exposure_factor=1.0)
    barriers = build_barriers(
        symbol="R_50",
        entry=100.0,
        direction=SignalDirection.BUY,
        chart_sl=98.0,
        chart_tp=110.0,
        spec=spec,
        mode="chart_matched",
    )
    df = _frame(highs=[100, 102.5], lows=[100, 98.4], closes=[100, 98.5])
    _, pnl, resolution, _, _, _ = resolve_exit(
        df,
        0,
        entry=100.0,
        direction=SignalDirection.BUY,
        barriers=barriers,
        spec=spec,
        policy=ExitPolicy(name="trail_1r", trail_after_r=1.0),
        bar_minutes=5,
    )
    assert resolution == "stake_out"
    assert pnl == -100.0


def test_partial_exit_banks_half_at_one_r():
    spec = ContractSpec(stake=100.0, multiplier=30.0, cost_pct_of_notional=0.0, exposure_factor=1.0)
    barriers = build_barriers(
        symbol="R_50",
        entry=100.0,
        direction=SignalDirection.BUY,
        chart_sl=98.0,
        chart_tp=110.0,
        spec=spec,
        mode="chart_matched",
    )
    df = _frame(
        highs=[100, 102.5, 100.5],
        lows=[100, 100.2, 97.5],
        closes=[100, 102.2, 97.9],
    )
    _, pnl, resolution, _, _, _ = resolve_exit(
        df,
        0,
        entry=100.0,
        direction=SignalDirection.BUY,
        barriers=barriers,
        spec=spec,
        policy=ExitPolicy(name="partial_1r", partial_at_r=1.0, partial_fraction=0.5),
        bar_minutes=5,
    )
    assert resolution == "stop"
    # Half banked at +2% (+$30), half stopped at -2% (-$30).
    assert pnl == 0.0


def _snapshot(**overrides) -> MarketSnapshot:
    base = dict(
        symbol="R_50",
        epoch=1_700_000_000,
        open=100.0,
        high=101.0,
        low=99.0,
        close=100.0,
        volume=0.0,
        ema_9=100.0,
        ema_21=100.0,
        ema_50=100.0,
        sma_20=100.0,
        rsi=50.0,
        atr=1.0,
        atr_sma=1.0,
        macd=0.0,
        macd_signal=0.0,
        macd_hist=0.0,
        macd_hist_prev=0.0,
        macd_bull_cross=False,
        macd_bear_cross=False,
        bb_upper=102.0,
        bb_mid=100.0,
        bb_lower=98.0,
        bb_width=0.04,
        bb_mid_slope=0.0,
        support=98.0,
        resistance=102.0,
        swing_low=98.0,
        swing_high=102.0,
        structure_trend="up",
        higher_highs=True,
        higher_lows=True,
        lower_highs=False,
        lower_lows=False,
        ema_aligned_up=True,
        ema_aligned_down=False,
        trend_direction="up",
        regime="trending",
    )
    base.update(overrides)
    return MarketSnapshot(**base)


def test_snapshot_pattern_precedence_matches_price_action_scoring():
    assert snapshot_pattern(_snapshot(engulfing="bullish_engulfing")) == "engulfing"
    assert snapshot_pattern(_snapshot(pin_bar="bullish_pin")) == "pin"
    assert snapshot_pattern(_snapshot(break_of_structure_up=True)) == "break_of_structure"
    assert snapshot_pattern(_snapshot(inside_bar=True)) == "inside_bar"
    assert snapshot_pattern(_snapshot()) == "none"


def test_summarize_reports_expectancy_and_loss_streak():
    trades = replay_pattern_strategy(
        "R_50",
        _trending_frame(),
        "trend_following",
        ReplayConfig(spec=ContractSpec(stake=100.0, multiplier=30.0, cost_pct_of_notional=0.0, exposure_factor=1.0)),
    )
    stats = summarize(trades)
    assert stats.n == len(trades)
    if trades:
        assert stats.to_dict()["trades"] == len(trades)
        assert "resolutions" in stats.to_dict()
        assert set(group_stats(trades, "pattern")) <= {
            "engulfing",
            "pin",
            "break_of_structure",
            "inside_bar",
            "none",
        }


def _trending_frame(n: int = 400) -> pd.DataFrame:
    price = 100.0
    closes = []
    for i in range(n):
        price += 0.05 if i % 7 else -0.03
        closes.append(price)
    closes = np.array(closes)
    opens = np.concatenate([[closes[0] - 0.05], closes[:-1]])
    return _frame(
        highs=np.maximum(opens, closes) + 0.08,
        lows=np.minimum(opens, closes) - 0.08,
        closes=closes,
        opens=opens,
    )


def test_pattern_filter_restricts_entries_to_rejection_candles():
    df = _trending_frame()
    config = ReplayConfig(
        spec=ContractSpec(stake=100.0, multiplier=30.0, cost_pct_of_notional=0.0, exposure_factor=1.0),
        require_patterns=frozenset({"pin", "engulfing"}),
    )
    trades = replay_pattern_strategy("R_50", df, "price_action", config)
    assert all(t.pattern in {"pin", "engulfing"} for t in trades)


def test_every_exit_policy_scores_the_same_entries():
    """Exit policies must be compared on identical entries, not on samples they cause."""
    df = _trending_frame(600)
    spec = ContractSpec(stake=100.0, multiplier=30.0, cost_pct_of_notional=0.0, exposure_factor=1.0)
    entries = find_pattern_entries(
        "R_50", df, "trend_following", ReplayConfig(spec=spec)
    )

    counts = set()
    for policy in exit_policies():
        config = ReplayConfig(spec=spec, policy=policy)
        trades = resolve_entries("R_50", df, entries, config)
        counts.add(len(trades))

    assert counts == {len(entries)}


def test_entry_discovery_is_independent_of_barriers_and_exits():
    df = _trending_frame(600)
    aggressive = ReplayConfig(
        spec=ContractSpec(stake=100.0, multiplier=80.0, cost_pct_of_notional=0.0, exposure_factor=1.0),
        barrier_mode="as_deployed",
        policy=ExitPolicy(name="time_1h", max_hours=1.0),
    )
    conservative = ReplayConfig(
        spec=ContractSpec(stake=50.0, multiplier=30.0),
        barrier_mode="chart_matched",
    )
    a = find_pattern_entries("R_50", df, "trend_following", aggressive)
    b = find_pattern_entries("R_50", df, "trend_following", conservative)
    assert [e.idx for e in a] == [e.idx for e in b]
