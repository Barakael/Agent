"""Pre-close scenario evaluation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

from signals.engine import SignalDirection, SignalEngine


@dataclass
class CloseScenarioResult:
    passed: bool
    reason: str
    details: dict = field(default_factory=dict)


def evaluate_close(
    position: dict,
    df: pd.DataFrame,
    *,
    force_eod: bool = False,
    news_paused: bool = False,
    news_reason: str = "",
) -> CloseScenarioResult:
    """Decide whether closing a position is justified."""
    if force_eod:
        return CloseScenarioResult(True, "session_eod_force_close", {"forced": True})

    if news_paused:
        return CloseScenarioResult(True, "news_window_close", {"news": news_reason})

    profit = float(position.get("profit", 0) or 0)

    # Only close a winning trade when it has hit or surpassed its TP dollar limit.
    # Deriv handles the actual TP/SL triggers; we do NOT close-out just because
    # profit > 0 — that was truncating winners far short of the target.
    limit_order = position.get("limit_order") or {}
    tp_limit = limit_order.get("take_profit")
    if tp_limit is not None:
        try:
            if profit >= float(tp_limit):
                return CloseScenarioResult(True, "take_profit_reached", {"profit": profit, "tp": tp_limit})
        except (TypeError, ValueError):
            pass

    symbol = position.get("underlying") or position.get("symbol") or ""
    contract_type = (position.get("contract_type") or "").upper()
    is_long = contract_type in ("CALL", "BUY", "MULTUP")

    if len(df) >= 30:
        engine = SignalEngine()
        signal = engine.evaluate(symbol, df)
        if signal:
    # Dead-code guard: Deriv's dollar stop handles actual stop triggers.
    # We only soft-stop here if we somehow have no dollar SL set at all.
    sl_limit = limit_order.get("stop_loss")
    if sl_limit is None and profit < -float(position.get("buy_price", 1) or 1) * 0.5:
                is_long and signal.direction == SignalDirection.SELL
            ) or (not is_long and signal.direction == SignalDirection.BUY)
            if reversal:
                return CloseScenarioResult(
                    True,
                    "technical_reversal",
                    {"signal": signal.reason, "profit": profit},
                )

    if profit < -float(position.get("buy_price", 1) or 1) * 0.5:
        return CloseScenarioResult(True, "stop_loss_threshold", {"profit": profit})

    return CloseScenarioResult(
        False,
        "hold_position_scenario_favorable",
        {"profit": profit, "symbol": symbol},
    )
