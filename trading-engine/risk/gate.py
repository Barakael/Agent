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

# Pip / point sizes per symbol (for fixed-pip fallback and distance stats)
PIP_SIZE = {
    "frxEURUSD": 0.0001,
    "frxGBPUSD": 0.0001,
    "frxAUDUSD": 0.0001,
    "frxUSDCAD": 0.0001,
    "frxUSDCHF": 0.0001,
    "frxNZDUSD": 0.0001,
    "frxUSDJPY": 0.01,
    "frxEURJPY": 0.01,
    "frxGBPJPY": 0.01,
    # Metals quote to fewer decimals than currency pairs
    "frxXAUUSD": 0.01,
    "frxXAGUSD": 0.001,
    # Synthetic Volatility Indices
    "R_10": 0.001,
    "R_25": 0.001,
    "R_50": 0.01,
    "R_75": 0.01,
    "R_100": 0.01,
}


def pip_size(symbol: str) -> float:
    """Point size for a symbol.

    Falls back to the quote-currency convention rather than a flat default,
    because assuming 0.0001 on a JPY pair understates distances a hundredfold
    and does so silently.
    """
    if symbol in PIP_SIZE:
        return PIP_SIZE[symbol]
    s = (symbol or "").upper()
    if s.startswith("FRX"):
        if s.endswith("JPY"):
            return 0.01
        if "XAU" in s:
            return 0.01
        if "XAG" in s:
            return 0.001
        return 0.0001
    return 0.0001


def is_synthetic_symbol(symbol: str) -> bool:
    """Deriv synthetics ignore macro news and trade 24/7."""
    s = (symbol or "").upper()
    return s.startswith("R_") or s.startswith("1HZ")


def is_forex_symbol(symbol: str) -> bool:
    """Deriv forex and metals: real market prices, and closed at weekends."""
    return (symbol or "").upper().startswith("FRX")


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
    sl_tp_method: str = "fixed_pips"

    def to_dict(self) -> dict:
        return {
            "decision": self.decision.value,
            "reason": self.reason,
            "stake": self.stake,
            "stop_loss_price": self.stop_loss_price,
            "take_profit_price": self.take_profit_price,
            "stop_loss_pips": self.stop_loss_pips,
            "take_profit_pips": self.take_profit_pips,
            "sl_tp_method": self.sl_tp_method,
        }


