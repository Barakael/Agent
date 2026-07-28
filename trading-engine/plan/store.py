"""Persist active daily plan to disk."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from plan.schema import DailyPlan, clamp_plan_dict

logger = logging.getLogger(__name__)

PLAN_PATH = Path(__file__).resolve().parent.parent / "data" / "active_plan.json"


class PlanStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or PLAN_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._cached: Optional[DailyPlan] = None

    def load(self) -> Optional[DailyPlan]:
        if self._cached is not None:
            return self._cached
        if not self.path.exists():
            return None
        try:
            raw = json.loads(self.path.read_text())
            self._cached = clamp_plan_dict(raw)
            return self._cached
        except Exception as exc:
            # Quarantine invalid plans (e.g. forex pairs after switching to synthetics)
            # so status polling does not spam stack traces every few seconds.
            logger.warning("Ignoring invalid active plan at %s: %s", self.path, exc)
            try:
                bad = self.path.with_name(self.path.name + ".invalid")
                if bad.exists():
                    bad.unlink()
                self.path.replace(bad)
            except Exception:
                try:
                    self.path.unlink(missing_ok=True)
                except Exception:
                    pass
            return None

    def save(self, plan: DailyPlan) -> DailyPlan:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(plan.to_dict(), indent=2))
        self._cached = plan
        logger.info(
            "Active plan saved date=%s pairs=%s sl=%s tp=%s risk=%s",
            plan.date,
            plan.pairs,
            plan.sl_pips,
            plan.tp_pips,
            plan.risk_percent,
        )
        return plan

    def save_dict(self, raw: dict) -> DailyPlan:
        plan = clamp_plan_dict(raw)
        return self.save(plan)

    def clear_cache(self) -> None:
        self._cached = None


plan_store = PlanStore()
