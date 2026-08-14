"""
Tools :: Discovery :: Search
============================

Search engine abstraction over the catalog, index, matcher and ranker.

Supported search types: ``keyword``, ``semantic`` (token overlap proxy),
``capability``, ``namespace``, ``tag``, ``prefix`` and ``hybrid``. The
engine stays storage-agnostic: it reads postings from the index and falls
back to a full scan when no index terms match.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set

from .catalog import DiscoveryEntry, ToolCatalog
from .index import DiscoveryIndex, tokenize
from .matcher import Matcher, MatchResult
from .ranking import Ranker, RankedTool

__all__ = ["SearchRequest", "SearchResult", "SearchEngine", "SEARCH_TYPES"]

SEARCH_TYPES = ("keyword", "semantic", "capability", "namespace", "tag", "prefix", "hybrid")


@dataclass
class SearchRequest:
    """One search invocation."""

    query: str
    search_type: str = "hybrid"
    namespace: str = ""
    category: str = ""
    tags: List[str] = field(default_factory=list)
    capabilities: List[str] = field(default_factory=list)
    top_k: int = 5
    include_hidden: bool = False

    def as_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query,
            "search_type": self.search_type,
            "namespace": self.namespace,
            "category": self.category,
            "tags": list(self.tags),
            "capabilities": list(self.capabilities),
            "top_k": self.top_k,
        }


@dataclass
class SearchResult:
    """Outcome of a search request."""

    request: SearchRequest
    results: List[RankedTool] = field(default_factory=list)
    candidate_count: int = 0
    cache_hit: bool = False

    def as_dict(self) -> Dict[str, Any]:
        return {
            "query": self.request.query,
            "search_type": self.request.search_type,
            "candidate_count": self.candidate_count,
            "results": [r.as_dict() for r in self.results],
        }


class SearchEngine:
    """Index-backed search over a catalog."""

    def __init__(
        self,
        catalog: Optional[ToolCatalog] = None,
        *,
        index: Optional[DiscoveryIndex] = None,
        matcher: Optional[Matcher] = None,
        ranker: Optional[Ranker] = None,
    ) -> None:
        self.catalog = catalog if catalog is not None else ToolCatalog()
        self.index = index if index is not None else DiscoveryIndex()
        self.matcher = matcher if matcher is not None else Matcher()
        self.ranker = ranker if ranker is not None else Ranker()

    # -- maintenance ------------------------------------------------------------ #

    def add(self, entry: DiscoveryEntry) -> None:
        self.catalog.add(entry)
        self.index.add(entry)

    def remove(self, tool_id: str) -> None:
        self.catalog.remove(tool_id)
        self.index.remove(tool_id)

    # -- candidate selection ---------------------------------------------------- #

    def _index_candidates(self, request: SearchRequest) -> Set[str]:
        ids: Set[str] = set()
        tokens = tokenize(request.query)
        if request.search_type in ("keyword", "hybrid", "semantic"):
            for token in tokens[:4]:
                ids |= self.index.postings("name", token) | self.index.postings("tag", token)
                ids |= self.index.postings("capability", token)
        if request.search_type == "capability":
            for cap in request.capabilities or tokens:
                ids |= self.index.postings("capability", cap)
        if request.search_type == "namespace":
            ids |= self.index.postings("namespace", request.namespace or request.query)
        if request.search_type == "tag":
            for tag in request.tags or tokens:
                ids |= self.index.postings("tag", tag)
        if request.search_type == "prefix":
            ids |= self.index.prefix("name", tokens[0]) if tokens else set()
        return ids

    def search(self, request: SearchRequest) -> SearchResult:
        if request.search_type not in SEARCH_TYPES:
            raise ValueError(f"unknown search type {request.search_type!r}")

        ids = self._index_candidates(request)
        entries: List[DiscoveryEntry] = []
        if ids:
            for tool_id in ids:
                entry = self.catalog.get(tool_id)
                if entry is not None and (request.include_hidden or not entry.hidden):
                    entries.append(entry)
        else:
            entries = self.catalog.all(visible_only=not request.include_hidden)

        candidates = [e for e in entries if not request.namespace or e.namespace == request.namespace]
        if request.category:
            candidates = [e for e in candidates if e.category == request.category]
        if request.capabilities:
            candidates = [e for e in candidates if set(request.capabilities) <= set(e.capabilities)]

        matches = self.matcher.matches(candidates, request.query, namespace=request.namespace)
        ranked = self.ranker.rank(matches, top_k=request.top_k)
        return SearchResult(request=request, results=ranked, candidate_count=len(matches))