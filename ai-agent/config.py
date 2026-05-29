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
    ALLOWED_TOOL_ACTIONS: str = os.getenv(
        "ALLOWED_TOOL_ACTIONS",
        "browser.navigate,browser.read,file.read,file.write,terminal.exec",
    )

    class Config:
        env_file = ".env"
        case_sensitive = True 


settings = Settings()
