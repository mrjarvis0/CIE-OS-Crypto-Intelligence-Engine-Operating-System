"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.monitoring.health

Purpose:
    Health checks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Callable


@dataclass(slots=True)
class HealthStatus:
    """
    Result of a health check.
    """

    healthy: bool
    checks: dict[str, Any] = field(default_factory=dict)
    checked_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "healthy": self.healthy,
            "checks": self.checks,
            "checked_at": self.checked_at.isoformat(),
        }


class HealthCheck:
    """
    Runs registered health checks.
    """

    def __init__(self) -> None:
        self._checks: list[tuple[str, Callable[[], bool]]] = []

    def add(self, name: str, check: Callable[[], bool]) -> "HealthCheck":
        """
        Register a named health check.
        """
        self._checks.append((name, check))
        return self

    def run(self) -> HealthStatus:
        """
        Run all checks and return the overall status.

        An instance with no registered checks is never reported
        healthy: a health check that checks nothing should not claim
        the system is healthy.
        """
        results: dict[str, bool] = {}
        for name, check in self._checks:
            try:
                results[name] = bool(check())
            except Exception:  # noqa: BLE001
                results[name] = False
        healthy = bool(self._checks) and all(results.values())
        return HealthStatus(healthy=healthy, checks=results)
