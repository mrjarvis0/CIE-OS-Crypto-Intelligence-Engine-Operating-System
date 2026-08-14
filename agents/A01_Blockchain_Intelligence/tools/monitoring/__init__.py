"""
Tools :: Monitoring Layer
=========================

The observability and telemetry system of the Tools platform: metrics,
structured logs, distributed traces, health, profiling, diagnostics and
unified telemetry ingestion.

Monitoring never executes tools; it observes them.

Modules: metrics, logging, tracing, telemetry, health, profiler,
diagnostics. :class:`Monitor` is the facade every subsystem publishes to.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Mapping, Optional, Sequence

__all__ = [
    "MonitoringError",
    "Metric",
    "MetricKind",
    "MetricsRegistry",
    "LogRecord",
    "StructuredLogger",
    "Span",
    "Trace",
    "Tracer",
    "TelemetryEvent",
    "Telemetry",
    "HealthCheck",
    "HealthStatus",
    "HealthRegistry",
    "ProfileSample",
    "ProfileReport",
    "Profiler",
    "DiagnosticReport",
    "DiagnosticEngine",
    "ERROR_CATEGORIES",
    "categorize_error",
    "Monitor",
]

logger = logging.getLogger(__name__)


class MonitoringError(Exception):
    """Base class for every error raised by the monitoring layer."""


from .metrics import Metric, MetricKind, MetricsRegistry  # noqa: E402
from .logging import LogRecord, StructuredLogger  # noqa: E402
from .tracing import Span, Trace, Tracer  # noqa: E402
from .telemetry import TelemetryEvent, Telemetry  # noqa: E402
from .health import HealthCheck, HealthStatus, HealthRegistry  # noqa: E402
from .profiler import ProfileSample, ProfileReport, Profiler  # noqa: E402
from .diagnostics import DiagnosticReport, DiagnosticEngine, ERROR_CATEGORIES, categorize_error  # noqa: E402


class Monitor:
    """Facade: one entry point for metrics, logs, traces, health and diagnostics."""

    def __init__(
        self,
        *,
        telemetry: Optional[Telemetry] = None,
        health: Optional[HealthRegistry] = None,
        profiler: Optional[Profiler] = None,
        diagnostics: Optional[DiagnosticEngine] = None,
    ) -> None:
        self.telemetry = telemetry if telemetry is not None else Telemetry()
        self.health = health if health is not None else HealthRegistry()
        self.profiler = profiler if profiler is not None else Profiler()
        self.diagnostics = diagnostics if diagnostics is not None else DiagnosticEngine()

    def instrument(self, name: str, duration_s: float, *, ok: bool = True, labels: Optional[Mapping[str, str]] = None) -> None:
        self.telemetry.record_duration(name, duration_s, labels)
        self.telemetry.increment(name + "_count", labels=labels)
        if not ok:
            self.telemetry.increment(name + "_failures", labels=labels)

    def snapshot(self) -> Dict[str, Any]:
        return {
            "telemetry": self.telemetry.snapshot(),
            "health": self.health.check().as_dict(),
            "profile": self.profiler.report().as_dict(),
            "diagnostics": self.diagnostics.categories(),
        }