"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    planning.monitoring.metrics

Purpose:
    Metric collection for the planning subsystem.

Provides counters, gauges, and timers to track planning activity such
as tasks created, tasks succeeded, and execution durations.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("a01.planning.monitoring")


@dataclass(slots=True)
class Counter:
    """
    A monotonically increasing counter.

    Fields:
        * Name and current value
    """

    name: str
    value: int = 0

    def inc(self, amount: int = 1) -> int:
        """Increment and return the counter value."""
        self.value += amount
        return self.value

    def reset(self) -> None:
        """Reset the counter to zero."""
        self.value = 0


@dataclass(slots=True)
class Gauge:
    """
    A value that can rise and fall.

    Fields:
        * Name and current value
    """

    name: str
    value: float = 0.0

    def set(self, value: float) -> None:
        """Set the gauge value."""
        self.value = value

    def add(self, amount: float) -> float:
        """Adjust the gauge by a delta and return the new value."""
        self.value += amount
        return self.value


class MetricsRegistry:
    """
    Stores and reports planning metrics.

    Responsibilities:
        * Counter management
        * Gauge management
        * Snapshot reporting
    """

    def __init__(self) -> None:
        self._counters: dict[str, Counter] = {}
        self._gauges: dict[str, Gauge] = {}
        self._timers: dict[str, list[float]] = defaultdict(list)

    def counter(self, name: str) -> Counter:
        """Return (creating if needed) a named counter."""
        if name not in self._counters:
            self._counters[name] = Counter(name)
        return self._counters[name]

    def gauge(self, name: str) -> Gauge:
        """Return (creating if needed) a named gauge."""
        if name not in self._gauges:
            self._gauges[name] = Gauge(name)
        return self._gauges[name]

    def inc(self, name: str, amount: int = 1) -> int:
        """Increment a named counter."""
        return self.counter(name).inc(amount)

    def record_duration(self, name: str, seconds: float) -> None:
        """Record a duration sample under a named timer."""
        self._timers[name].append(seconds)

    def duration_stats(self, name: str) -> dict[str, float]:
        """Return count, total, and mean for a named timer."""
        samples = self._timers[name]

        if not samples:
            return {"count": 0.0, "total": 0.0, "mean": 0.0}

        total = sum(samples)
        return {
            "count": float(len(samples)),
            "total": total,
            "mean": total / len(samples),
        }

    def snapshot(self) -> dict[str, Any]:
        """Return a full metrics snapshot."""
        return {
            "counters": {
                name: counter.value
                for name, counter in self._counters.items()
            },
            "gauges": {
                name: gauge.value
                for name, gauge in self._gauges.items()
            },
            "timers": {
                name: self.duration_stats(name)
                for name in self._timers
            },
        }

    def reset(self) -> None:
        """Reset all counters, gauges, and timers."""
        for counter in self._counters.values():
            counter.reset()

        for gauge in self._gauges.values():
            gauge.set(0.0)

        self._timers.clear()


class Timer:
    """
    Context manager that records elapsed time into a registry.

    Usage::

        with Timer(metrics, "task_run"):
            ...
    """

    def __init__(
        self,
        registry: MetricsRegistry,
        name: str,
    ) -> None:
        self._registry = registry
        self._name = name
        self._started: float | None = None

    def __enter__(self) -> "Timer":
        self._started = time.perf_counter()
        return self

    def __exit__(self, *exc_info: Any) -> None:
        if self._started is not None:
            self._registry.record_duration(
                self._name,
                time.perf_counter() - self._started,
            )
