"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.timeline.reconstruction

Purpose:
    Full chronological reconstruction for a subject.
"""

from __future__ import annotations

from typing import Any

from ..schemas.timeline import Timeline
from .chronology import Chronology
from .event_builder import EventBuilder
from .milestones import MilestoneDetector


class TimelineReconstructor:
    """
    Reconstructs a chronological Timeline from raw activity records.
    """

    def __init__(self) -> None:
        self._events = EventBuilder()
        self._chronology = Chronology()
        self._milestones = MilestoneDetector()

    def reconstruct(self, subject_id: str, records: list[dict[str, Any]]) -> Timeline:
        """
        Build an ordered Timeline with milestones from raw records.
        """
        events = [self._events.from_record(record) for record in records]
        ordered = self._chronology.sort_events(events)
        milestones = self._milestones.detect(ordered)
        return Timeline(
            subject_id=subject_id,
            events=tuple(ordered),
            milestones=tuple(milestones),
        )
