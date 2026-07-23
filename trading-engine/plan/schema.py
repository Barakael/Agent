"""Daily trading plan schema with hard clamps."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from config import settings
from strategies import ALL_STRATEGY_IDS, PATTERN_STRATEGY_IDS

ALLOWED_STRATEGIES = set(ALL_STRATEGY_IDS)
ALLOWED_PATTERN_STRATEGIES = set(PATTERN_STRATEGY_IDS)
SL_MIN, SL_MAX = 5, 50
TP_MIN, TP_MAX = 10, 100
SWING_SL_MAX = 80
SWING_TP_MAX = 200


def _risk_max() -> float:
    return float(getattr(settings, "PLAN_RISK_PERCENT_MAX", 2.0))


def _stake_ceiling() -> float:
    return float(getattr(settings, "PLAN_MAX_STAKE_USD_CEILING", 50.0))


class DailyPlan(BaseModel):
    date: str = Field(..., description="UTC date YYYY-MM-DD")
    pairs: list[str] = Field(..., min_length=1)
    strategy_id: str = "macd_rsi"
    enabled_strategies: list[str] = Field(default_factory=lambda: ["macd_rsi"])
    trade_mode: str = "pattern"  # pattern | bias
    directional_bias: str = "neutral"  # buy | sell | neutral
    hold_policy: str = "intraday"  # intraday | swing
    max_hold_days: int = Field(default=1, ge=1, le=14)
    sl_pips: int = Field(default=15, ge=SL_MIN)
    tp_pips: int = Field(default=30, ge=TP_MIN)
    risk_percent: float = Field(default=1.5, gt=0)
    max_stake_usd: float = Field(default=25.0, gt=0)
    notes: str = ""
    source: str = "cursor-automation"

    @field_validator("date")
    @classmethod
    def validate_date(cls, v: str) -> str:
        date.fromisoformat(v)
        return v

    @field_validator("trade_mode")
    @classmethod
    def validate_trade_mode(cls, v: str) -> str:
        v = v.lower()
        if v not in {"pattern", "bias"}:
            raise ValueError("trade_mode must be pattern or bias")
        return v

    @field_validator("directional_bias")
    @classmethod
    def validate_bias(cls, v: str) -> str:
        v = v.lower()
        if v not in {"buy", "sell", "neutral"}:
            raise ValueError("directional_bias must be buy, sell, or neutral")
        return v

    @field_validator("hold_policy")
    @classmethod
    def validate_hold(cls, v: str) -> str:
        v = v.lower()
        if v not in {"intraday", "swing"}:
            raise ValueError("hold_policy must be intraday or swing")
        return v

    @field_validator("strategy_id")
    @classmethod
    def validate_strategy(cls, v: str) -> str:
        if v not in ALLOWED_STRATEGIES:
            raise ValueError(f"strategy_id must be one of {sorted(ALLOWED_STRATEGIES)}")
        return v

    @field_validator("enabled_strategies")
    @classmethod
    def validate_enabled(cls, v: list[str]) -> list[str]:
        cleaned = [s.strip() for s in v if s and s.strip()]
        if not cleaned:
            cleaned = ["macd_rsi"]
        bad = [s for s in cleaned if s not in ALLOWED_PATTERN_STRATEGIES and s != "bias_swing"]
        if bad:
            raise ValueError(f"unknown strategies: {bad}")
        if len(cleaned) > 5:
            cleaned = cleaned[:5]
        return cleaned

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
        sl_max = SWING_SL_MAX if self.hold_policy == "swing" or self.trade_mode == "bias" else SL_MAX
        tp_max = SWING_TP_MAX if self.hold_policy == "swing" or self.trade_mode == "bias" else TP_MAX
        if self.sl_pips > sl_max:
            object.__setattr__(self, "sl_pips", sl_max)
        if self.tp_pips > tp_max:
            object.__setattr__(self, "tp_pips", tp_max)
        if self.sl_pips < SL_MIN:
            object.__setattr__(self, "sl_pips", SL_MIN)
        if self.tp_pips < TP_MIN:
            object.__setattr__(self, "tp_pips", TP_MIN)
        if self.tp_pips < self.sl_pips:
            raise ValueError("tp_pips must be >= sl_pips (min R:R 1.0)")
        risk_cap = _risk_max()
        if self.risk_percent > risk_cap:
            object.__setattr__(self, "risk_percent", risk_cap)
        ceiling = _stake_ceiling()
        if self.max_stake_usd > ceiling:
            object.__setattr__(self, "max_stake_usd", ceiling)
        if self.trade_mode == "bias":
            object.__setattr__(self, "hold_policy", "swing" if self.hold_policy == "intraday" else self.hold_policy)
            if self.directional_bias == "neutral":
                raise ValueError("directional_bias required for bias trade_mode")
            object.__setattr__(self, "enabled_strategies", ["bias_swing"])
            object.__setattr__(self, "strategy_id", "bias_swing")
        elif "bias_swing" in self.enabled_strategies:
            object.__setattr__(
                self,
                "enabled_strategies",
                [s for s in self.enabled_strategies if s != "bias_swing"] or ["macd_rsi"],
            )
        if self.strategy_id not in self.enabled_strategies and self.trade_mode == "pattern":
            # keep primary strategy_id as first enabled
            object.__setattr__(self, "strategy_id", self.enabled_strategies[0])
        return self

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()

    def is_active_for_today(self, today: Optional[str] = None) -> bool:
        today = today or datetime.now(timezone.utc).date().isoformat()
        return self.date == today

    @property
    def is_swing(self) -> bool:
        return self.hold_policy == "swing" or self.trade_mode == "bias"


def clamp_plan_dict(raw: dict[str, Any]) -> DailyPlan:
    """Validate/clamp incoming plan; raises ValueError on rejection."""
    cleaned = {k: v for k, v in raw.items() if k not in {"mode", "trading_mode", "TRADING_MODE"}}
    if "enabled_strategies" not in cleaned and cleaned.get("strategy_id"):
        cleaned["enabled_strategies"] = [cleaned["strategy_id"]]
    return DailyPlan.model_validate(cleaned)
