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
                strategy_id=getattr(signal, "strategy_id", None),
                confidence=getattr(signal, "confidence", None),
                market_condition=getattr(signal, "market_condition", None),
                score_breakdown=json.dumps(getattr(signal, "score_breakdown", None) or {}),
            )
            session.add(entry)
            session.commit()
            return entry.id

    def log_no_trade(
        self,
        symbol: str,
        price: float,
        epoch: int,
        regime: str,
        reason: str,
        evaluations: Optional[list] = None,
        rsi: float = 0.0,
        macd: float = 0.0,
    ) -> int:
        """Log intentional No Trade / skip so Phase 3 can analyse missed setups."""
        with self.Session() as session:
            breakdown = {}
            if evaluations:
                breakdown = {
                    "evaluations": [
                        {
                            "strategy_id": getattr(e, "strategy_id", None),
                            "direction": getattr(getattr(e, "direction", None), "value", str(getattr(e, "direction", ""))),
                            "confidence": getattr(e, "confidence", 0),
                            "reasons": getattr(e, "reasons", []),
                        }
                        for e in evaluations
                    ]
                }
            entry = SignalLog(
                symbol=symbol,
                direction="none",
                rsi=rsi,
                macd=macd,
                price=price,
                epoch=epoch,
                reason=f"NO_TRADE: {reason}",
                risk_decision="skipped",
                risk_reason=reason,
                strategy_id=None,
                confidence=0.0,
                market_condition=regime,
                score_breakdown=json.dumps(breakdown),
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
        stop_loss_usd: Optional[float] = None,
        take_profit_usd: Optional[float] = None,
    ) -> int:
        from execution.orders import usd_limit_from_risk

        if stop_loss_usd is None or take_profit_usd is None:
            computed_sl, computed_tp = usd_limit_from_risk(risk)
            stop_loss_usd = stop_loss_usd if stop_loss_usd is not None else computed_sl
            take_profit_usd = take_profit_usd if take_profit_usd is not None else computed_tp

        with self.Session() as session:
            trade = TradeJournal(
                symbol=signal.symbol,
                direction=signal.direction.value,
                entry_price=signal.price,
                stake=risk.stake,
                stop_loss=risk.stop_loss_price,
                take_profit=risk.take_profit_price,
                stop_loss_usd=stop_loss_usd,
                take_profit_usd=take_profit_usd,
                signal_source=getattr(signal, "strategy_id", None) or "rsi_macd_confluence",
                rsi_at_entry=signal.rsi,
                macd_at_entry=signal.macd,
                contract_id=str(contract_id) if contract_id else None,
                status="open",
                mode=mode,
                reason=(
                    f"[{getattr(signal, 'trade_mode', 'pattern')}/{getattr(signal, 'hold_policy', 'intraday')}] "
                    f"{signal.reason}"
                ),
                confidence=getattr(signal, "confidence", None),
                market_condition=getattr(signal, "market_condition", None),
                score_breakdown=json.dumps(getattr(signal, "score_breakdown", None) or {}),
                sl_tp_method=getattr(risk, "sl_tp_method", None)
                or getattr(signal, "sl_tp_method", None),
            )
            session.add(trade)
            session.commit()
            logger.info(
                "Journal open %s stake=%.2f price_sl=%.5f price_tp=%.5f "
                "usd_sl=%.2f usd_tp=%.2f method=%s conf=%s",
                signal.symbol,
                risk.stake,
                risk.stop_loss_price,
                risk.take_profit_price,
                stop_loss_usd or 0,
                take_profit_usd or 0,
                trade.sl_tp_method,
                getattr(signal, "confidence", None),
            )
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
                strategy_id=getattr(signal, "strategy_id", None),
                confidence=getattr(signal, "confidence", None),
                market_condition=getattr(signal, "market_condition", None),
                score_breakdown=json.dumps(getattr(signal, "score_breakdown", None) or {}),
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
            return [self._trade_row(r) for r in rows]

    def get_day_review_payload(self, day: Optional[str] = None) -> dict:
        """Internal/debug day review (may include row-level detail). Not for OpenAI."""
        day = day or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        start = datetime.fromisoformat(f"{day}T00:00:00+00:00")
        end = datetime.fromisoformat(f"{day}T23:59:59.999999+00:00")
        with self.Session() as session:
            trades = (
                session.query(TradeJournal)
                .filter(TradeJournal.created_at >= start, TradeJournal.created_at <= end)
                .all()
            )
            signals = (
                session.query(SignalLog)
                .filter(SignalLog.created_at >= start, SignalLog.created_at <= end)
                .all()
            )

        closed = [t for t in trades if t.status == "closed"]
        by_strategy: dict[str, dict] = {}
        by_regime: dict[str, dict] = {}
        for t in closed:
            sid = t.signal_source or "unknown"
            bucket = by_strategy.setdefault(sid, {"trades": 0, "wins": 0, "pnl": 0.0, "losses": 0})
            bucket["trades"] += 1
            bucket["pnl"] += float(t.pnl or 0)
            if (t.pnl or 0) > 0:
                bucket["wins"] += 1
            elif (t.pnl or 0) < 0:
                bucket["losses"] += 1

            regime = t.market_condition or "unknown"
            rb = by_regime.setdefault(regime, {"trades": 0, "pnl": 0.0})
            rb["trades"] += 1
            rb["pnl"] += float(t.pnl or 0)

        skips = [s for s in signals if (s.risk_decision or "") in ("skipped",) or (s.reason or "").startswith("NO_TRADE")]
        rejects = [s for s in signals if s.risk_decision == "rejected"]

        sl_distances = []
        for t in closed:
            if t.entry_price and t.stop_loss:
                sl_distances.append(abs(t.entry_price - t.stop_loss))

        return {
            "date": day,
            "summary": {
                "trades_opened": len(trades),
                "trades_closed": len(closed),
                "total_pnl": round(sum(float(t.pnl or 0) for t in closed), 2),
                "wins": sum(1 for t in closed if (t.pnl or 0) > 0),
                "losses": sum(1 for t in closed if (t.pnl or 0) < 0),
                "skips": len(skips),
                "risk_rejects": len(rejects),
                "avg_sl_distance": round(sum(sl_distances) / len(sl_distances), 6) if sl_distances else None,
            },
            "by_strategy": by_strategy,
            "by_regime": by_regime,
            "trades": [self._trade_row(t) for t in trades],
            "skips": [
                {
                    "symbol": s.symbol,
                    "price": s.price,
                    "reason": s.reason,
                    "market_condition": s.market_condition,
                    "created_at": s.created_at.isoformat() if s.created_at else None,
                }
                for s in skips[:100]
            ],
            "rejects": [
                {
                    "symbol": s.symbol,
                    "reason": s.risk_reason or s.reason,
                    "strategy_id": s.strategy_id,
                    "confidence": s.confidence,
                }
                for s in rejects[:50]
            ],
        }

    def get_evening_ai_payload(self, day: Optional[str] = None) -> dict:
        """Privacy-safe aggregates for OpenAI — no prices, stakes, contracts, or reasons."""
        day = day or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        start = datetime.fromisoformat(f"{day}T00:00:00+00:00")
        end = datetime.fromisoformat(f"{day}T23:59:59.999999+00:00")
        with self.Session() as session:
            trades = (
                session.query(TradeJournal)
                .filter(TradeJournal.created_at >= start, TradeJournal.created_at <= end)
                .all()
            )
            signals = (
                session.query(SignalLog)
                .filter(SignalLog.created_at >= start, SignalLog.created_at <= end)
                .all()
            )

        closed = [t for t in trades if t.status == "closed"]
        skips = [
            s
            for s in signals
            if (s.risk_decision or "") == "skipped" or (s.reason or "").startswith("NO_TRADE")
        ]
        rejects = [s for s in signals if s.risk_decision == "rejected"]

        def _pip(symbol: str) -> float:
            return 0.01 if "JPY" in (symbol or "").upper() else 0.0001

        def _bucket_stats(rows: list) -> dict:
            n = len(rows)
            if n == 0:
                return {"trades": 0, "win_rate_pct": 0.0, "avg_pnl": 0.0}
            wins = sum(1 for t in rows if (t.pnl or 0) > 0)
            avg_pnl = sum(float(t.pnl or 0) for t in rows) / n
            return {
                "trades": n,
                "win_rate_pct": round(100.0 * wins / n, 1),
                "avg_pnl": round(avg_pnl, 2),
            }

        by_strategy: dict[str, list] = {}
        by_regime: dict[str, list] = {}
        by_hour: dict[str, list] = {}
        confidences: list[float] = []
        sl_pips: list[float] = []
        tp_pips: list[float] = []

        for t in closed:
            sid = t.signal_source or "unknown"
            by_strategy.setdefault(sid, []).append(t)
            regime = t.market_condition or "unknown"
            by_regime.setdefault(regime, []).append(t)
            ts = t.created_at
            if ts is not None:
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                hour = ts.astimezone(timezone.utc).strftime("%H")
                by_hour.setdefault(hour, []).append(t)
            if getattr(t, "confidence", None) is not None:
                confidences.append(float(t.confidence))
            pip = _pip(t.symbol)
            if t.entry_price and t.stop_loss:
                sl_pips.append(abs(float(t.entry_price) - float(t.stop_loss)) / pip)
            if t.entry_price and t.take_profit:
                tp_pips.append(abs(float(t.take_profit) - float(t.entry_price)) / pip)

        # Also fold signal confidence when trade confidence missing
        if not confidences:
            for s in signals:
                if s.confidence is not None and s.direction != "none":
                    confidences.append(float(s.confidence))

        n_closed = len(closed)
        wins = sum(1 for t in closed if (t.pnl or 0) > 0)
        total_pnl = sum(float(t.pnl or 0) for t in closed)

        return {
            "date": day,
            "summary": {
                "trades_opened": len(trades),
                "trades_closed": n_closed,
                "win_rate_pct": round(100.0 * wins / n_closed, 1) if n_closed else 0.0,
                "avg_pnl_per_trade": round(total_pnl / n_closed, 2) if n_closed else 0.0,
                "skips": len(skips),
                "risk_rejects": len(rejects),
                "avg_confidence": round(sum(confidences) / len(confidences), 1) if confidences else None,
                "avg_sl_distance_pips": round(sum(sl_pips) / len(sl_pips), 1) if sl_pips else None,
                "avg_tp_distance_pips": round(sum(tp_pips) / len(tp_pips), 1) if tp_pips else None,
            },
            "by_strategy": {k: _bucket_stats(v) for k, v in sorted(by_strategy.items())},
            "by_regime": {k: _bucket_stats(v) for k, v in sorted(by_regime.items())},
            "by_hour_utc": {k: _bucket_stats(v) for k, v in sorted(by_hour.items())},
        }

    @staticmethod
    def _trade_row(r: TradeJournal) -> dict:
        breakdown = None
        if getattr(r, "score_breakdown", None):
            try:
                breakdown = json.loads(r.score_breakdown)
            except Exception:
                breakdown = r.score_breakdown
        return {
            "id": r.id,
            "symbol": r.symbol,
            "direction": r.direction,
            "entry_price": r.entry_price,
            "exit_price": r.exit_price,
            "stake": r.stake,
            "stop_loss": r.stop_loss,
            "take_profit": r.take_profit,
            "stop_loss_usd": getattr(r, "stop_loss_usd", None),
            "take_profit_usd": getattr(r, "take_profit_usd", None),
            "pnl": r.pnl,
            "status": r.status,
            "mode": r.mode,
            "reason": r.reason,
            "signal_source": r.signal_source,
            "confidence": getattr(r, "confidence", None),
            "market_condition": getattr(r, "market_condition", None),
            "score_breakdown": breakdown,
            "sl_tp_method": getattr(r, "sl_tp_method", None),
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "closed_at": r.closed_at.isoformat() if r.closed_at else None,
        }
