"""Main trading bot loop — data ingestion, signals, risk, execution."""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from alerts.telegram import TelegramAlerter
from analytics.metrics import compute_metrics
from config import settings
from data.calendar import EconomicCalendar
from data.candle_aggregator import CandleAggregator
from data.deriv_ws import DerivWebSocketClient
from execution.orders import OrderExecutor
from execution.positions import PositionManager
from journal.writer import JournalWriter
from risk.gate import RiskDecision, RiskGate
from risk.session import SessionManager
from signals.engine import SignalEngine

logger = logging.getLogger(__name__)


class TradingBot:
    def __init__(self) -> None:
        self.client = DerivWebSocketClient()
        self.aggregator = CandleAggregator(
            timeframe_minutes=settings.CANDLE_TIMEFRAME_MINUTES,
            buffer_size=settings.CANDLE_BUFFER_SIZE,
        )
        self.signals = SignalEngine()
        self.risk = RiskGate()
        self.session = SessionManager()
        self.executor = OrderExecutor(self.client)
        self.positions = PositionManager(self.client)
        self.journal = JournalWriter()
        self.calendar = EconomicCalendar()
        self.telegram = TelegramAlerter()
        self._running = False
        self._paused = False
        self._task: Optional[asyncio.Task] = None

    @property
    def state(self) -> str:
        if self.risk.kill_switch_active:
            return "killed"
        if self._paused:
            return "paused"
        if self._running:
            return "running"
        return "stopped"

    def pause(self) -> None:
        self._paused = True
        self.journal.update_bot_state("paused", settings.TRADING_MODE, self.risk.daily_pnl)

    def resume(self) -> None:
        if not self.risk.kill_switch_active:
            self._paused = False
            self.journal.update_bot_state("running", settings.TRADING_MODE, self.risk.daily_pnl)

    def kill(self, reason: str = "manual") -> None:
        self.risk.trigger_kill_switch(reason)
        self._paused = True
        self.journal.update_bot_state("killed", settings.TRADING_MODE, self.risk.daily_pnl)

    def _on_tick(self, symbol: str, price: float, epoch: int) -> None:
        closed = self.aggregator.on_tick(symbol, price, epoch)
        if closed is not None:
            asyncio.create_task(self._on_candle_close(symbol))

    async def _on_candle_close(self, symbol: str) -> None:
        if self._paused or not self._running:
            return

        if self.session.must_force_close():
            await self.positions.close_all()
            return

        news_paused, news_reason = self.calendar.is_trading_paused()
        df = self.aggregator.get_dataframe(symbol)
        signal = self.signals.evaluate(symbol, df)
        if signal is None:
            return

        risk_result = self.risk.evaluate(
            signal,
            self.client.balance,
            trading_paused=self._paused,
            news_paused=news_paused,
        )
        self.journal.log_signal(signal, risk_result)

        if risk_result.decision != RiskDecision.APPROVED:
            logger.info("Signal rejected %s: %s", symbol, risk_result.reason)
            return

        if settings.TRADING_MODE == "log_only":
            logger.info(
                "SIGNAL %s %s @ %.5f RSI=%.1f — %s",
                signal.direction.value,
                symbol,
                signal.price,
                signal.rsi,
                signal.reason,
            )
            self.journal.log_trade_open(signal, risk_result, mode="log_only")
            await self.telegram.trade_opened(
                symbol, signal.direction.value, risk_result.stake, "log_only"
            )
            return

        if not self.session.is_session_open():
            return

        order = await self.executor.execute_signal(signal, risk_result)
        contract_id = str(order.get("contract_id", "")) if order else None
        self.journal.log_trade_open(signal, risk_result, contract_id, settings.TRADING_MODE)
        await self.telegram.trade_opened(
            symbol, signal.direction.value, risk_result.stake, settings.TRADING_MODE
        )

    async def _session_watchdog(self) -> None:
        while self._running:
            if self.session.must_force_close():
                logger.warning("End of session — force closing all positions")
                await self.positions.close_all()
                metrics = compute_metrics()
                await self.telegram.daily_summary(self.risk.daily_pnl, metrics)
            await asyncio.sleep(60)

    async def start(self) -> None:
        if self._running:
            return
        await self.client.connect()
        if settings.DERIV_API_TOKEN:
            auth = await self.client.authorize()
            self.risk.reset_session(float(auth.get("balance", 10000)))
        else:
            self.risk.reset_session(10000.0)
            logger.warning("No DERIV_API_TOKEN — running in offline/simulated mode")

        await self.calendar.refresh()

        for symbol in settings.pairs_list:
            try:
                if settings.DERIV_API_TOKEN:
                    history = await self.client.get_candles_history(
                        symbol, settings.granularity_seconds, settings.CANDLE_BUFFER_SIZE
                    )
                    self.aggregator.load_historical_candles(symbol, history)
                    await self.client.subscribe_ticks(symbol)
            except Exception:
                logger.exception("Failed to init symbol %s", symbol)

        self.client.on_tick(self._on_tick)
        self._running = True
        self._paused = False
        self.journal.update_bot_state("running", settings.TRADING_MODE, self.risk.daily_pnl)
        self._task = asyncio.create_task(self._session_watchdog())
        logger.info("Trading bot started mode=%s pairs=%s", settings.TRADING_MODE, settings.pairs_list)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        await self.client.disconnect()
        self.journal.update_bot_state("stopped", settings.TRADING_MODE, self.risk.daily_pnl)

    def status(self) -> dict:
        bot_state = self.journal.get_bot_state()
        return {
            "state": self.state,
            "mode": settings.TRADING_MODE,
            "pairs": settings.pairs_list,
            "daily_pnl": self.risk.daily_pnl,
            "kill_switch_active": self.risk.kill_switch_active,
            "balance": self.client.balance,
            "session": self.session.session_status(),
            "last_heartbeat": bot_state.get("last_heartbeat"),
        }
