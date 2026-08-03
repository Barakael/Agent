"""Persist market feature logs for evidence-driven analysis."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.orm import sessionmaker

from journal.models import MarketFeatureLog, init_db

logger = logging.getLogger(__name__)


class FeatureStore:
    def __init__(self, session_factory: Optional[sessionmaker] = None) -> None:
        self._Session = session_factory or init_db()

    def log(
        self,
        *,
        symbol: str,
        event: str,
        features: dict[str, Any],
        bias_id: str | None = None,
        regime: str | None = None,
        bias: str | None = None,
        trade_id: int | None = None,
    ) -> None:
        try:
            with self._Session() as db:
                row = MarketFeatureLog(
                    symbol=symbol,
                    event=event,
                    bias_id=bias_id,
                    regime=regime,
                    bias=bias,
                    trade_id=trade_id,
                    features_json=json.dumps(features, default=str),
                    created_at=datetime.now(timezone.utc),
                )
                db.add(row)
                db.commit()
        except Exception:
            logger.exception("Failed to write market feature log")

    def recent(self, symbol: str | None = None, limit: int = 50) -> list[dict]:
        with self._Session() as db:
            q = db.query(MarketFeatureLog).order_by(MarketFeatureLog.id.desc())
            if symbol:
                q = q.filter(MarketFeatureLog.symbol == symbol)
            rows = q.limit(limit).all()
            out = []
            for r in rows:
                try:
                    feats = json.loads(r.features_json or "{}")
                except Exception:
                    feats = {}
                out.append(
                    {
                        "id": r.id,
                        "symbol": r.symbol,
                        "event": r.event,
                        "bias_id": r.bias_id,
                        "regime": r.regime,
                        "bias": r.bias,
                        "trade_id": r.trade_id,
                        "features": feats,
                        "created_at": r.created_at.isoformat() if r.created_at else None,
                    }
                )
            return out
