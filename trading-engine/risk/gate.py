"""Risk management gate — every signal must pass before becoming an order."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from config import settings
from signals.engine import SignalDirection, TradeSignal

logger = logging.getLogger(__name__)

# Pip sizes per symbol (approximate for position sizing)
PIP_SIZE = {
    "frxEURUSD": 0.0001,
    "frxGBPUSD": 0.0001,
    "frxAUDUSD": 0.0001,
    "frxUSDJPY": 0.01,
}


class RiskDecision(str, Enum):
    APPROVED = "approved"
    REJECTED = "rejected"


@dataclass
class RiskCheckResult:
    decision: RiskDecision
    reason: str
    stake: float = 0.0
    stop_loss_price: float = 0.0
    take_profit_price: float = 0.0
    stop_loss_pips: int = 0
    take_profit_pips: int = 0

    def to_dict(self) -> dict:
        return {
            "decision": self.decision.value,
            "reason": self.reason,
            "stake": self.stake,
            "stop_loss_price": self.stop_loss_price,
            "take_profit_price": self.take_profit_price,
            "stop_loss_pips": self.stop_loss_pips,
            "take_profit_pips": self.take_profit_pips,
        }


class RiskGate:
    """Non-negotiable risk controls before any order."""

    def __init__(self) -> None:
        self.risk_percent = settings.RISK_PERCENT_PER_TRADE
        self.daily_limit_percent = settings.DAILY_DRAWDOWN_LIMIT_PERCENT
        self.default_sl_pips = settings.DEFAULT_SL_PIPS
        self.default_tp_pips = settings.DEFAULT_TP_PIPS
        self._daily_pnl: float = 0.0
        self._session_start_balance: float = 0.0
        self._kill_switch_active: bool = False

    def reset_session(self, balance: float) -> None:
        self._daily_pnl = 0.0
        self._session_start_balance = balance
        self._kill_switch_active = False
        logger.info("Risk session reset balance=%.2f", balance)

    def record_pnl(self, pnl: float) -> None:
        self._daily_pnl += pnl
        if self._session_start_balance > 0:
            drawdown_pct = abs(min(0, self._daily_pnl)) / self._session_start_balance * 100
            if drawdown_pct >= self.daily_limit_percent:
                self._kill_switch_active = True
                logger.warning(
                    "Daily kill switch triggered: drawdown %.2f%% >= %.2f%%",
                    drawdown_pct,
                    self.daily_limit_percent,
                )

    def trigger_kill_switch(self, reason: str = "manual") -> None:
        self._kill_switch_active = True
        logger.warning("Kill switch activated: %s", reason)

    @property
    def kill_switch_active(self) -> bool:
        return self._kill_switch_active

    @property
    def daily_pnl(self) -> float:
        return self._daily_pnl

    def _pip_size(self, symbol: str) -> float:
        return PIP_SIZE.get(symbol, 0.0001)

    def calculate_stake(self, balance: float, sl_pips: int, symbol: str) -> float:
        """Position size from fixed % risk — never flat lot size."""
        if sl_pips <= 0 or balance <= 0:
            return 0.0
        risk_amount = balance * (self.risk_percent / 100.0)
        pip_value_per_unit = self._pip_size(symbol) * 10  # simplified for Deriv stake
        if pip_value_per_unit <= 0:
            return 0.0
        stake = risk_amount / (sl_pips * pip_value_per_unit)
        return max(1.0, round(stake, 2))

    def calculate_sl_tp_prices(
        self,
        signal: TradeSignal,
        sl_pips: Optional[int] = None,
        tp_pips: Optional[int] = None,
    ) -> tuple[float, float, int, int]:
        sl_pips = sl_pips or self.default_sl_pips
        tp_pips = tp_pips or self.default_tp_pips
        pip = self._pip_size(signal.symbol)
        price = signal.price

        if signal.direction == SignalDirection.BUY:
            sl = price - sl_pips * pip
            tp = price + tp_pips * pip
        else:
            sl = price + sl_pips * pip
            tp = price - tp_pips * pip
        return sl, tp, sl_pips, tp_pips

    def evaluate(
        self,
        signal: TradeSignal,
        balance: float,
        trading_paused: bool = False,
        news_paused: bool = False,
        sl_pips: Optional[int] = None,
        tp_pips: Optional[int] = None,
    ) -> RiskCheckResult:
        if self._kill_switch_active:
            return RiskCheckResult(
                decision=RiskDecision.REJECTED,
                reason="Daily kill switch active",
            )
        if trading_paused:
            return RiskCheckResult(
                decision=RiskDecision.REJECTED,
                reason="Trading paused by operator",
            )
        if news_paused:
            return RiskCheckResult(
                decision=RiskDecision.REJECTED,
                reason="News blackout window",
            )
        if balance <= 0:
            return RiskCheckResult(
                decision=RiskDecision.REJECTED,
                reason="Insufficient balance",
            )

        sl, tp, sl_pips_used, tp_pips_used = self.calculate_sl_tp_prices(
            signal, sl_pips, tp_pips
        )
        if sl <= 0 or tp <= 0:
            return RiskCheckResult(
                decision=RiskDecision.REJECTED,
                reason="Invalid SL/TP calculation",
            )

        stake = self.calculate_stake(balance, sl_pips_used, signal.symbol)
        if stake <= 0:
            return RiskCheckResult(
                decision=RiskDecision.REJECTED,
                reason="Stake calculation failed",
            )

        return RiskCheckResult(
            decision=RiskDecision.APPROVED,
            reason="Risk checks passed",
            stake=stake,
            stop_loss_price=sl,
            take_profit_price=tp,
            stop_loss_pips=sl_pips_used,
            take_profit_pips=tp_pips_used,
        )

    def validate_manual_order(
        self,
        stop_loss: float,
        take_profit: float,
        stake: float,
    ) -> RiskCheckResult:
        """Manual orders must also have SL and TP."""
        if stop_loss <= 0 or take_profit <= 0:
            return RiskCheckResult(
                decision=RiskDecision.REJECTED,
                reason="Manual order requires stop_loss and take_profit",
            )
        if stake <= 0:
            return RiskCheckResult(
                decision=RiskDecision.REJECTED,
                reason="Invalid stake amount",
            )
        if self._kill_switch_active:
            return RiskCheckResult(
                decision=RiskDecision.REJECTED,
                reason="Daily kill switch active",
            )
        return RiskCheckResult(
            decision=RiskDecision.APPROVED,
            reason="Manual order validated",
            stake=stake,
            stop_loss_price=stop_loss,
            take_profit_price=take_profit,
        )
