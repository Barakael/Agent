"""Persist every trading decision with reconstructable context."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from journal.models import AnalysisRun, BotState, SignalLog, TradeJournal, TradingSession, init_db
from risk.gate import RiskCheckResult
from signals.engine import TradeSignal

logger = logging.getLogger(__name__)


class JournalWriter:
    def __init__(self) -> None:
        self.Session = init_db()

    def log_signal(
        self,
        signal: TradeSignal,
        risk: Optional[RiskCheckResult] = None,
    ) -> int:
        with self.Session() as session:
            entry = SignalLog(
                symbol=signal.symbol,
                direction=signal.direction.value,
                rsi=signal.rsi,
                macd=signal.macd,
                price=signal.price,
                epoch=signal.epoch,
                reason=signal.reason,
                risk_decision=risk.decision.value if risk else None,
                risk_reason=risk.reason if risk else None,
            )
            session.add(entry)
            session.commit()
            return entry.id

    def log_trade_open(
        self,
        signal: TradeSignal,
        risk: RiskCheckResult,
        contract_id: Optional[str] = None,
        mode: str = "log_only",
    ) -> int:
        with self.Session() as session:
            trade = TradeJournal(
                symbol=signal.symbol,
                direction=signal.direction.value,
                entry_price=signal.price,
                stake=risk.stake,
                stop_loss=risk.stop_loss_price,
                take_profit=risk.take_profit_price,
                signal_source="rsi_macd_confluence",
                rsi_at_entry=signal.rsi,
                macd_at_entry=signal.macd,
                contract_id=str(contract_id) if contract_id else None,
                status="open",
                mode=mode,
                reason=signal.reason,
            )
            session.add(trade)
            session.commit()
            return trade.id

    def log_signal_rejected(self, signal: TradeSignal, reason: str) -> int:
        with self.Session() as session:
            entry = SignalLog(
                symbol=signal.symbol,
                direction=signal.direction.value,
                rsi=signal.rsi,
                macd=signal.macd,
                price=signal.price,
                epoch=signal.epoch,
                reason=f"REJECTED: {reason} | {signal.reason}",
                risk_decision="rejected",
                risk_reason=reason,
            )
            session.add(entry)
            session.commit()
            return entry.id

    def log_analysis_run(self, snapshot) -> int:
        with self.Session() as session:
            row = AnalysisRun(
                run_type=snapshot.run_type,
                symbol=snapshot.symbol,
                passed=snapshot.passed,
                decision=snapshot.decision,
                reasons=json.dumps(snapshot.reasons),
                sources=json.dumps(snapshot.sources, default=str),
            )
            session.add(row)
            session.commit()
            return row.id

    def get_latest_preflight(self) -> Optional[dict]:
        with self.Session() as session:
            row = (
                session.query(AnalysisRun)
                .filter(AnalysisRun.run_type == "preflight")
                .order_by(AnalysisRun.created_at.desc())
                .first()
            )
            if not row:
                return None
            return {
                "id": row.id,
                "passed": row.passed,
                "decision": row.decision,
                "reasons": json.loads(row.reasons or "[]"),
                "sources": json.loads(row.sources or "{}"),
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }

    def get_open_trade_by_contract_id(self, contract_id: str) -> Optional[int]:
        with self.Session() as session:
            row = (
                session.query(TradeJournal)
                .filter(
                    TradeJournal.contract_id == str(contract_id),
                    TradeJournal.status == "open",
                )
                .order_by(TradeJournal.created_at.desc())
                .first()
            )
            return row.id if row else None

    def log_trade_close(self, trade_id: int, exit_price: float, pnl: float) -> None:
        with self.Session() as session:
            trade = session.get(TradeJournal, trade_id)
            if trade:
                trade.exit_price = exit_price
                trade.pnl = pnl
                trade.status = "closed"
                trade.closed_at = datetime.now(timezone.utc)
                session.commit()

    def update_bot_state(self, state: str, mode: str, daily_pnl: float) -> None:
        with self.Session() as session:
            row = session.query(BotState).first()
            if row is None:
                row = BotState()
                session.add(row)
            row.state = state
            row.mode = mode
            row.daily_pnl = daily_pnl
            row.last_heartbeat = datetime.now(timezone.utc)
            session.commit()

    def get_bot_state(self) -> dict:
        with self.Session() as session:
            row = session.query(BotState).first()
            if row is None:
                return {
                    "state": "stopped",
                    "mode": "log_only",
                    "daily_pnl": 0.0,
                    "last_heartbeat": None,
                }
            return {
                "state": row.state,
                "mode": row.mode,
                "daily_pnl": row.daily_pnl,
                "last_heartbeat": row.last_heartbeat.isoformat() if row.last_heartbeat else None,
            }

    def get_trades(self, limit: int = 50, offset: int = 0) -> list[dict]:
        with self.Session() as session:
            rows = (
                session.query(TradeJournal)
                .order_by(TradeJournal.created_at.desc())
                .offset(offset)
                .limit(limit)
                .all()
            )
            return [
                {
                    "id": r.id,
                    "symbol": r.symbol,
                    "direction": r.direction,
                    "entry_price": r.entry_price,
                    "exit_price": r.exit_price,
                    "stake": r.stake,
                    "stop_loss": r.stop_loss,
                    "take_profit": r.take_profit,
                    "pnl": r.pnl,
                    "status": r.status,
                    "mode": r.mode,
                    "reason": r.reason,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in rows
            ]
