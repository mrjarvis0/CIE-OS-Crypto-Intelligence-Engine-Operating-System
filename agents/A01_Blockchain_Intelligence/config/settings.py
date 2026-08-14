"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    config.settings

Purpose:
    Central strongly-typed runtime settings for the A01 agent.

Design goals:
    - Pydantic v2 / pydantic-settings based
    - Environment-aware
    - Nested settings models
    - Typed configuration
    - Secret-safe defaults
    - No business logic
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import AnyHttpUrl, Field, SecretStr, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .constants import (
    AGENT_ID,
    AGENT_NAME,
    DEFAULT_BATCH_SIZE,
    DEFAULT_CONFIRMATIONS,
    DEFAULT_ENCODING,
    DEFAULT_MAX_WORKERS,
    DEFAULT_QUEUE_SIZE,
    DEFAULT_RETRY_COUNT,
    DEFAULT_RETRY_DELAY,
    DEFAULT_TIMEOUT_SECONDS,
    Environment,
    LogLevel,
)
from .environment import get_environment
from .paths import (
    DEV_ENV_FILE,
    ENV_FILE,
    PROJECT_ROOT,
    PRODUCTION_ENV_FILE,
    STAGING_ENV_FILE,
    TEST_ENV_FILE,
)
from .security.validation import validate_env_prefix, validate_port, validate_positive_int, validate_url


class AgentSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="A01_AGENT_",
        case_sensitive=False,
        extra="ignore",
    )

    id: str = AGENT_ID
    name: str = AGENT_NAME
    version: str = "1.0.0"
    environment: Environment = Field(default_factory=get_environment)
    debug: bool = False
    max_workers: int = DEFAULT_MAX_WORKERS

    @field_validator("max_workers")
    @classmethod
    def _validate_max_workers(cls, value: int) -> int:
        return validate_positive_int(value, "max_workers", minimum=1, maximum=256)


class RpcEndpointSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="A01_RPC_",
        case_sensitive=False,
        extra="ignore",
    )

    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    retry_count: int = DEFAULT_RETRY_COUNT
    retry_delay_seconds: float = DEFAULT_RETRY_DELAY
    max_backoff_seconds: float = 30.0
    prefer_websocket: bool = False
    default_chain: str = "ethereum"

    @field_validator("timeout_seconds")
    @classmethod
    def _validate_timeout(cls, value: int) -> int:
        return validate_positive_int(value, "timeout_seconds", minimum=1, maximum=300)

    @field_validator("retry_count")
    @classmethod
    def _validate_retry_count(cls, value: int) -> int:
        return validate_positive_int(value, "retry_count", minimum=0, maximum=20)


class BlockchainSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="A01_CHAIN_",
        case_sensitive=False,
        extra="ignore",
    )

    confirmations: int = DEFAULT_CONFIRMATIONS
    supported_chains: tuple[str, ...] = (
        "ethereum",
        "bnb_chain",
        "polygon",
        "arbitrum",
        "optimism",
        "base",
        "avalanche",
        "solana",
        "bitcoin",
    )

    @field_validator("confirmations")
    @classmethod
    def _validate_confirmations(cls, value: int) -> int:
        return validate_positive_int(value, "confirmations", minimum=0, maximum=1000)


class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="A01_DB_",
        case_sensitive=False,
        extra="ignore",
    )

    url: str = "sqlite+aiosqlite:///./data/database/a01.db"
    echo: bool = False
    pool_size: int = 10

    @field_validator("url")
    @classmethod
    def _validate_url(cls, value: str) -> str:
        # sqlite is file-backed: "sqlite+aiosqlite:///./data/a01.db" has an
        # empty netloc, so only server-backed engines require one.
        file_backed = value.lower().startswith("sqlite")
        return validate_url(
            value,
            "database.url",
            allowed_schemes=(
                "sqlite",
                "sqlite+aiosqlite",
                "postgresql",
                "postgresql+asyncpg",
            ),
            require_netloc=not file_backed,
        )

    @field_validator("pool_size")
    @classmethod
    def _validate_pool_size(cls, value: int) -> int:
        return validate_positive_int(value, "pool_size", minimum=1, maximum=100)


class MemorySettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="A01_MEMORY_",
        case_sensitive=False,
        extra="ignore",
    )

    short_term_size: int = 50
    working_window: int = 20
    long_term_enabled: bool = True
    vector_enabled: bool = True
    summarization_enabled: bool = True

    @field_validator("short_term_size", "working_window")
    @classmethod
    def _validate_sizes(cls, value: int, info: Any) -> int:
        return validate_positive_int(value, info.field_name, minimum=1, maximum=10000)


class AISettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="A01_AI_",
        case_sensitive=False,
        extra="ignore",
    )

    provider: Literal["openai", "ollama", "local", "mock"] = "mock"
    model_name: str = "gpt-4.1-mini"
    temperature: float = 0.2
    max_tokens: int = 2048
    api_key: SecretStr | None = None

    @field_validator("temperature")
    @classmethod
    def _validate_temperature(cls, value: float) -> float:
        return float(value) if 0.0 <= float(value) <= 2.0 else (_ for _ in ()).throw(ValueError("temperature must be between 0 and 2"))

    @field_validator("max_tokens")
    @classmethod
    def _validate_max_tokens(cls, value: int) -> int:
        return validate_positive_int(value, "max_tokens", minimum=1, maximum=128000)


class LoggingSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="A01_LOG_",
        case_sensitive=False,
        extra="ignore",
    )

    level: LogLevel = LogLevel.INFO
    json_logs: bool = True
    enable_otel: bool = True
    log_dir: Path = Path("./runtime/logs")

    @field_validator("log_dir")
    @classmethod
    def _validate_log_dir(cls, value: Path) -> Path:
        return Path(value)


class CacheSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="A01_CACHE_",
        case_sensitive=False,
        extra="ignore",
    )

    enabled: bool = True
    max_size: int = 1024
    ttl_seconds: int = 300

    @field_validator("max_size")
    @classmethod
    def _validate_max_size(cls, value: int) -> int:
        return validate_positive_int(value, "max_size", minimum=1, maximum=1000000)

    @field_validator("ttl_seconds")
    @classmethod
    def _validate_ttl(cls, value: int) -> int:
        return validate_positive_int(value, "ttl_seconds", minimum=1, maximum=86400)


class SecuritySettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="A01_SEC_",
        case_sensitive=False,
        extra="ignore",
    )

    secret_dir: Path = Path("./secrets")
    env_prefix: str = "A01_SECRET_"
    enable_strict_secrets: bool = False

    @field_validator("env_prefix")
    @classmethod
    def _validate_prefix(cls, value: str) -> str:
        return validate_env_prefix(value)

    @field_validator("secret_dir")
    @classmethod
    def _validate_secret_dir(cls, value: Path) -> Path:
        return Path(value)


class AppSettings(BaseSettings):
    """
    Top-level application settings object.
    """

    model_config = SettingsConfigDict(
        env_prefix="A01_",
        env_file=None,
        case_sensitive=False,
        extra="ignore",
    )

    agent: AgentSettings = Field(default_factory=AgentSettings)
    rpc: RpcEndpointSettings = Field(default_factory=RpcEndpointSettings)
    blockchain: BlockchainSettings = Field(default_factory=BlockchainSettings)
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    memory: MemorySettings = Field(default_factory=MemorySettings)
    ai: AISettings = Field(default_factory=AISettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    cache: CacheSettings = Field(default_factory=CacheSettings)
    security: SecuritySettings = Field(default_factory=SecuritySettings)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type["AppSettings"],
        init_settings,
        env_settings,
        dotenv_settings,
        file_secret_settings,
    ):
        """
        Customize source priority.

        Order:
            init kwargs > env vars > dotenv > secret files
        """
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            file_secret_settings,
        )


def _resolve_env_file() -> Path | None:
    env = get_environment()
    if env.value == "development":
        return DEV_ENV_FILE if DEV_ENV_FILE.exists() else ENV_FILE
    if env.value == "testing":
        return TEST_ENV_FILE if TEST_ENV_FILE.exists() else ENV_FILE
    if env.value == "staging":
        return STAGING_ENV_FILE if STAGING_ENV_FILE.exists() else ENV_FILE
    if env.value == "production":
        return PRODUCTION_ENV_FILE if PRODUCTION_ENV_FILE.exists() else ENV_FILE
    return ENV_FILE if ENV_FILE.exists() else None


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    """
    Cached application settings singleton.
    """
    env_file = _resolve_env_file()

    try:
        if env_file is not None:
            return AppSettings(_env_file=env_file)
        return AppSettings()
    except ValidationError:
        raise


settings = get_settings()

__all__ = [
    "AgentSettings",
    "RpcEndpointSettings",
    "BlockchainSettings",
    "DatabaseSettings",
    "MemorySettings",
    "AISettings",
    "LoggingSettings",
    "CacheSettings",
    "SecuritySettings",
    "AppSettings",
    "get_settings",
    "settings",
]
