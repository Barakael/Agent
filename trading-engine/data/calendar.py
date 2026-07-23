"""Economic calendar — pause trading around high-impact news events."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from xml.etree import ElementTree

import httpx

from config import settings

logger = logging.getLogger(__name__)

FF_CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.xml"


@dataclass
class EconomicEvent:
    title: str
    currency: str
    impact: str  # High, Medium, Low
    event_time: datetime

    @property
    def is_high_impact(self) -> bool:
        return self.impact.lower() == "high"


class EconomicCalendar:
    """Fetch and cache Forex Factory calendar; detect news blackout windows."""

    def __init__(
        self,
        pause_before_minutes: Optional[int] = None,
        pause_after_minutes: Optional[int] = None,
    ) -> None:
        self.pause_before = pause_before_minutes or settings.NEWS_PAUSE_MINUTES_BEFORE
        self.pause_after = pause_after_minutes or settings.NEWS_PAUSE_MINUTES_AFTER
        self._events: List[EconomicEvent] = []
        self._last_fetch: Optional[datetime] = None

    async def refresh(self) -> None:
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(FF_CALENDAR_URL)
                resp.raise_for_status()
            self._events = self._parse_xml(resp.text)
            self._last_fetch = datetime.now(timezone.utc)
            logger.info("Loaded %d economic events", len(self._events))
        except Exception:
            logger.exception("Failed to fetch economic calendar")

    def _parse_xml(self, xml_text: str) -> List[EconomicEvent]:
        events: List[EconomicEvent] = []
        try:
            root = ElementTree.fromstring(xml_text)
            for event_el in root.findall(".//event"):
                title = (event_el.findtext("title") or "").strip()
                currency = (event_el.findtext("country") or "").strip()
                impact = (event_el.findtext("impact") or "Low").strip()
                date_str = (event_el.findtext("date") or "").strip()
                time_str = (event_el.findtext("time") or "").strip()
                if not date_str:
                    continue
                try:
                    dt_str = f"{date_str} {time_str or '12:00am'}"
                    event_time = datetime.strptime(dt_str, "%m-%d-%Y %I:%M%p")
                    event_time = event_time.replace(tzinfo=timezone.utc)
                except ValueError:
                    continue
                events.append(
                    EconomicEvent(
                        title=title,
                        currency=currency,
                        impact=impact,
                        event_time=event_time,
                    )
                )
        except ElementTree.ParseError:
            logger.warning("Could not parse calendar XML")
        return events

    def is_trading_paused(self, now: Optional[datetime] = None) -> tuple[bool, str]:
        now = now or datetime.now(timezone.utc)
        for event in self._events:
            if not event.is_high_impact:
                continue
            window_start = event.event_time - timedelta(minutes=self.pause_before)
            window_end = event.event_time + timedelta(minutes=self.pause_after)
            if window_start <= now <= window_end:
                return True, f"News pause: {event.title} ({event.currency})"
        return False, ""

    def is_paused_for_currencies(
        self,
        currencies: set[str],
        now: Optional[datetime] = None,
    ) -> tuple[bool, str]:
        """True if a high-impact event affects any of the given currencies."""
        if not currencies:
            return self.is_trading_paused(now)
        now = now or datetime.now(timezone.utc)
        for event in self._events:
            if not event.is_high_impact:
                continue
            event_currency = event.currency.upper()
            if event_currency != "ALL" and event_currency not in {c.upper() for c in currencies}:
                continue
            window_start = event.event_time - timedelta(minutes=self.pause_before)
            window_end = event.event_time + timedelta(minutes=self.pause_after)
            if window_start <= now <= window_end:
                return True, f"News pause: {event.title} ({event.currency})"
        return False, ""

    def upcoming_high_impact(self, hours: int = 24) -> List[EconomicEvent]:
        return self.upcoming_events(hours=hours, impacts={"high"})

    def upcoming_events(
        self,
        hours: int = 24,
        impacts: set[str] | None = None,
    ) -> List[EconomicEvent]:
        """Upcoming calendar events filtered by impact (default High+Medium)."""
        now = datetime.now(timezone.utc)
        cutoff = now + timedelta(hours=hours)
        wanted = {i.lower() for i in (impacts or {"high", "medium"})}
        return [
            e
            for e in self._events
            if e.impact.lower() in wanted and now <= e.event_time <= cutoff
        ]

    def to_brief_dict(self, hours: int = 24) -> dict:
        high = self.upcoming_high_impact(hours)
        medium_high = self.upcoming_events(hours=hours, impacts={"high", "medium"})
        next_6h = self.upcoming_events(hours=6, impacts={"high", "medium"})

        def _ser(e: EconomicEvent) -> dict:
            return {
                "title": e.title,
                "currency": e.currency,
                "impact": e.impact,
                "time": e.event_time.isoformat(),
            }

        return {
            "events_loaded": len(self._events),
            "last_fetch": self._last_fetch.isoformat() if self._last_fetch else None,
            "upcoming_high_impact": [_ser(e) for e in high[:20]],
            "upcoming_medium_high": [_ser(e) for e in medium_high[:30]],
            "next_6h": [_ser(e) for e in next_6h[:15]],
        }
