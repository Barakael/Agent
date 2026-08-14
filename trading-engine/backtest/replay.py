"""Bar-by-bar replay that prices Deriv multiplier contracts honestly.

Unlike :mod:`backtest.runner`, this harness drives the shipping
``NumberEngine`` / strategy / bias code, resolves exits from each bar's high
and low, and converts price distances into contract dollars the same way a
MULTUP/MULTDOWN position behaves — including liquidation once the adverse
move reaches ``1 / multiplier``.
"""

from __future__ import annotations

import statistics
from collections import Counter
from dataclasses import dataclass, field
from typing import Iterable, Literal, Optional

import pandas as pd

from analysis.horizon_projection import (
    compute_horizon_projection,
    projection_agrees_with_bias,
)
from bias.bias_6h import compute_bias_6h
from bias.confirm_1h import confirm_1h_entry, is_entry_bar_close
from bias.regime_24h import compute_regime_24h
from bias.risk import bias_sl_tp
from config import settings
from number_engine import NumberEngine
from number_engine.snapshot import MarketSnapshot
from risk.gate import pip_size
from signals.engine import SignalDirection
from strategies import get_strategy
from strategies.base import StrategyContext

BarrierMode = Literal["as_deployed", "chart_matched"]
Resolution = Literal["target", "stop", "trail", "stake_out", "time", "end_of_data"]


@dataclass(frozen=True)
class ContractSpec:
    """Economics of one Deriv multiplier position."""

    stake: float = 100.0
    multiplier: float = 100.0
    # Measured against live Deriv proposals on the forex majors, which quote the
    # trigger price for any dollar limit (scripts/demo_roundtrip.py). Their P/L
    # behaves as ``exposure_factor x notional x move/entry - cost``:
    #   * only ~97% of the gross position earns the move
    #   * total cost is ~0.088% of notional, four times the 0.02% commission
    #     quoted in the proposal, the rest being spread
    # Charging only the quoted commission understated real cost fourfold, which
    # on a 0.42% stop is the difference between paying 5% and 21% of the risked
    # amount per trade.
    cost_pct_of_notional: float = 0.00088
    exposure_factor: float = 0.97

    @property
    def notional(self) -> float:
        return self.stake * self.multiplier

    @property
    def effective_notional(self) -> float:
        """The part of the position that actually earns the move."""
        return self.notional * self.exposure_factor

    @property
    def stake_out_pct(self) -> float:
        """Adverse move that wipes the stake, cost included.

        Not 1 / multiplier: cost is charged out of the same stake, so
        liquidation arrives slightly sooner. Deriv quoted stop-out at 0.94% on a
        x100 contract, not the 1.00% the plain formula implies.
        """
        room = max(self.effective_notional, 1e-9)
        return max(self.stake - self.cost_usd, 0.0) / room

    @property
    def cost_usd(self) -> float:
        return self.notional * self.cost_pct_of_notional

    def pnl_usd(self, entry: float, exit_price: float, direction: SignalDirection) -> float:
        if entry <= 0:
            return 0.0
        move = (exit_price - entry) if direction == SignalDirection.BUY else (entry - exit_price)
        gross = self.effective_notional * (move / entry)
        # A multiplier position cannot lose more than its stake: the venue closes
        # it at stop-out, so cost is inside that loss rather than added to it.
        return max(gross - self.cost_usd, -self.stake)

    def pct_to_usd(self, pct: float) -> float:
        """Net dollars for a move, so it matches what the venue's limits mean."""
        return self.effective_notional * pct - self.cost_usd

    def usd_to_pct(self, usd: float) -> float:
        return (usd + self.cost_usd) / max(self.effective_notional, 1e-9)


@dataclass
class Barriers:
    """Stop and target expressed as prices, percentages, and contract dollars."""

    sl_price: float
    tp_price: float
    sl_pct: float
    tp_pct: float
    usd_sl: float
    usd_tp: float
    mode: BarrierMode
    encodable: bool


