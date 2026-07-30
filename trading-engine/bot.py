"""Main trading bot loop — data ingestion, signals, risk, execution."""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from alerts.telegram import TelegramAlerter
from analytics.metrics import compute_metrics
from analysis.engine import AnalysisEngine
from analysis.multi_timeframe import higher_timeframe_aligned
from config import settings
from data.calendar import EconomicCalendar
from data.candle_aggregator import CandleAggregator
from data.deriv_ws import DerivWebSocketClient
from execution.orders import OrderExecutor
from execution.positions import PositionManager
from journal.writer import JournalWriter
from number_engine import NumberEngine
from plan.store import plan_store
from plan.schema import DailyPlan
from risk.gate import RiskDecision, RiskGate, is_synthetic_symbol
from risk.session import SessionManager
from signals.engine import SignalEngine
from strategies import (
    PATTERN_STRATEGY_IDS,
    allowlist_strategy_ids,
    apply_strategy_allowlist,
    evaluate_strategies_detailed,
)
from strategies.base import StrategyContext

logger = logging.getLogger(__name__)


class TradingBot:
    def __init__(self) -> None:
        self.client = DerivWebSocketClient()
        self.aggregator = CandleAggregator(
            timeframe_minutes=settings.CANDLE_TIMEFRAME_MINUTES,
            buffer_size=settings.CANDLE_BUFFER_SIZE,
        )
        self.signals = SignalEngine()
        self.number_engine = NumberEngine()
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
        self._feed_task: Optional[asyncio.Task] = None
        self._subscribed_symbols: set[str] = set()
        self._last_analysis: dict[str, dict] = {}
        self._last_tick_epoch: dict[str, int] = {}
        self._account_probed = False
        self._account_probe_error: Optional[str] = None
        self.plan_store = plan_store

    def get_active_plan(self) -> Optional[DailyPlan]:
        plan = self.plan_store.load()
        if plan and plan.is_active_for_today():
            return plan
        return None

    @property
    def active_pairs(self) -> list[str]:
        plan = self.get_active_plan()
        if plan:
            return list(plan.pairs)
        return settings.pairs_list

    def set_active_plan(self, raw: dict) -> DailyPlan:
        return self.plan_store.save_dict(raw)

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
        # Operator resume also clears daily kill switch so trading can continue after a false trip
        if self.risk.kill_switch_active:
            self.risk._kill_switch_active = False
            logger.warning("Kill switch cleared by resume")
        self._paused = False
        self.journal.update_bot_state("running", settings.TRADING_MODE, self.risk.daily_pnl)

    def kill(self, reason: str = "manual") -> None:
        self.risk.trigger_kill_switch(reason)
        self.analysis.disarm("kill_switch")
        self._paused = True
        self.journal.update_bot_state("killed", settings.TRADING_MODE, self.risk.daily_pnl)

    def _on_tick(self, symbol: str, price: float, epoch: int) -> None:
        self._last_tick_epoch[symbol] = epoch
        closed = self.aggregator.on_tick(symbol, price, epoch)
        if closed is not None:
            asyncio.create_task(self._on_candle_close(symbol))

    def _record_analysis(
        self,
        symbol: str,
        *,
        price: float,
        regime: str,
        rsi: float,
        atr: float,
        epoch: int,
        bars: int,
        best_strategy: str | None,
        confidence: float,
        skip_reason: str | None,
        signal_direction: str | None,
    ) -> None:
        import time as _time

        now = int(_time.time())
        last_tick = self._last_tick_epoch.get(symbol, 0)
        self._last_analysis[symbol] = {
            "symbol": symbol,
            "price": price,
            "regime": regime,
            "rsi": round(rsi, 2) if rsi is not None else None,
            "atr": round(atr, 5) if atr is not None else None,
            "epoch": epoch,
            "bars": bars,
            "best_strategy": best_strategy,
            "confidence": round(confidence, 1),
            "skip_reason": skip_reason,
            "signal": signal_direction,
            "feed_ok": symbol in self._subscribed_symbols,
            "last_tick_age_sec": (now - last_tick) if last_tick else None,
            "updated_at": _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime()),
        }

    def get_analysis_snapshots(self) -> list[dict]:
        """Last Number Engine evaluation per active pair (for live UI)."""
        out: list[dict] = []
        for symbol in self.active_pairs:
            if symbol in self._last_analysis:
                out.append(self._last_analysis[symbol])
            else:
                df = self.aggregator.get_dataframe(symbol)
                bars = len(df)
                last_tick = self._last_tick_epoch.get(symbol, 0)
                import time as _time

                now = int(_time.time())
                out.append(
                    {
                        "symbol": symbol,
                        "price": float(df["close"].iloc[-1]) if bars else None,
                        "regime": None,
                        "rsi": None,
                        "atr": None,
                        "epoch": int(df["epoch"].iloc[-1]) if bars and "epoch" in df.columns else None,
                        "bars": bars,
                        "best_strategy": None,
                        "confidence": 0.0,
                        "skip_reason": "waiting_for_candle_close" if bars else "warming_up",
                        "signal": None,
                        "feed_ok": symbol in self._subscribed_symbols,
                        "last_tick_age_sec": (now - last_tick) if last_tick else None,
                        "updated_at": None,
                    }
                )
        return out

    async def _on_candle_close(self, symbol: str) -> None:
        if self._paused or not self._running:
            return

        plan = self.get_active_plan()
        if plan and symbol not in plan.pairs:
            return

        # EOD: close intraday positions but keep Number Engine evaluating
        if self.session.must_force_close():
            await self._close_all_positions(force=True, skip_swing=True)

        df = self.aggregator.get_dataframe(symbol)
        snapshot = self.number_engine.compute(symbol, df)
        if snapshot is None:
            self._record_analysis(
                symbol,
                price=float(df["close"].iloc[-1]) if len(df) else 0.0,
                regime="unknown",
                rsi=0.0,
                atr=0.0,
                epoch=int(df["epoch"].iloc[-1]) if len(df) and "epoch" in df.columns else 0,
                bars=len(df),
                best_strategy=None,
                confidence=0.0,
                skip_reason="insufficient_bars",
                signal_direction=None,
            )
            return

        ctx = StrategyContext(
            trade_mode=plan.trade_mode if plan else "pattern",
            directional_bias=plan.directional_bias if plan else "neutral",
            hold_policy=plan.hold_policy if plan else "intraday",
        )
        if plan:
            strategy_ids = apply_strategy_allowlist(plan.enabled_strategies)
        else:
            allowed = allowlist_strategy_ids()
            strategy_ids = allowed if allowed else list(PATTERN_STRATEGY_IDS)
        # Number Engine mode: Strategy Manager confidence is the filter, not ATAE armed set
        if settings.NUMBER_ENGINE_EXECUTION:
            armed_filter = None
        else:
            armed = self.analysis.armed_strategy_ids
            if plan and plan.trade_mode == "pattern":
                pattern_armed = {s for s in armed if s != "bias_swing"}
                armed_filter = pattern_armed if pattern_armed else None
            else:
                armed_filter = None

        manager_result = evaluate_strategies_detailed(
            symbol,
            df,
            strategy_ids,
            ctx,
            armed_ids=armed_filter,
            snapshot=snapshot,
        )
        signal = manager_result.signal
        evals = manager_result.evaluations or []
        best_eval = max(evals, key=lambda e: e.confidence, default=None) if evals else None
        best_conf = best_eval.confidence if best_eval else 0.0
        best_id = best_eval.strategy_id if best_eval else None

        if signal is None:
            self._record_analysis(
                symbol,
                price=snapshot.close,
                regime=manager_result.regime,
                rsi=snapshot.rsi,
                atr=snapshot.atr,
                epoch=snapshot.epoch,
                bars=len(df),
                best_strategy=best_id,
                confidence=best_conf,
                skip_reason=manager_result.skip_reason or "No trade",
                signal_direction=None,
            )
            # Always log skips when focused allowlist is on (otherwise silence hides why)
            should_log_skip = (
                bool(allowlist_strategy_ids())
                or best_conf >= 40.0
                or (
                    manager_result.skip_reason
                    and "confidence" in (manager_result.skip_reason or "").lower()
                )
            )
            if should_log_skip:
                self.journal.log_no_trade(
                    symbol=symbol,
                    price=snapshot.close,
                    epoch=snapshot.epoch,
                    regime=manager_result.regime,
                    reason=manager_result.skip_reason or "No trade",
                    evaluations=manager_result.evaluations,
                    rsi=snapshot.rsi,
                    macd=snapshot.macd,
                )
            logger.debug(
                "No trade %s regime=%s: %s",
                symbol,
                manager_result.regime,
                manager_result.skip_reason,
            )
            return

        # 15m HTF confirmation (Number Engine path)
        htf_ok, htf_reason = higher_timeframe_aligned(df, signal.direction.value)
        if not htf_ok:
            skip = f"htf_not_aligned:{htf_reason}"
            self._record_analysis(
                symbol,
                price=snapshot.close,
                regime=manager_result.regime,
                rsi=snapshot.rsi,
                atr=snapshot.atr,
                epoch=snapshot.epoch,
                bars=len(df),
                best_strategy=getattr(signal, "strategy_id", best_id),
                confidence=getattr(signal, "confidence", best_conf),
                skip_reason=skip,
                signal_direction=signal.direction.value,
            )
            self.journal.log_no_trade(
                symbol=symbol,
                price=snapshot.close,
                epoch=snapshot.epoch,
                regime=manager_result.regime,
                reason=skip,
                evaluations=manager_result.evaluations,
                rsi=snapshot.rsi,
                macd=snapshot.macd,
            )
            logger.info("HTF skip %s: %s", symbol, htf_reason)
            return

        self._record_analysis(
            symbol,
            price=snapshot.close,
            regime=manager_result.regime,
            rsi=snapshot.rsi,
            atr=snapshot.atr,
            epoch=snapshot.epoch,
            bars=len(df),
            best_strategy=getattr(signal, "strategy_id", best_id),
            confidence=getattr(signal, "confidence", best_conf),
            skip_reason=None,
            signal_direction=signal.direction.value,
        )

        # Bias: one open bias position per pair
        if getattr(signal, "trade_mode", "pattern") == "bias":
            await self.positions.refresh()
            for pos in self.positions.positions:
                psym = pos.get("underlying") or pos.get("symbol") or ""
                if psym == symbol:
                    logger.info("Bias skip %s — already open", symbol)
                    return

        # Cap concurrent opens (no stacking)
        max_open = int(getattr(settings, "MAX_OPEN_POSITIONS", 1) or 0)
        if max_open > 0:
            try:
                await self.positions.refresh()
            except Exception:
                logger.debug("Position refresh before max-open check failed", exc_info=True)
            open_count = len(self.positions.positions or [])
            if open_count >= max_open:
                skip = f"max_open_positions ({open_count}>={max_open})"
                cached = self._last_analysis.get(symbol)
                if cached:
                    cached["skip_reason"] = skip
                self.journal.log_signal_rejected(signal, skip)
                logger.info("Skip open %s: %s", symbol, skip)
                return

        news_paused, news_reason = self.calendar.is_trading_paused()
        if is_synthetic_symbol(symbol):
            news_paused = False
        sl_pips = plan.sl_pips if plan else None
        tp_pips = plan.tp_pips if plan else None
        max_stake = plan.max_stake_usd if plan else None
        if plan:
            self.risk.risk_percent = plan.risk_percent
        else:
            self.risk.risk_percent = settings.RISK_PERCENT_PER_TRADE

        risk_result = self.risk.evaluate(
            signal,
            self.client.balance,
            trading_paused=self._paused,
            news_paused=news_paused,
            sl_pips=sl_pips,
            tp_pips=tp_pips,
            max_stake_usd=max_stake,
        )
        self.journal.log_signal(signal, risk_result)

        if risk_result.decision != RiskDecision.APPROVED:
            logger.info("Signal rejected %s: %s", symbol, risk_result.reason)
            cached = self._last_analysis.get(symbol)
            if cached:
                cached["skip_reason"] = risk_result.reason
                cached["signal"] = signal.direction.value
            return

        if not settings.NUMBER_ENGINE_EXECUTION:
            open_snapshot = self.analysis.evaluate_open(signal, df, risk_result)
            if not open_snapshot.passed:
                self.journal.log_signal_rejected(signal, "; ".join(open_snapshot.reasons))
                logger.info("Analysis rejected open %s: %s", symbol, open_snapshot.reasons)
                return

        if settings.TRADING_MODE == "log_only":
            logger.info(
                "SIGNAL %s %s @ %.5f conf=%.0f RSI=%.1f — %s [number_engine]",
                signal.direction.value,
                symbol,
                signal.price,
                getattr(signal, "confidence", 0),
                signal.rsi,
                signal.reason,
            )
            self.journal.log_trade_open(signal, risk_result, mode="log_only")
            self.risk.record_trade_opened()
            await self.telegram.trade_opened(
                symbol, signal.direction.value, risk_result.stake, "log_only"
            )
            return

        hold = getattr(signal, "hold_policy", "intraday")
        if hold != "swing" and not self.session.is_session_open():
            return

        if (
            not settings.NUMBER_ENGINE_EXECUTION
            and settings.ANALYSIS_REQUIRE_PREFLIGHT
            and not self.analysis_armed
        ):
            self.journal.log_signal_rejected(signal, "preflight_not_armed")
            return

        try:
            order = await self.executor.execute_signal(signal, risk_result)
        except Exception as exc:
            msg = f"execution_failed: {exc}"
            logger.exception("Order execution failed %s", symbol)
            self.journal.log_signal_rejected(signal, msg[:500])
            cached = self._last_analysis.get(symbol)
            if cached:
                cached["skip_reason"] = msg[:200]
                cached["signal"] = signal.direction.value
            return

        contract_id = str(order.get("contract_id", "")) if order else None
        self.journal.log_trade_open(
            signal,
            risk_result,
            contract_id,
            settings.TRADING_MODE,
            stop_loss_usd=order.get("stop_loss_usd") if order else None,
            take_profit_usd=order.get("take_profit_usd") if order else None,
        )
        self.risk.record_trade_opened()
        if contract_id and hold == "swing":
            self.positions.mark_swing(int(order["contract_id"]) if order and order.get("contract_id") else 0)
        await self.telegram.trade_opened(
            symbol, signal.direction.value, risk_result.stake, settings.TRADING_MODE
        )

    async def _close_all_positions(self, force: bool = False, skip_swing: bool = False) -> None:
        dfs = {s: self.aggregator.get_dataframe(s) for s in settings.pairs_list}
        await self.positions.close_all(force=force, df_by_symbol=dfs, skip_swing=skip_swing)

    async def _session_watchdog(self) -> None:
        while self._running:
            try:
                if self.client._socket_alive():
                    await self.positions.refresh()
            except Exception:
                logger.debug("Session watchdog position refresh failed", exc_info=True)
            if self.session.must_force_close():
                logger.warning("End of session — force closing intraday positions (swing kept)")
                await self._close_all_positions(force=True, skip_swing=True)
                metrics = compute_metrics()
                await self.telegram.daily_summary(self.risk.daily_pnl, metrics)
            await asyncio.sleep(60)

    async def _ensure_symbol_feed(self, symbol: str) -> bool:
        """Load history + subscribe ticks. Returns True if ticks are live."""
        try:
            history = await self.client.get_candles_history(
                symbol, settings.granularity_seconds, settings.CANDLE_BUFFER_SIZE
            )
            self.aggregator.load_historical_candles(symbol, history)
        except Exception:
            logger.exception("Failed to load history for %s", symbol)
        try:
            await self.client.subscribe_ticks(symbol)
            self._subscribed_symbols.add(symbol)
            logger.info("Market feed live for %s", symbol)
            return True
        except Exception as exc:
            msg = str(exc)
            if "AlreadySubscribed" in msg:
                self._subscribed_symbols.add(symbol)
                logger.info("Market feed already live for %s", symbol)
                return True
            if "MarketIsClosed" in msg:
                logger.warning("Market closed for %s — will retry", symbol)
            else:
                logger.exception("Failed to subscribe ticks for %s", symbol)
            self._subscribed_symbols.discard(symbol)
            return False

    async def _feed_watchdog(self) -> None:
        """Retry Deriv tick subscriptions when markets reopen or the socket drops.

        Critical: after a WS drop, symbols may still sit in `_subscribed_symbols`.
        Always reconnect when the socket is dead, clear that set, then resubscribe.
        """
        while self._running:
            sleep_for = 30.0
            if not settings.DERIV_API_TOKEN:
                await asyncio.sleep(sleep_for)
                continue
            try:
                if not self.client._socket_alive():
                    wait = self.client.seconds_until_reconnect()
                    if wait > 0:
                        logger.info("Feed watchdog waiting %.0fs (reconnect backoff)", wait)
                        sleep_for = min(wait, 30.0)
                    else:
                        logger.warning(
                            "Feed watchdog: socket dead — reconnecting and clearing subscriptions"
                        )
                        await self.client.ensure_connected()
                        self._subscribed_symbols.clear()
                        self._account_probe_error = None
                if self.client._socket_alive():
                    missing = [
                        s for s in self.active_pairs if s not in self._subscribed_symbols
                    ]
                    for symbol in missing:
                        await self._ensure_symbol_feed(symbol)
                    # Keep status heartbeat fresh while feed is alive
                    try:
                        self.journal.update_bot_state(
                            "running", settings.TRADING_MODE, self.risk.daily_pnl
                        )
                    except Exception:
                        pass
            except Exception as exc:
                self._account_probe_error = self._format_deriv_error(exc)
                self._subscribed_symbols.clear()
                delay = self.client.seconds_until_reconnect() or 30.0
                sleep_for = min(max(delay, 30.0), 300.0)
                logger.warning(
                    "Feed watchdog reconnect failed: %s (next try in %.0fs)",
                    exc,
                    sleep_for,
                )
            await asyncio.sleep(sleep_for)

    async def probe_deriv_account(self) -> None:
        if self._account_probed or self._running or not settings.DERIV_API_TOKEN:
            return
        self._account_probed = True
        try:
            await self.client.ensure_connected()
            self._account_probe_error = None
        except Exception as exc:
            self._account_probe_error = self._format_deriv_error(exc)
            logger.warning("Deriv account probe failed: %s", exc)
        finally:
            if not self._running:
                await self.client.disconnect()

    async def run_preflight(self) -> dict:
        pairs = self.active_pairs
        ephemeral = False
        if not self.client._socket_alive() and settings.DERIV_API_TOKEN:
            await self.client.ensure_connected()
            ephemeral = True
        try:
            snapshot = await self.analysis.run_preflight(
                client=self.client if self.client._ws else None,
                symbols=pairs,
            )
            return snapshot.to_dict()
        finally:
            # Only tear down a one-off connection opened for /preflight while the bot is stopped.
            # Never disconnect when start() already authorized — that killed feeds after restart.
            if ephemeral and not self._running:
                await self.client.disconnect()

    async def start(self) -> None:
        if self._running:
            return

        deriv_connected = False
        market_data_only = False
        if settings.DERIV_API_TOKEN:
            try:
                # OTP/PAT apps must not open legacy app_id=1089 first (HTTP 401).
                auth = await self.client.ensure_connected()
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
        if settings.NUMBER_ENGINE_EXECUTION:
            # Arm immediately so UI/status are not blocked while preflight backtests run
            self.analysis.analysis_armed = True
        try:
            await self.run_preflight()
        except Exception:
            if settings.NUMBER_ENGINE_EXECUTION:
                logger.exception(
                    "Preflight failed on start — continuing Number Engine loop anyway"
                )
                self.analysis.analysis_armed = True
            else:
                logger.exception("Preflight failed on start — bot will not arm")

        # Only reconnect when the socket is actually dead — do not tear down a healthy OTP session.
        if settings.DERIV_API_TOKEN and (deriv_connected or market_data_only):
            if not self.client._socket_alive():
                try:
                    await self.client.ensure_connected()
                    deriv_connected = True
                    self._account_probe_error = None
                except Exception as exc:
                    self._account_probe_error = self._format_deriv_error(exc)
                    logger.exception("Deriv ensure_connected before feeds failed")
            else:
                logger.info("Deriv socket still authorized — skipping ensure_connected")

        if self.client._socket_alive() or market_data_only:
            self._subscribed_symbols.clear()
            for symbol in self.active_pairs:
                await self._ensure_symbol_feed(symbol)
            self.client.on_tick(self._on_tick)
            if self._subscribed_symbols:
                deriv_connected = True
                self._account_probe_error = None

        self._running = True
        self._paused = False
        self.journal.update_bot_state("running", settings.TRADING_MODE, self.risk.daily_pnl)
        self._task = asyncio.create_task(self._session_watchdog())
        self._feed_task = asyncio.create_task(self._feed_watchdog())

        # Seed Live analysis immediately (don't wait up to 5m for first candle close)
        for symbol in list(self._subscribed_symbols):
            try:
                await self._on_candle_close(symbol)
            except Exception:
                logger.exception("Initial analysis failed for %s", symbol)

        logger.info(
            "Trading bot started mode=%s number_engine=%s armed=%s deriv=%s pairs=%s subscribed=%s",
            settings.TRADING_MODE,
            settings.NUMBER_ENGINE_EXECUTION,
            self.analysis_armed,
            deriv_connected,
            self.active_pairs,
            sorted(self._subscribed_symbols),
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
        for task in (self._task, self._feed_task):
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self._task = None
        self._feed_task = None
        self._subscribed_symbols.clear()
        await self.client.disconnect()
        self.journal.update_bot_state("stopped", settings.TRADING_MODE, self.risk.daily_pnl)

    def status(self) -> dict:
        bot_state = self.journal.get_bot_state()
        preflight = self.analysis.last_preflight or self.journal.get_latest_preflight()
        plan = self.get_active_plan()
        stored = self.plan_store.load()
        return {
            "state": self.state,
            "mode": settings.TRADING_MODE,
            "pairs": self.active_pairs,
            "strategy_allowlist": allowlist_strategy_ids(),
            "max_open_positions": int(getattr(settings, "MAX_OPEN_POSITIONS", 1) or 0),
            "max_trades_per_day": int(getattr(settings, "MAX_TRADES_PER_DAY", 0) or 0),
            "feed_connected": self.client._socket_alive(),
            "daily_pnl": self.risk.daily_pnl,
            "kill_switch_active": self.risk.kill_switch_active,
            "balance": self.client.balance,
            "loginid": self.client.loginid,
            "is_demo": self.client.is_demo,
            "account_type": "demo" if self.client.is_demo else "live",
            "account_error": self._account_probe_error,
            "analysis_armed": self.analysis_armed,
            "number_engine_execution": settings.NUMBER_ENGINE_EXECUTION,
            "auto_start_bot": settings.AUTO_START_BOT,
            "armed_strategies": sorted(self.analysis.armed_strategy_ids),
            "strategy_win_rates": self.analysis.strategy_win_rates,
            "preflight": preflight,
            "sources": self.analysis.source_status(),
            "session": self.session.session_status(),
            "last_heartbeat": bot_state.get("last_heartbeat"),
            "active_plan": plan.to_dict() if plan else None,
            "stored_plan": stored.to_dict() if stored else None,
        }
