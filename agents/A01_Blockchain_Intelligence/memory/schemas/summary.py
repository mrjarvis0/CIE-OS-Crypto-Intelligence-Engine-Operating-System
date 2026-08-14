"""
Summary Schema

Canonical data model and validation for generated summaries and
compression reports. Complements ``memory.base.summarizer`` and
``memory.summarization``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Mapping
from uuid import UUID, uuid4

from memory.schemas.memory import SchemaValidationError, _now


class SummaryType(str, Enum):
    """
    Canonical summary categories.
    """

    CONVERSATION = "conversation"
    TOPIC = "topic"
    SESSION = "session"
    KNOWLEDGE = "knowledge"
    GENERIC = "generic"


class SummaryStyle(str, Enum):
    """
    Canonical summary formats.
    """

    BULLET = "bullet"
    PARAGRAPH = "paragraph"
    CONCISE = "concise"
    DETAILED = "detailed"


class SummaryState(str, Enum):
    """
    Canonical summary lifecycle states.
    """

    DRAFT = "draft"
    FINAL = "final"
    SUPERSEDED = "superseded"


@dataclass(slots=True)
class SummarySchema:
    """
    Canonical summary data model.

    Fields:
        * Type, style, and content
        * Token accounting and provenance
    """

    summary_id: str
    content: str
    summary_type: SummaryType = SummaryType.GENERIC
    style: SummaryStyle = SummaryStyle.CONCISE
    state: SummaryState = SummaryState.FINAL
    source_keys: list[str] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    compression_ratio: float = 0.0
    created_at: datetime = field(default_factory=_now)
    summary_uuid: UUID = field(default_factory=uuid4)

    def validate(self) -> None:
        if not self.summary_id or not self.summary_id.strip():
            raise SchemaValidationError("summary_id must be non-empty.")
        if not self.content or not self.content.strip():
            raise SchemaValidationError("summary content must be non-empty.")
        if self.input_tokens < 0 or self.output_tokens < 0:
            raise SchemaValidationError("token counts must be non-negative.")
        if not 0.0 <= self.compression_ratio <= 1.0:
            raise SchemaValidationError("compression_ratio must be within [0, 1].")

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary_id": self.summary_id,
            "content": self.content,
            "summary_type": self.summary_type.value,
            "style": self.style.value,
            "state": self.state.value,
            "source_keys": list(self.source_keys),
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "compression_ratio": self.compression_ratio,
            "created_at": self.created_at.isoformat(),
            "summary_uuid": str(self.summary_uuid),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "SummarySchema":
        try:
            schema = cls(
                summary_id=str(payload["summary_id"]),
                content=str(payload["content"]),
                summary_type=SummaryType(str(payload.get("summary_type", SummaryType.GENERIC.value))),
                style=SummaryStyle(str(payload.get("style", SummaryStyle.CONCISE.value))),
                state=SummaryState(str(payload.get("state", SummaryState.FINAL.value))),
                source_keys=list(payload.get("source_keys", [])),
                input_tokens=int(payload.get("input_tokens", 0)),
                output_tokens=int(payload.get("output_tokens", 0)),
                compression_ratio=float(payload.get("compression_ratio", 0.0)),
                created_at=datetime.fromisoformat(payload.get("created_at", _now().isoformat())),
                summary_uuid=UUID(str(payload.get("summary_uuid", uuid4()))),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise SchemaValidationError(f"Invalid summary payload: {exc}") from exc
        schema.validate()
        return schema

    def __repr__(self) -> str:
        return f"SummarySchema(id={self.summary_id!r}, type={self.summary_type.value!r})"
