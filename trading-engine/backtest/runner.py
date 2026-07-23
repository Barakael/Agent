"""Backtest strategy + risk logic against historical Deriv candles."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import List

import pandas as pd

from config import settings
from data.deriv_ws import DerivWebSocketClient
from risk.gate import RiskGate
from signals.engine import SignalDirection, SignalEngine
from strategies import get_strategy
from strategies.base import StrategyContext

logger = logging.getLogger(__name__)


@dataclass
class BacktestTrade:
    symbol: str
    direction: str
    entry_price: float
    exit_price: float
    pnl: float
    stake: float


@dataclass
class BacktestResult:
    trades: List[BacktestTrade] = field(default_factory=list)
    total_pnl: float = 0.0
    win_rate: float = 0.0
    max_drawdown: float = 0.0
    expectancy: float = 0.0
    passed: bool = False
    high_win_rate: bool = False

    def to_dict(self) -> dict:
        return {
            "total_trades": len(self.trades),
            "total_pnl": round(self.total_pnl, 2),
            "win_rate": round(self.win_rate * 100, 2),
            "max_drawdown": round(self.max_drawdown, 2),
            "expectancy": round(self.expectancy, 4),
            "passed": self.passed,
            "high_win_rate": getattr(self, "high_win_rate", False),
        }


class BacktestRunner:
    def __init__(self, initial_balance: float = 10000.0) -> None:
        self.initial_balance = initial_balance
        self.signal_engine = SignalEngine()
        self.risk_gate = RiskGate()
        self.risk_gate.reset_session(initial_balance)

    def run_on_dataframe(
        self,
        symbol: str,
        df: pd.DataFrame,
        strategy_id: str = "macd_rsi",
    ) -> BacktestResult:
        result = BacktestResult()
        balance = self.initial_balance
        equity_curve = [balance]
        open_trade: BacktestTrade | None = None
        # Fresh risk session per symbol so one pair cannot kill the whole run
        self.risk_gate.reset_session(balance)
        strategy = get_strategy(strategy_id)
        ctx = StrategyContext(trade_mode="pattern", hold_policy="intraday")

        min_bars = settings.MACD_SLOW + settings.MACD_SIGNAL + settings.RSI_PERIOD + 2

        for i in range(min_bars, len(df)):
            window = df.iloc[: i + 1].copy()
            if strategy:
                signal = strategy.evaluate(symbol, window, ctx)
            else:
                signal = self.signal_engine.evaluate(symbol, window)
            bar = df.iloc[i]
            price = float(bar["close"])

            if open_trade:
                sl_dist = settings.DEFAULT_SL_PIPS * (
                    0.01 if "JPY" in symbol else 0.0001
                )
                tp_dist = settings.DEFAULT_TP_PIPS * (
                    0.01 if "JPY" in symbol else 0.0001
                )
                sl_hit = (
                    open_trade.direction == "buy" and price <= open_trade.entry_price - sl_dist
                ) or (
                    open_trade.direction == "sell" and price >= open_trade.entry_price + sl_dist
                )
                tp_hit = (
                    open_trade.direction == "buy" and price >= open_trade.entry_price + tp_dist
                ) or (
                    open_trade.direction == "sell" and price <= open_trade.entry_price - tp_dist
                )
                if sl_hit or tp_hit:
                    # Dollars risked = stake; TP pays R-multiple, SL loses stake
                    rr = settings.DEFAULT_TP_PIPS / max(1, settings.DEFAULT_SL_PIPS)
                    pnl = open_trade.stake * rr if tp_hit else -open_trade.stake
                    open_trade.exit_price = price
                    open_trade.pnl = pnl
                    balance += pnl
                    self.risk_gate.record_pnl(pnl)
                    result.trades.append(open_trade)
                    equity_curve.append(balance)
                    open_trade = None

            if signal and open_trade is None and not self.risk_gate.kill_switch_active:
                risk = self.risk_gate.evaluate(signal, balance)
                if risk.decision.value == "approved":
                    # Use risk dollars (1.5% of balance), not the FX lot-size formula
                    dollars_risked = max(
                        1.0, round(balance * (settings.RISK_PERCENT_PER_TRADE / 100.0), 2)
                    )
                    open_trade = BacktestTrade(
                        symbol=symbol,
                        direction=signal.direction.value,
                        entry_price=price,
                        exit_price=0.0,
                        pnl=0.0,
                        stake=dollars_risked,
                    )

        if result.trades:
            wins = sum(1 for t in result.trades if t.pnl > 0)
            result.win_rate = wins / len(result.trades)
            result.total_pnl = sum(t.pnl for t in result.trades)
            pnls = pd.Series([t.pnl for t in result.trades])
            cumulative = pnls.cumsum()
            result.max_drawdown = float(abs((cumulative - cumulative.cummax()).min()))
            result.expectancy = float(pnls.mean())

        result.passed = (
            result.expectancy > 0
            and result.total_pnl > 0
            and result.max_drawdown < self.initial_balance * 0.15
            and len(result.trades) > 0
        )
        # High win-rate gate is applied separately for pattern strategy arming
        result.high_win_rate = (
            len(result.trades) >= settings.STRATEGY_MIN_TRADES
            and result.win_rate >= settings.STRATEGY_MIN_WIN_RATE
        )
        return result

    async def run_live_history(self, symbol: str, count: int = 500) -> BacktestResult:
        """Fetch candles over public legacy WS (no auth required for history)."""
        client = DerivWebSocketClient(
            app_id="1089",
            api_token="",
            ws_url="wss://ws.derivws.com/websockets/v3?app_id=1089",
        )
        await client.connect()
        try:
            candles = await client.get_candles_history(
                symbol, settings.granularity_seconds, count
            )
            df = pd.DataFrame(candles)
            return self.run_on_dataframe(symbol, df)
        finally:
            await client.disconnect()

    async def run_all_pairs(self, count: int = 500) -> dict:
        """One public WS for all pairs — avoids OTP reconnect storms."""
        results = {}
        client = DerivWebSocketClient(
            app_id="1089",
            api_token="",
            ws_url="wss://ws.derivws.com/websockets/v3?app_id=1089",
        )
        await client.connect()
        try:
            for symbol in settings.pairs_list:
                try:
                    candles = await client.get_candles_history(
                        symbol, settings.granularity_seconds, count
                    )
                    df = pd.DataFrame(candles)
                    print(f"{symbol}: fetched {len(df)} candles")
                    results[symbol] = self.run_on_dataframe(symbol, df).to_dict()
                except Exception as exc:
                    results[symbol] = {"error": str(exc)}
        finally:
            await client.disconnect()
        return results
