"""
Tools :: Lifecycle :: State
===========================

The lifecycle state machine: the source of truth for every tool's status.

A tool progresses through the canonical lifecycle chain. Every transition is
validated against the allowed-transition map, recorded into an immutable
history, and rejected when illegal. Failure states are tracked so observers
can distinguish a clean lifecycle from one that needs recovery.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Sequence

from ..utils.helpers import iso_now
from ..core.exceptions import LifecycleError

__all__ = ["LifecycleState", "StateRecord", "ALL_STATES", "State"]

# The canonical lifecycle chain.
ALL_STATES = [
    "discovered",
    "downloaded",
    "verified",
    "installed",
    "configured",
    "activated",
    "running",
    "paused",
    "updated",
    "migrated",
    "retired",
    "archived",
    "removed",
]

FAILED = "failed"


class State:
    """Canonical lifecycle state constants."""

    DISCOVERED = "discovered"
    DOWNLOADED = "downloaded"
    VERIFIED = "verified"
    INSTALLED = "installed"
    CONFIGURED = "configured"
    ACTIVATED = "activated"
    RUNNING = "running"
    PAUSED = "paused"
    UPDATED = "updated"
    MIGRATED = "migrated"
    RETIRED = "retired"
    ARCHIVED = "archived"
    REMOVED = "removed"
    FAILED = FAILED

    ALL = list(ALL_STATES)

# Allowed forward transitions. The machine only permits forward movement
# along the chain plus the recovery edges listed explicitly.
_TRANSITIONS: Dict[str, set] = {
    "discovered": {"downloaded", "verified", "installed", FAILED},
    "downloaded": {"verified", "installed", FAILED},
    "verified": {"installed", FAILED},
    "installed": {"configured", FAILED},
    "configured": {"activated", FAILED},
    "activated": {"running", "paused", "updated", "migrated", "retired", FAILED},
    "running": {"paused", "updated", "migrated", "retired", "activated", FAILED},
    "paused": {"running", "activated", "updated", "migrated", "retired", FAILED},
    "updated": {"running", "activated", "configured", "paused", "migrated", "retired", FAILED},
    "migrated": {"running", "activated", "configured", "retired", FAILED},
    "retired": {"archived", FAILED},
    "archived": {"removed", "retired"},
    "removed": set(),
    FAILED: set(),
}


@dataclass
class StateRecord:
    """One immutable entry in the transition history."""

    from_state: str
    to_state: str
    at: str = field(default_factory=iso_now)
    reason: str = ""
    operator: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "from": self.from_state,
            "to": self.to_state,
            "at": self.at,
            "reason": self.reason,
            "operator": self.operator,
        }


class LifecycleState:
    """
    Thread-safe state holder with validation and history.

    ``current`` is the active state; ``history`` is append-only. Transition
    checks are non-destructive; ``transition`` mutates only on success so a
    failed attempt leaves history untouched.
    """

    def __init__(self, initial: str = "discovered") -> None:
        initial = initial.lower()
        if initial not in ALL_STATES and initial != FAILED:
            raise LifecycleError(f"unknown initial state: {initial!r}")
        self._lock = threading.RLock()
        self._current = initial
        self._history: list["StateRecord"] = []

    @property
    def current(self) -> str:
        return self._current

    @property
    def state(self) -> str:
        return self._current

    def allows(self, target: str) -> bool:
        """Non-mutating check whether a transition is currently allowed."""
        target = target.lower()
        return target in _TRANSITIONS.get(self._current, set())

    def transition(self, target: str, *, reason: str = "", operator: str = "") -> "StateRecord":
        """Validate and apply a transition; raises :class:`LifecycleError`."""

        target = target.lower()
        if target == self._current:
            return StateRecord(self._current, target, reason=reason, operator=operator)
        if not self.allows(target):
            raise LifecycleError(
                f"illegal lifecycle transition {self._current!r} -> {target!r}"
            )
        if self._current == FAILED:
            raise LifecycleError("cannot transition out of the failed state")
        record = StateRecord(self._current, target, reason=reason, operator=operator)
        with self._lock:
            self._current = target
            self._history.append(record)
        return record

    def fail(self, *, reason: str = "", operator: str = "") -> "StateRecord":
        """Move into the terminal ``failed`` state and return the record."""
        if self._current == FAILED:
            raise LifecycleError("already failed")
        record = StateRecord(self._current, FAILED, reason=reason, operator=operator)
        with self._lock:
            self._current = FAILED
            self._history.append(record)
        return record

    def history(self) -> tuple["StateRecord", ...]:
        with self._lock:
            return tuple(self._history)

    @property
    def failed(self) -> bool:
        return self._current == FAILED

    def reset(self, target: str = "discovered") -> None:
        if target.lower() not in ALL_STATES:
            raise LifecycleError(f"unknown reset state {target!r}")
        with self._lock:
            self._current = target.lower()
            self._history.clear()

    def as_dict(self) -> Mapping[str, object]:
        return {
            "current": self._current,
            "history": [r.as_dict() for r in self.history()],
        }