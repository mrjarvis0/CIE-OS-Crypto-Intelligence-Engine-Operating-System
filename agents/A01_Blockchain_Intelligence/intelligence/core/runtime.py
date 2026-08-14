"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.core.runtime

Purpose:
    Runtime facilities shared by the intelligence engine.

    Tracks the engine lifecycle (enforcing allowed state transitions),
    records per-stage timings, and exposes the active asyncio loop.
"""

from __future__ import annotations

import asyncio
import logging
import time

from typing import Any

from ..utils.helpers import now_utc
from .state import (
    EngineState,
    InvalidTransitionError,
    validate_transition,
)

logger = logging.getLogger("a01.intelligence.core")


class IntelligenceRuntime:
    """
    Timing, async loop access, and lifecycle state tracking.

    Responsibilities:
        * Enforce allowed engine state transitions
        * Record per-stage and total timings
        * Provide a best-effort running loop reference
    """

    def __init__(self) -> None:
        self._state = EngineState.IDLE
        self._started_at: float | None = None
        self._stage_timings: dict[str, float] = {}
        self._history: list[str] = []

    @property
    def state(self) -> EngineState:
        """Current engine state."""
        return self._state

    @property
    def history(self) -> list[str]:
        """Ordered list of states visited."""
        return list(self._history)

    def begin(self) -> None:
        """Mark the start of a run (resetting prior state)."""
        self.reset()
        self.transition(EngineState.INITIALIZING)
        self._started_at = time.monotonic()

    def reset(self) -> None:
        """Reset runtime state to IDLE, clearing timings and history."""
        self._state = EngineState.IDLE
        self._stage_timings = {}
        self._history = []
        self._started_at = None

    def transition(self, new_state: EngineState) -> None:
        """
        Transition to a new state, raising on invalid transitions.

        Raises
        ------
        InvalidTransitionError
            When the transition is not allowed from the current state.
        """
        if EngineState.is_terminal(self._state) and new_state != self._state:
            raise InvalidTransitionError(
                f"no transition out of terminal state {self._state.value}"
            )
        if not validate_transition(self._state, new_state):
            raise InvalidTransitionError(
                f"invalid engine transition: "
                f"{self._state.value} -> {new_state.value}"
            )
        self._state = new_state
        self._history.append(new_state.value)

    def time_stage(self, stage: str, elapsed: float) -> None:
        """Record a stage timing."""
        self._stage_timings[stage] = round(elapsed, 6)

    def finish(self) -> None:
        """Mark completion and record total time."""
        if self._started_at is not None:
            self._stage_timings["total"] = round(
                time.monotonic() - self._started_at, 6
            )
        try:
            self.transition(EngineState.COMPLETED)
        except InvalidTransitionError:
            logger.debug("run already terminal; skipping completion")
        logger.info("intelligence run completed in %.3fs", self.timings.get("total", 0.0))

    def fail(self, error: Exception | None = None) -> None:
        """Mark failure, capturing the error message."""
        if error is not None:
            logger.warning("intelligence run failed: %s", error)
        try:
            self.transition(EngineState.FAILED)
        except InvalidTransitionError:
            logger.debug("run already terminal; skipping failure")

    @property
    def timings(self) -> dict[str, float]:
        """Recorded stage timings."""
        return dict(self._stage_timings)

    @staticmethod
    def get_loop() -> asyncio.AbstractEventLoop:
        """
        Return the running event loop, creating one if necessary.

        Returns the ``asyncio`` running loop when available; otherwise
        returns a fresh event loop.
        """
        try:
            return asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.new_event_loop()

    def to_dict(self) -> dict[str, Any]:
        """Serialize runtime state."""
        return {
            "state": self._state.value,
            "history": self.history,
            "timings": self.timings,
            "started_at": now_utc().isoformat() if self._started_at is not None else None,
        }
