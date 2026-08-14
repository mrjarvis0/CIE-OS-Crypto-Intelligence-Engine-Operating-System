"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    core.lifecycle

Purpose:
    Agent lifecycle finite state machine foundation.

Part 1 contains:

- Lifecycle states
- Transition matrix
- Lifecycle models
- History manager

Runtime transition engine is implemented in Part 2.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final

# =============================================================================
# Helpers
# =============================================================================


def utc_now() -> datetime:
    """Return current UTC time."""
    return datetime.now(UTC)


# =============================================================================
# Lifecycle States
# =============================================================================


class LifecycleState(StrEnum):
    """
    Valid agent lifecycle states.
    """

    CREATED = "created"

    INITIALIZING = "initializing"

    READY = "ready"

    RUNNING = "running"

    PAUSED = "paused"

    RESUMING = "resuming"

    STOPPING = "stopping"

    STOPPED = "stopped"

    FAILED = "failed"

    SHUTDOWN = "shutdown"


# =============================================================================
# Allowed Transitions
# =============================================================================

ALLOWED_TRANSITIONS: Final[
    dict[LifecycleState, set[LifecycleState]]
] = {

    # SHUTDOWN is reachable from CREATED/INITIALIZING so that an agent which
    # never reached READY can still be disposed of without a bogus detour
    # through RUNNING or FAILED.
    LifecycleState.CREATED: {
        LifecycleState.INITIALIZING,
        LifecycleState.SHUTDOWN,
    },

    LifecycleState.INITIALIZING: {
        LifecycleState.READY,
        LifecycleState.FAILED,
        LifecycleState.SHUTDOWN,
    },

    LifecycleState.READY: {
        LifecycleState.RUNNING,
        LifecycleState.SHUTDOWN,
    },

    LifecycleState.RUNNING: {
        LifecycleState.PAUSED,
        LifecycleState.STOPPING,
        LifecycleState.FAILED,
    },

    LifecycleState.PAUSED: {
        LifecycleState.RESUMING,
        LifecycleState.STOPPING,
    },

    LifecycleState.RESUMING: {
        LifecycleState.RUNNING,
        LifecycleState.FAILED,
    },

    LifecycleState.STOPPING: {
        LifecycleState.STOPPED,
    },

    LifecycleState.STOPPED: {
        LifecycleState.SHUTDOWN,
    },

    LifecycleState.FAILED: {
        LifecycleState.SHUTDOWN,
    },

    LifecycleState.SHUTDOWN: set(),
}


# =============================================================================
# Transition Model
# =============================================================================


@dataclass(slots=True)
class LifecycleTransition:
    """
    Represents one state transition.
    """

    from_state: LifecycleState

    to_state: LifecycleState

    timestamp: datetime = field(default_factory=utc_now)

    actor: str = "system"

    reason: str = ""

    success: bool = True


# =============================================================================
# Lifecycle Event
# =============================================================================


@dataclass(slots=True)
class LifecycleEvent:
    """
    Lifecycle event emitted after transitions.
    """

    state: LifecycleState

    previous_state: LifecycleState | None

    transition: LifecycleTransition

    emitted_at: datetime = field(default_factory=utc_now)


# =============================================================================
# Transition History
# =============================================================================


@dataclass(slots=True)
class LifecycleHistory:
    """
    Stores all lifecycle transitions.
    """

    transitions: list[LifecycleTransition] = field(
        default_factory=list
    )

    def append(
        self,
        transition: LifecycleTransition,
    ) -> None:
        """
        Store transition.
        """
        self.transitions.append(transition)

    def latest(
        self,
    ) -> LifecycleTransition | None:
        """
        Return latest transition.
        """
        if not self.transitions:
            return None

        return self.transitions[-1]

    def clear(self) -> None:
        """
        Remove all history.
        """
        self.transitions.clear()

    @property
    def count(self) -> int:
        """
        Number of stored transitions.
        """
        return len(self.transitions)


# =============================================================================
# Validation Helpers
# =============================================================================


def is_transition_allowed(
    current: LifecycleState,
    target: LifecycleState,
) -> bool:
    """
    Check whether a transition is valid.
    """

    return target in ALLOWED_TRANSITIONS[current]


def available_transitions(
    state: LifecycleState,
) -> set[LifecycleState]:
    """
    Return allowed next states.
    """

    return ALLOWED_TRANSITIONS[state]


# =============================================================================
# Part 2 Imports
# =============================================================================

import asyncio
import logging

from collections.abc import Awaitable, Callable

from .exceptions import LifecycleError

logger = logging.getLogger(__name__)

TransitionListener = Callable[[LifecycleEvent], None | Awaitable[None]]


# =============================================================================
# Transition Engine
# =============================================================================


