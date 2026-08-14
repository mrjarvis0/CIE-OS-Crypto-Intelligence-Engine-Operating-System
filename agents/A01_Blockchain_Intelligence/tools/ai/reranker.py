"""
Tools :: AI :: Reranker
=======================

Improve retrieval quality by re-scoring candidate results.

Pipeline: retrieve -> score -> re-rank -> return best results. The local
implementation scores candidates with lexical overlap (token Jaccard with
an IDF-style boost); real cross-encoder providers plug in behind the same
:class:`Reranker` interface.
"""

from __future__ import annotations

import math
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Iterable, List, Mapping, Optional, Sequence

from . import AIUsage, AIValidationError, AIResponse, BaseAIModel

__all__ = ["RerankItem", "RerankResult", "Reranker", "LocalReranker", "jaccard_score", "overlap_score"]


@dataclass
class RerankItem:
    """One candidate with its (re-)score and rank."""

    text: str
    score: float = 0.0
    rank: int = 0
    id: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Mapping[str, Any]:
        return {"text": self.text, "score": self.score, "rank": self.rank, "id": self.id, "metadata": dict(self.metadata)}


@dataclass
class RerankResult:
    """Ordered list of re-ranked items."""

    items: List[RerankItem] = field(default_factory=list)

    def best(self) -> Optional[RerankItem]:
        return self.items[0] if self.items else None

    def as_dict(self) -> Mapping[str, Any]:
        return {"items": [item.as_dict() for item in self.items]}


def _tokens(text: str) -> set:
    return set(re.findall(r"[a-z0-9_]+", text.lower()))


def overlap_score(query: str, document: str) -> float:
    """Fraction of query tokens present in the document (0..1)."""
    query_tokens = _tokens(query)
    if not query_tokens:
        return 0.0
    doc_tokens = _tokens(document)
    return len(query_tokens & doc_tokens) / len(query_tokens)


def jaccard_score(query: str, document: str) -> float:
    """Jaccard similarity between query and document token sets."""
    query_tokens = _tokens(query)
    doc_tokens = _tokens(document)
    union = query_tokens | doc_tokens
    if not union:
        return 0.0
    return len(query_tokens & doc_tokens) / len(union)


class Reranker(BaseAIModel):
    """Base class for re-ranking providers."""

    capability = "reranker"

    def __init__(self, *, model: str = "local", top_k: int = 5, logger: Any = None) -> None:
        super().__init__(logger=logger)
        self._model = model or "local"
        self._top_k = top_k

    def _score(self, query: str, document: str) -> float:
        raise NotImplementedError

    def rerank(self, query: str, documents: Sequence[str], *, top_k: Optional[int] = None) -> RerankResult:
        if not query:
            raise AIValidationError("empty query", provider=self.provider)
        k = top_k or self._top_k
        scored = [RerankItem(text=doc, score=self._score(query, doc)) for doc in documents]
        scored.sort(key=lambda item: item.score, reverse=True)
        for rank, item in enumerate(scored[:k], start=1):
            item.rank = rank
        return RerankResult(items=scored[:k])

    def execute(self, request: AIRequest) -> AIResponse:
        started = time.monotonic()
        params = getattr(request, "params", None) or {}
        query = str(params.get("query", ""))
        documents = list(params.get("documents") or ())
        if not query or not documents:
            raise AIValidationError("rerank requires query and documents", provider=self.provider)
        result = self.rerank(query, documents)
        return self.normalize(
            True,
            data=result.as_dict(),
            request_id=getattr(request, "request_id", ""),
            duration_ms=(time.monotonic() - started) * 1000.0,
            usage=AIUsage(prompt_tokens=len(query.split()) + sum(len(d.split()) for d in documents)),
        )


class LocalReranker(Reranker):
    """Lexical re-ranker (token overlap + IDF-style boost)."""

    provider = "local"

    def _score(self, query: str, document: str) -> float:
        overlap = overlap_score(query, document)
        if overlap == 0.0:
            return 0.0
        # Rare query tokens (longer/less frequent) get a mild boost.
        rarity = sum(1.0 for token in _tokens(query) if len(token) >= 6) / max(len(_tokens(query)), 1)
        return overlap * (1.0 + 0.25 * rarity)