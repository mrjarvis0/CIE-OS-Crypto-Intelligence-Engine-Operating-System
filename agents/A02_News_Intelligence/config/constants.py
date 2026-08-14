"""
CIE-OS
A02 News Intelligence Agent

Module:
    config.constants

Purpose:
    Central constants for the A02 agent.

Design goals:
    - No business logic
    - No imports from other A02 modules
    - Safe to import everywhere
"""

from __future__ import annotations

from typing import Final

# ==============================================================================
# IDENTITY
# ==============================================================================

AGENT_ID: Final[str] = "A02"
AGENT_NAME: Final[str] = "News Intelligence Agent"
AGENT_VERSION: Final[str] = "0.1.0"

# ==============================================================================
# ENCODING / I/O
# ==============================================================================

DEFAULT_ENCODING: Final[str] = "utf-8"
DEFAULT_TIMEOUT_SECONDS: Final[float] = 30.0
DEFAULT_RETRY_COUNT: Final[int] = 3
DEFAULT_RETRY_DELAY: Final[float] = 1.0

# ==============================================================================
# INGESTION DEFAULTS
# ==============================================================================

DEFAULT_POLL_INTERVAL_SECONDS: Final[int] = 60
DEFAULT_MAX_ITEMS_PER_FETCH: Final[int] = 100
DEFAULT_NEWS_HISTORY_DAYS: Final[int] = 30

# ==============================================================================
# NARRATIVE / DETECTION DEFAULTS
# ==============================================================================

NARRATIVE_WINDOW_HOURS: Final[int] = 24
MIN_NARRATIVE_MENTIONS: Final[int] = 3
MIN_CLAIM_LENGTH: Final[int] = 20
MAX_CLAIM_LENGTH: Final[int] = 500

# ==============================================================================
# VERIFICATION DEFAULTS
# ==============================================================================

DEFAULT_VERDICT_CONFIDENCE: Final[float] = 0.0
MIN_CONFIRMATION_SOURCES: Final[int] = 2

# ==============================================================================
# MARKET DEFAULTS
# ==============================================================================

DEFAULT_IMPACT_HORIZONS_HOURS: Final[tuple[int, ...]] = (1, 6, 24)

# ==============================================================================
# SCORING RANGES
# ==============================================================================

FOMO_MIN: Final[int] = 0
FOMO_MAX: Final[int] = 100
COORDINATION_MIN: Final[int] = 0
COORDINATION_MAX: Final[int] = 100
CONFIDENCE_MIN: Final[float] = 0.0
CONFIDENCE_MAX: Final[float] = 1.0

# ==============================================================================
# ENUMS
# ==============================================================================


class NarrativeStatus:
    """Lifecycle of a rumor narrative (Phase 2)."""

    EMERGING = "emerging"
    SPREADING = "spreading"
    PEAK_HYPE = "peak_hype"
    VERIFYING = "verifying"
    RESOLVED = "resolved"
    FADING = "fading"


class Stance:
    """Stance of a single item toward its narrative."""

    SUPPORT = "support"
    DENY = "deny"
    NEUTRAL = "neutral"
    QUESTION = "question"


class EpistemicStatus:
    """Graded truth status of a claim (Phase 3)."""

    CONFIRMED_TRUE = "confirmed_true"
    LIKELY_TRUE = "likely_true"
    UNCONFIRMED = "unconfirmed"
    DISPUTED = "disputed"
    LIKELY_FALSE = "likely_false"
    CONFIRMED_FALSE = "confirmed_false"
    FABRICATED = "fabricated"


__all__ = [
    "AGENT_ID",
    "AGENT_NAME",
    "AGENT_VERSION",
    "DEFAULT_ENCODING",
    "DEFAULT_TIMEOUT_SECONDS",
    "DEFAULT_RETRY_COUNT",
    "DEFAULT_RETRY_DELAY",
    "DEFAULT_POLL_INTERVAL_SECONDS",
    "DEFAULT_MAX_ITEMS_PER_FETCH",
    "DEFAULT_NEWS_HISTORY_DAYS",
    "NARRATIVE_WINDOW_HOURS",
    "MIN_NARRATIVE_MENTIONS",
    "MIN_CLAIM_LENGTH",
    "MAX_CLAIM_LENGTH",
    "DEFAULT_VERDICT_CONFIDENCE",
    "MIN_CONFIRMATION_SOURCES",
    "DEFAULT_IMPACT_HORIZONS_HOURS",
    "FOMO_MIN",
    "FOMO_MAX",
    "COORDINATION_MIN",
    "COORDINATION_MAX",
    "CONFIDENCE_MIN",
    "CONFIDENCE_MAX",
    "NarrativeStatus",
    "Stance",
    "EpistemicStatus",
]
