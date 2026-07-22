"""Order execution via Deriv API."""

from __future__ import annotations

import logging
from typing import Optional

from config import settings
from data.deriv_ws import DerivWebSocketClient
from risk.gate import RiskCheckResult
from signals.engine import SignalDirection, TradeSignal

logger = logging.getLogger(__name__)


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
        if self.mode == "log_only":
            logger.info(
                "LOG_ONLY: would %s %s stake=%.2f SL=%.5f TP=%.5f",
                signal.direction.value,
                signal.symbol,
                risk.stake,
                risk.stop_loss_price,
                risk.take_profit_price,
            )
            return {
                "mode": "log_only",
                "symbol": signal.symbol,
                "direction": signal.direction.value,
                "stake": risk.stake,
                "stop_loss": risk.stop_loss_price,
                "take_profit": risk.take_profit_price,
            }

        contract_type = self._contract_type(signal.direction)
        duration = settings.CANDLE_TIMEFRAME_MINUTES * 3  # unused for multipliers

        result = await self.client.buy_contract(
            symbol=signal.symbol,
            contract_type=contract_type,
            amount=risk.stake,
            duration=duration,
            duration_unit="m",
            stop_loss=risk.stop_loss_price,
            take_profit=risk.take_profit_price,
            multiplier=100,
        )
        logger.info("Order placed %s %s contract_id=%s", signal.symbol, contract_type, result.get("contract_id"))
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
        return await self.client.buy_contract(
            symbol=symbol,
            contract_type=contract_type,
            amount=stake,
            duration=duration,
            duration_unit="m",
            stop_loss=stop_loss,
            take_profit=take_profit,
            multiplier=100,
        )
