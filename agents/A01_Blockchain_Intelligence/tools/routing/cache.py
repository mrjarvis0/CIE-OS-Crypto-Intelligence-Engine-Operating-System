"""
Tools :: Routing :: Cache
=========================

Caches routing decisions: frequently used routes, capability lookups,
route scores and policy evaluations. Reduces repeated routing
computation.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

__all__ = ["RouteCache", "CacheEntry"]


@dataclass
class CacheEntry:
    """One cached routing result."""

    key: str
    value: Any
    created_at: float = field(default_factory=time.time)
    ttl_s: float = 60.0

    def expired(self) -> bool:
        return time.time() - self.created_at > self.ttl_s


class RouteCache:
    """TTL-bounded, capacity-limited cache for routing decisions."""

    def __init__(self, *, capacity: int = 256, default_ttl_s: float = 60.0) -> None:
        self.capacity = max(1, int(capacity))
        self.default_ttl_s = default_ttl_s
        self._entries: Dict[str, CacheEntry] = {}
        self._hits = 0
        self._misses = 0

    def key_for(self, *parts: Any) -> str:
        return "|".join(str(part).strip().lower() for part in parts if part is not None)

    def get(self, key: str) -> Optional[Any]:
        entry = self._entries.get(key)
        if entry is None:
            self._misses += 1
            return None
        if entry.expired():
            self._entries.pop(key, None)
            self._misses += 1
            return None
        self._hits += 1
        return entry.value

    def set(self, key: str, value: Any, ttl_s: Optional[float] = None) -> None:
        if key in self._entries:
            self._entries[key].value = value
            self._entries[key].created_at = time.time()
            self._entries[key].ttl_s = ttl_s if ttl_s is not None else self.default_ttl_s
            return
        self._entries[key] = CacheEntry(key=key, value=value, ttl_s=ttl_s if ttl_s is not None else self.default_ttl_s)
        if len(self._entries) > self.capacity:
            oldest = min(self._entries, key=lambda k: self._entries[k].created_at)
            self._entries.pop(oldest, None)

    def get_or_set(self, key: str, factory: Any, ttl_s: Optional[float] = None) -> Any:
        cached = self.get(key)
        if cached is not None:
            return cached
        value = factory()
        self.set(key, value, ttl_s)
        return value

    def invalidate(self, key: str) -> None:
        self._entries.pop(key, None)

    def clear(self) -> None:
        self._entries.clear()

    def size(self) -> int:
        self._purge()
        return len(self._entries)

    def stats(self) -> Dict[str, Any]:
        return {"hits": self._hits, "misses": self._misses, "size": self.size(), "capacity": self.capacity}

    def _purge(self) -> None:
        for key, entry in list(self._entries.items()):
            if entry.expired():
                self._entries.pop(key, None)