"""Application configuration using Pydantic Settings."""

from enum import Enum
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AIProvider(str, Enum):
    """Supported AI providers for summarization."""

    ANTHROPIC = "anthropic"
    OPENAI = "openai"


class DigestFrequency(str, Enum):
    """Supported digest delivery frequencies."""

    DAILY = "daily"
    WEEKLY = "weekly"
    TWICE_WEEKLY = "twice_weekly"
    MONTHLY = "monthly"


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_name: str = "AI News Digest"
    app_version: str = "0.1.0"
    debug: bool = False
    secret_key: str = Field(default="change-me-in-production")

    # Database
    database_url: str = Field(default="sqlite+aiosqlite:///./news_digest.db")

    # AI Providers
    ai_provider: AIProvider = Field(default=AIProvider.ANTHROPIC)
    anthropic_api_key: str = Field(default="")
    anthropic_model: str = Field(default="claude-sonnet-4-20250514")
    openai_api_key: str = Field(default="")
    openai_model: str = Field(default="gpt-4o")

    # News API
    newsapi_key: str = Field(default="")

    # Email (Resend)
    resend_api_key: str = Field(default="")
    email_from_address: str = Field(default="digest@yourdomain.com")
    email_from_name: str = Field(default="AI News Digest")

    # Gist-based article history (for cross-day dedup)
    github_token: str = Field(default="")
    gist_id: str = Field(default="")

    # Scheduling
    default_digest_hour: int = Field(default=8, ge=0, le=23)
    default_digest_minute: int = Field(default=0, ge=0, le=59)
    default_timezone: str = Field(default="UTC")

    # Limits
    max_topics_per_user: int = Field(default=5)
    max_articles_per_topic: int = Field(default=10)
    summary_max_length: int = Field(default=500)


@lru_cache
def get_settings() -> Settings:
    """Get cached application settings."""
    return Settings()
