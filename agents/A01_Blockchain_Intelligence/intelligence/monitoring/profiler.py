"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.monitoring.profiler

Purpose:
    Performance profiling.
"""

from __future__ import annotations

import time

from typing import Any, Callable


class Profiler:
    """
    Times named operations.
    """

    def __init__(self) -> None:
        self._timings: dict[str, list[float]] = {}

    def time(self, name: str, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """
        Run a function and record its duration.
        """
        start = time.monotonic()
        result = fn(*args, **kwargs)
        elapsed = time.monotonic() - start
        self._timings.setdefault(name, []).append(elapsed)
        return result

    def record(self, name: str, elapsed: float) -> None:
        """
        Manually record a duration for a named operation.
        """
        self._timings.setdefault(name, []).append(elapsed)

    def summary(self) -> dict[str, dict[str, float]]:
        """
        Return aggregate timing stats per operation.
        """
        result: dict[str, dict[str, float]] = {}
        for name, timings in self._timings.items():
            result[name] = {
                "count": len(timings),
                "total": sum(timings),
                "avg": sum(timings) / len(timings) if timings else 0.0,
                "max": max(timings) if timings else 0.0,
            }
        return result
