"""
Session Schema

Canonical data model and validation for conversation sessions.
Complements session concepts in ``memory.base.conversation``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Mapping
from uuid import UUID, uuid4

from memory.schemas.memory import SchemaValidationError, _now

DEFAULT_NAMESPACE = "default"


class SessionState(str, Enum):
    """
    Canonical session lifecycle states.
    """

    OPEN = "open"
    ACTIVE = "active"
    PAUSED = "paused"
    CLOSED = "closed"
    EXPIRED = "expired"


@dataclass(slots=True)
class SessionSchema:
    """
    Canonical conversation session data model.

    Fields:
        * Session identifiers and metadata
        * Activation and expiry times
        * Owner and namespace
    """

    session_id: str
    owner: str
    namespace: str = DEFAULT_NAMESPACE
    title: str | None = None
    state: SessionState = SessionState.OPEN
    message_count: int = 0
    activated_at: datetime = field(default_factory=_now)
    expires_at: datetime | None = None
    closed_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    session_uuid: UUID = field(default_factory=uuid4)

    def validate(self) -> None:
        """
        Validate all fields, raising SchemaValidationError on failure.
        """
        if not self.session_id or not self.session_id.strip():
            raise SchemaValidationError("session_id must be non-empty.")
        if not self.owner or not self.owner.strip():
            raise SchemaValidationError("owner must be non-empty.")
        if self.message_count < 0:
            raise SchemaValidationError("message_count must be non-negative.")
        if self.expires_at is not None and self.expires_at < self.activated_at:
            raise SchemaValidationError("expires_at cannot precede activated_at.")
        if self.closed_at is not None and self.closed_at < self.activated_at:
            raise SchemaValidationError("closed_at cannot precede activated_at.")

    def is_expired(self, *, reference: datetime | None = None) -> bool:
        if self.expires_at is None:
            return False
        return self.expires_at <= (reference or _now())

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "owner": self.owner,
            "namespace": self.namespace,
            "title": self.title,
            "state": self.state.value,
            "message_count": self.message_count,
            "activated_at": self.activated_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at is not None else None,
            "closed_at": self.closed_at.isoformat() if self.closed_at is not None else None,
            "metadata": dict(self.metadata),
            "session_uuid": str(self.session_uuid),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "SessionSchema":
        try:
            expires = payload.get("expires_at")
            closed = payload.get("closed_at")
            schema = cls(
                session_id=str(payload["session_id"]),
                owner=str(payload["owner"]),
                namespace=str(payload.get("namespace", DEFAULT_NAMESPACE)),
                title=payload.get("title"),
                state=SessionState(str(payload.get("state", SessionState.OPEN.value))),
                message_count=int(payload.get("message_count", 0)),
                activated_at=datetime.fromisoformat(payload.get("activated_at", _now().isoformat())),
                expires_at=datetime.fromisoformat(expires) if expires else None,
                closed_at=datetime.fromisoformat(closed) if closed else None,
                metadata=dict(payload.get("metadata", {})),
                session_uuid=UUID(str(payload.get("session_uuid", uuid4()))),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise SchemaValidationError(f"Invalid session payload: {exc}") from exc
        schema.validate()
        return schema

    def __repr__(self) -> str:
        return f"SessionSchema(id={self.session_id!r}, state={self.state.value!r})"
