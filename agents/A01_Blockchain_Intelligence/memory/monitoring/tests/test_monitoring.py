"""
Integration tests for the memory monitoring package.

Drives real ShortTermMemory instances through the monitoring
collectors.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from memory.base.memory import MemoryEntry
from memory.base.short_term import ShortTermMemory
from memory.monitoring import (
    AuditTrail,
    DiagnosticsRunner,
    HealthChecker,
    MetricsCollector,
    MonitoringReport,
    StatisticsCollector,
    UsageMonitor,
)

PASS = 0
FAIL = 0


def check(name: str, condition: bool) -> None:
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  ok  {name}")
    else:
        FAIL += 1
        print(f"FAIL  {name}")


async def scenario() -> None:
    one = ShortTermMemory()
    two = ShortTermMemory()
    await one.put(MemoryEntry("a", "alpha"))
    await one.put(MemoryEntry("b", "beta"))
    await two.put(MemoryEntry("c", "gamma"))

    health = HealthChecker()
    h1 = await health.check(one)
    check("health.check ok", h1.get("ok") is True)
    hsum = await health.check_all([("one", one), ("two", two)])
    check("health.check_all healthy", hsum["healthy_count"] == 2)
    check("health.check_all total", hsum["total"] == 2)
    check("health.check_all ok", hsum["ok"] is True)
    check("health.latest", health.latest() is not None)
    check("health.history len", len(health.history(5)) == 3)

    metrics = MetricsCollector()
    m1 = await metrics.collect(one)
    check("metrics.collect dict", isinstance(m1, dict))
    mall = await metrics.collect_all([("one", one), ("two", two)])
    check("metrics.collect_all sources", len(mall["sources"]) == 2)
    check("metrics.collect_all size", mall["totals"].get("size", 0) == 3)
    check("metrics.total_entries", metrics.total_entries() >= 3)

    stats = StatisticsCollector()
    s1 = await stats.snapshot(one)
    check("stats.snapshot dict", isinstance(s1, dict))
    await one.put(MemoryEntry("d", "delta"))
    s2 = await stats.snapshot(one)
    delta = stats.diff(s1, s2)
    check("stats.diff writes", delta.get("writes", 0) == 1)
    check("stats.latest", stats.latest() is not None)

    diag = DiagnosticsRunner()
    d1 = await diag.run(one)
    check("diagnostics.run dict", isinstance(d1, dict))
    dall = await diag.run_all([("one", one), ("two", two)])
    check("diagnostics.run_all checked", dall["checked"] == 2)

    usage = UsageMonitor()
    u1 = await usage.observe(one)
    check("usage.observe size", u1["size"] == 3)
    check("usage.observe capacity", isinstance(u1["capacity"], int))
    u2 = await usage.observe(one)
    check("usage.growth", usage.growth(u1, u2)["delta"] == 0)

    audit = AuditTrail()
    audit.record("put", one, key="a")
    audit.record("put", one, key="b")
    audit.record("delete", two, key="c")
    check("audit.recent count", len(audit.recent(10)) == 3)
    check("audit.by_operation put", len(audit.by_operation("put")) == 2)
    summary = audit.summarize()
    check("audit.summarize total", summary["total"] == 3)
    check("audit.summarize ops", summary["operations"]["put"] == 2)
    audit.clear()
    check("audit.clear", len(audit.recent()) == 0)

    reporter = MonitoringReport()
    report = await reporter.build(
        hsum, mall, {"latest": s2}, {"one": u2}, audit.summarize()
    )
    check("report.build ok", report["ok"] is True)
    check("report.summarize", "2/2" in reporter.summarize(report))
    check("report.latest", reporter.latest() is not None)


def main() -> int:
    print("monitoring tests")
    asyncio.run(scenario())
    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
