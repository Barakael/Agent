"""Tests for strategy pruning and stacking caps."""

from __future__ import annotations

from config import settings
from strategies import (
    allowlist_strategy_ids,
    apply_strategy_allowlist,
    denylist_strategy_ids,
)


def test_denied_strategies_cannot_be_requested(monkeypatch):
    monkeypatch.setattr(settings, "STRATEGY_DENYLIST", "range_trading,momentum")
    monkeypatch.setattr(settings, "STRATEGY_ALLOWLIST", "")

    result = apply_strategy_allowlist(
        ["trend_following", "range_trading", "momentum", "price_action"]
    )

    assert result == ["trend_following", "price_action"]


def test_denylist_beats_an_allowlist_that_names_a_dead_strategy(monkeypatch):
    monkeypatch.setattr(settings, "STRATEGY_DENYLIST", "range_trading,momentum")
    monkeypatch.setattr(settings, "STRATEGY_ALLOWLIST", "momentum,trend_following")

    assert "momentum" not in allowlist_strategy_ids()
    assert allowlist_strategy_ids() == ["trend_following"]
    assert apply_strategy_allowlist(["momentum"]) == []


def test_denylist_resolves_legacy_aliases(monkeypatch):
    monkeypatch.setattr(settings, "STRATEGY_DENYLIST", "macd_rsi")
    # macd_rsi is an alias of momentum, so the archetype must be barred too.
    assert denylist_strategy_ids() == {"momentum"}
    monkeypatch.setattr(settings, "STRATEGY_ALLOWLIST", "")
    assert apply_strategy_allowlist(["momentum", "trend_following"]) == [
        "trend_following"
    ]


def test_empty_denylist_restores_every_strategy(monkeypatch):
    monkeypatch.setattr(settings, "STRATEGY_DENYLIST", "")
    monkeypatch.setattr(settings, "STRATEGY_ALLOWLIST", "")
    result = apply_strategy_allowlist(["momentum", "range_trading"])
    assert result == ["momentum", "range_trading"]


def test_stacking_caps_are_real_numbers_not_unlimited():
    assert settings.MAX_OPEN_POSITIONS == 1
    assert 0 < settings.MAX_TRADES_PER_DAY <= 6


def test_default_allowlist_excludes_unmeasured_strategies():
    assert settings.STRATEGY_ALLOWLIST == "trend_following"
    assert "range_trading" in settings.STRATEGY_DENYLIST
    assert "momentum" in settings.STRATEGY_DENYLIST
