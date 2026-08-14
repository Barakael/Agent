"""The Deriv endpoint's instrument field name is detected, not assumed."""

from __future__ import annotations

import pytest

from data.deriv_ws import DerivWebSocketClient


def _rejection(field: str) -> dict:
    return {
        "error": {
            "code": "InputValidationFailed",
            "message": f"Input validation failed: Properties not allowed: {field}.",
        }
    }


class _Recorder(DerivWebSocketClient):
    """Captures payloads and replays canned responses in order."""

    def __init__(self, responses: list[dict]) -> None:
        super().__init__(app_id="1089", api_token="t", ws_url="wss://example/ws")
        self.sent: list[dict] = []
        self._responses = list(responses)

    async def _send(self, payload: dict, timeout: float = 30.0) -> dict:
        self.sent.append(payload)
        return self._responses.pop(0)


def test_rejected_property_is_extracted():
    assert (
        DerivWebSocketClient._rejected_property(
            _rejection("underlying_symbol")["error"]
        )
        == "underlying_symbol"
    )
    assert DerivWebSocketClient._rejected_property({"code": "OfferingsValidationError"}) is None
    assert DerivWebSocketClient._rejected_property(None) is None


@pytest.mark.asyncio
async def test_falls_back_to_legacy_symbol_field():
    client = _Recorder([_rejection("underlying_symbol"), {"proposal": {"id": "abc"}}])

    resp = await client._send_for_symbol({"proposal": 1}, "frxEURUSD")

    assert resp == {"proposal": {"id": "abc"}}
    assert [p for p in client.sent[0] if p.endswith("symbol")] == ["underlying_symbol"]
    assert client.sent[1]["symbol"] == "frxEURUSD"
    assert client.symbol_key == "symbol"


@pytest.mark.asyncio
async def test_accepted_field_is_remembered_and_not_reprobed():
    client = _Recorder(
        [
            _rejection("underlying_symbol"),
            {"proposal": {"id": "one"}},
            {"proposal": {"id": "two"}},
        ]
    )

    await client._send_for_symbol({"proposal": 1}, "frxEURUSD")
    await client._send_for_symbol({"proposal": 1}, "frxGBPUSD")

    # Three payloads, not four: the second call skips the rejected spelling.
    assert len(client.sent) == 3
    assert client.sent[2]["symbol"] == "frxGBPUSD"


@pytest.mark.asyncio
async def test_a_real_error_does_not_trigger_a_schema_retry():
    """An unavailable instrument means the field was fine; do not try the other."""
    client = _Recorder([{"error": {"code": "OfferingsValidationError"}}])

    resp = await client._send_for_symbol({"proposal": 1}, "frxEURUSD")

    assert resp["error"]["code"] == "OfferingsValidationError"
    assert len(client.sent) == 1
    assert client.symbol_key == "underlying_symbol"


@pytest.mark.asyncio
async def test_contracts_for_does_not_send_currency():
    """The newer endpoint rejects currency outright, so it is never sent."""
    client = _Recorder([{"contracts_for": {"available": []}}, {"error": {"code": "x"}}])

    await client.get_allowed_multipliers("frxEURUSD")

    assert client.sent[0] == {"contracts_for": "frxEURUSD"}
    assert "currency" not in client.sent[0]
