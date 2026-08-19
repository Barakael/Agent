"""FastAPI control plane for the trading engine."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from analytics.metrics import compute_metrics
from backtest.runner import BacktestRunner
from bot import TradingBot
from config import settings
from journal.writer import JournalWriter
from execution.orders import UnencodableStop
from risk.gate import RiskGate

logging.basicConfig(
    level=logging.INFO if settings.DEBUG else logging.WARNING,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("trading-engine")

bot: TradingBot | None = None
journal = JournalWriter()
security = HTTPBearer(auto_error=False)


def validate_api_key(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> bool:
    if not settings.TRADING_SERVICE_API_KEY:
        return True
    if (
        credentials is None
        or credentials.scheme.lower() != "bearer"
        or credentials.credentials != settings.TRADING_SERVICE_API_KEY
    ):
        raise HTTPException(status_code=401, detail="Unauthorized")
    return True


@asynccontextmanager
async def lifespan(app: FastAPI):
    global bot
    bot = TradingBot()
    try:
        journal.update_bot_state("stopped", settings.TRADING_MODE, 0.0)
    except Exception:
        logger.exception("Could not update bot state on startup — continuing")
    if settings.AUTO_START_BOT:
        # Start in background so uvicorn binds immediately (preflight can take minutes)
        async def _auto_start() -> None:
            try:
                await bot.start()
                logger.info("AUTO_START_BOT: trading loop started")
            except Exception:
                logger.exception(
                    "AUTO_START_BOT failed — API is up; call POST /start when ready"
                )

        asyncio.create_task(_auto_start())
    yield
    if bot:
        await bot.stop()


app = FastAPI(
    title=settings.API_TITLE,
    version=settings.API_VERSION,
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ManualOrderRequest(BaseModel):
    symbol: str
    direction: str = Field(..., pattern="^(buy|sell)$")
    stake: float = Field(..., gt=0)
    stop_loss: float = Field(..., gt=0)
    take_profit: float = Field(..., gt=0)


@app.get("/health")
async def health(auth: bool = Depends(validate_api_key)):
    return {
        "status": "ok",
        "version": settings.API_VERSION,
        "mode": settings.TRADING_MODE,
        "bot_state": bot.state if bot else "stopped",
        "analysis_armed": bot.analysis_armed if bot else False,
    }


@app.get("/status")
async def status(auth: bool = Depends(validate_api_key)):
    if bot is None:
        return {"state": "stopped", "mode": settings.TRADING_MODE, "not_configured": True}
    await bot.probe_deriv_account()
    return bot.status()


@app.get("/preflight/latest")
async def preflight_latest(auth: bool = Depends(validate_api_key)):
    latest = journal.get_latest_preflight()
    armed = bot.analysis_armed if bot else False
    return {"data": latest, "analysis_armed": armed}


@app.post("/preflight")
async def run_preflight(auth: bool = Depends(validate_api_key)):
    if bot is None:
        raise HTTPException(status_code=503, detail="Bot not initialized")
    try:
        result = await bot.run_preflight()
        return {"data": result, "analysis_armed": bot.analysis_armed}
    except Exception as exc:
        logger.exception("Preflight failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/analysis/sources")
async def analysis_sources(auth: bool = Depends(validate_api_key)):
    if bot is None:
        return {"data": {}}
    return {"data": bot.analysis.source_status()}


@app.get("/analysis/snapshots")
async def analysis_snapshots(auth: bool = Depends(validate_api_key)):
    """Live Number Engine snapshots per pair — prove Deriv feed + analysis without waiting for fills."""
    if bot is None:
        return {"data": []}
    return {"data": bot.get_analysis_snapshots()}


@app.get("/analysis/horizon-reviews")
async def horizon_reviews(auth: bool = Depends(validate_api_key)):
    """Independent mid (4/6h) and 8h trade-stance reviews (advisory only)."""
    if bot is None:
        return {"data": []}
    return {"data": bot.get_horizon_reviews()}


@app.get("/analysis/bias-feature-report")
async def bias_feature_report(
    min_n: int = 1,
    auth: bool = Depends(validate_api_key),
):
    """Phase 3: empirical WR by regime/bias/confirm (no auto-weight)."""
    from scripts.bias_feature_report import build_report

    return {"data": build_report(min_n=max(1, min_n))}


@app.get("/analysis/market-brief")
async def market_brief(auth: bool = Depends(validate_api_key)):
    """Live multi-source brief for Cursor Automations (prices, calendar, headlines, fitness)."""
    from analysis.market_brief import build_market_brief

    try:
        brief = await build_market_brief(bot=bot)
    except Exception as exc:
        logger.exception("Market brief failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"data": brief}


class AiDecisionRequest(BaseModel):
    decision: str
    summary: str = ""
    reasons: list = Field(default_factory=list)
    risks: list = Field(default_factory=list)
    source: str = "ai-agent"
    recommended_trade_mode: str | None = None
    pairs: list[str] = Field(default_factory=list)
    enabled_strategies: list[str] = Field(default_factory=list)
    directional_bias: str | None = None
    hold_policy: str | None = None
    confidence: int | None = None
    recommendation: dict = Field(default_factory=dict)


@app.post("/analysis/ai-decision")
async def set_ai_decision(body: AiDecisionRequest, auth: bool = Depends(validate_api_key)):
    if bot is None:
        raise HTTPException(status_code=503, detail="Bot not initialized")
    bot.analysis.set_ai_decision(body.model_dump())
    return {"status": "ok", "decision": body.decision}


@app.get("/positions")
async def positions(auth: bool = Depends(validate_api_key)):
    if bot is None:
        return {"data": []}
    await bot.positions.refresh()
    return {"data": bot.positions.to_api_list()}


@app.get("/journal")
async def journal_list(limit: int = 50, offset: int = 0, auth: bool = Depends(validate_api_key)):
    return {"data": journal.get_trades(limit=limit, offset=offset)}


@app.get("/journal/day-review")
async def journal_day_review(day: str | None = None, auth: bool = Depends(validate_api_key)):
    """Internal/debug day stats (may include row detail). Not for OpenAI."""
    return {"data": journal.get_day_review_payload(day)}


@app.get("/journal/evening-ai-payload")
async def journal_evening_ai_payload(day: str | None = None, auth: bool = Depends(validate_api_key)):
    """Privacy-safe aggregates only — safe to send to OpenAI evening review."""
    return {"data": journal.get_evening_ai_payload(day)}


class EveningReviewSaveRequest(BaseModel):
    date: str
    markdown: str
    summary: str = ""
    best_strategy: str | None = None
    worst_strategy: str | None = None
    answers: dict = Field(default_factory=dict)
    experiments: list[str] = Field(default_factory=list)


@app.post("/journal/evening-review")
async def save_evening_review(body: EveningReviewSaveRequest, auth: bool = Depends(validate_api_key)):
    """Persist evening learning review markdown under reports/reviews."""
    from pathlib import Path

    reviews_dir = Path(__file__).resolve().parent / "reports" / "reviews"
    reviews_dir.mkdir(parents=True, exist_ok=True)
    path = reviews_dir / f"evening_review_{body.date}.md"
    header = (
        f"<!-- evening-review date={body.date} "
        f"best={body.best_strategy or ''} worst={body.worst_strategy or ''} -->\n\n"
    )
    path.write_text(header + body.markdown, encoding="utf-8")
    return {"status": "ok", "file": path.name, "path": str(path)}


@app.get("/metrics")
async def metrics(auth: bool = Depends(validate_api_key)):
    return {"data": compute_metrics()}


@app.post("/pause")
async def pause(auth: bool = Depends(validate_api_key)):
    if bot:
        bot.pause()
    return {"status": "paused"}


@app.post("/resume")
async def resume(auth: bool = Depends(validate_api_key)):
    if bot:
        bot.resume()
    return {"status": "resumed"}


@app.post("/kill")
async def kill(auth: bool = Depends(validate_api_key)):
    if bot:
        bot.kill("api_kill")
    return {"status": "killed"}


@app.post("/start")
async def start_bot(auth: bool = Depends(validate_api_key)):
    if bot is None:
        raise HTTPException(status_code=503, detail="Bot not initialized")
    try:
        await bot.start()
    except Exception as exc:
        logger.exception("Bot start failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {
        "status": "running",
        "analysis_armed": bot.analysis_armed,
        "account_error": bot._account_probe_error,
        "deriv_connected": bot.client._authorized,
    }


@app.post("/stop")
async def stop_bot(auth: bool = Depends(validate_api_key)):
    if bot:
        await bot.stop()
    return {"status": "stopped"}


@app.post("/orders")
async def manual_order(body: ManualOrderRequest, auth: bool = Depends(validate_api_key)):
    gate = RiskGate()
    check = gate.validate_manual_order(body.stop_loss, body.take_profit, body.stake)
    if check.decision.value != "approved":
        raise HTTPException(status_code=403, detail=check.reason)
    if bot is None:
        raise HTTPException(status_code=503, detail="Bot not available")
    entry = None
    df = bot.aggregator.get_dataframe(body.symbol)
    if df is not None and len(df):
        entry = float(df["close"].iloc[-1])
    try:
        result = await bot.executor.execute_manual(
            body.symbol,
            body.direction,
            body.stake,
            body.stop_loss,
            body.take_profit,
            entry=entry,
        )
    except UnencodableStop as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"status": "placed", "data": result}


@app.post("/positions/{contract_id}/close")
async def close_position(contract_id: int, auth: bool = Depends(validate_api_key)):
    if bot is None:
        raise HTTPException(status_code=503, detail="Bot not available")
    await bot.positions.refresh()
    pos = next((p for p in bot.positions.positions if p.get("contract_id") == contract_id), {})
    symbol = pos.get("underlying") or pos.get("symbol") or ""
    df = bot.aggregator.get_dataframe(symbol) if symbol else None
    try:
        result = await bot.positions.close_position(contract_id, df=df)
    except RuntimeError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {"status": "closed", "data": result}


@app.post("/positions/close-all")
async def close_all(auth: bool = Depends(validate_api_key)):
    if bot is None:
        raise HTTPException(status_code=503, detail="Bot not available")
    dfs = {s: bot.aggregator.get_dataframe(s) for s in settings.pairs_list}
    results = await bot.positions.close_all(force=True, df_by_symbol=dfs)
    return {"status": "closed", "count": len(results)}


@app.post("/backtest")
async def run_backtest(auth: bool = Depends(validate_api_key)):
    runner = BacktestRunner()
    results = await runner.run_all_pairs()
    return {"data": results}


class DailyPlanRequest(BaseModel):
    date: str
    pairs: list[str]
    strategy_id: str = "momentum"
    enabled_strategies: list[str] | None = None
    trade_mode: str = "pattern"
    directional_bias: str = "neutral"
    hold_policy: str = "intraday"
    max_hold_days: int = 1
    sl_pips: int = 15
    tp_pips: int = 30
    risk_percent: float = 1.5
    max_stake_usd: float = 25.0
    confidence: int = 50
    notes: str = ""
    source: str = "cursor-automation"


@app.get("/plan/active")
async def get_active_plan(auth: bool = Depends(validate_api_key)):
    if bot is None:
        return {"data": None}
    plan = bot.get_active_plan()
    stored = bot.plan_store.load()
    return {
        "data": plan.to_dict() if plan else None,
        "stored": stored.to_dict() if stored else None,
        "active_for_today": plan is not None,
    }


@app.put("/plan/active")
async def put_active_plan(body: DailyPlanRequest, auth: bool = Depends(validate_api_key)):
    if bot is None:
        raise HTTPException(status_code=503, detail="Bot not initialized")
    from plan.schema import clamp_plan_dict

    payload = body.model_dump(exclude_none=True)
    if not payload.get("enabled_strategies") and payload.get("strategy_id"):
        payload["enabled_strategies"] = [payload["strategy_id"]]
    try:
        clamped = clamp_plan_dict(payload)
        plan = bot.set_active_plan(clamped.to_dict())
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"status": "ok", "data": plan.to_dict(), "active_for_today": plan.is_active_for_today()}


@app.get("/candles/{symbol}")
async def get_candles(symbol: str, auth: bool = Depends(validate_api_key)):
    if bot is None:
        raise HTTPException(status_code=503, detail="Bot not available")
    df = bot.aggregator.get_dataframe(symbol)
    return {"symbol": symbol, "count": len(df), "candles": df.tail(20).to_dict(orient="records")}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host=settings.HOST, port=settings.PORT, reload=settings.DEBUG)
