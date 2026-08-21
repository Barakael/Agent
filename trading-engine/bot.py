"""Main trading bot loop — data ingestion, signals, risk, execution."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from alerts.telegram import TelegramAlerter
from analytics.metrics import compute_metrics
from analysis.engine import AnalysisEngine
from analysis.horizon_review import (
    HorizonReview,
    compute_8h_review,
    compute_mid_review,
    is_horizon_bar_close,
)
from analysis.horizon_projection import (
    HorizonProjection,
    compute_horizon_projection,
    projection_agrees_with_bias,
)
from analysis.multi_timeframe import higher_timeframe_aligned
from bias import (
    FeatureStore,
    bias_sl_tp,
    build_feature_dict,
    compute_bias_6h,
    compute_regime_24h,
    confirm_1h_entry,
)
from bias.bias_6h import BiasState
from bias.confirm_1h import is_entry_bar_close
from bias.regime_24h import RegimeState
from config import settings
from data.calendar import EconomicCalendar
from data.candle_aggregator import CandleAggregator
from data.deriv_ws import DerivWebSocketClient
from execution.multiplier import contract_room_pct, validate_multiplier
from execution.orders import InvertedRR, OrderExecutor, UnencodableStop
from execution.positions import PositionManager
from journal.writer import JournalWriter
from number_engine import NumberEngine
from plan.store import plan_store
from plan.schema import DailyPlan
from risk.gate import RiskDecision, RiskGate, is_synthetic_symbol
from risk.market_hours import (
    is_market_open,
    market_status,
    seconds_until_open,
    should_flatten_for_weekend,
)
from risk.session import SessionManager
from signals.engine import SignalDirection, SignalEngine
from strategies import (
    PATTERN_STRATEGY_IDS,
    allowlist_strategy_ids,
    apply_strategy_allowlist,
    denylist_strategy_ids,
    evaluate_strategies_detailed,
)
from strategies.base import StrategyContext, make_signal

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
        self.feature_store = FeatureStore(self.journal.Session)
        self._running = False
        self._paused = False
        self._task: Optional[asyncio.Task] = None
        self._feed_task: Optional[asyncio.Task] = None
        self._subscribed_symbols: set[str] = set()
        self._last_analysis: dict[str, dict] = {}
        self._last_tick_epoch: dict[str, int] = {}
        self._account_probed = False
        self._account_probe_error: Optional[str] = None
        self._bias_state: dict[str, BiasState] = {}
        self._regime_state: dict[str, RegimeState] = {}
        self._traded_bias_ids: dict[str, str] = {}
        self._mid_review: dict[str, HorizonReview] = {}
        self._8h_review: dict[str, HorizonReview] = {}
        self._projection: dict[str, HorizonProjection] = {}
        self._allowed_multipliers: dict[str, list[float]] = {}
        self.plan_store = plan_store
        self._cursor_filled_symbols: set[str] = set()
        self._cursor_fill_day: str | None = None

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
        confidence: float | None,
        skip_reason: str | None,
        signal_direction: str | None,
        bias: str | None = None,
        bias_id: str | None = None,
        gates: dict | None = None,
        pipeline: str | None = None,
        empirical: float | None = None,
    ) -> None:
        import time as _time

        now = int(_time.time())
        last_tick = self._last_tick_epoch.get(symbol, 0)
        entry: dict = {
            "symbol": symbol,
            "price": price,
            "regime": regime,
            "rsi": round(rsi, 2) if rsi is not None else None,
            "atr": round(atr, 5) if atr is not None else None,
            "epoch": epoch,
            "bars": bars,
            "best_strategy": best_strategy,
            "confidence": round(confidence, 1) if confidence is not None else None,
            "skip_reason": skip_reason,
            "signal": signal_direction,
            "feed_ok": symbol in self._subscribed_symbols,
            "last_tick_age_sec": (now - last_tick) if last_tick else None,
            "updated_at": _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime()),
        }
        if pipeline:
            entry["pipeline"] = pipeline
            entry["bias"] = bias
            entry["bias_id"] = bias_id
            entry["gates"] = gates or {"passed": [], "failed": []}
            entry["empirical"] = empirical
            # No fake checklist % on bias path
            entry["confidence"] = None
        mid = self._mid_review.get(symbol)
        long8 = self._8h_review.get(symbol)
        if mid is not None:
            entry["review_mid"] = mid.to_dict()
        if long8 is not None:
            entry["review_8h"] = long8.to_dict()
        proj = self._projection.get(symbol)
        if proj is not None:
            entry["projection"] = proj.to_dict()
        self._last_analysis[symbol] = entry

    def get_horizon_reviews(self) -> list[dict]:
        """Latest mid (4/6h) and 8h advisory reviews per active pair."""
        out: list[dict] = []
        for symbol in self.active_pairs:
            mid = self._mid_review.get(symbol)
            long8 = self._8h_review.get(symbol)
            proj = self._projection.get(symbol)
            # Prefer live rolling projection; fall back to review-attached
            projection = None
            if proj is not None:
                projection = proj.to_dict()
            elif long8 and long8.projection:
                projection = long8.projection
            elif mid and mid.projection:
                projection = mid.projection
            out.append(
                {
                    "symbol": symbol,
                    "review_mid": mid.to_dict() if mid else None,
                    "review_8h": long8.to_dict() if long8 else None,
                    "projection": projection,
                    "mid_hours": settings.REVIEW_MID_HOURS,
                    "long_hours": settings.REVIEW_8H_HOURS,
                    "enabled": settings.uses_horizon_review(symbol),
                }
            )
        return out

    def _maybe_refresh_horizon_reviews(self, symbol: str, df) -> None:
        """Refresh mid and 8h reviews on their own bar-close cadences (independent)."""
        if not settings.uses_horizon_review(symbol):
            return
        if df is None or len(df) == 0 or "epoch" not in df.columns:
            return

        epoch = int(df["epoch"].iloc[-1])
        bar_minutes = settings.CANDLE_TIMEFRAME_MINUTES
        mid_h = int(settings.REVIEW_MID_HOURS)
        long_h = int(settings.REVIEW_8H_HOURS)

        # Seed once so UI has something before the first period close
        if symbol not in self._mid_review:
            mid = compute_mid_review(symbol, df, bar_minutes=bar_minutes, hours=mid_h)
            self._mid_review[symbol] = mid
            self._log_horizon_review(mid, event="review_mid_seed")
        if symbol not in self._8h_review:
            long_rev = compute_8h_review(symbol, df, bar_minutes=bar_minutes, hours=long_h)
            self._8h_review[symbol] = long_rev
            self._log_horizon_review(long_rev, event="review_8h_seed")

        if is_horizon_bar_close(epoch, mid_h):
            mid = compute_mid_review(symbol, df, bar_minutes=bar_minutes, hours=mid_h)
            prev = self._mid_review.get(symbol)
            self._mid_review[symbol] = mid
            if prev is None or prev.review_id != mid.review_id or prev.stance != mid.stance:
                self._log_horizon_review(mid, event="review_mid")
                logger.info(
                    "Mid %sh review %s stance=%s id=%s",
                    mid_h,
                    symbol,
                    mid.stance,
                    mid.review_id,
                )

        if is_horizon_bar_close(epoch, long_h):
            long_rev = compute_8h_review(symbol, df, bar_minutes=bar_minutes, hours=long_h)
            prev = self._8h_review.get(symbol)
            self._8h_review[symbol] = long_rev
            if (
                prev is None
                or prev.review_id != long_rev.review_id
                or prev.stance != long_rev.stance
            ):
                self._log_horizon_review(long_rev, event="review_8h")
                logger.info(
                    "8h review %s stance=%s id=%s",
                    symbol,
                    long_rev.stance,
                    long_rev.review_id,
                )

        cached = self._last_analysis.get(symbol)
        if cached is not None:
            if symbol in self._mid_review:
                cached["review_mid"] = self._mid_review[symbol].to_dict()
            if symbol in self._8h_review:
                cached["review_8h"] = self._8h_review[symbol].to_dict()
            if symbol in self._projection:
                cached["projection"] = self._projection[symbol].to_dict()

    def _refresh_projection(self, symbol: str, df) -> Optional[HorizonProjection]:
        """Recompute rolling 8h structure+ATR projection (enter-now advisory)."""
        if not getattr(settings, "PROJECTION_ENABLED", True):
            return self._projection.get(symbol)
        if df is None or len(df) == 0:
            return self._projection.get(symbol)
        proj = compute_horizon_projection(
            df,
            lookback_hours=int(settings.PROJECTION_LOOKBACK_HOURS),
            forward_hours=int(settings.PROJECTION_FORWARD_HOURS),
            bar_minutes=settings.CANDLE_TIMEFRAME_MINUTES,
            atr_mult=float(settings.PROJECTION_ATR_MULT),
        )
        self._projection[symbol] = proj
        return proj

    def _log_horizon_review(self, review: HorizonReview, *, event: str) -> None:
        try:
            self.feature_store.log(
                symbol=review.symbol,
                event=event,
                features=review.to_dict(),
                bias_id=review.review_id,
                regime=f"{review.hours}h",
                bias=review.stance,
            )
            self.journal.log_analysis_run(
                type(
                    "Snap",
                    (),
                    {
                        "run_type": event,
                        "symbol": review.symbol,
                        "passed": review.stance != "STAND_ASIDE",
                        "decision": "GO" if review.stance != "STAND_ASIDE" else "NO-GO",
                        "reasons": review.reasons,
                        "sources": review.to_dict(),
                    },
                )()
            )
        except Exception:
            logger.debug("Horizon review log failed", exc_info=True)

    def get_analysis_snapshots(self) -> list[dict]:
        """Last Number Engine / bias evaluation per active pair (for live UI)."""
        out: list[dict] = []
        for symbol in self.active_pairs:
            if symbol in self._last_analysis:
                row = dict(self._last_analysis[symbol])
                if symbol in self._mid_review:
                    row["review_mid"] = self._mid_review[symbol].to_dict()
                if symbol in self._8h_review:
                    row["review_8h"] = self._8h_review[symbol].to_dict()
                if symbol in self._projection:
                    row["projection"] = self._projection[symbol].to_dict()
                out.append(row)
            else:
                df = self.aggregator.get_dataframe(symbol)
                bars = len(df)
                last_tick = self._last_tick_epoch.get(symbol, 0)
                import time as _time

                now = int(_time.time())
                row = {
                    "symbol": symbol,
                    "price": float(df["close"].iloc[-1]) if bars else None,
                    "regime": None,
                    "rsi": None,
                    "atr": None,
                    "epoch": int(df["epoch"].iloc[-1]) if bars and "epoch" in df.columns else None,
                    "bars": bars,
                    "best_strategy": None,
                    "confidence": 0.0 if not settings.uses_bias_pipeline(symbol) else None,
                    "skip_reason": "waiting_for_candle_close" if bars else "warming_up",
                    "signal": None,
                    "feed_ok": symbol in self._subscribed_symbols,
                    "last_tick_age_sec": (now - last_tick) if last_tick else None,
                    "updated_at": None,
                }
                if settings.uses_bias_pipeline(symbol):
                    row["pipeline"] = "bias_v1"
                    row["bias"] = None
                    row["gates"] = {"passed": [], "failed": []}
                    row["empirical"] = None
                if symbol in self._mid_review:
                    row["review_mid"] = self._mid_review[symbol].to_dict()
                if symbol in self._8h_review:
                    row["review_8h"] = self._8h_review[symbol].to_dict()
                if symbol in self._projection:
                    row["projection"] = self._projection[symbol].to_dict()
                out.append(row)
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

        # Independent horizon reviews (mid 4/6h + 8h) — never block bias/entry path
        self._maybe_refresh_horizon_reviews(symbol, df)

        if settings.uses_bias_pipeline(symbol):
            await self._on_bias_pipeline_candle(symbol, df, plan)
            return

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

        await self._risk_and_execute(symbol, signal, df, plan)

    def _reset_cursor_fills_if_new_day(self) -> None:
        today = datetime.now(timezone.utc).date().isoformat()
        if self._cursor_fill_day != today:
            self._cursor_fill_day = today
            self._cursor_filled_symbols.clear()

    def _cursor_setup_for(self, plan: DailyPlan, symbol: str):
        for s in plan.setups or []:
            if s.symbol == symbol:
                return s
        return None

    def _cursor_atr(self, df) -> float | None:
        if len(df) < 2 or not {"high", "low", "close"}.issubset(df.columns):
            return None
        high = df["high"].astype(float)
        low = df["low"].astype(float)
        prev_close = df["close"].astype(float).shift(1)
        tr = (high - low).to_frame("a")
        tr["b"] = (high - prev_close).abs()
        tr["c"] = (low - prev_close).abs()
        series = tr.max(axis=1)
        if len(series) < 14:
            return float(series.mean()) if len(series) else None
        return float(series.tail(14).mean())

    def _near_ema21_pullback(self, df, direction: SignalDirection, price: float) -> bool:
        """ATR-based pullback near EMA21.

        Cursor owns direction; this only times entry. Allow up to ~1.0 ATR so a
        valid ALIGN plan is not parked all day on a half-ATR haircut.
        """
        if len(df) < 21 or "close" not in df.columns:
            return False
        ema = float(df["close"].ewm(span=21, adjust=False).mean().iloc[-1])
        atr = self._cursor_atr(df)
        if ema <= 0 or not atr or atr <= 0:
            return False
        dist_atr = abs(price - ema) / atr
        if dist_atr > 1.0:
            return False
        # Soft side check: mild extension past EMA still counts as near
        if direction == SignalDirection.BUY and price > ema + atr:
            return False
        if direction == SignalDirection.SELL and price < ema - atr:
            return False
        return True

    def _cursor_chase_blocked(self, df, direction: SignalDirection, price: float) -> bool:
        """Reject longs near swing high / shorts near swing low (anti-chase)."""
        atr = self._cursor_atr(df)
        if not atr or atr <= 0 or "high" not in df.columns or "low" not in df.columns:
            return False
        look = min(48, len(df))
        swing_high = float(df["high"].astype(float).tail(look).max())
        swing_low = float(df["low"].astype(float).tail(look).min())
        if direction == SignalDirection.BUY:
            return (swing_high - price) / atr <= 0.35
        return (price - swing_low) / atr <= 0.35

    def _cursor_priority_blocks(self, plan: DailyPlan, symbol: str) -> bool:
        """Soft prefer only: never park a ready pair behind one still waiting on timing.

        Priority / prefer_symbol_order is advisory. Hard caps are max_trades_today
        and max_open_positions. Blocking GBPUSD all day because EURUSD awaits EMA
        pullback prevented Cursor ALIGN plans from filling.
        """
        return False

    async def _execute_cursor_directed(
        self, symbol: str, df, plan: DailyPlan, price: float, epoch: int
    ) -> None:
        """Bot only executes: news+chart thesis already decided by Cursor Automation."""
        self._reset_cursor_fills_if_new_day()

        if symbol not in (plan.pairs or []):
            self._record_analysis(
                symbol,
                price=price,
                regime="cursor_plan",
                rsi=0.0,
                atr=0.0,
                epoch=epoch,
                bars=len(df),
                best_strategy="cursor_execute",
                confidence=float(plan.confidence),
                skip_reason="symbol_not_in_plan",
                signal_direction=None,
                pipeline="cursor_execute",
                gates={"passed": [], "failed": ["symbol_not_in_plan"]},
            )
            return

        if plan.avoid_until_utc:
            try:
                avoid = datetime.fromisoformat(plan.avoid_until_utc.replace("Z", "+00:00"))
                if datetime.now(timezone.utc) < avoid:
                    self._record_analysis(
                        symbol,
                        price=price,
                        regime="cursor_plan",
                        rsi=0.0,
                        atr=0.0,
                        epoch=epoch,
                        bars=len(df),
                        best_strategy="cursor_execute",
                        confidence=float(plan.confidence),
                        skip_reason="cursor_avoid_until",
                        signal_direction=None,
                        pipeline="cursor_execute",
                        gates={"passed": [], "failed": ["cursor_avoid_until"]},
                    )
                    return
            except Exception:
                pass

        trades_today = int(getattr(self.risk, "_trades_today", 0) or 0)
        if trades_today >= int(plan.max_trades_today):
            self._record_analysis(
                symbol,
                price=price,
                regime="cursor_plan",
                rsi=0.0,
                atr=0.0,
                epoch=epoch,
                bars=len(df),
                best_strategy="cursor_execute",
                confidence=float(plan.confidence),
                skip_reason="cursor_max_trades",
                signal_direction=None,
                pipeline="cursor_execute",
                gates={"passed": [], "failed": ["cursor_max_trades"]},
            )
            return

        if symbol in self._cursor_filled_symbols:
            return

        if self._cursor_priority_blocks(plan, symbol):
            self._record_analysis(
                symbol,
                price=price,
                regime="cursor_plan",
                rsi=0.0,
                atr=0.0,
                epoch=epoch,
                bars=len(df),
                best_strategy="cursor_execute",
                confidence=float(plan.confidence),
                skip_reason="awaiting_higher_priority_symbol",
                signal_direction=None,
                pipeline="cursor_execute",
                gates={"passed": [], "failed": ["awaiting_higher_priority_symbol"]},
            )
            return

        setup = self._cursor_setup_for(plan, symbol)
        if setup is not None:
            direction = SignalDirection.BUY if setup.direction == "buy" else SignalDirection.SELL
            entry_style = setup.entry_style or plan.entry_style
            sl_pips = setup.sl_pips or plan.sl_pips
            tp_pips = setup.tp_pips or plan.tp_pips
            rationale = setup.rationale or plan.notes or plan.review
        else:
            if plan.directional_bias not in {"buy", "sell"}:
                return
            direction = (
                SignalDirection.BUY if plan.directional_bias == "buy" else SignalDirection.SELL
            )
            entry_style = plan.entry_style or "pullback"
            sl_pips = plan.sl_pips
            tp_pips = plan.tp_pips
            rationale = plan.review or plan.notes

        if self._cursor_chase_blocked(df, direction, price):
            self._record_analysis(
                symbol,
                price=price,
                regime="cursor_plan",
                rsi=0.0,
                atr=0.0,
                epoch=epoch,
                bars=len(df),
                best_strategy="cursor_execute",
                confidence=float(plan.confidence),
                skip_reason="anti_chase_swing",
                signal_direction=direction.value,
                pipeline="cursor_execute",
                gates={"passed": ["cursor_thesis"], "failed": ["anti_chase_swing"]},
            )
            return

        if entry_style == "pullback" and not self._near_ema21_pullback(df, direction, price):
            self._record_analysis(
                symbol,
                price=price,
                regime="cursor_plan",
                rsi=0.0,
                atr=0.0,
                epoch=epoch,
                bars=len(df),
                best_strategy="cursor_execute",
                confidence=float(plan.confidence),
                skip_reason="awaiting_pullback_ema21_atr",
                signal_direction=direction.value,
                pipeline="cursor_execute",
                gates={"passed": ["cursor_thesis"], "failed": ["awaiting_pullback_ema21_atr"]},
            )
            return

        # Price levels from plan pips via RiskGate helpers
        pip = self.risk._pip_size(symbol)
        if direction == SignalDirection.BUY:
            sl = price - sl_pips * pip
            tp = price + tp_pips * pip
        else:
            sl = price + sl_pips * pip
            tp = price - tp_pips * pip

        signal = make_signal(
            strategy_id="cursor_execute",
            symbol=symbol,
            direction=direction,
            price=price,
            epoch=epoch,
            reason=f"cursor_execute {direction.value}: {(rationale or '')[:240]}",
            rsi=0.0,
            macd=0.0,
            trade_mode="bias",
            hold_policy=plan.hold_policy or "swing",
            confidence=float(plan.confidence or 0) / 100.0,
            market_condition="cursor_plan",
            score_breakdown={
                "pipeline": "cursor_execute",
                "entry_style": entry_style,
                "max_trades_today": plan.max_trades_today,
                "review": (plan.review or "")[:500],
            },
            suggested_sl=sl,
            suggested_tp=tp,
            sl_tp_method="cursor_plan_pips",
            bias_id=f"cursor-{plan.date}-{symbol}",
            feature_json={
                "review": plan.review,
                "notes": plan.notes,
                "analysis": plan.analysis.model_dump() if plan.analysis else None,
            },
            gates={"passed": ["cursor_thesis", f"entry:{entry_style}", "anti_chase"], "failed": []},
        )

        self._record_analysis(
            symbol,
            price=price,
            regime="cursor_plan",
            rsi=0.0,
            atr=0.0,
            epoch=epoch,
            bars=len(df),
            best_strategy="cursor_execute",
            confidence=float(plan.confidence),
            skip_reason=None,
            signal_direction=direction.value,
            pipeline="cursor_execute",
            gates={"passed": ["cursor_thesis", f"entry:{entry_style}", "anti_chase"], "failed": []},
        )

        prev_max = self.risk.max_trades_per_day
        try:
            self.risk.max_trades_per_day = int(plan.max_trades_today)
            opened = await self._risk_and_execute(symbol, signal, df, plan)
        finally:
            self.risk.max_trades_per_day = prev_max

        if opened:
            self._cursor_filled_symbols.add(symbol)
            logger.info(
                "Cursor-directed fill %s %s (style=%s trades_cap=%s)",
                direction.value,
                symbol,
                entry_style,
                plan.max_trades_today,
            )

    async def _on_bias_pipeline_candle(self, symbol: str, df, plan) -> None:
        """Cursor-directed execute, or legacy 24h→6h→1h chart confirm path."""
        bar_minutes = settings.CANDLE_TIMEFRAME_MINUTES
        epoch = int(df["epoch"].iloc[-1]) if len(df) and "epoch" in df.columns else 0
        price = float(df["close"].iloc[-1]) if len(df) else 0.0

        active = self.get_active_plan() or plan
        if active is not None and getattr(active, "is_cursor_execute", False):
            await self._execute_cursor_directed(symbol, df, active, price, epoch)
            return

        if len(df) < 60:
            self._record_analysis(
                symbol,
                price=price,
                regime="unknown",
                rsi=0.0,
                atr=0.0,
                epoch=epoch,
                bars=len(df),
                best_strategy="bias_pipeline",
                confidence=None,
                skip_reason="insufficient_bars",
                signal_direction=None,
                pipeline="bias_v1",
                gates={"passed": [], "failed": ["insufficient_bars"]},
            )
            return

        regime = compute_regime_24h(
            df,
            bar_minutes=bar_minutes,
            hours=settings.BIAS_REGIME_HOURS,
        )
        prev = self._bias_state.get(symbol)
        bias = compute_bias_6h(
            df,
            regime,
            bar_minutes=bar_minutes,
            hours=settings.BIAS_LOOKBACK_HOURS,
            deadzone_atr_frac=settings.BIAS_DEADZONE_ATR_FRAC,
            prev_bias=prev,
        )
        self._regime_state[symbol] = regime
        if prev is None or prev.bias_id != bias.bias_id or prev.direction != bias.direction:
            feats = build_feature_dict(symbol=symbol, regime=regime, bias=bias)
            self.feature_store.log(
                symbol=symbol,
                event="bias_change",
                features=feats,
                bias_id=bias.bias_id,
                regime=regime.label,
                bias=bias.direction,
            )
        self._bias_state[symbol] = bias

        # Rolling 8h enter-now projection (advisory + soft gate on 1h eval)
        proj = self._refresh_projection(symbol, df)

        gates = {"passed": [f"regime:{regime.label}", f"bias:{bias.direction}"], "failed": []}
        if proj is not None:
            gates["passed"].append(f"projection:{proj.direction}")
        entry_tf = settings.BIAS_ENTRY_TF_MINUTES
        on_entry_bar = is_entry_bar_close(epoch, entry_tf)

        if not on_entry_bar:
            self._record_analysis(
                symbol,
                price=price,
                regime=regime.label,
                rsi=bias.rsi,
                atr=bias.atr_6h,
                epoch=epoch,
                bars=len(df),
                best_strategy="bias_pipeline",
                confidence=None,
                skip_reason="awaiting_1h_close",
                signal_direction=None,
                bias=bias.direction,
                bias_id=bias.bias_id,
                gates=gates,
                pipeline="bias_v1",
            )
            return

        # Soft gate: projection must agree with bias (+ 8h stance not opposing)
        stance_8h = None
        long8 = self._8h_review.get(symbol)
        if long8 is not None:
            stance_8h = long8.stance
        proj_ok, proj_passed, proj_failed = projection_agrees_with_bias(
            bias.direction,
            proj if proj is not None else compute_horizon_projection(df),
            stance_8h=stance_8h,
        )
        gates["passed"] = list(dict.fromkeys(gates["passed"] + list(proj_passed)))
        gates["failed"] = list(dict.fromkeys(gates["failed"] + list(proj_failed)))

        if not proj_ok:
            skip = "projection_not_aligned"
            if "bias_no_trade" in proj_failed:
                skip = "bias_no_trade"
            self._record_analysis(
                symbol,
                price=price,
                regime=regime.label,
                rsi=bias.rsi,
                atr=bias.atr_6h,
                epoch=epoch,
                bars=len(df),
                best_strategy="bias_pipeline",
                confidence=None,
                skip_reason=skip,
                signal_direction=None,
                bias=bias.direction,
                bias_id=bias.bias_id,
                gates=gates,
                pipeline="bias_v1",
            )
            self.feature_store.log(
                symbol=symbol,
                event="skip",
                features={
                    "skip": skip,
                    "projection": proj.to_dict() if proj else None,
                    "stance_8h": stance_8h,
                    "gates": gates,
                },
                bias_id=bias.bias_id,
                regime=regime.label,
                bias=bias.direction,
            )
            return

        # 1h evaluation (after projection agreement)
        confirm = confirm_1h_entry(
            df,
            bias,
            regime,
            bar_minutes=bar_minutes,
            entry_tf_minutes=entry_tf,
        )
        feats = build_feature_dict(
            symbol=symbol, regime=regime, bias=bias, confirm=confirm
        )
        if proj is not None:
            feats["projection"] = proj.to_dict()
            feats["stance_8h"] = stance_8h
        self.feature_store.log(
            symbol=symbol,
            event="evaluate",
            features=feats,
            bias_id=bias.bias_id,
            regime=regime.label,
            bias=bias.direction,
        )
        gates = {
            "passed": list(dict.fromkeys(list(proj_passed) + list(confirm.gates_passed))),
            "failed": list(dict.fromkeys(list(proj_failed) + list(confirm.gates_failed))),
        }

        if bias.direction == "NO_TRADE":
            skip = "bias_no_trade"
            gates["failed"] = list(dict.fromkeys(gates["failed"] + ["bias_no_trade"]))
            self._record_analysis(
                symbol,
                price=price,
                regime=regime.label,
                rsi=bias.rsi,
                atr=bias.atr_6h,
                epoch=epoch,
                bars=len(df),
                best_strategy="bias_pipeline",
                confidence=None,
                skip_reason=skip,
                signal_direction=None,
                bias=bias.direction,
                bias_id=bias.bias_id,
                gates=gates,
                pipeline="bias_v1",
            )
            self.feature_store.log(
                symbol=symbol,
                event="skip",
                features={**feats, "skip": skip},
                bias_id=bias.bias_id,
                regime=regime.label,
                bias=bias.direction,
            )
            return

        # Daily-plan gate: require today's Cursor Automation plan; charts only time entry.
        active_plan = self.get_active_plan()
        if active_plan is None:
            skip = "no_daily_plan"
            gates["failed"] = list(dict.fromkeys(gates["failed"] + [skip]))
            self._record_analysis(
                symbol,
                price=price,
                regime=regime.label,
                rsi=bias.rsi,
                atr=bias.atr_6h,
                epoch=epoch,
                bars=len(df),
                best_strategy="bias_pipeline",
                confidence=None,
                skip_reason=skip,
                signal_direction=None,
                bias=bias.direction,
                bias_id=bias.bias_id,
                gates=gates,
                pipeline="bias_v1",
            )
            return

        plan_source = (getattr(active_plan, "source", "") or "").lower()
        plan_notes = (getattr(active_plan, "notes", "") or "")
        if (
            not plan_source.startswith("cursor")
            or "awaiting_cursor_plan" in plan_notes
            or "Fallback bias" in plan_notes
        ):
            skip = "no_cursor_plan"
            gates["failed"] = list(dict.fromkeys(gates["failed"] + [skip]))
            self._record_analysis(
                symbol,
                price=price,
                regime=regime.label,
                rsi=bias.rsi,
                atr=bias.atr_6h,
                epoch=epoch,
                bars=len(df),
                best_strategy="bias_pipeline",
                confidence=None,
                skip_reason=skip,
                signal_direction=None,
                bias=bias.direction,
                bias_id=bias.bias_id,
                gates=gates,
                pipeline="bias_v1",
            )
            return

        plan_pairs = list(getattr(active_plan, "pairs", None) or [])
        if plan_pairs and symbol not in plan_pairs:
            skip = "symbol_not_in_plan"
            gates["failed"] = list(dict.fromkeys(gates["failed"] + [skip]))
            self._record_analysis(
                symbol,
                price=price,
                regime=regime.label,
                rsi=bias.rsi,
                atr=bias.atr_6h,
                epoch=epoch,
                bars=len(df),
                best_strategy="bias_pipeline",
                confidence=None,
                skip_reason=skip,
                signal_direction=None,
                bias=bias.direction,
                bias_id=bias.bias_id,
                gates=gates,
                pipeline="bias_v1",
            )
            return

        plan_dir = (active_plan.directional_bias or "neutral").lower()
        bias_dir = (bias.direction or "").upper()
        plan_conflict = False
        if plan_dir == "buy" and bias_dir == "SELL_ONLY":
            plan_conflict = True
        elif plan_dir == "sell" and bias_dir == "BUY_ONLY":
            plan_conflict = True
        elif plan_dir == "neutral":
            plan_conflict = True  # neutral plan = stand-aside; no opens today
        if plan_conflict:
            skip = "plan_bias_conflict"
            gates["failed"] = list(dict.fromkeys(gates["failed"] + [skip]))
            self._record_analysis(
                symbol,
                price=price,
                regime=regime.label,
                rsi=bias.rsi,
                atr=bias.atr_6h,
                epoch=epoch,
                bars=len(df),
                best_strategy="bias_pipeline",
                confidence=None,
                skip_reason=skip,
                signal_direction=None,
                bias=bias.direction,
                bias_id=bias.bias_id,
                gates=gates,
                pipeline="bias_v1",
            )
            self.feature_store.log(
                symbol=symbol,
                event="skip",
                features={**feats, "skip": skip, "plan_dir": plan_dir, "bias_dir": bias_dir},
                bias_id=bias.bias_id,
                regime=regime.label,
                bias=bias.direction,
            )
            return

        # Thesis lock: open position or same bias_id already traded
        thesis_open = False
        try:
            await self.positions.refresh()
        except Exception:
            logger.debug("Position refresh before thesis check failed", exc_info=True)
        for pos in self.positions.positions or []:
            psym = pos.get("underlying") or pos.get("symbol") or ""
            if psym == symbol:
                thesis_open = True
                break
        if not thesis_open and self.journal.has_open_thesis(symbol):
            thesis_open = True
        if thesis_open and settings.BIAS_MAX_OPEN_THESIS >= 1:
            skip = "thesis_already_open"
            gates["failed"] = list(dict.fromkeys(gates["failed"] + [skip]))
            self._record_analysis(
                symbol,
                price=price,
                regime=regime.label,
                rsi=bias.rsi,
                atr=bias.atr_6h,
                epoch=epoch,
                bars=len(df),
                best_strategy="bias_pipeline",
                confidence=None,
                skip_reason=skip,
                signal_direction=None,
                bias=bias.direction,
                bias_id=bias.bias_id,
                gates=gates,
                pipeline="bias_v1",
            )
            self.feature_store.log(
                symbol=symbol,
                event="skip",
                features={**feats, "skip": skip},
                bias_id=bias.bias_id,
                regime=regime.label,
                bias=bias.direction,
            )
            return

        last_bias = self._traded_bias_ids.get(symbol) or self.journal.last_closed_bias_id(symbol)
        if last_bias and last_bias == bias.bias_id:
            skip = "same_bias_thesis"
            gates["failed"] = list(dict.fromkeys(gates["failed"] + [skip]))
            self._record_analysis(
                symbol,
                price=price,
                regime=regime.label,
                rsi=bias.rsi,
                atr=bias.atr_6h,
                epoch=epoch,
                bars=len(df),
                best_strategy="bias_pipeline",
                confidence=None,
                skip_reason=skip,
                signal_direction=None,
                bias=bias.direction,
                bias_id=bias.bias_id,
                gates=gates,
                pipeline="bias_v1",
            )
            self.feature_store.log(
                symbol=symbol,
                event="skip",
                features={**feats, "skip": skip},
                bias_id=bias.bias_id,
                regime=regime.label,
                bias=bias.direction,
            )
            return

        if not confirm.ok:
            skip = "confirm_failed:" + (",".join(confirm.gates_failed) or "none")
            self._record_analysis(

                symbol,
                price=price,
                regime=regime.label,
                rsi=confirm.rsi or bias.rsi,
                atr=bias.atr_6h,
                epoch=epoch,
                bars=len(df),
                best_strategy="bias_pipeline",
                confidence=None,
                skip_reason=skip,
                signal_direction=confirm.direction if confirm.direction != "none" else None,
                bias=bias.direction,
                bias_id=bias.bias_id,
                gates=gates,
                pipeline="bias_v1",
            )
            self.feature_store.log(
                symbol=symbol,
                event="skip",
                features={**feats, "skip": skip},
                bias_id=bias.bias_id,
                regime=regime.label,
                bias=bias.direction,
            )
            self.journal.log_no_trade(
                symbol=symbol,
                price=price,
                epoch=epoch,
                regime=regime.label,
                reason=skip,
                rsi=confirm.rsi or bias.rsi,
                macd=0.0,
            )
            return

        direction = (
            SignalDirection.BUY if confirm.direction == "buy" else SignalDirection.SELL
        )
        entry = confirm.entry_price or price
        sl, tp, method = bias_sl_tp(bias, entry, direction)
        gates_payload = {
            "passed": gates["passed"],
            "failed": gates["failed"],
            "confirm_type": confirm.confirm_type,
        }
        signal = make_signal(
            strategy_id="bias_pipeline",
            symbol=symbol,
            direction=direction,
            price=entry,
            epoch=epoch,
            reason=f"bias_v1 {bias.direction} {confirm.confirm_type}; " + "; ".join(confirm.reasons),
            rsi=confirm.rsi or bias.rsi,
            macd=0.0,
            trade_mode="bias",
            hold_policy="swing",
            confidence=0.0,
            market_condition=regime.label,
            score_breakdown={
                "gates_passed": gates["passed"],
                "gates_failed": gates["failed"],
                "confirm_type": confirm.confirm_type,
                "pipeline": "bias_v1",
                "projection": proj.direction if proj else None,
            },
            suggested_sl=sl,
            suggested_tp=tp,
            sl_tp_method=method,
            bias_id=bias.bias_id,
            feature_json=feats,
            gates=gates_payload,
        )

        self._record_analysis(
            symbol,
            price=entry,
            regime=regime.label,
            rsi=signal.rsi,
            atr=bias.atr_6h,
            epoch=epoch,
            bars=len(df),
            best_strategy="bias_pipeline",
            confidence=None,
            skip_reason=None,
            signal_direction=signal.direction.value,
            bias=bias.direction,
            bias_id=bias.bias_id,
            gates=gates_payload,
            pipeline="bias_v1",
        )

        opened = await self._risk_and_execute(symbol, signal, df, plan)
        if opened:
            self._traded_bias_ids[symbol] = bias.bias_id
            self.feature_store.log(
                symbol=symbol,
                event="fill",
                features=feats,
                bias_id=bias.bias_id,
                regime=regime.label,
                bias=bias.direction,
            )

    async def _risk_and_execute(self, symbol: str, signal, df, plan) -> bool:
        """Shared RiskGate → execute path. Returns True if a trade was opened."""
        # Forex shuts from late Friday to late Sunday. The last close before the
        # break is a stale price to act on, so skip rather than journal a fill
        # that could not have happened.
        if not is_market_open(symbol):
            skip = f"market_closed (reopens in {seconds_until_open(symbol)}s)"
        elif settings.FOREX_WEEKEND_FLATTEN_MINUTES > 0 and should_flatten_for_weekend(
            symbol
        ):
            skip = "weekend_flatten_window"
        else:
            skip = ""
        if skip:
            cached = self._last_analysis.get(symbol)
            if cached:
                cached["skip_reason"] = skip
            logger.info("Skip open %s: %s", symbol, skip)
            return False

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
                return False

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
            return False

        # Cursor Automation owns direction/ALIGN. Do not let the legacy ATAE
        # scenario simulator (scenario_no_simulated_outcomes) veto a cursor plan.
        # Bot role is timing + risk only.
        cursor_owned = bool(
            (plan is not None and getattr(plan, "is_cursor_execute", False))
            or getattr(signal, "strategy_id", "") == "cursor_execute"
            or (getattr(signal, "score_breakdown", None) or {}).get("pipeline")
            == "cursor_execute"
        )
        if not settings.NUMBER_ENGINE_EXECUTION and not cursor_owned:
            open_snapshot = self.analysis.evaluate_open(signal, df, risk_result)
            if not open_snapshot.passed:
                self.journal.log_signal_rejected(signal, "; ".join(open_snapshot.reasons))
                logger.info("Analysis rejected open %s: %s", symbol, open_snapshot.reasons)
                return False

        if settings.TRADING_MODE == "log_only":
            logger.info(
                "SIGNAL %s %s @ %.5f gates=%s RSI=%.1f — %s [bias_or_ne]",
                signal.direction.value,
                symbol,
                signal.price,
                getattr(signal, "gates", None) or getattr(signal, "confidence", 0),
                signal.rsi,
                signal.reason,
            )
            self.journal.log_trade_open(signal, risk_result, mode="log_only")
            self.risk.record_trade_opened()
            await self.telegram.trade_opened(
                symbol, signal.direction.value, risk_result.stake, "log_only"
            )
            return True

        hold = getattr(signal, "hold_policy", "intraday")
        if not self.session.is_session_open():
            # Session gate applies to ALL opens (including swing) for forex pairs.
            self.journal.log_signal_rejected(signal, "outside_session_window")
            return False

        if (
            not settings.NUMBER_ENGINE_EXECUTION
            and not cursor_owned
            and settings.ANALYSIS_REQUIRE_PREFLIGHT
            and not self.analysis_armed
        ):
            self.journal.log_signal_rejected(signal, "preflight_not_armed")
            return False

        try:
            order = await self.executor.execute_signal(signal, risk_result)
        except UnencodableStop as exc:
            # The chart stop does not fit the contract; skip rather than trade a
            # tighter stop than the thesis called for.
            logger.warning("Signal skipped for %s: %s", symbol, exc)
            self.journal.log_signal_rejected(signal, f"unencodable_stop: {exc}"[:500])
            cached = self._last_analysis.get(symbol)
            if cached:
                cached["skip_reason"] = f"unencodable_stop: {exc}"[:200]
            return False
        except InvertedRR as exc:
            logger.warning("Signal skipped for %s: %s", symbol, exc)
            self.journal.log_signal_rejected(signal, f"rr_below_minimum: {exc}"[:500])
            cached = self._last_analysis.get(symbol)
            if cached:
                cached["skip_reason"] = f"rr_below_minimum: {exc}"[:200]
            return False
        except Exception as exc:
            msg = f"execution_failed: {exc}"
            logger.exception("Order execution failed %s", symbol)
            self.journal.log_signal_rejected(signal, msg[:500])
            cached = self._last_analysis.get(symbol)
            if cached:
                cached["skip_reason"] = msg[:200]
                cached["signal"] = signal.direction.value
            return False

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
        return True

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
            elif settings.FOREX_WEEKEND_FLATTEN_MINUTES > 0 and any(
                should_flatten_for_weekend(s) for s in self.active_pairs
            ):
                # Swing positions are included: a weekend gap ignores the stop
                # regardless of how the position was labelled.
                logger.warning("Forex close approaching — flattening before the weekend")
                await self._close_all_positions(force=True, skip_swing=False)
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
                        s
                        for s in self.active_pairs
                        if s not in self._subscribed_symbols and is_market_open(s)
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

        if deriv_connected:
            await self._verify_multiplier()

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

    async def _verify_multiplier(self) -> None:
        """Confirm Deriv offers the configured multiplier before trading it.

        A rejected multiplier is silently substituted at proposal time, which
        would change the dollar value of every stop, so the mismatch is surfaced
        at startup instead.
        """
        configured = float(settings.DERIV_MULTIPLIER)
        room_pct = contract_room_pct(configured)
        for symbol in self.active_pairs:
            if not is_synthetic_symbol(symbol):
                continue
            try:
                allowed = await self.client.get_allowed_multipliers(symbol)
            except Exception:
                logger.warning("Could not read multipliers for %s", symbol, exc_info=True)
                continue
            ok, detail = validate_multiplier(configured, allowed)
            self._allowed_multipliers[symbol] = allowed
            if ok:
                logger.info(
                    "Multiplier %g valid for %s — stop room %.2f%% (allowed %s)",
                    configured,
                    symbol,
                    room_pct * 100,
                    ", ".join(f"{m:g}" for m in allowed) or "unreported",
                )
            else:
                logger.error("Multiplier check failed for %s: %s", symbol, detail)
                self._account_probe_error = f"{symbol}: {detail}"

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
            "strategy_denylist": sorted(denylist_strategy_ids()),
            "max_open_positions": int(getattr(settings, "MAX_OPEN_POSITIONS", 1) or 0),
            "max_trades_per_day": int(getattr(settings, "MAX_TRADES_PER_DAY", 0) or 0),
            "multiplier": float(settings.DERIV_MULTIPLIER),
            "multiplier_room_pct": round(
                contract_room_pct(settings.DERIV_MULTIPLIER) * 100, 3
            ),
            "allowed_multipliers": self._allowed_multipliers,
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
            "markets": market_status(self.active_pairs),
            "last_heartbeat": bot_state.get("last_heartbeat"),
            "active_plan": plan.to_dict() if plan else None,
            "stored_plan": stored.to_dict() if stored else None,
        }