def _pip(symbol: str) -> float:
    return pip_size(symbol)


def build_barriers(
    *,
    symbol: str,
    entry: float,
    direction: SignalDirection,
    chart_sl: float,
    chart_tp: float,
    spec: ContractSpec,
    mode: BarrierMode,
) -> Barriers:
    """Translate a strategy's chart levels into contract barriers.

    ``chart_matched`` keeps the plan's own distances. ``as_deployed`` reproduces
    :func:`execution.orders.usd_limit_from_risk`, which fixes the stop at
    ``0.8 x stake`` and derives the target from the pip ratio — so the position
    ignores the chart distance entirely.
    """
    sl_dist = abs(entry - chart_sl)
    tp_dist = abs(chart_tp - entry)
    chart_sl_pct = sl_dist / entry if entry else 0.0
    chart_tp_pct = tp_dist / entry if entry else 0.0

    if mode == "chart_matched":
        sl_pct, tp_pct = chart_sl_pct, chart_tp_pct
    else:
        pip = _pip(symbol)
        sl_pips = max(1, int(round(sl_dist / pip)))
        tp_pips = max(1, int(round(tp_dist / pip)))
        sl_pct = spec.usd_to_pct(spec.stake * 0.8)
        tp_pct = spec.usd_to_pct(spec.stake * (tp_pips / sl_pips))

    sign = 1.0 if direction == SignalDirection.BUY else -1.0
    return Barriers(
        sl_price=entry * (1.0 - sign * sl_pct),
        tp_price=entry * (1.0 + sign * tp_pct),
        sl_pct=sl_pct,
        tp_pct=tp_pct,
        usd_sl=spec.pct_to_usd(sl_pct),
        usd_tp=spec.pct_to_usd(tp_pct),
        mode=mode,
        encodable=sl_pct <= spec.stake_out_pct + 1e-12,
    )


@dataclass
class ExitPolicy:
    """How a position is managed once open."""

    name: str = "target_only"
    max_hours: Optional[float] = None
    partial_at_r: Optional[float] = None
    partial_fraction: float = 0.5
    trail_after_r: Optional[float] = None
    # Engine capability this policy needs. The bot can only send a static
    # stop_loss / take_profit at open, so anything else is a proposal, not a
    # result that can be deployed.
    requires: str = ""


def exit_policies() -> list[ExitPolicy]:
    """The exit rules under comparison.

    Half of all live wins came from an operator flatten at partial profit and
    only nine trades ever reached a target, so the target is a hypothesis to be
    measured against time-based and profit-taking alternatives.
    """
    return [
        ExitPolicy(name="target_2r"),
        ExitPolicy(name="time_4h", max_hours=4.0, requires="scheduled_close"),
        ExitPolicy(name="time_8h", max_hours=8.0, requires="scheduled_close"),
        ExitPolicy(
            name="partial_1r_runner",
            partial_at_r=1.0,
            partial_fraction=0.5,
            requires="partial_close",
        ),
        ExitPolicy(name="trail_after_1r", trail_after_r=1.0, requires="contract_update"),
        ExitPolicy(
            name="partial_and_trail",
            partial_at_r=1.0,
            partial_fraction=0.5,
            trail_after_r=1.0,
            requires="contract_update+partial_close",
        ),
    ]


@dataclass
class ReplayTrade:
    symbol: str
    strategy_id: str
    direction: str
    pattern: str
    regime: str
    entry_epoch: int
    entry_price: float
    exit_price: float
    pnl_usd: float
    resolution: Resolution
    bars_held: int
    hours_held: float
    mfe_r: float
    mae_r: float
    sl_pct: float
    tp_pct: float
    encodable: bool

    @property
    def is_win(self) -> bool:
        return self.pnl_usd > 0


def _favorable_pct(entry: float, price: float, direction: SignalDirection) -> float:
    if entry <= 0:
        return 0.0
    move = (price - entry) if direction == SignalDirection.BUY else (entry - price)
    return move / entry


