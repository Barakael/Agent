"""Open position tracking and force-close."""

from __future__ import annotations

import logging
from typing import Callable, List, Optional

from data.deriv_ws import DerivWebSocketClient
from journal.writer import JournalWriter
from risk.gate import RiskGate

logger = logging.getLogger(__name__)


class PositionManager:
    def __init__(
        self,
        client: DerivWebSocketClient,
        journal: Optional[JournalWriter] = None,
        risk: Optional[RiskGate] = None,
        close_gate: Optional[Callable[..., bool]] = None,
    ) -> None:
        self.client = client
        self.journal = journal
        self.risk = risk
        self._close_gate = close_gate
        self._cached: List[dict] = []
        self._swing_contract_ids: set[int] = set()

    def mark_swing(self, contract_id: int) -> None:
        if contract_id:
            self._swing_contract_ids.add(int(contract_id))

    async def refresh(self) -> List[dict]:
        try:
            self._cached = await self.client.get_open_positions()
        except Exception:
            logger.exception("Failed to refresh positions")
        return self._cached

    @property
    def positions(self) -> List[dict]:
        return self._cached

    async def close_position(
        self,
        contract_id: int,
        *,
        force: bool = False,
        df=None,
    ) -> dict:
        pos = next((p for p in self._cached if p.get("contract_id") == contract_id), {})
        if self._close_gate and not force:
            allowed = await self._close_gate(pos, force_eod=force, df=df)
            if not allowed:
                raise RuntimeError(f"Close analysis rejected for contract {contract_id}")

        result = await self.client.sell_contract(contract_id)
        self._cached = [p for p in self._cached if p.get("contract_id") != contract_id]
        self._record_close_pnl(contract_id, pos, result)
        logger.info("Closed position contract_id=%s", contract_id)
        return result

    def _record_close_pnl(self, contract_id: int, pos: dict, result: dict) -> None:
        if not self.journal:
            return
        pnl = float(result.get("profit") or result.get("sold_for") or pos.get("profit") or 0)
        exit_price = float(result.get("sold_for") or pos.get("sell_price") or 0)
        trade_id = self.journal.get_open_trade_by_contract_id(str(contract_id))
        if trade_id:
            self.journal.log_trade_close(trade_id, exit_price, pnl)
        if self.risk:
            self.risk.record_pnl(pnl)

    async def close_all(
        self,
        *,
        force: bool = False,
        df_by_symbol: Optional[dict] = None,
        skip_swing: bool = False,
    ) -> List[dict]:
        await self.refresh()
        results = []
        for pos in list(self._cached):
            cid = pos.get("contract_id")
            if not cid:
                continue
            cid_int = int(cid)
            if skip_swing and cid_int in self._swing_contract_ids:
                logger.info("Keeping swing position contract_id=%s past session close", cid_int)
                continue
            symbol = pos.get("underlying") or pos.get("symbol") or ""
            df = (df_by_symbol or {}).get(symbol)
            try:
                results.append(await self.close_position(cid_int, force=force, df=df))
                self._swing_contract_ids.discard(cid_int)
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
