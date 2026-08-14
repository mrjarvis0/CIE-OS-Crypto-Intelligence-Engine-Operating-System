"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.schemas.timeline

Purpose:
    Canonical timeline data models.

    A Timeline reconstructs chronological activity for a subject.
    EventArtifact is a single dated event; Milestone is a notable
    point within a timeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class EventSeverity(StrEnum):
    """
    Importance of a timeline event.
    """

    INFO = "info"
    NOTABLE = "notable"
    IMPORTANT = "important"
    CRITICAL = "critical"


@dataclass(frozen=True, slots=True)
class EventArtifact:
    """
    A single chronological event.
    """

    event_id: str
    occurred_at: datetime
    event_type: str = "activity"
    description: str = ""
    severity: EventSeverity | str = EventSeverity.INFO
    source_ref: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "occurred_at": self.occurred_at.isoformat(),
            "event_type": self.event_type,
            "description": self.description,
            "severity": str(self.severity),
            "source_ref": self.source_ref,
            "attributes": self.attributes,
        }


@dataclass(frozen=True, slots=True)
class Milestone:
    """
    A notable point in a timeline (e.g. wallet creation, deploy, exit).
    """

    label: str
    occurred_at: datetime
    description: str = ""
    attributes: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "occurred_at": self.occurred_at.isoformat(),
            "description": self.description,
            "attributes": self.attributes,
        }


@dataclass(frozen=True, slots=True)
class Timeline:
    """
    An ordered reconstruction of activity for a subject.
    """

    subject_id: str
    events: tuple[EventArtifact, ...] = ()
    milestones: tuple[Milestone, ...] = ()
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject_id": self.subject_id,
            "events": [e.to_dict() for e in self.events],
            "milestones": [m.to_dict() for m in self.milestones],
            "created_at": self.created_at.isoformat(),
            "metadata": self.metadata,
        }
