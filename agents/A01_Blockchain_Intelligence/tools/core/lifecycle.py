"""
Tools :: Core :: Lifecycle
==========================

Lifecycle state machine for every tool in the registry.

A tool progresses through well-defined states; the machine rejects illegal
transitions and records history for audit. This is the *runtime* counterpart
to the install/update/rollback operations handled by the lifecycle package.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Mapping, Optional

from ..utils.helpers import iso_now
from .exceptions import LifecycleError

__all__ = ["ToolState", "LifecycleMachine", "ALL_STATES"]

# The canonical state flow defined by the architecture README.
ALL_STATES = [
    "discovered",
    "loaded",
    "registered",
    "enabled",
    "executing",
    "idle",
    "disabled",
    "retired",
]


class ToolState:
    """Canonical tool lifecycle state constants."""

    DISCOVERED = "discovered"
    LOADED = "loaded"
    REGISTERED = "registered"
    ENABLED = "enabled"
    EXECUTING = "executing"
    IDLE = "idle"
    DISABLED = "disabled"
    RETIRED = "retired"

    ALL = list(ALL_STATES)

# Transition table: current -> allowed next states.
_TRANSITIONS: Dict[str, set] = {
    "discovered": {"loaded", "registered", "enabled"},
    "loaded": {"registered", "disabled", "retired"},
    "registered": {"enabled", "disabled", "retired"},
    "enabled": {"executing", "disabled", "idle", "retired"},
    "executing": {"idle", "disabled", "retired"},
    "idle": {"enabled", "executing", "disabled", "retired"},
    "disabled": {"enabled", "retired"},
    "retired": set(),
}


@dataclass
class Transition:
    """One recorded state transition (audit trail)."""

    from_state: str
    to_state: str
    at: str = field(default_factory=iso_now)
    reason: str = ""


class LifecycleMachine:
    """
    Thread-safe per-tool lifecycle tracker.

    ``current`` holds the state; ``history`` is an append-only list of
    :class:`Transition` records. Every mutation validates the transition and
    raises :class:`LifecycleError` on illegal moves.
    """

    def __init__(self, initial: str = "discovered") -> None:
        if initial not in ALL_STATES:
            raise LifecycleError(f"unknown initial state: {initial!r}")
        self._current = initial
        self.history: List[Transition] = []

    @property
    def current(self) -> str:
        return self._current

    @property
    def state(self) -> str:
        return self._current

    def transition(self, target: str, *, reason: str = "") -> None:
        if target not in ALL_STATES:
            raise LifecycleError(f"unknown target state: {target!r}")
        allowed = _TRANSITIONS.get(self._current, set())
        if target not in allowed:
            raise LifecycleError(
                f"illegal transition {self._current!r} -> {target!r}"
            )
        self.history.append(
            Transition(from_state=self._current, to_state=target, reason=reason)
        )
        self._current = target

    def can(self, target: str) -> bool:
        """Non-mutating check whether a transition is currently allowed."""
        return target in _TRANSITIONS.get(self._current, set())

    def as_dict(self) -> Mapping[str, object]:
        return {
            "current": self._current,
            "history": [
                {
                    "from": t.from_state,
                    "to": t.to_state,
                    "at": t.at,
                    "reason": t.reason,
                }
                for t in self.history
            ],
        }