"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.timeline.event_builder

Purpose:
    Build events from raw data.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from ..schemas.timeline import EventArtifact
from ..utils.helpers import new_id


def _parse_time(value: Any) -> datetime:
    """
    Coerce a datetime or ISO-8601 string into a tz-aware datetime.
    """
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"invalid occurred_at timestamp: {value!r}") from exc
    else:
        raise ValueError(f"invalid occurred_at timestamp: {value!r}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


class EventBuilder:
    """
    Constructs EventArtifact instances from raw records.
    """

    def build(
        self,
        occurred_at: datetime,
        event_type: str = "activity",
        description: str = "",
        severity: str = "info",
        source_ref: str | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> EventArtifact:
        """
        Build a single event artifact.
        """
        return EventArtifact(
            event_id=new_id("evt"),
            occurred_at=_parse_time(occurred_at),
            event_type=event_type,
            description=description,
            severity=severity,
            source_ref=source_ref,
            attributes=dict(attributes or {}),
        )

    def from_record(self, record: dict[str, Any]) -> EventArtifact:
        """
        Build an event from a raw dict record.

        ``occurred_at`` is required and may be a datetime or an
        ISO-8601 string; a missing key raises a clear ValueError.
        """
        if "occurred_at" not in record or record["occurred_at"] is None:
            raise ValueError("event record requires 'occurred_at'")
        return self.build(
            occurred_at=record["occurred_at"],
            event_type=record.get("event_type", "activity"),
            description=record.get("description", ""),
            severity=record.get("severity", "info"),
            source_ref=record.get("source_ref"),
            attributes=record.get("attributes"),
        )