def resolve_exit(
    df: pd.DataFrame,
    entry_idx: int,
    *,
    entry: float,
    direction: SignalDirection,
    barriers: Barriers,
    spec: ContractSpec,
    policy: ExitPolicy,
    bar_minutes: int,
) -> tuple[float, float, Resolution, int, float, float]:
    """Walk bars forward and return the first barrier the position touches.

    When a single bar spans both barriers the stop is assumed first, so results
    stay pessimistic rather than flattering the target.
    """
    is_buy = direction == SignalDirection.BUY
    risk_pct = max(barriers.sl_pct, 1e-9)
    stake_out_pct = spec.stake_out_pct

    # Liquidation can sit closer to entry than the planned stop.
    effective_stop_pct = min(risk_pct, stake_out_pct)
    stop_is_liquidation = stake_out_pct < risk_pct

    best_fav_pct = 0.0
    worst_adverse_pct = 0.0
    realized = 0.0
    remaining = 1.0
    trail_pct: Optional[float] = None

    highs = df["high"].astype(float)
    lows = df["low"].astype(float)
    closes = df["close"].astype(float)

    # Elapsed time comes from timestamps, not bar counts. Instruments that close
    # overnight or for the weekend leave gaps, and counting bars there would call
    # a position "4 hours old" days after it opened.
    epochs = df["epoch"].astype("int64") if "epoch" in df.columns else None
    entry_epoch = int(epochs.iloc[entry_idx]) if epochs is not None else 0

    for i in range(entry_idx + 1, len(df)):
        high = float(highs.iloc[i])
        low = float(lows.iloc[i])
        bars_held = i - entry_idx
        if epochs is not None:
            hours_held = (int(epochs.iloc[i]) - entry_epoch) / 3600.0
        else:
            hours_held = bars_held * bar_minutes / 60.0

        fav_extreme = high if is_buy else low
        adv_extreme = low if is_buy else high
        best_fav_pct = max(best_fav_pct, _favorable_pct(entry, fav_extreme, direction))
        worst_adverse_pct = min(
            worst_adverse_pct, _favorable_pct(entry, adv_extreme, direction)
        )

        # A trailed stop is always tighter than the original; it may sit past entry.
        # Only a trail set on an earlier bar applies, so this bar's own excursion
        # cannot both raise the stop and be stopped out by it.
        trail_active = trail_pct is not None
        stop_pct = trail_pct if trail_active else effective_stop_pct
        stop_price = entry * (1.0 - (1.0 if is_buy else -1.0) * stop_pct)
        hit_stop = low <= stop_price if is_buy else high >= stop_price
        hit_target = high >= barriers.tp_price if is_buy else low <= barriers.tp_price

        if policy.partial_at_r and remaining == 1.0:
            partial_pct = policy.partial_at_r * risk_pct
            partial_price = entry * (1.0 + (1.0 if is_buy else -1.0) * partial_pct)
            reached = high >= partial_price if is_buy else low <= partial_price
            if reached and not hit_stop:
                realized += policy.partial_fraction * spec.pnl_usd(
                    entry, partial_price, direction
                )
                remaining = 1.0 - policy.partial_fraction

        if policy.trail_after_r and best_fav_pct >= policy.trail_after_r * risk_pct:
            trail_pct = -(best_fav_pct - risk_pct)

        if hit_stop:
            if trail_active:
                resolution: Resolution = "trail"
            elif stop_is_liquidation:
                resolution = "stake_out"
            else:
                resolution = "stop"
            pnl = realized + remaining * spec.pnl_usd(entry, stop_price, direction)
            if resolution == "stake_out":
                # Stop-out forfeits the stake, cost included — not stake plus cost.
                pnl = realized + remaining * (-spec.stake)
            return (
                stop_price,
                pnl,
                resolution,
                bars_held,
                best_fav_pct / risk_pct,
                worst_adverse_pct / risk_pct,
            )

        if hit_target:
            pnl = realized + remaining * spec.pnl_usd(entry, barriers.tp_price, direction)
            return (
                barriers.tp_price,
                pnl,
                "target",
                bars_held,
                best_fav_pct / risk_pct,
                worst_adverse_pct / risk_pct,
            )

        if policy.max_hours is not None and hours_held >= policy.max_hours:
            exit_price = float(closes.iloc[i])
            pnl = realized + remaining * spec.pnl_usd(entry, exit_price, direction)
            return (
                exit_price,
                pnl,
                "time",
                bars_held,
                best_fav_pct / risk_pct,
                worst_adverse_pct / risk_pct,
            )

    last = float(closes.iloc[-1])
    bars_held = len(df) - 1 - entry_idx
    pnl = realized + remaining * spec.pnl_usd(entry, last, direction)
    return (
        last,
        pnl,
        "end_of_data",
        bars_held,
        best_fav_pct / risk_pct,
        worst_adverse_pct / risk_pct,
    )


