"""Trading performance metrics."""

from __future__ import annotations

import math
from typing import List

import pandas as pd

from journal.models import TradeJournal, init_db


def compute_metrics(trades: List[dict] | None = None) -> dict:
    Session = init_db()
    if trades is None:
        with Session() as session:
            rows = session.query(TradeJournal).filter(TradeJournal.status == "closed").all()
            trades = [
                {
                    "pnl": r.pnl or 0.0,
                    "stake": r.stake,
                    "entry_price": r.entry_price,
                    "stop_loss": r.stop_loss,
                    "take_profit": r.take_profit,
                }
                for r in rows
            ]

    if not trades:
        return {
            "total_trades": 0,
            "win_rate": 0.0,
            "avg_rr": 0.0,
            "max_drawdown": 0.0,
            "sharpe_ratio": 0.0,
            "total_pnl": 0.0,
        }

    df = pd.DataFrame(trades)
    pnls = df["pnl"].fillna(0.0)
    wins = (pnls > 0).sum()
    total = len(pnls)
    win_rate = wins / total if total else 0.0

    # Average risk:reward from SL/TP distances
    rr_values = []
    for _, row in df.iterrows():
        risk = abs(row["entry_price"] - row["stop_loss"])
        reward = abs(row["take_profit"] - row["entry_price"])
        if risk > 0:
            rr_values.append(reward / risk)
    avg_rr = sum(rr_values) / len(rr_values) if rr_values else 0.0

    cumulative = pnls.cumsum()
    peak = cumulative.cummax()
    drawdown = cumulative - peak
    max_drawdown = float(abs(drawdown.min())) if len(drawdown) else 0.0

    sharpe = 0.0
    if len(pnls) > 1 and pnls.std() > 0:
        sharpe = float((pnls.mean() / pnls.std()) * math.sqrt(252))

    return {
        "total_trades": total,
        "win_rate": round(win_rate * 100, 2),
        "avg_rr": round(avg_rr, 2),
        "max_drawdown": round(max_drawdown, 2),
        "sharpe_ratio": round(sharpe, 2),
        "total_pnl": round(float(pnls.sum()), 2),
    }
