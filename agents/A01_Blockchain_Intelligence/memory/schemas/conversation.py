"""
Conversation Schema

Canonical data model and validation for a full conversation, combining
session, message, topic, and entity records.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Mapping
from uuid import UUID, uuid4

from memory.schemas.memory import SchemaValidationError, _now
from memory.schemas.message import MessageSchema
from memory.schemas.session import SessionSchema


class ConversationState(str, Enum):
    """
    Canonical conversation lifecycle states.
    """

    OPEN = "open"
    ACTIVE = "active"
    PAUSED = "paused"
    CLOSED = "closed"


@dataclass(slots=True)
class ConversationSchema:
    """
    Canonical conversation data model.

    Fields:
        * Session and message collection
        * Topics, entities, and aggregate counts
        * Lifecycle state and timestamps
    """

    conversation_id: str
    title: str | None = None
    user_id: str = "anonymous"
    state: ConversationState = ConversationState.OPEN
    session: SessionSchema | None = None
    messages: list[MessageSchema] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)
    entities: list[dict[str, Any]] = field(default_factory=list)
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)
    conversation_uuid: UUID = field(default_factory=uuid4)

    @property
    def message_count(self) -> int:
        return len(self.messages)

    def validate(self) -> None:
        if not self.conversation_id or not self.conversation_id.strip():
            raise SchemaValidationError("conversation_id must be non-empty.")
        for message in self.messages:
            message.validate()
        if self.session is not None:
            self.session.validate()

    def to_dict(self) -> dict[str, Any]:
        return {
            "conversation_id": self.conversation_id,
            "title": self.title,
            "user_id": self.user_id,
            "state": self.state.value,
            "session": self.session.to_dict() if self.session is not None else None,
            "messages": [message.to_dict() for message in self.messages],
            "topics": list(self.topics),
            "entities": [dict(entity) for entity in self.entities],
            "message_count": self.message_count,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "conversation_uuid": str(self.conversation_uuid),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ConversationSchema":
        try:
            session_payload = payload.get("session")
            schema = cls(
                conversation_id=str(payload["conversation_id"]),
                title=payload.get("title"),
                user_id=str(payload.get("user_id", "anonymous")),
                state=ConversationState(str(payload.get("state", ConversationState.OPEN.value))),
                session=SessionSchema.from_dict(session_payload) if session_payload else None,
                messages=[
                    MessageSchema.from_dict(item)
                    for item in payload.get("messages", [])
                ],
                topics=list(payload.get("topics", [])),
                entities=[dict(item) for item in payload.get("entities", [])],
                created_at=datetime.fromisoformat(payload.get("created_at", _now().isoformat())),
                updated_at=datetime.fromisoformat(payload.get("updated_at", _now().isoformat())),
                conversation_uuid=UUID(str(payload.get("conversation_uuid", uuid4()))),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise SchemaValidationError(f"Invalid conversation payload: {exc}") from exc
        schema.validate()
        return schema

    def __repr__(self) -> str:
        return f"ConversationSchema(id={self.conversation_id!r}, messages={self.message_count!r})"
