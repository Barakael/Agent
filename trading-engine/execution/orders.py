"""Order execution via Deriv API."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from config import settings
from data.deriv_ws import DerivWebSocketClient
from execution.multiplier import (
    ContractCalibration,
    contract_room_pct,
    price_distance_pct,
    stop_fits,
    usd_from_pct,
)
from risk.gate import RiskCheckResult
from signals.engine import SignalDirection, TradeSignal

logger = logging.getLogger(__name__)


class UnencodableStop(RuntimeError):
    """Raised when the chart stop cannot fit inside the contract's room."""


class InvertedRR(RuntimeError):
    """Raised when dollar TP is below the minimum 1.5x dollar SL after cost calibration."""


MIN_DOLLAR_RR = 1.5


@dataclass(frozen=True)
class ContractBarriers:
    """Chart distances expressed as contract dollars and percentages."""

    usd_sl: float
    usd_tp: float
    sl_pct: float
    tp_pct: float
    multiplier: float
    encodable: bool
    # False means the dollar limits came from plain arithmetic, so both barriers
    # will sit inside the chart levels by roughly the contract's cost.
    calibrated: bool = False

    @property
    def room_pct(self) -> float:
        return contract_room_pct(self.multiplier)


def barriers_from_risk(
    risk: RiskCheckResult,
    entry: float,
    *,
    multiplier: float | None = None,
    calibration: ContractCalibration | None = None,
) -> ContractBarriers:
    """Map the plan's stop and target prices onto multiplier dollar limits.

    Deriv's ``limit_order`` takes USD amounts, and those amounts are net of the
    commission and spread already inside the contract. Converting a chart
    distance with plain ``stake x multiplier x distance / entry`` therefore puts
    the stop nearer than the chart asked and the target further away — measured
    live at 18% and 17% of the intended distances. When a ``calibration`` fitted
    from the venue's own quoted trigger prices is supplied, the cost is added
    back so both barriers fire where the thesis intended.
    """
    mult = float(multiplier if multiplier is not None else settings.DERIV_MULTIPLIER)
    stake = float(risk.stake)
    sl_pct = price_distance_pct(entry, risk.stop_loss_price)
    tp_pct = price_distance_pct(entry, risk.take_profit_price)

    if calibration is not None:
        usd_sl = calibration.usd_for_stop(sl_pct)
        usd_tp = calibration.usd_for_target(tp_pct)
    else:
        usd_sl = usd_from_pct(stake, mult, sl_pct)
        usd_tp = usd_from_pct(stake, mult, tp_pct)

    return ContractBarriers(
        usd_sl=round(usd_sl, 2),
        usd_tp=round(usd_tp, 2),
        sl_pct=sl_pct,
        tp_pct=tp_pct,
        multiplier=mult,
        encodable=stop_fits(
            mult, sl_pct, safety=float(settings.MULTIPLIER_STOP_SAFETY)
        ),
        calibrated=calibration is not None,
    )


def usd_limit_from_risk(
    risk: RiskCheckResult, entry: float | None = None
) -> tuple[float, float]:
    """Contract stop and target in USD for the plan's chart levels."""
    price = entry if entry is not None else risk.stop_loss_price
    barriers = barriers_from_risk(risk, float(price))
    return barriers.usd_sl, barriers.usd_tp


class OrderExecutor:
    """Place orders only when risk gate approves and mode allows execution."""

    def __init__(self, client: DerivWebSocketClient) -> None:
        self.client = client
        self.mode = settings.TRADING_MODE
        self._calibrations: dict[tuple[str, float, float], ContractCalibration] = {}

    def _contract_type(self, direction: SignalDirection) -> str:
        # Multipliers can be sold early; binary CALL/PUT often cannot.
        return "MULTUP" if direction == SignalDirection.BUY else "MULTDOWN"

    async def _calibration(
        self, symbol: str, stake: float, multiplier: float
    ) -> Optional[ContractCalibration]:
        """Cached per symbol, stake and multiplier — the fit depends on all three."""
        if not settings.CALIBRATE_CONTRACT_BARRIERS:
            return None
        key = (symbol, round(float(stake), 2), float(multiplier))
        if key not in self._calibrations:
            try:
                fitted = await self.client.calibrate_contract(symbol, stake, multiplier)
            except Exception:
                logger.warning("Barrier calibration failed for %s", symbol, exc_info=True)
                return None
            if fitted is None:
                return None
            self._calibrations[key] = fitted
        return self._calibrations[key]

    async def execute_signal(
        self,
        signal: TradeSignal,
        risk: RiskCheckResult,
    ) -> Optional[dict]:
        mult = float(settings.DERIV_MULTIPLIER)
        calibration = None
        if self.mode != "log_only":
            calibration = await self._calibration(signal.symbol, risk.stake, mult)
        barriers = barriers_from_risk(
            risk, float(signal.price), calibration=calibration
        )
        usd_sl, usd_tp = barriers.usd_sl, barriers.usd_tp

        if not barriers.encodable:
            detail = (
                f"{signal.symbol} stop needs {barriers.sl_pct * 100:.2f}% but multiplier "
                f"{barriers.multiplier:g} liquidates at {barriers.room_pct * 100:.2f}%"
            )
            if settings.REJECT_UNENCODABLE_STOP:
                logger.warning("Rejecting signal — %s", detail)
                raise UnencodableStop(detail)
            logger.warning("Stop exceeds contract room — %s", detail)

        if usd_sl > 0 and usd_tp < MIN_DOLLAR_RR * usd_sl:
            detail = (
                f"{signal.symbol} dollar RR {usd_tp:.2f}/{usd_sl:.2f}="
                f"{usd_tp/usd_sl:.2f} < {MIN_DOLLAR_RR} after calibration"
            )
            logger.warning("Rejecting signal — %s", detail)
            raise InvertedRR(detail)

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
            multiplier=barriers.multiplier,
            stop_loss_pct=barriers.sl_pct,
            take_profit_pct=barriers.tp_pct,
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
        entry: Optional[float] = None,
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
        mult = float(settings.DERIV_MULTIPLIER)
        sl_pct = tp_pct = None
        if entry:
            sl_pct = price_distance_pct(entry, stop_loss)
            tp_pct = price_distance_pct(entry, take_profit)
            sl_usd = round(usd_from_pct(stake, mult, sl_pct), 2)
            tp_usd = round(usd_from_pct(stake, mult, tp_pct), 2)
            if not stop_fits(mult, sl_pct, safety=float(settings.MULTIPLIER_STOP_SAFETY)):
                detail = (
                    f"{symbol} manual stop needs {sl_pct * 100:.2f}% but multiplier "
                    f"{mult:g} liquidates at {contract_room_pct(mult) * 100:.2f}%"
                )
                if settings.REJECT_UNENCODABLE_STOP:
                    raise UnencodableStop(detail)
                logger.warning("Manual stop exceeds contract room — %s", detail)
        else:
            logger.warning(
                "Manual order for %s has no entry price — falling back to fixed "
                "dollar limits, which will not match the requested chart levels",
                symbol,
            )
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
            multiplier=mult,
            stop_loss_pct=sl_pct,
            take_profit_pct=tp_pct,
        )
