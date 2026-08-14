"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.timeline.chronology

Purpose:
    Ordering and time-series helpers for timelines.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ..schemas.timeline import EventArtifact

_EPOCH = datetime.min


def _when(event: EventArtifact) -> datetime:
    """
    Ordering key: events with an unknown timestamp sort first.
    """
    return event.occurred_at if event.occurred_at is not None else _EPOCH


class Chronology:
    """
    Chronological ordering helpers and time-series analysis.

    Includes activity-gap detection, useful for spotting dormancy
    (long inactive windows) and burst activity that may indicate an
    automated operator.
    """

    def sort_events(self, events: list[EventArtifact]) -> list[EventArtifact]:
        """
        Return events sorted ascending by occurrence time.
        """
        return sorted(events, key=_when)

    def reverse(self, events: list[EventArtifact]) -> list[EventArtifact]:
        """
        Return events sorted descending by occurrence time.
        """
        return sorted(events, key=_when, reverse=True)

    def between(self, events: list[EventArtifact], start: datetime, end: datetime) -> list[EventArtifact]:
        """
        Return events within the [start, end] datetime range.

        Events without a timestamp are excluded; a None start/end is
        treated as unbounded.
        """
        if not events:
            return []
        return [
            e
            for e in events
            if e.occurred_at is not None
            and (start is None or start <= e.occurred_at)
            and (end is None or e.occurred_at <= end)
        ]

    def gaps(self, events: list[EventArtifact]) -> list[tuple[datetime, datetime, float]]:
        """
        Return inactivity gaps between consecutive events.

        Each entry is (previous_event_time, next_event_time, gap_seconds).
        Large gaps indicate dormancy; near-zero gaps indicate bursts.
        """
        ordered = self.sort_events([e for e in events if e.occurred_at is not None])
        gaps: list[tuple[datetime, datetime, float]] = []
        for prev, nxt in zip(ordered, ordered[1:]):
            gap = (nxt.occurred_at - prev.occurred_at).total_seconds()
            gaps.append((prev.occurred_at, nxt.occurred_at, gap))
        return gaps

    def activity_span_days(self, events: list[EventArtifact]) -> float:
        """
        Return the total span in days between the first and last event.
        """
        ordered = self.sort_events([e for e in events if e.occurred_at is not None])
        if not ordered:
            return 0.0
        return (ordered[-1].occurred_at - ordered[0].occurred_at).total_seconds() / 86400.0
