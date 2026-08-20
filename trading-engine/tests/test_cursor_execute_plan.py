"""Cursor-execute plan schema and execute-only path helpers."""

from __future__ import annotations

from plan.schema import clamp_plan_dict


def test_cursor_execute_plan_accepts_setups_and_review():
    plan = clamp_plan_dict(
        {
            "date": "2026-08-20",
            "trade_mode": "bias",
            "directional_bias": "buy",
            "hold_policy": "swing",
            "pairs": ["frxEURUSD", "frxGBPUSD"],
            "sl_pips": 20,
            "tp_pips": 40,
            "source": "cursor-automation",
            "execution_mode": "cursor_execute",
            "max_trades_today": 2,
            "entry_style": "pullback",
            "review": "USD soft; prefer EURUSD/GBPUSD longs near EMA21.",
            "setups": [
                {
                    "symbol": "frxEURUSD",
                    "direction": "buy",
                    "entry_style": "pullback",
                    "sl_pips": 20,
                    "tp_pips": 40,
                    "rationale": "pullback to ema21",
                }
            ],
        }
    )
    assert plan.is_cursor_execute is True
    assert plan.max_trades_today == 2
    assert plan.review.startswith("USD soft")
    assert len(plan.setups) == 1
    assert plan.setups[0].symbol == "frxEURUSD"
    assert plan.execution_mode == "cursor_execute"


def test_cursor_source_forces_cursor_execute_mode():
    plan = clamp_plan_dict(
        {
            "date": "2026-08-20",
            "trade_mode": "bias",
            "directional_bias": "sell",
            "pairs": ["frxUSDJPY"],
            "sl_pips": 25,
            "tp_pips": 50,
            "source": "cursor-cloud",
            "execution_mode": "chart_confirm",  # should be forced to cursor_execute
            "max_trades_today": 1,
        }
    )
    assert plan.execution_mode == "cursor_execute"
    assert plan.is_cursor_execute is True


def test_stand_aside_max_trades_zero_not_execute():
    plan = clamp_plan_dict(
        {
            "date": "2026-08-20",
            "trade_mode": "pattern",
            "directional_bias": "neutral",
            "pairs": ["frxEURUSD"],
            "source": "cursor-automation",
            "max_trades_today": 0,
            "review": "Stand aside",
        }
    )
    assert plan.is_cursor_execute is False
