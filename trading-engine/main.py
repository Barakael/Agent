"""FastAPI control plane for the trading engine."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any, Dict, Optional

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from analytics.metrics import compute_metrics
from backtest.runner import BacktestRunner
from bot import TradingBot
from config import settings
from journal.writer import JournalWriter
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
    journal.update_bot_state("stopped", settings.TRADING_MODE, 0.0)
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
    }


@app.get("/status")
async def status(auth: bool = Depends(validate_api_key)):
    if bot is None:
        return {"state": "stopped", "mode": settings.TRADING_MODE, "not_configured": True}
    return bot.status()


@app.get("/positions")
async def positions(auth: bool = Depends(validate_api_key)):
    if bot is None:
        return {"data": []}
    await bot.positions.refresh()
    return {"data": bot.positions.to_api_list()}


@app.get("/journal")
async def journal_list(limit: int = 50, offset: int = 0, auth: bool = Depends(validate_api_key)):
    return {"data": journal.get_trades(limit=limit, offset=offset)}


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
    await bot.start()
    return {"status": "running"}


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
    result = await bot.executor.execute_manual(
        body.symbol,
        body.direction,
        body.stake,
        body.stop_loss,
        body.take_profit,
    )
    return {"status": "placed", "data": result}


@app.post("/positions/{contract_id}/close")
async def close_position(contract_id: int, auth: bool = Depends(validate_api_key)):
    if bot is None:
        raise HTTPException(status_code=503, detail="Bot not available")
    result = await bot.positions.close_position(contract_id)
    return {"status": "closed", "data": result}


@app.post("/positions/close-all")
async def close_all(auth: bool = Depends(validate_api_key)):
    if bot is None:
        raise HTTPException(status_code=503, detail="Bot not available")
    results = await bot.positions.close_all()
    return {"status": "closed", "count": len(results)}


@app.post("/backtest")
async def run_backtest(auth: bool = Depends(validate_api_key)):
    runner = BacktestRunner()
    results = await runner.run_all_pairs()
    return {"data": results}


@app.get("/candles/{symbol}")
async def get_candles(symbol: str, auth: bool = Depends(validate_api_key)):
    """Return aggregated candles for chart verification (A1 gate)."""
    if bot is None:
        raise HTTPException(status_code=503, detail="Bot not available")
    df = bot.aggregator.get_dataframe(symbol)
    return {"symbol": symbol, "count": len(df), "candles": df.tail(20).to_dict(orient="records")}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host=settings.HOST, port=settings.PORT, reload=settings.DEBUG)
