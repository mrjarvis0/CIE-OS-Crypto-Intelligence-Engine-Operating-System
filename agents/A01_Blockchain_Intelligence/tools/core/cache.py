"""
Tools :: Core :: Cache
======================

Execution cache used by the executor for request deduplication and result
reuse, plus a capability-index cache for the registry.

Built on the utils layer caches; adds request-scoped key building and an
in-flight dedup guard so concurrent identical requests execute once.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, Dict, Mapping, Optional

from ..utils.cache import TTLCache
from ..utils.hashing import deterministic_key

__all__ = ["ExecutionCache", "InFlightGuard"]


class ExecutionCache:
    """
    TTL result cache keyed by (tool, arguments-hash).

    ``enabled=False`` disables reads/writes; ``ttl`` seconds per entry.
    ``get_or_execute`` runs ``fn`` once per unique key and returns the
    cached result for the duration of the TTL.
    """

    def __init__(self, *, ttl: float = 30.0, enabled: bool = True, maxsize: Optional[int] = 2048) -> None:
        self._ttl = ttl
        self._enabled = enabled
        self._cache: "TTLCache[str, Any]" = TTLCache(default_ttl=ttl, maxsize=maxsize)

    @property
    def enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, value: bool) -> None:
        self._enabled = bool(value)
        if not self._enabled:
            self.clear()

    def key_for(self, tool: str, arguments: Mapping[str, Any], *, scope: str = "") -> str:
        return deterministic_key(scope, tool, arguments)

    def get(self, tool: str, arguments: Mapping[str, Any], *, scope: str = "") -> Optional[Any]:
        if not self._enabled:
            return None
        return self._cache.get(self.key_for(tool, arguments, scope=scope))

    def set(self, tool: str, arguments: Mapping[str, Any], result: Any, *, scope: str = "") -> None:
        if not self._enabled:
            return
        self._cache.set(self.key_for(tool, arguments, scope=scope), result)

    def get_or_execute(
        self,
        tool: str,
        arguments: Mapping[str, Any],
        fn: Callable[[], Any],
        *,
        scope: str = "",
    ) -> Any:
        cached = self.get(tool, arguments, scope=scope)
        if cached is not None:
            return cached
        result = fn()
        self.set(tool, arguments, result, scope=scope)
        return result

    def invalidate(self, tool: str, arguments: Optional[Mapping[str, Any]] = None, *, scope: str = "") -> None:
        if arguments is None:
            self.clear()
            return
        self._cache.delete(self.key_for(tool, arguments, scope=scope))

    def clear(self) -> None:
        self._cache.clear()

    def size(self) -> int:
        return self._cache.size


class InFlightGuard:
    """
    Prevent duplicate concurrent execution of the same request key.

    ``guard(key, fn)`` runs ``fn`` once; concurrent callers for the same key
    block on the shared future and receive its result instead of re-running.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._futures: Dict[str, "concurrent_future"] = {}  # type: ignore[name-defined]

    def guard(self, key: str, fn: Callable[[], Any]) -> Any:
        import concurrent.futures

        with self._lock:
            existing = self._futures.get(key)
            if existing is not None and not existing.done():
                return existing.result(timeout=None)  # block on the same run

        future = concurrent.futures.Future()
        with self._lock:
            self._futures[key] = future
        try:
            future.set_result(fn())
        except BaseException as exc:  # noqa: BLE001
            future.set_exception(exc)
        finally:
            with self._lock:
                self._futures.pop(key, None)
        return future.result()