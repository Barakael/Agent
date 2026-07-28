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
        self._profit_table_cache: dict[str, dict] = {}

    def mark_swing(self, contract_id: int) -> None:
        if contract_id:
            self._swing_contract_ids.add(int(contract_id))

    async def refresh(self) -> List[dict]:
        try:
            self._cached = await self.client.get_open_positions()
        except Exception:
            logger.exception("Failed to refresh positions")
            return self._cached
        try:
            await self.reconcile_closed_journal()
        except Exception:
            logger.exception("Failed to reconcile closed journal trades")
        return self._cached

    @property
    def positions(self) -> List[dict]:
        return self._cached

    async def _load_profit_table(self) -> dict[str, dict]:
        if self._profit_table_cache:
            return self._profit_table_cache
        try:
            rows = await self.client.get_profit_table(limit=100)
        except Exception:
            logger.warning("Profit table unavailable for reconcile", exc_info=True)
            rows = []
        cache: dict[str, dict] = {}
        for row in rows:
            cid = row.get("contract_id")
            if cid is not None:
                cache[str(cid)] = row
        self._profit_table_cache = cache
        return cache

    async def reconcile_closed_journal(self) -> int:
        """Mark journal opens closed when Deriv portfolio no longer lists them (SL/TP)."""
        if not self.journal:
            return 0
        open_rows = self.journal.list_open_trades_with_contracts(max_age_hours=48)
        if not open_rows:
            return 0
        live_ids = {
            str(p.get("contract_id"))
            for p in self._cached
            if p.get("contract_id") is not None
        }
        missing = [r for r in open_rows if r["contract_id"] not in live_ids]
        if not missing:
            return 0

        # Refresh profit table once per reconcile batch
        self._profit_table_cache = {}
        await self._load_profit_table()

        closed_n = 0
        for row in missing:
            cid = row["contract_id"]
            try:
                cid_int = int(cid)
            except (TypeError, ValueError):
                continue
            sold_for, pnl, trusted = await self._resolve_close_amounts(
                cid_int, stake=row["stake"]
            )
            self.journal.log_trade_close(int(row["id"]), sold_for, pnl)
            # Only apply PnL to risk when Deriv returned real numbers (avoid kill-switch from guesses)
            if trusted and self.risk:
                self.risk.record_pnl(pnl)
            self._swing_contract_ids.discard(cid_int)
            closed_n += 1
            logger.info(
                "Reconciled auto-close contract_id=%s sold_for=%.2f pnl=%+.2f trusted=%s",
                cid,
                sold_for,
                pnl,
                trusted,
            )
        return closed_n

    async def _resolve_close_amounts(
        self, contract_id: int, *, stake: float = 0.0
    ) -> tuple[float, float, bool]:
        """Return (sold_for, pnl, trusted) for a contract no longer in the open portfolio."""
        # Prefer profit_table (reliable for closed contracts)
        pt = (await self._load_profit_table()).get(str(contract_id))
        if pt:
            buy = float(pt.get("buy_price") or stake or 0)
            sold_for = float(pt.get("sell_price") or pt.get("sold_for") or 0)
            if pt.get("profit") is not None:
                pnl = float(pt["profit"])
            else:
                pnl = sold_for - buy
            if sold_for <= 0 and buy:
                sold_for = max(0.0, buy + pnl)
            return round(sold_for, 2), round(pnl, 2), True

        try:
            detail = await self.client.get_contract(contract_id)
        except Exception:
            logger.warning(
                "Could not fetch closed contract %s — closing journal without risk PnL",
                contract_id,
                exc_info=True,
            )
            # Unknown outcome: mark closed with zero cash, do not poison daily PnL
            return 0.0, 0.0, False

        sold_for = float(detail.get("sell_price") or detail.get("sold_for") or 0)
        buy = float(detail.get("buy_price") or stake or 0)
        if detail.get("profit") is not None:
            pnl = float(detail["profit"])
            trusted = True
        elif sold_for > 0 or buy > 0:
            pnl = sold_for - buy
            trusted = sold_for > 0
        else:
            return 0.0, 0.0, False
        if sold_for <= 0 and buy:
            sold_for = max(0.0, buy + pnl)
        return round(sold_for, 2), round(pnl, 2), trusted

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
        sold_for = float(result.get("sold_for") or result.get("sell_price") or 0)
        buy = float(pos.get("buy_price") or 0)
        if result.get("profit") is not None:
            pnl = float(result["profit"])
        else:
            pnl = sold_for - buy if (sold_for or buy) else 0.0
        if sold_for <= 0 and buy:
            sold_for = max(0.0, buy + pnl)
        trade_id = self.journal.get_open_trade_by_contract_id(str(contract_id))
        if trade_id:
            self.journal.log_trade_close(trade_id, round(sold_for, 2), round(pnl, 2))
        if self.risk:
            self.risk.record_pnl(round(pnl, 2))

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
