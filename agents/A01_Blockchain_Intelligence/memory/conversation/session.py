"""
Conversation Session

Session lifecycle and state for conversational memory: creation,
activation, expiration, and teardown. Thin facade over a
``ConversationMemory``-like source.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Callable

from memory.base.conversation import Conversation

DEFAULT_SESSION_TTL_HOURS = 24.0


@dataclass(slots=True)
class SessionState:
    """
    Runtime session bookkeeping.
    """

    session_id: str
    active: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    activated_at: datetime | None = None
    expires_at: datetime | None = None
    conversation_id: str | None = None

    @property
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return self.expires_at <= datetime.now(UTC)


class ConversationSession:
    """
    Manages conversation session lifecycle.

    Responsibilities:
        * Session creation and expiry
        * Active session tracking
        * Session metadata storage
    """

    def __init__(
        self,
        memory: Any,
        *,
        ttl_hours: float = DEFAULT_SESSION_TTL_HOURS,
    ) -> None:
        self._memory = memory
        self._ttl_hours = ttl_hours
        self._sessions: dict[str, SessionState] = {}

    @property
    def memory(self) -> Any:
        return self._memory

    @property
    def ttl_hours(self) -> float:
        return self._ttl_hours

    async def create(
        self,
        title: str,
        *,
        user_id: str = "anonymous",
        namespace: str | None = None,
        metadata: dict[str, Any] | None = None,
        session_id: str | None = None,
    ) -> Conversation:
        """
        Create a conversation and register a session for it.
        """
        create_conversation = getattr(self._memory, "create_conversation", None)
        if not callable(create_conversation):
            raise AttributeError("memory source must expose create_conversation()")
        result = create_conversation(
            title,
            user_id=user_id,
            namespace=namespace,
            metadata=metadata,
        )
        conversation = await result if hasattr(result, "__await__") else result
        sid = session_id or conversation.id
        self._sessions[sid] = SessionState(
            session_id=sid,
            active=False,
            conversation_id=conversation.id,
        )
        return conversation

    def activate(self, session_id: str) -> SessionState:
        """
        Mark a session active with a fresh TTL.
        """
        state = self._require(session_id)
        state.active = True
        state.activated_at = datetime.now(UTC)
        state.expires_at = datetime.now(UTC) + timedelta(hours=self._ttl_hours)
        return state

    def pause(self, session_id: str) -> SessionState:
        state = self._require(session_id)
        state.active = False
        return state

    def close(self, session_id: str) -> SessionState:
        state = self._require(session_id)
        state.active = False
        state.expires_at = datetime.now(UTC)
        return state

    async def expire(self, session_id: str) -> bool:
        """
        Expire a session and optionally delete its conversation.
        """
        state = self._sessions.get(session_id)
        if state is None:
            return False
        state.active = False
        state.expires_at = datetime.now(UTC)
        if state.conversation_id is not None:
            delete_conversation = getattr(self._memory, "delete_conversation", None)
            if callable(delete_conversation):
                result = delete_conversation(state.conversation_id)
                if hasattr(result, "__await__"):
                    await result
        del self._sessions[session_id]
        return True

    def get(self, session_id: str) -> SessionState | None:
        return self._sessions.get(session_id)

    def _require(self, session_id: str) -> SessionState:
        state = self._sessions.get(session_id)
        if state is None:
            raise KeyError(f"Unknown session '{session_id}'.")
        return state

    async def refresh(
        self,
        session_id: str,
        *,
        re_activate: bool = False,
    ) -> SessionState:
        """
        Refresh a session's TTL, re-activating it when requested.
        """
        state = self._require(session_id)
        if re_activate:
            return self.activate(session_id)
        if not state.active:
            return state
        state.expires_at = datetime.now(UTC) + timedelta(hours=self._ttl_hours)
        return state

    def active_sessions(self) -> list[SessionState]:
        return [state for state in self._sessions.values() if state.active]

    def expired_sessions(self) -> list[SessionState]:
        return [state for state in self._sessions.values() if state.is_expired]

    def snapshot(self) -> dict[str, Any]:
        return {
            "sessions": [
                {
                    "session_id": state.session_id,
                    "active": state.active,
                    "conversation_id": state.conversation_id,
                    "expires_at": (
                        state.expires_at.isoformat()
                        if state.expires_at is not None
                        else None
                    ),
                }
                for state in self._sessions.values()
            ],
            "count": len(self._sessions),
            "ttl_hours": self._ttl_hours,
        }
