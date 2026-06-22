"""Main trading bot loop — data ingestion, signals, risk, execution."""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from alerts.telegram import TelegramAlerter
from analytics.metrics import compute_metrics
from analysis.engine import AnalysisEngine
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
        self.journal = JournalWriter()
        self.calendar = EconomicCalendar()
        self.analysis = AnalysisEngine(self.journal, self.calendar, self.risk)
        self.executor = OrderExecutor(self.client)
        self.positions = PositionManager(
            self.client,
            journal=self.journal,
            risk=self.risk,
            close_gate=self._close_gate,
        )
        self.telegram = TelegramAlerter()
        self._running = False
        self._paused = False
        self._task: Optional[asyncio.Task] = None
        self._account_probed = False
        self._account_probe_error: Optional[str] = None

    @property
    def analysis_armed(self) -> bool:
        return self.analysis.analysis_armed

    @property
    def state(self) -> str:
        if self.risk.kill_switch_active:
            return "killed"
        if self._paused:
            return "paused"
        if self._running:
            return "running"
        return "stopped"

    async def _close_gate(self, position: dict, force_eod: bool = False, df=None) -> bool:
        if force_eod:
            snapshot = self.analysis.evaluate_close(position, df or __import__("pandas").DataFrame(), force_eod=True)
            return snapshot.passed
        symbol = position.get("underlying") or position.get("symbol") or ""
        if df is None:
            df = self.aggregator.get_dataframe(symbol)
        snapshot = self.analysis.evaluate_close(position, df, force_eod=False)
        if not snapshot.passed:
            logger.info("Close rejected %s: %s", symbol, snapshot.reasons)
        return snapshot.passed

    def pause(self) -> None:
        self._paused = True
        self.journal.update_bot_state("paused", settings.TRADING_MODE, self.risk.daily_pnl)

    def resume(self) -> None:
        if not self.risk.kill_switch_active:
            self._paused = False
            self.journal.update_bot_state("running", settings.TRADING_MODE, self.risk.daily_pnl)

    def kill(self, reason: str = "manual") -> None:
        self.risk.trigger_kill_switch(reason)
        self.analysis.disarm("kill_switch")
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
            await self._close_all_positions(force=True)
            return

        df = self.aggregator.get_dataframe(symbol)
        signal = self.signals.evaluate(symbol, df)
        if signal is None:
            return

        news_paused, news_reason = self.calendar.is_trading_paused()
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

        open_snapshot = self.analysis.evaluate_open(signal, df, risk_result)
        if not open_snapshot.passed:
            self.journal.log_signal_rejected(signal, "; ".join(open_snapshot.reasons))
            logger.info("Analysis rejected open %s: %s", symbol, open_snapshot.reasons)
            return

        if settings.TRADING_MODE == "log_only":
            logger.info(
                "SIGNAL %s %s @ %.5f RSI=%.1f — %s [analysis GO]",
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

        if settings.ANALYSIS_REQUIRE_PREFLIGHT and not self.analysis_armed:
            self.journal.log_signal_rejected(signal, "preflight_not_armed")
            return

        order = await self.executor.execute_signal(signal, risk_result)
        contract_id = str(order.get("contract_id", "")) if order else None
        self.journal.log_trade_open(signal, risk_result, contract_id, settings.TRADING_MODE)
        await self.telegram.trade_opened(
            symbol, signal.direction.value, risk_result.stake, settings.TRADING_MODE
        )

    async def _close_all_positions(self, force: bool = False) -> None:
        dfs = {s: self.aggregator.get_dataframe(s) for s in settings.pairs_list}
        await self.positions.close_all(force=force, df_by_symbol=dfs)

    async def _session_watchdog(self) -> None:
        while self._running:
            if self.session.must_force_close():
                logger.warning("End of session — force closing all positions")
                await self._close_all_positions(force=True)
                metrics = compute_metrics()
                await self.telegram.daily_summary(self.risk.daily_pnl, metrics)
            await asyncio.sleep(60)

    async def probe_deriv_account(self) -> None:
        if self._account_probed or self._running or not settings.DERIV_API_TOKEN:
            return
        self._account_probed = True
        try:
            await self.client.connect()
            await self.client.authorize()
            self._account_probe_error = None
        except Exception as exc:
            self._account_probe_error = str(exc)
            logger.warning("Deriv account probe failed: %s", exc)
        finally:
            if not self._running:
                await self.client.disconnect()

    async def run_preflight(self) -> dict:
        client = self.client if self._running and self.client._ws else None
        if not client and settings.DERIV_API_TOKEN:
            await self.client.connect()
            try:
                await self.client.authorize()
                snapshot = await self.analysis.run_preflight(client=self.client)
            finally:
                if not self._running:
                    await self.client.disconnect()
            return snapshot.to_dict()
        snapshot = await self.analysis.run_preflight(client=client)
        return snapshot.to_dict()

    async def start(self) -> None:
        if self._running:
            return

        deriv_connected = False
        market_data_only = False
        if settings.DERIV_API_TOKEN:
            try:
                await self.client.connect()
                auth = await self.client.authorize()
                if self.client.market_data_only:
                    market_data_only = True
                    self._account_probe_error = (
                        "PAT not active on Deriv yet — running on public market data only. "
                        "Complete partner profile at developers.deriv.com, then create a new "
                        "token with Trade + Account management scopes."
                    )
                    self.risk.reset_session(10000.0)
                else:
                    self.risk.reset_session(float(auth.get("balance", 10000)))
                    deriv_connected = True
                    self._account_probe_error = None
            except Exception as exc:
                self._account_probe_error = self._format_deriv_error(exc)
                logger.exception("Deriv connection failed at start")
                if settings.TRADING_MODE != "log_only":
                    raise RuntimeError(self._account_probe_error) from exc
                self.risk.reset_session(10000.0)
                logger.warning(
                    "Starting log_only without Deriv — fix DERIV_API_TOKEN / DERIV_APP_ID"
                )
        else:
            self.risk.reset_session(10000.0)
            self._account_probe_error = "DERIV_API_TOKEN not set"
            logger.warning("No DERIV_API_TOKEN — running in offline/simulated mode")

        await self.calendar.refresh()
        try:
            await self.run_preflight()
        except Exception:
            logger.exception("Preflight failed on start — bot will not arm")

        if deriv_connected or market_data_only or self.client._ws is not None:
            for symbol in settings.pairs_list:
                try:
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
        logger.info(
            "Trading bot started mode=%s armed=%s deriv=%s pairs=%s",
            settings.TRADING_MODE,
            self.analysis_armed,
            deriv_connected,
            settings.pairs_list,
        )

    @staticmethod
    def _format_deriv_error(exc: Exception) -> str:
        msg = str(exc)
        if "InvalidToken" in msg or "invalid" in msg.lower():
            return (
                "Deriv token invalid or expired. Create a new demo PAT at "
                "developers.deriv.com → API tokens (select Demo account)."
            )
        if "401" in msg:
            return (
                "Deriv WebSocket rejected connection. Set DERIV_WS_APP_ID=1089 in .env "
                "(DERIV_APP_ID UUID is for REST only, not legacy WebSocket)."
            )
        return msg

    async def stop(self) -> None:
        self._running = False
        self.analysis.disarm("bot_stopped")
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
        preflight = self.analysis.last_preflight or self.journal.get_latest_preflight()
        return {
            "state": self.state,
            "mode": settings.TRADING_MODE,
            "pairs": settings.pairs_list,
            "daily_pnl": self.risk.daily_pnl,
            "kill_switch_active": self.risk.kill_switch_active,
            "balance": self.client.balance,
            "loginid": self.client.loginid,
            "is_demo": self.client.is_demo,
            "account_type": "demo" if self.client.is_demo else "live",
            "account_error": self._account_probe_error,
            "analysis_armed": self.analysis_armed,
            "preflight": preflight,
            "sources": self.analysis.source_status(),
            "session": self.session.session_status(),
            "last_heartbeat": bot_state.get("last_heartbeat"),
        }
