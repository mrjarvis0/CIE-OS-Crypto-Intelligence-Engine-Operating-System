"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.core.manager

Purpose:
    Lifecycle and coordination manager for intelligence sessions.

    Creates, tracks, runs, and expires intelligence sessions while
    enforcing the configured maximum and cleaning up expired sessions.
    Runs reuse the session's own context so the session object reflects
    the investigation that actually executed.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from ..utils.constants import (
    DEFAULT_MAX_SESSIONS,
    DEFAULT_SESSION_TIMEOUT_SECONDS,
)
from ..utils.helpers import new_id, now_utc
from .configuration import IntelligenceConfig
from .context import IntelligenceContext
from .engine import IntelligenceEngine
from .session import IntelligenceSession

logger = logging.getLogger("a01.intelligence.core")


class IntelligenceManager:
    """
    Creates, tracks, and expires intelligence sessions.
    """

    def __init__(
        self,
        engine: IntelligenceEngine | None = None,
        config: IntelligenceConfig | None = None,
        max_sessions: int = DEFAULT_MAX_SESSIONS,
    ) -> None:
        self._config = config or IntelligenceConfig()
        self._engine = engine or IntelligenceEngine(self._config)
        self._max_sessions = max(1, max_sessions)
        self._sessions: dict[str, IntelligenceSession] = {}

    @property
    def engine(self) -> IntelligenceEngine:
        """The bound engine."""
        return self._engine

    def create_session(self, subject: dict) -> IntelligenceSession:
        """
        Create and register a new intelligence session.
        """
        context = self._engine.start(subject)
        session = IntelligenceSession(
            session_id=new_id("sess"),
            context=context,
            timeout_seconds=DEFAULT_SESSION_TIMEOUT_SECONDS,
        )
        self._sessions[session.session_id] = session
        self._prune()
        logger.info("created session %s", session.session_id)
        return session

    def get(self, session_id: str) -> IntelligenceSession | None:
        """Return a session by id."""
        return self._sessions.get(session_id)

    def run(self, session_id: str) -> IntelligenceSession | None:
        """
        Run the engine for a registered session.

        The session's own context is populated in place; expired
        sessions are marked cancelled and skipped.
        """
        session = self._sessions.get(session_id)
        if session is None:
            return None
        if session.expire():
            session.mark_expired()
            logger.info("session %s expired; skipped", session_id)
            return session

        package = self._engine.run(session.context.subject, context=session.context)
        session.result = package.to_dict()
        session.state = self._engine.runtime.state
        logger.info(
            "ran session %s evidence=%d",
            session_id,
            len(session.context.evidence),
        )
        return session

    async def arun(self, session_id: str) -> IntelligenceSession | None:
        """
        Async variant of :meth:`run` using the engine's async path.
        """
        session = self._sessions.get(session_id)
        if session is None:
            return None
        if session.expire():
            session.mark_expired()
            return session

        package = await self._engine.arun(session.context.subject, context=session.context)
        session.result = package.to_dict()
        session.state = self._engine.runtime.state
        return session

    def close_expired(self) -> int:
        """
        Mark all expired sessions as cancelled; return the count closed.
        """
        closed = 0
        for session in self._sessions.values():
            if session.expire() and session.is_active():
                session.mark_expired()
                closed += 1
        return closed

    def _prune(self) -> None:
        """Remove sessions over the configured maximum (oldest first)."""
        while len(self._sessions) > self._max_sessions:
            oldest_id = min(self._sessions, key=lambda k: self._sessions[k].created_at)
            del self._sessions[oldest_id]
            logger.debug("pruned session %s", oldest_id)

    @property
    def session_count(self) -> int:
        """Number of tracked sessions."""
        return len(self._sessions)
