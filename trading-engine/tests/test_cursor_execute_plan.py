"""Cursor-execute plan schema and ALIGN gate."""

from __future__ import annotations

import pytest

from plan.schema import clamp_plan_dict

_ALIGNED = {
    "news_thesis": "USD soft",
    "structure_bias": "bullish",
    "prefer_symbol_order": ["frxEURUSD"],
    "invalidation": "break below ema21",
    "checklist": {
        "news_chart_aligned": True,
        "structure_aligned": True,
        "not_chasing": True,
        "rsi_ok": True,
        "event_ok": True,
    },
}


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
            "analysis": _ALIGNED,
            "setups": [
                {
                    "symbol": "frxEURUSD",
                    "direction": "buy",
                    "entry_style": "pullback",
                    "priority": 1,
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
    assert plan.prefer_order()[0] == "frxEURUSD"


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
            "execution_mode": "chart_confirm",
            "max_trades_today": 1,
            "analysis": {
                **_ALIGNED,
                "prefer_symbol_order": ["frxUSDJPY"],
                "structure_bias": "bearish",
            },
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


def test_misaligned_checklist_rejected():
    with pytest.raises(ValueError, match="ALIGN gate"):
        clamp_plan_dict(
            {
                "date": "2026-08-20",
                "trade_mode": "bias",
                "directional_bias": "buy",
                "pairs": ["frxGBPUSD"],
                "sl_pips": 20,
                "tp_pips": 40,
                "source": "cursor-automation",
                "max_trades_today": 1,
                "analysis": {
                    "news_thesis": "USD soft",
                    "checklist": {
                        "news_chart_aligned": False,
                        "structure_aligned": False,
                        "not_chasing": False,
                        "rsi_ok": False,
                        "event_ok": True,
                    },
                },
            }
        )


def test_missing_analysis_rejected_for_execute():
    with pytest.raises(ValueError, match="analysis.checklist required"):
        clamp_plan_dict(
            {
                "date": "2026-08-20",
                "trade_mode": "bias",
                "directional_bias": "buy",
                "pairs": ["frxEURUSD"],
                "sl_pips": 20,
                "tp_pips": 40,
                "source": "cursor-automation",
                "max_trades_today": 1,
            }
        )
