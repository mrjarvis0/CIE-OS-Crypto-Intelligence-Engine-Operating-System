"""
Tools :: Discovery :: Catalog
=============================

Logical catalog of discoverable tools.

A :class:`DiscoveryEntry` is a lightweight, search-oriented snapshot of a
tool (never the tool itself -- discovery never executes). The catalog is
the searchable inventory the rest of the layer reads from.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Optional, Sequence

__all__ = ["DiscoveryEntry", "ToolCatalog"]


@dataclass
class DiscoveryEntry:
    """Search metadata for one discoverable tool."""

    tool_id: str = ""
    name: str = ""
    description: str = ""
    category: str = "general"
    namespace: str = "default"
    tags: List[str] = field(default_factory=list)
    capabilities: List[str] = field(default_factory=list)
    version: str = "1.0.0"
    author: str = ""
    permissions: List[str] = field(default_factory=list)
    health_status: str = "healthy"
    supported_inputs: List[str] = field(default_factory=list)
    supported_outputs: List[str] = field(default_factory=list)
    usage_frequency: float = 0.0
    success_rate: float = 1.0
    latency_class: str = "fast"
    trust_score: float = 1.0
    policy_priority: float = 0.5
    hidden: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.tool_id:
            self.tool_id = uuid.uuid4().hex

    def as_dict(self) -> Dict[str, Any]:
        return {
            "tool_id": self.tool_id,
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "namespace": self.namespace,
            "tags": list(self.tags),
            "capabilities": list(self.capabilities),
            "version": self.version,
            "author": self.author,
            "permissions": list(self.permissions),
            "health_status": self.health_status,
            "supported_inputs": list(self.supported_inputs),
            "supported_outputs": list(self.supported_outputs),
            "usage_frequency": self.usage_frequency,
            "success_rate": self.success_rate,
            "latency_class": self.latency_class,
            "trust_score": self.trust_score,
            "policy_priority": self.policy_priority,
            "hidden": self.hidden,
        }


class ToolCatalog:
    """Ordered, deduplicated inventory of :class:`DiscoveryEntry` records."""

    def __init__(self, entries: Optional[Iterable[DiscoveryEntry]] = None) -> None:
        self._by_id: Dict[str, DiscoveryEntry] = {}
        self._namespaces: Dict[str, int] = {}
        self._categories: Dict[str, int] = {}
        if entries:
            for entry in entries:
                self.add(entry)

    # -- mutation ------------------------------------------------------------- #

    def add(self, entry: DiscoveryEntry) -> DiscoveryEntry:
        """Register or replace an entry (by tool_id)."""
        self._by_id[entry.tool_id] = entry
        self._namespaces[entry.namespace] = self._namespaces.get(entry.namespace, 0) + 1
        self._categories[entry.category] = self._categories.get(entry.category, 0) + 1
        return entry

    def remove(self, tool_id: str) -> Optional[DiscoveryEntry]:
        entry = self._by_id.pop(tool_id, None)
        if entry is not None:
            self._namespaces[entry.namespace] -= 1
            self._categories[entry.category] -= 1
        return entry

    def update(self, tool_id: str, **fields: Any) -> Optional[DiscoveryEntry]:
        """Patch an entry in place (tags/capabilities replaced wholesale)."""
        entry = self._by_id.get(tool_id)
        if entry is None:
            return None
        for key, value in fields.items():
            if hasattr(entry, key):
                setattr(entry, key, value)
        return entry

    # -- queries --------------------------------------------------------------- #

    def get(self, tool_id: str) -> Optional[DiscoveryEntry]:
        return self._by_id.get(tool_id)

    def by_name(self, name: str) -> Optional[DiscoveryEntry]:
        return next((e for e in self._by_id.values() if e.name == name), None)

    def all(self, *, visible_only: bool = True) -> List[DiscoveryEntry]:
        entries = list(self._by_id.values())
        if visible_only:
            entries = [e for e in entries if not e.hidden]
        return entries

    def by_namespace(self, namespace: str) -> List[DiscoveryEntry]:
        return [e for e in self._by_id.values() if e.namespace == namespace]

    def by_category(self, category: str) -> List[DiscoveryEntry]:
        return [e for e in self._by_id.values() if e.category == category]

    def by_capability(self, capability: str) -> List[DiscoveryEntry]:
        return [e for e in self._by_id.values() if capability in e.capabilities]

    def by_tag(self, tag: str) -> List[DiscoveryEntry]:
        return [e for e in self._by_id.values() if tag in e.tags]

    @property
    def namespaces(self) -> List[str]:
        return sorted(ns for ns, count in self._namespaces.items() if count > 0)

    @property
    def categories(self) -> List[str]:
        return sorted(cat for cat, count in self._categories.items() if count > 0)

    def __len__(self) -> int:
        return len(self._by_id)

    def __iter__(self) -> Iterator[DiscoveryEntry]:
        return iter(self._by_id.values())