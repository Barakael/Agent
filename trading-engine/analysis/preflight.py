"""Daily preflight runner."""

from __future__ import annotations

from analysis.engine import AnalysisEngine, AnalysisSnapshot


async def run_daily_preflight(engine: AnalysisEngine, client=None) -> AnalysisSnapshot:
    return await engine.run_preflight(client=client)
