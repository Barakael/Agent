"""Telegram notifications for trades and daily P&L."""

from __future__ import annotations

import logging

import httpx

from config import settings

logger = logging.getLogger(__name__)


class TelegramAlerter:
    def __init__(self) -> None:
        self.token = settings.TELEGRAM_BOT_TOKEN
        self.chat_id = settings.TELEGRAM_CHAT_ID
        self.enabled = bool(self.token and self.chat_id)

    async def send(self, message: str) -> bool:
        if not self.enabled:
            logger.debug("Telegram disabled: %s", message[:80])
            return False
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    url,
                    json={"chat_id": self.chat_id, "text": message, "parse_mode": "HTML"},
                )
                resp.raise_for_status()
            return True
        except Exception:
            logger.exception("Telegram send failed")
            return False

    async def trade_opened(self, symbol: str, direction: str, stake: float, mode: str) -> None:
        await self.send(
            f"<b>Trade opened</b> ({mode})\n"
            f"{direction.upper()} {symbol}\nStake: ${stake:.2f}"
        )

    async def trade_closed(self, symbol: str, pnl: float) -> None:
        emoji = "+" if pnl >= 0 else ""
        await self.send(f"<b>Trade closed</b> {symbol}\nP&L: {emoji}${pnl:.2f}")

    async def daily_summary(self, pnl: float, metrics: dict) -> None:
        await self.send(
            f"<b>Daily summary</b>\n"
            f"P&L: ${pnl:.2f}\n"
            f"Win rate: {metrics.get('win_rate', 0)}%\n"
            f"Trades: {metrics.get('total_trades', 0)}\n"
            f"Max DD: ${metrics.get('max_drawdown', 0)}"
        )

    async def kill_switch(self, reason: str) -> None:
        await self.send(f"<b>KILL SWITCH</b>\n{reason}")
