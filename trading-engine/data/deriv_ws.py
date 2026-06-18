"""Deriv WebSocket client — auth, tick streaming, historical candles."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Callable, Dict, List, Optional

import websockets
from websockets.client import WebSocketClientProtocol

from config import settings

logger = logging.getLogger(__name__)


class DerivWebSocketClient:
    """Async Deriv WebSocket API client."""

    def __init__(
        self,
        app_id: Optional[str] = None,
        api_token: Optional[str] = None,
        ws_url: Optional[str] = None,
    ) -> None:
        self.app_id = app_id or settings.DERIV_APP_ID
        self.api_token = api_token or settings.DERIV_API_TOKEN
        self.ws_url = ws_url or settings.DERIV_WS_URL
        self._ws: Optional[WebSocketClientProtocol] = None
        self._req_id = 0
        self._pending: Dict[int, asyncio.Future] = {}
        self._tick_handlers: List[Callable[[str, float, int], None]] = []
        self._authorized = False
        self._balance: float = 0.0
        self._listen_task: Optional[asyncio.Task] = None

    def _next_id(self) -> int:
        self._req_id += 1
        return self._req_id

    async def connect(self) -> None:
        logger.info("Connecting to Deriv WebSocket")
        self._ws = await websockets.connect(
            self.ws_url,
            ping_interval=20,
            ping_timeout=20,
        )
        self._listen_task = asyncio.create_task(self._listen())

    async def disconnect(self) -> None:
        if self._listen_task:
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass
        if self._ws:
            await self._ws.close()
            self._ws = None

    async def _listen(self) -> None:
        assert self._ws is not None
        try:
            async for raw in self._ws:
                msg = json.loads(raw)
                req_id = msg.get("req_id")
                if req_id is not None and req_id in self._pending:
                    fut = self._pending.pop(req_id)
                    if not fut.done():
                        fut.set_result(msg)
                    continue
                if msg.get("msg_type") == "tick":
                    tick = msg.get("tick", {})
                    symbol = tick.get("symbol", "")
                    quote = float(tick.get("quote", 0))
                    epoch = int(tick.get("epoch", 0))
                    for handler in self._tick_handlers:
                        try:
                            handler(symbol, quote, epoch)
                        except Exception:
                            logger.exception("Tick handler error for %s", symbol)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("WebSocket listen loop failed")

    async def _send(self, payload: dict, timeout: float = 30.0) -> dict:
        if self._ws is None:
            raise RuntimeError("WebSocket not connected")
        req_id = self._next_id()
        payload = {**payload, "req_id": req_id}
        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[req_id] = fut
        await self._ws.send(json.dumps(payload))
        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            self._pending.pop(req_id, None)
            raise TimeoutError(f"Deriv API timeout for {payload}")

    async def authorize(self) -> dict:
        if not self.api_token:
            raise ValueError("DERIV_API_TOKEN is required")
        resp = await self._send({"authorize": self.api_token})
        if "error" in resp:
            raise RuntimeError(f"Deriv authorize failed: {resp['error']}")
        self._authorized = True
        auth = resp.get("authorize", {})
        self._balance = float(auth.get("balance", 0))
        logger.info("Authorized Deriv account balance=%.2f", self._balance)
        return auth

    @property
    def balance(self) -> float:
        return self._balance

    def on_tick(self, handler: Callable[[str, float, int], None]) -> None:
        self._tick_handlers.append(handler)

    async def subscribe_ticks(self, symbol: str) -> None:
        resp = await self._send({"ticks": symbol, "subscribe": 1})
        if "error" in resp:
            raise RuntimeError(f"Tick subscribe failed for {symbol}: {resp['error']}")
        logger.info("Subscribed to ticks: %s", symbol)

    async def unsubscribe_ticks(self, symbol: str) -> None:
        await self._send({"forget": symbol})

    async def get_candles_history(
        self,
        symbol: str,
        granularity: int,
        count: int = 200,
    ) -> List[dict]:
        """Fetch OHLC history from Deriv ticks_history API."""
        resp = await self._send(
            {
                "ticks_history": symbol,
                "adjust_start_time": 1,
                "count": count,
                "end": "latest",
                "granularity": granularity,
                "style": "candles",
            },
            timeout=60.0,
        )
        if "error" in resp:
            raise RuntimeError(f"History fetch failed for {symbol}: {resp['error']}")
        candles = resp.get("candles", [])
        return [
            {
                "epoch": c["epoch"],
                "open": float(c["open"]),
                "high": float(c["high"]),
                "low": float(c["low"]),
                "close": float(c["close"]),
                "volume": 0,
            }
            for c in candles
        ]

    async def buy_contract(
        self,
        symbol: str,
        contract_type: str,
        amount: float,
        duration: int,
        duration_unit: str,
        basis: str = "stake",
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
    ) -> dict:
        """Place a contract via proposal + buy flow."""
        proposal_payload: Dict[str, Any] = {
            "proposal": 1,
            "amount": amount,
            "basis": basis,
            "contract_type": contract_type,
            "currency": "USD",
            "duration": duration,
            "duration_unit": duration_unit,
            "symbol": symbol,
        }
        if stop_loss is not None:
            proposal_payload["limit_order"] = proposal_payload.get("limit_order", {})
            proposal_payload["limit_order"]["stop_loss"] = stop_loss
        if take_profit is not None:
            proposal_payload["limit_order"] = proposal_payload.get("limit_order", {})
            proposal_payload["limit_order"]["take_profit"] = take_profit

        proposal_resp = await self._send(proposal_payload)
        if "error" in proposal_resp:
            raise RuntimeError(f"Proposal failed: {proposal_resp['error']}")
        proposal = proposal_resp.get("proposal", {})
        proposal_id = proposal.get("id")
        if not proposal_id:
            raise RuntimeError("No proposal id returned")

        buy_resp = await self._send({"buy": proposal_id, "price": amount})
        if "error" in buy_resp:
            raise RuntimeError(f"Buy failed: {buy_resp['error']}")
        return buy_resp.get("buy", {})

    async def get_open_positions(self) -> List[dict]:
        resp = await self._send({"portfolio": 1})
        if "error" in resp:
            raise RuntimeError(f"Portfolio fetch failed: {resp['error']}")
        return resp.get("portfolio", {}).get("contracts", [])

    async def sell_contract(self, contract_id: int) -> dict:
        resp = await self._send({"sell": contract_id, "price": 0})
        if "error" in resp:
            raise RuntimeError(f"Sell failed: {resp['error']}")
        return resp.get("sell", {})
