from typing import Literal
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # General
    PROJECT_NAME: str = "AI Radar"
    ENVIRONMENT: Literal["development", "production", "testing"] = "development"
    LOG_LEVEL: str = "INFO"
    TIMEZONE: str = "Europe/Moscow"

    # Database
    DATABASE_URL: str = Field(default="postgresql://postgres:postgres_pwd_123@db:5432/ai_radar_db")
    
    # LLM Config
    LLM_BASE_URL: str = Field(default="https://api.openai.com/v1")
    LLM_API_KEY: str = Field(default="mock-key")
    LLM_MODEL: str = Field(default="gpt-4o-mini")

    # Telegram Config
    TELEGRAM_BOT_TOKEN: str = Field(default="mock-token")
    TELEGRAM_MODERATION_CHAT_ID: str = Field(default="-1001234567890")
    TELEGRAM_CHANNEL_ID: str = Field(default="-1009876543210")

settings = Settings()
