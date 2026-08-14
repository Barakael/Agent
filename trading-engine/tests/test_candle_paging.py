"""Tests for backwards paging of Deriv candle history."""

from __future__ import annotations

import pytest

from data.deriv_ws import DerivWebSocketClient

GRAN = 300


def _series(start: int, n: int) -> list[dict]:
    return [
        {
            "epoch": start + i * GRAN,
            "open": 100.0,
            "high": 100.5,
            "low": 99.5,
            "close": 100.1,
            "volume": 0,
        }
        for i in range(n)
    ]


class _FakeHistory:
    """Serves a finite candle series honouring count and end."""

    def __init__(self, oldest: int, total: int) -> None:
        self.all = _series(oldest, total)
        self.calls: list[tuple[int, object]] = []

    async def fetch(self, symbol, granularity, count=200, end=None):
        self.calls.append((count, end))
        rows = self.all
        if end is not None and end != "latest":
            rows = [c for c in rows if c["epoch"] <= int(end)]
        return rows[-count:]


@pytest.mark.asyncio
async def test_paging_stitches_pages_into_one_ordered_series():
    client = DerivWebSocketClient(app_id="1089", api_token="", ws_url="ws://test")
    fake = _FakeHistory(oldest=1_700_000_000, total=12_000)
    client.get_candles_history = fake.fetch  # type: ignore[method-assign]

    candles = await client.get_candles_paged("R_50", GRAN, total=9_000, page_size=5_000)

    assert len(candles) == 9_000
    epochs = [c["epoch"] for c in candles]
    assert epochs == sorted(epochs)
    assert len(set(epochs)) == len(epochs)
    assert len(fake.calls) >= 2
    # First page reads the latest window, later pages walk backwards.
    assert fake.calls[0][1] is None
    assert isinstance(fake.calls[1][1], int)


@pytest.mark.asyncio
async def test_paging_stops_when_history_is_exhausted():
    client = DerivWebSocketClient(app_id="1089", api_token="", ws_url="ws://test")
    fake = _FakeHistory(oldest=1_700_000_000, total=800)
    client.get_candles_history = fake.fetch  # type: ignore[method-assign]

    candles = await client.get_candles_paged("R_50", GRAN, total=5_000, page_size=500)

    assert len(candles) == 800
    assert len(fake.calls) < 20


@pytest.mark.asyncio
async def test_paging_respects_an_explicit_end_epoch():
    client = DerivWebSocketClient(app_id="1089", api_token="", ws_url="ws://test")
    oldest = 1_700_000_000
    fake = _FakeHistory(oldest=oldest, total=4_000)
    client.get_candles_history = fake.fetch  # type: ignore[method-assign]

    cutoff = oldest + 1_000 * GRAN
    candles = await client.get_candles_paged(
        "R_50", GRAN, total=600, page_size=300, end=cutoff
    )

    assert candles
    assert max(c["epoch"] for c in candles) <= cutoff
    assert len(candles) == 600
