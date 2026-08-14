"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    planning.monitoring.timeline

Purpose:
    Chronological activity timeline for the planning subsystem.

Records plan and task lifecycle steps in order so progress can be
reconstructed and audited after the fact.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from planning.schemas.base import _now
from planning.utils.constants import TaskStatus

logger = logging.getLogger("a01.planning.monitoring")


@dataclass(slots=True)
class TimelineEntry:
    """
    A single timeline record.

    Fields:
        * Reference and status
        * Message and metadata
        * Occurrence timestamp
    """

    reference_id: str
    status: str
    message: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    occurred_at: datetime = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "reference_id": self.reference_id,
            "status": self.status,
            "message": self.message,
            "metadata": dict(self.metadata),
            "occurred_at": self.occurred_at.isoformat(),
        }


class Timeline:
    """
    Appends and queries chronological activity entries.

    Responsibilities:
        * Entry recording
        * Filtered queries
        * Reset
    """

    def __init__(
        self,
        *,
        limit: int = 10000,
    ) -> None:
        self._entries: list[TimelineEntry] = []
        self._limit = limit

    @property
    def entries(self) -> list[TimelineEntry]:
        """All recorded entries in chronological order."""
        return list(self._entries)

    def record(
        self,
        reference_id: str,
        status: str,
        *,
        message: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> TimelineEntry:
        """Record a new timeline entry."""
        entry = TimelineEntry(
            reference_id=reference_id,
            status=status,
            message=message,
            metadata=metadata or {},
        )
        self._entries.append(entry)

        if self._limit > 0:
            self._entries = self._entries[-self._limit:]

        return entry

    def for_plan(self, plan_id: str) -> list[TimelineEntry]:
        """Return all entries for a plan, oldest first."""
        return [
            entry
            for entry in self._entries
            if entry.reference_id == plan_id
        ]

    def for_status(self, status: str) -> list[TimelineEntry]:
        """Return all entries with a matching status."""
        return [
            entry
            for entry in self._entries
            if entry.status == status
        ]

    def task_events(self, task_id: str) -> list[TimelineEntry]:
        """Return all entries whose message mentions a task id."""
        return [
            entry
            for entry in self._entries
            if task_id in entry.message or task_id in entry.reference_id
        ]

    def succeeded_count(self, plan_id: str) -> int:
        """Count of SUCCEEDED status entries for a plan."""
        return sum(
            1
            for entry in self.for_plan(plan_id)
            if entry.status == TaskStatus.SUCCEEDED.value
        )

    def clear(self) -> None:
        """Clear all entries."""
        self._entries.clear()
