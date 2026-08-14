"""
Tools :: Marketplace :: Client
==============================

Main interface to remote marketplace services: connect, authenticate,
search, fetch metadata, download and check updates.

A local client serves an in-memory catalog so everything works offline.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

from .catalog import MarketplaceCatalog, PackageEntry

__all__ = ["MarketplaceClient", "LocalMarketplaceClient"]


class MarketplaceClient:
    """API client contract for a marketplace service."""

    provider = "marketplace"

    def __init__(self, *, base_url: str = "https://marketplace.local", token: str = "") -> None:
        self.base_url = base_url
        self.token = token

    # -- provider hooks -------------------------------------------------------- #

    def _search(self, query: str, **filters: Any) -> List[PackageEntry]:
        raise NotImplementedError

    def _package(self, package_id: str) -> Optional[PackageEntry]:
        raise NotImplementedError

    def _metadata(self, package_id: str) -> Mapping[str, Any]:
        raise NotImplementedError

    def _latest(self, package_id: str) -> Optional[PackageEntry]:
        raise NotImplementedError

    # -- capabilities ----------------------------------------------------------- #

    def search(self, query: str = "", **filters: Any) -> List[PackageEntry]:
        return self._search(query, **filters)

    def package(self, package_id: str) -> PackageEntry:
        entry = self._package(package_id)
        if entry is None:
            raise KeyError(f"package {package_id!r} not found")
        return entry

    def metadata(self, package_id: str) -> Mapping[str, Any]:
        return self._metadata(package_id)

    def latest_version(self, package_id: str) -> Optional[PackageEntry]:
        return self._latest(package_id)


class LocalMarketplaceClient(MarketplaceClient):
    """Offline marketplace backed by a :class:`MarketplaceCatalog`."""

    provider = "local-marketplace"

    def __init__(self, *, catalog: Optional[MarketplaceCatalog] = None, base_url: str = "https://marketplace.local", token: str = "") -> None:
        super().__init__(base_url=base_url, token=token)
        self.catalog = catalog if catalog is not None else MarketplaceCatalog()

    def publish(self, entry: PackageEntry) -> PackageEntry:
        return self.catalog.add(entry)

    def _search(self, query: str, **filters: Any) -> List[PackageEntry]:
        return self.catalog.search(query, **filters)

    def _package(self, package_id: str) -> Optional[PackageEntry]:
        return self.catalog.get(package_id)

    def _metadata(self, package_id: str) -> Mapping[str, Any]:
        entry = self.package(package_id)
        return {"package_id": entry.package_id, "name": entry.name, "version": entry.version, "downloads": entry.downloads, "trust_score": entry.trust_score}

    def _latest(self, package_id: str) -> Optional[PackageEntry]:
        return self.catalog.get(package_id)