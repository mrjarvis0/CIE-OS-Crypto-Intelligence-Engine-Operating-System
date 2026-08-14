"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.monitoring.metrics

Purpose:
    Runtime metrics collection.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class Metrics:
    """
    Collects simple counter and gauge metrics.
    """

    counters: dict[str, int] = field(default_factory=dict)
    gauges: dict[str, float] = field(default_factory=dict)

    def increment(self, name: str, by: int = 1) -> None:
        """
        Increment a named counter.
        """
        self.counters[name] = self.counters.get(name, 0) + by

    def set_gauge(self, name: str, value: float) -> None:
        """
        Set a named gauge.
        """
        self.gauges[name] = value

    def snapshot(self) -> dict[str, Any]:
        """
        Return a metrics snapshot.
        """
        return {"counters": dict(self.counters), "gauges": dict(self.gauges)}
