"""
Tools :: Marketplace :: Catalog
===============================

Searchable marketplace inventory: categories, capabilities, tags,
authors, publishers, compatibility, versions, downloads and trust.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence

__all__ = ["PackageEntry", "MarketplaceCatalog"]


@dataclass
class PackageEntry:
    """Metadata for one publishable artifact."""

    package_id: str
    name: str
    version: str = "1.0.0"
    description: str = ""
    category: str = "tool"
    capabilities: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    author: str = ""
    publisher: str = ""
    license: str = "MIT"
    homepage: str = ""
    repository: str = ""
    dependencies: List[str] = field(default_factory=list)
    permissions: List[str] = field(default_factory=list)
    runtime_requirements: List[str] = field(default_factory=list)
    checksum: str = ""
    signature: str = ""
    trust_score: float = 0.5
    downloads: int = 0
    state: str = "published"

    def as_dict(self) -> Dict[str, Any]:
        return {
            "package_id": self.package_id,
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "category": self.category,
            "capabilities": list(self.capabilities),
            "tags": list(self.tags),
            "author": self.author,
            "publisher": self.publisher,
            "license": self.license,
            "homepage": self.homepage,
            "repository": self.repository,
            "dependencies": list(self.dependencies),
            "permissions": list(self.permissions),
            "runtime_requirements": list(self.runtime_requirements),
            "checksum": self.checksum,
            "trust_score": self.trust_score,
            "downloads": self.downloads,
            "state": self.state,
        }


class MarketplaceCatalog:
    """Searchable inventory of :class:`PackageEntry` records."""

    def __init__(self) -> None:
        self._by_id: Dict[str, PackageEntry] = {}

    def add(self, entry: PackageEntry) -> PackageEntry:
        self._by_id[entry.package_id] = entry
        return entry

    def upsert_version(self, entry: PackageEntry) -> PackageEntry:
        return self.add(entry)

    def get(self, package_id: str) -> Optional[PackageEntry]:
        return self._by_id.get(package_id)

    def by_name(self, name: str) -> Optional[PackageEntry]:
        return next((e for e in self._by_id.values() if e.name == name), None)

    def search(
        self,
        query: str = "",
        *,
        category: str = "",
        publisher: str = "",
        tags: Optional[Sequence[str]] = None,
        capability: str = "",
        min_trust: float = 0.0,
        state: str = "",
    ) -> List[PackageEntry]:
        query_l = query.lower()
        tag_set = {t.lower() for t in (tags or [])}
        results = []
        for entry in self._by_id.values():
            if state and entry.state != state:
                continue
            if category and entry.category != category:
                continue
            if publisher and entry.publisher != publisher:
                continue
            if capability and capability.lower() not in {c.lower() for c in entry.capabilities}:
                continue
            if tag_set and not (tag_set <= {t.lower() for t in entry.tags}):
                continue
            if entry.trust_score < min_trust:
                continue
            if query_l and not any(
                q in (entry.name + " " + entry.description + " " + " ".join(entry.tags)).lower()
                for q in query_l.split()
            ):
                continue
            results.append(entry)
        results.sort(key=lambda e: (-e.trust_score, -e.downloads, e.name))
        return results

    def by_category(self, category: str) -> List[PackageEntry]:
        return self.search(category=category)

    @property
    def categories(self) -> List[str]:
        return sorted({e.category for e in self._by_id.values()})

    @property
    def publishers(self) -> List[str]:
        return sorted({e.publisher for e in self._by_id.values() if e.publisher})

    def __len__(self) -> int:
        return len(self._by_id)