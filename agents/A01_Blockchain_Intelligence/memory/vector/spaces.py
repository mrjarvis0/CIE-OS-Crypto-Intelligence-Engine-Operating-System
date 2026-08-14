"""
Vector Spaces

Namespace, collection, and snapshot management for vector storage over
a ``VectorMemory``-like source. Thin facades using duck typing.
"""

from __future__ import annotations

from typing import Any

VectorSource = Any
NamespaceSource = Any

DEFAULT_NAMESPACE = "default"


class CollectionError(Exception):
    pass


class CollectionNotFoundError(CollectionError):
    pass


class CollectionManager:
    """
    Manages named vector collections.

    Responsibilities:
        * Create and drop collections
        * List and resolve collections
        * Track collection statistics
    """

    def __init__(
        self,
        memory: VectorSource,
        *,
        default_collection: str = "_default",
    ) -> None:
        self._memory = memory
        self._default_collection = default_collection

    @property
    def memory(self) -> VectorSource:
        return self._memory

    @property
    def default_collection(self) -> str:
        return self._default_collection

    async def create(self, name: str, *, namespace: str | None = None) -> bool:
        create_collection = getattr(self._memory, "create_collection", None)
        if not callable(create_collection):
            raise AttributeError(
                "memory source must expose create_collection()"
            )
        result = create_collection(name, namespace=namespace)
        return await result if hasattr(result, "__await__") else bool(result)

    async def drop(self, name: str, *, namespace: str | None = None) -> bool:
        drop_collection = getattr(self._memory, "drop_collection", None)
        if not callable(drop_collection):
            raise AttributeError(
                "memory source must expose drop_collection()"
            )
        result = drop_collection(name, namespace=namespace)
        return await result if hasattr(result, "__await__") else bool(result)

    async def list(self, *, namespace: str | None = None) -> list[str]:
        list_collections = getattr(self._memory, "list_collections", None)
        if not callable(list_collections):
            raise AttributeError(
                "memory source must expose list_collections()"
            )
        try:
            result = list_collections(namespace=namespace)
        except TypeError:  # pragma: no cover - source without kwarg
            result = list_collections()
        return await result if hasattr(result, "__await__") else list(result)

    async def exists(self, name: str, *, namespace: str | None = None) -> bool:
        return name in await self.list(namespace=namespace)

    async def ensure(self, name: str, *, namespace: str | None = None) -> bool:
        if await self.exists(name):
            return False
        return await self.create(name, namespace=namespace)

    async def count_entries(
        self,
        name: str,
        *,
        namespace: str | None = None,
    ) -> int:
        keys = getattr(self._memory, "keys", None)
        if not callable(keys):
            return 0
        result = keys(namespace=namespace, collection=name)
        keys_list = await result if hasattr(result, "__await__") else result
        return len(keys_list)

    async def snapshot(self) -> dict[str, Any]:
        collections = await self.list()
        return {
            "collections": collections,
            "default_collection": self._default_collection,
            "counts": {
                name: await self.count_entries(name) for name in collections
            },
        }


class NamespaceError(Exception):
    pass


class NamespaceNotFoundError(NamespaceError):
    pass


class NamespaceExistsError(NamespaceError):
    pass


