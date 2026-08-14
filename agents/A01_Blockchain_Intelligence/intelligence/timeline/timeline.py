"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.timeline.timeline

Purpose:
    Timeline model operations.
"""

from __future__ import annotations

from ..schemas.timeline import EventArtifact, Timeline
from .chronology import Chronology


class TimelineService:
    """
    High-level operations over Timeline models.
    """

    def __init__(self, chronology: Chronology | None = None) -> None:
        self._chronology = chronology or Chronology()

    def sorted(self, timeline: Timeline) -> list[EventArtifact]:
        """
        Return events ordered chronologically.
        """
        return self._chronology.sort_events(list(timeline.events))

    def summarize(self, timeline: Timeline) -> dict:
        """
        Return a lightweight summary of a timeline.

        Earliest/latest are derived from the chronologically sorted
        events, so unsorted timelines still report correct bounds.
        """
        ordered = self.sorted(timeline)
        return {
            "subject_id": timeline.subject_id,
            "event_count": len(timeline.events),
            "milestone_count": len(timeline.milestones),
            "earliest": ordered[0].occurred_at.isoformat() if ordered else None,
            "latest": ordered[-1].occurred_at.isoformat() if ordered else None,
        }
