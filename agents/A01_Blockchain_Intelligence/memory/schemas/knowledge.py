"""
Knowledge Schema

Canonical data model and validation for structured knowledge:
facts, preferences, decisions, tasks, and events. Complements the
extraction types in ``memory.base.summarizer``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Mapping
from uuid import UUID, uuid4

from memory.schemas.memory import SchemaValidationError, _now


class KnowledgeKind(str, Enum):
    """
    Canonical knowledge categories.
    """

    FACT = "fact"
    PREFERENCE = "preference"
    DECISION = "decision"
    TASK = "task"
    EVENT = "event"


class TaskState(str, Enum):
    """
    Canonical task lifecycle states.
    """

    OPEN = "open"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    CANCELLED = "cancelled"


@dataclass(slots=True)
class KnowledgeItemSchema:
    """
    Canonical structured knowledge record.

    Fields:
        * Kind, content, and subject
        * Confidence, tags, and provenance
    """

    kind: KnowledgeKind
    content: str
    subject: str | None = None
    confidence: float = 1.0
    tags: list[str] = field(default_factory=list)
    context: str | None = None
    created_at: datetime = field(default_factory=_now)
    item_uuid: UUID = field(default_factory=uuid4)

    def validate(self) -> None:
        if not self.content or not self.content.strip():
            raise SchemaValidationError("knowledge content must be non-empty.")
        if not 0.0 <= self.confidence <= 1.0:
            raise SchemaValidationError("confidence must be within [0, 1].")

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "content": self.content,
            "subject": self.subject,
            "confidence": self.confidence,
            "tags": list(self.tags),
            "context": self.context,
            "created_at": self.created_at.isoformat(),
            "item_uuid": str(self.item_uuid),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "KnowledgeItemSchema":
        try:
            schema = cls(
                kind=KnowledgeKind(str(payload["kind"])),
                content=str(payload["content"]),
                subject=payload.get("subject"),
                confidence=float(payload.get("confidence", 1.0)),
                tags=list(payload.get("tags", [])),
                context=payload.get("context"),
                created_at=datetime.fromisoformat(payload.get("created_at", _now().isoformat())),
                item_uuid=UUID(str(payload.get("item_uuid", uuid4()))),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise SchemaValidationError(f"Invalid knowledge payload: {exc}") from exc
        schema.validate()
        return schema

    def __repr__(self) -> str:
        return f"KnowledgeItemSchema(kind={self.kind.value!r})"


@dataclass(slots=True)
class DecisionSchema:
    """
    Canonical decision record.

    Fields:
        * Decision statement and rationale
        * Options and choice
        * Confidence and provenance
    """

    decision: str
    rationale: str | None = None
    options: list[str] = field(default_factory=list)
    chosen: str | None = None
    confidence: float = 1.0
    made_at: datetime = field(default_factory=_now)

    def validate(self) -> None:
        if not self.decision or not self.decision.strip():
            raise SchemaValidationError("decision must be non-empty.")
        if not 0.0 <= self.confidence <= 1.0:
            raise SchemaValidationError("confidence must be within [0, 1].")

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "rationale": self.rationale,
            "options": list(self.options),
            "chosen": self.chosen,
            "confidence": self.confidence,
            "made_at": self.made_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "DecisionSchema":
        try:
            schema = cls(
                decision=str(payload["decision"]),
                rationale=payload.get("rationale"),
                options=list(payload.get("options", [])),
                chosen=payload.get("chosen"),
                confidence=float(payload.get("confidence", 1.0)),
                made_at=datetime.fromisoformat(payload.get("made_at", _now().isoformat())),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise SchemaValidationError(f"Invalid decision payload: {exc}") from exc
        schema.validate()
        return schema


@dataclass(slots=True)
class TaskSchema:
    """
    Canonical task record.

    Fields:
        * Description, state, and priority
        * Due date and provenance
    """

    description: str
    state: TaskState = TaskState.OPEN
    priority: int = 5
    due_at: datetime | None = None
    tags: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=_now)

    def validate(self) -> None:
        if not self.description or not self.description.strip():
            raise SchemaValidationError("task description must be non-empty.")
        if self.priority < 0:
            raise SchemaValidationError("priority must be non-negative.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "description": self.description,
            "state": self.state.value,
            "priority": self.priority,
            "due_at": self.due_at.isoformat() if self.due_at is not None else None,
            "tags": list(self.tags),
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "TaskSchema":
        try:
            due = payload.get("due_at")
            schema = cls(
                description=str(payload["description"]),
                state=TaskState(str(payload.get("state", TaskState.OPEN.value))),
                priority=int(payload.get("priority", 5)),
                due_at=datetime.fromisoformat(due) if due else None,
                tags=list(payload.get("tags", [])),
                created_at=datetime.fromisoformat(payload.get("created_at", _now().isoformat())),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise SchemaValidationError(f"Invalid task payload: {exc}") from exc
        schema.validate()
        return schema


@dataclass(slots=True)
class EventSchema:
    """
    Canonical event record.

    Fields:
        * Event name and timestamp
        * Participants and context
    """

    name: str
    occurs_at: datetime
    participants: list[str] = field(default_factory=list)
    context: str | None = None
    tags: list[str] = field(default_factory=list)

    def validate(self) -> None:
        if not self.name or not self.name.strip():
            raise SchemaValidationError("event name must be non-empty.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "occurs_at": self.occurs_at.isoformat(),
            "participants": list(self.participants),
            "context": self.context,
            "tags": list(self.tags),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "EventSchema":
        try:
            schema = cls(
                name=str(payload["name"]),
                occurs_at=datetime.fromisoformat(payload["occurs_at"]),
                participants=list(payload.get("participants", [])),
                context=payload.get("context"),
                tags=list(payload.get("tags", [])),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise SchemaValidationError(f"Invalid event payload: {exc}") from exc
        schema.validate()
        return schema


@dataclass(slots=True)
class KnowledgeReportSchema:
    """
    Canonical aggregate knowledge report.

    Fields:
        * Item collection and counts
        * Generation timestamp
    """

    items: list[KnowledgeItemSchema] = field(default_factory=list)
    decisions: list[DecisionSchema] = field(default_factory=list)
    tasks: list[TaskSchema] = field(default_factory=list)
    events: list[EventSchema] = field(default_factory=list)
    generated_at: datetime = field(default_factory=_now)

    @property
    def item_count(self) -> int:
        return len(self.items) + len(self.decisions) + len(self.tasks) + len(self.events)

    def to_dict(self) -> dict[str, Any]:
        return {
            "items": [item.to_dict() for item in self.items],
            "decisions": [decision.to_dict() for decision in self.decisions],
            "tasks": [task.to_dict() for task in self.tasks],
            "events": [event.to_dict() for event in self.events],
            "item_count": self.item_count,
            "generated_at": self.generated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "KnowledgeReportSchema":
        try:
            schema = cls(
                items=[
                    KnowledgeItemSchema.from_dict(item)
                    for item in payload.get("items", [])
                ],
                decisions=[
                    DecisionSchema.from_dict(item)
                    for item in payload.get("decisions", [])
                ],
                tasks=[
                    TaskSchema.from_dict(item)
                    for item in payload.get("tasks", [])
                ],
                events=[
                    EventSchema.from_dict(item)
                    for item in payload.get("events", [])
                ],
                generated_at=datetime.fromisoformat(payload.get("generated_at", _now().isoformat())),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise SchemaValidationError(f"Invalid knowledge report payload: {exc}") from exc
        return schema
