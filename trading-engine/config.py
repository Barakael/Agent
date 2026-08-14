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
    # Liquidation happens at 1/multiplier, which caps how wide a stop can be.
    # Deriv offers 100/200/300/500/800 on forex, so 100 is the most room available
    # (1.0% of price) and the only value that holds a one-ATR stop on the majors,
    # whose daily ATR measures 0.4-0.7%. Synthetics start at 80 (1.25% of room)
    # against a 4% daily ATR, which is why they were dropped. See
    # scripts/instrument_fit.py. Validated against Deriv's list at startup.
    DERIV_MULTIPLIER: float = float(os.getenv("DERIV_MULTIPLIER", "100"))
    # Headroom required between the planned stop and liquidation
    MULTIPLIER_STOP_SAFETY: float = float(os.getenv("MULTIPLIER_STOP_SAFETY", "1.25"))
    # Close forex positions this many minutes before Friday's close. A stop is a
    # dollar limit, not a guaranteed price, so a weekend gap can pass straight
    # through it. Set to 0 to carry positions over the weekend deliberately.
    FOREX_WEEKEND_FLATTEN_MINUTES: int = int(
        os.getenv("FOREX_WEEKEND_FLATTEN_MINUTES", "20")
    )
    # Ask the venue where a dollar stop actually fires and correct for the cost
    # baked into it, so barriers land on the chart levels instead of ~18% inside
    # them. Costs two extra proposals per symbol, cached per stake.
    CALIBRATE_CONTRACT_BARRIERS: bool = (
        os.getenv("CALIBRATE_CONTRACT_BARRIERS", "true").lower() == "true"
    )
    # Refuse a trade whose chart stop cannot be encoded, instead of shipping a tighter one
    REJECT_UNENCODABLE_STOP: bool = (
        os.getenv("REJECT_UNENCODABLE_STOP", "true").lower() == "true"
    )

    # Entry patterns allowed to fire. Breakouts are excluded by default: every
    # live fill used one and they lost on their own exits. Add "break_of_structure"
    # / "break_prev" only after replay measures them.
    PRICE_ACTION_PATTERNS: str = os.getenv("PRICE_ACTION_PATTERNS", "pin,engulfing")
    BIAS_CONFIRM_TYPES: str = os.getenv("BIAS_CONFIRM_TYPES", "pin,engulfing")

    # Analysis engine (ATAE) — optional when NUMBER_ENGINE_EXECUTION is on
    ANALYSIS_REQUIRE_PREFLIGHT: bool = os.getenv("ANALYSIS_REQUIRE_PREFLIGHT", "false").lower() == "true"
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
    # frx* = forex (closed Fri 20:55 to Sun 21:05 UTC); R_* / 1HZ* = synthetic (24/7)
    # Majors only: their daily ATR fits inside the contract room at x100. Gold
    # (2.2% ATR) and the synthetics (4% ATR) do not, so a stop set from the chart
    # cannot be encoded on them. Re-check with scripts/instrument_fit.py before
    # adding a symbol.
    TRADING_PAIRS: str = os.getenv(
        "TRADING_PAIRS",
        "frxEURUSD,frxGBPUSD,frxUSDJPY,frxAUDUSD,frxUSDCAD",
    )
    CANDLE_TIMEFRAME_MINUTES: int = int(os.getenv("CANDLE_TIMEFRAME_MINUTES", "5"))
    # >=288 for 24h regime; >=360 for 30×1h; 400 clears 1h confirm with headroom
    CANDLE_BUFFER_SIZE: int = int(os.getenv("CANDLE_BUFFER_SIZE", "400"))

    # Bias pipeline (R_50): 24h regime → 6h bias → 1h confirm; 5m is feed only
    BIAS_PIPELINE: bool = os.getenv("BIAS_PIPELINE", "true").lower() == "true"
    BIAS_PIPELINE_SYMBOLS: str = os.getenv("BIAS_PIPELINE_SYMBOLS", "R_50")
    BIAS_REGIME_HOURS: int = int(os.getenv("BIAS_REGIME_HOURS", "24"))
    BIAS_LOOKBACK_HOURS: int = int(os.getenv("BIAS_LOOKBACK_HOURS", "6"))
    BIAS_ENTRY_TF_MINUTES: int = int(os.getenv("BIAS_ENTRY_TF_MINUTES", "60"))
    BIAS_DEADZONE_ATR_FRAC: float = float(os.getenv("BIAS_DEADZONE_ATR_FRAC", "0.3"))
    BIAS_MAX_OPEN_THESIS: int = int(os.getenv("BIAS_MAX_OPEN_THESIS", "1"))
    BIAS_SL_ATR_MULT: float = float(os.getenv("BIAS_SL_ATR_MULT", "1.0"))

    # Independent horizon reviews (advisory; do not place orders)
    # Mid review: 4 or 6h cadence; 8h review: separate longer-horizon stance
    REVIEW_HORIZON_ENABLED: bool = (
        os.getenv("REVIEW_HORIZON_ENABLED", "true").lower() == "true"
    )
    REVIEW_MID_HOURS: int = int(os.getenv("REVIEW_MID_HOURS", "6"))  # 4 or 6
    REVIEW_8H_HOURS: int = int(os.getenv("REVIEW_8H_HOURS", "8"))
    REVIEW_HORIZON_SYMBOLS: str = os.getenv("REVIEW_HORIZON_SYMBOLS", "")  # empty = active pairs

    # 8h structure+ATR “enter now” projection + soft gate vs 6h bias
    PROJECTION_ENABLED: bool = os.getenv("PROJECTION_ENABLED", "true").lower() == "true"
    PROJECTION_LOOKBACK_HOURS: int = int(os.getenv("PROJECTION_LOOKBACK_HOURS", "8"))
    PROJECTION_FORWARD_HOURS: int = int(os.getenv("PROJECTION_FORWARD_HOURS", "6"))
    PROJECTION_ATR_MULT: float = float(os.getenv("PROJECTION_ATR_MULT", "1.0"))
    PROJECTION_SOFT_GATE: bool = os.getenv("PROJECTION_SOFT_GATE", "true").lower() == "true"

    # Indicators
    RSI_PERIOD: int = int(os.getenv("RSI_PERIOD", "14"))
    RSI_OVERSOLD: float = float(os.getenv("RSI_OVERSOLD", "30"))
    RSI_OVERBOUGHT: float = float(os.getenv("RSI_OVERBOUGHT", "70"))
    MACD_FAST: int = int(os.getenv("MACD_FAST", "12"))
    MACD_SLOW: int = int(os.getenv("MACD_SLOW", "26"))
    MACD_SIGNAL: int = int(os.getenv("MACD_SIGNAL", "9"))

    # Strategy Manager
    STRATEGY_CONFIDENCE_THRESHOLD: float = float(
        os.getenv("STRATEGY_CONFIDENCE_THRESHOLD", "94")
    )
    # Comma list; empty = all pattern strategies. Example: trend_following
    STRATEGY_ALLOWLIST: str = os.getenv("STRATEGY_ALLOWLIST", "trend_following")
    # Strategies barred regardless of allowlist or regime routing. range_trading
    # went 0/12 and momentum 0/5 in demo, neither ever winning on its own exit.
    # Remove an id only after replay shows positive expectancy for it.
    STRATEGY_DENYLIST: str = os.getenv("STRATEGY_DENYLIST", "range_trading,momentum")
    ATR_SL_MULTIPLIER: float = float(os.getenv("ATR_SL_MULTIPLIER", "1.5"))
    DEFAULT_RR_RATIO: float = float(os.getenv("DEFAULT_RR_RATIO", "2.0"))

    # Risk (moderate profile)
    RISK_PERCENT_PER_TRADE: float = float(os.getenv("RISK_PERCENT_PER_TRADE", "1.5"))
    # Demo: fixed USD stake. Live: balance × RISK_PERCENT_PER_TRADE
    DEMO_FIXED_STAKE_USD: float = float(os.getenv("DEMO_FIXED_STAKE_USD", "100"))
    DAILY_DRAWDOWN_LIMIT_PERCENT: float = float(
        os.getenv("DAILY_DRAWDOWN_LIMIT_PERCENT", "4.0")
    )
    MAX_DAILY_PROFIT_PERCENT: float = float(os.getenv("MAX_DAILY_PROFIT_PERCENT", "8.0"))
    # 0 = unlimited. Capped because 22 fills once landed in a single 8h window and
    # one operator flatten then decided the month's result.
    MAX_TRADES_PER_DAY: int = int(os.getenv("MAX_TRADES_PER_DAY", "4"))
    # One position at a time: the thesis is a single 6h swing, not a basket.
    MAX_OPEN_POSITIONS: int = int(os.getenv("MAX_OPEN_POSITIONS", "1"))
    DEFAULT_SL_PIPS: int = int(os.getenv("DEFAULT_SL_PIPS", "15"))
    DEFAULT_TP_PIPS: int = int(os.getenv("DEFAULT_TP_PIPS", "30"))
    TRAILING_STOP_ENABLED: bool = os.getenv("TRAILING_STOP_ENABLED", "false").lower() == "true"
    TRAILING_STOP_PIPS: int = int(os.getenv("TRAILING_STOP_PIPS", "10"))

    STRATEGY_MIN_WIN_RATE: float = float(os.getenv("STRATEGY_MIN_WIN_RATE", "0.70"))
    STRATEGY_MIN_TRADES: int = int(os.getenv("STRATEGY_MIN_TRADES", "3"))

    # Daily plan clamps (automation callback)
    PLAN_RISK_PERCENT_MAX: float = float(os.getenv("PLAN_RISK_PERCENT_MAX", "2.0"))
    PLAN_MAX_STAKE_USD_CEILING: float = float(os.getenv("PLAN_MAX_STAKE_USD_CEILING", "100"))

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
    def strategy_allowlist(self) -> list[str]:
        """Resolved strategy ids from STRATEGY_ALLOWLIST; empty means no restriction."""
        raw = [p.strip() for p in self.STRATEGY_ALLOWLIST.split(",") if p.strip()]
        # Lazy import avoided — aliases applied by callers via resolve_strategy_id
        return raw

    @property
    def bias_pipeline_symbols(self) -> list[str]:
        return [p.strip() for p in self.BIAS_PIPELINE_SYMBOLS.split(",") if p.strip()]

    def uses_bias_pipeline(self, symbol: str) -> bool:
        return bool(self.BIAS_PIPELINE) and symbol in self.bias_pipeline_symbols

    @property
    def review_horizon_symbols(self) -> list[str]:
        raw = [p.strip() for p in self.REVIEW_HORIZON_SYMBOLS.split(",") if p.strip()]
        return raw

    def uses_horizon_review(self, symbol: str) -> bool:
        if not self.REVIEW_HORIZON_ENABLED:
            return False
        scoped = self.review_horizon_symbols
        if not scoped:
            return True
        return symbol in scoped

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
