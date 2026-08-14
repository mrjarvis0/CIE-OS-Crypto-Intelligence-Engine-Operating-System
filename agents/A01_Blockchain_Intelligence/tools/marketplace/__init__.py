"""
Tools :: Marketplace Layer
==========================

Trusted distribution and ecosystem platform: secure discovery,
installation, verification, updating, publishing and lifecycle management
of tools, plugins, skills, agents and adapters.

Unlike the local Registry, the marketplace manages the global catalog of
available artifacts. The marketplace never executes tools.

A :class:`Marketplace` facade wires catalog, client, downloader, verifier,
installer and publisher into one entry point.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Mapping, Optional, Sequence

__all__ = [
    "MarketplaceError",
    "PackageEntry",
    "MarketplaceCatalog",
    "MarketplaceClient",
    "LocalMarketplaceClient",
    "DownloadResult",
    "Downloader",
    "LocalDownloader",
    "sha256_hex",
    "VerificationReport",
    "Verifier",
    "InstallResult",
    "Installer",
    "PublishResult",
    "Publisher",
    "UpdateInfo",
    "UpdateManager",
    "compare_versions",
    "Rating",
    "RatingsStore",
    "Review",
    "ReviewsStore",
    "REVIEW_KINDS",
    "Marketplace",
]

logger = logging.getLogger(__name__)


class MarketplaceError(Exception):
    """Base class for every error raised by the marketplace layer."""


from .catalog import PackageEntry, MarketplaceCatalog  # noqa: E402
from .client import MarketplaceClient, LocalMarketplaceClient  # noqa: E402
from .downloader import DownloadResult, Downloader, LocalDownloader, sha256_hex  # noqa: E402
from .verifier import VerificationReport, Verifier  # noqa: E402
from .installer import InstallResult, Installer  # noqa: E402
from .publisher import PublishResult, Publisher  # noqa: E402
from .updates import UpdateInfo, UpdateManager, compare_versions  # noqa: E402
from .ratings import Rating, RatingsStore  # noqa: E402
from .reviews import Review, ReviewsStore, REVIEW_KINDS  # noqa: E402


class Marketplace:
    """Facade over the marketplace pipeline."""

    def __init__(
        self,
        *,
        catalog: Optional[MarketplaceCatalog] = None,
        client: Optional[MarketplaceClient] = None,
        downloader: Optional[Downloader] = None,
        verifier: Optional[Verifier] = None,
        installer: Optional[Installer] = None,
        publisher: Optional[Publisher] = None,
        updates: Optional[UpdateManager] = None,
    ) -> None:
        self.catalog = catalog if catalog is not None else MarketplaceCatalog()
        self.client = client if client is not None else LocalMarketplaceClient(catalog=self.catalog)
        self.downloader = downloader if downloader is not None else LocalDownloader()
        self.verifier = verifier if verifier is not None else Verifier()
        self.installer = installer if installer is not None else Installer(downloader=self.downloader, verifier=self.verifier)
        self.publisher = publisher if publisher is not None else Publisher()
        self.updates = updates if updates is not None else UpdateManager()

    def search(self, query: str = "", **filters: Any) -> Sequence[PackageEntry]:
        return self.client.search(query, **filters)

    def publish(self, entry: PackageEntry, **kwargs: Any) -> PublishResult:
        return self.publisher.publish(entry, **kwargs)

    def install(self, entry: PackageEntry, **kwargs: Any) -> InstallResult:
        return self.installer.install(entry, **kwargs)