"""
Tools :: Discovery :: Finder
============================

Primary discovery coordinator: the entry point for discovery operations.

Runs the pipeline (index candidates -> match -> rank -> filter), applies
namespace/category/visibility filters, serves a bounded cache and emits an
observability record for every request.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .catalog import DiscoveryEntry, ToolCatalog
from .index import DiscoveryIndex
from .matcher import Matcher
from .ranking import Ranker, RankedTool
from .search import SearchEngine, SearchRequest, SearchResult

__all__ = ["DiscoveryRecord", "DiscoveryFinder"]


@dataclass
class DiscoveryRecord:
    """Observability snapshot of one discovery operation."""

    request_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    query: str = ""
    search_type: str = "hybrid"
    candidate_count: int = 0
    ranking_time_ms: float = 0.0
    total_latency_ms: float = 0.0
    selected_tools: List[str] = field(default_factory=list)
    cache_hit: bool = False
    error_status: str = "ok"

    def as_dict(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "query": self.query,
            "search_type": self.search_type,
            "candidate_count": self.candidate_count,
            "ranking_time_ms": self.ranking_time_ms,
            "total_latency_ms": self.total_latency_ms,
            "selected_tools": list(self.selected_tools),
            "cache_hit": self.cache_hit,
            "error_status": self.error_status,
        }


class DiscoveryFinder:
    """Facade over the discovery pipeline with caching and audit records."""

    def __init__(
        self,
        *,
        catalog: Optional[ToolCatalog] = None,
        engine: Optional[SearchEngine] = None,
        cache_size: int = 64,
    ) -> None:
        self.catalog = catalog if catalog is not None else ToolCatalog()
        self.engine = engine if engine is not None else SearchEngine(catalog=self.catalog)
        self._cache: Dict[Tuple[str, ...], Tuple[float, List[RankedTool]]] = {}
        self._cache_size = max(1, int(cache_size))
        self._records: List[DiscoveryRecord] = []

    # -- registration ----------------------------------------------------------- #

    def register(self, entry: DiscoveryEntry) -> DiscoveryEntry:
        self.engine.add(entry)
        self._cache.clear()
        return entry

    def unregister(self, tool_id: str) -> None:
        self.engine.remove(tool_id)
        self._cache.clear()

    # -- pipeline ---------------------------------------------------------------- #

    def find(
        self,
        query: str,
        *,
        search_type: str = "hybrid",
        namespace: str = "",
        category: str = "",
        tags: Optional[Sequence[str]] = None,
        capabilities: Optional[Sequence[str]] = None,
        top_k: int = 5,
        include_hidden: bool = False,
    ) -> List[RankedTool]:
        started = time.perf_counter()
        request = SearchRequest(
            query=query,
            search_type=search_type,
            namespace=namespace,
            category=category,
            tags=list(tags or []),
            capabilities=list(capabilities or []),
            top_k=top_k,
            include_hidden=include_hidden,
        )
        key = (
            query.lower().strip(),
            search_type,
            namespace,
            category,
            tuple(sorted(tags or [])),
            tuple(sorted(capabilities or [])),
            int(top_k),
            bool(include_hidden),
        )
        cache_hit = key in self._cache
        if cache_hit:
            _, cached = self._cache[key]
            results = cached
        else:
            try:
                result = self.engine.search(request)
                results = result.results
            except ValueError as exc:
                record = self._record(request, 0, 0.0, started, [], False, str(exc))
                self._records.append(record)
                return []
            self._cache[key] = (time.time(), results)
            if len(self._cache) > self._cache_size:
                oldest = min(self._cache, key=lambda k: self._cache[k][0])
                del self._cache[oldest]
        record = self._record(
            request,
            len(results),
            round((time.perf_counter() - started) * 1000, 3),
            started,
            [r.entry.tool_id for r in results],
            cache_hit,
            "ok",
        )
        self._records.append(record)
        return results

    def _record(
        self,
        request: SearchRequest,
        candidate_count: int,
        ranking_time_ms: float,
        started: float,
        selected: List[str],
        cache_hit: bool,
        error: str,
    ) -> DiscoveryRecord:
        return DiscoveryRecord(
            request_id=uuid.uuid4().hex,
            query=request.query,
            search_type=request.search_type,
            candidate_count=candidate_count,
            ranking_time_ms=ranking_time_ms,
            total_latency_ms=round((time.perf_counter() - started) * 1000, 3),
            selected_tools=selected,
            cache_hit=cache_hit,
            error_status=error,
        )

    # -- audit ------------------------------------------------------------------- #

    def records(self, limit: int = 50) -> List[DiscoveryRecord]:
        return list(self._records[-max(1, int(limit)):])

    def clear_records(self) -> None:
        self._records.clear()