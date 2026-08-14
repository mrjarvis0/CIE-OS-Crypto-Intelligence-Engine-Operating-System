"""
Tools :: Web :: Search
======================

Web search: query building, local document indexing, ranking and
result normalization. The local index is the deterministic stand-in for
search providers; real backends subclass ``SearchProvider``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

from ..utils.helpers import iso_now
from ..utils.ids import new_id

__all__ = ["SearchResult", "SearchDocument", "QueryBuilder", "WebSearch"]

_WORD_RE = re.compile(r"[a-z0-9]+")


@dataclass
class SearchResult:
    """One normalized search result."""

    url: str
    title: str = ""
    snippet: str = ""
    score: float = 0.0
    source: str = "web"
    published: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "url": self.url,
            "title": self.title,
            "snippet": self.snippet,
            "score": round(self.score, 4),
            "source": self.source,
            "published": self.published,
        }


@dataclass
class SearchDocument:
    """A searchable local document."""

    url: str
    title: str = ""
    content: str = ""
    source: str = "web"
    published: str = ""
    rank: float = 1.0

    def tokens(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for token in _WORD_RE.findall((self.title + " " + self.content).lower()):
            counts[token] = counts.get(token, 0) + 1
        return counts


class QueryBuilder:
    """Builds normalized search queries (token lists, phrase flags)."""

    def build(self, query: str) -> Dict[str, Any]:
        text = query.lower()
        phrases = re.findall(r'"([^"]+)"', text)
        cleaned = re.sub(r'"[^"]*"', " ", text)
        tokens = [t for t in _WORD_RE.findall(cleaned) if len(t) > 1]
        return {
            "original": query,
            "tokens": tokens,
            "phrases": phrases,
            "length": len(tokens),
        }

    def matches(self, tokens: Sequence[str], document_tokens: Mapping[str, int]) -> int:
        return sum(1 for token in tokens if token in document_tokens)


class WebSearch:
    """Local deterministic search engine over registered documents."""

    def __init__(self) -> None:
        self._documents: Dict[str, SearchDocument] = {}
        self.queries = QueryBuilder()

    def index(self, document: SearchDocument) -> None:
        self._documents[document.url] = document

    def index_many(self, documents: Sequence[SearchDocument]) -> None:
        for document in documents:
            self.index(document)

    def remove(self, url: str) -> None:
        self._documents.pop(url, None)

    def search(self, query: str, *, limit: int = 10, source: str = "") -> List[SearchResult]:
        built = self.queries.build(query)
        tokens = built["tokens"]
        results: List[SearchResult] = []
        for document in self._documents.values():
            if source and document.source != source:
                continue
            doc_tokens = document.tokens()
            overlap = self.queries.matches(tokens, doc_tokens)
            if not overlap and not built["phrases"]:
                continue
            title_hits = sum(1 for t in tokens if t in _WORD_RE.findall(document.title.lower()))
            score = overlap * 1.0 + title_hits * 0.5 + document.rank * 0.1
            if any(phrase in document.content.lower() or phrase in document.title.lower() for phrase in built["phrases"]):
                score += 2.0
            snippet = document.content[:160] + ("..." if len(document.content) > 160 else "")
            results.append(
                SearchResult(
                    url=document.url,
                    title=document.title,
                    snippet=snippet,
                    score=round(score, 4),
                    source=document.source,
                    published=document.published,
                )
            )
        results.sort(key=lambda r: r.score, reverse=True)
        return results[: max(1, int(limit))]

    def count(self) -> int:
        return len(self._documents)