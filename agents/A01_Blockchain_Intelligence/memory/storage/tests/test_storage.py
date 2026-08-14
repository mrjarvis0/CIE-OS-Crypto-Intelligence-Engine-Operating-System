"""
Self-contained tests for memory.storage.

Runs without pytest:
    python memory/storage/tests/test_storage.py

Exits 0 on success, non-zero with a diagnostic on failure.
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(
    0,
    os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ),
)

from memory.base.memory import MemoryEntry, MemoryMetadata, MemoryPriority  # noqa: E402
from memory.storage import (  # noqa: E402
    BackupService,
    CacheStorage,
    FileSystemStorage,
    MemoryRepository,
    MigrationRunner,
    RestoreService,
    SnapshotManager,
    SqliteStorage,
    entry_to_payload,
    payload_to_entry,
)

PASS = 0
FAIL = 0


def check(name: str, condition: bool) -> None:
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}")


def make_entries() -> list[MemoryEntry]:
    return [
        MemoryEntry(
            "alpha",
            "prefers gas-free L2 settlement",
            MemoryMetadata(
                tags=["pref"],
                priority=MemoryPriority.HIGH,
                source="chat",
            ),
        ),
        MemoryEntry(
            "beta",
            "deployed contract on Arbitrum",
            MemoryMetadata(tags=["deploy"]),
        ),
        MemoryEntry(
            "gamma",
            "meeting at 3pm about staking yields",
            MemoryMetadata(tags=["event"]),
        ),
    ]


def test_payload_roundtrip() -> None:
    print("payload roundtrip")
    entry = make_entries()[0]
    payload = entry_to_payload(entry)
    check("payload has key", payload["key"] == "alpha")
    check("payload has metadata", payload["metadata"]["tags"] == ["pref"])
    restored = payload_to_entry(payload)
    check("value preserved", restored.value == entry.value)
    check("tags preserved", restored.metadata.tags == ["pref"])
    check("priority preserved", restored.metadata.priority == MemoryPriority.HIGH)


async def test_sqlite_repository() -> None:
    print("sqlite repository")
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "memory.db"
        storage = SqliteStorage(path=db)
        await storage.connect()
        repo = MemoryRepository(storage)
        await repo.connect()
        try:
            check("save_many", await repo.save_many(make_entries()) == 3)
            check("count", await repo.count() == 3)
            got = await repo.get("alpha")
            check("roundtrip value", got is not None and got.value == "prefers gas-free L2 settlement")
            check("roundtrip tags", got is not None and got.metadata.tags == ["pref"])
            hits = await repo.search("staking")
            check("search", [r.key for r in hits] == ["gamma"])
            check("exists", await repo.exists("beta"))
            check("delete", await repo.delete("gamma"))
            check("count after delete", await repo.count() == 2)
            check("missing get None", await repo.get("nope") is None)
            metrics = repo.metrics()
            check("metrics keys", "reads" in metrics and "writes" in metrics)
        finally:
            await repo.disconnect()


async def test_snapshots_backup_restore() -> None:
    print("snapshots / backup / restore")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        storage = SqliteStorage(path=root / "memory.db")
        await storage.connect()
        repo = MemoryRepository(storage)
        await repo.connect()
        try:
            await repo.save_many(make_entries())

            manager = SnapshotManager(storage)
            snapshot = await manager.create(label="checkpoint")
            check("snapshot count", snapshot.count == 3)
            json_payload = snapshot.to_json()
            check("snapshot roundtrip", SnapshotManager.deserialize(json_payload).count == 3)

            backup = BackupService(storage, directory=root / "backups", retention=2)
            backup_path = await backup.create_backup(label="daily")
            check("backup exists", backup_path.exists())
            check("backup listed", len(backup.list_backups()) == 1)

            await storage.clear()
            check("cleared", await repo.count() == 0)
            restored = await backup.restore(backup_path, replace=True)
            check("restore count", restored == 3)
            check("restored count", await repo.count() == 3)

            restore_service = RestoreService(storage)
            info = await restore_service.inspect(backup_path)
            check("inspect count", info["count"] == 3)
        finally:
            await repo.disconnect()


async def test_filesystem_and_cache() -> None:
    print("filesystem + cache")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)

        fs = FileSystemStorage(directory=root / "fs")
        await fs.connect()
        repo = MemoryRepository(fs)
        await repo.connect()
        try:
            await repo.save_many(make_entries()[:2])
            check("fs count", await repo.count() == 2)
            hits = await repo.search("L2")
            check("fs search", [r.key for r in hits] == ["alpha"])
            check("fs json", "alpha" in fs.to_json())
        finally:
            await repo.disconnect()

        cache = CacheStorage(max_size=5, ttl_seconds=60)
        await cache.connect()
        repo_cache = MemoryRepository(cache)
        await repo_cache.connect()
        try:
            await repo_cache.save(make_entries()[0])
            check("cache get", (await repo_cache.get("alpha")).value == "prefers gas-free L2 settlement")
            check("cache stats", cache.stats()["size"] == 1)
        finally:
            await repo_cache.disconnect()


def test_migration_runner() -> None:
    print("migration runner")
    runner = MigrationRunner()

    @runner.register(1)
    async def m1(backend, migrator):
        pass

    @runner.register(2, name="add_index")
    async def m2(backend, migrator):
        pass

    check("pending versions", asyncio.run(runner.pending()) == [1, 2])


def main() -> None:
    test_payload_roundtrip()
    test_migration_runner()
    asyncio.run(test_sqlite_repository())
    asyncio.run(test_snapshots_backup_restore())
    asyncio.run(test_filesystem_and_cache())
    print(f"\n{PASS} passed, {FAIL} failed")
    if FAIL:
        sys.exit(1)


if __name__ == "__main__":
    main()
