"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.core.session

Purpose:
    Per-investigation session container.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from ..utils.constants import DEFAULT_SESSION_TIMEOUT_SECONDS
from ..utils.helpers import now_utc
from .context import IntelligenceContext
from .state import EngineState


@dataclass(slots=True)
class IntelligenceSession:
    """
    A single investigation session bound to a context.

    Tracks lifecycle state, optional result, and supports timeout
    expiry for lifecycle cleanup.
    """

    session_id: str
    context: IntelligenceContext
    state: EngineState = EngineState.IDLE
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    timeout_seconds: float = DEFAULT_SESSION_TIMEOUT_SECONDS
    result: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def expire(self, now: datetime | None = None) -> bool:
        """
        Return True if the session has exceeded its timeout.
        """
        now = now or now_utc()
        elapsed = (now - self.created_at).total_seconds()
        return elapsed > self.timeout_seconds

    def mark_expired(self) -> None:
        """Set the session state to CANCELLED once expired."""
        if self.expire():
            self.state = EngineState.CANCELLED

    def is_active(self) -> bool:
        """Return True while the session has not reached a terminal state."""
        return not EngineState.is_terminal(self.state)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the session."""
        return {
            "session_id": self.session_id,
            "state": str(self.state),
            "created_at": self.created_at.isoformat(),
            "timeout_seconds": self.timeout_seconds,
            "expired": self.expire(),
            "result": self.result,
            "metadata": self.metadata,
            "context": self.context.to_dict(),
        }
