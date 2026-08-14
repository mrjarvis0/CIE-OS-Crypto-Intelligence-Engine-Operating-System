"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.utils.constants

Purpose:
    Central immutable constants for the intelligence layer.

Rules:
    - No secrets
    - No environment-specific values
    - No business logic
    - Safe to import anywhere
"""

from __future__ import annotations

from typing import Final

# ==============================================================================
# VERSION
# ==============================================================================

INTELLIGENCE_VERSION: Final[str] = "0.1.0"

SCHEMA_VERSION: Final[int] = 1

# ==============================================================================
# RUNTIME DEFAULTS
# ==============================================================================

DEFAULT_PIPELINE_TIMEOUT_SECONDS: Final[float] = 120.0

DEFAULT_MAX_EVIDENCE: Final[int] = 64

DEFAULT_CONFIDENCE_THRESHOLD: Final[float] = 0.6

DEFAULT_SESSION_TIMEOUT_SECONDS: Final[float] = 600.0

DEFAULT_MAX_SESSIONS: Final[int] = 100

DEFAULT_MAX_GRAPH_NODES: Final[int] = 10_000

DEFAULT_MAX_GRAPH_DEPTH: Final[int] = 64

DEFAULT_MAX_TIMELINE_EVENTS: Final[int] = 10_000

# ==============================================================================
# SCORE BANDS
# ==============================================================================

SCORE_CRITICAL_MIN: Final[float] = 80.0

SCORE_HIGH_MIN: Final[float] = 60.0

SCORE_MEDIUM_MIN: Final[float] = 40.0

SCORE_LOW_MIN: Final[float] = 20.0

# ==============================================================================
# PUBLIC EXPORTS
# ==============================================================================

__all__ = [
    "INTELLIGENCE_VERSION",
    "SCHEMA_VERSION",
    "DEFAULT_PIPELINE_TIMEOUT_SECONDS",
    "DEFAULT_MAX_EVIDENCE",
    "DEFAULT_CONFIDENCE_THRESHOLD",
    "DEFAULT_SESSION_TIMEOUT_SECONDS",
    "DEFAULT_MAX_SESSIONS",
    "DEFAULT_MAX_GRAPH_NODES",
    "DEFAULT_MAX_GRAPH_DEPTH",
    "DEFAULT_MAX_TIMELINE_EVENTS",
    "SCORE_CRITICAL_MIN",
    "SCORE_HIGH_MIN",
    "SCORE_MEDIUM_MIN",
    "SCORE_LOW_MIN",
]
