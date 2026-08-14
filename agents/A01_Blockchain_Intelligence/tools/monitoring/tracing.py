"""
Tools :: Monitoring :: Tracing
==============================

Distributed execution tracing: trace IDs, span management, parent-child
relationships and end-to-end tool traces.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

__all__ = ["Span", "Tracer", "Trace"]


@dataclass
class Span:
    """One unit of work inside a trace."""

    name: str
    span_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    parent_id: str = ""
    status: str = "ok"
    started_at: float = field(default_factory=time.time)
    ended_at: Optional[float] = None
    attributes: Dict[str, Any] = field(default_factory=dict)

    def end(self, *, status: str = "ok", **attributes: Any) -> "Span":
        self.ended_at = time.time()
        self.status = status
        self.attributes.update(attributes)
        return self

    @property
    def duration_ms(self) -> float:
        end = self.ended_at if self.ended_at is not None else time.time()
        return round((end - self.started_at) * 1000, 3)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "span_id": self.span_id,
            "parent_id": self.parent_id,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "attributes": dict(self.attributes),
        }


class Trace:
    """End-to-end trace: a tree of spans."""

    def __init__(self, name: str, trace_id: str = "", *, started_at: Optional[float] = None) -> None:
        self.name = name
        self.trace_id = trace_id or uuid.uuid4().hex
        self.started_at = started_at if started_at is not None else time.time()
        self.ended_at: Optional[float] = None
        self.root: Optional[Span] = None
        self.spans: List[Span] = []

    @property
    def span_count(self) -> int:
        return len(self.spans)

    @property
    def duration_ms(self) -> float:
        end = self.ended_at if self.ended_at is not None else time.time()
        return round((end - self.started_at) * 1000, 3)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "name": self.name,
            "duration_ms": self.duration_ms,
            "span_count": len(self.spans),
            "spans": [span.as_dict() for span in self.spans],
        }


class Tracer:
    """Creates and manages traces with an active-span stack."""

    def __init__(self) -> None:
        self._active_trace: Optional[Trace] = None
        self._stack: List[Span] = []
        self._traces: Dict[str, Trace] = {}

    # -- lifecycle ---------------------------------------------------------------- #

    def start(self, name: str, trace_id: str = "") -> Trace:
        trace = Trace(name, trace_id)
        self._active_trace = trace
        self._stack = []
        self._traces[trace.trace_id] = trace
        return trace

    def span(self, name: str, **attributes: Any) -> Span:
        trace = self._active_trace
        if trace is None:
            trace = self.start(name)
        parent = self._stack[-1] if self._stack else None
        span = Span(name=name, parent_id=parent.span_id if parent else "", attributes=dict(attributes))
        if trace.root is None:
            trace.root = span
        trace.spans.append(span)
        self._stack.append(span)
        return span

    def end(self, *, status: str = "ok", **attributes: Any) -> Optional[Trace]:
        span = self._stack.pop() if self._stack else None
        if span is not None:
            span.end(status=status, **attributes)
        return self._active_trace

    def finish(self) -> Optional[Trace]:
        while self._stack:
            self._stack.pop().end()
        trace = self._active_trace
        if trace is not None:
            trace.ended_at = time.time()
        self._active_trace = None
        return trace

    # -- queries ------------------------------------------------------------------- #

    def trace(self, trace_id: str) -> Optional[Trace]:
        return self._traces.get(trace_id)

    def traces(self, limit: int = 100) -> List[Trace]:
        return list(self._traces.values())[-max(1, int(limit)):]

    def current(self) -> Optional[Trace]:
        return self._active_trace