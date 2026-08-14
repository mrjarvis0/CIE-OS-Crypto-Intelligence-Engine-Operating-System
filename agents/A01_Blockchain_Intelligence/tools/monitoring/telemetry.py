"""
Tools :: Monitoring :: Telemetry
================================

Unified telemetry pipeline: metrics, logs and trace ingestion with
event collection and runtime statistics.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .logging import LogRecord, StructuredLogger
from .metrics import MetricsRegistry
from .tracing import Tracer, Trace

__all__ = ["TelemetryEvent", "Telemetry"]


class TelemetryEvent:
    """One free-form telemetry event."""

    def __init__(self, event_type: str, *, name: str = "", **fields: Any) -> None:
        self.event_type = event_type
        self.name = name
        self.fields = dict(fields)
        self.timestamp = time.time()

    def as_dict(self) -> Dict[str, Any]:
        return {"event_type": self.event_type, "name": self.name, "timestamp": self.timestamp, **self.fields}


class Telemetry:
    """Central telemetry collector over metrics, logs, traces and events."""

    def __init__(self, *, logger: Optional[StructuredLogger] = None) -> None:
        self.metrics = MetricsRegistry()
        self.logger = logger if logger is not None else StructuredLogger(source="telemetry")
        self.tracer = Tracer()
        self._events: List[TelemetryEvent] = []

    # -- metrics -------------------------------------------------------------------- #

    def increment(self, name: str, amount: float = 1.0, labels: Optional[Mapping[str, str]] = None) -> None:
        self.metrics.increment(name, amount, labels)

    def gauge(self, name: str, value: float, labels: Optional[Mapping[str, str]] = None) -> None:
        self.metrics.gauge(name, value, labels)

    def record_duration(self, name: str, seconds: float, labels: Optional[Mapping[str, str]] = None) -> None:
        self.metrics.duration(name, seconds, labels)

    # -- logs ------------------------------------------------------------------------- #

    def log(self, level: str, message: str, *, correlation_id: str = "", event: str = "", **fields: Any) -> LogRecord:
        return self.logger.log(level, message, correlation_id=correlation_id, event=event, **fields)

    def info(self, message: str, **fields: Any) -> LogRecord:
        return self.logger.info(message, **fields)

    def error(self, message: str, **fields: Any) -> LogRecord:
        return self.logger.error(message, **fields)

    # -- traces ------------------------------------------------------------------------ #

    def start_trace(self, name: str, trace_id: str = "") -> Trace:
        return self.tracer.start(name, trace_id)

    def finish_trace(self) -> Optional[Trace]:
        return self.tracer.finish()

    # -- events ------------------------------------------------------------------------ #

    def emit(self, event_type: str, *, name: str = "", **fields: Any) -> TelemetryEvent:
        event = TelemetryEvent(event_type, name=name, **fields)
        self._events.append(event)
        return event

    def events(self, event_type: str = "", limit: int = 200) -> List[TelemetryEvent]:
        result = [e for e in self._events if not event_type or e.event_type == event_type]
        return list(result[-max(1, int(limit)):])

    # -- snapshot ---------------------------------------------------------------------- #

    def snapshot(self) -> Dict[str, Any]:
        return {
            "metrics": self.metrics.snapshot(),
            "log_count": len(self.logger._records),
            "trace_count": len(self.tracer._traces),
            "event_count": len(self._events),
        }