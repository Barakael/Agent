"""Empirical WR / expectancy by bias-pipeline feature buckets (Phase 3).

No auto-weighting — report only. Prefer ≥100 closed pipeline trades
(or ≥30 per major bucket) before promoting rules.

Usage:
  cd trading-engine && python -m scripts.bias_feature_report
  python -m scripts.bias_feature_report --min-n 5
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from typing import Any


def _bucket_stats(rows: list[dict]) -> dict[str, Any]:
    n = len(rows)
    if not n:
        return {"n": 0, "wins": 0, "wr_pct": None, "expectancy": None, "total_pnl": 0.0}
    wins = sum(1 for r in rows if (r.get("pnl") or 0) > 0)
    total = sum(float(r.get("pnl") or 0) for r in rows)
    return {
        "n": n,
        "wins": wins,
        "wr_pct": round(100.0 * wins / n, 1),
        "expectancy": round(total / n, 2),
        "total_pnl": round(total, 2),
    }


def build_report(min_n: int = 1) -> dict[str, Any]:
    from journal.models import TradeJournal, init_db

    Session = init_db()
    with Session() as db:
        rows = (
            db.query(TradeJournal)
            .filter(
                TradeJournal.status == "closed",
                TradeJournal.signal_source == "bias_pipeline",
            )
            .order_by(TradeJournal.closed_at.desc())
            .limit(2000)
            .all()
        )

    trades: list[dict] = []
    for r in rows:
        feat: dict = {}
        if r.feature_json:
            try:
                feat = json.loads(r.feature_json)
            except Exception:
                feat = {}
        trades.append(
            {
                "id": r.id,
                "pnl": float(r.pnl or 0),
                "regime": feat.get("regime") or r.market_condition,
                "bias": feat.get("bias"),
                "confirm_type": feat.get("confirm_type"),
                "utc_hour": feat.get("utc_hour"),
                "atr_6h": feat.get("bias_atr_6h") or feat.get("atr_6h"),
                "bias_id": r.bias_id,
            }
        )

    by_regime: dict[str, list] = defaultdict(list)
    by_bias: dict[str, list] = defaultdict(list)
    by_confirm: dict[str, list] = defaultdict(list)
    by_hour: dict[str, list] = defaultdict(list)
    by_atr: dict[str, list] = defaultdict(list)

    for t in trades:
        by_regime[str(t.get("regime") or "unknown")].append(t)
        by_bias[str(t.get("bias") or "unknown")].append(t)
        by_confirm[str(t.get("confirm_type") or "unknown")].append(t)
        hour = t.get("utc_hour")
        by_hour[str(hour) if hour is not None else "unknown"].append(t)
        atr = t.get("atr_6h")
        if atr is None:
            bucket = "unknown"
        elif atr < 0.5:
            bucket = "atr_low"
        elif atr < 1.5:
            bucket = "atr_mid"
        else:
            bucket = "atr_high"
        by_atr[bucket].append(t)

    def filt(d: dict[str, list]) -> dict[str, dict]:
        return {
            k: _bucket_stats(v)
            for k, v in sorted(d.items())
            if len(v) >= min_n
        }

    overall = _bucket_stats(trades)
    note = (
        "Insufficient sample for auto-weighting"
        if overall["n"] < 100
        else "Sample size supports manual rule review"
    )
    return {
        "pipeline": "bias_v1",
        "closed_pipeline_trades": overall["n"],
        "overall": overall,
        "note": note,
        "auto_weight": False,
        "by_regime": filt(by_regime),
        "by_bias": filt(by_bias),
        "by_confirm_type": filt(by_confirm),
        "by_utc_hour": filt(by_hour),
        "by_atr_bucket": filt(by_atr),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bias pipeline empirical feature report")
    parser.add_argument("--min-n", type=int, default=1, help="Min trades per bucket")
    parser.add_argument("--json", action="store_true", help="Print JSON only")
    args = parser.parse_args(argv)
    report = build_report(min_n=args.min_n)
    if args.json:
        print(json.dumps(report, indent=2))
        return 0
    print(f"Bias pipeline closed trades: {report['closed_pipeline_trades']}")
    print(f"Overall: {report['overall']}")
    print(f"Note: {report['note']}")
    for section in (
        "by_regime",
        "by_bias",
        "by_confirm_type",
        "by_utc_hour",
        "by_atr_bucket",
    ):
        print(f"\n== {section} ==")
        for k, v in report[section].items():
            print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
