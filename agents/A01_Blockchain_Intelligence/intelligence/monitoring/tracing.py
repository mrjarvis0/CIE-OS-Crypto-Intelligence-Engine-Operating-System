"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.monitoring.tracing

Purpose:
    Trace recording.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Iterator

from ..utils.helpers import new_id


@dataclass(slots=True)
class Trace:
    """
    A recorded trace span.
    """

    name: str
    span_id: str
    parent_id: str | None = None
    start: datetime = field(default_factory=lambda: datetime.now(UTC))
    end: datetime | None = None
    attributes: dict[str, Any] = field(default_factory=dict)

    def close(self) -> None:
        """
        Mark the trace as complete.
        """
        if self.end is None:
            self.end = datetime.now(UTC)

    @property
    def duration_ms(self) -> float:
        """
        Duration in milliseconds.
        """
        if self.end is None:
            return 0.0
        return (self.end - self.start).total_seconds() * 1000


class Tracer:
    """
    Manages a stack of trace spans.
    """

    def __init__(self) -> None:
        self._stack: list[Trace] = []
        self._completed: list[Trace] = []

    def start(self, name: str) -> Trace:
        """
        Begin a new span, nested under the current top.
        """
        parent = self._stack[-1] if self._stack else None
        trace = Trace(
            name=name,
            span_id=new_id("span"),
            parent_id=parent.span_id if parent else None,
        )
        self._stack.append(trace)
        return trace

    @contextmanager
    def span(self, name: str) -> Iterator[Trace]:
        """
        Context-manager span: automatically stops on exit, even on error.
        """
        trace = self.start(name)
        try:
            yield trace
        finally:
            self.stop(trace)

    def stop(self, trace: Trace) -> None:
        """
        Complete a span and record it.

        Stopping is idempotent: a span that is already closed (or was
        already recorded) is not appended a second time.
        """
        if trace in self._completed:
            return
        trace.close()
        if trace in self._stack:
            self._stack.remove(trace)
        self._completed.append(trace)

    def completed(self) -> list[Trace]:
        """
        Return all completed spans.
        """
        return list(self._completed)