class RiskGate:
    """Non-negotiable risk controls before any order. Strategies never set stake."""

    def __init__(self) -> None:
        self.risk_percent = settings.RISK_PERCENT_PER_TRADE
        self.daily_limit_percent = settings.DAILY_DRAWDOWN_LIMIT_PERCENT
        self.max_daily_profit_percent = settings.MAX_DAILY_PROFIT_PERCENT
        self.max_trades_per_day = settings.MAX_TRADES_PER_DAY
        self.default_sl_pips = settings.DEFAULT_SL_PIPS
        self.default_tp_pips = settings.DEFAULT_TP_PIPS
        self._daily_pnl: float = 0.0
        self._session_start_balance: float = 0.0
        self._kill_switch_active: bool = False
        self._trades_today: int = 0
        self._session_date: str = ""

    def reset_session(self, balance: float) -> None:
        self._daily_pnl = 0.0
        self._session_start_balance = balance
        self._kill_switch_active = False
        self._trades_today = 0
        self._session_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        logger.info("Risk session reset balance=%.2f", balance)

    def _roll_day_if_needed(self) -> None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self._session_date and self._session_date != today:
            self._trades_today = 0
            self._daily_pnl = 0.0
            self._kill_switch_active = False
            self._session_date = today

    def record_trade_opened(self) -> None:
        self._roll_day_if_needed()
        self._trades_today += 1

    def record_pnl(self, pnl: float) -> None:
        self._roll_day_if_needed()
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
            profit_pct = max(0, self._daily_pnl) / self._session_start_balance * 100
            if profit_pct >= self.max_daily_profit_percent:
                self._kill_switch_active = True
                logger.warning(
                    "Daily profit cap reached: %.2f%% >= %.2f%% — stopping new trades",
                    profit_pct,
                    self.max_daily_profit_percent,
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

    @property
    def trades_today(self) -> int:
        return self._trades_today

    def _pip_size(self, symbol: str) -> float:
        return pip_size(symbol)

    def calculate_stake(self, balance: float, sl_pips: int, symbol: str) -> float:
        """Demo: fixed DEMO_FIXED_STAKE_USD. Live: % of balance (not FX lot sizing)."""
        if settings.TRADING_MODE == "demo":
            return max(1.0, round(float(settings.DEMO_FIXED_STAKE_USD), 2))
        if sl_pips <= 0 or balance <= 0:
            return 0.0
        stake = balance * (self.risk_percent / 100.0)
        return max(1.0, round(stake, 2))

    def calculate_sl_tp_prices(
        self,
        signal: TradeSignal,
        sl_pips: Optional[int] = None,
        tp_pips: Optional[int] = None,
    ) -> tuple[float, float, int, int, str]:
        """Prefer strategy-suggested ATR/structure levels; fall back to fixed pips."""
        pip = self._pip_size(signal.symbol)
        price = signal.price
        suggested_sl = getattr(signal, "suggested_sl", None)
        suggested_tp = getattr(signal, "suggested_tp", None)
        method = getattr(signal, "sl_tp_method", None) or "fixed_pips"

        if suggested_sl and suggested_tp and suggested_sl > 0 and suggested_tp > 0:
            sl = float(suggested_sl)
            tp = float(suggested_tp)
            if signal.direction == SignalDirection.BUY:
                sl_dist = max(price - sl, pip)
                tp_dist = max(tp - price, pip)
            else:
                sl_dist = max(sl - price, pip)
                tp_dist = max(price - tp, pip)
            sl_pips_used = max(1, int(round(sl_dist / pip)))
            tp_pips_used = max(1, int(round(tp_dist / pip)))
            return sl, tp, sl_pips_used, tp_pips_used, method or "atr"

        sl_pips = sl_pips or self.default_sl_pips
        tp_pips = tp_pips or self.default_tp_pips
        if signal.direction == SignalDirection.BUY:
            sl = price - sl_pips * pip
            tp = price + tp_pips * pip
        else:
            sl = price + sl_pips * pip
            tp = price - tp_pips * pip
        return sl, tp, sl_pips, tp_pips, "fixed_pips"

    def evaluate(
        self,
        signal: TradeSignal,
        balance: float,
        trading_paused: bool = False,
        news_paused: bool = False,
        sl_pips: Optional[int] = None,
        tp_pips: Optional[int] = None,
        max_stake_usd: Optional[float] = None,
    ) -> RiskCheckResult:
        self._roll_day_if_needed()

        # Forex-only: reject synthetics (R_*, 1HZ*) and any non-frx symbol.
        symbol = getattr(signal, "symbol", "") or ""
        if not symbol.lower().startswith("frx"):
            return RiskCheckResult(
                decision=RiskDecision.REJECTED,
                reason=f"non_frx_symbol_rejected: {symbol}",
            )

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
        # MAX_TRADES_PER_DAY <= 0 means unlimited (demo data collection)
        if self.max_trades_per_day > 0 and self._trades_today >= self.max_trades_per_day:
            return RiskCheckResult(
                decision=RiskDecision.REJECTED,
                reason=f"Max trades today ({self.max_trades_per_day}) reached",
            )
        if self._session_start_balance > 0:
            profit_pct = max(0, self._daily_pnl) / self._session_start_balance * 100
            if profit_pct >= self.max_daily_profit_percent:
                return RiskCheckResult(
                    decision=RiskDecision.REJECTED,
                    reason="Max daily profit reached",
                )

        sl, tp, sl_pips_used, tp_pips_used, method = self.calculate_sl_tp_prices(
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
        # Live: apply ceiling + daily-plan max. Demo keeps fixed stake (ceiling as safety only).
        hard_ceiling = float(getattr(settings, "PLAN_MAX_STAKE_USD_CEILING", 100.0))
        if settings.TRADING_MODE == "demo":
            stake = min(stake, hard_ceiling)
        else:
            stake = min(stake, hard_ceiling)
            if max_stake_usd is not None and max_stake_usd > 0:
                stake = min(stake, float(max_stake_usd))

        return RiskCheckResult(
            decision=RiskDecision.APPROVED,
            reason="Risk checks passed",
            stake=stake,
            stop_loss_price=sl,
            take_profit_price=tp,
            stop_loss_pips=sl_pips_used,
            take_profit_pips=tp_pips_used,
            sl_tp_method=method,
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
            sl_tp_method="manual",
        )