class AgentLifecycle:
    """
    Runtime finite state machine driving an agent through its lifecycle.

    Every transition is validated against :data:`ALLOWED_TRANSITIONS`, recorded
    in :class:`LifecycleHistory`, and published to registered listeners.

    Concurrency
    -----------
    All public transition methods serialize on an internal ``asyncio.Lock``, so
    concurrent ``start``/``stop`` calls cannot interleave and corrupt the state.
    The private ``_transition`` helper assumes the lock is already held.

    Idempotency
    -----------
    ``stop`` and ``shutdown`` are safe to call repeatedly and from any state;
    they no-op when there is nothing left to do. This matters because
    ``AgentRuntime.shutdown`` calls ``stop`` before ``shutdown``.
    """

    def __init__(
        self,
        *,
        initial_state: LifecycleState = LifecycleState.CREATED,
    ) -> None:

        self._state: LifecycleState = initial_state

        self._previous_state: LifecycleState | None = None

        self.history = LifecycleHistory()

        self._listeners: list[TransitionListener] = []

        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def state(self) -> LifecycleState:
        """Current lifecycle state."""
        return self._state

    @property
    def previous_state(self) -> LifecycleState | None:
        """State occupied before the last successful transition."""
        return self._previous_state

    @property
    def is_running(self) -> bool:
        """True when the agent is actively running."""
        return self._state is LifecycleState.RUNNING

    @property
    def is_terminal(self) -> bool:
        """True when no further transition is possible."""
        return self._state is LifecycleState.SHUTDOWN

    def can_transition_to(self, target: LifecycleState) -> bool:
        """Check whether ``target`` is reachable in one step."""
        return is_transition_allowed(self._state, target)

    def available(self) -> set[LifecycleState]:
        """States reachable from the current one in a single step."""
        return available_transitions(self._state)

    # ------------------------------------------------------------------
    # Listeners
    # ------------------------------------------------------------------

    def add_listener(self, listener: TransitionListener) -> None:
        """Register a callback invoked after each successful transition."""
        self._listeners.append(listener)

    def remove_listener(self, listener: TransitionListener) -> None:
        """Unregister a previously added callback. Unknown ones are ignored."""
        if listener in self._listeners:
            self._listeners.remove(listener)

    async def _emit(self, event: LifecycleEvent) -> None:
        """
        Notify listeners.

        A misbehaving listener must never break the state machine, so
        exceptions are logged and swallowed.
        """
        for listener in list(self._listeners):
            try:
                result = listener(event)

                if asyncio.iscoroutine(result):
                    await result

            except Exception:
                logger.exception(
                    "Lifecycle listener failed for transition %s -> %s",
                    event.previous_state,
                    event.state,
                )

    # ------------------------------------------------------------------
    # Core transition
    # ------------------------------------------------------------------

    async def _transition(
        self,
        target: LifecycleState,
        *,
        actor: str = "system",
        reason: str = "",
    ) -> LifecycleTransition:
        """
        Perform one validated transition. Caller must hold ``self._lock``.

        Raises
        ------
        LifecycleError
            When the transition is not permitted by the matrix.
        """

        current = self._state

        if not is_transition_allowed(current, target):
            failed = LifecycleTransition(
                from_state=current,
                to_state=target,
                actor=actor,
                reason=reason,
                success=False,
            )
            self.history.append(failed)

            raise LifecycleError(
                f"Illegal lifecycle transition {current.value} -> {target.value}",
                current=current.value,
                target=target.value,
            )

        transition = LifecycleTransition(
            from_state=current,
            to_state=target,
            actor=actor,
            reason=reason,
            success=True,
        )

        self._previous_state = current
        self._state = target
        self.history.append(transition)

        logger.debug(
            "Lifecycle transition %s -> %s (actor=%s)",
            current.value,
            target.value,
            actor,
        )

        await self._emit(
            LifecycleEvent(
                state=target,
                previous_state=current,
                transition=transition,
            )
        )

        return transition

    # ------------------------------------------------------------------
    # Startup
    # ------------------------------------------------------------------

    async def initialize(
        self,
        *,
        actor: str = "system",
        reason: str = "",
    ) -> None:
        """CREATED -> INITIALIZING. No-op if already past initialization."""

        async with self._lock:
            if self._state is not LifecycleState.CREATED:
                return

            await self._transition(
                LifecycleState.INITIALIZING,
                actor=actor,
                reason=reason,
            )

    async def ready(
        self,
        *,
        actor: str = "system",
        reason: str = "",
    ) -> None:
        """INITIALIZING -> READY. No-op if already READY."""

        async with self._lock:
            if self._state is LifecycleState.READY:
                return

            await self._transition(
                LifecycleState.READY,
                actor=actor,
                reason=reason,
            )

    async def start(
        self,
        *,
        actor: str = "system",
        reason: str = "",
    ) -> None:
        """READY -> RUNNING. No-op if already RUNNING."""

        async with self._lock:
            if self._state is LifecycleState.RUNNING:
                return

            await self._transition(
                LifecycleState.RUNNING,
                actor=actor,
                reason=reason,
            )

    # ------------------------------------------------------------------
    # Pause / Resume
    # ------------------------------------------------------------------

    async def pause(
        self,
        *,
        actor: str = "system",
        reason: str = "",
    ) -> None:
        """RUNNING -> PAUSED. No-op if already PAUSED."""

        async with self._lock:
            if self._state is LifecycleState.PAUSED:
                return

            await self._transition(
                LifecycleState.PAUSED,
                actor=actor,
                reason=reason,
            )

    async def resume(
        self,
        *,
        actor: str = "system",
        reason: str = "",
    ) -> None:
        """PAUSED -> RESUMING -> RUNNING. No-op if already RUNNING."""

        async with self._lock:
            if self._state is LifecycleState.RUNNING:
                return

            await self._transition(
                LifecycleState.RESUMING,
                actor=actor,
                reason=reason,
            )

            await self._transition(
                LifecycleState.RUNNING,
                actor=actor,
                reason=reason,
            )

    # ------------------------------------------------------------------
    # Failure
    # ------------------------------------------------------------------

    async def fail(
        self,
        reason: str,
        *,
        actor: str = "system",
    ) -> None:
        """Move to FAILED. No-op if already FAILED or SHUTDOWN."""

        async with self._lock:
            if self._state in {
                LifecycleState.FAILED,
                LifecycleState.SHUTDOWN,
            }:
                return

            await self._transition(
                LifecycleState.FAILED,
                actor=actor,
                reason=reason,
            )

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    #: States from which a running agent can be wound down.
    _STOPPABLE = frozenset(
        {
            LifecycleState.RUNNING,
            LifecycleState.PAUSED,
            LifecycleState.RESUMING,
        }
    )

    async def stop(
        self,
        *,
        actor: str = "system",
        reason: str = "",
    ) -> None:
        """
        Wind the agent down to STOPPED.

        RUNNING/PAUSED -> STOPPING -> STOPPED. When the agent was never
        started there is nothing to stop, so this is a no-op rather than an
        error; ``AgentRuntime.shutdown`` relies on that.
        """

        async with self._lock:
            if self._state is LifecycleState.STOPPING:
                await self._transition(
                    LifecycleState.STOPPED,
                    actor=actor,
                    reason=reason,
                )
                return

            if self._state not in self._STOPPABLE:
                return

            if self._state is LifecycleState.RESUMING:
                await self._transition(
                    LifecycleState.RUNNING,
                    actor=actor,
                    reason=reason,
                )

            await self._transition(
                LifecycleState.STOPPING,
                actor=actor,
                reason=reason,
            )

            await self._transition(
                LifecycleState.STOPPED,
                actor=actor,
                reason=reason,
            )

    async def shutdown(
        self,
        *,
        actor: str = "system",
        reason: str = "",
    ) -> None:
        """
        Drive the agent to the terminal SHUTDOWN state from any state.

        Idempotent: calling it on an already shut-down agent does nothing.
        """

        if self._state is LifecycleState.SHUTDOWN:
            return

        # stop() takes the lock itself, so it must be called outside it.
        if (
            self._state in self._STOPPABLE
            or self._state is LifecycleState.STOPPING
        ):
            await self.stop(actor=actor, reason=reason)

        async with self._lock:
            if self._state is LifecycleState.SHUTDOWN:
                return

            await self._transition(
                LifecycleState.SHUTDOWN,
                actor=actor,
                reason=reason,
            )

    # ------------------------------------------------------------------
    # Reset
    # ------------------------------------------------------------------

    async def reset(self) -> None:
        """Return to CREATED and clear history. Intended for tests."""

        async with self._lock:
            self._state = LifecycleState.CREATED
            self._previous_state = None
            self.history.clear()

    def snapshot(self) -> dict[str, object]:
        """Serializable view of the current lifecycle state."""

        latest = self.history.latest()

        return {
            "state": self._state.value,
            "previous_state": (
                self._previous_state.value
                if self._previous_state is not None
                else None
            ),
            "transition_count": self.history.count,
            "last_transition_at": (
                latest.timestamp.isoformat() if latest is not None else None
            ),
        }

    def __repr__(self) -> str:
        return f"AgentLifecycle(state={self._state.value!r})"


__all__ = [
    "ALLOWED_TRANSITIONS",
    "AgentLifecycle",
    "LifecycleEvent",
    "LifecycleHistory",
    "LifecycleState",
    "LifecycleTransition",
    "TransitionListener",
    "available_transitions",
    "is_transition_allowed",
    "utc_now",
]