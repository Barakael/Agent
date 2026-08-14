#!/usr/bin/env python3
"""Replay R_50 history and report expectancy per barrier mode and exit policy.

Fetches (or reuses cached) 5m history, then runs every strategy twice — once
with the dollar barriers the bot used to ship, once with barriers matched to the
chart — across the exit policies under test.

    python scripts/replay_report.py --days 30
    python scripts/replay_report.py --offline --json out.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys

import pandas as pd

from backtest.history import fetch_history, gap_report, load_cached
from backtest.replay import (
    ContractSpec,
    EntryCandidate,
    ReplayConfig,
    exit_policies,
    find_bias_entries,
    find_pattern_entries,
    group_stats,
    resolve_entries,
    summarize,
)
from config import settings

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("replay_report")

# Measured together so each branch gets a sample; production gating stays separate.
MEASURE_PATTERNS = "pin,engulfing,break_of_structure"
MEASURE_CONFIRMS = "pin,engulfing,break_prev"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", default=",".join(settings.pairs_list))
    parser.add_argument("--days", type=float, default=30.0)
    parser.add_argument("--stake", type=float, default=settings.DEMO_FIXED_STAKE_USD)
    parser.add_argument(
        "--cost-pct",
        type=float,
        default=ContractSpec.cost_pct_of_notional,
        help=(
            "Total round-trip cost as a fraction of notional. Default is the "
            "0.088%% measured from live Deriv proposals, not the 0.02%% commission "
            "they quote, which is only part of it."
        ),
    )
    parser.add_argument(
        "--multipliers",
        default="100",
        help="Multipliers to compare; forex offers 100/200/300/500/800",
    )
    parser.add_argument(
        "--strategies",
        default="price_action,trend_following,bias_pipeline",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Use only cached history; never contact Deriv",
    )
    parser.add_argument("--json", dest="json_out", default="")
    return parser.parse_args(argv)


async def load_frames(args: argparse.Namespace) -> dict[str, pd.DataFrame]:
    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    granularity = int(settings.granularity_seconds)
    frames: dict[str, pd.DataFrame] = {}

    for symbol in symbols:
        cached = load_cached(symbol, granularity)
        needed = int(args.days * 86400 / granularity)
        if cached is not None and len(cached) >= needed * 0.9:
            frames[symbol] = cached
            logger.info("Using cached history for %s (%s bars)", symbol, len(cached))
            continue
        if args.offline:
            if cached is None:
                logger.error("No cached history for %s and --offline set", symbol)
                continue
            frames[symbol] = cached
            logger.warning(
                "Cached history for %s is short: %s of %s bars",
                symbol,
                len(cached),
                needed,
            )
            continue

        from data.deriv_ws import DerivWebSocketClient

        client = DerivWebSocketClient()
        await client.connect()
        try:
            if settings.DERIV_API_TOKEN:
                await client.authorize()
            frames[symbol] = await fetch_history(
                client, symbol, granularity, args.days
            )
        finally:
            await client.disconnect()

    return frames


def run_matrix(frames: dict[str, pd.DataFrame], args: argparse.Namespace) -> dict:
    granularity = int(settings.granularity_seconds)
    strategies = [s.strip() for s in args.strategies.split(",") if s.strip()]
    multipliers = [float(m) for m in args.multipliers.split(",") if m.strip()]
    report: dict = {
        "settings": {
            "days_requested": args.days,
            "stake": args.stake,
            "multipliers": multipliers,
            "cost_pct_of_notional": args.cost_pct,
            "bar_minutes": settings.CANDLE_TIMEFRAME_MINUTES,
        },
        "coverage": {
            symbol: gap_report(df, granularity) for symbol, df in frames.items()
        },
        "runs": [],
    }

    # Entries depend only on the chart, so they are found once and reused. Every
    # barrier mode and exit policy is then scored on an identical entry list.
    entries: dict[str, list[EntryCandidate]] = {}
    for symbol, df in frames.items():
        discovery = ReplayConfig(spec=ContractSpec(stake=args.stake))
        found: list[EntryCandidate] = []
        for strategy_id in strategies:
            if strategy_id == "bias_pipeline":
                found.extend(find_bias_entries(symbol, df, discovery))
            else:
                found.extend(find_pattern_entries(symbol, df, strategy_id, discovery))
        entries[symbol] = found
        logger.info("%s: %d entry candidates", symbol, len(found))
    report["entries_per_symbol"] = {s: len(v) for s, v in entries.items()}

    for multiplier in multipliers:
        spec = ContractSpec(
            stake=args.stake,
            multiplier=multiplier,
            cost_pct_of_notional=args.cost_pct,
        )
        for barrier_mode in ("as_deployed", "chart_matched"):
            for policy in exit_policies():
                trades = []
                for symbol, df in frames.items():
                    config = ReplayConfig(
                        spec=spec,
                        barrier_mode=barrier_mode,  # type: ignore[arg-type]
                        policy=policy,
                    )
                    trades.extend(
                        resolve_entries(symbol, df, entries[symbol], config)
                    )

                stats = summarize(trades)
                report["runs"].append(
                    {
                        "multiplier": multiplier,
                        "barrier_mode": barrier_mode,
                        "exit_policy": policy.name,
                        "requires": policy.requires,
                        "overall": stats.to_dict(),
                        "by_strategy": group_stats(trades, "strategy_id"),
                        "by_pattern": group_stats(trades, "pattern"),
                        "by_symbol": group_stats(trades, "symbol"),
                        "by_regime": group_stats(trades, "regime"),
                    }
                )
                logger.info(
                    "mult=%g %s %s: n=%d win=%.1f%% exp=%.2f",
                    multiplier,
                    barrier_mode,
                    policy.name,
                    stats.n,
                    stats.win_rate * 100,
                    stats.expectancy,
                )

    return report


def print_report(report: dict) -> None:
    print("\nCoverage")
    for symbol, cov in report["coverage"].items():
        print(
            f"  {symbol}: {cov['bars']} bars, {cov.get('days', 0)} days, "
            f"coverage {cov.get('coverage_pct', 0)}%, gaps {cov.get('gaps', 0)}"
        )

    print("\nExpectancy per resolved trade (USD), with 95% confidence interval")
    header = (
        f"  {'mult':>5} {'barriers':<14} {'exit':<18} {'n':>5} {'win%':>6} "
        f"{'exp':>8} {'t':>6} {'ci95':>18} {'sig':>4} {'encod%':>7} {'needs':<24}"
    )
    print(header)
    print("  " + "-" * (len(header) - 2))
    for run in report["runs"]:
        o = run["overall"]
        ci = f"[{o['ci95'][0]:.1f}, {o['ci95'][1]:.1f}]"
        print(
            f"  {run['multiplier']:>5g} {run['barrier_mode']:<14} {run['exit_policy']:<18} "
            f"{o['trades']:>5} {o['win_rate_pct']:>6} {o['expectancy']:>8} "
            f"{o['t_stat']:>6} {ci:>18} {'yes' if o['significant'] else 'no':>4} "
            f"{o['encodable_rate_pct']:>7} {run.get('requires') or '-':<24}"
        )

    print("\nRanked by expectancy")
    ranked = sorted(
        (r for r in report["runs"] if r["overall"]["trades"] > 0),
        key=lambda r: r["overall"]["expectancy"],
        reverse=True,
    )
    for run in ranked[:5]:
        o = run["overall"]
        note = "" if o["significant"] else "  <-- inside noise, not an edge"
        needs = run.get("requires")
        cap = f", needs {needs}" if needs else ""
        print(
            f"  mult={run['multiplier']:g} {run['barrier_mode']} {run['exit_policy']}: "
            f"exp={o['expectancy']} t={o['t_stat']}{cap}{note}"
        )

    significant = [
        r
        for r in report["runs"]
        if r["overall"]["significant"] and r["overall"]["expectancy"] > 0
    ]
    deployable = [r for r in significant if not r.get("requires")]
    print(
        f"\n{len(significant)} of {len(report['runs'])} configurations show a "
        f"statistically significant positive expectancy; "
        f"{len(deployable)} of those need no new engine capability."
    )


async def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    # Measure every branch, including the ones production now gates off.
    settings.PRICE_ACTION_PATTERNS = MEASURE_PATTERNS
    settings.BIAS_CONFIRM_TYPES = MEASURE_CONFIRMS

    frames = await load_frames(args)
    if not frames:
        logger.error("No history available — run without --offline once to populate cache")
        return 1

    report = run_matrix(frames, args)
    print_report(report)

    if args.json_out:
        with open(args.json_out, "w") as fh:
            json.dump(report, fh, indent=2)
        logger.info("Wrote %s", args.json_out)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1:])))
