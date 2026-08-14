"""
Memory Monitor

Monitoring collectors for the memory subsystem: health checks,
metrics, statistics, diagnostics, and usage tracking over
``MemoryManager``-like sources.
"""

from __future__ import annotations

from typing import Any, Iterable

MonitoredSource = Any
MetricSource = Any
StatSource = Any
DiagSource = Any
UsageSource = Any

_OK_STATUSES = ("healthy", "ok", "up")


class HealthChecker:
    """
    Aggregate health checks across monitored memory sources.

    Responsibilities:
        * Run a single source's health check
        * Aggregate health across many sources
        * Report the overall status
    """

    def __init__(self) -> None:
        self._history: list[dict[str, Any]] = []

    async def check(self, source: MonitoredSource) -> dict[str, Any]:
        method = getattr(source, "health_check", None)
        if not callable(method):
            return {"status": "unknown", "ok": False}
        result = method()
        payload = (
            await result if hasattr(result, "__await__") else result
        )
        if not isinstance(payload, dict):
            raise TypeError("health_check() must return a dict.")
        payload.setdefault(
            "ok",
            str(payload.get("status", "")).lower() in _OK_STATUSES,
        )
        self._history.append(payload)
        return payload

    async def check_all(
        self,
        sources: Iterable[tuple[str, MonitoredSource]],
    ) -> dict[str, Any]:
        per_source: dict[str, dict[str, Any]] = {}
        for name, source in sources:
            try:
                per_source[name] = await self.check(source)
            except Exception as exc:  # noqa: BLE001
                per_source[name] = {"status": "error", "ok": False, "error": str(exc)}
        ok = all(
            entry.get("ok", False)
            for entry in per_source.values()
            if isinstance(entry, dict)
        )
        return {
            "ok": ok,
            "healthy_count": sum(
                1
                for entry in per_source.values()
                if isinstance(entry, dict) and entry.get("ok", False)
            ),
            "total": len(per_source),
            "sources": per_source,
        }

    def history(self, limit: int = 10) -> list[dict[str, Any]]:
        return self._history[-limit:]

    def latest(self) -> dict[str, Any] | None:
        return self._history[-1] if self._history else None


class MetricsCollector:
    """
    Gather and aggregate metrics across monitored sources.

    Responsibilities:
        * Collect a single source's metrics dict
        * Aggregate numeric counters across sources
        * Track collection history
    """

    def __init__(self) -> None:
        self._history: list[dict[str, Any]] = []

    async def collect(self, source: MetricSource) -> dict[str, Any]:
        method = getattr(source, "metrics", None)
        if not callable(method):
            return {}
        result = method()
        payload = (
            await result if hasattr(result, "__await__") else result
        )
        if not isinstance(payload, dict):
            raise TypeError("metrics() must return a dict.")
        self._history.append(payload)
        return payload

    async def collect_all(
        self,
        sources: Iterable[tuple[str, MetricSource]],
    ) -> dict[str, Any]:
        per_source: dict[str, dict[str, Any]] = {}
        totals: dict[str, float] = {}
        for name, source in sources:
            try:
                payload = await self.collect(source)
            except Exception:  # noqa: BLE001
                payload = {}
            per_source[name] = payload
            for key, value in payload.items():
                if isinstance(value, (int, float)):
                    totals.setdefault(key, 0.0)
                    totals[key] += value
        return {
            "sources": per_source,
            "totals": {
                key: round(value, 6)
                for key, value in sorted(totals.items())
            },
        }

    def history(self, limit: int = 10) -> list[dict[str, Any]]:
        return self._history[-limit:]

    def total_entries(self) -> int:
        total = 0
        for payload in self._history:
            total += int(
                payload.get("size", payload.get("entries", 0)) or 0
            )
        return total


