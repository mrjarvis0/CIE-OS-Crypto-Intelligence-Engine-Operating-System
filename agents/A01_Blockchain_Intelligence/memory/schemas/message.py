"""
Message Schema

Canonical data model and validation for conversation messages.
Complements the runtime ``Message`` in ``memory.base.conversation``
without duplicating it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Mapping
from uuid import UUID, uuid4

from memory.schemas.memory import SchemaValidationError, _now

DEFAULT_USER_ID = "anonymous"


class MessageRole(str, Enum):
    """
    Canonical message roles.
    """

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"
    FUNCTION = "function"
    UNKNOWN = "unknown"


@dataclass(slots=True)
class MessageSchema:
    """
    Canonical message data model.

    Fields:
        * Role, content, and metadata
        * Session and ordering identifiers
        * Timestamps
    """

    role: MessageRole
    content: str
    session_id: str | None = None
    user_id: str = DEFAULT_USER_ID
    order: int = 0
    conversation_id: str | None = None
    message_id: UUID = field(default_factory=uuid4)
    tokens: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=_now)

    def validate(self) -> None:
        """
        Validate all fields, raising SchemaValidationError on failure.
        """
        if not self.content or not self.content.strip():
            raise SchemaValidationError("message content must be non-empty.")
        if self.order < 0:
            raise SchemaValidationError("order must be non-negative.")
        if self.tokens < 0:
            raise SchemaValidationError("tokens must be non-negative.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role.value,
            "content": self.content,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "order": self.order,
            "conversation_id": self.conversation_id,
            "message_id": str(self.message_id),
            "tokens": self.tokens,
            "metadata": dict(self.metadata),
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "MessageSchema":
        try:
            schema = cls(
                role=MessageRole(str(payload.get("role", MessageRole.UNKNOWN.value))),
                content=str(payload["content"]),
                session_id=payload.get("session_id"),
                user_id=str(payload.get("user_id", DEFAULT_USER_ID)),
                order=int(payload.get("order", 0)),
                conversation_id=payload.get("conversation_id"),
                message_id=UUID(str(payload.get("message_id", uuid4()))),
                tokens=int(payload.get("tokens", 0)),
                metadata=dict(payload.get("metadata", {})),
                created_at=datetime.fromisoformat(payload.get("created_at", _now().isoformat())),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise SchemaValidationError(f"Invalid message payload: {exc}") from exc
        schema.validate()
        return schema

    def __repr__(self) -> str:
        return f"MessageSchema(role={self.role.value!r}, order={self.order!r})"
