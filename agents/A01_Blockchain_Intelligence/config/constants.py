"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    config.constants

Purpose:
    Central immutable constants used across the A01 agent.

Rules:
    - No secrets
    - No environment-specific values
    - No business logic
    - Safe to import anywhere
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final

# ==============================================================================
# PROJECT METADATA
# ==============================================================================

PROJECT_NAME: Final = "CIE-OS"

PROJECT_FULL_NAME: Final = "Crypto Intelligence Engine Operating System"

PROJECT_VERSION: Final = "1.0.0"

AGENT_ID: Final = "A01"

AGENT_NAME: Final = "Blockchain Intelligence Agent"

DEFAULT_ENCODING: Final = "utf-8"

# ==============================================================================
# SCOPE BOUNDARIES
# ==============================================================================

#: A01 analyses; it never acts on a market. No order is placed, no transaction
#: is signed, no key is held.
#:
#: This is stated as a constant rather than left to prose because the guarantee
#: was previously enforced only indirectly -- `tests/test_security.py` scans the
#: source for signing primitives and asserts the service and REST surface expose
#: no write operation. Those tests are the real defence and remain so; what they
#: could not do is give the boundary a name that code and `cli doctor` can cite.
#:
#: Deliberately not configurable, and deliberately not read from the
#: environment. A boundary that a deployment can switch off is a default, not a
#: boundary -- the same reasoning `decision.maturity` applies to ALERT_MATURITY.
NO_TRADE_EXECUTION: Final[bool] = True

# ==============================================================================
# ENVIRONMENTS
# ==============================================================================


class Environment(StrEnum):
    DEVELOPMENT = "development"
    TESTING = "testing"
    STAGING = "staging"
    PRODUCTION = "production"


# ==============================================================================
# BLOCKCHAINS
# ==============================================================================


class Chain(StrEnum):
    ETHEREUM = "ethereum"
    BNB = "bnb"
    POLYGON = "polygon"
    ARBITRUM = "arbitrum"
    OPTIMISM = "optimism"
    BASE = "base"
    AVALANCHE = "avalanche"

# Future

# SOLANA = "solana"
# BITCOIN = "bitcoin"

SUPPORTED_CHAINS: Final = (
    Chain.ETHEREUM,
    Chain.BNB,
    Chain.POLYGON,
    Chain.ARBITRUM,
    Chain.OPTIMISM,
    Chain.BASE,
    Chain.AVALANCHE,
)

# ==============================================================================
# AGENT STATES
# ==============================================================================


class AgentState(StrEnum):
    INITIALIZING = "initializing"
    STARTING = "starting"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"


# ==============================================================================
# HEALTH STATUS
# ==============================================================================


class HealthStatus(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


# ==============================================================================
# MEMORY
# ==============================================================================


class MemoryType(StrEnum):
    SHORT_TERM = "short_term"
    WORKING = "working"
    LONG_TERM = "long_term"


# ==============================================================================
# LOG LEVELS
# ==============================================================================


class LogLevel(StrEnum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


# ==============================================================================
# EVENTS
# ==============================================================================


class Event(StrEnum):
    BLOCK_RECEIVED = "block_received"
    BLOCK_PROCESSED = "block_processed"

    TRANSACTION_RECEIVED = "transaction_received"
    TRANSACTION_PROCESSED = "transaction_processed"

    CONTRACT_EVENT = "contract_event"

    AGENT_STARTED = "agent_started"
    AGENT_STOPPED = "agent_stopped"

    REPLAY_STARTED = "replay_started"
    REPLAY_FINISHED = "replay_finished"

    ALERT_CREATED = "alert_created"


# ==============================================================================
# DETECTION THRESHOLDS
# ==============================================================================

#: Percentile rank a transfer must meet to qualify as whale-scale. Shared by the
#: whale analyzer and the whale transfer skill so the skill's population size
#: requirement stays consistent with the threshold the detector will apply.
WHALE_PERCENTILE: Final[float] = 99.9

# ==============================================================================
# RUNTIME DEFAULTS
# ==============================================================================

DEFAULT_TIMEOUT_SECONDS: Final = 30

DEFAULT_RETRY_COUNT: Final = 3

DEFAULT_RETRY_DELAY: Final = 2

DEFAULT_BATCH_SIZE: Final = 100

DEFAULT_QUEUE_SIZE: Final = 1000

DEFAULT_MAX_WORKERS: Final = 4

DEFAULT_CONFIRMATIONS: Final = 12

# ==============================================================================
# CACHE
# ==============================================================================

CACHE_PREFIX_BLOCK: Final = "block"

CACHE_PREFIX_TX: Final = "tx"

CACHE_PREFIX_TOKEN: Final = "token"

CACHE_PREFIX_WALLET: Final = "wallet"

CACHE_PREFIX_CONTRACT: Final = "contract"

# ==============================================================================
# FILE NAMES
# ==============================================================================

ENV_FILE: Final = ".env"

DEV_ENV_FILE: Final = ".env.development"

TEST_ENV_FILE: Final = ".env.testing"

STAGING_ENV_FILE: Final = ".env.staging"

PRODUCTION_ENV_FILE: Final = ".env.production"

# ==============================================================================
# NETWORK
# ==============================================================================

HTTP_TIMEOUT: Final = 30

WEBSOCKET_TIMEOUT: Final = 60

MAX_RPC_FAILURES: Final = 5

# ==============================================================================
# EXPORTS
# ==============================================================================

__all__ = [
    "PROJECT_NAME",
    "PROJECT_FULL_NAME",
    "PROJECT_VERSION",
    "AGENT_ID",
    "AGENT_NAME",
    "DEFAULT_ENCODING",
    "NO_TRADE_EXECUTION",
    "WHALE_PERCENTILE",
    "Environment",
    "Chain",
    "SUPPORTED_CHAINS",
    "AgentState",
    "HealthStatus",
    "MemoryType",
    "LogLevel",
    "Event",
    "DEFAULT_TIMEOUT_SECONDS",
    "DEFAULT_RETRY_COUNT",
    "DEFAULT_RETRY_DELAY",
    "DEFAULT_BATCH_SIZE",
    "DEFAULT_QUEUE_SIZE",
    "DEFAULT_MAX_WORKERS",
    "DEFAULT_CONFIRMATIONS",
    "CACHE_PREFIX_BLOCK",
    "CACHE_PREFIX_TX",
    "CACHE_PREFIX_TOKEN",
    "CACHE_PREFIX_WALLET",
    "CACHE_PREFIX_CONTRACT",
    "ENV_FILE",
    "DEV_ENV_FILE",
    "TEST_ENV_FILE",
    "STAGING_ENV_FILE",
    "PRODUCTION_ENV_FILE",
    "HTTP_TIMEOUT",
    "WEBSOCKET_TIMEOUT",
    "MAX_RPC_FAILURES",
]