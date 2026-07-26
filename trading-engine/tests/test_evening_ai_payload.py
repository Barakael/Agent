"""Tests for privacy-safe evening AI payload."""

from __future__ import annotations

from datetime import datetime, timezone

from journal.models import Base, SignalLog, TradeJournal, get_engine, init_db
from journal.writer import JournalWriter


def test_evening_ai_payload_has_no_sensitive_fields(tmp_path, monkeypatch):
    db = tmp_path / "t.db"
    url = f"sqlite:///{db}"
    monkeypatch.setenv("DATABASE_URL", url)
    import config

    monkeypatch.setattr(config.settings, "DATABASE_URL", url)

    engine = get_engine()
    Base.metadata.create_all(engine)
    Session = init_db()
    writer = JournalWriter()
    writer.Session = Session

    with Session() as session:
        session.add(
            TradeJournal(
                symbol="frxEURUSD",
                direction="buy",
                entry_price=1.1000,
                exit_price=1.1020,
                stake=25.0,
                stop_loss=1.0980,
                take_profit=1.1040,
                pnl=5.0,
                signal_source="momentum",
                status="closed",
                mode="demo",
                reason="secret reason with price 1.1000",
                confidence=82.0,
                market_condition="trending",
                contract_id="secret-contract-99",
                created_at=datetime(2026, 7, 26, 14, 30, tzinfo=timezone.utc),
                closed_at=datetime(2026, 7, 26, 15, 0, tzinfo=timezone.utc),
            )
        )
        session.add(
            SignalLog(
                symbol="frxEURUSD",
                direction="none",
                price=1.1010,
                epoch=1,
                reason="NO_TRADE: low confidence",
                risk_decision="skipped",
                confidence=40.0,
                market_condition="quiet",
                created_at=datetime(2026, 7, 26, 10, 0, tzinfo=timezone.utc),
            )
        )
        session.commit()

    payload = writer.get_evening_ai_payload("2026-07-26")
    blob = str(payload)
    assert "1.1000" not in blob
    assert "secret-contract" not in blob
    assert "entry_price" not in blob
    assert "contract" not in blob
    assert "trades" not in payload  # no raw trades list at top level
    assert isinstance(payload["summary"]["skips"], int)
    assert "by_strategy" in payload
    assert "by_hour_utc" in payload
    assert payload["by_strategy"]["momentum"]["trades"] == 1
    assert "14" in payload["by_hour_utc"]
    # Sensitive keys must not appear in summary
    for key in ("stake", "entry_price", "contract_id", "loginid", "balance"):
        assert key not in payload["summary"]
