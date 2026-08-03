"""Build feature dictionaries for logging / later stats."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from bias.bias_6h import BiasState
from bias.confirm_1h import ConfirmResult
from bias.regime_24h import RegimeState


def build_feature_dict(
    *,
    symbol: str,
    regime: RegimeState,
    bias: BiasState,
    confirm: Optional[ConfirmResult] = None,
    extra: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    out: dict[str, Any] = {
        "symbol": symbol,
        "ts_utc": now.isoformat(),
        "utc_hour": now.hour,
        "regime": regime.label,
        "regime_return_24h": regime.return_24h,
        "regime_atr_ratio": regime.atr_ratio,
        "bias": bias.direction,
        "bias_id": bias.bias_id,
        "bias_return_6h": bias.return_6h,
        "bias_atr_6h": bias.atr_6h,
        "bias_range_high": bias.range_high,
        "bias_range_low": bias.range_low,
        "ema_aligned_up": bias.ema_aligned_up,
        "ema_aligned_down": bias.ema_aligned_down,
        "structure_trend": bias.structure_trend,
        "rsi": bias.rsi,
        "gates_passed": confirm.gates_passed if confirm else [],
        "gates_failed": confirm.gates_failed if confirm else [],
        "confirm_ok": confirm.ok if confirm else None,
        "confirm_type": confirm.confirm_type if confirm else None,
        "pipeline": "bias_v1",
    }
    if extra:
        out.update(extra)
    return out
