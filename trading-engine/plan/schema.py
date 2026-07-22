"""Daily trading plan schema with hard clamps."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from config import settings

ALLOWED_STRATEGIES = {"macd_rsi"}
SL_MIN, SL_MAX = 5, 50
TP_MIN, TP_MAX = 10, 100


def _risk_max() -> float:
    return float(getattr(settings, "PLAN_RISK_PERCENT_MAX", 2.0))


def _stake_ceiling() -> float:
    return float(getattr(settings, "PLAN_MAX_STAKE_USD_CEILING", 50.0))


class DailyPlan(BaseModel):
    date: str = Field(..., description="UTC date YYYY-MM-DD")
    pairs: list[str] = Field(..., min_length=1)
    strategy_id: str = "macd_rsi"
    sl_pips: int = Field(default=15, ge=SL_MIN, le=SL_MAX)
    tp_pips: int = Field(default=30, ge=TP_MIN, le=TP_MAX)
    risk_percent: float = Field(default=1.5, gt=0)
    max_stake_usd: float = Field(default=25.0, gt=0)
    notes: str = ""
    source: str = "cursor-automation"

    @field_validator("date")
    @classmethod
    def validate_date(cls, v: str) -> str:
        date.fromisoformat(v)
        return v

    @field_validator("strategy_id")
    @classmethod
    def validate_strategy(cls, v: str) -> str:
        if v not in ALLOWED_STRATEGIES:
            raise ValueError(f"strategy_id must be one of {sorted(ALLOWED_STRATEGIES)}")
        return v

    @field_validator("pairs")
    @classmethod
    def validate_pairs(cls, v: list[str]) -> list[str]:
        allow = set(settings.pairs_list)
        cleaned = [p.strip() for p in v if p.strip()]
        if not cleaned:
            raise ValueError("pairs must not be empty")
        bad = [p for p in cleaned if p not in allow]
        if bad:
            raise ValueError(f"pairs not in allowlist: {bad}; allowed={sorted(allow)}")
        return cleaned

    @model_validator(mode="after")
    def clamp_and_check_rr(self) -> DailyPlan:
        if self.tp_pips < self.sl_pips:
            raise ValueError("tp_pips must be >= sl_pips (min R:R 1.0)")
        risk_cap = _risk_max()
        if self.risk_percent > risk_cap:
            object.__setattr__(self, "risk_percent", risk_cap)
        ceiling = _stake_ceiling()
        if self.max_stake_usd > ceiling:
            object.__setattr__(self, "max_stake_usd", ceiling)
        return self

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()

    def is_active_for_today(self, today: Optional[str] = None) -> bool:
        today = today or datetime.now(timezone.utc).date().isoformat()
        return self.date == today


def clamp_plan_dict(raw: dict[str, Any]) -> DailyPlan:
    """Validate/clamp incoming plan; raises ValueError on rejection."""
    cleaned = {k: v for k, v in raw.items() if k not in {"mode", "trading_mode", "TRADING_MODE"}}
    return DailyPlan.model_validate(cleaned)
