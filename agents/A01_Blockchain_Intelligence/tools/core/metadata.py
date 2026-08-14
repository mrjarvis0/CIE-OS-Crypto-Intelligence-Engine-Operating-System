"""
Tools :: Core :: Metadata
=========================

Runtime metadata store describing every registered tool.

Layer above the schema's immutable ToolMetadata: adds a live key/value
descriptor the registry keeps in sync with a tool's lifecycle state, plus
a small query surface (by name, capability, tag).
"""

from __future__ import annotations

import threading
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from ..schemas.metadata import ToolMetadata, metadata_dict
from .exceptions import ToolNotFoundError

__all__ = ["MetadataStore", "ToolMetadata"]


class MetadataStore:
    """
    Thread-safe, in-memory metadata index for tools.

    ``register`` stores a schema-level descriptor; ``update`` patches fields;
    ``get`` returns the latest view. Queries are pure and never mutate.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._by_name: Dict[str, ToolMetadata] = {}

    def register(self, entry: ToolMetadata) -> None:
        with self._lock:
            if not entry.name:
                raise ValueError("metadata name is required")
            self._by_name[entry.name] = entry

    def update(self, name: str, **fields: Any) -> ToolMetadata:
        with self._lock:
            current = self._by_name.get(name)
            if current is None:
                raise ToolNotFoundError(name)
            updated = current.with_extra(**fields)
            self._by_name[name] = updated
            return updated

    def get(self, name: str) -> Optional[ToolMetadata]:
        with self._lock:
            return self._by_name.get(name)

    def __getitem__(self, name: str) -> ToolMetadata:
        meta = self.get(name)
        if meta is None:
            raise ToolNotFoundError(name)
        return meta

    def __contains__(self, name: str) -> bool:
        return self.get(name) is not None

    def list(self) -> Sequence[ToolMetadata]:
        with self._lock:
            return tuple(sorted(self._by_name.values(), key=lambda m: m.name))

    def count(self) -> int:
        with self._lock:
            return len(self._by_name)

    def remove(self, name: str) -> bool:
        with self._lock:
            return self._by_name.pop(name, None) is not None

    def search(self, *, name: str = "", capability: str = "", tag: str = "") -> Sequence[ToolMetadata]:
        """Filter by optional name/capability/tag substrings."""
        results: List[ToolMetadata] = []
        for meta in self.list():
            if name and name not in meta.name:
                continue
            if capability and capability not in getattr(meta, "capabilities", []):
                continue
            if tag and tag not in getattr(meta, "tags", []):
                continue
            results.append(meta)
        return results

    def as_dict(self) -> Mapping[str, Mapping[str, object]]:
        return {meta.name: metadata_dict(meta) for meta in self.list()}