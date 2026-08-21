"""Daily trading plan schema with hard clamps and news+chart ALIGN checklist."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from config import settings
from strategies import ALL_STRATEGY_IDS, PATTERN_STRATEGY_IDS, STRATEGY_ALIASES, resolve_strategy_id

ALLOWED_STRATEGIES = set(ALL_STRATEGY_IDS) | set(STRATEGY_ALIASES.keys())
ALLOWED_PATTERN_STRATEGIES = set(PATTERN_STRATEGY_IDS) | {
    k for k, v in STRATEGY_ALIASES.items() if v in PATTERN_STRATEGY_IDS
}
ALLOWED_MAJORS = {
    "frxEURUSD",
    "frxGBPUSD",
    "frxUSDJPY",
    "frxAUDUSD",
    "frxUSDCAD",
}
SL_MIN, SL_MAX = 5, 50
TP_MIN, TP_MAX = 10, 100
SWING_SL_MAX = 80
SWING_TP_MAX = 200


def _risk_max() -> float:
    return float(getattr(settings, "PLAN_RISK_PERCENT_MAX", 2.0))


def _stake_ceiling() -> float:
    return float(getattr(settings, "PLAN_MAX_STAKE_USD_CEILING", 50.0))


class PlanChecklist(BaseModel):
    news_chart_aligned: bool = False
    structure_aligned: bool = False
    not_chasing: bool = False
    rsi_ok: bool = False
    event_ok: bool = True


class PlanAnalysis(BaseModel):
    news_thesis: str = ""
    structure_bias: str = ""
    currency_board: dict[str, str] = Field(default_factory=dict)
    invalidation: str = ""
    prefer_symbol_order: list[str] = Field(default_factory=list)
    checklist: PlanChecklist = Field(default_factory=PlanChecklist)

    @field_validator("prefer_symbol_order")
    @classmethod
    def validate_prefer(cls, v: list[str]) -> list[str]:
        cleaned = [p.strip() for p in v if p and p.strip()]
        bad = [p for p in cleaned if p not in ALLOWED_MAJORS]
        if bad:
            raise ValueError(f"prefer_symbol_order not in allowlist: {bad}")
        return cleaned[:5]


class PlanSetup(BaseModel):
    """One Cursor-directed trade the VPS bot may execute."""

    symbol: str
    direction: str  # buy | sell
    entry_style: str = "pullback"  # market | pullback
    entry_price: Optional[float] = None
    sl_pips: Optional[int] = None
    tp_pips: Optional[int] = None
    priority: int = Field(default=1, ge=1, le=10)
    rationale: str = ""

    @field_validator("symbol")
    @classmethod
    def validate_symbol(cls, v: str) -> str:
        v = v.strip()
        if v not in ALLOWED_MAJORS:
            raise ValueError(f"setup symbol must be one of {sorted(ALLOWED_MAJORS)}")
        return v

    @field_validator("direction")
    @classmethod
    def validate_direction(cls, v: str) -> str:
        v = v.lower()
        if v not in {"buy", "sell"}:
            raise ValueError("setup direction must be buy or sell")
        return v

    @field_validator("entry_style")
    @classmethod
    def validate_entry_style(cls, v: str) -> str:
        v = v.lower()
        if v not in {"market", "pullback"}:
            raise ValueError("entry_style must be market or pullback")
        return v


class DailyPlan(BaseModel):
    date: str = Field(..., description="UTC date YYYY-MM-DD")
    pairs: list[str] = Field(..., min_length=1)
    strategy_id: str = "momentum"
    enabled_strategies: list[str] = Field(
        default_factory=lambda: [
            "momentum",
            "trend_following",
            "range_trading",
            "breakout",
            "price_action",
        ]
    )
    trade_mode: str = "pattern"  # pattern | bias
    directional_bias: str = "neutral"  # buy | sell | neutral
    hold_policy: str = "intraday"  # intraday | swing
    max_hold_days: int = Field(default=1, ge=1, le=14)
    sl_pips: int = Field(default=15, ge=SL_MIN)
    tp_pips: int = Field(default=30, ge=TP_MIN)
    risk_percent: float = Field(default=1.5, gt=0)
    max_stake_usd: float = Field(default=25.0, gt=0)
    confidence: int = Field(default=50, ge=0, le=100)
    notes: str = ""
    source: str = "cursor-automation"
    execution_mode: str = "cursor_execute"  # cursor_execute | chart_confirm
    max_trades_today: int = Field(default=3, ge=0, le=4)
    entry_style: str = "pullback"
    review: str = ""
    avoid_until_utc: Optional[str] = None
    setups: list[PlanSetup] = Field(default_factory=list)
    analysis: Optional[PlanAnalysis] = None

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

    @field_validator("execution_mode")
    @classmethod
    def validate_execution_mode(cls, v: str) -> str:
        v = v.lower()
        if v not in {"cursor_execute", "chart_confirm"}:
            raise ValueError("execution_mode must be cursor_execute or chart_confirm")
        return v

    @field_validator("entry_style")
    @classmethod
    def validate_plan_entry_style(cls, v: str) -> str:
        v = v.lower()
        if v not in {"market", "pullback"}:
            raise ValueError("entry_style must be market or pullback")
        return v

    @field_validator("strategy_id")
    @classmethod
    def validate_strategy(cls, v: str) -> str:
        v = resolve_strategy_id(v)
        if v not in ALLOWED_STRATEGIES and v not in set(ALL_STRATEGY_IDS):
            raise ValueError(f"strategy_id must be one of {sorted(ALLOWED_STRATEGIES)}")
        return v

    @field_validator("enabled_strategies")
    @classmethod
    def validate_enabled(cls, v: list[str]) -> list[str]:
        cleaned = [resolve_strategy_id(s.strip()) for s in v if s and s.strip()]
        if not cleaned:
            cleaned = ["momentum"]
        bad = [s for s in cleaned if s not in ALLOWED_PATTERN_STRATEGIES and s != "bias_swing"]
        if bad:
            raise ValueError(f"unknown strategies: {bad}")
        seen: set[str] = set()
        uniq: list[str] = []
        for s in cleaned:
            if s not in seen:
                seen.add(s)
                uniq.append(s)
        if len(uniq) > 5:
            uniq = uniq[:5]
        return uniq

    @field_validator("pairs")
    @classmethod
    def validate_pairs(cls, v: list[str]) -> list[str]:
        allow = set(settings.pairs_list) | ALLOWED_MAJORS
        cleaned = [p.strip() for p in v if p.strip()]
        if not cleaned:
            raise ValueError("pairs must not be empty")
        bad = [p for p in cleaned if p not in allow]
        if bad:
            raise ValueError(f"pairs not in allowlist: {bad}; allowed={sorted(allow)}")
        if len(cleaned) > 3:
            cleaned = cleaned[:3]
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

        src = (self.source or "").lower()
        if src.startswith("cursor"):
            object.__setattr__(self, "execution_mode", "cursor_execute")

        if self.trade_mode == "bias":
            object.__setattr__(
                self,
                "hold_policy",
                "swing" if self.hold_policy == "intraday" else self.hold_policy,
            )
            if self.directional_bias == "neutral" and self.max_trades_today > 0:
                raise ValueError("directional_bias required for bias trade_mode")
            object.__setattr__(self, "enabled_strategies", ["bias_swing"])
            object.__setattr__(self, "strategy_id", "bias_swing")
        elif "bias_swing" in self.enabled_strategies:
            object.__setattr__(
                self,
                "enabled_strategies",
                [s for s in self.enabled_strategies if s != "bias_swing"] or ["momentum"],
            )
        if self.strategy_id not in self.enabled_strategies and self.trade_mode == "pattern":
            object.__setattr__(self, "strategy_id", self.enabled_strategies[0])

        clamped_setups: list[PlanSetup] = []
        for s in self.setups:
            sl = s.sl_pips if s.sl_pips is not None else self.sl_pips
            tp = s.tp_pips if s.tp_pips is not None else self.tp_pips
            sl = max(SL_MIN, min(int(sl), sl_max))
            tp = max(TP_MIN, min(int(tp), tp_max))
            if tp < sl:
                tp = sl
            clamped_setups.append(s.model_copy(update={"sl_pips": sl, "tp_pips": tp}))
        if clamped_setups:
            object.__setattr__(self, "setups", clamped_setups)

        # Hard ALIGN gate for cursor execute buys/sells
        wants_execute = (
            src.startswith("cursor")
            and self.execution_mode == "cursor_execute"
            and self.max_trades_today > 0
            and self.directional_bias in {"buy", "sell"}
        )
        if wants_execute:
            if self.analysis is None:
                raise ValueError(
                    "analysis.checklist required for cursor_execute bias plans "
                    "(news_chart_aligned must be true)"
                )
            cl = self.analysis.checklist
            required = (
                cl.news_chart_aligned
                and cl.structure_aligned
                and cl.not_chasing
                and cl.rsi_ok
                and cl.event_ok
            )
            if not required:
                raise ValueError(
                    "ALIGN gate failed: analysis.checklist must have "
                    "news_chart_aligned, structure_aligned, not_chasing, rsi_ok, event_ok all true "
                    "(or set max_trades_today=0 to stand aside)"
                )

        return self

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()

    def is_active_for_today(self, today: Optional[str] = None) -> bool:
        today = today or datetime.now(timezone.utc).date().isoformat()
        return self.date == today

    @property
    def is_swing(self) -> bool:
        return self.hold_policy == "swing" or self.trade_mode == "bias"

    @property
    def is_cursor_execute(self) -> bool:
        thesis = self.directional_bias in {"buy", "sell"} or bool(self.setups)
        aligned = True
        if self.analysis is not None:
            cl = self.analysis.checklist
            aligned = (
                cl.news_chart_aligned
                and cl.structure_aligned
                and cl.not_chasing
                and cl.rsi_ok
                and cl.event_ok
            )
        return (
            (self.source or "").lower().startswith("cursor")
            and self.execution_mode == "cursor_execute"
            and self.max_trades_today > 0
            and thesis
            and aligned
        )

    def prefer_order(self) -> list[str]:
        if self.analysis and self.analysis.prefer_symbol_order:
            return list(self.analysis.prefer_symbol_order)
        setups = sorted(self.setups or [], key=lambda s: int(s.priority or 1))
        if setups:
            return [s.symbol for s in setups]
        return list(self.pairs or [])


def clamp_plan_dict(raw: dict[str, Any]) -> DailyPlan:
    """Validate/clamp incoming plan; raises ValueError on rejection."""
    cleaned = {k: v for k, v in raw.items() if k not in {"mode", "trading_mode", "TRADING_MODE"}}
    if "enabled_strategies" not in cleaned and cleaned.get("strategy_id"):
        cleaned["enabled_strategies"] = [cleaned["strategy_id"]]
    return DailyPlan.model_validate(cleaned)
