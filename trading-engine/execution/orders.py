"""Order execution via Deriv API."""

from __future__ import annotations

import logging
from typing import Optional

from config import settings
from data.deriv_ws import DerivWebSocketClient
from risk.gate import RiskCheckResult
from signals.engine import SignalDirection, TradeSignal

logger = logging.getLogger(__name__)


def usd_limit_from_risk(risk: RiskCheckResult) -> tuple[float, float]:
    """
    Deriv MULTUP/MULTDOWN limit_order uses USD P/L amounts, not chart prices.

    Journal / RiskGate keep price_sl / price_tp (ATR or fixed pips).
    Contract risk is enforced in dollars: SL ≈ stake×0.8, TP ≈ stake×(tp_pips/sl_pips).
    """
    sl_usd = round(float(risk.stake) * 0.8, 2)
    tp_usd = round(
        float(risk.stake) * (risk.take_profit_pips / max(1, risk.stop_loss_pips)),
        2,
    )
    return sl_usd, tp_usd


class OrderExecutor:
    """Place orders only when risk gate approves and mode allows execution."""

    def __init__(self, client: DerivWebSocketClient) -> None:
        self.client = client
        self.mode = settings.TRADING_MODE

    def _contract_type(self, direction: SignalDirection) -> str:
        # Multipliers can be sold early; binary CALL/PUT often cannot.
        return "MULTUP" if direction == SignalDirection.BUY else "MULTDOWN"

    async def execute_signal(
        self,
        signal: TradeSignal,
        risk: RiskCheckResult,
    ) -> Optional[dict]:
        usd_sl, usd_tp = usd_limit_from_risk(risk)
        if self.mode == "log_only":
            logger.info(
                "LOG_ONLY: would %s %s stake=%.2f price_sl=%.5f price_tp=%.5f "
                "usd_sl=%.2f usd_tp=%.2f method=%s",
                signal.direction.value,
                signal.symbol,
                risk.stake,
                risk.stop_loss_price,
                risk.take_profit_price,
                usd_sl,
                usd_tp,
                risk.sl_tp_method,
            )
            return {
                "mode": "log_only",
                "symbol": signal.symbol,
                "direction": signal.direction.value,
                "stake": risk.stake,
                "stop_loss": risk.stop_loss_price,
                "take_profit": risk.take_profit_price,
                "stop_loss_usd": usd_sl,
                "take_profit_usd": usd_tp,
                "sl_tp_method": risk.sl_tp_method,
            }

        contract_type = self._contract_type(signal.direction)
        duration = settings.CANDLE_TIMEFRAME_MINUTES * 3  # unused for multipliers

        logger.info(
            "Opening %s %s stake=%.2f price_sl=%.5f price_tp=%.5f "
            "usd_sl=%.2f usd_tp=%.2f method=%s",
            signal.symbol,
            contract_type,
            risk.stake,
            risk.stop_loss_price,
            risk.take_profit_price,
            usd_sl,
            usd_tp,
            risk.sl_tp_method,
        )

        result = await self.client.buy_contract(
            symbol=signal.symbol,
            contract_type=contract_type,
            amount=risk.stake,
            duration=duration,
            duration_unit="m",
            stop_loss=usd_sl,
            take_profit=usd_tp,
            multiplier=settings.DERIV_MULTIPLIER,
        )
        if result is not None:
            result["stop_loss_usd"] = usd_sl
            result["take_profit_usd"] = usd_tp
            result["price_sl"] = risk.stop_loss_price
            result["price_tp"] = risk.take_profit_price
            result["sl_tp_method"] = risk.sl_tp_method
        logger.info(
            "Order placed %s %s contract_id=%s usd_sl=%.2f usd_tp=%.2f",
            signal.symbol,
            contract_type,
            result.get("contract_id") if result else None,
            usd_sl,
            usd_tp,
        )
        return result

    async def execute_manual(
        self,
        symbol: str,
        direction: str,
        stake: float,
        stop_loss: float,
        take_profit: float,
    ) -> dict:
        if self.mode == "log_only":
            return {
                "mode": "log_only",
                "symbol": symbol,
                "direction": direction,
                "stake": stake,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
            }

        contract_type = "MULTUP" if direction.lower() == "buy" else "MULTDOWN"
        duration = settings.CANDLE_TIMEFRAME_MINUTES * 3
        sl_usd = round(float(stake) * 0.8, 2)
        tp_usd = round(float(stake) * 2.0, 2)
        logger.info(
            "Manual open %s %s stake=%.2f price_sl=%.5f price_tp=%.5f usd_sl=%.2f usd_tp=%.2f",
            symbol,
            contract_type,
            stake,
            stop_loss,
            take_profit,
            sl_usd,
            tp_usd,
        )
        return await self.client.buy_contract(
            symbol=symbol,
            contract_type=contract_type,
            amount=stake,
            duration=duration,
            duration_unit="m",
            stop_loss=sl_usd,
            take_profit=tp_usd,
            multiplier=settings.DERIV_MULTIPLIER,
        )
