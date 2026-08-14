"""
Integration tests for the memory sync package.

Drives the real ShortTermMemory through the sync orchestrators.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from memory.base.memory import MemoryEntry
from memory.base.short_term import ShortTermMemory
from memory.sync import (
    EntrySynchronizer,
    MetadataSynchronizer,
    StateSynchronizer,
    SyncCoordinator,
    SyncLock,
    SyncReporter,
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


class FakeManager:
    def __init__(self) -> None:
        self.sync_calls = 0
        self.pipeline_calls = 0
        self.checkpoint_calls = 0

    async def synchronize(self) -> dict[str, bool]:
        self.sync_calls += 1
        return {"short_term": True}

    async def synchronize_pipeline(self) -> dict[str, object]:
        self.pipeline_calls += 1
        return {
            "memories": {"short_term": True},
            "backends": {"sqlite": True},
            "successful": True,
        }

    async def checkpoint(self) -> dict[str, object]:
        self.checkpoint_calls += 1
        return {"namespace": "default", "memory_count": 1}


async def scenario() -> None:
    source = ShortTermMemory()
    target = ShortTermMemory()
    await source.put(MemoryEntry("a", "alpha"))
    await source.put(MemoryEntry("b", "beta"))

    lock = SyncLock(source)
    check("lock.supported", lock.supported())
    check("lock initially free", not await lock.locked())
    async with lock:
        check("lock held inside", await lock.locked())
    check("lock released after", not await lock.locked())
    check("lock.describe", lock.describe()["supported"] is True)

    states = StateSynchronizer()
    payload = await states.export(source)
    check("state.export entries", payload["entries"] == 2)
    await states.import_state(target, {"metadata": {"region": "us"}})
    target_meta = await states.export(target)
    check("state.import_state metadata", target_meta["metadata"].get("region") == "us")
    desc = await states.describe(source)
    check("state.describe namespace", desc["namespace"] == "default")

    entries = EntrySynchronizer()
    merged = await entries.synchronize_with(target, source)
    check("entries.synchronize_with count", merged == 2)

    third = ShortTermMemory()
    await third.put(MemoryEntry("c", "gamma"))
    total = await entries.merge(target, [source, third])
    check("entries.merge total", total == 3)

    meta = MetadataSynchronizer()
    await meta.synchronize_metadata(target, {"region": "eu"})
    check("meta.merge count", await meta.merge(target, [{"tier": "1"}]) == 1)
    delta = await meta.diff(source, target)
    check("meta.diff only_in_a", "tier" not in delta["only_in_a"])
    check("meta.diff only_in_b has tier", "tier" in delta["only_in_b"])

    reporter = SyncReporter()
    report = await reporter.report(source)
    check("reporter.report entries", report["entries"] == 2)
    summary = reporter.summarize({"a": True, "b": False})
    check("reporter.summarize failed", summary["failed"] == 1)
    check("reporter.summarize not all", summary["all_successful"] is False)
    check("reporter.format", "1/2 synced" in reporter.format({"a": True, "b": False}))

    manager = FakeManager()
    coord = SyncCoordinator(manager)
    status = await coord.synchronize()
    check("coord.synchronize", status == {"short_term": True})
    check("coord.synchronize called", manager.sync_calls == 1)
    report = await coord.run_pipeline()
    check("coord.pipeline successful", report["successful"] is True)
    check("coord.pipeline called", manager.pipeline_calls == 1)
    checkpoint = await coord.checkpoint()
    check("coord.checkpoint memory_count", checkpoint["memory_count"] == 1)
    check("coord.checkpoint called", manager.checkpoint_calls == 1)


def main() -> int:
    print("sync tests")
    asyncio.run(scenario())
    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
