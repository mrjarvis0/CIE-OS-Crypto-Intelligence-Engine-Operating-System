"""
Tools :: Discovery Layer
========================

Intelligent search and capability discovery over the tool catalog.

The discovery layer never executes tools: it only determines which tools
are the best candidates for a request. It is the bridge between the Tool
Registry and the Planning Engine -- returning the top-N ranked candidates
instead of exposing the whole registry.

Pipeline: ``Finder -> (Index -> Matcher -> Ranker) -> SearchEngine``.

Two hard rules (mirroring the tools tree):

1. Discovery is read-only: catalog mutation goes through explicit
   register/unregister APIs, never through search.
2. All results are normalized dict/dataclass outputs; the layer never
   talks to adapters or external services.
"""

from __future__ import annotations

import abc
import logging

__all__ = [
    "DiscoveryError",
    "DiscoveryValidationError",
    "DiscoveryIndexError",
    "DiscoveryNotFoundError",
    "DiscoveryEntry",
    "ToolCatalog",
    "DiscoveryIndex",
    "MatchResult",
    "Matcher",
    "RankedTool",
    "Ranker",
    "SearchRequest",
    "SearchResult",
    "SearchEngine",
    "DiscoveryRecord",
    "DiscoveryFinder",
    "SEARCH_TYPES",
]

logger = logging.getLogger(__name__)


class DiscoveryError(Exception):
    """Base class for every error raised by the discovery layer."""


class DiscoveryValidationError(DiscoveryError):
    """A discovery request failed validation."""


class DiscoveryIndexError(DiscoveryError):
    """Index maintenance failed."""


class DiscoveryNotFoundError(DiscoveryError):
    """The requested entry does not exist."""


from .catalog import DiscoveryEntry, ToolCatalog  # noqa: E402
from .index import DiscoveryIndex  # noqa: E402
from .matcher import MatchResult, Matcher  # noqa: E402
from .ranking import RankedTool, Ranker  # noqa: E402
from .search import SearchEngine, SearchRequest, SearchResult, SEARCH_TYPES  # noqa: E402
from .finder import DiscoveryRecord, DiscoveryFinder  # noqa: E402