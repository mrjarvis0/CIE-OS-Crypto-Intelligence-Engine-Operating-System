"""
Memory Audit and Report

Audit trail recording and consolidated monitoring reports for the
memory subsystem.
"""

from __future__ import annotations

from typing import Any

AuditSource = Any
ReportSource = Any


class AuditTrail:
    """
    Append-only audit log for memory operations.

    Responsibilities:
        * Record operations with timestamps
        * Query recent / per-source operations
        * Summarize activity
    """

    def __init__(self, max_entries: int = 1000) -> None:
        self._entries: list[dict[str, Any]] = []
        self._max_entries = max_entries

    def record(
        self,
        operation: str,
        source: AuditSource | None = None,
        **details: Any,
    ) -> dict[str, Any]:
        entry = {
            "operation": operation,
            "source": (
                type(source).__name__ if source is not None else None
            ),
            "details": details,
            "sequence": len(self._entries) + 1,
        }
        self._entries.append(entry)
        if len(self._entries) > self._max_entries:
            self._entries = self._entries[-self._max_entries :]
        return entry

    def recent(self, limit: int = 10) -> list[dict[str, Any]]:
        return self._entries[-limit:]

    def by_operation(self, operation: str) -> list[dict[str, Any]]:
        return [
            entry
            for entry in self._entries
            if entry["operation"] == operation
        ]

    def summarize(self) -> dict[str, Any]:
        counts: dict[str, int] = {}
        for entry in self._entries:
            op = entry["operation"]
            counts[op] = counts.get(op, 0) + 1
        return {
            "total": len(self._entries),
            "operations": dict(
                sorted(counts.items(), key=lambda item: item[0])
            ),
        }

    def clear(self) -> None:
        self._entries.clear()


class MonitoringReport:
    """
    Build a unified snapshot of memory subsystem health.

    Responsibilities:
        * Combine health, metrics, statistics, and usage
        * Attach audit activity
        * Render a short summary string
    """

    def __init__(self) -> None:
        self._history: list[dict[str, Any]] = []

    async def build(
        self,
        health: dict[str, Any],
        metrics: dict[str, Any],
        statistics: dict[str, Any],
        usage: dict[str, Any],
        audit: dict[str, Any],
    ) -> dict[str, Any]:
        report = {
            "ok": bool(health.get("ok", False)),
            "health": health,
            "metrics": metrics,
            "statistics": statistics,
            "usage": usage,
            "audit": audit,
        }
        self._history.append(report)
        return report

    def summarize(self, report: dict[str, Any]) -> str:
        health = report.get("health", {})
        metrics = report.get("metrics", {})
        totals = metrics.get("totals", {})
        healthy = health.get("healthy_count", 0)
        total = health.get("total", 0)
        return (
            f"ok={report.get('ok', False)} "
            f"health={healthy}/{total} "
            f"entries={totals.get('entries', 0)}"
        )

    def history(self, limit: int = 10) -> list[dict[str, Any]]:
        return self._history[-limit:]

    def latest(self) -> dict[str, Any] | None:
        return self._history[-1] if self._history else None
