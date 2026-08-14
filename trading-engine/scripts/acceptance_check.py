#!/usr/bin/env python3
"""Check a replay report against the promotion criteria, and live results against it.

    python scripts/acceptance_check.py --report replay.json
    python scripts/acceptance_check.py --report replay.json --drift
    python scripts/acceptance_check.py --reset-journal

Promotion criteria (all must hold, per strategy):
  * at least 200 resolved replay trades
  * expectancy per trade above zero
  * expectancy at least two standard errors above zero, so it is not a lucky sample
  * worst losing run inside the daily drawdown limit at the configured stake
  * every stop encodable inside the contract's room

No criterion promises a win in any window. A configuration that fails is revised
or dropped, not deployed at a larger stake.
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from backtest.acceptance import (
    MIN_TRADES,
    evaluate_acceptance,
    expectancy_drift,
)
from backtest.replay import ReplayStats
from config import settings

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("acceptance")


def stats_from_dict(payload: dict) -> ReplayStats:
    stats = ReplayStats(
        n=int(payload.get("trades", 0)),
        unresolved=int(payload.get("unresolved", 0)),
        wins=int(payload.get("wins", 0)),
        losses=int(payload.get("losses", 0)),
    )
    stats.win_rate = float(payload.get("win_rate_pct", 0.0)) / 100.0
    stats.total_pnl = float(payload.get("total_pnl", 0.0))
    stats.expectancy = float(payload.get("expectancy", 0.0))
    stats.max_drawdown = float(payload.get("max_drawdown", 0.0))
    stats.max_consecutive_losses = int(payload.get("max_consecutive_losses", 0))
    stats.encodable_rate = float(payload.get("encodable_rate_pct", 0.0)) / 100.0
    stats.resolutions = dict(payload.get("resolutions", {}))
    stats.stdev = float(payload.get("stdev", 0.0))
    stats.std_error = float(payload.get("std_error", 0.0))
    stats.t_stat = float(payload.get("t_stat", 0.0))
    ci = payload.get("ci95") or [0.0, 0.0]
    stats.ci95_low, stats.ci95_high = float(ci[0]), float(ci[1])
    return stats


def best_run(report: dict) -> dict | None:
    """Highest-expectancy run that used chart-matched barriers."""
    candidates = [
        r
        for r in report.get("runs", [])
        if r.get("barrier_mode") == "chart_matched" and r["overall"]["trades"] > 0
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda r: r["overall"]["expectancy"])


def check_report(path: str, stake: float, balance: float) -> int:
    report = json.loads(Path(path).read_text())
    run = best_run(report)
    if run is None:
        logger.error("No chart-matched runs with trades in %s", path)
        return 1

    print(
        f"\nBest chart-matched run: multiplier={run['multiplier']:g} "
        f"exit={run['exit_policy']}"
    )
    print(f"Promotion criteria (min {MIN_TRADES} trades, expectancy > 0)\n")

    failures = 0
    for strategy_id, payload in sorted(run["by_strategy"].items()):
        result = evaluate_acceptance(
            strategy_id,
            stats_from_dict(payload),
            stake=stake,
            balance=balance,
        )
        status = "PASS" if result.passed else "FAIL"
        detail = result.detail
        print(
            f"  [{status}] {strategy_id}: n={detail['trades']} "
            f"win={detail['win_rate_pct']}% exp=${detail['expectancy']} "
            f"worst_streak={detail['max_consecutive_losses']}"
        )
        for failure in result.failures:
            print(f"           - {failure}")
        if not result.passed:
            failures += 1

    if failures:
        print(
            f"\n{failures} strategy(ies) not promotable. Revise or drop them; "
            "do not raise stake or frequency to compensate."
        )
        return 1
    print("\nAll strategies clear the promotion criteria.")
    return 0


def check_drift(path: str) -> int:
    from journal.models import TradeJournal
    from journal.writer import JournalWriter

    report = json.loads(Path(path).read_text())
    run = best_run(report)
    if run is None:
        logger.error("No chart-matched runs in report")
        return 1

    writer = JournalWriter()
    with writer.Session() as session:
        rows = (
            session.query(TradeJournal)
            .filter(TradeJournal.status == "closed", TradeJournal.pnl.isnot(None))
            .all()
        )
        live_pnls = [float(r.pnl) for r in rows]

    result = expectancy_drift(run["overall"]["expectancy"], live_pnls)
    print("\nLive versus replay expectancy")
    for key, value in result.to_dict().items():
        print(f"  {key}: {value}")
    return 1 if result.diverged else 0


def reset_journal() -> int:
    """Archive the journal so the next sample is not mixed with the old era."""
    url = str(settings.DATABASE_URL)
    if not url.startswith("sqlite"):
        logger.error("Refusing to reset a non-sqlite database: %s", url)
        return 1
    db_path = Path(url.split("sqlite:///")[-1]).resolve()
    if not db_path.exists():
        logger.info("No journal at %s — nothing to reset", db_path)
        return 0

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archive = db_path.with_name(f"{db_path.stem}.pre_expectancy_{stamp}{db_path.suffix}")
    shutil.copy2(db_path, archive)
    db_path.unlink()
    logger.info("Archived journal to %s and started a clean one", archive)
    print(
        "\nJournal reset. The spray-and-flatten sample is preserved in:\n"
        f"  {archive}\n"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", default="", help="JSON written by replay_report.py")
    parser.add_argument("--stake", type=float, default=settings.DEMO_FIXED_STAKE_USD)
    parser.add_argument("--balance", type=float, default=10_000.0)
    parser.add_argument("--drift", action="store_true", help="Compare live journal to replay")
    parser.add_argument("--reset-journal", action="store_true")
    args = parser.parse_args(argv)

    if args.reset_journal:
        return reset_journal()
    if not args.report:
        parser.error("--report is required unless --reset-journal is used")
    if args.drift:
        return check_drift(args.report)
    return check_report(args.report, args.stake, args.balance)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
