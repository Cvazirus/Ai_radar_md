from typing import Literal
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, model_validator

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
    DATABASE_URL: str = Field(default="postgresql://postgres:${POSTGRES_PASSWORD}@db:5432/${POSTGRES_DB}")
    
    # LLM Config
    LLM_PROVIDER: str = Field(default="openai_compatible")
    LLM_BASE_URL: str = Field(default="")
    LLM_API_KEY: str = Field(default="")
    LLM_MODEL: str = Field(default="")
    LLM_TIMEOUT_SECONDS: int = Field(default=90)
    LLM_CONNECT_TIMEOUT_SECONDS: int = Field(default=20)
    LLM_MAX_RETRIES: int = Field(default=2)
    LLM_TEMPERATURE: float = Field(default=0.1)
    LLM_MAX_INPUT_CHARS: int = Field(default=30000)
    LLM_MAX_OUTPUT_TOKENS: int = Field(default=2500)
    LLM_ANALYSIS_ENABLED: bool = Field(default=False)
    LLM_STORE_RAW_RESPONSE: bool = Field(default=True)
    LLM_PROMPT_VERSION: str = Field(default="phase5-v1")
    LLM_ANALYSIS_VERSION: str = Field(default="1.0")
    LLM_SCORE_VERSION: str = Field(default="1.0")

    # Telegram Config
    TELEGRAM_BOT_TOKEN: str = Field(default="mock-token")
    TELEGRAM_MODERATION_CHAT_ID: str = Field(default="-1001234567890")
    TELEGRAM_CHANNEL_ID: str = Field(default="-1009876543210")
    TELEGRAM_FEEDBACK_ENABLED: bool = Field(default=False)
    TELEGRAM_ALLOWED_USER_IDS: str = Field(default="")
    TELEGRAM_FEEDBACK_POLL_TIMEOUT_SECONDS: int = Field(default=20, ge=1, le=50)
    TELEGRAM_FEEDBACK_BATCH_LIMIT: int = Field(default=100, ge=1, le=100)
    TELEGRAM_FEEDBACK_CALLBACK_PREFIX: str = Field(default="feedback", min_length=1, max_length=32)

    # Moderation Config
    MODERATION_ENABLED: bool = Field(default=True)
    MODERATION_RULES_VERSION: str = Field(default="1.0")
    MODERATION_MAX_AGE_DAYS: int = Field(default=30)
    MODERATION_DIGEST_MIN_SCORE: float = Field(default=5.0)
    MODERATION_REVIEW_MIN_SCORE: float = Field(default=7.0)
    MODERATION_PRIORITY_MIN_SCORE: float = Field(default=8.5)
    MODERATION_MIN_CONFIDENCE: float = Field(default=0.60)
    MODERATION_PRIORITY_MIN_CONFIDENCE: float = Field(default=0.75)
    MODERATION_BATCH_LIMIT: int = Field(default=50)
    MODERATION_ALLOW_LEGACY_ANALYSIS: bool = Field(default=False)

    # Scheduler Config
    SCHEDULER_ENABLED: bool = Field(default=True)
    SCHEDULER_INTERVAL_MINUTES: int = Field(default=60)
    SCHEDULER_MAX_PARALLEL_RUNS: int = Field(default=1)
    SCHEDULER_LOCK_TIMEOUT: int = Field(default=1800)
    SCHEDULER_DEFAULT_LIMIT: int = Field(default=10)

    @model_validator(mode="after")
    def validate_llm_settings(self):
        if self.LLM_ANALYSIS_ENABLED:
            if not self.LLM_BASE_URL:
                raise ValueError("LLM_BASE_URL is required when LLM_ANALYSIS_ENABLED is True")
            if not self.LLM_API_KEY:
                raise ValueError("LLM_API_KEY is required when LLM_ANALYSIS_ENABLED is True")
            if not self.LLM_MODEL:
                raise ValueError("LLM_MODEL is required when LLM_ANALYSIS_ENABLED is True")
        return self

settings = Settings()