def snapshot_pattern(snapshot: MarketSnapshot) -> str:
    """Pattern label in the same precedence ``price_action`` scores them."""
    if snapshot.engulfing:
        return "engulfing"
    if snapshot.pin_bar:
        return "pin"
    if snapshot.break_of_structure_up or snapshot.break_of_structure_down:
        return "break_of_structure"
    if snapshot.inside_bar:
        return "inside_bar"
    return "none"


@dataclass
class ReplayConfig:
    spec: ContractSpec = field(default_factory=ContractSpec)
    barrier_mode: BarrierMode = "chart_matched"
    policy: ExitPolicy = field(default_factory=ExitPolicy)
    buffer_bars: int = 0
    bar_minutes: int = 0
    confidence_threshold: Optional[float] = None
    require_patterns: Optional[frozenset[str]] = None
    # Bars to wait after an entry before taking another. Fixed rather than
    # derived from the holding time so every exit policy sees the same entries.
    cooldown_bars: int = 0

    def __post_init__(self) -> None:
        if not self.buffer_bars:
            self.buffer_bars = int(settings.CANDLE_BUFFER_SIZE)
        if not self.bar_minutes:
            self.bar_minutes = int(settings.CANDLE_TIMEFRAME_MINUTES)
        if not self.cooldown_bars:
            self.cooldown_bars = max(1, int(6 * 60 / self.bar_minutes))


@dataclass
class EntryCandidate:
    """A signal to open, independent of how it is later closed."""

    idx: int
    epoch: int
    entry: float
    direction: SignalDirection
    chart_sl: float
    chart_tp: float
    strategy_id: str
    pattern: str
    regime: str


