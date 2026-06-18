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

    def to_dict(self) -> dict:
        return {
            "total_trades": len(self.trades),
            "total_pnl": round(self.total_pnl, 2),
            "win_rate": round(self.win_rate * 100, 2),
            "max_drawdown": round(self.max_drawdown, 2),
            "expectancy": round(self.expectancy, 4),
            "passed": self.passed,
        }


class BacktestRunner:
    def __init__(self, initial_balance: float = 10000.0) -> None:
        self.initial_balance = initial_balance
        self.signal_engine = SignalEngine()
        self.risk_gate = RiskGate()
        self.risk_gate.reset_session(initial_balance)

    def run_on_dataframe(self, symbol: str, df: pd.DataFrame) -> BacktestResult:
        result = BacktestResult()
        balance = self.initial_balance
        equity_curve = [balance]
        open_trade: BacktestTrade | None = None

        min_bars = settings.MACD_SLOW + settings.MACD_SIGNAL + settings.RSI_PERIOD + 2

        for i in range(min_bars, len(df)):
            window = df.iloc[: i + 1].copy()
            signal = self.signal_engine.evaluate(symbol, window)
            bar = df.iloc[i]
            price = float(bar["close"])

            if open_trade:
                sl_hit = (
                    open_trade.direction == "buy" and price <= open_trade.entry_price - settings.DEFAULT_SL_PIPS * 0.0001
                ) or (
                    open_trade.direction == "sell" and price >= open_trade.entry_price + settings.DEFAULT_SL_PIPS * 0.0001
                )
                tp_hit = (
                    open_trade.direction == "buy" and price >= open_trade.entry_price + settings.DEFAULT_TP_PIPS * 0.0001
                ) or (
                    open_trade.direction == "sell" and price <= open_trade.entry_price - settings.DEFAULT_TP_PIPS * 0.0001
                )
                if sl_hit or tp_hit:
                    exit_price = price
                    if open_trade.direction == "buy":
                        pnl = (exit_price - open_trade.entry_price) * open_trade.stake * 10000
                    else:
                        pnl = (open_trade.entry_price - exit_price) * open_trade.stake * 10000
                    open_trade.exit_price = exit_price
                    open_trade.pnl = pnl
                    balance += pnl
                    self.risk_gate.record_pnl(pnl)
                    result.trades.append(open_trade)
                    equity_curve.append(balance)
                    open_trade = None

            if signal and open_trade is None and not self.risk_gate.kill_switch_active:
                risk = self.risk_gate.evaluate(signal, balance)
                if risk.decision.value == "approved":
                    open_trade = BacktestTrade(
                        symbol=symbol,
                        direction=signal.direction.value,
                        entry_price=price,
                        exit_price=0.0,
                        pnl=0.0,
                        stake=risk.stake,
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
        )
        return result

    async def run_live_history(self, symbol: str, count: int = 500) -> BacktestResult:
        client = DerivWebSocketClient()
        await client.connect()
        try:
            if settings.DERIV_API_TOKEN:
                await client.authorize()
            candles = await client.get_candles_history(
                symbol, settings.granularity_seconds, count
            )
            df = pd.DataFrame(candles)
            return self.run_on_dataframe(symbol, df)
        finally:
            await client.disconnect()

    async def run_all_pairs(self) -> dict:
        results = {}
        for symbol in settings.pairs_list:
            try:
                results[symbol] = (await self.run_live_history(symbol)).to_dict()
            except Exception as exc:
                results[symbol] = {"error": str(exc)}
        return results
