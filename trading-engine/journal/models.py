"""SQLAlchemy models for trade journal."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String, Text, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from config import settings

Base = declarative_base()


class TradeJournal(Base):
    __tablename__ = "trade_journal"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(32), nullable=False)
    direction = Column(String(8), nullable=False)
    entry_price = Column(Float, nullable=False)
    exit_price = Column(Float, nullable=True)
    stake = Column(Float, nullable=False)
    stop_loss = Column(Float, nullable=False)
    take_profit = Column(Float, nullable=False)
    # Deriv multiplier limit_order amounts (USD P/L); journal SL/TP columns are chart prices
    stop_loss_usd = Column(Float, nullable=True)
    take_profit_usd = Column(Float, nullable=True)
    pnl = Column(Float, nullable=True)
    signal_source = Column(String(64), default="confluence")
    rsi_at_entry = Column(Float, nullable=True)
    macd_at_entry = Column(Float, nullable=True)
    spread = Column(Float, nullable=True)
    slippage = Column(Float, nullable=True)
    contract_id = Column(String(64), nullable=True)
    status = Column(String(16), default="open")  # open, closed, cancelled
    mode = Column(String(16), default="log_only")
    reason = Column(Text, nullable=True)
    confidence = Column(Float, nullable=True)
    market_condition = Column(String(32), nullable=True)
    score_breakdown = Column(Text, nullable=True)  # JSON
    sl_tp_method = Column(String(32), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    closed_at = Column(DateTime, nullable=True)


class TradingSession(Base):
    __tablename__ = "trading_sessions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_date = Column(String(10), nullable=False)
    start_balance = Column(Float, nullable=False)
    end_balance = Column(Float, nullable=True)
    cumulative_pnl = Column(Float, default=0.0)
    kill_switch_triggered = Column(Boolean, default=False)
    started_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    ended_at = Column(DateTime, nullable=True)


class BotState(Base):
    __tablename__ = "trading_bot_state"

    id = Column(Integer, primary_key=True, autoincrement=True)
    state = Column(String(16), default="stopped")  # running, paused, killed, stopped
    mode = Column(String(16), default="log_only")
    last_heartbeat = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    daily_pnl = Column(Float, default=0.0)


class SignalLog(Base):
    __tablename__ = "signal_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(32), nullable=False)
    direction = Column(String(8), nullable=False)
    rsi = Column(Float, nullable=True)
    macd = Column(Float, nullable=True)
    price = Column(Float, nullable=False)
    epoch = Column(Integer, nullable=False)
    reason = Column(Text, nullable=True)
    risk_decision = Column(String(16), nullable=True)
    risk_reason = Column(Text, nullable=True)
    strategy_id = Column(String(64), nullable=True)
    confidence = Column(Float, nullable=True)
    market_condition = Column(String(32), nullable=True)
    score_breakdown = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_type = Column(String(32), nullable=False)  # preflight, open, close
    symbol = Column(String(32), nullable=True)
    passed = Column(Boolean, default=False)
    decision = Column(String(16), default="NO-GO")  # GO, NO-GO
    reasons = Column(Text, nullable=True)  # JSON list
    sources = Column(Text, nullable=True)  # JSON dict
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


def get_engine():
    return create_engine(settings.DATABASE_URL, echo=settings.DEBUG)


def init_db() -> sessionmaker:
    engine = get_engine()
    Base.metadata.create_all(engine)
    # Best-effort migrate new columns on existing SQLite DBs
    _ensure_columns(engine)
    return sessionmaker(bind=engine)


def _ensure_columns(engine) -> None:
    migrations = [
        ("trade_journal", "confidence", "FLOAT"),
        ("trade_journal", "market_condition", "VARCHAR(32)"),
        ("trade_journal", "score_breakdown", "TEXT"),
        ("trade_journal", "sl_tp_method", "VARCHAR(32)"),
        ("trade_journal", "stop_loss_usd", "FLOAT"),
        ("trade_journal", "take_profit_usd", "FLOAT"),
        ("signal_logs", "strategy_id", "VARCHAR(64)"),
        ("signal_logs", "confidence", "FLOAT"),
        ("signal_logs", "market_condition", "VARCHAR(32)"),
        ("signal_logs", "score_breakdown", "TEXT"),
    ]
    try:
        with engine.connect() as conn:
            for table, col, coltype in migrations:
                try:
                    conn.execute(
                        __import__("sqlalchemy").text(
                            f"ALTER TABLE {table} ADD COLUMN {col} {coltype}"
                        )
                    )
                    conn.commit()
                except Exception:
                    pass
    except Exception:
        logger = __import__("logging").getLogger(__name__)
        logger.debug("Column migrate skipped", exc_info=True)
