"""
Vector Maintenance

Index, metrics, and compaction operations for vector storage over a
``VectorMemory``-like source.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

VectorSource = Any


@dataclass(slots=True)
class IndexStatus:
    """
    Snapshot of the current vector index.
    """

    rebuilt_at: datetime | None = None
    entry_count: int = 0
    collections: list[str] = field(default_factory=list)
    namespaces: list[str] = field(default_factory=list)
    last_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "rebuilt_at": self.rebuilt_at.isoformat()
            if self.rebuilt_at
            else None,
            "entry_count": self.entry_count,
            "collections": self.collections,
            "namespaces": self.namespaces,
            "last_error": self.last_error,
        }


class VectorIndex:
    """
    Manages the vector index lifecycle.

    Responsibilities:
        * Rebuild embeddings for stored entries
        * Report index statistics
        * Expose maintenance status
    """

    def __init__(self, memory: VectorSource) -> None:
        self._memory = memory
        self._rebuilt_at: datetime | None = None
        self._last_error: str | None = None

    @property
    def memory(self) -> VectorSource:
        return self._memory

    async def rebuild(self) -> int:
        """
        Re-embed all stored entries. Returns the number reindexed.
        """
        rebuild_index = getattr(self._memory, "rebuild_index", None)
        if callable(rebuild_index):
            result = rebuild_index()
            await result if hasattr(result, "__await__") else None
        count = await self.entry_count()
        self._rebuilt_at = datetime.now(UTC)
        self._last_error = None
        return count

    async def entry_count(self) -> int:
        count = getattr(self._memory, "count", None)
        if callable(count):
            result = count()
            return await result if hasattr(result, "__await__") else result
        keys = getattr(self._memory, "keys", None)
        if callable(keys):
            result = keys()
            keys_list = (
                await result if hasattr(result, "__await__") else result
            )
            return len(keys_list)
        return 0

    async def list_collections(self) -> list[str]:
        list_collections = getattr(self._memory, "list_collections", None)
        if not callable(list_collections):
            return []
        result = list_collections()
        return await result if hasattr(result, "__await__") else result

    async def list_namespaces(self) -> list[str]:
        list_namespaces = getattr(self._memory, "list_namespaces", None)
        if not callable(list_namespaces):
            return []
        result = list_namespaces()
        return await result if hasattr(result, "__await__") else result

    async def status(self) -> IndexStatus:
        try:
            return IndexStatus(
                rebuilt_at=self._rebuilt_at,
                entry_count=await self.entry_count(),
                collections=await self.list_collections(),
                namespaces=await self.list_namespaces(),
                last_error=self._last_error,
            )
        except Exception as exc:  # pragma: no cover - defensive
            self._last_error = str(exc)
            return IndexStatus(
                rebuilt_at=self._rebuilt_at,
                entry_count=0,
                last_error=str(exc),
            )

    async def health(self) -> dict[str, Any]:
        status = await self.status()
        return {
            "ok": status.last_error is None,
            "entries": status.entry_count,
            "collections": status.collections,
            "namespaces": status.namespaces,
            "last_rebuilt": status.rebuilt_at.isoformat()
            if status.rebuilt_at
            else None,
        }


@dataclass(slots=True)
class VectorMetrics:
    """
    Collected vector memory metrics.
    """

    entry_count: int = 0
    namespace_count: int = 0
    collection_count: int = 0
    cache_size: int = 0
    cache_capacity: int = 0
    hit_rate: float = 0.0
    healthy: bool = True
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_count": self.entry_count,
            "namespace_count": self.namespace_count,
            "collection_count": self.collection_count,
            "cache_size": self.cache_size,
            "cache_capacity": self.cache_capacity,
            "hit_rate": self.hit_rate,
            "healthy": self.healthy,
            "detail": self.detail,
        }


class VectorMetricsCollector:
    """
    Collects operational metrics from vector memory.

    Responsibilities:
        * Gather entry / namespace / collection counts
        * Pull embedder cache statistics
        * Compute an overall health summary
    """

    def __init__(self, memory: Any) -> None:
        self._memory = memory

    @property
    def memory(self) -> Any:
        return self._memory

    async def collect(self) -> VectorMetrics:
        detail: dict[str, Any] = {}
        healthy = True

        async def safe(op: str) -> Any:
            nonlocal healthy
            try:
                return await self._call(op)
            except Exception as exc:  # pragma: no cover - defensive
                detail.setdefault("errors", []).append(f"{op}: {exc}")
                healthy = False
                return None

        entry_count = await safe("count")
        namespaces = await safe("list_namespaces")
        collections = await safe("list_collections")
        namespaces = list(namespaces) if namespaces else []
        collections = list(collections) if collections else []
        detail["namespaces"] = namespaces
        detail["collections"] = collections

        cache_stats = self._embedder_stats()
        if cache_stats is not None:
            detail["embedder_cache"] = cache_stats

        return VectorMetrics(
            entry_count=int(entry_count or 0),
            namespace_count=len(namespaces),
            collection_count=len(collections),
            cache_size=int(cache_stats.get("size", 0))
            if cache_stats
            else 0,
            cache_capacity=int(cache_stats.get("capacity", 0))
            if cache_stats
            else 0,
            hit_rate=float(cache_stats.get("hit_rate", 0.0))
            if cache_stats
            else 0.0,
            healthy=healthy,
            detail=detail,
        )

    async def health(self) -> dict[str, Any]:
        metrics = await self.collect()
        return {
            "healthy": metrics.healthy,
            "entries": metrics.entry_count,
            "namespaces": metrics.namespace_count,
            "collections": metrics.collection_count,
            "hit_rate": metrics.hit_rate,
        }

    def _embedder_stats(self) -> dict[str, Any] | None:
        embedder = getattr(self._memory, "embedder", None)
        if embedder is None:
            return None
        stats = getattr(embedder, "stats", None)
        if not callable(stats):
            return None
        return stats()

    async def _call(self, name: str):
        fn = getattr(self._memory, name, None)
        if not callable(fn):
            return None
        result = fn()
        if hasattr(result, "__await__"):
            return await result
        return result


@dataclass(slots=True)
class MaintenanceReport:
    """
    Outcome of a maintenance run.
    """

    compacted: bool = False
    purged: int = 0
    optimized: bool = False
    started_at: datetime | None = None
    finished_at: datetime | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "compacted": self.compacted,
            "purged": self.purged,
            "optimized": self.optimized,
            "started_at": self.started_at.isoformat()
            if self.started_at
            else None,
            "finished_at": self.finished_at.isoformat()
            if self.finished_at
            else None,
            "notes": self.notes,
        }


class VectorCompactor:
    """
    Runs maintenance on vector storage.

    Responsibilities:
        * Compact the underlying store
        * Purge expired or stale entries
        * Optimize (vacuum) storage
    """

    def __init__(self, memory: Any) -> None:
        self._memory = memory

    @property
    def memory(self) -> Any:
        return self._memory

    async def compact(self) -> MaintenanceReport:
        report = MaintenanceReport()
        report.started_at = datetime.now(UTC)
        compact = getattr(self._memory, "compact", None)
        if callable(compact):
            result = compact()
            await result if hasattr(result, "__await__") else None
            report.compacted = True
            report.notes.append("compact() executed")
        report.finished_at = datetime.now(UTC)
        return report

    async def purge(
        self,
        *,
        namespace: str | None = None,
        collection: str | None = None,
    ) -> int:
        """
        Purge entries in a namespace/collection. Returns rows removed.
        """
        drop_collection = getattr(self._memory, "drop_collection", None)
        if callable(drop_collection) and collection is not None:
            result = drop_collection(collection, namespace=namespace)
            return (
                await result if hasattr(result, "__await__") else result
            )
        clear = getattr(self._memory, "clear", None)
        if not callable(clear):
            return 0
        result = clear(namespace=namespace, collection=collection)
        await result if hasattr(result, "__await__") else None
        return 0

    async def optimize(self) -> MaintenanceReport:
        report = MaintenanceReport()
        report.started_at = datetime.now(UTC)
        vacuum = getattr(self._memory, "vacuum", None)
        if callable(vacuum):
            result = vacuum()
            await result if hasattr(result, "__await__") else None
            report.optimized = True
            report.notes.append("vacuum() executed")
        report.finished_at = datetime.now(UTC)
        return report

    async def run(
        self,
        *,
        purge: bool = False,
        namespace: str | None = None,
        collection: str | None = None,
    ) -> MaintenanceReport:
        report = await self.compact()
        if purge:
            report.purged = await self.purge(
                namespace=namespace,
                collection=collection,
            )
        optimize_report = await self.optimize()
        report.optimized = optimize_report.optimized
        report.notes.extend(optimize_report.notes)
        report.finished_at = datetime.now(UTC)
        return report
