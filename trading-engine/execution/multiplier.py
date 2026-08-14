"""Multiplier contract geometry.

A Deriv multiplier position gains ``stake x multiplier x pct_move`` and is
liquidated once the adverse move reaches ``1 / multiplier``. That ceiling, not
the chart, decides how wide a stop can actually be encoded.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable, Optional, Sequence

logger = logging.getLogger(__name__)

# Require headroom between the planned stop and liquidation so normal noise
# cannot close a position at the contract's hard floor.
DEFAULT_STOP_SAFETY = 1.25


def contract_room_pct(multiplier: float) -> float:
    """Adverse percentage move that wipes the whole stake."""
    return 1.0 / max(float(multiplier), 1e-9)


def price_distance_pct(entry: float, level: float) -> float:
    if entry <= 0:
        return 0.0
    return abs(float(entry) - float(level)) / float(entry)


def usd_from_pct(stake: float, multiplier: float, pct: float) -> float:
    """Contract profit or loss in dollars for a percentage move."""
    return float(stake) * float(multiplier) * float(pct)


def pct_from_usd(stake: float, multiplier: float, usd: float) -> float:
    notional = float(stake) * float(multiplier)
    if notional <= 0:
        return 0.0
    return float(usd) / notional


def usd_from_price_distance(
    stake: float, multiplier: float, entry: float, level: float
) -> float:
    return usd_from_pct(stake, multiplier, price_distance_pct(entry, level))


def stop_fits(
    multiplier: float, stop_pct: float, safety: float = DEFAULT_STOP_SAFETY
) -> bool:
    """True when the stop sits inside the contract's room with headroom."""
    if stop_pct <= 0:
        return False
    return contract_room_pct(multiplier) >= stop_pct * safety


@dataclass(frozen=True)
class ContractCalibration:
    """The venue's own map between a chart distance and a dollar limit.

    Deriv's ``limit_order`` amounts are net of costs, so converting a chart
    distance with plain ``stake x multiplier x pct`` puts the trigger short of the
    intended level: measured on live proposals a one-ATR stop fired 18% closer
    than the chart asked, and the matching target sat 17% further away. Both
    errors work against the position.

    Fitting the venue's quoted trigger prices gives ``usd = notional x pct -/+
    cost``, where ``notional`` runs slightly under ``stake x multiplier`` and
    ``cost`` is the commission and spread already priced into the contract.
    """

    notional: float
    cost: float
    symbol: str = ""
    stake: float = 0.0
    multiplier: float = 0.0

    @property
    def gross_notional(self) -> float:
        return self.stake * self.multiplier

    def usd_for_stop(self, pct: float) -> float:
        """Dollar stop whose trigger price sits ``pct`` the wrong side of entry."""
        return self.notional * float(pct) + self.cost

    def usd_for_target(self, pct: float) -> float:
        """Dollar target whose trigger price sits ``pct`` the right side of entry."""
        return self.notional * float(pct) - self.cost

    def stop_pct_for_usd(self, usd: float) -> float:
        """Where a given dollar stop will actually fire, as a fraction of entry."""
        if self.notional <= 0:
            return 0.0
        return (float(usd) - self.cost) / self.notional

    def target_pct_for_usd(self, usd: float) -> float:
        if self.notional <= 0:
            return 0.0
        return (float(usd) + self.cost) / self.notional


def fit_calibration(
    spot: float,
    observations: Sequence[tuple[float, float]],
    *,
    symbol: str = "",
    stake: float = 0.0,
    multiplier: float = 0.0,
) -> Optional[ContractCalibration]:
    """Fit the dollar-limit map from ``(usd, trigger_price)`` pairs on the stop side.

    Returns None when the points are degenerate or the implied notional is not
    close to ``stake x multiplier``, so a change at the venue makes the engine
    fall back to plain arithmetic rather than trade on a nonsense fit.
    """
    spot = float(spot)
    if spot <= 0:
        return None
    points = []
    for usd, trigger in observations:
        pct = (spot - float(trigger)) / spot
        if pct > 0:
            points.append((pct, abs(float(usd))))
    if len(points) < 2:
        return None

    n = len(points)
    mean_pct = sum(p for p, _ in points) / n
    mean_usd = sum(u for _, u in points) / n
    variance = sum((p - mean_pct) ** 2 for p, _ in points)
    if variance <= 1e-12:
        return None
    slope = sum((p - mean_pct) * (u - mean_usd) for p, u in points) / variance
    intercept = mean_usd - slope * mean_pct

    gross = float(stake) * float(multiplier)
    if gross > 0 and not (0.5 * gross <= slope <= 1.2 * gross):
        logger.warning(
            "Discarding contract calibration for %s: implied notional %.2f is not "
            "close to stake x multiplier %.2f",
            symbol or "?",
            slope,
            gross,
        )
        return None
    if intercept < 0:
        return None

    return ContractCalibration(
        notional=slope,
        cost=intercept,
        symbol=symbol,
        stake=float(stake),
        multiplier=float(multiplier),
    )


def select_multiplier(
    allowed: Iterable[float],
    required_stop_pct: float,
    safety: float = DEFAULT_STOP_SAFETY,
) -> Optional[float]:
    """Highest multiplier that still leaves room for the planned stop.

    Highest is preferred so capital efficiency is maximised, subject to the
    stop being encodable rather than truncated by liquidation.
    """
    viable = [
        float(m) for m in allowed if stop_fits(float(m), required_stop_pct, safety)
    ]
    return max(viable) if viable else None


def validate_multiplier(
    configured: float, allowed: Sequence[float]
) -> tuple[bool, str]:
    """Check a configured multiplier against the values Deriv accepts."""
    if not allowed:
        return True, "no allowed set reported; keeping configured multiplier"
    if float(configured) in {float(m) for m in allowed}:
        return True, "multiplier accepted"
    return (
        False,
        f"multiplier {configured:g} not offered; allowed values are "
        + ", ".join(f"{float(m):g}" for m in sorted(allowed)),
    )


def parse_allowed_from_error(error: dict) -> list[float]:
    """Extract the allowed multiplier list from a MultiplierOutOfRange error."""
    raw = error.get("code_args") if isinstance(error, dict) else None
    if not raw:
        return []
    text = str(raw[0]) if isinstance(raw, list) and raw else str(raw)
    values: list[float] = []
    for part in text.replace(" ", "").split(","):
        try:
            values.append(float(part))
        except ValueError:
            continue
    return values