class StatisticsCollector:
    """
    Take and compare statistics snapshots over time.

    Responsibilities:
        * Capture a snapshot from a source
        * Compare two snapshots to measure growth
    """

    def __init__(self) -> None:
        self._history: list[dict[str, Any]] = []

    async def snapshot(self, source: StatSource) -> dict[str, Any]:
        payload = None
        for method_name in (
            "snapshot_statistics",
            "statistics_snapshot",
            "statistics",
        ):
            method = getattr(source, method_name, None)
            if not callable(method):
                continue
            result = method()
            payload = (
                await result if hasattr(result, "__await__") else result
            )
            break
        if not isinstance(payload, dict):
            raise TypeError(
                "source must expose a statistics snapshot method."
            )
        self._history.append(payload)
        return payload

    def diff(
        self,
        earlier: dict[str, Any],
        later: dict[str, Any],
    ) -> dict[str, Any]:
        keys = sorted(set(earlier) | set(later))
        deltas: dict[str, Any] = {}
        for key in keys:
            a = earlier.get(key)
            b = later.get(key)
            if isinstance(a, (int, float)) and isinstance(b, (int, float)):
                deltas[key] = b - a
            elif a != b:
                deltas[key] = b
        return deltas

    def history(self, limit: int = 10) -> list[dict[str, Any]]:
        return self._history[-limit:]

    def latest(self) -> dict[str, Any] | None:
        return self._history[-1] if self._history else None


class DiagnosticsRunner:
    """
    Execute and aggregate diagnostics checks.

    Responsibilities:
        * Run a single source's diagnostics
        * Aggregate diagnostics across sources
        * Keep a diagnostics history
    """

    def __init__(self) -> None:
        self._history: list[dict[str, Any]] = []

    async def run(self, source: DiagSource) -> dict[str, Any]:
        method = getattr(source, "diagnostics", None)
        if not callable(method):
            return {}
        result = method()
        payload = (
            await result if hasattr(result, "__await__") else result
        )
        if not isinstance(payload, dict):
            raise TypeError("diagnostics() must return a dict.")
        self._history.append(payload)
        return payload

    async def run_all(
        self,
        sources: Iterable[tuple[str, DiagSource]],
    ) -> dict[str, Any]:
        per_source: dict[str, dict[str, Any]] = {}
        for name, source in sources:
            try:
                per_source[name] = await self.run(source)
            except Exception as exc:  # noqa: BLE001
                per_source[name] = {"ok": False, "error": str(exc)}
        issues = [
            (name, payload)
            for name, payload in per_source.items()
            if payload.get("issues")
            or payload.get("problems")
            or not payload.get("ok", True)
        ]
        return {
            "ok": len(issues) == 0,
            "checked": len(per_source),
            "sources": per_source,
            "issues": [
                {"source": name, "details": payload}
                for name, payload in issues
            ],
        }

    def history(self, limit: int = 10) -> list[dict[str, Any]]:
        return self._history[-limit:]


class UsageMonitor:
    """
    Measure utilization of monitored memory sources.

    Responsibilities:
        * Read size / capacity from a source
        * Compute utilization ratios
        * Track growth between observations
    """

    def __init__(self) -> None:
        self._history: list[dict[str, Any]] = []

    async def observe(self, source: UsageSource) -> dict[str, Any]:
        size = self._read(source, "size")
        capacity = self._read(source, "capacity")
        utilization = None
        if capacity and size is not None:
            utilization = round(size / capacity, 6)
        entry = {
            "size": size,
            "capacity": capacity,
            "utilization": utilization,
            "source": type(source).__name__,
        }
        self._history.append(entry)
        return entry

    async def observe_all(
        self,
        sources: Iterable[tuple[str, UsageSource]],
    ) -> dict[str, Any]:
        per_source: dict[str, dict[str, Any]] = {}
        for name, source in sources:
            try:
                per_source[name] = await self.observe(source)
            except Exception:  # noqa: BLE001
                per_source[name] = {}
        return {"sources": per_source}

    def growth(
        self,
        earlier: dict[str, Any],
        later: dict[str, Any],
    ) -> dict[str, Any]:
        a = earlier.get("size")
        b = later.get("size")
        return {
            "delta": (b - a) if a is not None and b is not None else None,
            "from": a,
            "to": b,
        }

    def history(self, limit: int = 10) -> list[dict[str, Any]]:
        return self._history[-limit:]

    def _read(self, source: UsageSource, name: str) -> int | None:
        value = getattr(source, name, None)
        if callable(value):
            value = value()
        if value is not None and not isinstance(value, (int, float)):
            raise TypeError(f"{name} must be numeric.")
        return None if value is None else int(value)