class NamespaceManager:
    """
    Provides namespace isolation within vector storage.

    Responsibilities:
        * Create and delete namespaces
        * Resolve and validate namespace keys
        * Enforce access boundaries
        * Track namespace statistics
    """

    def __init__(
        self,
        memory: NamespaceSource,
        *,
        default_namespace: str = DEFAULT_NAMESPACE,
    ) -> None:
        self._memory = memory
        self._default_namespace = default_namespace

    @property
    def memory(self) -> NamespaceSource:
        return self._memory

    @property
    def default_namespace(self) -> str:
        return self._default_namespace

    def _require_source(self) -> None:
        if not any(
            callable(getattr(self._memory, method, None))
            for method in (
                "create_namespace",
                "delete_namespace",
                "list_namespaces",
            )
        ):
            raise AttributeError(
                "memory source must expose namespace management methods"
            )

    async def create(self, namespace: str) -> bool:
        self._require_source()
        self._validate(namespace)
        create_namespace = getattr(self._memory, "create_namespace", None)
        if not callable(create_namespace):
            raise AttributeError("memory source must expose create_namespace()")
        result = create_namespace(namespace)
        if hasattr(result, "__await__"):
            return await result
        return bool(result)

    async def delete(self, namespace: str) -> bool:
        self._require_source()
        self._validate(namespace)
        delete_namespace = getattr(self._memory, "delete_namespace", None)
        if not callable(delete_namespace):
            raise AttributeError("memory source must expose delete_namespace()")
        result = delete_namespace(namespace)
        if hasattr(result, "__await__"):
            return await result
        return bool(result)

    async def list(self) -> list[str]:
        self._require_source()
        list_namespaces = getattr(self._memory, "list_namespaces", None)
        if not callable(list_namespaces):
            raise AttributeError("memory source must expose list_namespaces()")
        result = list_namespaces()
        if hasattr(result, "__await__"):
            return await result
        return list(result)

    async def exists(self, namespace: str) -> bool:
        self._require_source()
        return namespace in await self.list()

    def _validate(self, namespace: str) -> None:
        if not namespace or not namespace.strip():
            raise NamespaceError("Namespace must be a non-empty string.")
        if any(ch in namespace for ch in "/\\\0"):
            raise NamespaceError(
                f"Namespace '{namespace}' contains reserved characters."
            )

    async def ensure(
        self,
        namespace: str,
    ) -> bool:
        """
        Create the namespace when it does not already exist.
        """
        if await self.exists(namespace):
            return False
        return await self.create(namespace)

    async def swap(
        self,
        old_namespace: str,
        new_namespace: str,
    ) -> bool:
        """
        Recreate an existing namespace under a new key. This is a
        cooperative migration helper: callers must re-insert entries.
        """
        if not await self.exists(old_namespace):
            raise NamespaceNotFoundError(
                f"Namespace '{old_namespace}' does not exist."
            )
        await self.ensure(new_namespace)
        await self.delete(old_namespace)
        return True

    async def counts(self) -> dict[str, int]:
        """
        Map each namespace to its entry count where the source supports
        per-namespace key enumeration.
        """
        counts: dict[str, int] = {}
        for namespace in await self.list():
            counts[namespace] = await self._count_namespace(namespace)
        return counts

    async def _count_namespace(self, namespace: str) -> int:
        keys = getattr(self._memory, "keys", None)
        if not callable(keys):
            return 0
        result = keys(namespace=namespace)
        if hasattr(result, "__await__"):
            return len(await result)
        return len(result)

    async def snapshot(self) -> dict[str, Any]:
        return {
            "namespaces": await self.list(),
            "default_namespace": self._default_namespace,
            "counts": await self.counts(),
        }


class SnapshotError(Exception):
    pass


class SnapshotManager:
    """
    Manages vector memory snapshots.

    Responsibilities:
        * Capture full state snapshots
        * Apply snapshots to restore state
        * Report snapshot metadata
    """

    def __init__(self, memory: VectorSource) -> None:
        self._memory = memory

    @property
    def memory(self) -> VectorSource:
        return self._memory

    async def snapshot(self) -> dict[str, Any]:
        snapshot = getattr(self._memory, "snapshot", None)
        if not callable(snapshot):
            raise AttributeError("memory source must expose snapshot()")
        result = snapshot()
        payload = (
            await result if hasattr(result, "__await__") else result
        )
        if not isinstance(payload, dict):
            raise SnapshotError("snapshot() must return a dict.")
        return payload

    async def restore(
        self,
        payload: dict[str, Any],
    ) -> bool:
        """
        Replace current state with a snapshot payload.
        """
        restore = getattr(self._memory, "restore", None)
        if callable(restore):
            result = restore(payload)
            result = (
                await result
                if hasattr(result, "__await__")
                else result
            )
            return bool(result)
        return await self._restore_via_clear(payload)

    async def _restore_via_clear(self, payload: dict[str, Any]) -> bool:
        clear = getattr(self._memory, "clear", None)
        put = getattr(self._memory, "put", None)
        if not callable(clear) or not callable(put):
            raise SnapshotError(
                "memory source must expose restore() or clear()+put()"
            )
        result = clear()
        await result if hasattr(result, "__await__") else None
        entries = payload.get("entries") or payload.get("items") or []
        for item in entries:
            key = item.get("key")
            value = item.get("value")
            if key is None or value is None:
                continue
            metadata = item.get("metadata") or {}
            put_result = put(
                key,
                value,
                namespace=metadata.get("namespace"),
                tags=metadata.get("tags"),
                priority=metadata.get("priority"),
                source=metadata.get("source"),
            )
            await put_result if hasattr(put_result, "__await__") else None
        return True

    def describe(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        entries = payload.get("entries") or payload.get("items") or []
        return {
            "entry_count": len(entries) or payload.get("entries_count", 0),
            "keys": payload.get("keys", []),
            "schema_version": payload.get("schema_version"),
            "captured_at": payload.get("captured_at")
            or payload.get("timestamp"),
            "namespace": payload.get("namespace"),
            "collection": payload.get("collection"),
        }
