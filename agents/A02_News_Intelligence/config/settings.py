"""
CIE-OS
A02 News Intelligence Agent

Module:
    config.settings

Purpose:
    Central strongly-typed runtime settings for the A02 agent.

Design goals:
    - Pydantic v2 / pydantic-settings based
    - Env prefix A02_ (reads from repo-root .env)
    - Secret-safe (SecretStr for API keys)
    - No business logic
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from .constants import (
    AGENT_ID,
    AGENT_NAME,
    AGENT_VERSION,
    DEFAULT_MAX_ITEMS_PER_FETCH,
    DEFAULT_NEWS_HISTORY_DAYS,
    DEFAULT_POLL_INTERVAL_SECONDS,
    DEFAULT_TIMEOUT_SECONDS,
    MIN_CLAIM_LENGTH,
    MAX_CLAIM_LENGTH,
    MIN_NARRATIVE_MENTIONS,
    NARRATIVE_WINDOW_HOURS,
)
from .environment import Environment, get_environment
from .paths import DATABASE_FILE, ENV_FILE


class AgentSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="A02_AGENT_",
        case_sensitive=False,
        extra="ignore",
        env_file=ENV_FILE,
    )

    id: str = AGENT_ID
    name: str = AGENT_NAME
    version: str = AGENT_VERSION
    environment: Environment = Field(default_factory=get_environment)
    debug: bool = False


class IngestionSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="A02_INGESTION_",
        case_sensitive=False,
        extra="ignore",
        env_file=ENV_FILE,
    )

    poll_interval_seconds: int = DEFAULT_POLL_INTERVAL_SECONDS
    max_items_per_fetch: int = DEFAULT_MAX_ITEMS_PER_FETCH
    news_history_days: int = DEFAULT_NEWS_HISTORY_DAYS
    request_timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS


class NewsSourceSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="A02_NEWS_",
        case_sensitive=False,
        extra="ignore",
        env_file=ENV_FILE,
    )

    tiingo_api_key: SecretStr = SecretStr("")
    alpaca_api_key: SecretStr = SecretStr("")
    alpaca_secret_key: SecretStr = SecretStr("")
    finnhub_api_key: SecretStr = SecretStr("")
    newsapi_key: SecretStr = SecretStr("")
    financialjuice_api_key: SecretStr = SecretStr("")


class SocialSourceSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="A02_SOCIAL_",
        case_sensitive=False,
        extra="ignore",
        env_file=ENV_FILE,
    )

    reddit_client_id: SecretStr = SecretStr("")
    reddit_client_secret: SecretStr = SecretStr("")
    reddit_user_agent: str = "cie-os-a02/0.1"
    subreddits: str = "wallstreetbets,cryptocurrency,stocks"
    enable_x_stream: bool = False
    # Phase 6
    telegram_bot_token: SecretStr = SecretStr("")
    telegram_chat_ids: str = ""
    x_bearer_token: SecretStr = SecretStr("")
    x_search_query: str = "crypto OR bitcoin OR ethereum OR stock OR finance lang:en -is:retweet"


class MarketSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="A02_MARKET_",
        case_sensitive=False,
        extra="ignore",
        env_file=ENV_FILE,
    )

    alpha_vantage_api_key: SecretStr = SecretStr("")
    binance_base_url: str = "https://api.binance.com"
    enable_crypto: bool = True
    enable_stocks: bool = True
    enable_forex: bool = False


class NarrativeSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="A02_NARRATIVE_",
        case_sensitive=False,
        extra="ignore",
        env_file=ENV_FILE,
    )

    window_hours: int = NARRATIVE_WINDOW_HOURS
    min_mentions: int = MIN_NARRATIVE_MENTIONS
    min_claim_length: int = MIN_CLAIM_LENGTH
    max_claim_length: int = MAX_CLAIM_LENGTH


class ModelSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="A02_MODEL_",
        case_sensitive=False,
        extra="ignore",
        env_file=ENV_FILE,
    )

    fake_detector_model: str = "bert-base-uncased"
    fake_detector_threshold: float = 0.5
    impact_model_type: Literal["rules", "logistic", "gradient_boosting", "transformer"] = "rules"
    min_confidence: float = 0.6


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="A02_",
        case_sensitive=False,
        extra="ignore",
        env_file=ENV_FILE,
    )

    agent: AgentSettings = Field(default_factory=AgentSettings)
    ingestion: IngestionSettings = Field(default_factory=IngestionSettings)
    news: NewsSourceSettings = Field(default_factory=NewsSourceSettings)
    social: SocialSourceSettings = Field(default_factory=SocialSourceSettings)
    market: MarketSettings = Field(default_factory=MarketSettings)
    narrative: NarrativeSettings = Field(default_factory=NarrativeSettings)
    model: ModelSettings = Field(default_factory=ModelSettings)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached application settings singleton."""

    return Settings()


__all__ = [
    "AgentSettings",
    "IngestionSettings",
    "NewsSourceSettings",
    "SocialSourceSettings",
    "MarketSettings",
    "NarrativeSettings",
    "ModelSettings",
    "Settings",
    "get_settings",
]
