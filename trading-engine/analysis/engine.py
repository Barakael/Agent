"""ATAE orchestrator — preflight, open/close gates, source collection."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
import pandas as pd

from analysis.multi_timeframe import higher_timeframe_aligned
from analysis.scenario_close import CloseScenarioResult, evaluate_close
from analysis.scenario_open import OpenScenarioResult, simulate_sl_tp_window
from analytics.metrics import compute_metrics
from backtest.runner import BacktestRunner
from config import settings
from data.calendar import EconomicCalendar
from journal.writer import JournalWriter
from risk.gate import RiskCheckResult, RiskGate
from signals.engine import TradeSignal

logger = logging.getLogger(__name__)

PAIR_CURRENCIES = {
    "frxEURUSD": {"EUR", "USD"},
    "frxGBPUSD": {"GBP", "USD"},
    "frxUSDJPY": {"USD", "JPY"},
    "frxAUDUSD": {"AUD", "USD"},
}


@dataclass
class AnalysisSnapshot:
    passed: bool
    decision: str  # GO | NO-GO
    run_type: str
    reasons: list[str] = field(default_factory=list)
    sources: dict[str, Any] = field(default_factory=dict)
    symbol: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "decision": self.decision,
            "run_type": self.run_type,
            "reasons": self.reasons,
            "sources": self.sources,
            "symbol": self.symbol,
        }


class AnalysisEngine:
    def __init__(
        self,
        journal: JournalWriter,
        calendar: EconomicCalendar,
        risk: RiskGate,
    ) -> None:
        self.journal = journal
        self.calendar = calendar
        self.risk = risk
        self.analysis_armed = False
        self.last_preflight: Optional[dict] = None
        self.ai_decision: Optional[dict] = None

    def disarm(self, reason: str = "manual") -> None:
        self.analysis_armed = False
        logger.info("Analysis disarmed: %s", reason)

    def set_ai_decision(self, decision: dict) -> None:
        self.ai_decision = decision

    async def fetch_ai_decision(self) -> Optional[dict]:
        if self.ai_decision:
            return self.ai_decision
        return await self.fetch_ai_decision_from_url()

    async def fetch_ai_decision_from_url(self) -> Optional[dict]:
        url = settings.ANALYSIS_AI_DECISION_URL.strip()
        if not url:
            return None
        headers = {}
        if settings.BACKEND_API_KEY:
            headers["Authorization"] = f"Bearer {settings.BACKEND_API_KEY}"
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(url, headers=headers)
                if resp.status_code == 200:
                    body = resp.json()
                    self.ai_decision = body.get("data", body)
                    return self.ai_decision
        except Exception:
            logger.exception("Failed to fetch AI analysis decision")
        return None

    def _news_for_symbol(self, symbol: str) -> tuple[bool, str]:
        currencies = PAIR_CURRENCIES.get(symbol, set())
        paused, reason = self.calendar.is_paused_for_currencies(currencies)
        if paused:
            return True, f"{reason} (pair {symbol})" if symbol else reason
        return False, ""

    async def run_preflight(
        self,
        client=None,
        symbols: list[str] | None = None,
    ) -> AnalysisSnapshot:
        reasons: list[str] = []
        sources: dict[str, Any] = {}
        pairs = symbols or settings.pairs_list

        await self.calendar.refresh()
        sources["news_events_loaded"] = len(self.calendar._events)
        sources["upcoming_high_impact"] = [
            {"title": e.title, "currency": e.currency, "time": e.event_time.isoformat()}
            for e in self.calendar.upcoming_high_impact(24)
        ]
        sources["preflight_pairs"] = pairs

        metrics = compute_metrics()
        sources["metrics"] = metrics
        if self.risk.kill_switch_active:
            reasons.append("kill_switch_active")

        runner = BacktestRunner()
        if client and settings.DERIV_API_TOKEN:
            backtest = {}
            for symbol in pairs:
                try:
                    candles = await client.get_candles_history(
                        symbol,
                        settings.granularity_seconds,
                        settings.ANALYSIS_PREFLIGHT_BACKTEST_BARS,
                    )
                    df = pd.DataFrame(candles)
                    backtest[symbol] = runner.run_on_dataframe(symbol, df).to_dict()
                except Exception as exc:
                    backtest[symbol] = {"error": str(exc), "passed": False}
        else:
            backtest = await runner.run_all_pairs()
            backtest = {s: backtest[s] for s in pairs if s in backtest}

        sources["backtest"] = backtest
        for symbol, result in backtest.items():
            if result.get("error"):
                reasons.append(f"backtest_error_{symbol}")
            elif not result.get("passed"):
                reasons.append(f"backtest_failed_{symbol}")

        ai = await self.fetch_ai_decision()
        if ai:
            sources["ai_decision"] = ai
            if ai.get("decision") == "NO-GO":
                reasons.append(f"ai_no_go: {ai.get('summary', '')[:120]}")

        passed = len(reasons) == 0
        snapshot = AnalysisSnapshot(
            passed=passed,
            decision="GO" if passed else "NO-GO",
            run_type="preflight",
            reasons=reasons or ["all_checks_passed"],
            sources=sources,
        )
        self.journal.log_analysis_run(snapshot)
        self.last_preflight = snapshot.to_dict()
        self.analysis_armed = passed and settings.ANALYSIS_REQUIRE_PREFLIGHT
        if not settings.ANALYSIS_REQUIRE_PREFLIGHT:
            self.analysis_armed = passed
        logger.info("Preflight %s armed=%s reasons=%s", snapshot.decision, self.analysis_armed, reasons)
        return snapshot

    def evaluate_open(
        self,
        signal: TradeSignal,
        df: pd.DataFrame,
        risk: RiskCheckResult,
    ) -> AnalysisSnapshot:
        reasons: list[str] = []
        sources: dict[str, Any] = {
            "signal": signal.to_dict(),
            "risk": risk.to_dict(),
        }

        if settings.ANALYSIS_REQUIRE_PREFLIGHT and not self.analysis_armed:
            reasons.append("preflight_not_passed")

        news_paused, news_reason = self._news_for_symbol(signal.symbol)
        sources["news_paused"] = news_paused
        if news_paused:
            reasons.append(news_reason or "news_paused")

        scenario: OpenScenarioResult = simulate_sl_tp_window(df, signal)
        sources["open_scenario"] = {
            "passed": scenario.passed,
            "win_rate": scenario.win_rate,
            "expected_value": scenario.expected_value,
            "simulated_trades": scenario.simulated_trades,
            "details": scenario.details,
        }
        if not scenario.passed:
            reasons.append(scenario.reason)

        htf_ok, htf_reason = higher_timeframe_aligned(df, signal.direction.value)
        sources["multi_timeframe"] = {"aligned": htf_ok, "reason": htf_reason}
        if not htf_ok:
            reasons.append(htf_reason)

        passed = len(reasons) == 0
        snapshot = AnalysisSnapshot(
            passed=passed,
            decision="GO" if passed else "NO-GO",
            run_type="open",
            reasons=reasons or ["open_analysis_passed"],
            sources=sources,
            symbol=signal.symbol,
        )
        self.journal.log_analysis_run(snapshot)
        return snapshot

    def evaluate_close(
        self,
        position: dict,
        df: pd.DataFrame,
        *,
        force_eod: bool = False,
    ) -> AnalysisSnapshot:
        symbol = position.get("underlying") or position.get("symbol") or ""
        news_paused, news_reason = self._news_for_symbol(symbol) if symbol else (False, "")

        scenario: CloseScenarioResult = evaluate_close(
            position,
            df,
            force_eod=force_eod,
            news_paused=news_paused,
            news_reason=news_reason,
        )
        sources = {
            "position": position,
            "close_scenario": {
                "passed": scenario.passed,
                "reason": scenario.reason,
                "details": scenario.details,
            },
        }
        reasons = [] if scenario.passed else [scenario.reason]
        snapshot = AnalysisSnapshot(
            passed=scenario.passed,
            decision="GO" if scenario.passed else "NO-GO",
            run_type="close",
            reasons=reasons or [scenario.reason],
            sources=sources,
            symbol=symbol or None,
        )
        self.journal.log_analysis_run(snapshot)
        return snapshot

    def source_status(self) -> dict[str, str]:
        return {
            "deriv": "online" if settings.DERIV_API_TOKEN else "offline_no_token",
            "forex_factory": "loaded" if self.calendar._events else "not_loaded",
            "journal": "online",
            "backtest": "available",
            "preflight": "GO" if self.analysis_armed else "NO-GO",
            "ai_decision": self.ai_decision.get("decision", "none") if self.ai_decision else "none",
        }
