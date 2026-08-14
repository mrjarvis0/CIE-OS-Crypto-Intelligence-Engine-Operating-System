"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.timeline.milestones

Purpose:
    Milestone detection in a timeline.
"""

from __future__ import annotations

from datetime import timedelta

from ..schemas.timeline import EventArtifact, EventSeverity, Milestone
from .chronology import Chronology

_MILESTONE_TYPES = {"create", "deploy", "bridge", "withdraw", "sell", "stake", "exit"}
_HIGH_SEVERITY = {EventSeverity.IMPORTANT, EventSeverity.CRITICAL}


class MilestoneDetector:
    """
    Detects notable milestone events within a timeline.

    A milestone is either a recognized high-value event type (deploy,
    exit, bridge...) or any event flagged at important/critical severity.
    """

    def __init__(self, burst_window_seconds: float = 60.0) -> None:
        self._chronology = Chronology()
        self._burst_window = timedelta(seconds=burst_window_seconds)

    def detect(self, events: list[EventArtifact]) -> list[Milestone]:
        """
        Return milestones derived from recognized event types.
        """
        milestones: list[Milestone] = []
        for event in events:
            if event.event_type in _MILESTONE_TYPES or self._is_high(event):
                milestones.append(
                    Milestone(
                        label=event.event_type,
                        occurred_at=event.occurred_at,
                        description=event.description,
                        attributes=dict(event.attributes),
                    )
                )
        return milestones

    def detect_bursts(self, events: list[EventArtifact]) -> list[dict]:
        """
        Flag dense activity bursts (e.g. rapid multi-hop laundering).

        Returns windows where events fall within a short time span,
        indicating automated or orchestrated behaviour.
        """
        ordered = self._chronology.sort_events(events)
        bursts: list[dict] = []
        for idx, event in enumerate(ordered):
            if idx == 0:
                continue
            gap = (event.occurred_at - ordered[idx - 1].occurred_at).total_seconds()
            if gap < self._burst_window.total_seconds():
                bursts.append(
                    {
                        "event_ids": [ordered[idx - 1].event_id, event.event_id],
                        "gap_seconds": gap,
                    }
                )
        return bursts

    def _is_high(self, event: EventArtifact) -> bool:
        try:
            return EventSeverity(event.severity) in _HIGH_SEVERITY
        except ValueError:
            return False