def find_pattern_entries(
    symbol: str,
    df: pd.DataFrame,
    strategy_id: str,
    config: Optional[ReplayConfig] = None,
) -> list[EntryCandidate]:
    """Collect entries for one pattern strategy in isolation.

    Strategies are called directly rather than through ``StrategyManager`` so a
    single strategy's edge is measured without the allowlist or regime map
    silently substituting another.
    """
    config = config or ReplayConfig()
    strategy = get_strategy(strategy_id)
    if strategy is None:
        return []

    engine = NumberEngine()
    ctx = StrategyContext(trade_mode="pattern", hold_policy="intraday")
    threshold = (
        config.confidence_threshold
        if config.confidence_threshold is not None
        else float(settings.STRATEGY_CONFIDENCE_THRESHOLD)
    )

    entries: list[EntryCandidate] = []
    next_free_idx = 0
    start = max(engine.min_bars, config.buffer_bars // 4)

    for i in range(start, len(df) - 1):
        if i < next_free_idx:
            continue
        window = df.iloc[max(0, i - config.buffer_bars + 1) : i + 1]
        snap = engine.compute(symbol, window)
        if snap is None:
            continue

        evaluation = strategy.evaluate_snapshot(snap, ctx)
        if not evaluation.is_trade or evaluation.confidence < threshold:
            continue

        pattern = evaluation.pattern or snapshot_pattern(snap)
        if config.require_patterns and pattern not in config.require_patterns:
            continue
        if not evaluation.suggested_sl or not evaluation.suggested_tp:
            continue

        entries.append(
            EntryCandidate(
                idx=i,
                epoch=snap.epoch,
                entry=snap.close,
                direction=evaluation.direction,
                chart_sl=float(evaluation.suggested_sl),
                chart_tp=float(evaluation.suggested_tp),
                strategy_id=strategy_id,
                pattern=pattern,
                regime=snap.regime,
            )
        )
        next_free_idx = i + config.cooldown_bars

    return entries


def resolve_entries(
    symbol: str,
    df: pd.DataFrame,
    entries: Iterable[EntryCandidate],
    config: Optional[ReplayConfig] = None,
) -> list[ReplayTrade]:
    """Price a fixed entry list under one barrier mode and exit policy."""
    config = config or ReplayConfig()
    return [
        _open_and_resolve(
            symbol=symbol,
            df=df,
            entry_idx=candidate.idx,
            entry=candidate.entry,
            direction=candidate.direction,
            chart_sl=candidate.chart_sl,
            chart_tp=candidate.chart_tp,
            strategy_id=candidate.strategy_id,
            pattern=candidate.pattern,
            regime=candidate.regime,
            entry_epoch=candidate.epoch,
            config=config,
        )
        for candidate in entries
    ]


def replay_pattern_strategy(
    symbol: str,
    df: pd.DataFrame,
    strategy_id: str,
    config: Optional[ReplayConfig] = None,
) -> list[ReplayTrade]:
    """Find and resolve entries for one pattern strategy."""
    config = config or ReplayConfig()
    entries = find_pattern_entries(symbol, df, strategy_id, config)
    return resolve_entries(symbol, df, entries, config)


def find_bias_entries(
    symbol: str,
    df: pd.DataFrame,
    config: Optional[ReplayConfig] = None,
) -> list[EntryCandidate]:
    """Collect entries from the 24h regime, 6h bias, 8h projection, 1h confirm chain."""
    config = config or ReplayConfig()
    entries: list[EntryCandidate] = []
    next_free_idx = 0
    bar_minutes = config.bar_minutes
    warmup = max(int(settings.BIAS_REGIME_HOURS * 60 / bar_minutes), 288)

    prev_bias = None
    traded_bias_ids: set[str] = set()

    for i in range(warmup, len(df) - 1):
        epoch = int(df["epoch"].iloc[i])
        # Entries only occur on entry-TF closes, so the layers are rebuilt there.
        if not is_entry_bar_close(epoch, settings.BIAS_ENTRY_TF_MINUTES):
            continue
        if i < next_free_idx:
            continue
        window = df.iloc[max(0, i - config.buffer_bars + 1) : i + 1]

        regime = compute_regime_24h(
            window, bar_minutes=bar_minutes, hours=settings.BIAS_REGIME_HOURS
        )
        bias = compute_bias_6h(
            window,
            regime,
            bar_minutes=bar_minutes,
            hours=settings.BIAS_LOOKBACK_HOURS,
            deadzone_atr_frac=settings.BIAS_DEADZONE_ATR_FRAC,
            prev_bias=prev_bias,
        )
        prev_bias = bias

        if bias.direction == "NO_TRADE" or bias.bias_id in traded_bias_ids:
            continue

        projection = compute_horizon_projection(
            window,
            lookback_hours=int(settings.PROJECTION_LOOKBACK_HOURS),
            forward_hours=int(settings.PROJECTION_FORWARD_HOURS),
            bar_minutes=bar_minutes,
            atr_mult=float(settings.PROJECTION_ATR_MULT),
        )
        agreed, _, _ = projection_agrees_with_bias(bias.direction, projection)
        if not agreed:
            continue

        confirm = confirm_1h_entry(
            window,
            bias,
            regime,
            bar_minutes=bar_minutes,
            entry_tf_minutes=settings.BIAS_ENTRY_TF_MINUTES,
        )
        if not confirm.ok:
            continue
        if config.require_patterns and confirm.confirm_type not in config.require_patterns:
            continue

        direction = (
            SignalDirection.BUY if confirm.direction == "buy" else SignalDirection.SELL
        )
        entry = confirm.entry_price or float(df["close"].iloc[i])
        chart_sl, chart_tp, _ = bias_sl_tp(bias, entry, direction)

        entries.append(
            EntryCandidate(
                idx=i,
                epoch=epoch,
                entry=entry,
                direction=direction,
                chart_sl=chart_sl,
                chart_tp=chart_tp,
                strategy_id="bias_pipeline",
                pattern=confirm.confirm_type or "none",
                regime=regime.label,
            )
        )
        traded_bias_ids.add(bias.bias_id)
        next_free_idx = i + config.cooldown_bars

    return entries


def replay_bias_pipeline(
    symbol: str,
    df: pd.DataFrame,
    config: Optional[ReplayConfig] = None,
) -> list[ReplayTrade]:
    """Find and resolve entries from the bias pipeline."""
    config = config or ReplayConfig()
    entries = find_bias_entries(symbol, df, config)
    return resolve_entries(symbol, df, entries, config)


def _elapsed_hours(
    df: pd.DataFrame, entry_idx: int, bars_held: int, bar_minutes: int
) -> float:
    """Wall-clock hours a position was open, using timestamps where available."""
    exit_idx = min(entry_idx + bars_held, len(df) - 1)
    if "epoch" in df.columns and exit_idx > entry_idx:
        start = int(df["epoch"].astype("int64").iloc[entry_idx])
        end = int(df["epoch"].astype("int64").iloc[exit_idx])
        return (end - start) / 3600.0
    return bars_held * bar_minutes / 60.0


def _open_and_resolve(
    *,
    symbol: str,
    df: pd.DataFrame,
    entry_idx: int,
    entry: float,
    direction: SignalDirection,
    chart_sl: float,
    chart_tp: float,
    strategy_id: str,
    pattern: str,
    regime: str,
    entry_epoch: int,
    config: ReplayConfig,
) -> ReplayTrade:
    barriers = build_barriers(
        symbol=symbol,
        entry=entry,
        direction=direction,
        chart_sl=chart_sl,
        chart_tp=chart_tp,
        spec=config.spec,
        mode=config.barrier_mode,
    )
    exit_price, pnl, resolution, bars_held, mfe_r, mae_r = resolve_exit(
        df,
        entry_idx,
        entry=entry,
        direction=direction,
        barriers=barriers,
        spec=config.spec,
        policy=config.policy,
        bar_minutes=config.bar_minutes,
    )
    return ReplayTrade(
        symbol=symbol,
        strategy_id=strategy_id,
        direction=direction.value,
        pattern=pattern,
        regime=regime,
        entry_epoch=entry_epoch,
        entry_price=entry,
        exit_price=exit_price,
        pnl_usd=round(pnl, 2),
        resolution=resolution,
        bars_held=bars_held,
        hours_held=round(
            _elapsed_hours(df, entry_idx, bars_held, config.bar_minutes), 2
        ),
        mfe_r=round(mfe_r, 3),
        mae_r=round(mae_r, 3),
        sl_pct=round(barriers.sl_pct, 6),
        tp_pct=round(barriers.tp_pct, 6),
        encodable=barriers.encodable,
    )


@dataclass
class ReplayStats:
    n: int = 0
    unresolved: int = 0
    wins: int = 0
    losses: int = 0
    total_pnl: float = 0.0
    expectancy: float = 0.0
    win_rate: float = 0.0
    avg_mfe_r: float = 0.0
    avg_mae_r: float = 0.0
    max_drawdown: float = 0.0
    max_consecutive_losses: int = 0
    encodable_rate: float = 0.0
    # Expectancy is a sample mean, so it carries an error bar. Without one, a
    # positive number cannot be told apart from a lucky sample.
    stdev: float = 0.0
    std_error: float = 0.0
    t_stat: float = 0.0
    ci95_low: float = 0.0
    ci95_high: float = 0.0
    resolutions: dict[str, int] = field(default_factory=dict)

    @property
    def significant(self) -> bool:
        """True when expectancy is more than two standard errors above zero."""
        return self.t_stat >= 2.0

    def to_dict(self) -> dict:
        return {
            "trades": self.n,
            "unresolved": self.unresolved,
            "wins": self.wins,
            "losses": self.losses,
            "win_rate_pct": round(self.win_rate * 100, 2),
            "total_pnl": round(self.total_pnl, 2),
            "expectancy": round(self.expectancy, 2),
            "stdev": round(self.stdev, 2),
            "std_error": round(self.std_error, 2),
            "t_stat": round(self.t_stat, 2),
            "ci95": [round(self.ci95_low, 2), round(self.ci95_high, 2)],
            "significant": self.significant,
            "avg_mfe_r": round(self.avg_mfe_r, 3),
            "avg_mae_r": round(self.avg_mae_r, 3),
            "max_drawdown": round(self.max_drawdown, 2),
            "max_consecutive_losses": self.max_consecutive_losses,
            "encodable_rate_pct": round(self.encodable_rate * 100, 1),
            "resolutions": self.resolutions,
        }


def summarize(trades: Iterable[ReplayTrade]) -> ReplayStats:
    """Aggregate resolved trades.

    Positions still open when the data ends are counted separately: marking them
    at the final close would let the sample's own drift flatter the expectancy.
    """
    all_rows = list(trades)
    rows = [t for t in all_rows if t.resolution != "end_of_data"]
    stats = ReplayStats(
        n=len(rows), unresolved=len(all_rows) - len(rows)
    )
    if not rows:
        return stats

    pnls = [t.pnl_usd for t in rows]
    stats.wins = sum(1 for t in rows if t.is_win)
    stats.losses = sum(1 for t in rows if t.pnl_usd < 0)
    stats.total_pnl = sum(pnls)
    stats.expectancy = stats.total_pnl / len(rows)
    stats.win_rate = stats.wins / len(rows)
    stats.avg_mfe_r = statistics.mean(t.mfe_r for t in rows)
    stats.avg_mae_r = statistics.mean(t.mae_r for t in rows)
    stats.encodable_rate = sum(1 for t in rows if t.encodable) / len(rows)
    stats.resolutions = dict(Counter(t.resolution for t in rows))

    if len(rows) > 1:
        stats.stdev = statistics.stdev(pnls)
        stats.std_error = stats.stdev / (len(rows) ** 0.5)
        if stats.std_error > 0:
            stats.t_stat = stats.expectancy / stats.std_error
        stats.ci95_low = stats.expectancy - 1.96 * stats.std_error
        stats.ci95_high = stats.expectancy + 1.96 * stats.std_error

    running = 0.0
    peak = 0.0
    worst = 0.0
    streak = 0
    worst_streak = 0
    for pnl in pnls:
        running += pnl
        peak = max(peak, running)
        worst = min(worst, running - peak)
        if pnl < 0:
            streak += 1
            worst_streak = max(worst_streak, streak)
        else:
            streak = 0
    stats.max_drawdown = abs(worst)
    stats.max_consecutive_losses = worst_streak
    return stats


def group_stats(
    trades: Iterable[ReplayTrade], key: str
) -> dict[str, dict]:
    """Aggregate by ``strategy_id``, ``pattern``, ``symbol``, or ``regime``."""
    buckets: dict[str, list[ReplayTrade]] = {}
    for trade in trades:
        buckets.setdefault(str(getattr(trade, key)), []).append(trade)
    return {name: summarize(rows).to_dict() for name, rows in sorted(buckets.items())}
