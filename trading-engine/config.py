import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """All strategy and risk parameters are env-driven — never hardcoded."""

    # Service
    API_TITLE: str = "Wayda Trading Engine"
    API_VERSION: str = "1.0.0"
    DEBUG: bool = os.getenv("DEBUG", "true").lower() == "true"
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8002"))
    TRADING_SERVICE_API_KEY: str = os.getenv("TRADING_SERVICE_API_KEY", "")
    BACKEND_URL: str = os.getenv("BACKEND_URL", "http://localhost:8000")
    BACKEND_API_KEY: str = os.getenv("BACKEND_API_KEY", "")

    # Deriv — PAT from developers.deriv.com Dashboard → API tokens (demo account)
    DERIV_APP_ID: str = os.getenv("DERIV_APP_ID", "1089")
    DERIV_CLIENT_ID: str = os.getenv("DERIV_CLIENT_ID", "")
    DERIV_API_TOKEN: str = os.getenv("DERIV_API_TOKEN", "")
    DERIV_WS_URL: str = os.getenv(
        "DERIV_WS_URL",
        f"wss://ws.derivws.com/websockets/v3?app_id={os.getenv('DERIV_APP_ID', '1089')}",
    )
    DERIV_WS_APP_ID: str = os.getenv("DERIV_WS_APP_ID", "1089")
    # Optional: force demo wallet (VRTC… login id)
    DERIV_DEMO_LOGINID: str = os.getenv("DERIV_DEMO_LOGINID", "")
    # New API: options account id for OTP WebSocket (from REST list accounts)
    DERIV_ACCOUNT_ID: str = os.getenv("DERIV_ACCOUNT_ID", "")
    # Multiplier contracts on synthetics — 100 is often invalid; 80 is commonly accepted
    DERIV_MULTIPLIER: float = float(os.getenv("DERIV_MULTIPLIER", "80"))

    # Analysis engine (ATAE) — optional when NUMBER_ENGINE_EXECUTION is on
    ANALYSIS_REQUIRE_PREFLIGHT: bool = os.getenv("ANALYSIS_REQUIRE_PREFLIGHT", "true").lower() == "true"
    ANALYSIS_SCENARIO_WINDOW_BARS: int = int(os.getenv("ANALYSIS_SCENARIO_WINDOW_BARS", "50"))
    ANALYSIS_MIN_SCENARIO_WIN_RATE: float = float(os.getenv("ANALYSIS_MIN_SCENARIO_WIN_RATE", "0.45"))
    ANALYSIS_PREFLIGHT_BACKTEST_BARS: int = int(os.getenv("ANALYSIS_PREFLIGHT_BACKTEST_BARS", "500"))
    ANALYSIS_AI_DECISION_URL: str = os.getenv("ANALYSIS_AI_DECISION_URL", "")

    # Always-on Number Engine: Deriv → NumberEngine → StrategyManager → RiskGate
    # AUTO_START_BOT: start the bot loop when uvicorn boots (set true on VPS)
    AUTO_START_BOT: bool = os.getenv("AUTO_START_BOT", "false").lower() == "true"
    # NUMBER_ENGINE_EXECUTION: skip ATAE evaluate_open / analysis_armed for opens
    NUMBER_ENGINE_EXECUTION: bool = (
        os.getenv("NUMBER_ENGINE_EXECUTION", "true").lower() == "true"
    )

    # Block live account unless TRADING_MODE=live
    DERIV_REQUIRE_DEMO: bool = os.getenv("DERIV_REQUIRE_DEMO", "true").lower() == "true"

    # Trading mode: log_only | demo | live
    TRADING_MODE: str = os.getenv("TRADING_MODE", "log_only")

    # Pairs — Deriv symbols
    # frx* = forex (Mon–Fri only); R_* / 1HZ* = synthetic volatility (24/7)
    TRADING_PAIRS: str = os.getenv(
        "TRADING_PAIRS",
        "R_10,R_25,R_50,R_75,R_100",
    )
    CANDLE_TIMEFRAME_MINUTES: int = int(os.getenv("CANDLE_TIMEFRAME_MINUTES", "5"))
    CANDLE_BUFFER_SIZE: int = int(os.getenv("CANDLE_BUFFER_SIZE", "200"))

    # Indicators
    RSI_PERIOD: int = int(os.getenv("RSI_PERIOD", "14"))
    RSI_OVERSOLD: float = float(os.getenv("RSI_OVERSOLD", "30"))
    RSI_OVERBOUGHT: float = float(os.getenv("RSI_OVERBOUGHT", "70"))
    MACD_FAST: int = int(os.getenv("MACD_FAST", "12"))
    MACD_SLOW: int = int(os.getenv("MACD_SLOW", "26"))
    MACD_SIGNAL: int = int(os.getenv("MACD_SIGNAL", "9"))

    # Strategy Manager
    STRATEGY_CONFIDENCE_THRESHOLD: float = float(
        os.getenv("STRATEGY_CONFIDENCE_THRESHOLD", "70")
    )
    ATR_SL_MULTIPLIER: float = float(os.getenv("ATR_SL_MULTIPLIER", "1.5"))
    DEFAULT_RR_RATIO: float = float(os.getenv("DEFAULT_RR_RATIO", "2.0"))

    # Risk (moderate profile)
    RISK_PERCENT_PER_TRADE: float = float(os.getenv("RISK_PERCENT_PER_TRADE", "1.5"))
    DAILY_DRAWDOWN_LIMIT_PERCENT: float = float(
        os.getenv("DAILY_DRAWDOWN_LIMIT_PERCENT", "4.0")
    )
    MAX_DAILY_PROFIT_PERCENT: float = float(os.getenv("MAX_DAILY_PROFIT_PERCENT", "8.0"))
    MAX_TRADES_PER_DAY: int = int(os.getenv("MAX_TRADES_PER_DAY", "20"))
    DEFAULT_SL_PIPS: int = int(os.getenv("DEFAULT_SL_PIPS", "15"))
    DEFAULT_TP_PIPS: int = int(os.getenv("DEFAULT_TP_PIPS", "30"))
    TRAILING_STOP_ENABLED: bool = os.getenv("TRAILING_STOP_ENABLED", "false").lower() == "true"
    TRAILING_STOP_PIPS: int = int(os.getenv("TRAILING_STOP_PIPS", "10"))

    STRATEGY_MIN_WIN_RATE: float = float(os.getenv("STRATEGY_MIN_WIN_RATE", "0.70"))
    STRATEGY_MIN_TRADES: int = int(os.getenv("STRATEGY_MIN_TRADES", "3"))

    # Daily plan clamps (automation callback)
    PLAN_RISK_PERCENT_MAX: float = float(os.getenv("PLAN_RISK_PERCENT_MAX", "2.0"))
    PLAN_MAX_STAKE_USD_CEILING: float = float(os.getenv("PLAN_MAX_STAKE_USD_CEILING", "50"))

    # Session — force close all positions before this time (UTC)
    # SESSION_ENFORCE=false for 24/7 synthetics (no open/close window)
    SESSION_ENFORCE: bool = os.getenv("SESSION_ENFORCE", "true").lower() == "true"
    SESSION_CLOSE_HOUR_UTC: int = int(os.getenv("SESSION_CLOSE_HOUR_UTC", "21"))
    SESSION_CLOSE_MINUTE_UTC: int = int(os.getenv("SESSION_CLOSE_MINUTE_UTC", "0"))
    SESSION_OPEN_HOUR_UTC: int = int(os.getenv("SESSION_OPEN_HOUR_UTC", "7"))

    # News calendar pause (minutes before/after high-impact events)
    NEWS_PAUSE_MINUTES_BEFORE: int = int(os.getenv("NEWS_PAUSE_MINUTES_BEFORE", "30"))
    NEWS_PAUSE_MINUTES_AFTER: int = int(os.getenv("NEWS_PAUSE_MINUTES_AFTER", "15"))

    # Storage
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./trading_journal.db")

    # Telegram alerts
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")

    class Config:
        env_file = ".env"
        case_sensitive = True

    @property
    def pairs_list(self) -> list[str]:
        return [p.strip() for p in self.TRADING_PAIRS.split(",") if p.strip()]

    @property
    def granularity_seconds(self) -> int:
        return self.CANDLE_TIMEFRAME_MINUTES * 60

    @property
    def deriv_ws_app_id(self) -> str:
        """Legacy WebSocket requires a numeric app_id; OAuth client UUIDs are not valid here."""
        raw = self.DERIV_APP_ID.strip()
        if raw.isdigit():
            return raw
        return self.DERIV_WS_APP_ID.strip() or "1089"


settings = Settings()
settings.DERIV_WS_URL = (
    f"wss://ws.derivws.com/websockets/v3?app_id={settings.deriv_ws_app_id}"
)
