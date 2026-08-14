"""
CIE-OS
A01 Blockchain Intelligence Agent

Package:
    planning.monitoring

Purpose:
    Monitoring subsystem for the planning stack.

Provides event emission, metrics, tracing, timelines, progress
tracking, and diagnostics.
"""

from __future__ import annotations

# ==============================================================================
# Events
# ==============================================================================

from .events import (
    EventBus,
    PlanEvent,
    Subscriber,
)

# ==============================================================================
# Metrics
# ==============================================================================

from .metrics import (
    Counter,
    Gauge,
    MetricsRegistry,
    Timer,
)

# ==============================================================================
# Tracing
# ==============================================================================

from .tracing import (
    Span,
    Tracer,
)

# ==============================================================================
# Timeline
# ==============================================================================

from .timeline import (
    Timeline,
    TimelineEntry,
)

# ==============================================================================
# Progress
# ==============================================================================

from .progress import (
    ProgressReport,
    ProgressTracker,
)

# ==============================================================================
# Diagnostics
# ==============================================================================

from .diagnostics import (
    CheckResult,
    DiagnosticReport,
    Diagnostics,
)

# ==============================================================================
# Public API
# ==============================================================================

__all__ = [
    # Events
    "Subscriber",
    "PlanEvent",
    "EventBus",
    # Metrics
    "Counter",
    "Gauge",
    "MetricsRegistry",
    "Timer",
    # Tracing
    "Span",
    "Tracer",
    # Timeline
    "TimelineEntry",
    "Timeline",
    # Progress
    "ProgressReport",
    "ProgressTracker",
    # Diagnostics
    "CheckResult",
    "DiagnosticReport",
    "Diagnostics",
]
