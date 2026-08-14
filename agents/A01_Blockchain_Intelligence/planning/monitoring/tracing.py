"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    planning.monitoring.tracing

Purpose:
    Distributed-style tracing for the planning subsystem.

Tracks spans across planning activity so the full path of a goal
through planning, execution, and reasoning can be reconstructed.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from planning.utils.ids import generate_trace_id

logger = logging.getLogger("a01.planning.monitoring")


@dataclass(slots=True)
class Span:
    """
    A single tracing span.

    Fields:
        * Identifier, trace, and parent linkage
        * Name, status, and timestamps
        * Attributes
    """

    name: str
    id: str = field(default_factory=generate_trace_id)
    trace_id: str = field(default_factory=generate_trace_id)
    parent_id: str | None = None
    status: str = "ok"
    started_ns: int = field(default_factory=lambda: time.perf_counter_ns())
    ended_ns: int | None = None
    attributes: dict[str, Any] = field(default_factory=dict)

    @property
    def duration_ms(self) -> float | None:
        """Elapsed milliseconds once the span is ended."""
        if self.ended_ns is None:
            return None
        return (self.ended_ns - self.started_ns) / 1_000_000.0

    def end(self) -> None:
        """Close the span."""
        if self.ended_ns is None:
            self.ended_ns = time.perf_counter_ns()


class Tracer:
    """
    Creates and records tracing spans.

    Responsibilities:
        * Span creation and lifecycle
        * Trace context (current span) tracking
        * Span storage
    """

    def __init__(self) -> None:
        self._spans: list[Span] = []
        self._context: list[Span] = []

    @property
    def current_span(self) -> Span | None:
        """The most recent active span, if any."""
        return self._context[-1] if self._context else None

    def start_span(
        self,
        name: str,
        *,
        parent: Span | None = None,
        trace_id: str | None = None,
    ) -> Span:
        """Start a new span, nesting under the given (or current) parent."""
        parent_span = parent or self.current_span
        span = Span(
            name=name,
            parent_id=parent_span.id if parent_span else None,
            trace_id=trace_id or (parent_span.trace_id if parent_span else None),
        )
        self._spans.append(span)
        self._context.append(span)
        return span

    def end_span(self, span: Span) -> None:
        """Close a span, optionally popping its context."""
        span.end()

        if self._context and self._context[-1].id == span.id:
            self._context.pop()

    def end_current(self) -> Span | None:
        """End and pop the current span, if any."""
        span = self.current_span
        if span is not None:
            self.end_span(span)
        return span

    def spans_for_trace(self, trace_id: str) -> list[Span]:
        """Return all spans belonging to a trace."""
        return [span for span in self._spans if span.trace_id == trace_id]

    def trace_has_errors(self, trace_id: str) -> bool:
        """Whether any span in a trace ended in error."""
        return any(
            span.status == "error"
            for span in self.spans_for_trace(trace_id)
        )
