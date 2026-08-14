"""Tests that contract barriers carry the chart's stop and target."""

from __future__ import annotations

import pytest

from config import settings
from execution.orders import (
    ContractBarriers,
    OrderExecutor,
    UnencodableStop,
    barriers_from_risk,
    usd_limit_from_risk,
)
from risk.gate import RiskCheckResult, RiskDecision
from signals.engine import SignalDirection, TradeSignal


def _risk(sl: float, tp: float, stake: float = 100.0) -> RiskCheckResult:
    return RiskCheckResult(
        decision=RiskDecision.APPROVED,
        reason="ok",
        stake=stake,
        stop_loss_price=sl,
        take_profit_price=tp,
        stop_loss_pips=200,
        take_profit_pips=300,
        sl_tp_method="atr",
    )


def _signal(price: float = 100.0) -> TradeSignal:
    return TradeSignal(
        symbol="R_50",
        direction=SignalDirection.BUY,
        rsi=55.0,
        macd=0.0,
        macd_signal=0.0,
        price=price,
        epoch=1_700_000_000,
        reason="test",
    )


class _FakeClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def buy_contract(self, **kwargs):
        self.calls.append(kwargs)
        return {"contract_id": 1}


def test_barriers_translate_chart_distance_into_contract_dollars():
    barriers = barriers_from_risk(_risk(sl=98.0, tp=103.0), entry=100.0, multiplier=30)
    # 2% stop and 3% target on 30x with a $100 stake.
    assert barriers.usd_sl == 60.0
    assert barriers.usd_tp == 90.0
    assert round(barriers.sl_pct, 6) == 0.02
    assert barriers.encodable is True


def test_barriers_no_longer_ship_a_flat_eighty_dollar_stop():
    near = barriers_from_risk(_risk(sl=99.0, tp=102.0), entry=100.0, multiplier=30)
    far = barriers_from_risk(_risk(sl=97.0, tp=106.0), entry=100.0, multiplier=30)
    # A wider chart stop must produce a wider dollar stop.
    assert near.usd_sl == 30.0
    assert far.usd_sl == 90.0
    assert near.usd_sl != far.usd_sl


def test_stop_beyond_contract_room_is_flagged_unencodable():
    barriers = barriers_from_risk(_risk(sl=98.0, tp=103.0), entry=100.0, multiplier=80)
    assert barriers.encodable is False
    assert round(barriers.room_pct, 5) == 0.0125


def test_usd_limit_from_risk_uses_the_entry_price():
    sl_usd, tp_usd = usd_limit_from_risk(_risk(sl=98.0, tp=103.0), 100.0)
    expected = barriers_from_risk(_risk(sl=98.0, tp=103.0), entry=100.0)
    assert (sl_usd, tp_usd) == (expected.usd_sl, expected.usd_tp)


@pytest.mark.asyncio
async def test_execute_signal_rejects_a_stop_that_cannot_be_encoded(monkeypatch):
    monkeypatch.setattr(settings, "DERIV_MULTIPLIER", 80.0)
    monkeypatch.setattr(settings, "REJECT_UNENCODABLE_STOP", True)
    monkeypatch.setattr(settings, "TRADING_MODE", "demo")

    client = _FakeClient()
    executor = OrderExecutor(client)  # type: ignore[arg-type]
    executor.mode = "demo"

    with pytest.raises(UnencodableStop):
        await executor.execute_signal(_signal(), _risk(sl=98.0, tp=103.0))
    assert client.calls == []


@pytest.mark.asyncio
async def test_execute_signal_sends_chart_matched_limits_and_percentages(monkeypatch):
    monkeypatch.setattr(settings, "DERIV_MULTIPLIER", 30.0)
    monkeypatch.setattr(settings, "REJECT_UNENCODABLE_STOP", True)

    client = _FakeClient()
    executor = OrderExecutor(client)  # type: ignore[arg-type]
    executor.mode = "demo"

    result = await executor.execute_signal(_signal(), _risk(sl=98.0, tp=103.0))

    assert result is not None
    call = client.calls[0]
    assert call["stop_loss"] == 60.0
    assert call["take_profit"] == 90.0
    assert call["multiplier"] == 30.0
    # Percentages travel with the order so a forced multiplier keeps the distance.
    assert round(call["stop_loss_pct"], 6) == 0.02
    assert round(call["take_profit_pct"], 6) == 0.03


@pytest.mark.asyncio
async def test_manual_order_without_entry_falls_back_but_warns(monkeypatch, caplog):
    monkeypatch.setattr(settings, "DERIV_MULTIPLIER", 30.0)
    client = _FakeClient()
    executor = OrderExecutor(client)  # type: ignore[arg-type]
    executor.mode = "demo"

    with caplog.at_level("WARNING"):
        await executor.execute_manual("R_50", "buy", 100.0, 98.0, 103.0)

    assert client.calls[0]["stop_loss"] == 80.0
    assert "no entry price" in caplog.text


@pytest.mark.asyncio
async def test_manual_order_with_entry_uses_chart_translation(monkeypatch):
    monkeypatch.setattr(settings, "DERIV_MULTIPLIER", 30.0)
    client = _FakeClient()
    executor = OrderExecutor(client)  # type: ignore[arg-type]
    executor.mode = "demo"

    await executor.execute_manual("R_50", "buy", 100.0, 98.0, 103.0, entry=100.0)

    assert client.calls[0]["stop_loss"] == 60.0
    assert client.calls[0]["take_profit"] == 90.0


def test_contract_barriers_room_tracks_multiplier():
    barriers = ContractBarriers(
        usd_sl=60.0,
        usd_tp=90.0,
        sl_pct=0.02,
        tp_pct=0.03,
        multiplier=30.0,
        encodable=True,
    )
    assert round(barriers.room_pct, 6) == round(1 / 30, 6)
