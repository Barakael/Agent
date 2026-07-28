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
        self.app_id = app_id or settings.deriv_ws_app_id
        self.api_token = api_token or settings.DERIV_API_TOKEN
        self.ws_url = ws_url or settings.DERIV_WS_URL
        self._ws: Optional[WebSocketClientProtocol] = None
        self._req_id = 0
        self._pending: Dict[int, asyncio.Future] = {}
        self._tick_handlers: List[Callable[[str, float, int], None]] = []
        self._authorized = False
        self._balance: float = 0.0
        self._loginid: str = ""
        self._is_demo: bool = False
        self._market_data_only: bool = False
        self._listen_task: Optional[asyncio.Task] = None
        # Reconnect backoff (seconds since epoch of next allowed attempt)
        self._reconnect_after: float = 0.0
        self._reconnect_backoff_sec: float = 30.0

    def _next_id(self) -> int:
        self._req_id += 1
        return self._req_id

    async def connect(self) -> None:
        logger.info("Connecting to Deriv WebSocket")
        self._ws = await websockets.connect(
            self.ws_url,
            ping_interval=20,
            ping_timeout=20,
            open_timeout=60,
            close_timeout=5,
        )
        self._listen_task = asyncio.create_task(self._listen())

    async def _reconnect(self, url: str) -> None:
        if self._listen_task:
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass
            self._listen_task = None
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None
        self.ws_url = url
        self._ws = await websockets.connect(
            url,
            ping_interval=20,
            ping_timeout=20,
            open_timeout=60,
            close_timeout=5,
        )
        self._listen_task = asyncio.create_task(self._listen())

    async def disconnect(self) -> None:
        if self._listen_task:
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass
            self._listen_task = None
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None
        self._authorized = False

    async def _listen(self) -> None:
        ws = self._ws
        assert ws is not None
        try:
            async for raw in ws:
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
        finally:
            # Only clear if this listener still owns the current socket (OTP reconnect
            # cancels the old listener after installing a new _ws — must not wipe it).
            if self._ws is ws:
                self._ws = None
                self._authorized = False

    def _uses_otp_auth(self) -> bool:
        token = str(self.api_token or "")
        is_pat = token.startswith("pat_")
        app_id = settings.DERIV_APP_ID.strip()
        is_new_app = bool(app_id) and not app_id.isdigit()
        return is_pat and is_new_app

    def _socket_alive(self) -> bool:
        if self._ws is None or not self._authorized:
            return False
        try:
            return not bool(getattr(self._ws, "closed", False))
        except Exception:
            return False

    def note_reconnect_success(self) -> None:
        self._reconnect_after = 0.0
        self._reconnect_backoff_sec = 30.0

    def note_reconnect_failure(self) -> float:
        """Record failure; return seconds to wait before next attempt."""
        import time as _time

        delay = self._reconnect_backoff_sec
        self._reconnect_after = _time.time() + delay
        self._reconnect_backoff_sec = min(delay * 2.0, 300.0)
        return delay

    def seconds_until_reconnect(self) -> float:
        import time as _time

        if self._reconnect_after <= 0:
            return 0.0
        return max(0.0, self._reconnect_after - _time.time())

    async def ensure_connected(self) -> dict:
        """Connect + authorize if the socket is missing or dead."""
        if self._socket_alive():
            return {"balance": self._balance, "loginid": self._loginid}

        wait = self.seconds_until_reconnect()
        if wait > 0:
            raise RuntimeError(f"Deriv reconnect backoff: retry in {wait:.0f}s")

        await self.disconnect()
        try:
            if self._uses_otp_auth():
                # OTP path fetches a fresh single-use URL and reconnects itself.
                # Do NOT open legacy app_id=1089 first — that often returns HTTP 401.
                result = await self.authorize()
            else:
                await self.connect()
                result = await self.authorize()
            self.note_reconnect_success()
            return result if result else {"balance": self._balance, "loginid": self._loginid}
        except Exception:
            self.note_reconnect_failure()
            raise

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

    async def _authorize_via_otp(self) -> dict:
        """New Deriv API: REST list accounts → OTP → authenticated WebSocket."""
        from data.deriv_rest import get_otp_websocket_url, list_accounts, pick_demo_account_id

        accounts = await list_accounts()
        account_id = pick_demo_account_id(accounts)
        if not account_id:
            raise RuntimeError("No Deriv account found for OTP auth")

        last_exc: Exception | None = None
        for attempt in range(1, 4):
            try:
                # OTP WebSocket URLs are typically single-use — refresh every attempt
                otp_url = await get_otp_websocket_url(account_id)
                logger.info(
                    "Deriv OTP WebSocket URL obtained for account %s (attempt %s)",
                    account_id,
                    attempt,
                )
                await self._reconnect(otp_url)
                last_exc = None
                break
            except Exception as exc:
                last_exc = exc
                logger.warning("OTP WebSocket connect attempt %s failed: %s", attempt, exc)
                await asyncio.sleep(1.5 * attempt)
        if last_exc is not None:
            # Restore public/legacy socket so callers are not left on a dead connection
            try:
                await self._reconnect(settings.DERIV_WS_URL)
            except Exception:
                pass
            raise last_exc

        self._authorized = True
        self._is_demo = "demo" in (self.ws_url or "").lower() or account_id.startswith(("DOT", "VRTC", "VRW", "VRT"))
        self._loginid = account_id
        self._market_data_only = False

        try:
            bal_resp = await self._send({"balance": 1})
            bal = bal_resp.get("balance", {})
            self._balance = float(bal.get("balance", 0))
        except Exception:
            logger.warning("Could not fetch balance on OTP WebSocket")

        logger.info(
            "Authorized via OTP account=%s demo=%s balance=%.2f",
            self._loginid,
            self._is_demo,
            self._balance,
        )
        return {"loginid": self._loginid, "balance": self._balance, "is_virtual": int(self._is_demo)}

    async def _authorize_legacy(self) -> dict:
        resp = await self._send({"authorize": self.api_token})
        if "error" in resp:
            raise RuntimeError(f"Deriv authorize failed: {resp['error']}")
        auth = self._apply_auth_response(resp.get("authorize", {}))

        require_demo = settings.DERIV_REQUIRE_DEMO and settings.TRADING_MODE != "live"
        if require_demo and auth.get("is_virtual", 0) != 1:
            demo_login = self._find_demo_loginid(auth)
            if demo_login:
                logger.info("Switching from live to demo account %s", demo_login)
                switch_resp = await self._send({"switch_account": demo_login})
                if "error" in switch_resp:
                    raise RuntimeError(
                        f"Live account connected but demo switch failed: {switch_resp['error']}. "
                        "Create a new PAT on developers.deriv.com and select the DEMO account."
                    )
                auth = self._apply_auth_response(switch_resp.get("authorize", auth))
            if auth.get("is_virtual", 0) != 1:
                raise RuntimeError(
                    f"Connected to LIVE account ({auth.get('loginid', 'unknown')}). "
                    "Use a demo token or set TRADING_MODE=live only for real trading."
                )

        self._authorized = True
        self._market_data_only = False
        logger.info(
            "Authorized Deriv account loginid=%s balance=%.2f demo=%s",
            self._loginid,
            self._balance,
            self._is_demo,
        )
        return auth

    async def authorize(self) -> dict:
        if not self.api_token:
            raise ValueError("DERIV_API_TOKEN is required")

        token = str(self.api_token)
        is_pat = token.startswith("pat_")
        # New developers.deriv.com apps use non-numeric App IDs (UUID or alphanumeric)
        is_new_app = bool(settings.DERIV_APP_ID.strip()) and not settings.DERIV_APP_ID.strip().isdigit()

        if is_pat and is_new_app:
            try:
                return await self._authorize_via_otp()
            except Exception as exc:
                logger.warning("OTP auth failed (%s), trying legacy WebSocket", exc)
                try:
                    await self._reconnect(settings.DERIV_WS_URL)
                except Exception:
                    logger.warning("Could not restore legacy WebSocket after OTP failure")

        try:
            return await self._authorize_legacy()
        except RuntimeError as exc:
            err_str = str(exc)
            if "InvalidToken" in err_str or "invalid" in err_str.lower():
                self._market_data_only = True
                self._authorized = False
                logger.warning(
                    "Token not valid on legacy WebSocket — using public market data. "
                    "Create a new token via home.deriv.com → Profile → API Management "
                    "(Trade + Account management scopes). See trading-engine/README.md"
                )
                return {}
            raise

    def _apply_auth_response(self, auth: dict) -> dict:
        self._balance = float(auth.get("balance", 0))
        self._loginid = str(auth.get("loginid", ""))
        self._is_demo = auth.get("is_virtual", 0) == 1
        return auth

    @staticmethod
    def _find_demo_loginid(auth: dict) -> Optional[str]:
        forced = (settings.DERIV_DEMO_LOGINID or "").strip()
        if forced:
            return forced
        for entry in auth.get("account_list", []) or []:
            if entry.get("is_virtual"):
                loginid = entry.get("loginid")
                if loginid:
                    return str(loginid)
        loginid = str(auth.get("loginid", ""))
        if loginid.startswith(("VRT", "VRW")):
            return loginid
        return None

    @property
    def loginid(self) -> str:
        return self._loginid

    @property
    def is_demo(self) -> bool:
        return self._is_demo

    @property
    def balance(self) -> float:
        return self._balance

    @property
    def market_data_only(self) -> bool:
        return self._market_data_only

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
        multiplier: Optional[float] = None,
    ) -> dict:
        """Place a contract via proposal + buy flow.

        New Options WebSocket schema uses ``underlying_symbol`` (legacy ``symbol``
        is rejected with InputValidationFailed). Multiplier contracts omit duration
        and support early ``sell``; binary CALL/PUT often cannot be resold.
        """
        proposal_payload: Dict[str, Any] = {
            "proposal": 1,
            "amount": amount,
            "basis": basis,
            "contract_type": contract_type,
            "currency": "USD",
            "underlying_symbol": symbol,
        }
        is_multiplier = contract_type in {"MULTUP", "MULTDOWN"} or multiplier is not None
        if is_multiplier:
            proposal_payload["multiplier"] = float(
                multiplier if multiplier is not None else settings.DERIV_MULTIPLIER
            )
        else:
            proposal_payload["duration"] = duration
            proposal_payload["duration_unit"] = duration_unit

        # limit_order is only valid for multipliers / accumulators on the new API.
        # For MULTUP/MULTDOWN these fields are USD P/L amounts (max 2 d.p.), not FX prices.
        if contract_type in {"MULTUP", "MULTDOWN", "ACCU"}:
            if stop_loss is not None:
                proposal_payload.setdefault("limit_order", {})["stop_loss"] = round(float(stop_loss), 2)
            if take_profit is not None:
                proposal_payload.setdefault("limit_order", {})["take_profit"] = round(float(take_profit), 2)

        proposal_resp = await self._send(proposal_payload)
        if "error" in proposal_resp:
            err = proposal_resp["error"]
            # Retry once with lowest allowed multiplier when Deriv rejects our value
            if (
                is_multiplier
                and isinstance(err, dict)
                and err.get("subcode") == "MultiplierOutOfRange"
                and err.get("code_args")
            ):
                raw = err["code_args"]
                if isinstance(raw, list) and raw:
                    allowed_str = str(raw[0])
                else:
                    allowed_str = str(raw)
                allowed = []
                for part in allowed_str.replace(" ", "").split(","):
                    try:
                        allowed.append(float(part))
                    except ValueError:
                        continue
                if allowed:
                    retry_mult = min(allowed)
                    logger.warning(
                        "Multiplier %s rejected for %s — retrying with %s (allowed %s)",
                        proposal_payload.get("multiplier"),
                        symbol,
                        retry_mult,
                        allowed_str,
                    )
                    proposal_payload["multiplier"] = retry_mult
                    proposal_resp = await self._send(proposal_payload)
                    if "error" not in proposal_resp:
                        err = None
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

    async def get_contract(self, contract_id: int) -> dict:
        """Fetch open or recently closed contract details (profit / sell_price)."""
        resp = await self._send(
            {"proposal_open_contract": 1, "contract_id": int(contract_id)},
            timeout=30.0,
        )
        if "error" in resp:
            raise RuntimeError(f"Contract fetch failed for {contract_id}: {resp['error']}")
        return resp.get("proposal_open_contract", {}) or {}

    async def get_profit_table(self, limit: int = 50) -> List[dict]:
        """Recent closed contracts with buy/sell/profit (for journal reconcile)."""
        resp = await self._send(
            {
                "profit_table": 1,
                "description": 1,
                "limit": int(limit),
                "sort": "DESC",
            },
            timeout=45.0,
        )
        if "error" in resp:
            raise RuntimeError(f"Profit table failed: {resp['error']}")
        return list(resp.get("profit_table", {}).get("transactions", []) or [])

    async def sell_contract(self, contract_id: int) -> dict:
        resp = await self._send({"sell": contract_id, "price": 0})
        if "error" in resp:
            raise RuntimeError(f"Sell failed: {resp['error']}")
        return resp.get("sell", {})
