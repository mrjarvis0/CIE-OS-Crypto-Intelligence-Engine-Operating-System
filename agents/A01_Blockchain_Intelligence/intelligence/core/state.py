"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.core.state

Purpose:
    Lifecycle state machine for the intelligence engine.
"""

from __future__ import annotations

from enum import StrEnum


class EngineState(StrEnum):
    """
    Lifecycle state of an intelligence engine/session.

    Terminal states are COMPLETED, FAILED, and CANCELLED; no
    transition is allowed out of a terminal state.
    """

    IDLE = "idle"
    INITIALIZING = "initializing"
    COLLECTING = "collecting"
    ANALYZING = "analyzing"
    CORRELATING = "correlating"
    REASONING = "reasoning"
    VERIFYING = "verifying"
    SCORING = "scoring"
    REPORTING = "reporting"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @classmethod
    def is_terminal(cls, state: "EngineState") -> bool:
        """Return True for terminal states."""
        return state in (cls.COMPLETED, cls.FAILED, cls.CANCELLED)


class InvalidTransitionError(Exception):
    """
    Raised when an engine state transition is not allowed.
    """


# Allowed engine state transitions.
_TRANSITIONS: dict[EngineState, set[EngineState]] = {
    EngineState.IDLE: {
        EngineState.INITIALIZING,
        EngineState.CANCELLED,
        EngineState.FAILED,
    },
    EngineState.INITIALIZING: {
        EngineState.COLLECTING,
        EngineState.CANCELLED,
        EngineState.FAILED,
    },
    EngineState.COLLECTING: {
        EngineState.COMPLETED,
        EngineState.ANALYZING,
        EngineState.CORRELATING,
        EngineState.CANCELLED,
        EngineState.FAILED,
    },
    EngineState.ANALYZING: {
        EngineState.COMPLETED,
        EngineState.CORRELATING,
        EngineState.REASONING,
        EngineState.CANCELLED,
        EngineState.FAILED,
    },
    EngineState.CORRELATING: {
        EngineState.COMPLETED,
        EngineState.REASONING,
        EngineState.CANCELLED,
        EngineState.FAILED,
    },
    EngineState.REASONING: {
        EngineState.COMPLETED,
        EngineState.VERIFYING,
        EngineState.CANCELLED,
        EngineState.FAILED,
    },
    EngineState.VERIFYING: {
        EngineState.COMPLETED,
        EngineState.SCORING,
        EngineState.CANCELLED,
        EngineState.FAILED,
    },
    EngineState.SCORING: {
        EngineState.COMPLETED,
        EngineState.REPORTING,
        EngineState.CANCELLED,
        EngineState.FAILED,
    },
    EngineState.REPORTING: {
        EngineState.COMPLETED,
        EngineState.CANCELLED,
        EngineState.FAILED,
    },
    EngineState.COMPLETED: set(),
    EngineState.FAILED: set(),
    EngineState.CANCELLED: set(),
}


def validate_transition(current: EngineState, target: EngineState) -> bool:
    """
    Return True if moving from ``current`` to ``target`` is allowed.

    The self-transition is always permitted.
    """
    if current == target:
        return True
    return target in _TRANSITIONS.get(current, set())
