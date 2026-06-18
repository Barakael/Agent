"""Trading session management — force close before end of session."""

from __future__ import annotations

import logging
from datetime import datetime, time, timezone

from config import settings

logger = logging.getLogger(__name__)


class SessionManager:
    """Enforce intraday-only trading — zero overnight exposure."""

    def __init__(self) -> None:
        self.open_hour = settings.SESSION_OPEN_HOUR_UTC
        self.close_hour = settings.SESSION_CLOSE_HOUR_UTC
        self.close_minute = settings.SESSION_CLOSE_MINUTE_UTC

    def is_session_open(self, now: datetime | None = None) -> bool:
        now = now or datetime.now(timezone.utc)
        current = now.time()
        open_time = time(self.open_hour, 0)
        close_time = time(self.close_hour, self.close_minute)
        if open_time <= close_time:
            return open_time <= current < close_time
        return current >= open_time or current < close_time

    def must_force_close(self, now: datetime | None = None) -> bool:
        """True when we are at or past session close — close all positions."""
        now = now or datetime.now(timezone.utc)
        close_time = time(self.close_hour, self.close_minute)
        current = now.time()
        return current >= close_time

    def seconds_until_close(self, now: datetime | None = None) -> int:
        now = now or datetime.now(timezone.utc)
        close_dt = now.replace(
            hour=self.close_hour,
            minute=self.close_minute,
            second=0,
            microsecond=0,
        )
        if now >= close_dt:
            return 0
        return int((close_dt - now).total_seconds())

    def session_status(self) -> dict:
        now = datetime.now(timezone.utc)
        return {
            "session_open": self.is_session_open(now),
            "must_force_close": self.must_force_close(now),
            "seconds_until_close": self.seconds_until_close(now),
            "close_time_utc": f"{self.close_hour:02d}:{self.close_minute:02d}",
        }
