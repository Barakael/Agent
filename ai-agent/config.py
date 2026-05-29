import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings from environment variables."""

    # API Configuration
    API_TITLE: str = "Agent AI Service"
    API_VERSION: str = "1.0.0"
    DEBUG: bool = os.getenv("DEBUG", "true").lower() == "true"

    # OpenAI Configuration
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-5.5")
    OPENAI_REASONING_EFFORT: str = os.getenv("OPENAI_REASONING_EFFORT", "medium")
    OPENAI_TEMPERATURE: float = float(os.getenv("OPENAI_TEMPERATURE", "0.7"))
    OPENAI_MAX_TOKENS: int = int(os.getenv("OPENAI_MAX_TOKENS", "4096"))

    # Backend Configuration
    BACKEND_URL: str = os.getenv("BACKEND_URL", "http://localhost:8000")
    BACKEND_API_KEY: str = os.getenv("BACKEND_API_KEY", "")

    # Service Configuration
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8001"))
    TIMEOUT: int = int(os.getenv("TIMEOUT", "120"))
    MAX_CONTEXT_LENGTH: int = int(os.getenv("MAX_CONTEXT_LENGTH", "8000"))
    AI_SERVICE_API_KEY: str = os.getenv("AI_SERVICE_API_KEY", "")
    TOOL_APPROVAL_TOKEN: str = os.getenv("TOOL_APPROVAL_TOKEN", "")
    AGENT_WORKSPACE_DIR: str = os.getenv("AGENT_WORKSPACE_DIR", os.path.join(os.path.dirname(os.path.dirname(__file__)), "workspace"))
    AGENT_PROJECT_ROOT: str = os.getenv(
        "AGENT_PROJECT_ROOT",
        os.path.dirname(os.path.dirname(__file__)),
    )
    CURSOR_TERMINALS_DIR: str = os.getenv("CURSOR_TERMINALS_DIR", "")
    CURSOR_API_KEY: str = os.getenv("CURSOR_API_KEY", "")
    CURSOR_MODEL: str = os.getenv("CURSOR_MODEL", "composer-2.5")
    CURSOR_PROJECT_CWD: str = os.getenv("CURSOR_PROJECT_CWD", os.getenv("AGENT_PROJECT_ROOT", os.path.dirname(os.path.dirname(__file__))))
    CURSOR_PROMPT_TIMEOUT: int = int(os.getenv("CURSOR_PROMPT_TIMEOUT", "600"))
    ALLOWED_MEDIA_DIRS: str = os.getenv(
        "ALLOWED_MEDIA_DIRS",
        f"{os.path.expanduser('~/Documents')},{os.path.expanduser('~/Movies')},{os.path.expanduser('~/Downloads')}",
    )
    AGENT_MAX_TOOL_ROUNDS: int = int(os.getenv("AGENT_MAX_TOOL_ROUNDS", "10"))
    BROWSER_HEADLESS: bool = os.getenv("BROWSER_HEADLESS", "false").lower() == "true"
    BROWSER_CHANNEL: str = os.getenv("BROWSER_CHANNEL", "chrome")
    BROWSER_TIMEOUT: int = int(os.getenv("BROWSER_TIMEOUT", "30"))
    ALLOWED_TOOL_ACTIONS: str = os.getenv(
        "ALLOWED_TOOL_ACTIONS",
        "browser.navigate,browser.read,browser.type,browser.click,browser.search,"
        "file.read,file.write,terminal.exec,system.inspect,media.play,media.search,"
        "cursor.prompt,cursor.resume",
    )

    class Config:
        env_file = ".env"
        case_sensitive = True 


settings = Settings()
