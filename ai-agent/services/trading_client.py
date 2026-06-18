"""HTTP client for trading-engine supervision from ai-agent."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import httpx

from config import settings

logger = logging.getLogger(__name__)


class TradingClient:
    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
    ) -> None:
        self.base_url = (base_url or settings.TRADING_ENGINE_URL).rstrip("/")
        self.api_key = api_key or settings.TRADING_SERVICE_API_KEY

    def _headers(self) -> dict:
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _request(self, method: str, path: str, **kwargs) -> Dict[str, Any]:
        with httpx.Client(timeout=30.0) as client:
            resp = client.request(
                method,
                f"{self.base_url}{path}",
                headers=self._headers(),
                **kwargs,
            )
            resp.raise_for_status()
            return resp.json()

    def status(self) -> Dict[str, Any]:
        return self._request("GET", "/status")

    def pause(self) -> Dict[str, Any]:
        return self._request("POST", "/pause")

    def resume(self) -> Dict[str, Any]:
        return self._request("POST", "/resume")

    def metrics(self) -> Dict[str, Any]:
        return self._request("GET", "/metrics")

    def positions(self) -> Dict[str, Any]:
        return self._request("GET", "/positions")

    def close_all(self) -> Dict[str, Any]:
        return self._request("POST", "/positions/close-all")

    def health(self) -> bool:
        try:
            self._request("GET", "/health")
            return True
        except Exception:
            return False
