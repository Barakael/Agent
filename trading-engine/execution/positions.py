"""Open position tracking and force-close."""

from __future__ import annotations

import logging
from typing import List

from data.deriv_ws import DerivWebSocketClient

logger = logging.getLogger(__name__)


class PositionManager:
    def __init__(self, client: DerivWebSocketClient) -> None:
        self.client = client
        self._cached: List[dict] = []

    async def refresh(self) -> List[dict]:
        try:
            self._cached = await self.client.get_open_positions()
        except Exception:
            logger.exception("Failed to refresh positions")
        return self._cached

    @property
    def positions(self) -> List[dict]:
        return self._cached

    async def close_position(self, contract_id: int) -> dict:
        result = await self.client.sell_contract(contract_id)
        self._cached = [p for p in self._cached if p.get("contract_id") != contract_id]
        logger.info("Closed position contract_id=%s", contract_id)
        return result

    async def close_all(self) -> List[dict]:
        await self.refresh()
        results = []
        for pos in self._cached:
            cid = pos.get("contract_id")
            if cid:
                try:
                    results.append(await self.close_position(int(cid)))
                except Exception:
                    logger.exception("Failed to close contract %s", cid)
        return results

    def to_api_list(self) -> List[dict]:
        return [
            {
                "contract_id": p.get("contract_id"),
                "symbol": p.get("underlying") or p.get("symbol"),
                "contract_type": p.get("contract_type"),
                "buy_price": p.get("buy_price"),
                "profit": p.get("profit"),
                "date_start": p.get("date_start"),
            }
            for p in self._cached
        ]
