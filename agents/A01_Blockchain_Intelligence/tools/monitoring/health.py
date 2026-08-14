"""
Tools :: Monitoring :: Health
=============================

Health monitoring: liveness, readiness, dependency health and overall
system status.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

__all__ = ["HealthCheck", "HealthStatus", "HealthRegistry"]


@dataclass
class HealthCheck:
    """Outcome of one named check."""

    name: str
    healthy: bool
    detail: str = ""
    latency_ms: float = 0.0
    checked_at: float = field(default_factory=time.time)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "healthy": self.healthy,
            "detail": self.detail,
            "latency_ms": self.latency_ms,
            "checked_at": self.checked_at,
        }


@dataclass
class HealthStatus:
    """Aggregate health report."""

    healthy: bool
    checks: List[HealthCheck] = field(default_factory=list)
    overall_latency_ms: float = 0.0

    @property
    def readiness(self) -> str:
        return "ready" if self.healthy else "not_ready"

    def as_dict(self) -> Dict[str, Any]:
        return {
            "healthy": self.healthy,
            "readiness": self.readiness,
            "overall_latency_ms": self.overall_latency_ms,
            "checks": [check.as_dict() for check in self.checks],
        }


class HealthRegistry:
    """Runs registered health checks (liveness/readiness/dependency)."""

    def __init__(self) -> None:
        self._checks: Dict[str, Callable[[], Any]] = {}
        self._group: Dict[str, str] = {}

    def register(self, name: str, check: Callable[[], Any], *, group: str = "dependency") -> None:
        self._checks[name] = check
        self._group[name] = group

    def _run(self, name: str) -> HealthCheck:
        started = time.perf_counter()
        try:
            result = self._checks[name]()
            healthy = bool(result)
            detail = str(result) if not isinstance(result, bool) else ""
        except Exception as exc:  # noqa: BLE001 - never fail the whole report
            healthy = False
            detail = str(exc)
        return HealthCheck(
            name=name,
            healthy=healthy,
            detail=detail,
            latency_ms=round((time.perf_counter() - started) * 1000, 3),
        )

    def check(self, names: Optional[Sequence[str]] = None) -> HealthStatus:
        selected = list(names) if names else list(self._checks)
        checks = [self._run(name) for name in selected if name in self._checks]
        return HealthStatus(
            healthy=all(check.healthy for check in checks),
            checks=checks,
            overall_latency_ms=round(sum(check.latency_ms for check in checks), 3),
        )

    def liveness(self) -> HealthStatus:
        return self.check([name for name, group in self._group.items() if group == "liveness"] or list(self._checks))

    def readiness(self) -> HealthStatus:
        return self.check()

    def by_group(self, group: str) -> HealthStatus:
        return self.check([name for name, g in self._group.items() if g == group])

    def names(self) -> List[str]:
        return list(self._checks)